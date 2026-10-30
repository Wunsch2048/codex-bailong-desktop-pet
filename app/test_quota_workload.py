import copy,io,json,sqlite3,unittest
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime,timezone
from token_analytics import migrate,scan_file
import quota_workload as w
from quota_history import WEEK,store,summarize_cycles,anomaly,snapshot,visible_anomaly


class MemoryLog:
    stem='quota-workload'
    def __init__(self):self.raw=b''
    def append(self,o):self.raw+=json.dumps(o).encode()+b'\n'
    def stat(self):return SimpleNamespace(st_size=len(self.raw))
    def resolve(self):return Path('quota-workload.jsonl').absolute()
    def open(self,*args):return io.BytesIO(self.raw)


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE files(path TEXT PRIMARY KEY,offset INTEGER,highwater INTEGER)')
        self.db.execute('CREATE TABLE usage(fingerprint TEXT PRIMARY KEY,stamp REAL,tokens INTEGER)')
        migrate(self.db);__import__('quota_history').migrate(self.db)
        self.log=MemoryLog();self.index=SimpleNamespace(format_known={});self.start=1800000000
    def tearDown(self):self.db.close()
    def event(self,t,a,b,c):
        return dict(timestamp=datetime.fromtimestamp(self.start+t,timezone.utc).isoformat(),type='event_msg',payload=dict(type='token_count',info=dict(total_token_usage=dict(input_tokens=a,output_tokens=b,cached_input_tokens=c,total_tokens=a+b))))
    def context(self,speed='standard',effort='medium',model='sol'):
        self.log.append(dict(type='turn_context',payload=dict(model=model,service_tier=speed,effort=effort)))
    def scan(self):scan_file(self.index,self.db,self.log,lambda:False)
    def profile(self):return w.profile(self.db,self.start,self.start+1000)
    def cycle(self,start,sol,astra,drop,cache=0,speed='standard'):
        for t,r in [(1,100),(100,100-drop/2),(200,100-drop)]:store(self.db,start+t,start+WEEK,r,plan='pro')
        for model,n in [('sol',sol),('astra',astra)]:
            if not n:continue
            key=str(start)+model;a=int(n*.8);b=n-a
            self.db.execute('INSERT INTO usage VALUES(?,?,?,?,?,?,?,?)',(key,start+50,n,'session',model,a,b,1))
            w.store(self.db,key,model,n,round(a*cache),dict(speed=speed,effort='medium'))
    def test_existing_scanner_collects_context_cache_and_restores_after_restart(self):
        self.context();self.log.append(self.event(10,80,20,40));self.scan()
        self.index=SimpleNamespace(format_known={});self.log.append(self.event(20,160,40,80));self.scan()
        p=self.profile();self.assertTrue(p['complete']);self.assertEqual(p['models']['sol']['cached'],80);self.assertEqual(p['tokens'],200)
        self.scan();self.assertEqual(self.profile(),p)
    def test_old_cursor_first_cache_delta_unknown_then_recovers_without_reread(self):
        self.context();self.log.append(self.event(10,80,20,40));self.scan()
        self.db.execute('DELETE FROM quota_workload_files');self.db.execute('DELETE FROM quota_workload_events')
        before=self.db.execute('SELECT offset FROM files').fetchone()[0]
        self.context();self.log.append(self.event(20,160,40,80));self.scan()
        self.assertIsNone(self.db.execute('SELECT cached FROM quota_workload_events').fetchone()[0])
        self.log.append(self.event(30,240,60,120));self.scan()
        recent=w.profile(self.db,self.start+20,self.start+30)
        self.assertTrue(recent['complete']);self.assertEqual(recent['models']['sol']['cached'],40)
        self.assertGreater(self.db.execute('SELECT offset FROM files').fetchone()[0],before)
    def test_missing_speed_stays_unknown_and_does_not_inherit_last_turn(self):
        self.context('priority');self.log.append(self.event(10,80,20,40))
        self.log.append(dict(type='turn_context',payload=dict(model='sol',effort='medium')))
        self.log.append(self.event(20,160,40,80));self.scan()
        self.assertFalse(self.profile()['complete'])
        self.assertEqual(self.db.execute('SELECT speed FROM quota_workload_events ORDER BY rowid DESC').fetchone()[0],'')
    def test_cache_rollback_or_missing_never_becomes_zero(self):
        self.context();self.log.append(self.event(10,80,20,40));self.log.append(self.event(20,160,40,10));self.scan()
        self.assertFalse(self.profile()['complete']);self.assertIsNone(self.db.execute('SELECT cached FROM quota_workload_events ORDER BY rowid DESC').fetchone()[0])
    def test_conflicting_duplicate_is_not_silently_relabelled(self):
        w.store(self.db,'a','sol',100,40,dict(speed='standard',effort='medium'))
        w.store(self.db,'a','sol',100,40,dict(speed='priority',effort='medium'))
        w.store(self.db,'a','sol',100,40,dict(speed='standard',effort='medium'))
        self.assertEqual(self.db.execute('SELECT tokens FROM quota_workload_events').fetchone()[0],-1)
    def test_constant_capacity_model_mix_counterexample_no_longer_warns(self):
        self.cycle(self.start,950,50,30);self.cycle(self.start+WEEK,850,150,40)
        now=self.start+WEEK+201;rows=summarize_cycles(self.db,now)
        self.assertIsNotNone(rows[0]['estimated_total']);self.assertIsNone(rows[0]['change'])
        self.assertIn('模型使用结构',rows[0]['comparison_block']);self.assertIsNone(anomaly(rows,now))
    def test_identical_conditions_can_still_warn_both_directions(self):
        for amounts,expected in [((1000,500),-50),((500,1000),100)]:
            self.db.execute('DELETE FROM usage');self.db.execute('DELETE FROM quota_observations');self.db.execute('DELETE FROM quota_workload_events')
            self.cycle(self.start,amounts[0],0,40);self.cycle(self.start+WEEK,amounts[1],0,40)
            now=self.start+WEEK+201;rows=summarize_cycles(self.db,now)
            self.assertEqual(anomaly(rows,now)['change'],expected)
    def test_cache_speed_effort_and_minor_expensive_model_changes_are_gated(self):
        self.cycle(self.start,1000,0,40);self.cycle(self.start+WEEK,500,0,40)
        rows=summarize_cycles(self.db,self.start+WEEK+201);a,b=rows
        for change,expected in [('cache','缓存'),('speed','档位'),('effort','档位'),('newmodel','模型')]:
            p=copy.deepcopy(a);v=p['workload']
            if change=='cache':v['models']['sol']['cached']=v['models']['sol']['input']*.5
            elif change=='newmodel':
                v['models']['sol']['tokens']-=1;v['models']['sol']['input']-=1
                v['models']['astra']=dict(tokens=1,input=1,output=0,cached=0)
                key=next(iter(v['settings']));v['settings'][key]-=1
                v['settings'][json.dumps(['astra','standard','medium'],separators=(',',':'))]=1
            else:
                key=next(iter(v['settings']));parts=json.loads(key);parts[1 if change=='speed' else 2]='priority' if change=='speed' else 'high'
                v['settings']={json.dumps(parts,separators=(',',':')):v['settings'][key]}
            self.assertIn(expected,w.mismatch(p,b))
    def test_missing_historical_metadata_keeps_facts_and_blocks_cached_alert(self):
        self.cycle(self.start,1000,0,40);self.cycle(self.start+WEEK,500,0,40)
        now=self.start+WEEK+201;rows=summarize_cycles(self.db,now);old=rows[1]
        self.db.execute('DELETE FROM quota_workload_events WHERE fingerprint LIKE ?',(str(self.start)+'%',))
        old.pop('workload');old['change']=-25
        self.db.execute('INSERT INTO quota_cycle_snapshots VALUES(?,?)',(old['id'],json.dumps(old)))
        result=snapshot(self.db,None,now,False,dict(pending=False,errors=1))
        self.assertEqual(result['cycles'][1]['estimated_total'],old['estimated_total'])
        self.assertIsNone(result['cycles'][0]['change']);self.assertIsNone(result['anomaly'])
        fresh=summarize_cycles(self.db,now)
        self.assertIn('条件记录不完整',fresh[0]['comparison_block'])
        legacy=dict(change=-25,through=now)
        self.assertIsNone(visible_anomaly(dict(quota_history=dict(anomaly=legacy)),[],now))
    def test_schema_upgrade_does_not_reset_original_cursors(self):
        self.context();self.log.append(self.event(10,80,20,40));self.scan()
        before=self.db.execute('SELECT * FROM files').fetchall();values=self.db.execute('SELECT * FROM usage').fetchall()
        migrate(self.db);self.assertEqual(before,self.db.execute('SELECT * FROM files').fetchall());self.assertEqual(values,self.db.execute('SELECT * FROM usage').fetchall())
    def test_malformed_cached_workload_blocks_instead_of_crashing_or_warning(self):
        self.cycle(self.start,1000,0,40);self.cycle(self.start+WEEK,500,0,40)
        rows=summarize_cycles(self.db,self.start+WEEK+201)
        for invalid in [None,['corrupt'],dict(version=1,complete=True,tokens=100),dict(version=1,complete=True,tokens=float('nan'),models={},settings={})]:
            changed=copy.deepcopy(rows);changed[0]['workload']=invalid
            self.assertTrue(w.mismatch(*changed));self.assertIsNone(anomaly(changed,self.start+WEEK+201))
    def test_model_override_cannot_keep_the_previous_models_speed_or_effort(self):
        self.context('priority','high');event=self.event(10,80,20,40);event['payload']['model']='astra'
        self.log.append(event);self.scan();p=self.profile()
        self.assertFalse(p['complete']);self.assertEqual(set(p['models']),{'astra'})
    def test_explicit_event_tier_can_supply_missing_turn_context_metadata(self):
        self.context(None,None);event=self.event(10,80,20,40)
        event['payload']['info'].update(service_tier='priority',reasoning_effort='high')
        self.log.append(event);self.scan();self.assertTrue(self.profile()['complete'])
    def test_unsupported_or_swapped_context_labels_remain_unknown(self):
        self.context('high','priority');self.log.append(self.event(10,80,20,40));self.scan()
        self.assertFalse(self.profile()['complete'])
        self.assertEqual(self.db.execute('SELECT speed,effort FROM quota_workload_events').fetchone(),('',''))

if __name__=='__main__':unittest.main()
