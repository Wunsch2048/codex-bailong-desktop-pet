"""Hover lifetime follows the pointer, not footer layout/data revisions."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint,QEvent,QCoreApplication,QObject
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

    def test_small_layout_change_keeps_popup_while_pointer_is_inside(self):
        card=self.card();self.show_hint(card)
        card.move(card.x()+1,card.y());card.resize(card.width()+1,20);APP.processEvents()
        self.assertTrue(card.popup.isVisible())

    def test_delayed_callback_rechecks_pointer_before_opening(self):
        card=self.card();self.position=QPoint(700,500);card._show_hint()
        self.assertFalse(card.popup.isVisible())

    def test_data_refresh_updates_rows_without_restarting_popup_fade(self):
        card=self.card();self.show_hint(card);card.popup.animation.setCurrentTime(160)
        with patch.object(card.popup,'present',wraps=card.popup.present) as present:
            card.set_data(dict(rate=15,details=[dict(session='a',name='会话',rate=15)]))
            self.assertEqual(card.popup.rows[0]['rate'],15)
            self.assertEqual(present.call_count,0)
        self.assertTrue(card.popup.isVisible())

    def test_brief_gap_can_reenter_but_real_leave_stops_watch(self):
        card=self.card();self.show_hint(card);self.position=QPoint(700,500)
        card._watch_hint();QTest.qWait(40)
        self.position=card.mapToGlobal(card.rect().center());card._watch_hint();QTest.qWait(200)
        self.assertTrue(card.popup.isVisible())
        self.position=QPoint(700,500);card._watch_hint();QTest.qWait(250)
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


if __name__=='__main__':unittest.main()
