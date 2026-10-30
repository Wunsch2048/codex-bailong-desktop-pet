"""Cost invariants using isolated fixtures; no production data or subprocesses."""
import json,os,sqlite3,tempfile,time,unittest
from pathlib import Path
from datetime import datetime
from contextlib import closing
from project_cost import migrate,update,snapshot,scan

class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name);self.now=time.time();self.stamp=datetime.fromtimestamp(self.now-1).astimezone().isoformat()
        self.db=sqlite3.connect(self.home/'cost.sqlite');migrate(self.db)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def lines(self,total=2000,parent=False,fork=False,pad=0):
        meta=dict(id='s',cwd='D:/old',model='gpt-6.1-sol')
        if parent:meta['parent_thread_id']='parent'
        if fork:meta['forked_from_id']='parent'
        event=self.event(total)
        return json.dumps(dict(type='session_meta',timestamp=self.stamp,payload=meta))+'\n'+event+(' '*pad+'\n' if pad else '')
    def event(self,total):
        return json.dumps(dict(type='event_msg',timestamp=self.stamp,payload=dict(type='token_count',info=dict(total_token_usage=dict(total_tokens=total,input_tokens=total*8//10,cached_input_tokens=total*6//10,output_tokens=total*2//10)))))+'\n'
    def write(self,text,name='s.jsonl'):
        p=self.home/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');return p
    def load(self,files):
        progress=update(self.db,files,budget=3);return snapshot(self.db,self.now,progress,files,self.home)
    def total(self,data):return sum(p['tokens'] for p in data['ranges']['all'])
    def membership(self,value,name='A'):
        self.write(json.dumps({'local-projects':{'a':{'name':name,'rootPaths':['D:/old']},'b':{'name':'B','rootPaths':['D:/new','D:/old']}},'thread-project-assignments':value}),'.codex-global-state.json')
    def test_moves_detach_rename_and_restart_conserve_totals(self):
        p=self.write(self.lines());self.membership({'s':{'projectId':'a'}})
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:
            db.execute('CREATE TABLE threads(id TEXT,cwd TEXT,archived INTEGER)');db.execute("INSERT INTO threads VALUES('s','D:/new',0)")
        for value,expected in [({'s':{'projectId':'a'}},'project:a'),({'s':{'projectId':'b'}},'project:b'),({'s':{'projectId':None}},'d:/new'),({'s':{'projectId':'a'}},'project:a'),({},'d:/new')]:
            self.membership(value);r=self.load([p]);self.assertEqual(self.total(r),2000);self.assertEqual(r['ranges']['all'][0]['id'],expected)
            self.db.commit();self.db.close();self.db=sqlite3.connect(self.home/'cost.sqlite')
        self.membership({'s':{'projectId':'a'}},name='改名');r=self.load([p]);self.assertEqual(r['ranges']['all'][0]['name'],'改名');self.assertEqual(self.total(r),2000)
    def test_rewrite_is_atomic_across_interruption_and_restart(self):
        p=self.write(self.lines(1000));self.assertEqual(self.total(self.load([p])),1000)
        p.write_text(self.lines(2000)+self.event(3000),encoding='utf-8');calls=[0]
        def stop():calls[0]+=1;return calls[0]>2
        self.assertTrue(scan(self.db,p,stop,time.monotonic()+3));self.assertEqual(self.total(snapshot(self.db,self.now,{'pending':True,'errors':0},[p],self.home)),1000)
        self.db.commit();self.db.close();self.db=sqlite3.connect(self.home/'cost.sqlite')
        self.assertEqual(self.total(self.load([p])),3000)
        self.assertGreater(self.db.execute('SELECT COUNT(*) FROM cost_revision_events').fetchone()[0],1)  # old revision retained, not counted
    def test_append_matches_cold_replay_without_duplicate_usage(self):
        p=self.write(self.lines(2000));self.load([p])
        with p.open('a',encoding='utf-8') as f:f.write(self.event(3000))
        current=self.load([p]);again=self.load([p]);self.assertEqual(self.total(current),3000);self.assertEqual(self.total(again),3000)
        with closing(sqlite3.connect(':memory:')) as cold:
            migrate(cold);progress=update(cold,[p],budget=3);data=snapshot(cold,self.now,progress,[p],self.home)
            self.assertEqual(current['ranges'],data['ranges'])
    def test_many_appends_grow_only_by_new_events_and_keep_confirmed_revision(self):
        p=self.write(self.lines(2000));self.load([p]);revision=self.db.execute('SELECT revision FROM cost_source_active').fetchone()[0]
        for total in range(3000,53000,1000):
            with p.open('a',encoding='utf-8') as f:f.write(self.event(total))
            self.load([p])
        self.assertEqual(self.db.execute('SELECT revision FROM cost_source_active').fetchone()[0],revision)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cost_source_events').fetchone()[0],51)
        self.assertEqual(self.total(self.load([p])),52000)
    def test_interrupted_append_does_not_publish_delta_early_and_resumes(self):
        p=self.write(self.lines(2000));self.load([p]);revision=self.db.execute('SELECT revision FROM cost_source_active').fetchone()[0]
        with p.open('a',encoding='utf-8') as f:f.write(self.event(3000)+self.event(4000))
        calls=[0]
        def stop():calls[0]+=1;return calls[0]>1
        self.assertTrue(scan(self.db,p,stop,time.monotonic()+3))
        self.assertEqual(self.total(snapshot(self.db,self.now,{'pending':True,'errors':0},[p],self.home)),2000)
        self.db.commit();self.db.close();self.db=sqlite3.connect(self.home/'cost.sqlite')
        self.assertEqual(self.total(self.load([p])),4000)
        self.assertEqual(self.db.execute('SELECT revision FROM cost_source_active').fetchone()[0],revision)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cost_source_events').fetchone()[0],3)
    def test_warm_append_reads_only_new_records_and_restart_verifies_prefix_once(self):
        import project_cost_store as store
        from unittest.mock import patch
        p=self.write(self.lines(2000,pad=12000));self.load([p])
        with p.open('a',encoding='utf-8') as f:f.write(self.event(3000))
        with patch.object(store,'digest',side_effect=AssertionError('warm append reread whole log')):
            self.assertEqual(self.total(self.load([p])),3000)
        store._STATES.clear();store._HASHES.clear()
        with p.open('a',encoding='utf-8') as f:f.write(self.event(4000))
        with patch.object(store,'digest',wraps=store.digest) as digest:
            self.assertEqual(self.total(self.load([p])),4000);self.assertEqual(digest.call_count,1)
        self.assertLessEqual(len(store._STATES),8)
    def test_complete_prefix_can_publish_while_writer_keeps_appending(self):
        import project_cost_store as store
        from unittest.mock import patch
        p=self.write(self.lines(2000));self.load([p])
        with p.open('a',encoding='utf-8') as f:f.write(self.event(3000))
        size=p.stat().st_size;original=store.remember;appended=[]
        def remember(*args):
            original(*args)
            if not appended:
                with p.open('a',encoding='utf-8') as f:f.write(self.event(4000))
                appended.append(True)
        with patch.object(store,'remember',side_effect=remember):data=self.load([p])
        self.assertEqual(self.total(data),3000);self.assertTrue(data['pending']);self.assertTrue(data['syncing']);self.assertFalse(data['initial_pending'])
        self.assertEqual(self.db.execute('SELECT offset FROM cost_source_active').fetchone()[0],size)
        self.assertEqual(self.total(self.load([p])),4000)
    def test_periodic_audit_catches_middle_rewrite_even_with_a_growing_tail(self):
        text=self.lines(2000);header,event=text.split('\n',1)
        p=self.write(header+'\n'+' '*6000+'\n'+event+' '*6000+'\n');self.load([p])
        changed=event.replace('"total_tokens": 2000','"total_tokens": 3000').replace('"input_tokens": 1600','"input_tokens": 2400').replace('"cached_input_tokens": 1200','"cached_input_tokens": 1800').replace('"output_tokens": 400','"output_tokens": 600')
        text=header+'\n'+' '*6000+'\n'+changed+' '*6000+'\n'
        p.write_text(text+' \n',encoding='utf-8')
        # Boundary sampling cannot prove arbitrary middle bytes unchanged.
        # Retain a timed full audit; do not move its deadline on every append.
        old_checked=self.db.execute('SELECT checked FROM cost_source_active').fetchone()[0]
        self.load([p]);self.assertEqual(self.db.execute('SELECT checked FROM cost_source_active').fetchone()[0],old_checked)
        self.db.execute('UPDATE cost_source_active SET checked=0')
        self.assertEqual(self.total(self.load([p])),3000)
    def test_interrupted_work_checks_its_exact_prefix_after_cache_loss(self):
        import project_cost_store as store
        header,event=self.lines(2000).split('\n',1)
        text=header+'\n'+' '*9000+'\n'+event+' '*9000+'\n'+' '*100+'\n'
        p=self.write(text);calls=[0]
        def stop():calls[0]+=1;return calls[0]>4
        self.assertTrue(scan(self.db,p,stop,time.monotonic()+3));self.db.commit()
        changed=event.replace('"total_tokens": 2000','"total_tokens": 3000')
        p.write_text(header+'\n'+' '*9000+'\n'+changed+' '*9000+'\n'+' '*100+'\n \n',encoding='utf-8')
        store._STATES.clear();store._HASHES.clear()
        self.assertEqual(self.total(self.load([p])),3000)
    def test_same_length_rewrite_and_shorter_revision_replace_totals(self):
        p=self.write(self.lines(2000));self.load([p]);size=p.stat().st_size;p.write_text(self.lines(3000),encoding='utf-8');self.assertEqual(p.stat().st_size,size)
        self.assertEqual(self.total(self.load([p])),3000)
        p.write_text(self.lines(1000,pad=1000),encoding='utf-8');self.load([p]);p.write_text(self.lines(2000),encoding='utf-8');self.assertEqual(self.total(self.load([p])),2000)
    def test_periodic_full_verification_catches_preserved_metadata_middle_edit(self):
        text=self.lines(2000);head,event=text.split('\n',1);p=self.write(head+'\n'+' '*6000+'\n'+event+' '*6000+'\n');self.load([p]);st=p.stat()
        p.write_text(p.read_text(encoding='utf-8').replace('2000','3000').replace('1600','2400').replace('1200','1800').replace('400','600'),encoding='utf-8');os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.db.execute('UPDATE cost_source_active SET checked=0');self.assertEqual(self.total(self.load([p])),3000)
    def test_parent_only_is_not_a_history_fork(self):
        p=self.write(self.lines(2000,parent=True));r=self.load([p]);self.assertEqual(self.total(r),2000);self.assertFalse(r['limited'])
    def test_unresolved_fork_and_last_only_are_visible_not_confirmed_zero(self):
        p=self.write(self.lines(2000,fork=True));r=self.load([p]);self.assertTrue(r['limited']);self.assertEqual(r['unresolved_events'],1)
        p.write_text(json.dumps(dict(type='session_meta',timestamp=self.stamp,payload=dict(id='s',cwd='D:/old')))+'\n'+json.dumps(dict(type='event_msg',timestamp=self.stamp,payload=dict(type='token_count',info=dict(last_token_usage=dict(total_tokens=200)))))+'\n',encoding='utf-8')
        r=self.load([p]);self.assertEqual(self.total(r),0);self.assertTrue(r['limited']);self.assertEqual(r['unresolved_events'],1)
    def test_copy_archive_and_restore_do_not_change_total(self):
        p=self.write(self.lines());q=self.write(p.read_text(encoding='utf-8'),'copy.jsonl');self.assertEqual(self.total(self.load([p,q])),2000)
        archived=self.home/'archived_sessions/s.jsonl';archived.parent.mkdir();p.rename(archived)
        self.assertEqual(self.total(self.load([archived,q])),2000)
        archived.rename(p);self.assertEqual(self.total(self.load([p,q])),2000)
    def test_missing_source_retains_last_complete_snapshot_and_marks_error(self):
        p=self.write(self.lines());self.load([p]);r=self.load([self.home/'missing.jsonl']);self.assertEqual(self.total(r),2000);self.assertEqual(r['errors'],1)
    def test_empty_replacement_does_not_erase_the_last_confirmed_history(self):
        p=self.write(self.lines());self.load([p]);p.write_text('',encoding='utf-8')
        r=self.load([p]);self.assertEqual(self.total(r),2000);self.assertTrue(r['limited'])
    def test_parent_cycle_does_not_silently_merge_unrelated_sessions(self):
        p=self.write(self.lines());self.load([p]);self.db.execute("INSERT INTO cost_parent VALUES('s','other')");self.db.execute("INSERT INTO cost_parent VALUES('other','s')")
        r=self.load([p]);self.assertEqual(self.total(r),2000);self.assertTrue(r['limited']);self.assertGreater(r['parent_conflicts'],0)
    def test_legacy_cost_tables_are_retained_for_previous_program_rollback(self):
        self.db.execute("INSERT INTO cost_events VALUES('legacy',?,'s','d:/old','gpt-6.1-sol',2000,1600,1200,400,1)",(self.now-1,))
        self.db.execute("INSERT INTO cost_files VALUES('legacy-path',1,?,0)",(json.dumps({'session':'s','project':'d:/old'}),))
        before=[list(self.db.execute('SELECT * FROM '+table)) for table in ('cost_events','cost_files')]
        p=self.write(self.lines(3000));r=self.load([p]);self.assertEqual(self.total(r),3000)
        after=[list(self.db.execute('SELECT * FROM '+table)) for table in ('cost_events','cost_files')];self.assertEqual(before,after)
    def test_read_error_does_not_revoke_confirmed_membership(self):
        p=self.write(self.lines());self.membership({'s':{'projectId':'b'}});self.load([p]);self.write('{not complete','.codex-global-state.json');r=self.load([p]);self.assertEqual(r['ranges']['all'][0]['id'],'project:b')

if __name__=='__main__':unittest.main()
