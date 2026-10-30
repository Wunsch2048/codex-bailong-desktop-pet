"""Cost navigation must capture real children and safely cancel stale covers."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest
from project_cost_ui import ProjectCosts
from data_page_motion import PageFade

APP=QApplication.instance() or QApplication([])

def ink_count(pixmap):
    image=pixmap.toImage();count=0
    for y in range(0,image.height(),2):
        for x in range(0,image.width(),2):
            c=image.pixelColor(x,y)
            count+=max(c.red(),c.green(),c.blue())-min(c.red(),c.green(),c.blue())>35 or min(c.red(),c.green(),c.blue())<175
    return count

class CostMotionTests(unittest.TestCase):
    def setUp(self):
        self.motion=patch('project_cost_ui.motion_enabled',return_value=True);self.motion.start()
        self.host=QWidget();layout=QVBoxLayout(self.host);self.view=ProjectCosts();layout.addWidget(self.view);self.host.resize(290,460)
        self.row=dict(id='synthetic',name='项目示例',path='D:/Projects/demo',cost=28.6,parts=[16.59,2.29,9.72],tokens=95_000_000,pending_tokens=0,sessions=2,archived=False,models=['gpt-6.1-sol'],model_usage=[dict(model='gpt-6.1-sol',tokens=95_000_000,cost=28.6,pending_tokens=0)])
        self.view.set_data(dict(ranges={'all':[self.row]}),'all');self.host.show();QTest.qWait(10)
    def tearDown(self):
        self.host.close();self.host.deleteLater();APP.processEvents();self.motion.stop()
    def prepared(self,item):
        self.view.select(item);APP.processEvents();APP.processEvents()
        self.view.detail_motion.animation.pause()
        return self.view.detail_motion
    def test_enter_and_return_snapshots_contain_text_before_animation_ends(self):
        for row in (self.row,None):
            motion=self.prepared(row)
            self.assertIsNotNone(motion.next_frame)
            self.assertGreater(ink_count(motion.next_frame),200,'New page snapshot lost all its child text')
            motion.animation.setCurrentTime(motion.animation.duration());APP.processEvents()
            self.assertTrue(self.view.updatesEnabled());self.assertFalse(motion.isVisible())
    def test_target_matches_live_page_without_cover(self):
        motion=self.prepared(self.row);target=motion.next_frame.copy()
        motion.animation.setCurrentTime(motion.animation.duration());APP.processEvents()
        # Verify the final page pixels, not only selected/state properties.
        self.assertEqual(target.toImage(),PageFade.snapshot(self.view).toImage())
    def test_latest_reverse_wins_before_queued_preparation(self):
        self.view.select(self.row);self.view.select(None);APP.processEvents();APP.processEvents()
        motion=self.view.detail_motion;self.assertIsNone(self.view.selected)
        self.assertGreater(ink_count(motion.next_frame),200)
        motion.animation.setCurrentTime(motion.animation.duration());APP.processEvents();self.assertFalse(motion.isVisible())
    def test_hide_cancels_pending_cover_and_stops_motion(self):
        self.view.select(self.row);self.host.hide();APP.processEvents();APP.processEvents()
        self.assertFalse(self.view.detail_motion.isVisible());self.assertIsNone(self.view.detail_motion.frame)
        self.assertEqual(self.view.detail_motion.animation.state(),QAbstractAnimation.State.Stopped)
        self.assertTrue(self.view.updatesEnabled())
    def test_parent_freeze_is_not_overridden_by_queued_cost_animation(self):
        self.view.select(self.row);self.host.setUpdatesEnabled(False);APP.processEvents();APP.processEvents()
        self.assertFalse(self.host.updatesEnabled());self.assertFalse(self.view.updatesEnabled())
        self.assertIsNone(self.view.detail_motion.frame)
        self.host.setUpdatesEnabled(True);self.assertEqual(self.view.selected,self.row['id'])
        self.assertGreater(ink_count(PageFade.snapshot(self.view)),200)
    def test_snapshot_failure_releases_overlay_and_keeps_live_target_usable(self):
        frame=PageFade.snapshot(self.view);self.view.selected=self.row['id'];self.view.refresh();self.view._detail_transition+=1
        self.view.detail_motion.hold(frame,self.view.rect())
        with patch.object(PageFade,'snapshot',side_effect=RuntimeError('injected capture failure')):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                self.view._present_detail(self.view._detail_transition,frame,True)
        self.assertFalse(self.view.detail_motion.isVisible());self.assertIsNone(self.view.detail_motion.frame)
        self.assertTrue(self.view.updatesEnabled());self.assertGreater(ink_count(PageFade.snapshot(self.view)),200)

if __name__=='__main__':unittest.main()
