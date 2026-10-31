"""Hover timing and lifetime, without a real tray registration or private data."""
import os,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint,QRect,QObject,Signal,QEvent
from PySide6.QtWidgets import QApplication,QWidget,QToolTip
from PySide6.QtTest import QTest
from compact_bubble import CompactBubble
from hover_hints import HintBubble,TrayHints,HOVER_DELAY_MS

APP=QApplication.instance() or QApplication([])

def wait_for(condition,timeout=2):
    end=time.monotonic()+timeout
    while not condition() and time.monotonic()<end:QTest.qWait(20)
    return bool(condition())

class FakeTray(QObject):
    activated=Signal(int)
    def isVisible(self):return True
    def geometry(self):return QRect(100,700,24,24)
    def contextMenu(self):return None

class HoverHintTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.move(100,500);self.b.show();APP.processEvents();self.b.size_transition.complete();APP.processEvents()
        self.h=self.b.inline_explanations
    def tearDown(self):
        self.h.dismiss(True);self.b.close();self.b.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
    def hover(self,index):
        QTest.mouseMove(self.b._header_actions[index],QPoint(5,5));APP.processEvents()
    def outside(self):
        QTest.mouseMove(self.b,QPoint(3,self.b.height()-3));APP.processEvents()
    def test_style_events_do_not_traverse_hover_ancestry(self):
        with patch.object(self.b,'isAncestorOf',side_effect=AssertionError('irrelevant ancestry')):
            self.assertFalse(self.h.eventFilter(self.b._header_actions[0],QEvent(QEvent.Type.StyleChange)))
    def test_deleted_optional_event_target_is_ignored(self):
        target=QWidget();target.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.assertFalse(self.h.eventFilter(target,QEvent(QEvent.Type.Enter)))
    def test_opaque_hint_repaints_changed_text_without_geometry_or_alpha_change(self):
        paints=[]
        class ObservedHint(HintBubble):
            def paintEvent(self,event):
                super().paintEvent(event);paints.append(self.title)
        popup=ObservedHint();anchor=QRect(self.b._header_actions[0].mapToGlobal(QPoint()),self.b._header_actions[0].size())
        try:
            with patch('hover_hints.motion_enabled',return_value=True):
                popup.present('刷新','',anchor,self.b.screen());QTest.qWait(250)
                self.assertEqual(popup.level,1.);self.assertIn('刷新',paints)
                geometry=QRect(popup.geometry());paints.clear()
                popup.present('数据','',anchor,self.b.screen());QTest.qWait(100)
                self.assertEqual(popup.geometry(),geometry);self.assertEqual(popup.level,1.)
                self.assertIn('数据',paints)
        finally:popup.dismiss(True);popup.close();popup.deleteLater();APP.processEvents()
    def test_short_pass_does_not_show_and_holding_does_not_expire(self):
        self.outside();self.hover(1);QTest.qWait(150);self.assertFalse(self.h.popup.isVisible())
        self.outside();QTest.qWait(HOVER_DELAY_MS+60);self.assertFalse(self.h.popup.isVisible())
        self.hover(1);self.assertTrue(wait_for(self.h.popup.isVisible));QTest.qWait(1200)
        self.assertTrue(self.h.popup.isVisible());self.assertEqual(self.h.popup.title,'数据');self.assertFalse(QToolTip.isVisible())
    def test_header_popup_is_owned_above_the_report_without_promoting_the_app(self):
        import weakref
        from daily_report import DailyReport
        from test_daily_report import sample
        r=DailyReport(self.b);self.b.report=r;r.set_snapshot(sample());r.open()
        r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
        self.h.target=weakref.ref(self.b._header_actions[0]);before=(self.b.geometry(),r.geometry())
        self.h._show();window=self.h.popup.windowHandle()
        self.assertEqual(window.transientParent(),r.windowHandle())
        self.assertEqual(bool(self.h.popup.windowFlags()&Qt.WindowType.WindowStaysOnTopHint),bool(self.b.windowFlags()&Qt.WindowType.WindowStaysOnTopHint))
        self.assertEqual((self.b.geometry(),r.geometry()),before)
        self.assertTrue(self.h.popup.windowFlags()&Qt.WindowType.WindowDoesNotAcceptFocus)
        r.dismiss();r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
        self.h.target=weakref.ref(self.b._header_actions[0]);self.h._show()
        self.assertEqual(window.transientParent(),self.b.windowHandle())
    def test_adjacent_actions_share_surface_and_card_geometry_is_unchanged(self):
        self.outside();before=QRect(self.b.geometry());self.hover(0);self.assertTrue(wait_for(self.h.popup.isVisible))
        surface=self.h.popup
        for index,text in ((1,'数据'),(2,'收起'),(3,'详情')):
            self.hover(index);QTest.qWait(30)
            self.assertIs(self.h.popup,surface);self.assertTrue(surface.isVisible());self.assertEqual(surface.title,text)
            self.assertEqual(self.b.geometry(),before);self.assertLessEqual(abs(surface.geometry().bottom()-self.b.y()),2)
        point=self.b._header_actions[3].mapToGlobal(QPoint(5,5))
        with patch('hover_hints.QCursor.pos',return_value=point):
            self.b.redraw();APP.processEvents()
            self.assertTrue(surface.isVisible());self.assertEqual(surface.title,'详情')
        self.outside();self.assertTrue(wait_for(lambda:not surface.isVisible()))
    def test_expanded_pin_and_move_share_delay_and_survive_refresh(self):
        from PySide6.QtWidgets import QToolButton
        self.b.toggle_details();self.b.size_transition.complete();APP.processEvents();self.outside()
        def control(label):return next(w for w in self.b.findChildren(QToolButton) if w.isVisible() and w.accessibleName()==label)
        pin=control('置顶');QTest.mouseMove(pin,QPoint(5,5));APP.processEvents();QTest.qWait(150)
        self.assertFalse(self.h.popup.isVisible());self.assertTrue(wait_for(self.h.popup.isVisible));self.assertEqual(self.h.popup.title,'置顶')
        moving=control('移动');QTest.mouseMove(moving,QPoint(5,5));APP.processEvents();QTest.qWait(30)
        self.assertTrue(self.h.popup.isVisible());self.assertEqual(self.h.popup.title,'移动')
        point=moving.mapToGlobal(QPoint(5,5))
        with patch('hover_hints.QCursor.pos',return_value=point):
            self.b.redraw();APP.processEvents();self.assertTrue(self.h.popup.isVisible());self.assertEqual(self.h.popup.title,'移动')
        self.outside();self.assertTrue(wait_for(lambda:not self.h.popup.isVisible()))
    def test_hide_during_delay_or_visible_never_leaves_a_popup(self):
        self.outside();self.hover(0);self.b.hide();QTest.qWait(HOVER_DELAY_MS+80)
        self.assertFalse(self.h.delay.isActive());self.assertFalse(self.h.popup.isVisible())
        self.b.show();APP.processEvents();self.outside();self.hover(0);self.assertTrue(wait_for(self.h.popup.isVisible))
        self.b.move(self.b.x()+10,self.b.y());APP.processEvents();self.assertFalse(self.h.popup.isVisible())
    def test_tray_hover_survives_data_changes_and_stops_polling_after_leave(self):
        tray=FakeTray();h=TrayHints(tray,self.b)
        try:
            self.assertFalse(h.watch.isActive())
            with patch('hover_hints.QCursor.pos',return_value=QPoint(110,710)):
                h.set_text('5小时额度 86%','下次重置 10/26 21:00');h.enter();QTest.qWait(150)
                self.assertFalse(h.popup.isVisible());self.assertTrue(wait_for(h.popup.isVisible))
                h.set_text('5小时额度 85%','下次重置 10/26 21:00');QTest.qWait(650)
                self.assertTrue(h.popup.isVisible());self.assertEqual(h.popup.title,'5小时额度 85%')
                self.assertTrue(h.watch.isActive())
            with patch('hover_hints.QCursor.pos',return_value=QPoint(500,300)):
                self.assertTrue(wait_for(lambda:not h.popup.isVisible()))
            self.assertFalse(h.watch.isActive());self.assertFalse(h.delay.isActive())
        finally:h.close();h.deleteLater()

if __name__=='__main__':unittest.main()
