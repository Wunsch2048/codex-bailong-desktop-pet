import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from PySide6.QtCore import QPointF,Qt,QRect
from PySide6.QtGui import QImage,QPainter,QColor,QFontMetrics
from PySide6.QtWidgets import QApplication
from rate_chart import rate_paths,missing_rate_pen,inspection_notes,ChartBubble
from token_charts import TokenChartCard
from datetime import datetime
APP=QApplication.instance() or QApplication([])

class RateFloorTests(unittest.TestCase):
    def test_unknown_runs_have_floor_geometry_but_keep_unknown_readout_and_real_zero(self):
        now=datetime(2026,10,30,13).timestamp();items=[None]*24;items[2]=dict(rate=20);items[3]=dict(rate=0);items[7]=dict(rate=30)
        card=TokenChartCard(dict(today='2026-10-30',hours=[10]*24,rates=dict(today=items)),period='day',now=now);card.resize(121,78);card.show();APP.processEvents();p=card.plot;p.grab()
        self.assertIsNone(p._combo_records[5]['rate_item']);self.assertEqual(p._combo_records[3]['rate_item']['rate'],0)
        self.assertFalse(p._missing_path.isEmpty());self.assertFalse(p._solid_rate_path.isEmpty())
        self.assertLessEqual(p._missing_path.boundingRect().right(),p._combo_records[13]['rect'].right())
        self.assertEqual(p._missing_path.boundingRect().bottom(),p.chart_rect().bottom());card.close();card.deleteLater();APP.processEvents()
    def test_geometry_never_changes_measured_anchor_and_unknown_is_not_solid(self):
        points=[QPointF(0,20),QPointF(10,0),QPointF(20,20),QPointF(30,20),QPointF(40,5)]
        solid,weak=rate_paths(points,[True,True,False,False,True])
        self.assertEqual(solid.currentPosition(),points[1]);self.assertEqual(weak.currentPosition(),points[-1])
        self.assertEqual(weak.boundingRect().bottom(),20)
    def test_floor_connections_visibly_have_gaps(self):
        image=QImage(160,12,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing);painter.setPen(missing_rate_pen('#00ffff'))
        painter.drawLine(QPointF(2,6),QPointF(158,6));painter.end()
        occupied=[image.pixelColor(x,6).alpha()>30 for x in range(5,155)]
        self.assertGreater(sum(occupied),30);self.assertGreater(150-sum(occupied),20)
        self.assertGreater(sum(a!=b for a,b in zip(occupied,occupied[1:])),20)
    def test_hover_counts_unknown_future_and_opaque_cross_point_paint(self):
        from typography import ui_font
        host=TokenChartCard({},period='day');host.resize(121,78);host.show();APP.processEvents()
        bubble=ChartBubble();anchor=QRect(100,300,20,20)
        record=dict(label='16:00–17:00',amount='22.20M Token',rate_item=dict(rate=29.,samples=9,valid_samples=6))
        bubble.inspect(record,anchor,host);bubble.animation.stop();bubble.level=1;APP.processEvents();valid=bubble.grab().toImage()
        self.assertIn('6 个已完成回合',bubble.accessibleDescription());self.assertIn('含思考、工具和等待',bubble.accessibleDescription())
        for item in (record,dict(record,rate_item=None),dict(record,rate_item=dict(rate=0.,valid_samples=3)),dict(record,future=True),dict(record,available=False)):
            for text in inspection_notes(item):self.assertLessEqual(QFontMetrics(ui_font(10)).horizontalAdvance(text),208)
        bubble.inspect(dict(record,rate_item=None),anchor,host);bubble.animation.stop();bubble.level=1;APP.processEvents()
        self.assertNotEqual(valid,bubble.grab().toImage());self.assertIn('不表示零速率',bubble.accessibleDescription())
        bubble.inspect(dict(record,rate_item=dict(rate=0.,valid_samples=3)),anchor,host)
        self.assertIn('0.0 tok/s',bubble.accessibleDescription());self.assertIn('3 个已完成回合',bubble.accessibleDescription())
        self.assertEqual(inspection_notes(dict(record,future=True))[0],'尚未到来')
        self.assertEqual(inspection_notes(dict(record,available=False))[0],'暂不可用')
        bubble.dismiss(True);bubble.deleteLater();host.close();host.deleteLater();APP.processEvents()
    def test_hover_median_changes_paint_and_is_unknown_without_valid_samples(self):
        import sys
        from unittest.mock import patch
        host=TokenChartCard({},period='day');host.resize(121,78);host.show();APP.processEvents()
        b=ChartBubble();anchor=QRect(100,300,20,20)
        record=dict(label='12:00–13:00',amount='1.00M Token',rate_item=dict(rate=12,median_rate=40,valid_samples=5))
        b.inspect(record,anchor,host);b.animation.stop();b.level=1;APP.processEvents();first=b.grab().toImage()
        self.assertEqual(b.median_value(),'40.0 tok/s');self.assertIn('回合中位速率 40.0 tok/s',b.accessibleDescription())
        self.assertEqual(b.hint_size(),(230,143))
        changed=dict(record,rate_item=dict(rate=12,median_rate=0,valid_samples=5,first_token_ms=1200))
        b.inspect(changed,anchor,host);b.animation.stop();b.level=1;APP.processEvents()
        self.assertEqual(b.median_value(),'0.0 tok/s');self.assertEqual(b.hint_size(),(230,161));self.assertNotEqual(first,b.grab().toImage())
        errors=[]
        with patch.object(sys,'excepthook',side_effect=lambda *args:errors.append(args)):
            for value in (dict(record,future=True),dict(record,available=False),dict(record,rate_item=None)):
                b.inspect(value,anchor,host);self.assertEqual(b.median_value(),'—')
                b.animation.setCurrentTime(80);APP.processEvents()
        self.assertEqual(errors,[])
        b.dismiss(True);b.deleteLater();host.close();host.deleteLater();APP.processEvents()
