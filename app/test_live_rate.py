import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QAbstractAnimation
from live_rate import LiveOutputRate,display
from live_rate_ui import LiveRateCard
from compact_bubble import CompactBubble
from surface_morph import SurfaceState,SharedPart

APP=QApplication.instance() or QApplication([])
def count(value):return dict(type='token_count',info=dict(total_token_usage=dict(output_tokens=value)))

class LiveRateTests(unittest.TestCase):
    @patch('live_rate.time.time',return_value=1000)
    def test_recent_delta_expiry_finish_and_historical_not_live(self,_):
        r=LiveOutputRate();r.ingest('s',count(100),990,historical=True,now=0)
        self.assertIsNone(r.snapshot(0)['rate'])
        r.ingest('s',dict(type='task_started'),999,now=1);r.ingest('s',count(140),1001,now=3)
        self.assertEqual(r.snapshot(3)['rate'],20);self.assertIsNone(r.snapshot(16)['rate'])
        r.ingest('s',dict(type='task_complete'),1002,now=4);self.assertIsNone(r.snapshot(4)['rate'])
    @patch('live_rate.time.time',return_value=1000)
    def test_no_counter_reset_spike_backlog_or_duplicate_timestamp(self,_):
        r=LiveOutputRate();r.ingest('s',count(100),999,historical=True,now=0);r.ingest('s',dict(type='task_started'),999,now=1)
        r.ingest('s',count(120),1000,now=2);self.assertEqual(r.snapshot(2)['rate'],20)
        r.ingest('s',count(120),1000,now=2);self.assertEqual(r.snapshot(2)['rate'],20)
        r.ingest('s',count(1),1001,now=3);self.assertIsNone(r.snapshot(3)['rate'])
        r.ingest('s',count(100000),900,now=4);self.assertIsNone(r.snapshot(4)['rate'])
    @patch('live_rate.time.time',return_value=1000)
    def test_all_supported_terminal_aliases_stop_rate_without_waiting_for_expiry(self,_):
        for kind in ('task_complete','task_completed','task_aborted','turn_aborted','turn_completed','turn_cancelled'):
            with self.subTest(kind=kind):
                r=LiveOutputRate();r.ingest('s',count(100),999,historical=True,now=0)
                r.ingest('s',dict(type='task_started'),999,now=1);r.ingest('s',count(140),1001,now=3)
                self.assertEqual(r.snapshot(3)['rate'],20)
                r.ingest('s',dict(type=kind),1002,now=4)
                self.assertIsNone(r.snapshot(4)['rate']);self.assertEqual(r.snapshot(4)['details'],[])
    def test_display_missing_and_large_numbers_are_bounded(self):
        self.assertEqual(display(None),'—');self.assertEqual(display(float('nan')),'—')
        self.assertEqual(display(1024.6),'1,024.6');self.assertEqual(display(10000),'10.0k')
    def test_value_only_animation_unit_anchor_and_hidden_timer_stop(self):
        card=LiveRateCard();card.resize(121,20);card.show();APP.processEvents()
        unit=None
        for value in (9.8,42.6,128.4,1024.6,100000):
            card.set_data(dict(rate=value));card.grab();self.assertEqual(card.number_rect.right()+4,card.unit_x)
            if unit is not None:self.assertEqual(card.unit_x,unit)
            unit=card.unit_x
        card.hide();self.assertEqual(card.animation.state(),QAbstractAnimation.State.Stopped);card.deleteLater();APP.processEvents()
    def test_both_footer_modules_are_shared_in_both_morph_directions(self):
        b=CompactBubble();b.show();APP.processEvents()
        def capture(expanded):
            b.expanded=expanded;b.bubble_mode='auto';b.redraw();APP.processEvents();return SurfaceState.capture(b)
        a,z=capture(False),capture(True)
        for start,end in ((a,z),(z,a)):
            for key in ('live_rate','live_rate_value','today_tokens','today_tokens_amount','today_tokens_link'):
                self.assertIn(key,start.shared_bounds);self.assertIn(key,end.shared_bounds)
                part=SharedPart(start,end,key);self.assertEqual(part.fit,'left' if key in ('live_rate','today_tokens') else 'right')
            self.assertLess(abs(start.shared_bounds['live_rate'].width()-start.shared_bounds['today_tokens'].width()),2)
        b.close();b.deleteLater();APP.processEvents()
    def test_visible_sample_expires_without_further_worker_events(self):
        import time
        from PySide6.QtTest import QTest
        card=LiveRateCard();card.resize(121,20);card.show();APP.processEvents()
        card.set_data(dict(rate=42.6,expires=time.monotonic()+.02));QTest.qWait(60)
        self.assertIsNone(card.value['rate']);self.assertFalse(card.expiry.isActive())
        card.close();card.deleteLater();APP.processEvents()
    @patch('live_rate.time.time',return_value=1100)
    def test_sparse_samples_and_mid_task_attach_keep_observation_until_next_batch(self,_):
        r=LiveOutputRate();r.ingest('a',count(100),1040,historical=True,now=0)
        r.ingest('a',count(1300),1100,now=60)
        value=r.snapshot(100)
        self.assertEqual(value['rate'],20);self.assertEqual(value['details'][0]['interval'],60)
        self.assertTrue(value['details'][0]['waiting']);self.assertEqual(value['details'][0]['sampled_at'],1100)
        self.assertIsNone(r.snapshot(211)['rate'])
    @patch('live_rate.time.time',return_value=1100)
    def test_per_session_details_sum_matches_footer_and_expiry_removes_only_that_session(self,_):
        r=LiveOutputRate()
        for sid,delta in [('a',40),('b',20)]:
            r.ingest(sid,count(100),1098,historical=True,now=0);r.ingest(sid,dict(type='task_started'),1098,now=0);r.ingest(sid,count(100+delta),1100,now=2)
        value=r.snapshot(3);self.assertEqual(value['rate'],30);self.assertEqual({d['session']:d['rate'] for d in value['details']},{'a':20,'b':10})
        r.ingest('b',dict(type='task_complete'),1101,now=4)
        self.assertEqual(r.snapshot(5)['rate'],20);self.assertEqual(len(r.snapshot(5)['details']),1)
    def test_session_popup_refresh_is_live_and_hides_with_card(self):
        from PySide6.QtCore import QPoint
        card=LiveRateCard(dict(rate=30,details=[dict(session='a',name='桌宠',rate=20),dict(session='b',name='代码检查',rate=10)]));card.resize(121,20);card.show();APP.processEvents()
        with patch('live_rate_ui.QCursor.pos',return_value=card.mapToGlobal(card.rect().center())):
            card._show_hint();card.hint_watch.stop();APP.processEvents()
        self.assertTrue(card.popup.isVisible());self.assertEqual(len(card.popup.rows),2);self.assertEqual(card.toolTip(),'')
        card.set_data(dict(rate=25,details=[dict(session='a',name='桌宠',rate=15),dict(session='b',name='代码检查',rate=10)]))
        self.assertEqual(card.popup.rows[0]['rate'],15);card.hide();self.assertFalse(card.popup.isVisible());self.assertFalse(card.hint_watch.isActive());card.close();card.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
