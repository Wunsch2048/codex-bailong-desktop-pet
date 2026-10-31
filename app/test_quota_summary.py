"""Exercise the quota card through real bubble navigation and Qt events."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time,unittest
from datetime import datetime
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent,QAbstractAnimation
from PySide6.QtGui import QMouseEvent,QHelpEvent,QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QToolTip,QLabel
from compact_bubble import CompactBubble
from quota_summary import QuotaSummary,TodayTokens
from token_charts import TokenChartCard
from reset_watch import local_time

APP=QApplication.instance() or QApplication([])


def drain():
    APP.processEvents();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def move_to(widget,point):
    APP.sendEvent(widget,QMouseEvent(QEvent.Type.MouseMove,QPointF(point),
        QPointF(widget.mapToGlobal(point)),Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))


def painted_text(widget):
    """Observe actual painted text without requiring a platform screenshot."""
    values=[]
    class TextRecorder(QPainter):
        def drawText(self,*args):
            if args and isinstance(args[-1],str):values.append(args[-1])
            return super().drawText(*args)
    # Text is now rasterized once per data/hover change, not every frame.
    widget._static_key=None
    with patch('quota_summary.QPainter',TextRecorder):widget.grab()
    return values


class QuotaCardTests(unittest.TestCase):
    def test_increase_and_decline_use_distinct_green_and_red_badges(self):
        cards=[]
        try:
            for value in (-19,15):
                card=QuotaSummary([dict(name='一周',remaining=69)],anomaly=dict(change=value,description='本轮与上一周期比较'))
                cards.append(card)
            self.assertEqual(cards[0].alert_badge.text(),'-19%')
            self.assertEqual(cards[1].alert_badge.text(),'+15%')
            from theme_registry import palette
            self.assertIn(palette()['dangerBg'],cards[0].alert_badge.styleSheet())
            self.assertIn(palette()['successBg'],cards[1].alert_badge.styleSheet())
            self.assertIn('上涨',cards[1].alert_badge.accessibleName())
        finally:
            for card in cards:card.deleteLater()
            drain()
    def test_decline_badge_is_inside_week_row_and_does_not_increase_card_height(self):
        for windows in ([dict(name='一周',remaining=73)],
                        [dict(name='5小时',remaining=40),dict(name='一周',remaining=73)]):
            alert=dict(change=-25,description='较上一轮推测总量下降25%',text='推测总量 -25%')
            card=QuotaSummary(windows,anomaly=alert);card.setFixedWidth(121);self.windows.append(card);card.show();drain()
            self.assertEqual(card.height(),102);self.assertEqual(card.alert_badge.text(),'-25%')
            self.assertTrue(card.row_rect(card.week_index).contains(card.alert_rect()))
            events=[];card.anomalyRequested.connect(lambda:events.append('comparison'))
            QTest.mouseClick(card.alert_badge,Qt.MouseButton.LeftButton)
            self.assertEqual(events,['comparison']);self.assertIn('下降',card.accessibleDescription())

    def setUp(self):self.windows=[]
    def tearDown(self):
        for widget in self.windows:widget.close();widget.deleteLater()
        drain()
    def card(self,windows,clock=None,cache=None):
        widget=QuotaSummary(windows,clock=clock,progress_cache=cache)
        widget.setFixedWidth(121);widget.show();self.windows.append(widget);drain();return widget
    def test_reset_deadline_invalidates_old_value_and_requests_refresh_once(self):
        now=[2000000000.];stamp=now[0]+20
        card=self.card([dict(name='5小时',remaining=72,resetsAt=stamp)],clock=lambda:now[0])
        requests=[];card.resetDue.connect(requests.append)
        self.assertEqual(card.items[0]['remaining'],72)
        now[0]=stamp;card._refresh_time()
        self.assertIsNone(card.items[0]['remaining']);self.assertIsNone(card.items[0]['progress'])
        self.assertEqual(card.items[0]['display'],'—');self.assertEqual(card.values['quota:5小时'],0)
        self.assertIn('待刷新',painted_text(card));self.assertNotIn('72%',painted_text(card))
        for _ in range(4):card._refresh_time()
        self.assertEqual(requests,[stamp]);self.assertIn('旧值不代表',card.accessibleDescription())
    def test_hover_replaces_countdown_with_precise_time_inside_card_only(self):
        now=2000000000.;stamp=now+3660
        card=self.card([dict(name='5小时',remaining=72,resetsAt=stamp)],clock=lambda:now)
        relative=card.items[0]['reset_text'];exact=local_time(stamp)+' 重置'
        self.assertIn(relative,painted_text(card));self.assertNotIn(exact,painted_text(card))
        point=card.row_rect(0).center().toPoint();move_to(card,point)
        self.assertEqual(card.active,0);self.assertIn(exact,painted_text(card));self.assertNotIn(relative,painted_text(card))
        with patch.object(QToolTip,'showText') as show:
            APP.sendEvent(card,QHelpEvent(QEvent.Type.ToolTip,point,card.mapToGlobal(point)));show.assert_not_called()
        self.assertEqual(card.toolTip(),'')
        APP.sendEvent(card,QEvent(QEvent.Type.Leave));self.assertIn(relative,painted_text(card))
    def test_hidden_card_stops_countdown_and_progress_animation(self):
        card=self.card([dict(name='一周',remaining=82,resetsAt=time.time()+3600)])
        card.begin_reveal();card.start_reveal();card.animation.setCurrentTime(100)
        self.assertTrue(card.timer.isActive());self.assertEqual(card.animation.state(),QAbstractAnimation.State.Running)
        card.hide();value=dict(card.values);drain()
        self.assertFalse(card.timer.isActive());self.assertEqual(card.animation.state(),QAbstractAnimation.State.Stopped)
        self.assertEqual(card.values,value)
    def test_showing_card_after_hidden_reset_never_exposes_old_percentage(self):
        now=[2000000000.];stamp=now[0]+20
        card=self.card([dict(name='一周',remaining=72,resetsAt=stamp)],clock=lambda:now[0])
        requests=[];card.resetDue.connect(requests.append);card.hide();now[0]=stamp+1
        card.show();self.assertNotIn('72%',painted_text(card));drain()
        self.assertIsNone(card.items[0]['remaining'])
        self.assertEqual(requests,[stamp])
    def test_second_window_expiry_requests_new_refresh_if_first_stays_stale(self):
        now=[2000000000.];first=now[0]+10;second=now[0]+20
        card=self.card([dict(name='5小时',remaining=42,resetsAt=first),
                        dict(name='一周',remaining=72,resetsAt=second)],clock=lambda:now[0])
        requests=[];card.resetDue.connect(requests.append)
        now[0]=first;card._refresh_time();self.assertEqual(requests,[first])
        now[0]=second;card._refresh_time();self.assertEqual(requests,[first,second])
        card._refresh_time();self.assertEqual(requests,[first,second])


class QuotaBubbleTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.windows=[dict(name='一周',remaining=73,resetsAt=time.time()+86400)]
        now=datetime.now();today=now.strftime('%Y-%m-%d')
        self.b.token_snapshot=dict(month=now.strftime('%Y-%m'),days={today:250000},total=250000)
        self.b.status='正在编辑文件';self.b.redraw();self.b.show();drain()
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater();drain()
    def visible(self,kind):return next(w for w in self.b.findChildren(kind) if w.isVisible())
    def test_single_and_dual_quota_preserve_normal_panel_size(self):
        for windows in ([dict(name='一周',remaining=73)],
                        [dict(name='一周',remaining=73),dict(name='5小时',remaining=29)]):
            self.b.windows=windows;self.b.redraw();drain()
            self.assertEqual((self.b.width(),self.b.height()),(268,186))
            self.assertEqual(len(self.visible(QuotaSummary).items),len(windows))
            self.assertEqual((self.visible(QuotaSummary).width(),self.visible(QuotaSummary).height()),(121,102))
            self.assertEqual(self.visible(TodayTokens).height(),20)
    def test_today_tokens_click_opens_daily_chart_without_opening_details(self):
        self.b.select_dashboard('reset');drain();size=self.b.size();events=[]
        self.b.tokenRangeChanged.connect(events.append)
        daily=self.visible(TodayTokens);QTest.mouseClick(daily,Qt.MouseButton.LeftButton,pos=QPoint(80,10));drain()
        self.assertEqual(self.b.dashboard_page,'tokens');self.assertEqual(self.b.token_range,'day')
        self.assertEqual(self.visible(TokenChartCard).period,'day');self.assertEqual(events,['day'])
        self.assertFalse(self.b.expanded);self.assertIsNone(self.b.details_tabs);self.assertEqual(self.b.size(),size)
        self.assertTrue(daily.selected);self.assertIn('当前显示',daily.accessibleName())
        self.assertNotIn('day',self.visible(TokenChartCard).range_buttons)
    def test_repeated_hourly_entry_keeps_plot_and_animation_then_range_switch_clears_selection(self):
        self.b.show_today_tokens();drain();card=self.visible(TokenChartCard);plot=card.plot;daily=self.visible(TodayTokens)
        plot.reveal.animation.setCurrentTime(130);progress=plot.reveal.progress;events=[]
        self.b.tokenRangeChanged.connect(events.append)
        for _ in range(3):QTest.mouseClick(daily,Qt.MouseButton.LeftButton,pos=QPoint(80,10))
        self.assertIs(self.visible(TokenChartCard).plot,plot);self.assertEqual(plot.reveal.progress,progress)
        self.assertEqual(events,[]);self.assertTrue(daily.selected)
        card.range_buttons['7d'].click()
        self.assertEqual(self.b.token_range,'7d');self.assertFalse(daily.selected);self.assertEqual(plot.series['mode'],'bars')
        self.assertEqual(events,['7d']);self.assertTrue(card.range_buttons['7d'].isChecked())
    def test_hourly_selection_tracks_reset_page_redraw_and_saved_range(self):
        self.b.show_today_tokens();drain();self.assertTrue(self.visible(TodayTokens).selected)
        self.b.select_dashboard('reset');self.assertFalse(self.visible(TodayTokens).selected)
        self.b.redraw();drain();self.assertFalse(self.visible(TodayTokens).selected)
        self.b.select_dashboard('tokens');self.assertTrue(self.visible(TodayTokens).selected)
        self.b.redraw();drain();self.assertEqual(self.visible(TokenChartCard).period,'day')
        self.assertTrue(self.visible(TodayTokens).selected)
    def test_quota_click_selects_quota_details_even_after_another_detail_tab(self):
        self.b.detail_tab='reset';card=self.visible(QuotaSummary)
        QTest.mousePress(card,Qt.MouseButton.LeftButton,pos=QPoint(40,40));self.assertTrue(card.pressed)
        QTest.mouseRelease(card,Qt.MouseButton.LeftButton,pos=QPoint(40,40))
        self.b.size_transition.complete();drain()
        self.assertTrue(self.b.expanded);self.assertEqual(self.b.detail_tab,'quota')
        self.assertEqual(self.b.details_tabs.currentIndex(),self.b.details_tabs.keys.index('quota'))
    def test_reset_refresh_is_deduplicated_across_bubble_rebuilds(self):
        events=[];self.b.quotaRefreshRequested.connect(lambda:events.append('refresh'))
        self.b.windows=[dict(name='一周',remaining=73,resetsAt=time.time()-1)]
        self.b.redraw()
        for _ in range(3):drain()
        self.assertEqual(events,['refresh']);self.assertIsNone(self.visible(QuotaSummary).items[0]['remaining'])
        for _ in range(3):self.b.redraw();drain()
        self.assertEqual(events,['refresh'])
        card=self.visible(QuotaSummary);QTest.mouseClick(card,Qt.MouseButton.LeftButton,pos=QPoint(30,30))
        self.b.size_transition.complete();drain()
        quota_labels=[w.text() for w in self.b.details_tabs.areas['quota'].findChildren(QLabel)]
        self.assertFalse(any('73%' in text for text in quota_labels))
    def test_two_expired_windows_do_not_ping_pong_refresh_when_rebuilt(self):
        now=time.time();first=now-20;second=now-10;events=[]
        self.b.quotaRefreshRequested.connect(lambda:events.append('refresh'))
        self.b.windows=[dict(name='5小时',remaining=42,resetsAt=first),
                        dict(name='一周',remaining=73,resetsAt=second)]
        # Both deadlines may be handled in one refresh; rebuilding must never
        # alternate between old deadline notifications and retry forever.
        self.b.redraw()
        for _ in range(5):drain()
        count=len(events);self.assertGreater(count,0);self.assertLessEqual(count,2)
        for _ in range(5):self.b.redraw();drain()
        self.assertEqual(len(events),count)
    def test_panel_entry_reveals_from_zero_and_status_updates_keep_its_clock(self):
        self.b.set_mode('mini');self.b.size_transition.complete();drain()
        self.b.set_mode('auto');self.assertTrue(self.b.size_transition.running)
        drain();card=self.b.content.findChildren(QuotaSummary)[0]
        self.assertEqual(card.values['quota:一周'],0)
        self.b.size_transition.complete();card.animation.setCurrentTime(120)
        before=card.values['quota:一周'];self.assertGreater(before,0);self.assertLess(before,.73)
        for i in range(30):self.b.message('状态更新 '+str(i))
        self.assertIs(self.visible(QuotaSummary),card);self.assertEqual(card.animation.currentTime(),120)
        self.assertAlmostEqual(card.values['quota:一周'],before)
        card.animation.setCurrentTime(card.animation.duration());self.assertAlmostEqual(card.values['quota:一周'],.73)


if __name__=='__main__':unittest.main()
