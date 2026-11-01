import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
import tempfile
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from quota_summary import QuotaSummary
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
from pet import Pet
from enhanced import EnhancedPet

app=QApplication.instance() or QApplication([])

def settle():
    app.processEvents()
    for window in app.topLevelWidgets():
        transition=getattr(window,'size_transition',None)
        if transition:transition.complete()
    app.processEvents()


def cheap_load(self,item):
    im=QPixmap(256,256);im.fill(Qt.GlobalColor.transparent)
    return [im]*8

class UiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.config_patch=patch('enhanced.CONFIG',__import__('pathlib').Path(self.tmp.name)/'settings.json')
        self.config_patch.start()
        self.loader=patch.object(Pet,'load',cheap_load);self.loader.start()
        self.pet=EnhancedPet(monitor=False)
        self.pet.show()
    def tearDown(self):
        self.pet.close();settle();self.loader.stop();self.config_patch.stop();self.tmp.cleanup()
    def test_head_bubble_keeps_progress_when_status_changes(self):
        self.pet.update_quota([{'name':'5小时','remaining':41,'resetsAt':None}],__import__('time').time(),'live')
        self.pet.on_activity({'kind':'status','state':'working','text':'测试进度','active':1})
        self.pet.status_hold=0;self.pet.flush_status()
        self.assertEqual(self.pet.bubble.status,'测试进度')
        self.assertEqual([w['remaining'] for b in self.pet.bubble.findChildren(QuotaSummary) if b.isVisible() for w in b.windows], [41])
        self.assertTrue(self.pet.bubble.isVisible())
    def test_failure_keeps_marked_quota_and_closing_stops_timers(self):
        self.pet.update_quota([{'name':'一周','remaining':80,'resetsAt':None}],__import__('time').time(),'live')
        self.pet.quota_failed('test')
        self.assertIn('上次记录',self.pet.bubble.quota_caption)
        self.assertEqual(self.pet.quota_windows[0]['remaining'],80)
        self.pet.close()
        self.assertFalse(self.pet.motion_timer.isActive())
    def test_completion_stops_motion_and_notifies(self):
        self.pet.start_walk()
        self.assertTrue(self.pet.walking)
        with patch.object(self.pet,'notify') as notify,patch.object(self.pet,'refresh_quota'):
            self.pet.on_activity({'kind':'complete','session':'11111111-1111-4111-8111-111111111111','turn':'turn-1','title':'测试任务'})
            self.assertFalse(self.pet.walking)
            self.assertEqual(self.pet.current['id'],'18')
            self.assertIn('完成',self.pet.bubble.status)
            self.assertEqual(self.pet.bubble.status_indicator.visual(),'attention')
            notify.assert_called_once()
    def test_only_deliberate_interaction_plays_sound(self):
        with patch.object(Pet,'play_click_sound') as sound:
            self.pet.choose(self.pet.variants[0])
            sound.assert_not_called()
            self.pet.single_click()
            sound.assert_called_once()
            self.pet.choose(self.pet.variants[1])
            self.assertEqual(sound.call_count,1)
            with patch.object(self.pet,'refresh_quota'):
                self.pet.quota()
            self.assertEqual(sound.call_count,2)
    def test_bubble_is_owned_nonactivating_and_above_character(self):
        self.pet.move(300,450)
        self.pet.bubble.redraw()
        self.pet.position_bubble()
        self.assertIs(self.pet.bubble.parentWidget(),self.pet)
        self.assertTrue(self.pet.bubble.isWindow())
        self.assertTrue(self.pet.bubble.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertLess(self.pet.bubble.geometry().bottom(),self.pet.geometry().top())
        self.pet.bubble.toggle_details();settle();self.pet.position_bubble()
        self.assertLess(self.pet.bubble.geometry().bottom(),self.pet.geometry().top())
        self.pet.bubble.toggle_details();settle();self.pet.position_bubble()
        self.assertLess(self.pet.bubble.geometry().bottom(),self.pet.geometry().top())
    def test_bubble_text_and_quota_height_are_reserved_before_positioning(self):
        self.pet.bubble.windows=[{'name':'一周','remaining':88}]
        self.pet.bubble.status='正在检查气泡位置和文字换行，自动动作与任务完成提醒都应保持安静。'
        self.pet.bubble.redraw()
        settle()
        needed=self.pet.bubble.layout.heightForWidth(self.pet.bubble.width())
        self.assertGreater(self.pet.bubble.height(),80)
        self.assertGreaterEqual(self.pet.bubble.height(),needed)
    def test_token_refresh_updates_calendar_without_replacing_activity_or_gesture(self):
        status=self.pet.bubble.status;current=self.pet.current
        snapshot=dict(month='2026-10',days={'2026-10-18':150},total=150)
        with patch.object(Pet,'play_click_sound') as sound:
            self.pet.on_activity(dict(kind='token_usage',snapshot=snapshot))
            self.assertEqual(self.pet.bubble.token_snapshot,snapshot)
            self.assertEqual(self.pet.bubble.status,status);self.assertIs(self.pet.current,current);sound.assert_not_called()
            self.pet.on_activity(dict(kind='token_usage_error'));self.assertTrue(self.pet.bubble.token_snapshot['partial'])
    def test_token_range_is_saved_without_sound_or_interrupting_animation(self):
        current=self.pet.current
        with patch.object(Pet,'play_click_sound') as sound,patch.object(self.pet,'refresh_quota') as quota:
            self.pet.bubble.select_token_range('day')
            self.assertEqual(self.pet.settings['token_chart_range'],'day');self.assertIs(self.pet.current,current)
            quota.assert_not_called();sound.assert_not_called()
        import json
        from pathlib import Path
        self.assertEqual(json.loads((Path(self.tmp.name)/'settings.json').read_text(encoding='utf-8'))['token_chart_range'],'day')

if __name__=='__main__':unittest.main()
