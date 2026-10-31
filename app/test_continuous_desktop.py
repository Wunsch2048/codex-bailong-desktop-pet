import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import copy,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from desktop import DesktopPet
from continuous_work import ContinuousWork
from status_reactions import StatusReactions

APP=QApplication.instance() or QApplication([])

class DesktopContinuousTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.patches=[patch(module+'.'+key,root/('settings.json' if key=='CONFIG' else '')) for module in ('enhanced','desktop') for key in ('CONFIG','STATE_DIR')]
        for p in self.patches:p.start()
        self.pet=DesktopPet(monitor=False);self.pet.show();self.pet.tick.stop();self.pet.motion_timer.stop()
        self.pet.apply_settings(dict(wandering=False,random_actions=False));APP.processEvents()
        self.pet.manifest=copy.deepcopy(self.pet.manifest)
    def tearDown(self):
        self.pet.close();APP.processEvents()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def begin(self,state='thinking',activity=''):
        p=self.pet;now=time.monotonic();p.reactions=StatusReactions(now,available=[i['id'] for i in p.manifest['workAnimations']])
        p.reactions.observe(dict(state=state,activity=activity,session='test',turn='one'),now-3)
        p.continuous=ContinuousWork();p.continuous.target(p.reactions,now-2)
        p.player.ended=True;p.gate.state='idle'
        self.assertTrue(p.play_status_reaction(now));self.assertTrue(p.sustained.active)
        self.assertTrue(p.sustained.tail.ready.wait(5))
        return now
    def frame_at(self,now,ended=False):
        # Simulate only clock/segment deadlines; retain the real DesktopPet,
        # semantic controller, actual source/profile and segment transitions.
        self.pet.player.ended=ended
        with patch('desktop.time.monotonic',return_value=now),patch.object(self.pet.player,'advance',return_value=(None,ended)):
            self.pet._animate_frame()
    def working_body(self):
        now=self.begin('working','execute')
        self.frame_at(now+3.6,True);self.assertEqual(self.pet.sustained.phase,'seam')
        self.frame_at(now+4.1,True);self.assertEqual(self.pet.sustained.phase,'body')
        return now
    def observe_at(self,now,state='working',activity='execute',turn='one'):
        self.pet.reactions.observe(dict(state=state,activity=activity,session='test',turn=turn),now)
    def end_segment(self):
        self.pet.player.ended=True
        with patch.object(self.pet.player,'advance',return_value=(None,True)):self.pet.animate()
    def test_completion_icon_immediate_and_character_finishes_original_tail(self):
        self.begin();p=self.pet
        with patch.object(p,'notify'),patch.object(p,'refresh_quota'):
            p.on_activity(dict(kind='complete',session='test',turn='one',title='测试完成'))
        self.assertTrue(p.bubble.status_indicator.unread);self.assertEqual(p.sustained.phase,'enter')
        tail_start=p.sustained.profile['end']+1
        self.end_segment();self.assertEqual(p.sustained.phase,'exit');self.assertEqual(p.player.frame_index,tail_start)
        self.end_segment();self.assertFalse(p.sustained.active);self.assertEqual(p.mode,'task');self.assertEqual(p.current['id'],'18')
    def test_manual_action_and_hide_cancel_workers_recover_cleanly(self):
        self.begin();p=self.pet;p.choose(p.variants[0],manual=True)
        self.assertFalse(p.sustained.active);self.assertIsNone(p.sustained.warmer)
        self.begin();p.hide();APP.processEvents();self.assertFalse(p.sustained.active)
        self.assertIsNone(p.player.thread);self.assertTrue(p._resume_idle)
        p.show();APP.processEvents();self.assertFalse(p._resume_idle);self.assertEqual(p.mode,'idle')
    def test_disable_requests_natural_tail_and_custom_without_profile_is_one_shot(self):
        self.begin();p=self.pet;p.apply_settings(dict(status_actions=False));self.end_segment()
        self.assertEqual(p.sustained.phase,'exit');self.end_segment();self.assertEqual(p.mode,'idle')
        p.apply_settings(dict(status_actions=True))
        for item in p.manifest['workAnimations']:item.pop('sustained',None)
        now=time.monotonic();p.reactions.earliest=now-5;p.reactions.played.clear();p.player.ended=True;p.gate.state='idle'
        p.continuous.target(p.reactions,now)
        self.assertTrue(p.play_status_reaction(now+2));self.assertFalse(p.sustained.active);self.assertEqual(p.current['id'],'work04')
    def test_same_turn_candidate_returns_without_tail_or_second_entrance(self):
        now=self.working_body();p=self.pet;owner=p.sustained.owner
        with patch.object(p.sustained,'begin',wraps=p.sustained.begin) as entered:
            self.observe_at(now+6,'thinking','');self.frame_at(now+6)
            self.frame_at(now+8,True);self.assertEqual(p.sustained.phase,'seam')
            self.frame_at(now+8.5,True);self.assertEqual(p.sustained.phase,'body')
            # The candidate is now stable, but this source loop has not ended.
            self.frame_at(now+9.2);self.assertTrue(p.sustained.exit_requested)
            self.assertFalse(p.sustained.hard_exit_requested)
            self.observe_at(now+9.4);self.frame_at(now+9.4)
            self.assertFalse(p.sustained.exit_requested)
            self.frame_at(now+9.6,True);self.assertEqual(p.sustained.phase,'seam')
            self.frame_at(now+10.1,True);self.assertEqual(p.sustained.phase,'body')
            self.assertEqual(p.sustained.owner,owner);self.assertEqual(p.current['id'],'work02')
            self.assertEqual(p.sustained.cycles,3);entered.assert_not_called()
    def assert_lifecycle_exit(self,reason):
        now=self.working_body();p=self.pet;old_owner=p.sustained.owner
        with patch.object(p.sustained,'begin',wraps=p.sustained.begin) as entered:
            if reason=='complete':
                with patch('desktop.time.monotonic',return_value=now+6),patch.object(p,'notify'),patch.object(p,'refresh_quota'):
                    p.on_activity(dict(kind='complete',session='test',turn='one',title='测试完成'))
                self.assertTrue(p.bubble.status_indicator.unread)
            elif reason=='new-turn':self.observe_at(now+6,turn='two')
            else:self.observe_at(now+6,'waiting_input','')
            self.frame_at(now+6);self.assertTrue(p.sustained.hard_exit_requested)
            resumed_turn='one' if reason=='waiting' else 'two'
            self.observe_at(now+6.2,turn=resumed_turn);self.frame_at(now+6.2)
            self.frame_at(now+8.2)
            self.assertTrue(p.sustained.exit_requested);self.assertTrue(p.sustained.hard_exit_requested)
            self.frame_at(now+8.4,True)
            self.assertEqual(p.sustained.phase,'exit');self.assertEqual(p.sustained.owner,old_owner)
            self.assertEqual(p.player.frame_index,p.sustained.profile['end']+1)
            self.frame_at(now+9);self.assertEqual(p.sustained.phase,'exit');entered.assert_not_called()
            # Only after the whole original tail may a new entrance start.
            self.frame_at(now+12,True)
            self.assertEqual(entered.call_count,1);self.assertEqual(p.sustained.phase,'enter')
            self.assertEqual(p.sustained.owner.turn,resumed_turn)
    def test_waiting_then_resumed_work_still_finishes_tail(self):
        self.assert_lifecycle_exit('waiting')
    def test_completion_then_new_work_still_finishes_tail(self):
        self.assert_lifecycle_exit('complete')
    def test_new_turn_cannot_reuse_old_turn_loop(self):
        self.assert_lifecycle_exit('new-turn')

    def test_runtime_idle_projects_to_icon_roster_and_animation_without_clearing_unread(self):
        from enhanced_core import ActivityReducer,Session
        p=self.pet;r=ActivityReducer();r.sessions['test']=Session(state='working',turn='one',done=False)
        p.on_activity(r._status('test',r.sessions['test']))
        p.bubble.status_indicator.unread=[('another','old-completion')]
        for event in r.runtime_events('test',False,'one'):p.on_activity(event)
        self.assertFalse(p.bubble.status_indicator.is_busy())
        self.assertEqual(p.last_activity['state'],'idle')
        self.assertEqual(p.bubble.roster.items['test']['state'],'idle')
        self.assertFalse(p.reactions.busy(time.monotonic()))
        self.assertEqual(p.bubble.status_indicator.unread,[('another','old-completion')])

    def test_task_stops_autonomous_route_at_natural_movement_tail(self):
        from unittest.mock import Mock
        p=self.pet;p.walking=True;p.mode='walk';p.gate.state='walk'
        p.roaming.queue=[(500,500)];p.locomotion.phase='body'
        with patch.object(p.locomotion,'request_stop') as stop:
            p.on_activity(dict(kind='status',session='test',turn='one',state='thinking',active=1))
            stop.assert_called_once()
        self.assertFalse(p.walking);self.assertFalse(p.roaming.queue)
        self.assertTrue(p.locomotion.active)
        p.locomotion.phase=None

    def test_active_status_does_not_interrupt_manual_drag_or_disabled_link(self):
        p=self.pet
        for disabled,dragging in ((False,True),(True,False)):
            p.settings['status_actions']=not disabled;p.dragging=dragging;p.walking=True
            with patch.object(p,'stop_walk') as stop:
                p.on_activity(dict(kind='status',session='test',turn='one',state='thinking',active=1))
                stop.assert_not_called()
        p.dragging=False;p.walking=False

if __name__=='__main__':unittest.main()
