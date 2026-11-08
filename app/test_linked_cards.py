import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
from PySide6.QtCore import QRect,QPointF,Qt
from PySide6.QtGui import QPixmap,QPainter
from PySide6.QtWidgets import QWidget
from compact_bubble import CompactBubble
from daily_report import DailyReport
from test_daily_report import sample,APP

class LinkedTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.move(120,630);self.b.show();APP.processEvents()
        self.r=DailyReport(self.b);self.b.report=self.r;self.r.set_snapshot(sample());self.r.open();self.r.animation.setCurrentTime(self.r.animation.duration());APP.processEvents()
    def tearDown(self):self.b.close();self.b.deleteLater();APP.processEvents()
    def test_open_report_morphs_with_settings_and_back_to_normal(self):
        b,r=self.b,self.r
        settings=QWidget()
        original_width=r.content_geometry().width()
        for navigate in (lambda:b.show_page('settings',settings),b.return_to_status):
            start=QRect(r.content_geometry())
            navigate()
            transition=b.size_transition
            self.assertTrue(r.requested and r.follow.committed)
            parts=r.follow.module_morph.shared_parts
            self.assertIn('chrome_0',parts)
            self.assertIn('chrome_1',parts)
            self.assertGreaterEqual(sum(key.startswith('body_') for key in parts),2)
            transition.animation.setCurrentTime(transition.animation.duration()//3)
            host=transition.morph.geometry(transition.raw_progress)
            middle=r.follow.geometry()
            self.assertAlmostEqual(middle.width(),host.width(),delta=1)
            self.assertAlmostEqual(middle.bottom()+r.GAP,host.top(),delta=1)
            self.assertNotEqual(middle.width(),start.width())
            self.assertNotEqual(middle.width(),transition.target_rect.width())
            transition.complete()
            r.follow.release()
            self.assertTrue(r.requested and r.surface.isVisible())
            self.assertEqual(r.content_geometry(),r.geometry_for_host(b.geometry()))
        self.assertEqual(r.content_geometry().width(),original_width)
    def test_report_uses_visible_card_edges_and_stable_native_canvas_in_both_directions(self):
        b=self.b;r=self.r
        for _ in range(2):
            initial=r.content_geometry();b.toggle_details();t=b.size_transition;t.animation.pause();self.assertTrue(r.follow.active)
            self.assertEqual(r.follow.geometry(0.).toRect(),initial);canvas=QRect(r.geometry());previous=None
            for i in range(0,100,4):
                at=i/100;t.advance(at);host=t.morph.geometry(at);report=r.follow.geometry()
                self.assertAlmostEqual(report.left(),host.left(),delta=.01);self.assertAlmostEqual(report.width(),host.width(),delta=.01)
                self.assertAlmostEqual(report.bottom()+r.GAP,host.top(),delta=1)
                self.assertEqual(r.geometry(),canvas)
                if previous:self.assertLess(abs(report.x()-previous.x()),12)
                previous=report
            target=QRect(t.target_rect);t.animation.resume();t.complete();r.follow.release()
            self.assertFalse(r.follow.active);self.assertTrue(r.surface.isVisible());self.assertEqual(r.content_geometry().x(),target.x());self.assertEqual(r.content_geometry().width(),target.width())
            self.assertEqual(r.content_geometry().bottom()+1+r.GAP,target.y())
    def test_preparation_restores_updates_only_under_hidden_target_content(self):
        b=self.b;states=[];original=b.setUpdatesEnabled
        def observe(enabled):
            if enabled and b.size_transition.preparing:states.append(b.content.isVisible())
            return original(enabled)
        self.r.dismiss();self.r.animation.setCurrentTime(self.r.animation.duration())
        with patch.object(b,'setUpdatesEnabled',side_effect=observe):b.set_mode('mini')
        self.assertTrue(states);self.assertFalse(any(states));b.size_transition.complete();b.size_transition.release_landing()
        with patch.object(b,'setUpdatesEnabled',side_effect=observe):b.set_mode('auto')
        self.assertFalse(any(states));b.size_transition.complete()
    def test_landing_backing_store_is_cleared_while_visible_before_reuse(self):
        landing=self.b.size_transition.landing;image=QPixmap(60,40);image.fill(Qt.GlobalColor.red)
        landing.present(image,QRect(10,10,60,40));calls=[];repaint=landing.repaint
        with patch.object(landing,'repaint',side_effect=lambda:(calls.append((landing.isVisible(),landing.image is None)),repaint())):landing.release()
        self.assertEqual(calls,[(True,True)]);self.assertIsNone(landing.image);self.assertFalse(landing.isVisible())
        landing.prepare(QRect(20,20,60,40));self.assertEqual(landing.grab().toImage().pixelColor(30,20).alpha(),0);landing.release()
    def test_report_open_in_flight_queues_expansion_without_teleport(self):
        r=self.r;r.dismiss();r.animation.setCurrentTime(r.animation.duration());r.open();r.animation.setCurrentTime(100)
        fraction=r.fraction;geometry=QRect(r.geometry());self.b.toggle_details()
        self.assertFalse(self.b.size_transition.running);self.assertEqual(r.geometry(),geometry);self.assertEqual(r.fraction,fraction)
        r.animation.setCurrentTime(r.animation.duration());self.assertTrue(self.b.size_transition.running)
        self.b.size_transition.complete();self.assertTrue(r.requested)
    def test_mini_closes_report_without_starting_report_follow(self):
        self.b.set_mode('mini');self.assertFalse(self.r.follow.active);self.assertTrue(self.r._animating)
        self.r.animation.setCurrentTime(self.r.animation.duration());self.b.size_transition.complete()
        self.assertFalse(self.r.isVisible());self.assertFalse(self.r.follow.landing.isVisible())
    def test_latest_report_refresh_waits_for_host_handoff(self):
        import copy
        self.b.toggle_details();t=self.b.size_transition;t.animation.pause();r=self.r;key=r.follow.new.cacheKey();canvas=QRect(r.geometry())
        latest=copy.deepcopy(sample());latest['report']['messages']=12345;r.set_snapshot(latest)
        self.assertTrue(r._pending_rebuild);self.assertEqual(r.follow.new.cacheKey(),key);self.assertEqual(r.geometry(),canvas)
        t.animation.resume();t.complete();r.follow.release()
        self.assertFalse(r._pending_rebuild);self.assertEqual(r.report['messages'],12345);self.assertEqual(r.content_geometry().width(),self.b.width())
    def test_live_native_report_is_suppressed_before_any_target_layout_and_restored_after_handoff(self):
        r=self.r;f=r.follow;native=QRect(r.geometry());opacity=r.windowOpacity();f.begin()
        self.assertEqual(r.windowOpacity(),0.);self.assertTrue(f.shield.isVisible());self.assertIsNotNone(f.shield.image)
        f.commit(self.b.content_geometry().adjusted(-50,0,50,0));canvas=QRect(f.landing.geometry())
        self.assertIsNone(f.shield.image);self.assertTrue(f.landing.isVisible())
        for t in (0.,.01,.15,.4,.7,.99,1.):
            f.advance(t);self.assertEqual(r.windowOpacity(),0.);self.assertEqual(r.geometry(),native);self.assertEqual(f.landing.geometry(),canvas)
        f.finish();self.assertAlmostEqual(r.windowOpacity(),opacity);self.assertFalse(r.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertTrue(f.landing.isVisible());f.release();self.assertIsNone(f.frame);self.assertIsNone(f.landing.image)
    def test_preparation_cancel_restores_opacity_input_and_removes_both_surfaces(self):
        f=self.r.follow;f.begin();self.assertTrue(f.shield.isVisible());f.cancel()
        self.assertEqual(self.r.windowOpacity(),1.);self.assertIsNone(f.landing.image);self.assertIsNone(f.shield.image);self.assertFalse(f.active)
    def test_complementary_mix_has_no_alpha_or_background_brightness_pulse(self):
        from PySide6.QtCore import QRectF
        f=self.r.follow;f.begin();f.commit(self.b.content_geometry().translated(-50,0))
        # Complete opaque snapshots of identical colour must stay identical;
        # source-over fading two half-opacity layers previously lost alpha.
        f.old.fill(Qt.GlobalColor.red);f.new.fill(Qt.GlobalColor.red)
        for t in (.01,.2,.4,.5,.7,.99):
            f.advance(t);rect=f.geometry().translated(-f.canvas.x(),-f.canvas.y());ratio=f.frame.devicePixelRatioF()
            colour=f.frame.toImage().pixelColor(round(rect.center().x()*ratio),round(rect.center().y()*ratio))
            self.assertGreaterEqual(colour.alpha(),254);self.assertGreaterEqual(colour.red(),254);self.assertEqual(colour.green(),0)
        f.cancel()
    def test_live_status_height_changes_use_the_same_fixed_presentation_canvas(self):
        b=self.b;r=self.r;scroller=b.status_view
        for text in ('测试状态更新内容很长，需要换行并连续调整卡片高度。'*3,'正在思考'):
            scroller.set_status(text);native=None
            for ms in (40,80,130,180,240,290):
                scroller.animation.setCurrentTime(ms)
                if not r.follow.active:continue
                self.assertTrue(r.follow.status_tracking);self.assertEqual(r.windowOpacity(),0.)
                q=r.follow.geometry();self.assertAlmostEqual(q.bottom()+r.GAP,b.y(),delta=1)
                if native is None:native=QRect(r.geometry())
                self.assertEqual(r.geometry(),native)
            self.assertIsNotNone(native)
            scroller.animation.resume();scroller.animation.setCurrentTime(300);r.follow.release()
            self.assertFalse(r.follow.active);self.assertEqual(r.windowOpacity(),1.)
    def test_navigation_during_status_height_change_releases_its_previous_opacity_hold(self):
        b=self.b;r=self.r;b.status_view.set_status('正在检查较长的状态信息和日报窗口过渡。'*3);b.status_view.animation.setCurrentTime(150)
        self.assertTrue(r.follow.status_tracking);self.assertEqual(r.windowOpacity(),0.)
        b.toggle_details();self.assertFalse(r.follow.status_tracking);self.assertTrue(r.follow.active)
        b.size_transition.complete();r.follow.release();self.assertEqual(r.windowOpacity(),1.)
        self.assertFalse(r.follow.active);self.assertFalse(r.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

if __name__=='__main__':unittest.main()
