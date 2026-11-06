"""Cold/reused tool surfaces are seeded before native visibility, never at idle."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QRect,QPoint,Qt,QEvent
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest
from hover_hints import HintBubble
from panel_transition import NativeLanding
from linked_report_motion import LinkedReportMotion
from quota_summary import QuotaSummary

APP=QApplication.instance() or QApplication([])

class ColdHoverTests(unittest.TestCase):
    def setUp(self):self.owner=QWidget();self.owner.show();APP.processEvents();self.widgets=[]
    def tearDown(self):
        for w in self.widgets:w.close();w.deleteLater()
        self.owner.close();self.owner.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
    def test_hint_cold_and_reused_show_seed_transparent_pixels_before_show(self):
        popup=HintBubble();self.widgets.append(popup);events=[];show=popup.show
        def publish(w,image):events.append(('publish',w.isVisible(),image));return True
        def shown():events.append(('show',popup.native_seeded,None));show()
        with patch('hover_hints.QApplication.platformName',return_value='windows'),patch('native_landing.publish',side_effect=publish),patch.object(popup,'show',side_effect=shown):
            for title in ('刷新','详情'):
                popup.present(title,'',QRect(100,200,24,24),self.owner.screen(),owner=self.owner,topmost=False)
                self.assertEqual(events[-2:], [('publish',False,None),('show',True,None)])
                self.assertEqual(popup.level,0.);popup.dismiss(True)
    def test_visible_hint_data_update_does_not_clear_native_store_or_drop_alpha(self):
        popup=HintBubble();self.widgets.append(popup)
        popup.present('额度 80%','等待刷新',QRect(100,200,24,24),self.owner.screen(),owner=self.owner,topmost=False,initial_level=1.)
        with patch('hover_hints.QApplication.platformName',return_value='windows'),patch('native_landing.publish') as publish:
            popup.present('额度 79%','等待刷新',QRect(100,200,24,24),self.owner.screen(),owner=self.owner,topmost=False)
            self.assertEqual(popup.level,1.);publish.assert_not_called();self.assertTrue(popup.isVisible())
    def test_guard_submits_target_bitmap_before_cold_show_and_again_after(self):
        guard=NativeLanding(self.owner);self.widgets.append(guard);image=QPixmap(60,40);image.fill(QColor('red'));events=[]
        def publish(w,pixels):events.append((w.isVisible(),pixels is image));return True
        with patch('native_landing.publish',side_effect=publish):guard.present(image,QRect(10,10,60,40))
        self.assertEqual(events,[(False,True),(True,True)]);self.assertTrue(guard.pre_show_published);self.assertTrue(guard.native_published)
    def test_open_report_parks_guards_hidden_instead_of_showing_empty_native_windows(self):
        report=QWidget();self.widgets.append(report);report.bubble=self.owner;report.requested=True;report.show();motion=LinkedReportMotion(report)
        for guard in (motion.landing,motion.shield):
            with patch.object(guard,'prepare',wraps=guard.prepare) as prepare:
                motion.park(guard);prepare.assert_not_called();self.assertFalse(guard.isVisible());self.assertIsNone(guard.image)
    def test_quota_hover_recovers_after_layout_show_without_another_mouse_move(self):
        card=QuotaSummary([dict(name='一周',remaining=80)]);self.widgets.append(card);card.resize(121,102);card.show();APP.processEvents()
        point=card.mapToGlobal(card.row_rect(0).center().toPoint())
        with patch.object(card,'underMouse',return_value=True),patch('quota_summary.QCursor.pos',return_value=point):
            card._sync_hover();self.assertEqual(card.active,0);card.hide();self.assertIsNone(card.active)
            card.show();APP.processEvents();self.assertEqual(card.active,0)
    def test_token_background_scan_updates_open_inspection_without_hiding(self):
        from datetime import datetime
        from token_charts import TokenPlot
        now=datetime(2026,10,2,13).timestamp();data=dict(today='2026-10-02',month='2026-10',days={'2026-10-02':100},hours=list(range(24)))
        plot=TokenPlot(data,'day',now=now);self.widgets.append(plot);plot.resize(160,80);plot.show();APP.processEvents();plot.reveal.animation.stop();plot.reveal.progress=1.;plot.grab()
        plot.inspect_at(plot.hits[3][0].center());plot.show_inspection();self.assertTrue(plot._popup.isVisible());before=plot._popup.record['amount']
        new=dict(data,hours=[n+100 for n in data['hours']])
        with patch.object(plot._popup,'hide',wraps=plot._popup.hide) as hide:plot.set_data(new,'day',now);hide.assert_not_called()
        self.assertTrue(plot._popup.isVisible());self.assertNotEqual(plot._popup.record['amount'],before)
        plot.set_data(new,'7d',now);self.assertFalse(plot._popup.isVisible())
    def test_daily_and_model_background_refresh_keep_hover_while_filter_change_clears_it(self):
        import copy
        import test_daily_report as fixture
        from daily_report import ReportPlot
        from token_analytics import model_series
        for mode in ('line','bars'):
            data=fixture.sample()['report'];series=model_series(data,'7d') if mode=='bars' else None
            plot=ReportPlot(data,mode=mode,series=series);self.widgets.append(plot);plot.resize(246,94);plot.show();APP.processEvents();plot.reveal.animation.stop();plot.reveal.progress=1.;plot.grab()
            plot.inspect_at(plot._combo_records[0]['rect'].center());plot.show_inspection();self.assertTrue(plot._popup.isVisible())
            new=copy.deepcopy(data);new['hours'][0]+=100;new_series=model_series(new,'7d') if mode=='bars' else None
            with patch.object(plot._popup,'hide',wraps=plot._popup.hide) as hide:plot.set_data(new,new_series);hide.assert_not_called()
            self.assertTrue(plot._popup.isVisible());self.assertEqual(plot._popup.level,1.)
            plot.set_data(new,new_series,selected='different-model');self.assertFalse(plot._popup.isVisible())
            plot.close()

