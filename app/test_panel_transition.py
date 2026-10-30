import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from PySide6.QtCore import QRect,QObject,QEvent,Qt
from PySide6.QtGui import QPalette,QColor
from PySide6.QtWidgets import QApplication,QWidget,QCheckBox,QLineEdit
from compact_bubble import CompactBubble

APP=QApplication.instance() or QApplication([])


class PanelTests(unittest.TestCase):
    def test_handoff_bitmap_is_submitted_before_hiding_the_live_card(self):
        from unittest.mock import patch
        events=[];original=self.b.setWindowOpacity
        def opacity(value):events.append(('opacity',value));return original(value)
        def publish(widget,image):events.append(('raster',image is not None));return True
        with patch('panel_transition.QApplication.platformName',return_value='windows'),patch('panel_transition.present_barrier'),\
             patch('native_landing.publish',side_effect=publish),patch.object(self.b,'setWindowOpacity',side_effect=opacity):
            self.b.toggle_details()
        self.assertLess(events.index(('raster',True)),events.index(('opacity',0.)))
    def test_native_canvas_is_invisible_until_start_frame_is_painted(self):
        from unittest.mock import patch
        b=self.b;b.setWindowOpacity(.8);opacity=b.windowOpacity();observed=[];original=b.setGeometry
        def move(*args):
            observed.append((b.windowOpacity(),b.size_transition.landing.image is not None));return original(*args)
        with patch('panel_transition.QApplication.platformName',return_value='windows'),patch('panel_transition.present_barrier'),patch.object(b,'setGeometry',side_effect=move):
            b.toggle_details()
        self.assertTrue(observed);self.assertTrue(all(value==0 and guard for value,guard in observed))
        self.assertEqual(b.windowOpacity(),opacity);b.size_transition.complete()
    def test_native_resize_failure_restores_user_opacity(self):
        from unittest.mock import patch
        b=self.b;b.setWindowOpacity(.7);opacity=b.windowOpacity()
        with patch('panel_transition.QApplication.platformName',return_value='windows'),patch('panel_transition.present_barrier'),patch.object(b,'setGeometry',side_effect=RuntimeError('synthetic native resize')):
            with self.assertRaises(RuntimeError):b.toggle_details()
        self.assertEqual(b.windowOpacity(),opacity);b.size_transition.cancel()
    def setUp(self):
        self.b=CompactBubble();self.b.status='检查中';self.b.redraw();self.b.show();APP.processEvents()
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater();APP.processEvents()
    def test_details_and_collapse_have_real_intermediate_sizes(self):
        b=self.b;small=b.size();b.toggle_details();t=b.size_transition;target=t.target_rect.size()
        self.assertTrue(t.running);native=b.size();self.assertEqual(t.visible_geometry().size(),small)
        self.assertFalse(b.layout.isEnabled())
        t.animation.setCurrentTime(140)
        visual=t.visible_geometry().size();self.assertEqual(b.size(),native)
        self.assertTrue(small.width()<visual.width()<target.width());self.assertTrue(small.height()<visual.height()<target.height())
        t.complete();self.assertEqual(b.size(),target);self.assertFalse(t.cover.isVisible())
        self.assertTrue(b.layout.isEnabled())
        b.toggle_details();t.animation.setCurrentTime(70);self.assertTrue(small.width()<t.visible_geometry().width()<target.width())
        t.complete();self.assertEqual(b.size(),small)
    def test_normal_detail_transition_never_exposes_blank_contents(self):
        self.b.toggle_details();m=self.b.size_transition.morph
        for i in range(101):
            outgoing,incoming=m.content_opacities(i/100)
            self.assertAlmostEqual(outgoing+incoming,1.)
        self.b.size_transition.complete()
    def test_shrink_never_reverses_with_solid_content_and_fixed_canvas(self):
        b=self.b;b.show_page('settings',QWidget());b.size_transition.complete()
        b.show_status(False);t=b.size_transition;native=QRect(b.geometry());handle=int(b.winId());sizes=[]
        for step in range(60):
            t.animation.setCurrentTime(round(step*t.animation.duration()/60))
            rect=t.visible_geometry();sizes.append(rect.height())
            self.assertEqual(b.geometry(),native);self.assertEqual(int(b.winId()),handle)
            self.assertTrue(native.contains(rect));self.assertTrue(b.content.isHidden())
            image=b.grab().toImage();point=rect.center()-b.pos();ratio=image.devicePixelRatio()
            self.assertEqual(image.pixelColor(round(point.x()*ratio),round(point.y()*ratio)).alpha(),255)
        self.assertEqual(min(sizes),t.target_rect.height())
        self.assertTrue(all(z<=a for a,z in zip(sizes,sizes[1:])))
        target=QRect(t.target_rect);t.complete();self.assertEqual(b.geometry(),target)
        self.assertTrue(b.content.isVisible());self.assertIsNone(t.before);self.assertFalse(t.frozen)
        self.assertIsNone(t.morph);self.assertIsNone(t.old_surface)
    def test_capsule_body_morphs_separately_from_satellites_in_both_directions(self):
        b=self.b;b.set_mode('mini');b.size_transition.complete()
        for mode in ('auto','mini'):
            b.set_mode(mode);t=b.size_transition;m=t.morph;native=QRect(b.geometry())
            mini=m.start if m.start.island else m.end
            self.assertEqual(round(mini.rect.width()),124);self.assertEqual(len(mini.satellites),2)
            self.assertEqual(round(mini.rect.height()),38)
            self.assertEqual(mini.content.toImage().pixelColor(2,2).alpha(),0)
            for step in range(40):
                t.animation.setCurrentTime(round(step*t.animation.duration()/40));r=t.visible_geometry()
                self.assertEqual(b.geometry(),native);self.assertTrue(native.contains(r));self.assertGreater(r.height(),0)
                self.assertEqual(len(m.start.satellites)+len(m.end.satellites),2)
            t.complete();self.assertIsNone(t.morph)
    def test_live_updates_wait_without_restarting_geometry_or_losing_latest(self):
        b=self.b;b.toggle_details();t=b.size_transition;t.animation.setCurrentTime(100);current=QRect(b.geometry())
        for i in range(20):b.message('最新状态 '+str(i))
        self.assertEqual(b.geometry(),current);self.assertEqual(t.animation.currentTime(),100)
        t.complete();self.assertEqual(b.status_view.text(),'最新状态 19');self.assertEqual(b.width(),360)
    def test_interruption_starts_from_the_visible_size(self):
        b=self.b;b.show_page('settings',QWidget());t=b.size_transition;t.animation.setCurrentTime(110)
        current=QRect(b.geometry());b.show_status(False)
        self.assertEqual(b.geometry(),current);self.assertEqual(t.animation.currentTime(),110)
        t.complete();APP.processEvents();t.complete();self.assertEqual(b.width(),268)
    def test_equal_sized_editor_pages_keep_widgets_and_have_no_resize(self):
        b=self.b;chat=QWidget();draft=QLineEdit(chat);draft.setText('draft')
        b.show_page('chat',chat);b.size_transition.complete();size=b.size()
        b.show_page('settings',QWidget());self.assertTrue(b.size_transition.running);self.assertEqual(b.size(),size)
        b.size_transition.complete();self.assertEqual(b.size(),size)
        b.show_page('chat',chat);self.assertTrue(b.size_transition.running);self.assertEqual(b.size(),size)
        b.size_transition.complete();self.assertEqual(draft.text(),'draft')
    def test_expanded_navigation_keeps_one_size_and_only_moves_the_body(self):
        b=self.b;b.toggle_details();b.size_transition.complete();original=QRect(b.geometry())
        chat=QWidget();QLineEdit('draft',chat)
        for change in (lambda:b.show_page('chat',chat),lambda:b.show_page('settings',QWidget()),b.return_to_status):
            change();t=b.size_transition
            self.assertEqual(t.target_rect,original)
            self.assertTrue(t.same_size_fade)
            nav=b.layout.itemAt(1).widget()
            self.assertGreater(t.cover.y(),nav.geometry().bottom())
            for ms in (0,40,80,120):
                t.animation.setCurrentTime(ms)
                self.assertEqual(b.geometry(),original)
                self.assertEqual(t.visible_geometry(),original)
                self.assertEqual(b.grab().toImage().pixelColor(b.rect().center()).alpha(),255)
            t.complete();self.assertEqual(b.geometry(),original)
    def test_editor_handoff_preserves_body_origin_and_rounded_window_corners(self):
        b=self.b;b.toggle_details();b.size_transition.complete()
        for change in (lambda:b.show_page('chat',QWidget()),lambda:b.show_page('settings',QWidget()),b.return_to_status):
            change();t=b.size_transition;body=QRect(t.cover.geometry())
            for ms in (0,40,80,120):
                t.animation.setCurrentTime(ms);image=b.grab().toImage();ratio=image.devicePixelRatioF()
                for x,y in ((0,b.height()-1),(b.width()-1,b.height()-1),(2,b.height()-3)):
                    self.assertEqual(image.pixelColor(round(x*ratio),round(y*ratio)).alpha(),0)
            t.complete()
            self.assertEqual(t.cover.geometry(),body,'Handoff moved the body raster over the header')
    def test_text_remains_dark_under_a_dark_system_palette(self):
        old=APP.palette();dark=QPalette(old)
        for role in (QPalette.ColorRole.WindowText,QPalette.ColorRole.Text,QPalette.ColorRole.ButtonText):dark.setColor(role,QColor('white'))
        try:
            APP.setPalette(dark);b=CompactBubble();check=QCheckBox('设置选项',b.editor_stack);field=QLineEdit(b.editor_stack)
            for widget,role in ((check,QPalette.ColorRole.WindowText),(field,QPalette.ColorRole.Text)):
                widget.ensurePolished()
                for group in (QPalette.ColorGroup.Active,QPalette.ColorGroup.Inactive):self.assertLess(widget.palette().color(group,role).lightness(),150)
            b.close();b.deleteLater();APP.processEvents()
        finally:APP.setPalette(old)
    def test_hidden_panel_stops_animation_and_releases_frozen_widgets(self):
        b=self.b;b.toggle_details();b.hide()
        self.assertFalse(b.size_transition.running);self.assertTrue(b.layout.isEnabled())
        self.assertFalse(b.size_transition.frozen)
    def test_disable_bubble_rebounds_and_hides_then_can_be_shown_again(self):
        b=self.b;original=QRect(b.geometry());b.enabled=False;b.redraw();t=b.size_transition
        self.assertTrue(t.closing);self.assertTrue(b.isVisible())
        self.assertTrue(b.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        heights=[]
        for step in range(60):
            t.animation.setCurrentTime(round(step*t.animation.duration()/60));heights.append(t.visible_geometry().height())
            self.assertEqual(b.geometry(),original);self.assertTrue(b.isVisible())
        self.assertTrue(all(z<=a for a,z in zip(heights,heights[1:])))
        t.complete();self.assertFalse(b.isVisible());self.assertEqual(b.geometry(),original)
        self.assertTrue(b.layout.isEnabled());self.assertIsNone(t.before)
        self.assertFalse(b.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        b.enabled=True;b.redraw();self.assertTrue(b.isVisible())
    def test_reenable_during_dismiss_preserves_latest_request(self):
        b=self.b;b.enabled=False;b.redraw();t=b.size_transition;t.animation.setCurrentTime(200)
        b.enabled=True;b.redraw();self.assertTrue(t.deferred)
        t.complete();self.assertTrue(b.isVisible());self.assertFalse(t.running)
        self.assertFalse(b.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
    def test_returning_from_settings_with_bubble_disabled_keeps_one_close_motion(self):
        b=self.b;b.show_page('settings',QWidget());b.size_transition.complete()
        b.enabled=False;b.redraw();self.assertTrue(b.isVisible())
        b.return_to_status();t=b.size_transition
        self.assertTrue(t.closing);self.assertEqual(t.target_rect.size().width(),1)
        t.complete();self.assertFalse(b.isVisible())
        b.enabled=True;b.redraw();self.assertTrue(b.isVisible());self.assertEqual(b.size(),b.content.size())
    def test_dismiss_restores_the_current_mouse_through_preference(self):
        b=self.b;owner=QWidget();owner.settings={'mouse_through':True};owner.show()
        b.setParent(owner,b.windowFlags());b.show();APP.processEvents()
        try:
            b.enabled=False;b.redraw();b.size_transition.complete()
            self.assertTrue(b.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
            self.assertTrue(b.windowHandle().flags()&Qt.WindowType.WindowTransparentForInput)
            b.enabled=True;b.redraw();self.assertTrue(b.isVisible())
            self.assertTrue(b.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        finally:b.setParent(None,b.windowFlags());owner.close();owner.deleteLater();APP.processEvents()
    def test_target_layout_preparation_never_resizes_or_hides_the_native_window(self):
        class Recorder(QObject):
            def __init__(self):super().__init__();self.events=[]
            def eventFilter(self,obj,event):
                if event.type() in (QEvent.Type.Resize,QEvent.Type.Hide):self.events.append(event.type())
                return False
        recorder=Recorder();b=self.b;b.installEventFilter(recorder)
        for change in (b.toggle_details,lambda:b.show_page('settings',QWidget())):
            change();self.assertNotIn(QEvent.Type.Hide,recorder.events);recorder.events.clear()
            t=b.size_transition;rect=QRect(b.geometry())
            for ms in (40,80,140,200,260):t.animation.setCurrentTime(ms);self.assertEqual(b.geometry(),rect)
            self.assertFalse(recorder.events);t.complete();recorder.events.clear()
    def test_every_transition_frame_contains_solid_content_without_a_fade_gap(self):
        b=self.b;page=QWidget();page.setStyleSheet('background:#61507a;')
        b.show_page('settings',page);t=b.size_transition
        expected=t.cover.image.toImage().pixelColor(35,90)
        self.assertLess(expected.lightness(),200)
        for ms in (0,40,80,100,140,200,260):
            t.animation.setCurrentTime(ms)
            rect=t.visible_geometry();image=b.grab().toImage();point=rect.center()-b.pos()
            self.assertEqual(image.pixelColor(point).alpha(),255)
        t.complete();self.assertEqual(b.grab().toImage().pixelColor(35,90),expected)
    def test_automatic_status_redraw_does_not_steal_another_windows_focus(self):
        other=QWidget();other.show();QApplication.setActiveWindow(other);APP.processEvents()
        try:
            self.b.message('新状态');APP.processEvents();self.assertIs(APP.activeWindow(),other)
        finally:other.close();other.deleteLater()
    def test_native_canvas_handoffs_are_not_paintable_intermediate_states(self):
        class Recorder(QObject):
            def __init__(self):super().__init__();self.events=[]
            def eventFilter(self,obj,event):
                if event.type() in (QEvent.Type.Move,QEvent.Type.Resize):
                    self.events.append((event.type().name,obj.updatesEnabled()))
                return False
        b=self.b;rec=Recorder();b.installEventFilter(rec)
        for change in (b.toggle_details,lambda:b.show_page('settings',QWidget()),lambda:b.show_status(False),lambda:b.set_mode('mini'),lambda:b.set_mode('auto')):
            rec.events=[];change();t=b.size_transition
            self.assertTrue(t.running)
            if t.same_size_fade:self.assertFalse(rec.events)
            else:self.assertTrue(rec.events)
            self.assertTrue(all(not enabled for _,enabled in rec.events),rec.events)
            rec.events=[];t.complete()
            self.assertTrue(all(not enabled for _,enabled in rec.events),rec.events)
            self.assertTrue(b.updatesEnabled());self.assertTrue(b.content.isVisible());self.assertFalse(t.cover.isVisible())
    def test_hidden_panel_never_restores_live_content_until_actual_show(self):
        b=self.b;b.enabled=False;b.redraw();b.size_transition.complete()
        self.assertTrue(b.content.isHidden())
        self.assertEqual(b.grab().toImage().pixelColor(b.rect().center()).alpha(),0)
        b.enabled=True;b.redraw();self.assertTrue(b.content.isVisible())
