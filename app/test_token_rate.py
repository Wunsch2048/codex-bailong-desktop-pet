import unittest
from datetime import datetime,timezone,timedelta
from token_rate import RateStore,sample,completion,capabilities,MetadataCollector

class RateTests(unittest.TestCase):
    def setUp(self):self.store=RateStore(':memory:');self.t=datetime(2026,10,30,12,tzinfo=timezone.utc).timestamp()
    def tearDown(self):self.store.close()
    def record(self,turn='1',out=100,ms=1000,**kw):
        return sample(source='local',session='s',turn=turn,stamp=self.t,input_tokens=200,output_tokens=out,generation_ms=ms,timing_source='generation_duration',**kw)
    def rows(self):return self.store.query(self.t-1,self.t+1,tz=timezone.utc)['bins']
    def test_weighted_average_not_mean_of_rates(self):
        self.store.put(self.record(out=100,ms=1000));self.store.put(self.record('2',out=900,ms=3000))
        self.assertEqual(self.rows()[0]['tokens_per_second'],250)
    def test_task_median_is_per_turn_and_does_not_replace_weighted_average(self):
        self.store.put(self.record('a',out=100,ms=None,task_ms=1000))
        self.store.put(self.record('b',out=900,ms=None,task_ms=3000))
        row=self.rows()[0]
        self.assertEqual(row['task_tokens_per_second'],250)
        self.assertEqual(row['task_median_tokens_per_second'],200)
        self.assertEqual(row['task_samples'],2)
        self.assertNotIn('_task_rates',row)
    def test_median_keeps_true_zero_and_excludes_missing_or_zero_duration(self):
        for name,out,task in [('zero',0,1000),('middle',20,1000),('high',100,1000),('unknown',1000,None),('invalid',1000,0)]:
            self.store.put(self.record(name,out=out,ms=None,task_ms=task))
        row=self.rows()[0]
        self.assertEqual(row['task_median_tokens_per_second'],20)
        self.assertEqual(row['task_samples'],3);self.assertEqual(row['samples'],5)
        from rate_index import snapshot
        hour=datetime.fromtimestamp(self.t).hour;item=snapshot(self.store.db,self.t+1)['today'][hour]
        self.assertEqual(item['median_rate'],20);self.assertEqual(item['valid_samples'],3)
    def test_slow_outlier_changes_mean_without_hiding_typical_turn_median(self):
        for i in range(9):self.store.put(self.record(str(i),out=100,ms=None,task_ms=1000))
        self.store.put(self.record('slow',out=100,ms=None,task_ms=100_000))
        row=self.rows()[0]
        self.assertEqual(row['task_median_tokens_per_second'],100)
        self.assertAlmostEqual(row['task_tokens_per_second'],1000/109)
    def test_median_query_does_not_write_or_change_stored_samples(self):
        self.store.put(self.record(ms=None,task_ms=None))
        before=list(self.store.db.execute('SELECT * FROM rate_samples'));changes=self.store.db.total_changes
        row=self.rows()[0];self.assertIsNone(row['task_median_tokens_per_second'])
        self.assertEqual(self.store.db.total_changes,changes)
        self.assertEqual(list(self.store.db.execute('SELECT * FROM rate_samples')),before)
    def test_restart_duplicate_and_conflicting_counts(self):
        self.assertTrue(self.store.put(self.record()));self.assertFalse(self.store.put(self.record()))
        with self.assertRaises(ValueError):self.store.put(self.record(out=200))
        self.assertEqual(self.rows()[0]['output_tokens'],100)
    def test_turn_elapsed_and_ttft_do_not_masquerade_as_generation(self):
        r=completion(dict(type='task_complete',turn_id='1',duration_ms=100000,time_to_first_token_ms=1000,last_agent_message='private'),dict(input_tokens=100,output_tokens=200,reasoning_output_tokens=50),source='local',session='s',stamp=self.t)
        self.store.put(r);g=self.rows()[0]
        self.assertIsNone(g['tokens_per_second']);self.assertEqual(g['output_tokens'],200)
        self.assertEqual(g['task_tokens_per_second'],2);self.assertNotIn('private',repr(r))
    def test_no_data_unknown_not_zero_and_partial_coverage(self):
        self.assertEqual(self.rows(),[])
        self.store.put(self.record());self.store.put(self.record('2',ms=None))
        self.assertEqual(self.rows()[0]['coverage'],.5)
    def test_hover_counts_only_turns_used_by_task_average_including_true_zero(self):
        self.store.put(self.record('missing',out=200,ms=None,task_ms=None))
        self.store.put(self.record('zero-duration',out=200,ms=None,task_ms=0))
        self.store.put(self.record('true-zero',out=0,ms=None,task_ms=1000))
        row=self.rows()[0]
        self.assertEqual(row['samples'],3);self.assertEqual(row['task_samples'],1)
        self.assertEqual(row['task_tokens_per_second'],0)
        from rate_index import snapshot
        item=snapshot(self.store.db,self.t+1)['today'][datetime.fromtimestamp(self.t).hour]
        self.assertEqual(item['valid_samples'],1);self.assertEqual(item['samples'],3)
    def test_source_isolation_and_reasoning_not_added_again(self):
        r=self.record(reasoning_tokens=40);self.store.put(r);r=dict(r,source='wsl');self.store.put(r)
        self.assertEqual(self.rows()[0]['output_tokens'],200)
    def test_invalid_numbers_and_zero_duration(self):
        for v in (True,float('nan'),-1):
            with self.assertRaises(ValueError):self.record(ms=v)
        self.assertIsNone(self.record(ms=0)['generation_ms'])
    def test_day_and_hour_use_local_completion_time(self):
        self.store.put(self.record());tz=timezone(timedelta(hours=13))
        self.assertEqual(self.store.query(self.t-1,self.t+1,tz=tz)['bins'][0]['key'],'2026-10-31')
        self.assertEqual(self.store.query(self.t-1,self.t+1,tz=tz,bucket='hour')['bins'][0]['key'],'2026-10-31T01+1300')
    def test_liveness_does_not_claim_network_is_healthy(self):
        self.assertEqual(capabilities(connected=True,last_event=1,now=40)['local_stream'],'stale')
        self.assertEqual(capabilities(connected=True,last_event=1,now=2)['network'],'not_measured')
    def test_metadata_collector_turn_delta_and_late_attachment(self):
        c=MetadataCollector(self.store)
        def feed(payload):return c.ingest('local','s',payload,self.t)
        feed(dict(type='task_started',turn_id='late'))
        usage=lambda n:dict(type='token_count',info=dict(total_token_usage=dict(input_tokens=n,output_tokens=n,reasoning_output_tokens=0)))
        feed(usage(1000))
        self.assertEqual(feed(dict(type='task_complete',turn_id='late'))['reason'],'missing_turn_baseline')
        feed(dict(type='task_started',turn_id='next'));feed(usage(1050))
        self.assertTrue(feed(dict(type='task_complete',turn_id='next',duration_ms=1000))['recorded'])
        self.assertEqual(self.rows()[0]['output_tokens'],50)

if __name__=='__main__':unittest.main()
