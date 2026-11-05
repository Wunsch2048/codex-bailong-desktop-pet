"""Decorative action captions cannot replace active task text."""
import os,unittest,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
import test_edge_dock as fixture

class ActionSpeechTests(unittest.TestCase):
    setUp=fixture.DockTests.setUp
    tearDown=fixture.DockTests.tearDown
    def ready(self):
        p=self.p;p.apply_settings(dict(self_talk=True,talk_quiet=False),save=False)
        p.status_hold=0;p._priority=1;p.message_priority=0
        return p
    def test_random_action_line_respects_master_switch(self):
        p=self.ready();p.settings['self_talk']=False
        with patch('enhanced.EnhancedPet.say') as say:p.say_action_line({'line':'action caption'})
        say.assert_not_called()
    def test_aggregate_busy_blocks_action_even_if_last_session_is_idle(self):
        p=self.ready();p.last_activity={'state':'idle','active':0}
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=True),patch('enhanced.EnhancedPet.say') as say:
            p.say_action_line({'line':'action caption'})
        say.assert_not_called()
    def test_clicked_action_line_is_allowed_during_work(self):
        p=self.ready();p._priority=5;p._interactive_action=True
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=True),patch('enhanced.EnhancedPet.say') as say:
            p.say_action_line({'line':'clicked caption'})
        say.assert_called_once_with('clicked caption',4000)
    def test_manual_action_line_is_allowed_during_work(self):
        p=self.ready();p._priority=5;p._manual_action=True
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=True),patch('enhanced.EnhancedPet.say') as say:
            p.say_action_line({'line':'manual caption'})
        say.assert_called_once_with('manual caption',4000)
    def test_work_status_refresh_keeps_explicit_clicked_caption(self):
        p=self.ready();p._priority=5;p._interactive_action=True
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=True):
            p.say_action_line({'line':'clicked caption'});p.quiet_background_speech()
        self.assertEqual(p._speech_source,'action');self.assertEqual(p.bubble._speech_text,'clicked caption')
    def test_quiet_work_blocks_periodic_automatic_speech(self):
        p=self.ready();p.settings['talk_quiet']=True;p._allow_talk_busy=False
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=True),patch('enhanced.EnhancedPet.say') as say:
            p.say('unsolicited periodic caption')
        say.assert_not_called()
    def test_idle_action_line_is_removed_when_work_starts(self):
        p=self.ready()
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=False):p.say_action_line({'line':'idle caption'})
        self.assertEqual(p.bubble._speech_text,'idle caption')
        p.on_activity(dict(kind='status',state='working',active=1,session='11111111-1111-4111-8111-111111111111',turn='speech-turn',text='正在执行任务'))
        self.assertEqual(p.bubble._speech_text,'');self.assertEqual(p.status_hold,0)
    def test_disabling_master_clears_existing_automatic_caption(self):
        p=self.ready()
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=False):
            p.say_action_line({'line':'idle caption'});p.apply_settings(dict(self_talk=False),save=False)
        self.assertEqual(p.bubble._speech_text,'')
    def test_completion_and_error_messages_survive(self):
        p=self.ready();p.settings['self_talk']=False
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=True),patch('enhanced.EnhancedPet.say') as say:
            for priority,text in ((10,'任务完成'),(5,'素材读取失败')):
                p._priority=priority;p.status_hold=0;p.say(text)
            self.assertEqual(say.call_count,2)
    def test_periodic_opt_in_is_separate_from_action_captions(self):
        p=self.ready();p._allow_talk_busy=True
        with patch.object(p.bubble.status_indicator,'is_busy',return_value=True),patch('enhanced.EnhancedPet.say') as say:
            p.say('用户允许工作时显示的定时台词')
        say.assert_called_once()

if __name__=='__main__':unittest.main()
