import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,time
from datetime import datetime,timedelta
from PySide6.QtWidgets import QApplication,QToolButton
from PySide6.QtTest import QTest
from PySide6.QtCore import QPoint,Qt
from token_calendar import usage_series
from token_charts import TokenChartCard

APP=QApplication.instance() or QApplication([])

class SeriesTests(unittest.TestCase):
    def setUp(self):self.now=datetime(2026,10,18,13,40).timestamp()
    def test_seven_and_thirty_cross_months_fill_zero_days_and_exclude_future(self):
        snap=dict(history_days={'2026-09-19':10,'2026-10-12':20,'2026-10-18':30,'2026-10-19':999})
        seven=usage_series(snap,'7d',self.now);thirty=usage_series(snap,'30d',self.now)
        self.assertEqual((len(seven['bins']),seven['total']),(7,50));self.assertEqual((len(thirty['bins']),thirty['total']),(30,60))
        self.assertEqual(thirty['start'],'2026-09-19');self.assertEqual(seven['bins'][1]['value'],0)
    def test_all_buckets_have_exact_totals_without_overlap_or_dropped_days(self):
        start=datetime(2024,1,1);days={(start+timedelta(days=i)).strftime('%Y-%m-%d'):i+1 for i in range(1000)}
        series=usage_series(dict(history_days=days),'all',self.now)
        self.assertLessEqual(len(series['bins']),24);self.assertEqual(series['total'],sum(days.values()))
        for a,b in zip(series['bins'],series['bins'][1:]):
            self.assertEqual(datetime.fromisoformat(a['end'])+timedelta(days=1),datetime.fromisoformat(b['start']))
    def test_hourly_is_consumption_not_cumulative_and_future_is_not_plotted(self):
        hours=[0]*24;hours[1]=100;hours[2]=50;hours[13]=80;hours[22]=900
        series=usage_series(dict(today='2026-10-18',hours=hours),'day',self.now)
        self.assertEqual(series['total'],230);self.assertEqual(series['bins'][2]['value'],50)
        self.assertTrue(series['bins'][13]['current']);self.assertTrue(series['bins'][14]['future'])
        stale=usage_series(dict(today='2026-10-17',hours=hours),'day',self.now)
        self.assertFalse(stale['available']);self.assertEqual(stale['total'],0)

class ChartTests(unittest.TestCase):
    def test_seven_day_usage_tracks_model_breakdown_and_rate(self):
        now=datetime(2026,10,18,13,40).timestamp()
        snapshot=dict(history_days={'2026-10-17':100},report={'daily_models':[
            dict(day='2026-10-17',model='model A',total=60),
            dict(day='2026-10-17',model='model B',total=40)]},rates={'days':{'2026-10-17':{'rate':12.}}})
        card=TokenChartCard(snapshot,period='7d',now=now);card.resize(120,80);card.show();APP.processEvents()
        try:
            card.plot.grab()
            record=card.plot._combo_records[-2]
            self.assertEqual(record['model_count'],2)
            self.assertEqual({name for name,_,_ in record['rows']},{'Token 用量','model A','model B','回合均速'})
        finally:card.close()
    def test_time_filter_pill_animates_without_layout_change(self):
        from unittest.mock import patch
        from PySide6.QtCore import QRectF
        card=TokenChartCard();card.resize(120,80);card.show();APP.processEvents()
        try:
            tabs=card.range_tabs;layout=[button.geometry() for button in tabs.buttons.values()]
            with patch('settings_controls.motion_enabled',return_value=True):
                card.set_period('7d')
                tabs.animation.setCurrentTime(65)
                self.assertGreater(tabs.pill.x(),layout[0].x())
                self.assertLess(tabs.pill.x(),layout[-1].x())
                tabs.animation.setCurrentTime(tabs.animation.duration())
                self.assertEqual(tabs.pill,QRectF(layout[-1]))
                card.set_period('day');tabs.animation.setCurrentTime(tabs.animation.duration())
                self.assertTrue(tabs.pill.isEmpty())
            self.assertEqual(layout,[button.geometry() for button in tabs.buttons.values()])
        finally:card.close()
    def test_small_card_buttons_plot_and_tooltips_fit_all_ranges(self):
        now=datetime(2026,10,18,13,40).timestamp()
        snap=dict(history_days={'2026-10-18':123456},today='2026-10-18',hours=[i*100 for i in range(24)])
        for period in ('all','30d','7d','day'):
            chart=TokenChartCard(snap,period=period,now=now);chart.resize(112,78);chart.show();APP.processEvents();chart.grab()
            for button in chart.findChildren(QToolButton):
                point=button.mapTo(chart,QPoint(0,0));self.assertLessEqual(point.x()+button.width(),112)
                self.assertGreaterEqual(button.width(),24)
            self.assertEqual(len(chart.plot.hits),24 if period=='day' else 30 if period=='30d' else 7 if period=='7d' else 1)
            self.assertTrue(all(rect.right()<=chart.plot.width() for rect,_ in chart.plot.hits))
            self.assertIn('输入含缓存',chart.plot.accessibleDescription())
            if period=='day':
                self.assertEqual(len(chart.plot.points),14)
                self.assertIn('当前小时',chart.plot.detail(chart.plot.series['bins'][13]))
                self.assertIn('尚未到来',chart.plot.detail(chart.plot.series['bins'][14]))
            chart.close()
