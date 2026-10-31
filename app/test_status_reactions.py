import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest
from status_reactions import StatusReactions,classify
from compact_bubble import CompactBubble
from desktop import DesktopPet

APP=QApplication.instance() or QApplication([])
def status(state='working',text='修改代码',session='a',turn='1',**kw):return dict(kind='status',state=state,text=text,session=session,turn=turn,active=1,**kw)

class SchedulerTests(unittest.TestCase):
    def test_burst_is_sampled_once_only_at_boundary_and_uses_latest(self):
        s=StatusReactions(0)
        for i in range(500):s.observe(status(text='执行任务'+str(i)),i/100)
        self.assertIsNone(s.poll(10,boundary=False));self.assertEqual(s.sample_count,0)
        s.observe(status(state='responding',text='正在回复'),10)
        self.assertEqual(s.poll(10,boundary=True).action_id,'01');self.assertEqual(s.sample_count,1)
        self.assertIsNone(s.poll(11,boundary=True));self.assertEqual(s.sample_count,1)
    def test_animation_finish_gap_and_latest_replacement(self):
        s=StatusReactions(0);s.observe(status(state='thinking'),0)
        self.assertEqual(s.poll(8,boundary=True).kind,'thinking')
        s.finished(12.5);s.observe(status(state='responding'),13)
        self.assertIsNone(s.poll(20,boundary=True));self.assertIsNone(s.poll(25,boundary=True))
        self.assertEqual(s.poll(27,boundary=True).kind,'reply')
    def test_repeated_category_and_stale_state_do_not_repeat_every_poll(self):
        s=StatusReactions(0);s.observe(status(),0);self.assertIsNotNone(s.poll(8,boundary=True))
        for t in (26,44,62):s.observe(status(),t);self.assertIsNone(s.poll(t,boundary=True))
        s.observe(status(),80);self.assertIsNotNone(s.poll(80,boundary=True))
        self.assertIsNone(s.poll(200,boundary=True))
    def test_complete_is_explicit_deduplicated_and_waits_for_current_clip(self):
        s=StatusReactions(0);s.observe(status(text='检查完成，继续处理'),0)
        self.assertNotEqual(classify(s.latest).kind,'complete')
        self.assertTrue(s.queue_completion(dict(session='a',turn='1'),2));self.assertFalse(s.queue_completion(dict(session='a',turn='1'),3))
        self.assertIsNone(s.poll(4,boundary=False));s.finished(4);self.assertIsNone(s.poll(10,boundary=True))
        self.assertEqual(s.poll(12,boundary=True).kind,'complete')
    def test_new_turn_supersedes_old_celebration_and_multi_session_keeps_working(self):
        s=StatusReactions(0);s.queue_completion(dict(session='a',turn='1'),1);s.observe(status(turn='2'),2)
        self.assertIsNone(s.completion)
        s.observe(status(session='b',activity='research'),3);s.observe(status(state='complete',session='a',turn='2'),4)
        self.assertEqual(s.poll(8,boundary=True).session,'b')
    def test_long_deferred_completion_expires(self):
        s=StatusReactions(0);s.queue_completion(dict(session='a',turn='1'),0)
        self.assertIsNone(s.poll(121,boundary=True));self.assertIsNone(s.completion)
    def test_alternating_states_cannot_bypass_per_action_repeat_gap(self):
        s=StatusReactions(0);s.observe(status(),0);self.assertEqual(s.poll(8,boundary=True).action_id,'22')
        s.observe(status(state='responding'),26);self.assertEqual(s.poll(26,boundary=True).action_id,'01')
        s.observe(status(),44);self.assertIsNone(s.poll(44,boundary=True))
    def test_known_states_have_suitable_existing_actions_and_errors_are_reviewed(self):
        for event,expected in [(status(state='thinking'),'quota'),(status(activity='research'),'quota'),(status(activity='verify'),'quota'),(status(activity='edit'),'22'),(status(state='responding'),'01'),(status(text='已经定位到原因'),'04'),(status(text='测试未通过，继续排查'),'quota'),(status(state='interrupted'),'idle2')]:self.assertEqual(classify(event).action_id,expected)
        self.assertIsNone(classify(status(state='offline')))

