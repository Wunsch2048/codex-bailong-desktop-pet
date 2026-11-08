"""The report's own HWND, not just its handoff guards, needs a cold raster."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtCore import QEvent
from compact_bubble import CompactBubble
from daily_report import DailyReport
from test_daily_report import APP,sample

class ReportColdSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.move(100,650);self.b.show();APP.processEvents()
        self.r=DailyReport(self.b);self.b.report=self.r;self.r.set_snapshot(sample())
    def tearDown(self):
        self.r.animation.stop();self.r.follow.cancel();self.r.close();self.b.close()
        self.r.deleteLater();self.b.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
    def test_report_is_seeded_then_masked_until_an_exposed_repaint(self):
        r=self.r;events=[];show=r.show
        def publish(widget,image):
            if widget is r:events.append(('seed',r.isVisible(),r.windowOpacity(),image))
            return True
        def shown():events.append(('show',r._open_native_seeded,r.windowOpacity()));show()
        with patch('daily_report.QApplication.platformName',return_value='windows'),patch('native_landing.publish',side_effect=publish),patch.object(r,'show',side_effect=shown),patch.object(r,'setWindowOpacity',wraps=r.setWindowOpacity) as opacity:
            r.open()
            self.assertEqual(events,[('seed',False,1.,None),('show',True,0.)])
            self.assertTrue(r._open_present_waiting);self.assertEqual(r.fraction,0.)
            with patch.object(r.windowHandle(),'isExposed',return_value=False):r._open_present_ready()
            self.assertTrue(r._open_present_waiting);self.assertEqual(r.windowOpacity(),0.)
            order=[]
            with patch.object(r.windowHandle(),'isExposed',return_value=True),patch.object(r,'repaint',side_effect=lambda:order.append('paint')),patch.object(r,'_start_animation',side_effect=lambda target:order.append('animate')):
                r._open_present_ready()
            self.assertFalse(r._open_present_waiting);self.assertEqual(r.windowOpacity(),1.)
            self.assertEqual(order,['paint','animate']);self.assertEqual([c.args[0] for c in opacity.call_args_list],[0.,1.])
    def test_failed_native_seed_retains_masked_open_and_records_error(self):
        r=self.r
        def publish(widget,image):
            if widget is r:raise OSError('synthetic layered failure')
            return True
        with patch('daily_report.QApplication.platformName',return_value='windows'),patch('native_landing.publish',side_effect=publish),patch.object(r,'setWindowOpacity',wraps=r.setWindowOpacity) as opacity:
            r.open()
            self.assertFalse(r._open_native_seeded);self.assertIn('synthetic',r._open_native_error)
            with patch.object(r.windowHandle(),'isExposed',return_value=True):r._open_present_ready()
            self.assertEqual([c.args[0] for c in opacity.call_args_list],[0.,1.])
            self.assertTrue(r.isVisible());self.assertEqual(r.windowOpacity(),1.)
    def test_dismiss_before_expose_cancels_mask_and_late_ready_callback(self):
        r=self.r
        with patch('daily_report.QApplication.platformName',return_value='windows'),patch('native_landing.publish',return_value=True):
            r.open();self.assertTrue(r._open_present_waiting);r.dismiss()
            self.assertFalse(r.isVisible());self.assertFalse(r.requested);self.assertEqual(r.windowOpacity(),1.)
            with patch.object(r,'_start_animation') as animate:r._open_present_ready();animate.assert_not_called()
    def test_repeated_open_waits_for_a_new_expose_each_time(self):
        r=self.r
        with patch('daily_report.QApplication.platformName',return_value='windows'),patch('native_landing.publish',return_value=True),patch.object(r.follow.shield,'present') as shield:
            for visit in range(3):
                r.open();self.assertTrue(r._open_present_waiting);self.assertEqual(r.windowOpacity(),0.)
                with patch.object(r.windowHandle(),'isExposed',return_value=True):r._open_present_ready()
                r.animation.setCurrentTime(r.animation.duration());r.dismiss();r.animation.setCurrentTime(r.animation.duration())
                self.assertFalse(r.isVisible());self.assertEqual(r.windowOpacity(),1.)
            shield.assert_not_called()
    def test_reversal_keeps_current_frame_without_reseeding_visible_window(self):
        r=self.r;r.open();r.animation.setCurrentTime(90);r.dismiss();r.animation.setCurrentTime(15);fraction=r.fraction
        with patch('daily_report.QApplication.platformName',return_value='windows'),patch('native_landing.publish') as publish:
            r.open();publish.assert_not_called();self.assertEqual(r.fraction,fraction)

if __name__=='__main__':unittest.main()
