"""Runtime truth, exact-turn repair and safe long-silent work semantics."""
import json,sqlite3,tempfile,time,unittest
from contextlib import closing
from pathlib import Path
from enhanced_core import ActivityReducer,Session
from codex_live_status import LifecycleProjection
from continuous_work import ContinuousWork
from status_reactions import StatusReactions
from session_read_state import terminal_conversations

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.r=ActivityReducer();self.r.sessions['a']=Session(state='working',turn='one',done=False,display='运行命令')
    def test_idle_is_reversible_and_does_not_complete_or_replay_greeting(self):
        quiet=self.r.set_runtime('a',False,'one')
        self.assertEqual([(e['kind'],e['state'],e['active']) for e in quiet],[('status','idle',0)])
        self.assertFalse(self.r.sessions['a'].done)
        self.assertFalse(self.r.set_runtime('a',False,'one'))
        resumed=self.r.set_runtime('a',True,'one')[0]
        self.assertEqual((resumed['state'],resumed['active']),('working',1))
        self.assertFalse(resumed['turn_started']);self.assertFalse(resumed['user_message'])
    def test_wrong_turn_unknown_and_terminal_never_resurrect(self):
        for turn,active in [('old',False),('',True),('one',None)]:self.assertFalse(self.r.set_runtime('a',active,turn))
        self.r.terminate('a','completed','one')
        self.assertFalse(self.r.set_runtime('a',True,'one'));self.assertTrue(self.r.sessions['a'].done)
        self.assertFalse(self.r.runtime_events('a',True,'one'))
    def test_worker_projection_orders_status_before_lease_and_heartbeats_do_not_refresh_text(self):
        events=self.r.runtime_events('a',False,'one')
        self.assertEqual([e['kind'] for e in events],['status','animation_lifecycle'])
        self.assertEqual([e['kind'] for e in self.r.runtime_events('a',False,'one')],['animation_lifecycle'])
        self.assertFalse(self.r.runtime_events('a',True,'old'))
    def test_other_running_session_and_waiting_are_not_cleared(self):
        self.r.sessions['b']=Session(state='thinking',turn='two',done=False)
        self.assertEqual(self.r.set_runtime('a',False,'one')[0]['active'],1)
        waiting=self.r.set_waiting('a','approval','one')[0]
        self.assertEqual(waiting['state'],'waiting');self.assertEqual(waiting['waiting'],1)
        self.assertEqual(waiting['active'],1)
    def test_new_turn_does_not_inherit_idle_and_late_idle_is_ignored(self):
        self.r.set_runtime('a',False,'one')
        events=self.r.apply('a',dict(type='event_msg',payload=dict(type='task_started',turn_id='two')))
        self.assertEqual((events[-1]['state'],events[-1]['active']),('thinking',1))
        self.assertFalse(self.r.set_runtime('a',False,'one'))
    def test_heartbeat_unknown_and_disconnect_are_not_native_idle(self):
        out=[];p=LifecycleProjection(lambda *a:None,emit_activity=lambda *v:out.append(v))
        p.states['a']=dict(turns=[dict(turnId='one',status='inProgress')])
        p.heartbeat(0);self.assertFalse(out)
        p.states['a']=dict(turns=[dict(turnId='one')],threadRuntimeStatus=dict(type='active'))
        p.heartbeat(0,force='a');self.assertFalse(out)
        p.states['a']['turns'][0]['status']='inProgress'
        p.states['a']['threadRuntimeStatus']=dict(type='active');p.heartbeat(1,force='a')
        self.assertEqual(out[-1],('a',True,'one'))
        p.forget('a');self.assertEqual(len(out),1)
    def test_explicit_idle_and_active_heartbeats_share_reducer_truth(self):
        out=[]
        def consume(sid,active,turn):out.extend(self.r.set_runtime(sid,active,turn))
        p=LifecycleProjection(lambda *a:None,emit_activity=consume)
        p.states['a']=dict(turns=[dict(turnId='one',status='inProgress')],threadRuntimeStatus=dict(type='idle'))
        p.heartbeat(0);self.assertEqual(out[-1]['state'],'idle')
        p.heartbeat(16);self.assertEqual(len(out),1)
        p.states['a']['threadRuntimeStatus']['type']='active';p.heartbeat(17,force='a')
        self.assertEqual(out[-1]['state'],'working')
    def test_live_long_silent_work_uses_generic_pose_without_faking_text(self):
        r=StatusReactions(0,available=('work02','work04'));c=ContinuousWork()
        r.observe(dict(session='a',turn='one',state='working',activity='execute',text='original command'),0)
        c.target(r,0);c.commit(c.target(r,2),2)
        r.confirm('a','one',True,100);c.target(r,100)
        generic=c.target(r,103.1)
        self.assertEqual(generic.action_id,'work04');self.assertTrue(r.busy(103.1))
        self.assertEqual((r.sessions['a']['received'],r.sessions['a']['text']),(0,'original command'))
        self.assertIsNone(c.target(r,136));self.assertFalse(r.busy(136))

class TerminalRepairTests(unittest.TestCase):
    def test_exact_turn_latest_revision_unknown_and_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);path=home/'thread_history_1.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE thread_turns(thread_id,turn_id,status,rollout_ordinal)')
                db.execute('CREATE INDEX turns_identity ON thread_turns(thread_id,turn_id,rollout_ordinal)')
                db.executemany('INSERT INTO thread_turns VALUES(?,?,?,?)',[
                    ('a','old','completed',1),('a','new','inProgress',2),
                    ('b','one','completed',1),('b','one','inProgress',2),
                    ('c','one','failed',1),('d','one','interrupted',1)])
            before=path.read_bytes()
            self.assertEqual(set(terminal_conversations(home,[('a','new'),('b','one'),('c','one'),('d','one'),('missing','x')])),{('c','one','failed'),('d','one','interrupted')})
            self.assertEqual(terminal_conversations(home,[('a','old')]),[('a','old','completed')])
            self.assertEqual(path.read_bytes(),before)
    def test_missing_schema_and_empty_input_have_no_side_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            self.assertEqual(terminal_conversations(home,[]),[])
            self.assertEqual(terminal_conversations(home,[('a','one')]),[])
            self.assertFalse(list(home.iterdir()))

if __name__=='__main__':unittest.main()