class ScrollTests(unittest.TestCase):
    def setUp(self):self.b=CompactBubble();self.b.status='正在检查代码';self.b.redraw();self.b.show();APP.processEvents();self.view=self.b.status_view;self.view.animation.stop();self.view.current=self.view.incoming=self.view.text()
    def tearDown(self):self.b.close();self.b.deleteLater();APP.processEvents()
    def test_scroll_moves_up_and_is_clipped_without_moving_quota(self):
        size=self.b.size();self.b.message('正在读取新的状态');self.assertEqual(self.view.animation.state(),QAbstractAnimation.State.Running)
        self.view.animation.setCurrentTime(140);old,new=self.view.offsets();self.assertLess(old,0);self.assertGreater(new,0)
        self.assertEqual(self.b.size(),size);self.assertTrue(self.b.rect().contains(self.view.geometry()))
        self.view.animation.setCurrentTime(300);self.assertEqual(self.view.current,'正在读取新的状态')
    def test_redraws_keep_widget_and_animation_progress_and_coalesce_burst(self):
        self.b.message('状态B');self.view.animation.setCurrentTime(100);progress=self.view.animation.currentTime()
        for i in range(20):self.b.status='最新状态'+str(i);self.b.redraw()
        self.assertIs(self.b.status_view,self.view);self.assertEqual(self.view.animation.currentTime(),progress);self.assertEqual(self.view.pending,'最新状态19')
        self.view.animation.setCurrentTime(300);APP.processEvents();self.view.animation.setCurrentTime(300);APP.processEvents()
        self.assertEqual(self.view.current,'最新状态19');self.assertIsNone(self.view.pending)
    def test_expansion_keeps_full_plain_text_and_collapsed_compact_size(self):
        self.b.message('很长的完整状态内容。'*25);self.b.toggle_details();self.b.size_transition.complete();APP.processEvents()
        self.assertTrue(self.view.full);self.assertEqual(self.view.text(),self.b.status)
        expanded=self.b.height();self.b.toggle_details();self.b.size_transition.complete();APP.processEvents();self.assertLess(self.b.height(),expanded)

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.patches=[patch('enhanced.CONFIG',root/'settings.json'),patch('enhanced.STATE_DIR',root),patch('desktop.CONFIG',root/'settings.json'),patch('desktop.STATE_DIR',root)]
        for p in self.patches:p.start()
        self.pet=DesktopPet(monitor=False);self.pet.show();self.pet.apply_settings(dict(wandering=False,random_actions=False));self.pet.tick.stop();self.pet.motion_timer.stop();APP.processEvents()
    def tearDown(self):
        self.pet.close();APP.processEvents()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def boundary(self,now):
        with patch('desktop.time.monotonic',return_value=now),patch.object(self.pet.player,'advance',return_value=(None,True)):
            self.pet.player.ended=True;self.pet.animate()
    def test_statuses_never_interrupt_clip_and_latest_is_used_at_later_boundary(self):
        self.pet.gate.state='idle';self.pet.play(self.pet.variants[0],'variant');current=self.pet.current
        clock=time.monotonic();self.pet.reactions=StatusReactions(clock)
        for i in range(60):self.pet.on_activity(status(text='正在执行'+str(i)))
        self.assertIs(self.pet.current,current);self.assertEqual(self.pet.mode,'variant')
        self.boundary(clock+4.5);self.assertEqual(self.pet.mode,'idle')
        self.pet.on_activity(status(state='responding',text='正在回复'))
        self.pet.continuous.target(self.pet.reactions,clock+11)
        with patch('pet.Pet.play_click_sound') as sound,patch.object(self.pet,'refresh_quota') as quota:
            self.boundary(clock+14);self.assertEqual(self.pet.mode,'reaction');self.assertEqual(self.pet.current['id'],'01');sound.assert_not_called();quota.assert_not_called()
    def test_completion_notification_is_immediate_but_celebration_waits(self):
        self.pet.gate.state='idle';self.pet.play(self.pet.variants[0],'variant');item=self.pet.current;clock=time.monotonic();self.pet.reactions=StatusReactions(clock)
        with patch.object(self.pet,'notify') as notify,patch.object(self.pet,'refresh_quota'):
            self.pet.on_activity(dict(kind='complete',session='s',turn='t',title='完成样例'));notify.assert_called_once()
        self.assertIs(self.pet.current,item);self.assertEqual(self.pet.mode,'variant')
        self.boundary(clock+4.5);self.assertEqual(self.pet.mode,'idle');self.assertIsNotNone(self.pet.pending_completion)
        self.boundary(clock+14);self.assertEqual(self.pet.mode,'task');self.assertEqual(self.pet.current['id'],'18')
    def test_reaction_does_not_rewrite_status_or_query_quota_and_setting_can_disable(self):
        clock=time.monotonic();self.pet.reactions=StatusReactions(clock);self.pet.on_activity(status(state='thinking'))
        text=self.pet.bubble.status
        self.pet.continuous.target(self.pet.reactions,clock+1)
        with patch.object(self.pet,'refresh_quota') as quota,patch('pet.Pet.play_click_sound') as sound:
            self.boundary(clock+10);self.assertEqual(self.pet.current['id'],'quota');self.assertEqual(self.pet.mode,'reaction');quota.assert_not_called();sound.assert_not_called()
        self.assertEqual(self.pet.bubble.status,text)
        self.pet.apply_settings({'status_actions':False});self.boundary(clock+15);self.boundary(clock+80);self.assertEqual(self.pet.mode,'idle')

if __name__=='__main__':unittest.main()
