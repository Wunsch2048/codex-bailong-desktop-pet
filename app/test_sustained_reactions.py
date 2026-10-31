"""Ongoing work stays expressive without stale tasks, interruptions or spam."""
import unittest
from unittest.mock import patch
from status_reactions import StatusReactions
from desktop_core import normalized
from codex_live_status import LifecycleProjection
from test_live_compaction import SID,decode,snapshot,patches

WORK={f'work{i:02}' for i in range(1,6)}
def event(**kw):return dict(dict(state='thinking',session=SID,turn='turn-one',activity='thinking',active=1),**kw)

class SustainedTests(unittest.TestCase):
    def scheduler(self):return StatusReactions(0,interval=12,available=WORK)
    def test_work_repeats_at_configured_cadence_not_60_second_decorative_cooldown(self):
        s=self.scheduler();s.observe(event(),0)
        self.assertEqual(s.poll(8,boundary=True).action_id,'work04');s.finished(14,2)
        self.assertIsNone(s.poll(16,boundary=True))
        self.assertEqual(s.poll(20,boundary=True).action_id,'work04')
        for now in range(21,32):self.assertIsNone(s.poll(now,boundary=False))
    def test_legacy_gestures_keep_conservative_repeat_limit(self):
        s=StatusReactions(0,interval=12);s.observe(event(),0)
        self.assertEqual(s.poll(8,boundary=True).action_id,'quota')
        for now in (20,32,44,56):self.assertIsNone(s.poll(now,boundary=True))
        self.assertIsNotNone(s.poll(68,boundary=True))
    def test_live_lease_keeps_silent_thinking_active_and_expiration_stops_it(self):
        s=self.scheduler();s.observe(event(),0);played=[]
        for now in range(0,301):
            if now%15==0:s.confirm(SID,'turn-one',True,now)
            result=s.poll(now,boundary=True)
            if result:played.append(result)
        self.assertGreaterEqual(len(played),24);self.assertTrue(s.busy(320))
        self.assertIsNone(s.poll(340,boundary=True));self.assertFalse(s.busy(340))
        self.assertEqual(s.latest['received'],0);self.assertFalse(s.openings)
    def test_terminal_lease_stops_work_without_inventing_completion(self):
        s=self.scheduler();s.observe(event(),0);s.confirm(SID,'turn-one',False,1)
        self.assertIsNone(s.poll(8,boundary=True));self.assertIsNone(s.completion)
        s.observe(event(turn='turn-two'),9)
        self.assertIsNotNone(s.poll(20,boundary=True))
    def test_old_turn_lease_does_not_keep_new_turn_alive(self):
        s=self.scheduler();s.observe(event(turn='new'),0);s.confirm(SID,'old',True,120)
        self.assertIsNone(s.poll(120,boundary=True))
    def test_inactive_lease_does_not_erase_explicit_interrupted_gesture(self):
        s=self.scheduler();s.observe(event(state='interrupted',active=0),0);s.confirm(SID,'turn-one',False,1)
        self.assertEqual(s.poll(8,boundary=True).action_id,'idle2')
    def test_expired_latest_does_not_hide_fresh_other_session(self):
        s=self.scheduler();s.observe(event(session='other',state='working',activity='execute'),0)
        s.observe(event(),1);s.confirm('other','turn-one',True,100)
        result=s.poll(100,boundary=True);self.assertEqual((result.session,result.action_id),('other','work02'))
    def test_waiting_and_closed_codex_never_continue_work(self):
        s=self.scheduler();s.observe(event(state='waiting'),0);s.confirm(SID,'turn-one',True,100)
        self.assertIsNone(s.poll(100,boundary=True));self.assertFalse(s.busy(100))
        s.observe(event(),101);s.present=False
        self.assertIsNone(s.poll(120,boundary=True));self.assertFalse(s.busy(120))
        s.queue_completion(dict(session=SID,turn='turn-one'),121)
        self.assertEqual(s.poll(122,boundary=True).kind,'complete')
    def test_storm_cannot_create_heartbeat_greetings_or_unbounded_history(self):
        s=self.scheduler();s.observe(event(),0)
        for i in range(2000):s.confirm(str(i),'turn',True,1)
        self.assertEqual(len(s.leases),32);self.assertFalse(s.openings)
    def test_new_defaults_only_fill_missing_values_and_preserve_saved_tuning(self):
        self.assertEqual(normalized({})['status_action_interval'],12)
        self.assertEqual(normalized({'status_action_interval':18})['status_action_interval'],18)
        self.assertEqual(normalized({'status_action_interval':30})['status_action_interval'],30)
        self.assertEqual(normalized({'status_action_interval':18,'status_response_revision':2})['status_action_interval'],18)

class LifecycleLeaseTests(unittest.TestCase):
    def setUp(self):
        self.events=[];self.p=LifecycleProjection(lambda *args:None,emit_activity=lambda *args:self.events.append(args))
    def test_silent_live_connection_renews_without_text_or_state_reemission(self):
        with patch('codex_live_status.time.monotonic',return_value=0):self.p.accept(decode(snapshot()),{SID})
        self.assertEqual(self.events,[(SID,True,'turn-one')])
        self.p.heartbeat(14);self.assertEqual(len(self.events),1)
        self.p.heartbeat(15);self.assertEqual(len(self.events),2)
        self.assertTrue(all(len(e)==3 for e in self.events))
    def test_terminal_state_immediate_even_during_lease_interval(self):
        with patch('codex_live_status.time.monotonic',return_value=0):self.p.accept(decode(snapshot()),{SID})
        with patch('codex_live_status.time.monotonic',return_value=1):self.p.accept(decode(patches(['turns',0,'status'],'completed')),{SID})
        self.assertEqual(self.events[-1],(SID,False,'turn-one'))
    def test_unfollow_disconnect_and_revision_gap_do_not_renew_old_truth(self):
        with patch('codex_live_status.time.monotonic',return_value=0):self.p.accept(decode(snapshot()),{SID})
        result=self.p.accept(decode(patches(['turns',0,'status'],'completed',base=88,revision=89)),{SID})
        self.assertEqual(result,'resync')
        self.p.forget(SID,clear=False);self.p.heartbeat(100)
        self.assertEqual(len(self.events),1)

if __name__=='__main__':unittest.main()
