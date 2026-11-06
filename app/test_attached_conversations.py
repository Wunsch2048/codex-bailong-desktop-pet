"""Explicit desktop attachments must not become separate visible tasks."""
import os,json,sqlite3,tempfile,time,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
from types import SimpleNamespace
from session_read_state import attached_conversations,non_user_sessions,active_conversations
from enhanced_core import ActivityReducer,RolloutTail,Session
from activity_targets import ActivityTargets

ROOT='11111111-1111-4111-8111-111111111111'
CHILD='22222222-2222-4222-8222-222222222222'
FORK='33333333-3333-4333-8333-333333333333'

class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:
            db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,name TEXT,title TEXT,source TEXT,agent_path TEXT,archived INT,has_user_event INT,attached_thread_parent_id TEXT)')
            db.executemany('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?)',[(ROOT,'同名','同名','vscode',None,0,1,None),(CHILD,'同名','同名','vscode',None,0,1,ROOT),(FORK,'同名','同名','vscode',None,0,1,None)])
    def tearDown(self):self.tmp.cleanup()
    def test_only_explicit_attachment_is_hidden_not_same_name_or_normal_fork(self):
        self.assertEqual(attached_conversations(self.home,[ROOT,CHILD,FORK]),{CHILD:ROOT})
        self.assertEqual(non_user_sessions(self.home,[ROOT,CHILD,FORK]),{CHILD})
    def test_chains_resolve_but_cycles_or_missing_parent_do_not_hide_unknown_chat(self):
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:
            db.execute('UPDATE threads SET attached_thread_parent_id=? WHERE id=?',(CHILD,FORK))
        self.assertEqual(attached_conversations(self.home,[FORK]),{FORK:ROOT})
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:
            db.execute('UPDATE threads SET attached_thread_parent_id=? WHERE id=?',(FORK,ROOT))
        self.assertEqual(attached_conversations(self.home,[CHILD,FORK]),{})
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:
            db.execute('UPDATE threads SET attached_thread_parent_id=? WHERE id=?',('missing',CHILD))
        self.assertEqual(attached_conversations(self.home,[CHILD]),{})
    def test_unknown_schema_or_unavailable_database_never_creates_or_hides(self):
        empty=self.home/'missing';empty.mkdir()
        self.assertEqual(attached_conversations(empty,[CHILD]),{});self.assertFalse((empty/'state_5.sqlite').exists())
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:db.execute('ALTER TABLE threads RENAME COLUMN attached_thread_parent_id TO future_parent')
        self.assertEqual(attached_conversations(self.home,[CHILD]),{})
    def test_active_database_seed_excludes_internal_attachment(self):
        with closing(sqlite3.connect(self.home/'thread_history_1.sqlite')) as db,db:
            db.execute('CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,status TEXT,rollout_ordinal INT)')
            db.executemany('INSERT INTO thread_turns VALUES(?,?,?,?)',[(ROOT,'a','inProgress',1),(CHILD,'b','inProgress',1),(FORK,'c','inProgress',1)])
        seeds=active_conversations(self.home)
        self.assertEqual({e['session'] for e in seeds},{ROOT,FORK});self.assertTrue(all(e['active']==2 for e in seeds))
    def test_attachment_never_counts_or_receives_live_targets_or_completion(self):
        r=ActivityReducer();r.sessions[ROOT]=Session(state='working',turn='a',done=False)
        r.sessions[CHILD]=Session(state='thinking',turn='b',done=False,attached_parent=ROOT,waiting_reason='input')
        targets=ActivityTargets();targets.sync(r.sessions,[(CHILD,'b')],[CHILD])
        self.assertEqual(set(targets.entries),{ROOT});self.assertEqual(targets.ipc_targets(),(ROOT,))
        status=r._status(ROOT,r.sessions[ROOT]);self.assertEqual((status['active'],status['waiting']),(1,0))
        self.assertFalse(r.runtime_events(CHILD,True,'b'));self.assertFalse(r.terminate(CHILD,'completed','b'))
        obj=dict(type='event_msg',payload=dict(type='task_complete',turn_id='b'))
        self.assertFalse(r.apply(CHILD,obj))
    def write_log(self,sid,records):
        folder=self.home/'sessions';folder.mkdir(exist_ok=True)
        p=folder/('rollout-'+sid+'.jsonl')
        rows=[dict(type='session_meta',payload=dict(id=sid,source='vscode',forked_from_id=ROOT if sid in (CHILD,FORK) else None))]+records
        p.write_text(''.join(json.dumps(x)+'\n' for x in rows),encoding='utf-8');return p
    def test_tail_does_not_promote_inherited_user_text_to_a_second_task(self):
        self.write_log(ROOT,[dict(type='event_msg',payload=dict(type='task_started',turn_id='real'))])
        self.write_log(CHILD,[dict(type='response_item',payload=dict(type='message',role='user',content=[dict(type='input_text',text='继承的用户消息')]))])
        tail=RolloutTail(self.home);events=tail.poll()
        self.assertTrue(any(e.get('session') and e.get('session').endswith(ROOT) for e in events))
        self.assertFalse(any(e.get('session') and e.get('session').endswith(CHILD) for e in events))
        self.assertTrue(tail.reducer.sessions[tail.file_ids[next(p for p in tail.file_ids if CHILD in p.name)]].source_hidden)
        self.assertTrue(any(e.get('kind')=='hidden_sessions' and CHILD in e['sessions'] for e in events))
        # A normal independent fork with the same name still reports work.
        self.write_log(FORK,[dict(type='event_msg',timestamp=datetime.fromtimestamp(time.time()+2,timezone.utc).isoformat(),payload=dict(type='task_started',turn_id='independent'))])
        tail.catalog.last_check=-1e9;events=tail.poll()
        self.assertTrue(any(e.get('session','').endswith(FORK) for e in events))
    def test_late_metadata_repairs_silent_active_count_without_emitting_completion(self):
        self.write_log(ROOT,[]);self.write_log(CHILD,[]);tail=RolloutTail(self.home);tail.poll()
        alias=next(k for k in tail.reducer.sessions if k.endswith(CHILD))
        tail.attached.clear();tail.reducer.sessions[alias].attached_parent='';tail.reducer.sessions[alias].done=False
        tail.reducer.sessions[alias].state='thinking';tail._hidden=set();tail._identity_scan=-1e9
        events=tail.poll();self.assertTrue(tail.reducer.sessions[alias].source_hidden)
        self.assertFalse(any(e['kind']=='complete' for e in events));self.assertEqual(events[-1]['active'],0)

