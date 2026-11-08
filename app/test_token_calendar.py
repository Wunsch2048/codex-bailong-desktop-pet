import calendar,json,sqlite3,tempfile,unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from token_calendar import TokenUsageIndex,month_bounds

def token(day,total,**fields):
    return {'timestamp':datetime(2026,10,day,12).astimezone().isoformat(),'type':'event_msg',
            'payload':{'type':'token_count','info':{'total_token_usage':{'total_tokens':total,**fields}}}}

class TokenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);(self.home/'sessions').mkdir()
        self.path=self.home/'sessions/rollout-test.jsonl';self.cache=self.home/'usage.sqlite3';self.index=TokenUsageIndex(self.cache,self.home)
        self.now=datetime(2026,10,18,12).timestamp()
    def tearDown(self):self.temp.cleanup()
    def write(self,events,mode='w'):
        with self.path.open(mode,encoding='utf-8') as f:
            for event in events:f.write(json.dumps(event)+'\n')
    def poll(self):return self.index.poll(self.now)
    def test_cumulative_deltas_not_sum_of_snapshots_or_cached_tokens(self):
        self.write([token(1,120,input_tokens=100,cached_input_tokens=80,output_tokens=20),token(1,120),token(2,250)])
        result=self.poll();self.assertEqual(result['total'],250);self.assertEqual(result['days']['2026-10-01'],120);self.assertEqual(result['days']['2026-10-02'],130)
        self.assertEqual(len(result['days']),31)
    def test_paginated_segment_books_only_new_usage_and_repairs_old_index(self):
        self.write([token(1,1_283_258_294,input_tokens=1_278_519_963,output_tokens=4_738_331)])
        self.poll()
        self.path=self.home/'sessions/rollout-continued.jsonl'
        header=dict(type='session_meta',payload=dict(id='thread',history_base={'thread_id':'thread'}))
        event=token(2,1_283_434_115,input_tokens=1_278_695_526,output_tokens=4_738_589)
        event['payload']['info']['last_token_usage']=dict(total_tokens=175_821,input_tokens=175_563,output_tokens=258,cached_input_tokens=170_000)
        self.write([header,event,token(2,1_283_434_215,input_tokens=1_278_695_626,output_tokens=4_738_589)])
        result=self.poll();self.assertEqual(result['days']['2026-10-02'],175_921)
        with closing(self.index.connect()) as db,db:
            from token_analytics import usage_fingerprint
            key=usage_fingerprint(event,1_283_434_115,event['payload']['info']['total_token_usage'])
            db.execute('UPDATE usage SET tokens=1283434115 WHERE fingerprint=?',(key,))
            db.execute('UPDATE quota_workload_events SET tokens=1283434115 WHERE fingerprint=?',(key,))
            db.execute('DELETE FROM token_segment_repairs')
        restarted=TokenUsageIndex(self.cache,self.home)
        for _ in range(2):
            result=restarted.poll(self.now)
            self.assertEqual(result['days']['2026-10-01'],1_283_258_294)
            self.assertEqual(result['days']['2026-10-02'],175_921)
        with closing(restarted.connect()) as db:
            self.assertEqual(db.execute('SELECT tokens,cached FROM quota_workload_events WHERE fingerprint=?',(key,)).fetchone(),(175_821,170_000))

    def test_repeated_poll_restart_append_and_partial_record(self):
        self.write([token(1,100)]);self.assertEqual(self.poll()['total'],100)
        self.assertEqual(TokenUsageIndex(self.cache,self.home).poll(self.now)['total'],100)
        line=json.dumps(token(2,150))
        with self.path.open('a',encoding='utf-8') as f:f.write(line[:30])
        self.assertEqual(self.poll()['total'],100)
        with self.path.open('a',encoding='utf-8') as f:f.write(line[30:]+'\n')
        self.assertEqual(self.poll()['total'],150)
    def test_fork_duplicate_and_move_to_archive_do_not_double_count(self):
        self.write([token(1,100),token(2,150)]);self.poll()
        clone=self.home/'sessions/rollout-fork.jsonl';clone.write_bytes(self.path.read_bytes())
        with clone.open('a',encoding='utf-8') as f:f.write(json.dumps(token(3,190))+'\n')
        self.assertEqual(self.poll()['total'],190)
        (self.home/'archived_sessions').mkdir();self.path.rename(self.home/'archived_sessions'/self.path.name)
        self.assertEqual(self.poll()['total'],190)
    def test_restart_after_non_token_tail_does_not_mark_valid_log_restricted(self):
        self.write([token(1,100)])
        self.assertFalse(self.poll()['partial'])
        # A real session continues with completion/progress events while no new
        # token counter is needed. A restarted reader resumes at the old offset.
        self.write([dict(type='event_msg',payload=dict(type='task_complete'))],'a')
        restarted=TokenUsageIndex(self.cache,self.home)
        for _ in range(2):
            result=restarted.poll(self.now)
            self.assertFalse(result['partial'])
            self.assertFalse(result['format_unknown'])
            self.assertEqual(result['readable_files'],1)
            self.assertEqual(result['all_total'],100)
    def test_month_boundary_excludes_old_cumulative_baseline(self):
        old=token(1,100);old['timestamp']=datetime(2026,9,30,23,59).astimezone().isoformat()
        self.write([old,token(1,160)]);self.assertEqual(self.poll()['total'],60)
        start,end=month_bounds(datetime(2028,2,3).timestamp());self.assertEqual((end-start).days,29)
    def test_temporarily_unknown_header_can_recover_at_the_same_saved_offset(self):
        unknown=json.dumps(dict(type='future_kind',payload={}))
        known=json.dumps(dict(type='session_meta',payload=dict(id='fixture')))
        width=max(len(unknown),len(known))
        self.path.write_text(unknown.ljust(width)+'\n',encoding='utf-8')
        self.assertTrue(self.poll()['format_unknown'])
        self.path.write_text(known.ljust(width)+'\n',encoding='utf-8')
        result=self.poll()
        self.assertFalse(result['partial'])
        self.assertFalse(result['format_unknown'])
    def test_counter_replay_and_truncation_do_not_inflate(self):
        self.write([token(1,150),token(2,120),token(3,180)]);self.assertEqual(self.poll()['total'],180)
        self.write([token(1,150)]);self.assertEqual(self.poll()['total'],180)
        self.write([token(3,180),token(4,220)],'a');self.assertEqual(self.poll()['total'],220)
    def test_only_counters_persist_and_bad_events_ignored(self):
        self.write([{'type':'response_item','payload':{'text':'PRIVATE_DIALOGUE_NEVER_CACHE'}},token(1,True),token(1,-10),token(1,100)])
        self.assertEqual(self.poll()['total'],100)
        with closing(sqlite3.connect(self.cache)) as db:self.assertNotIn('PRIVATE_DIALOGUE_NEVER_CACHE','\n'.join(db.iterdump()))
    def test_input_output_fallback_does_not_add_cache_or_reasoning_again(self):
        self.write([token(1,None,input_tokens=100,cached_input_tokens=80,output_tokens=20,reasoning_output_tokens=10)])
        self.assertEqual(self.poll()['total'],120)
    def test_deleted_log_keeps_previously_observed_usage(self):
        self.write([token(1,100)]);self.poll();self.path.unlink();self.assertEqual(self.poll()['total'],100)
    def test_future_dates_stay_empty_until_their_time_arrives(self):
        self.write([token(1,100),token(20,300)]);result=self.poll()
        self.assertEqual(result['total'],100);self.assertEqual(result['days']['2026-10-20'],0)
        self.assertEqual(self.index.poll(datetime(2026,10,21).timestamp())['total'],300)
    def test_all_history_and_calendar_day_hours_survive_existing_cache(self):
        a=token(1,80);a['timestamp']=datetime(2026,9,30,23,55).astimezone().isoformat()
        b=token(18,100);b['timestamp']=datetime(2026,10,18,0,10).astimezone().isoformat()
        c=token(18,150);c['timestamp']=datetime(2026,10,18,3,25).astimezone().isoformat()
        d=token(18,190);d['timestamp']=datetime(2026,10,18,14,0).astimezone().isoformat()
        self.write([a,b,c,d]);r=self.poll()
        self.assertEqual(r['all_total'],150);self.assertEqual(r['history_start'],'2026-09-30')
        self.assertEqual(r['total'],70);self.assertEqual(len(r['hours']),24)
        self.assertEqual(r['hours'][0],20);self.assertEqual(r['hours'][3],50);self.assertEqual(r['hours'][14],0)
        self.assertEqual(sum(r['hours']),r['days'][r['today']])
        self.path.unlink();self.assertEqual(self.index.poll(self.now)['hours'],r['hours'])

    def test_locked_legacy_database_is_retried_after_lock_releases(self):
        from token_analytics import migrate
        with closing(sqlite3.connect(self.cache)) as old,old:
            old.execute('CREATE TABLE files(path TEXT PRIMARY KEY,offset INTEGER,highwater INTEGER)')
            old.execute('CREATE TABLE usage(fingerprint TEXT PRIMARY KEY,stamp REAL,tokens INTEGER)')
            migrate(old)
            old.execute('INSERT INTO files(path,offset,highwater,session) VALUES(?,0,0,?)',(str(self.path),'legacy-session'))
            old.execute('INSERT INTO usage(fingerprint,stamp,tokens,session) VALUES(?,?,?,?)',('legacy',self.now,123,'legacy-session'))
        lock=sqlite3.connect(self.cache,timeout=0)
        try:
            lock.execute('BEGIN EXCLUSIVE')
            with closing(self.index.connect()) as db:
                self.assertFalse(db.execute('SELECT 1 FROM source_identity').fetchone())
                self.assertTrue(self.index.legacy_import_pending)
        finally:
            lock.rollback();lock.close()
        with closing(self.index.connect()) as db:
            self.assertEqual(self.index.snapshot(db,self.now)['all_total'],123)
            self.assertTrue(db.execute('SELECT 1 FROM source_identity').fetchone())
            self.assertFalse(self.index.legacy_import_pending)

if __name__=='__main__':unittest.main()
