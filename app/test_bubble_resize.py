import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication
from compact_bubble import CompactBubble
from desktop import DesktopPet
from dashboard_cards import CardDeck

APP=QApplication.instance() or QApplication([])
LONG='正在检查多个文件中的状态更新与界面变化，随后核对测试结果。'

def settle(b,text):
    b.message(text);b.size_transition.complete();APP.processEvents()
    b.size_transition.complete();APP.processEvents()

class ResizeTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.show();APP.processEvents();settle(self.b,'正在检查')
        self.v=self.b.status_view;self.short_height=self.b.height()
    def tearDown(self):self.b.close();self.b.deleteLater();APP.processEvents()
    def test_two_to_one_height_has_monotonic_intermediate_frames(self):
        settle(self.b,LONG);high=self.b.height();self.assertGreater(high,self.short_height)
        self.b.message('检查完成');t=self.b.size_transition
        self.assertTrue(t.running);self.assertTrue(t.morph.status_height_only)
        heights=[]
        for ms in range(0,t.animation.duration(),20):
            t.animation.setCurrentTime(ms);heights.append(t.visible_geometry().height())
        t.complete();heights.append(self.b.height())
        self.assertEqual(heights[0],high);self.assertEqual(heights[-1],self.short_height)
        self.assertGreater(len(set(heights)),5)
        self.assertTrue(all(a>=b for a,b in zip(heights,heights[1:])))
    def test_one_to_two_grows_from_current_height(self):
        self.b.message(LONG);t=self.b.size_transition
        self.assertEqual(t.visible_geometry().height(),self.short_height)
        target=t.target_rect.height();self.assertGreater(target,self.short_height)
        t.animation.setCurrentTime(t.animation.duration()//2)
        self.assertTrue(self.short_height<t.visible_geometry().height()<target)
        t.complete();self.assertEqual(self.b.height(),target)
    def test_bursts_keep_latest_and_redraw_does_not_restart_shared_timeline(self):
        settle(self.b,LONG);self.b.message('正在检查');t=self.b.size_transition
        t.animation.setCurrentTime(100);rect=t.visible_geometry()
        for i in range(20):self.b.message(LONG+'新的进度'+str(i))
        for _ in range(20):self.b.redraw()
        self.assertEqual(t.animation.currentTime(),100);self.assertEqual(t.visible_geometry(),rect)
        t.complete();APP.processEvents();t.complete();APP.processEvents()
        self.assertEqual(self.b.status_view.text(),LONG+'新的进度19')
        self.assertGreater(self.b.height(),self.short_height)
    def test_same_line_count_does_not_resize_and_expansion_reaches_full_target(self):
        self.b.message('正在验证');self.assertFalse(self.b.size_transition.running)
        settle(self.b,LONG);self.b.message('已完成');self.b.size_transition.animation.setCurrentTime(100)
        self.b.toggle_details()
        for _ in range(3):self.b.size_transition.complete();APP.processEvents()
        self.assertTrue(self.b.expanded);self.assertEqual(self.b.width(),360)
        self.assertFalse(self.b.size_transition.running)

class AnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.patches=[patch('enhanced.CONFIG',root/'settings.json'),patch('enhanced.STATE_DIR',root),patch('desktop.CONFIG',root/'settings.json'),patch('desktop.STATE_DIR',root)]
        for p in self.patches:p.start()
        self.pet=DesktopPet(monitor=False);self.pet.apply_settings(dict(wandering=False,random_actions=False),save=False)
        self.pet.tick.stop();self.pet.motion_timer.stop();self.pet.show();APP.processEvents()
    def tearDown(self):
        self.pet.close();APP.processEvents()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def exercise(self,y,below):
        self.pet.move(300,y);b=self.pet.bubble;settle(b,'检查');short_height=b.height();settle(b,LONG);self.pet.position_bubble();v=b.status_view
        transition=b.size_transition;start=b.geometry();b.message('检查完成')
        self.assertTrue(transition.running)
        anchors=[]
        for ms in range(0,transition.animation.duration(),20):
            transition.animation.setCurrentTime(ms);rect=transition.visible_geometry()
            anchors.append(rect.y() if below else rect.y()+rect.height())
        transition.complete();APP.processEvents()
        # QRect conversion may round a fractional spring origin by one pixel.
        self.assertLessEqual(max(anchors)-min(anchors),1,anchors)
        self.assertEqual(anchors[0],start.y() if below else start.y()+start.height())
        self.assertEqual(b.height(),short_height)
    def test_head_anchor_and_token_card_stay_fixed_above_pet(self):self.exercise(500,False)
    def test_near_top_edge_does_not_flip_sides_when_two_lines_become_one(self):
        self.exercise(APP.primaryScreen().availableGeometry().top()+170,True)
