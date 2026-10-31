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
    b.message(text);v=b.status_view
    if v.animation.state()==QAbstractAnimation.State.Running:v.animation.setCurrentTime(300)
    APP.processEvents()

class ResizeTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.show();APP.processEvents();settle(self.b,'正在检查')
        self.v=self.b.status_view;self.short_height=self.b.height()
    def tearDown(self):self.b.close();self.b.deleteLater();APP.processEvents()
    def test_two_to_one_scroll_and_height_share_the_same_progress_and_finish(self):
        settle(self.b,LONG);self.assertEqual(self.b.height(),self.short_height+18)
        self.b.message('检查完成');self.assertEqual(self.b.height(),self.short_height+18)
        heights=[]
        for ms in range(0,301,20):
            self.v.animation.setCurrentTime(ms);heights.append(self.b.height())
            self.assertEqual(self.b.height(),self.short_height-18+round(36-18*self.v.progress))
            old,new=self.v.offsets();self.assertAlmostEqual(old,-40*self.v.progress);self.assertAlmostEqual(new,40*(1-self.v.progress))
            if ms==140:self.assertTrue(self.short_height<self.b.height()<self.short_height+18)
        self.assertEqual(heights[-1],self.short_height);self.assertGreater(len(set(heights)),5)
        self.assertTrue(all(0<=a-b<=4 for a,b in zip(heights,heights[1:])))
        self.assertEqual(self.v.animation.state(),QAbstractAnimation.State.Stopped)
        APP.processEvents();self.assertEqual(self.b.height(),self.short_height)
    def test_one_to_two_grows_from_current_height(self):
        self.b.message(LONG);self.assertEqual(self.b.height(),self.short_height)
        self.v.animation.setCurrentTime(150);self.assertTrue(self.short_height<self.b.height()<self.short_height+18)
        self.v.animation.setCurrentTime(300);self.assertEqual(self.b.height(),self.short_height+18)
    def test_bursts_keep_latest_and_redraw_does_not_restart_shared_timeline(self):
        settle(self.b,LONG);self.b.message('正在检查');self.v.animation.setCurrentTime(100)
        height=self.b.height()
        for i in range(20):self.b.message(LONG+'新的进度'+str(i))
        self.assertEqual(self.b.height(),height);self.assertEqual(self.v.animation.currentTime(),100)
        for _ in range(20):self.b.redraw()
        self.assertEqual(self.v.animation.currentTime(),100)
        self.v.animation.setCurrentTime(300);self.assertEqual(self.b.height(),self.short_height)
        APP.processEvents();self.assertEqual(self.v.incoming,LONG+'新的进度19');self.assertEqual(self.b.height(),self.short_height)
        self.v.animation.setCurrentTime(150);self.assertTrue(self.short_height<self.b.height()<self.short_height+18)
        self.v.animation.setCurrentTime(300);self.assertEqual(self.b.height(),self.short_height+18)
    def test_same_line_count_does_not_resize_and_expansion_cancels_old_height_target(self):
        changes=[];self.v.heightChanged.connect(lambda:changes.append(self.v.height()))
        self.b.message('正在验证');self.v.animation.setCurrentTime(300);self.assertFalse(changes)
        settle(self.b,LONG);self.b.message('已完成');self.v.animation.setCurrentTime(150);self.b.toggle_details();self.b.size_transition.complete()
        expanded=self.b.height();self.assertEqual(self.v.animation.state(),QAbstractAnimation.State.Stopped)
        APP.processEvents();self.assertEqual(self.b.height(),expanded)

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
        positions=[];cards=[]
        deck=next(c for c in b.findChildren(CardDeck) if c.isVisible())
        def sample():
            positions.append(b.y() if below else b.y()+b.height())
            cards.append(deck.mapToGlobal(deck.rect().topLeft()).y())
        # This runs inside the same resize signal, before a queued move could
        # hide a temporary wrong position from the next event-loop snapshot.
        v.heightChanged.connect(sample);b.message('检查完成')
        deck=next(c for c in b.findChildren(CardDeck) if c.isVisible())
        for ms in range(0,301,20):v.animation.setCurrentTime(ms)
        self.assertTrue(positions);self.assertEqual(len(set(positions)),1)
        self.assertEqual(positions[-1],self.pet.y()+self.pet.height()+8 if below else self.pet.y()-8)
        if not below:self.assertEqual(len(set(cards)),1)
        self.assertEqual(b.height(),short_height)
    def test_head_anchor_and_token_card_stay_fixed_above_pet(self):self.exercise(500,False)
    def test_near_top_edge_does_not_flip_sides_when_two_lines_become_one(self):
        self.exercise(APP.primaryScreen().availableGeometry().top()+170,True)
