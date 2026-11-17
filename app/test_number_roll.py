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
    def test_today_roll_counts_display_steps_and_carries(self):
        roll=self.roll;roll.digits=True
        roll.snap('90.32M',90320000);roll.set('90.52M',90520000)
        self.assertEqual(roll.animation.duration(),420)
        self.assertEqual(roll.digit_tracks[1][:2],(9032,20))
        self.assertEqual(roll.digit_tracks[2][:2],(903,2))
        self.assertEqual(len(roll.digit_tracks),2)
        roll.animation.setCurrentTime(210)
        self.assertAlmostEqual(roll.progress,.5,places=4)
        roll.advance(.16)
        start_progress=roll.progress
        self.assertLess(start_progress,.08)
        roll.advance(.84)
        self.assertAlmostEqual(1-roll.progress,start_progress,places=4)
        roll.animation.setCurrentTime(420)
        self.assertEqual(roll.current,'90.52M')
        roll.snap('99.98M',99980000);roll.set('100.02M',100020000)
        self.assertEqual(roll.animation.duration(),260)
        self.assertEqual(len(roll.digit_tracks),5)
        self.assertTrue(roll.digit_tracks[6][3])
        roll.animation.setCurrentTime(260)
        self.assertEqual(roll.current,'100.02M')
    def test_performance_hidden_unknown_and_unit_switch_snap(self):
        r=self.roll;r.digits=True;r.snap('99.99K',99999);r.set('100.00K',100000,animate=False)
        self.assertEqual(r.current,'100.00K')
        with patch('number_roll.motion_enabled',return_value=False):r.set('101.00K',101000)
        self.assertEqual(r.current,'101.00K');r.set('1.00M',1000000);self.assertEqual(r.current,'1.00M')
        r.set('—',None);self.assertEqual(r.current,'—')
    def test_independent_digits_keep_dot_and_unit_fixed(self):
        r=self.roll;r.digits=True;r.snap('90.52M',90520000);r.set('90.53M',90530000);r.advance(.5)
        class Recorder:
            def __init__(self):self.calls=[];self.clips=[]
            def font(self):return QFont()
            def save(self):pass
            def restore(self):pass
            def setClipRect(self,rect):self.clips.append(QRectF(rect))
            def drawText(self,rect,flags,text):self.calls.append((text,rect.y(),rect.x()))
        p=Recorder();r.paint(p,QRectF(0,0,100,20))
        moving=[text for text,y,x in p.calls if y!=0];self.assertEqual(moving,['2','3'])
        self.assertGreater(p.clips[-1].top(),p.clips[0].top())
        self.assertLess(p.clips[-1].bottom(),p.clips[0].bottom())
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
        self.assert_rolls_survive_status_rebuild(expanded=False)

    def test_expanded_status_rebuild_preserves_both_rolls_then_real_hide_stops_them(self):
        self.assert_rolls_survive_status_rebuild(expanded=True)

    def assert_rolls_survive_status_rebuild(self,expanded):
        from compact_bubble import CompactBubble
        from datetime import datetime
        b=CompactBubble();b.expanded=expanded;b.show();APP.processEvents();day=datetime.now().strftime('%Y-%m-%d')
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
        self.assertTrue(today.roll.digits)
        self.assertEqual(today.roll.direction,1)
        self.assertTrue(live.roll.digits)
        self.assertEqual(live.roll.direction,1)
        live.animation.setCurrentTime(live.animation.duration())
        live.set_data(dict(rate=15))
        self.assertEqual(live.roll.direction,-1)
        self.assertEqual(live.animation.state(),QAbstractAnimation.State.Running)
        self.assertEqual(live.roll.digit_tracks[0][:2],(200,50))
        self.assertEqual(live.roll.digit_tracks[2][:2],(20,5))
        b.hide();APP.processEvents()
        for card in (today,live):self.assertEqual(card.roll.animation.state(),QAbstractAnimation.State.Stopped)
        b.close();b.deleteLater();APP.processEvents()

    def test_normal_snapshot_reuses_cards_and_does_not_rebuild_unchanged_chart(self):
        self.assert_snapshot_reuses_cards(expanded=False)

    def test_expanded_snapshot_reuses_cards_when_details_are_unchanged(self):
        self.assert_snapshot_reuses_cards(expanded=True)

    def assert_snapshot_reuses_cards(self,expanded):
        from compact_bubble import CompactBubble
        from datetime import datetime
        b=CompactBubble();b.expanded=expanded;b.show();APP.processEvents()
        try:
            day=datetime.now().date().isoformat()
            b.token_snapshot=dict(month=day[:7],days={day:90520000});b.redraw();APP.processEvents()
            deck=b.deck;quota=b.quota_summary_card;plot=deck.pages['tokens'].plot
            today=b.today_tokens_card;live=b.live_rate_card
            b.set_live_today(dict(day=day,count=90530000,generation=1,revision=1))
            with patch.object(b,'redraw',side_effect=AssertionError('snapshot rebuilt the card')),patch('token_charts.usage_series',side_effect=AssertionError('unchanged series recomputed')):
                b.token_snapshot=dict(b.token_snapshot,checked=time.time())
                self.assertTrue(b.refresh_token_snapshot())
            self.assertIs(b.deck,deck);self.assertIs(b.quota_summary_card,quota)
            self.assertIs(b.today_tokens_card,today);self.assertIs(b.live_rate_card,live)
            self.assertEqual(today.roll.target,'90.53M')
            self.assertEqual(today.roll.animation.state(),QAbstractAnimation.State.Running)
            b.token_snapshot=dict(b.token_snapshot,days={day:90600000})
            self.assertTrue(b.refresh_token_snapshot())
            self.assertEqual(plot.series['total'],90600000)
            if expanded:
                b.token_snapshot=dict(b.token_snapshot,all_total=90600000)
                self.assertFalse(b.refresh_token_snapshot())
        finally:b.close();b.deleteLater();APP.processEvents()

    def test_today_sample_during_preparation_is_delivered_at_handoff(self):
        from compact_bubble import CompactBubble
        from datetime import datetime
        b=CompactBubble();b.show();APP.processEvents()
        try:
            day=datetime.now().date().isoformat()
            b.token_snapshot=dict(month=day[:7],days={day:90520000});b.redraw();APP.processEvents()
            b.size_transition.begin()
            b.set_live_today(dict(day=day,count=90530000,generation=1,revision=1))
            b.set_live_today(dict(day=day,count=90540000,generation=1,revision=2))
            self.assertEqual(b.today_tokens_card.data['count'],90520000)
            b.size_transition.commit();b.size_transition.complete();b.size_transition.release_landing()
            self.assertEqual(b.today_tokens_card.data['count'],90540000)
            self.assertEqual(b.today_tokens_card.roll.target,'90.54M')
            self.assertEqual(b.today_tokens_card.roll.animation.state(),QAbstractAnimation.State.Running)
        finally:b.close();b.deleteLater();APP.processEvents()

