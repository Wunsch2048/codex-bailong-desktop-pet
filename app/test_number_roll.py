import os,time,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from PySide6.QtCore import QRectF,QAbstractAnimation
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication,QWidget
from number_roll import NumberRoll
from quota_summary import TodayTokens
from live_rate_ui import LiveRateCard

APP=QApplication.instance() or QApplication([])

class RollTests(unittest.TestCase):
    def setUp(self):self.widget=QWidget();self.widget.show();APP.processEvents();self.roll=NumberRoll(self.widget)
    def tearDown(self):self.widget.close();self.widget.deleteLater();APP.processEvents()
    def test_direction_and_only_latest_pending(self):
        r=self.roll;r.snap('10',10);r.set('20',20);self.assertEqual(r.direction,1)
        r.set('30',30);r.set('40',40);self.assertEqual(r.pending,('40',40))
        r.animation.setCurrentTime(180);self.assertEqual(r.target,'40');r.animation.setCurrentTime(180)
        r.set('5',5);self.assertEqual(r.direction,-1)
    def test_unchanged_rounded_number_has_no_animation(self):
        r=self.roll;r.snap('90.52M',90520000);r.set('90.52M',90520001)
        self.assertEqual(r.animation.state(),QAbstractAnimation.State.Stopped)
    def test_performance_hidden_unknown_and_unit_switch_snap(self):
        r=self.roll;r.digits=True;r.snap('99.99K',99999);r.set('100.00K',100000,animate=False)
        self.assertEqual(r.current,'100.00K')
        with patch('number_roll.motion_enabled',return_value=False):r.set('101.00K',101000)
        self.assertEqual(r.current,'101.00K');r.set('1.00M',1000000);self.assertEqual(r.current,'1.00M')
        r.set('—',None);self.assertEqual(r.current,'—')
    def test_independent_digits_keep_dot_and_unit_fixed(self):
        r=self.roll;r.digits=True;r.snap('90.52M',90520000);r.set('90.53M',90530000);r.advance(.5)
        class Recorder:
            def __init__(self):self.calls=[]
            def font(self):return QFont()
            def save(self):pass
            def restore(self):pass
            def setClipRect(self,rect):pass
            def drawText(self,rect,flags,text):self.calls.append((text,rect.y(),rect.x()))
        p=Recorder();r.paint(p,QRectF(0,0,100,20))
        moving=[text for text,y,x in p.calls if y!=0];self.assertEqual(moving,['2','3'])
        self.assertTrue(all(y==0 for text,y,x in p.calls if text in '90.5M'))
    def test_hide_lands_latest_value_and_stops_clock(self):
        card=LiveRateCard();card.show();APP.processEvents();card.set_data(dict(rate=10));card.set_data(dict(rate=20));card.set_data(dict(rate=30));card.hide()
        self.assertEqual(card.roll.current,'30.0');self.assertEqual(card.animation.state(),QAbstractAnimation.State.Stopped);card.deleteLater()
    def test_today_accepts_live_count_and_ignores_yesterdays_overlay(self):
        from datetime import datetime
        day=datetime.now().strftime('%Y-%m-%d');snap=dict(month=day[:7],days={day:90520000});card=TodayTokens(snap);card.show();APP.processEvents()
        card.set_data(snap,live=dict(day=day,count=90530000));self.assertEqual(card.data['count'],90530000);self.assertEqual(card.roll.target,'90.53M')
        card.hide();self.assertEqual(card.roll.current,'90.53M');card.set_data(snap,live=dict(day='2000-01-01',count=1));self.assertEqual(card.data['count'],90520000);card.deleteLater()
    def test_live_receipt_updates_only_footer_and_reused_card_keeps_latest_value(self):
        from compact_bubble import CompactBubble
        from datetime import datetime
        b=CompactBubble();b.show();APP.processEvents();day=datetime.now().strftime('%Y-%m-%d')
        b.token_snapshot=dict(month=day[:7],days={day:90520000});b.redraw();APP.processEvents();card=b.today_tokens_card
        receipt=dict(day=day,count=90530000,generation=1,revision=2)
        with patch.object(b,'redraw',side_effect=AssertionError('live-only rebuild')):
            b.set_live_today(receipt);self.assertEqual(card.data['count'],90530000)
            b.set_live_today(dict(receipt,count=1,revision=1));self.assertEqual(card.data['count'],90530000)
        b.expanded=True;b.redraw();APP.processEvents();self.assertIs(b.today_tokens_card,card);self.assertEqual(card.data['count'],90530000)
        b.close();b.deleteLater();APP.processEvents()
    def test_narrow_partial_footer_elides_end_instead_of_cutting_leading_digits(self):
        from datetime import datetime
        day=datetime.now().strftime('%Y-%m-%d');card=TodayTokens(dict(month=day[:7],days={day:90520000},partial=True));card.compact=True;card.resize(121,20);card.show();APP.processEvents();card.grab()
        slots=card.roll._slots;self.assertEqual(slots[0][0],'…');text=''.join(a for a,b,rect in reversed(slots));self.assertTrue(text.startswith('90.5'))
        self.assertGreaterEqual(min(rect.left() for a,b,rect in slots),card.roll._paint_rect.left());card.close();card.deleteLater()
    def test_digit_layout_matches_natural_text_width_even_for_narrow_ones(self):
        from PySide6.QtGui import QImage,QPainter,QFontMetricsF
        from typography import ui_font
        r=self.roll;r.digits=True;r.snap('111.11M',111110000)
        image=QImage(120,20,QImage.Format.Format_ARGB32);p=QPainter(image);p.setFont(ui_font(12,True));r.paint(p,QRectF(0,0,100,20));fm=QFontMetricsF(p.font(),p.device());p.end()
        left=min(rect.left() for a,b,rect in r._slots);self.assertAlmostEqual(100-left,fm.horizontalAdvance('111.11M'))
    def test_status_rebuild_preserves_both_rolls_then_real_hide_stops_them(self):
        from compact_bubble import CompactBubble
        from datetime import datetime
        b=CompactBubble();b.show();APP.processEvents();day=datetime.now().strftime('%Y-%m-%d')
        b.token_snapshot=dict(month=day[:7],days={day:90520000});b.live_output_rate=dict(rate=10);b.redraw();APP.processEvents()
        today=b.today_tokens_card;live=b.live_rate_card
        today.set_data(dict(month=day[:7],days={day:90530000}));b.token_snapshot=dict(month=day[:7],days={day:90530000})
        b.live_output_rate=dict(rate=20);live.set_data(b.live_output_rate)
        for card in (today,live):card.roll.animation.setCurrentTime(60)
        for repeat in range(3):
            b.redraw();APP.processEvents()
            for card in (today,live):
                self.assertEqual(card.roll.animation.state(),QAbstractAnimation.State.Running)
                self.assertGreaterEqual(card.roll.animation.currentTime(),60);self.assertNotEqual(card.roll.current,card.roll.target)
        b.hide();APP.processEvents()
        for card in (today,live):self.assertEqual(card.roll.animation.state(),QAbstractAnimation.State.Stopped)
        b.close();b.deleteLater();APP.processEvents()

