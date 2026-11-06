"""Real page motion, native target pixels and nested navigation cancellation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy,unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QObject,Signal,QAbstractAnimation,Qt,QEvent
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel
from data_page_motion import PageFade
from pricing_ui import PricingEditor
from official_rates_ui import OfficialRatesPage
from cost_preferences import defaults
from settings_controls import set_motion_mode

APP=QApplication.instance() or QApplication([])
RUNNING=QAbstractAnimation.State.Running

class Service(QObject):
    changed=Signal()
    def __init__(self,unit='usd_per_million_tokens'):
        super().__init__();self.busy=False
        rates={name:dict(name=name,rates=[2,.1,10]) for name in ('gpt-6.1-sol','gpt-6-astra','gpt-6-luna')}
        self.cache=SimpleNamespace(error='',data=dict(unit=unit,source='https://example.invalid/',checked_at=1800000000,versions=[dict(observed_at=1800000000,revision='one',rates=rates)]))
    def request(self):pass
    def ensure_due(self):pass

def ink(image):
    image=image.toImage();count=0
    for y in range(image.height()):
        for x in range(image.width()):
            c=image.pixelColor(x,y)
            count+=c.alpha()>180 and c.lightness()<160
    return count

class PricingNavigationTests(unittest.TestCase):
    def setUp(self):
        import settings_controls
        self.mode=settings_controls._motion_mode;set_motion_mode('quality')
        self.motion=patch('settings_controls._system_motion_enabled',return_value=True);self.motion.start()
        self.host=QWidget();self.host.resize(246,430);self.host.show();self.service=Service()
        with patch('pricing_ui.load',return_value=defaults()):self.editor=PricingEditor(self.host,price_service=self.service)
        self.editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,False);APP.processEvents()
    def tearDown(self):
        self.host.close();self.host.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.motion.stop();set_motion_mode(self.mode)
    def prepared(self,action):
        action();APP.processEvents();APP.processEvents()
        motion=self.editor.page_motion
        self.assertEqual(motion.animation.state(),RUNNING)
        self.assertIsNotNone(motion.next_frame);self.assertGreater(ink(motion.next_frame),100)
        return motion
    def finish(self,motion):motion.animation.setCurrentTime(motion.animation.duration());APP.processEvents()
    def test_price_list_enters_from_right_returns_left_and_header_stays_put(self):
        bounds=self.editor.geometry();header=self.editor.heading.geometry();footer=self.editor.commit.geometry()
        motion=self.prepared(self.editor.models_button.click)
        self.assertEqual(motion.direction,1);self.assertIs(motion.parentWidget(),self.editor.area.viewport())
        self.assertEqual(motion.geometry(),self.editor.area.viewport().rect())
        self.assertEqual(self.editor.heading.geometry(),header);self.assertEqual(self.editor.commit.geometry(),footer)
        self.assertEqual(self.editor.geometry(),bounds);self.finish(motion)
        motion=self.prepared(self.editor.go_back);self.assertEqual(motion.direction,-1);self.finish(motion)
        self.assertEqual(self.editor.page,'home');self.assertFalse(motion.isVisible())
    def test_nested_edit_return_preserves_draft_and_final_pixels_match(self):
        self.finish(self.prepared(self.editor.models_button.click))
        self.finish(self.prepared(lambda:self.editor.edit_model('gpt-6.1-sol')))
        self.editor.price_fields[0].setText('7.5')
        motion=self.prepared(self.editor.finish_model);self.assertEqual(motion.direction,-1)
        target=motion.next_frame.copy();self.finish(motion)
        self.assertEqual(target.toImage(),PageFade.snapshot(self.editor.area.viewport()).toImage())
        self.assertEqual(self.editor.draft['prices']['gpt-6.1-sol'][0],7.5)
    def test_rapid_reverse_cannot_publish_old_queued_target(self):
        self.editor.models_button.click();self.editor.go_back();APP.processEvents();APP.processEvents()
        self.assertEqual(self.editor.page,'home');motion=self.editor.page_motion
        self.assertEqual(motion.direction,-1);self.finish(motion)
        self.assertEqual(self.editor.page,'home');self.assertFalse(motion.isVisible())
    def test_hide_resize_and_parent_freeze_release_overlay_without_thaw(self):
        self.editor.models_button.click();self.host.setUpdatesEnabled(False);APP.processEvents()
        self.assertFalse(self.host.updatesEnabled());self.assertIsNone(self.editor.page_motion.frame)
        self.host.setUpdatesEnabled(True);self.editor.go_back();APP.processEvents();self.finish(self.editor.page_motion)
        self.editor.models_button.click();self.host.resize(268,450);APP.processEvents()
        self.assertFalse(self.editor.page_motion.isVisible())
        self.editor.go_back();self.host.hide();APP.processEvents()
        self.assertIsNone(self.editor.page_motion.frame);self.assertFalse(self.editor.page_motion.isVisible())
    def test_performance_mode_skips_snapshots_and_background_refresh_does_not_animate(self):
        set_motion_mode('performance')
        with patch.object(PageFade,'snapshot',wraps=PageFade.snapshot) as capture:
            self.editor.models_button.click();self.editor.go_back();APP.processEvents();capture.assert_not_called()
        set_motion_mode('quality');self.finish(self.prepared(self.editor.models_button.click))
        with patch.object(PageFade,'snapshot',wraps=PageFade.snapshot) as capture:
            self.service.cache.data['versions'][0]['revision']='two';self.service.changed.emit()
            APP.processEvents();capture.assert_not_called();self.assertFalse(self.editor.page_motion.isVisible())
    def test_snapshot_failure_clears_cover_and_keeps_page_usable(self):
        self.editor.models_button.click();ticket=self.editor._page_ticket;frame=self.editor.page_motion.frame
        with patch.object(PageFade,'snapshot',side_effect=RuntimeError('capture failed')):
            with self.assertRaisesRegex(RuntimeError,'capture failed'):self.editor.present_page(ticket,frame,1)
        self.assertIsNone(self.editor.page_motion.frame);self.assertTrue(self.editor.updatesEnabled())
        self.editor.cancel_page_motion();APP.processEvents()
    def test_api_refresh_during_entry_is_deferred_until_landing(self):
        self.editor.models_button.click();self.service.cache.data['versions'][0]['revision']='new'
        self.service.changed.emit();self.assertTrue(self.editor._pending_api_models)
        APP.processEvents();self.finish(self.editor.page_motion)
        self.assertFalse(self.editor._pending_api_models);self.assertEqual(self.editor._api_rows_revision,'new')
    def test_history_navigation_replaces_ongoing_list_transition(self):
        self.editor.models_button.click();self.service.cache.data['versions'][0]['revision']='last'
        self.service.changed.emit();self.editor.show_price_history();APP.processEvents()
        page=self.editor.history_page
        self.assertEqual(self.editor._api_rows_revision,'last')
        self.assertFalse(self.editor.page_motion.isVisible());self.assertEqual(page.page_motion.direction,1)
        self.finish(page.page_motion);page.back.click();APP.processEvents()
        self.assertTrue(page._returning);self.assertEqual(page.page_motion.direction,-1)
        self.finish(page.page_motion);self.assertTrue(page.isHidden());self.assertEqual(self.editor.page,'models')

class OfficialPageNavigationTests(unittest.TestCase):
    def setUp(self):
        import settings_controls
        self.mode=settings_controls._motion_mode;set_motion_mode('quality')
        self.patch=patch('settings_controls._system_motion_enabled',return_value=True);self.patch.start()
        self.host=QWidget();self.host.resize(246,430);layout=QVBoxLayout(self.host);layout.addWidget(QLabel('原额度页面：用量与历史周期'))
        self.host.show();APP.processEvents()
    def tearDown(self):
        self.host.close();self.host.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.patch.stop();set_motion_mode(self.mode)
    def page(self,unit='credits_per_million_tokens'):
        p=OfficialRatesPage(self.host,Service(unit));p.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,False);return p
    def test_credit_and_api_pages_have_readable_entry_and_reverse_to_exact_parent(self):
        parent=PageFade.snapshot(self.host)
        for unit in ('credits_per_million_tokens','usd_per_million_tokens'):
            p=self.page(unit);APP.processEvents();m=p.page_motion
            self.assertEqual(m.animation.state(),RUNNING);self.assertEqual(m.direction,1)
            self.assertGreater(ink(m.next_frame),100)
            m.animation.setCurrentTime(110);p.back.click();APP.processEvents()
            self.assertTrue(p._returning);self.assertEqual(m.direction,-1)
            self.assertEqual(m.next_frame.toImage(),parent.toImage())
            m.animation.setCurrentTime(m.animation.duration());APP.processEvents()
            self.assertTrue(p.isHidden());self.assertEqual(PageFade.snapshot(self.host).toImage(),parent.toImage())
            p.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_close_before_capture_and_hide_during_return_cancel_all_old_work(self):
        p=self.page();p.back.click();self.host.hide();APP.processEvents()
        self.assertIsNone(p.page_motion.frame);self.assertFalse(p.isVisible())
    def test_performance_mode_does_not_create_an_animated_overlay(self):
        set_motion_mode('performance')
        with patch.object(PageFade,'snapshot',wraps=PageFade.snapshot) as capture:
            p=self.page();p.back.click();APP.processEvents();capture.assert_not_called()
        self.assertTrue(p.isHidden());self.assertIsNone(p.page_motion.frame)

if __name__=='__main__':unittest.main()
