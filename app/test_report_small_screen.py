"""Compressed report bodies and reverse host motion remain usable."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtCore import QRect,QPoint,QPointF,Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication,QScrollArea,QWidget,QVBoxLayout,QLabel
import test_daily_report as report_tests
import test_native_interactions as native_tests
from daily_report import DailyReport
from project_cost_ui import SmoothCostScroll
APP=QApplication.instance() or QApplication([])

def wheel(area,delta):
    point=area.viewport().rect().center();global_point=area.viewport().mapToGlobal(point)
    event=QWheelEvent(QPointF(point),QPointF(global_point),QPoint(),QPoint(0,delta),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
    QApplication.sendEvent(area.viewport(),event)
    return event

class SmallReportTests(unittest.TestCase):
    setUp=report_tests.ReportUiTests.setUp
    tearDown=report_tests.ReportUiTests.tearDown
    def test_overview_cycle_models_scroll_when_compressed_without_showing_bars(self):
        data=report_tests.sample();data['report']['daily_models']=[dict(day='2026-10-17',model='model-'+str(i),total=1000,input=800,output=200,known=True) for i in range(12)]
        self.r.set_snapshot(data)
        with patch.object(self.r,'geometry_for_host',return_value=QRect(100,20,268,220)):
            for page in ('overview','cycle','models'):
                self.r.open(page);self.r.animation.setCurrentTime(self.r.animation.duration());APP.processEvents();self.r.sync_geometry();APP.processEvents()
                area=self.r.scroll;bar=area.verticalScrollBar()
                self.assertGreater(area.viewport().height(),0,page);self.assertGreater(bar.maximum(),0,page)
                self.assertFalse(bar.isVisible(),page);self.assertEqual(area.horizontalScrollBar().maximum(),0,page)
                bar.setValue(0);wheel(area,-120);area._smooth_scroll.animation.setCurrentTime(160)
                self.assertGreater(bar.value(),0,page)
    def test_nested_area_owns_wheel_until_its_boundary_then_outer_moves(self):
        outer=QScrollArea();outer.setWidgetResizable(True);outer.setFixedSize(240,200);outer.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body=QWidget();box=QVBoxLayout(body);inner=QScrollArea();inner.setWidgetResizable(True);inner.setFixedHeight(120)
        long=QLabel('line\n'*50);inner.setWidget(long);box.addWidget(inner);spacer=QWidget();spacer.setFixedHeight(350);box.addWidget(spacer);outer.setWidget(body)
        a=SmoothCostScroll(outer);b=SmoothCostScroll(inner);outer.show();APP.processEvents()
        try:
            self.assertGreater(inner.verticalScrollBar().maximum(),0);self.assertGreater(outer.verticalScrollBar().maximum(),0)
            wheel(inner,-120);b.animation.setCurrentTime(160)
            self.assertGreater(inner.verticalScrollBar().value(),0);self.assertEqual(outer.verticalScrollBar().value(),0)
            inner.verticalScrollBar().setValue(inner.verticalScrollBar().maximum());wheel(inner,-120);a.animation.setCurrentTime(160)
            self.assertGreater(outer.verticalScrollBar().value(),0)
            value=outer.verticalScrollBar().value();wheel(inner,120);b.animation.setCurrentTime(160)
            self.assertEqual(outer.verticalScrollBar().value(),value)
            inner.verticalScrollBar().setValue(0);outer.verticalScrollBar().setValue(100)
            wheel(inner,-120);wheel(inner,120);b.animation.setCurrentTime(160)
            self.assertEqual(outer.verticalScrollBar().value(),100,'Reversing an unfinished inner step must not scroll the outer area')
            wheel(inner,-120);self.assertTrue(b.animation.state().value);outer.hide();APP.processEvents()
            self.assertFalse(b.animation.state().value)
        finally:outer.close();outer.deleteLater();APP.processEvents()

class HostReturnTests(unittest.TestCase):
    setUp=native_tests.InteractionTests.setUp
    tearDown=native_tests.InteractionTests.tearDown
    def test_report_close_holds_host_then_animates_back_without_replaying_chart(self):
        p=self.pet;b=p.bubble;b.set_mode('auto');b.auto_compact=False;b.redraw();b.show();b.size_transition.complete();b.size_transition.release_landing();APP.processEvents()
        r=DailyReport(b);b.report=r;r.set_snapshot(report_tests.sample());original=QRect(b.geometry());displaced=QRect(original);displaced.translate(0,180)
        def target(size=None,**kw):return QRect(displaced if r.requested else original)
        with patch.object(b,'content_geometry',side_effect=target),patch('settings_controls.motion_enabled',return_value=True):
            r.open();b.size_transition.complete();b.size_transition.release_landing();APP.processEvents();r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
            displaced=QRect(b.geometry());self.assertNotEqual(displaced,original)
            r.dismiss();p.position_bubble();self.assertEqual(b.geometry(),displaced)
            r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
            t=b.size_transition;self.assertTrue(t.running);t.animation.setCurrentTime(t.animation.duration()//2)
            current=t.visible_geometry();self.assertGreater(current.y(),original.y());self.assertLess(current.y(),displaced.y())
            t.complete();t.release_landing();APP.processEvents();self.assertEqual(b.geometry(),original)

if __name__=='__main__':unittest.main()
