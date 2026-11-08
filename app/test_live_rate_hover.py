"""Hover lifetime follows the pointer, not footer layout/data revisions."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint,QEvent,QCoreApplication,QObject,Qt,QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from compact_bubble import CompactBubble
from live_rate_ui import LiveRateCard

APP=QApplication.instance() or QApplication([])


class LiveRateHoverTests(unittest.TestCase):
    def setUp(self):
        self.position=QPoint(200,200)
        self.cursor=patch('live_rate_ui.QCursor.pos',side_effect=lambda:self.position)
        self.cursor.start();self.widgets=[]

    def tearDown(self):
        for widget in self.widgets:widget.close();widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        APP.processEvents();self.cursor.stop()

    def card(self):
        card=LiveRateCard(dict(rate=30,details=[dict(session='a',name='会话',rate=30)]))
        self.widgets.append(card);card.setGeometry(100,300,121,20);card.show();APP.processEvents()
        self.position=card.mapToGlobal(card.rect().center());return card

    def show_hint(self,card):
        self.position=card.mapToGlobal(card.rect().center());card._show_hint();APP.processEvents()
        self.assertTrue(card.popup.isVisible())

    def test_hover_first_visible_frame_is_opaque(self):
        card=self.card();levels=[]
        class FirstShow(QObject):
            def eventFilter(self,obj,event):
                if event.type()==QEvent.Type.Show:levels.append(obj.level)
                return False
        observer=FirstShow();card.popup.installEventFilter(observer);self.show_hint(card)
        self.assertEqual(levels,[1.]);self.assertEqual(card.popup.level,1.)
        card.set_data(dict(rate=15,details=[dict(name='updated',rate=15)]));self.assertEqual(card.popup.level,1.)
    def test_trace_is_bounded_and_omits_session_content(self):
        card=self.card();card.set_data(dict(rate=30,details=[dict(session='private-id',name='private-title',rate=30)]));self.show_hint(card)
        for i in range(300):card._trace_hover('sample')
        trace=card.hover_diagnostics();self.assertEqual(len(trace['events']),240);self.assertEqual(trace['capacity'],240)
        text=__import__('json').dumps(trace);self.assertNotIn('private-title',text);self.assertNotIn('private-id',text)
        with patch.object(card,'_inside_hint',return_value=False):card._dismiss_if_outside()
        self.assertTrue(any(e['event']=='dismiss' and e['caller']=='_dismiss_if_outside' for e in card.hover_diagnostics()['events']))
    def test_small_layout_change_keeps_popup_while_pointer_is_inside(self):
        card=self.card();self.show_hint(card)
        card.move(card.x()+1,card.y());card.resize(card.width()+1,20);APP.processEvents()
        self.assertTrue(card.popup.isVisible())

    def test_delayed_callback_rechecks_pointer_before_opening(self):
        card=self.card();self.position=QPoint(700,500);card._show_hint()
        self.assertFalse(card.popup.isVisible())

    def test_stale_show_callback_does_not_close_visible_popup_under_pointer(self):
        card=self.card();self.show_hint(card)
        self.position=card.popup.geometry().center();card._show_hint()
        self.assertTrue(card.popup.isVisible());self.assertTrue(card.hint_watch.isActive())

    def test_rebuild_boundary_shift_uses_leave_grace_instead_of_immediate_hide(self):
        card=self.card();self.show_hint(card)
        self.position=card.mapToGlobal(QPoint(1,card.height()//2));original=card.pos()
        card.begin_rebuild(True);card.move(card.x()+3,card.y());APP.processEvents()
        self.assertTrue(card.popup.isVisible());self.assertTrue(card.hint_leave.isActive())
        card.move(original);APP.processEvents();card._watch_hint();QTest.qWait(220)
        self.assertTrue(card.popup.isVisible());self.assertFalse(card.hint_leave.isActive())

    def test_rebuild_does_not_extend_a_real_pointer_leave_forever(self):
        card=self.card();self.show_hint(card);self.position=QPoint(900,800)
        card._watch_hint();QTest.qWait(110)
        for _ in range(4):
            card.begin_rebuild(True);APP.processEvents();QTest.qWait(35)
        self.assertFalse(card.popup.isVisible());self.assertFalse(card.hint_watch.isActive())

    def test_data_refresh_updates_rows_without_restarting_popup_fade(self):
        card=self.card();self.show_hint(card);card.popup.animation.setCurrentTime(160)
        with patch.object(card.popup,'present',wraps=card.popup.present) as present:
            card.set_data(dict(rate=15,details=[dict(session='a',name='会话',rate=15)]))
            self.assertEqual(card.popup.rows[0]['rate'],15)
            self.assertEqual(present.call_count,0)
        self.assertTrue(card.popup.isVisible())

    def test_brief_gap_can_reenter_but_real_leave_stops_watch(self):
        card=self.card();self.show_hint(card);self.position=QPoint(700,500)
        card._watch_hint();self.assertTrue(card.hint_leave.isActive())
        self.position=card.mapToGlobal(card.rect().center());card._watch_hint()
        self.assertFalse(card.hint_leave.isActive());self.assertTrue(card.popup.isVisible())
        self.position=QPoint(700,500);card._watch_hint()
        self.assertTrue(card.hint_leave.isActive())
        card.hint_leave.stop();card.hint_leave.timeout.emit()
        self.assertFalse(card.popup.isVisible());self.assertFalse(card.hint_watch.isActive())

    def test_popup_pointer_and_scroll_survive_same_surface_rebuild(self):
        bubble=CompactBubble();self.widgets.append(bubble);bubble.move(100,400);bubble.show();APP.processEvents()
        card=bubble.live_rate_card
        card.set_data(dict(rate=30,details=[dict(session=str(i),name='会话',rate=3) for i in range(12)]))
        self.show_hint(card);popup=card.popup;popup.scroll=38
        self.position=popup.geometry().center()
        bubble.redraw();APP.processEvents()
        self.assertIs(bubble.live_rate_card,card);self.assertIs(card.popup,popup)
        self.assertTrue(popup.isVisible());self.assertEqual(popup.scroll,38)

    def test_pending_hover_delay_is_not_restarted_by_rebuild(self):
        bubble=CompactBubble();self.widgets.append(bubble);bubble.move(100,400);bubble.show();APP.processEvents()
        card=bubble.live_rate_card;self.position=card.mapToGlobal(card.rect().center())
        card.hint_delay.start(400);QTest.qWait(100)
        bubble.redraw();APP.processEvents()
        self.assertIs(bubble.live_rate_card,card)
        self.assertTrue(card.hint_delay.isActive());self.assertLess(card.hint_delay.remainingTime(),350)

    def test_real_hide_or_mode_change_dismisses_without_delayed_reopen(self):
        bubble=CompactBubble();self.widgets.append(bubble);bubble.show();APP.processEvents()
        card=bubble.live_rate_card;self.show_hint(card)
        bubble.bubble_mode='mini';bubble.redraw();APP.processEvents();QTest.qWait(550)
        self.assertFalse(card.popup.isVisible());self.assertFalse(card.hint_delay.isActive())
        bubble.bubble_mode='auto';bubble.redraw();APP.processEvents();card=bubble.live_rate_card
        self.show_hint(card);bubble.hide();QTest.qWait(550)
        self.assertFalse(card.popup.isVisible());self.assertFalse(card.hint_watch.isActive())

    def test_repeated_refresh_has_no_popup_hide_and_paints_new_rate(self):
        bubble=CompactBubble();self.widgets.append(bubble);bubble.move(100,400);bubble.show();APP.processEvents()
        card=bubble.live_rate_card;self.show_hint(card);card.popup.animation.setCurrentTime(160)
        class Events(QObject):
            def __init__(self):super().__init__();self.hides=0
            def eventFilter(self,obj,event):
                if event.type()==QEvent.Type.Hide:self.hides+=1
                return False
        events=Events();card.popup.installEventFilter(events);before=card.popup.grab().toImage()
        for i in range(12):
            bubble.live_output_rate=dict(rate=100+i,details=[dict(session='a',name='新采样',rate=100+i)])
            bubble.redraw();APP.processEvents()
            self.assertTrue(card.popup.isVisible())
        self.assertEqual(events.hides,0);self.assertEqual(card.popup.total,111)
        self.assertNotEqual(before,card.popup.grab().toImage())

    def test_expansion_hides_hint_and_blocks_show_during_handoff(self):
        bubble=CompactBubble();self.widgets.append(bubble);bubble.show();APP.processEvents()
        card=bubble.live_rate_card;self.show_hint(card)
        bubble.toggle_details();APP.processEvents()
        self.position=card.mapToGlobal(card.rect().center());card._show_hint()
        self.assertFalse(card.popup.isVisible());self.assertFalse(card.hint_delay.isActive())
        bubble.size_transition.complete();APP.processEvents()

    def test_quota_disabled_keeps_no_orphan_hint(self):
        bubble=CompactBubble();self.widgets.append(bubble);bubble.show();APP.processEvents()
        card=bubble.live_rate_card;self.show_hint(card)
        bubble.show_quota=False;bubble.redraw();APP.processEvents()
        self.assertFalse(card.isVisible());self.assertFalse(card.popup.isVisible())
        self.assertFalse(card.hint_watch.isActive())

    def test_visible_reposition_never_visits_old_anchor_formula(self):
        card=self.card();self.show_hint(card);popup=card.popup;old=QRect(popup.geometry())
        calls=[];original=popup.setGeometry
        def record(*args):
            rect=QRect(*args) if len(args)>1 else QRect(args[0]);calls.append(rect);return original(*args)
        with patch.object(popup,'setGeometry',side_effect=record):
            card.move(card.x()+1,card.y());popup.inspect(card.value,card)
        target=popup._placement[0]
        self.assertTrue(all(r==old or r==target for r in calls),calls)

    def test_visible_hover_keeps_native_owner_when_topmost_changes(self):
        card=self.card();self.show_hint(card);popup=card.popup
        popup.animation.setCurrentTime(160);owner=popup._placement[1:]
        with patch.object(popup,'present',wraps=popup.present) as present:
            card.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,not bool(card.windowFlags()&Qt.WindowType.WindowStaysOnTopHint));card.show()
            popup.inspect(card.value,card)
            self.assertEqual(present.call_count,0)
            self.assertEqual(popup._placement[1:],owner)
            self.assertEqual(popup.level,1.)

    def test_click_opens_service_directly_and_pointer_leave_does_not_close_it(self):
        card=self.card();self.show_hint(card)
        QTest.mouseClick(card,Qt.MouseButton.LeftButton)
        panel=card.service_panel
        self.assertTrue(panel.isVisible());self.assertEqual(panel.page,'service');self.assertFalse(card.popup.isVisible());self.assertEqual(panel.level,1.)
        self.position=QPoint(900,800);card._watch_hint();QTest.qWait(250)
        self.assertTrue(panel.isVisible())

    def test_service_panel_deactivate_closes_only_service_panel(self):
        card=self.card();QTest.mouseClick(card,Qt.MouseButton.LeftButton);panel=card.service_panel
        APP.sendEvent(panel,QEvent(QEvent.Type.WindowDeactivate));self.assertFalse(panel.isVisible())
    def test_second_click_stays_closed_when_deactivate_arrives_before_or_after_press(self):
        from public_status import shared
        card=self.card()
        with patch.object(shared(),'request'):
            for before_press in (True,False):
                QTest.mouseClick(card,Qt.MouseButton.LeftButton);panel=card.service_panel;self.assertTrue(panel.isVisible())
                if before_press:APP.sendEvent(panel,QEvent(QEvent.Type.WindowDeactivate))
                QTest.mousePress(card,Qt.MouseButton.LeftButton)
                if not before_press:APP.sendEvent(panel,QEvent(QEvent.Type.WindowDeactivate))
                QTest.mouseRelease(card,Qt.MouseButton.LeftButton);APP.processEvents()
                self.assertFalse(panel.isVisible());self.assertFalse(card.popup.isVisible());self.assertFalse(card.hint_delay.isActive())
    def test_outside_deactivate_and_expired_focus_loss_do_not_consume_a_new_open(self):
        from public_status import shared
        import time
        card=self.card()
        with patch.object(shared(),'request'):
            QTest.mouseClick(card,Qt.MouseButton.LeftButton);panel=card.service_panel
            self.position=QPoint(-1000,-1000);APP.sendEvent(panel,QEvent(QEvent.Type.WindowDeactivate))
            self.assertFalse(panel.isVisible());QTest.mouseClick(card,Qt.MouseButton.LeftButton);self.assertTrue(panel.isVisible())
            self.position=card.mapToGlobal(card.rect().center());APP.sendEvent(panel,QEvent(QEvent.Type.WindowDeactivate))
            card._service_deactivated_at=time.monotonic()-2
            QTest.mouseClick(card,Qt.MouseButton.LeftButton);self.assertTrue(panel.isVisible())
    def test_service_has_no_close_symbol_or_right_header_close_hit_target(self):
        from public_status import shared
        from PySide6.QtGui import QPainter
        card=self.card()
        with patch.object(shared(),'request'):
            QTest.mouseClick(card,Qt.MouseButton.LeftButton);panel=card.service_panel;labels=[]
            class Recorder(QPainter):
                def drawText(self,*args):
                    if args and isinstance(args[-1],str):labels.append(args[-1])
                    return super().drawText(*args)
            with patch('service_rate_ui.QPainter',Recorder):panel.grab()
            self.assertIn('‹ 会话速率',labels);self.assertNotIn('×',labels)
            QTest.mouseClick(panel,Qt.MouseButton.LeftButton,pos=QPoint(panel.width()-12,16))
            self.assertTrue(panel.isVisible());self.assertEqual(panel.page,'service')


if __name__=='__main__':unittest.main()