class AttachmentUiTests(unittest.TestCase):
    setUp=AttachmentTests.setUp
    tearDown=AttachmentTests.tearDown
    def test_saved_and_runtime_false_notice_removed_but_main_notice_and_dedupe_stay(self):
        from PySide6.QtWidgets import QApplication
        from status_indicator import StatusIndicator
        app=QApplication.instance() or QApplication([])
        path=self.home/'task-notifications.json'
        path.write_text(json.dumps(dict(unread=[[ROOT,'real'],[CHILD,'false']],seen=[])),encoding='utf-8')
        indicator=StatusIndicator();indicator.set_store(path,home=self.home)
        self.assertEqual(indicator.unread,[(ROOT,'real')])
        self.assertFalse(indicator.notify_complete(dict(session=CHILD,turn='false')))
        indicator.unread.append((CHILD,'late'))
        self.assertTrue(indicator.exclude_sessions([CHILD]))
        self.assertEqual(indicator.unread,[(ROOT,'real')]);self.assertIsNone(indicator.acknowledged_at)
        self.assertFalse(indicator.notify_complete(dict(session=CHILD,turn='late')))
        indicator.close();indicator.deleteLater();app.processEvents()
    def test_runtime_repair_clears_row_animation_and_notice_and_blocks_queued_child_events(self):
        from PySide6.QtWidgets import QApplication
        from desktop import DesktopPet
        from compact_bubble import CompactBubble
        from status_reactions import StatusReactions
        app=QApplication.instance() or QApplication([]);b=CompactBubble()
        reactions=StatusReactions(0,available=['work01'])
        alias='rollout-'+CHILD
        child=dict(session=alias,turn='false',state='thinking',turn_started=True,active=2)
        reactions.observe(child,1);reactions.confirm(alias,'false',True,1)
        reactions.queue_completion(dict(session=alias,turn='false'),2)
        b.roster.observe(dict(session=ROOT,state='working',turn='real',title='同名'))
        b.roster.observe(dict(session=CHILD,state='complete',turn='false',title='同名'))
        b.status_indicator.notify_complete(dict(session=CHILD,turn='false'))
        pet=SimpleNamespace(bubble=b,reactions=reactions,pending_completion=dict(session=alias,turn='false'))
        DesktopPet.on_activity(pet,dict(kind='hidden_sessions',sessions=[CHILD]))
        self.assertEqual(set(b.roster.items),{ROOT});self.assertFalse(b.status_indicator.unread)
        self.assertFalse(reactions.sessions);self.assertFalse(reactions.leases);self.assertFalse(reactions.openings)
        self.assertIsNone(reactions.latest);self.assertIsNone(pet.pending_completion)
        # The GUI discards old signal-queue entries too, before sounds/actions.
        DesktopPet.on_activity(pet,dict(kind='complete',session=alias,turn='another'))
        self.assertFalse(b.status_indicator.unread)
        b.close();b.deleteLater();app.processEvents()

if __name__=='__main__':unittest.main()
