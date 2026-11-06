"""Chart lifecycle regressions: visible starts, preserved clocks, cheap filters."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import copy,unittest
from unittest.mock import patch
from PySide6.QtCore import QAbstractAnimation,QEvent,QPointF,Qt
from PySide6.QtGui import QMouseEvent
from compact_bubble import CompactBubble
from daily_report import DailyReport
from test_daily_report import APP,sample
from token_analytics import model_series

RUNNING=QAbstractAnimation.State.Running

class ReportChartResponseTests(unittest.TestCase):
    def test_combo_columns_grow_from_baseline_without_a_horizontal_wipe(self):
        from daily_report import ReportPlot
        from rate_chart import colors
        from PySide6.QtGui import QColor,QPainter,QPixmap
        p=ReportPlot(dict(hours=[100]*24));p.resize(300,94);p.ensure_layers();builds=p.layer_builds
        target=QColor(colors()[1]);heights=[]
        def height(image,x):
            return sum(max(abs(image.pixelColor(x,y).red()-target.red()),abs(image.pixelColor(x,y).green()-target.green()),abs(image.pixelColor(x,y).blue()-target.blue()))<10
                       for y in range(round(p.chart_rect().top()),round(p.chart_rect().bottom())))
        for progress in (.2,.4,.6,.8,1.):
            p.reveal.progress=progress
            with patch.object(p,'combo_layers',side_effect=AssertionError('entry rebuilt geometry')):image=p.grab().toImage()
            first=height(image,round(p._combo_records[0]['rect'].center().x()));last=height(image,round(p._combo_records[-1]['rect'].center().x()))
            self.assertGreater(first,0);self.assertAlmostEqual(first,last,delta=1);heights.append(first)
        self.assertTrue(all(a<b for a,b in zip(heights,heights[1:])))
        for progress,height in zip((.2,.4,.6,.8,1.),heights):self.assertAlmostEqual(height,heights[-1]*progress,delta=2)
        image=QPixmap(p._layers[1].size());image.setDevicePixelRatio(p.devicePixelRatioF());image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image);painter.drawPicture(0,0,p._combo_bars);painter.drawPicture(0,0,p._combo_trace);painter.end()
        self.assertEqual(image.toImage(),p._layers[1].toImage());self.assertEqual(p.layer_builds,builds)
        p.close();p.deleteLater()

    def test_open_clock_ends_at_the_visual_response_endpoint(self):
        from spring_motion import EXPAND_MS,island_response
        self.r.dismiss();self.finish_open();self.r.open()
        self.assertEqual(self.r.animation.duration(),round(EXPAND_MS*.82))
        for fraction in (.1,.3,.6,.81):
            self.r.animation.setCurrentTime(round(self.r.animation.duration()*fraction))
            actual=self.r.animation.currentTime()/self.r.animation.duration()
            self.assertAlmostEqual(self.r.fraction,island_response(actual*.82),places=6)
        self.finish_open();self.assertFalse(self.r._animating);self.assertTrue(self.r.surface.isVisible())
        self.assertEqual(self.r.plot.reveal.animation.duration(),420)

    def test_model_bar_entry_reuses_commands_and_has_exact_static_endpoint(self):
        from daily_report import ReportPlot
        from PySide6.QtGui import QPainter,QPixmap
        p=ReportPlot(sample()['report'],'bars','all');p.resize(300,94);p.ensure_layers();builds=p.layer_builds
        self.assertIsNotNone(p._bar_commands)
        def endpoint(vector):
            image=QPixmap(p._layers[1].size());image.setDevicePixelRatio(p.devicePixelRatioF());image.fill(Qt.GlobalColor.transparent)
            painter=QPainter(image)
            if vector:painter.drawPicture(0,0,p._bar_commands)
            else:painter.drawPixmap(0,0,p._layers[1])
            painter.end();return image.toImage()
        self.assertEqual(endpoint(True),endpoint(False))
        with patch.object(p,'render_layers',side_effect=AssertionError('entry rebuilt chart geometry')):
            for progress in (.9,.95,.98,.995,1.):p.reveal.progress=progress;p.grab()
        self.assertEqual(p.layer_builds,builds);p.close();p.deleteLater()

    def setUp(self):
        self.b=CompactBubble();self.b.move(100,650);self.b.show();APP.processEvents()
        self.r=DailyReport(self.b);self.b.report=self.r;self.r.set_snapshot(sample())
        self.r.open();self.finish_open()
    def tearDown(self):
        self.r.close();self.b.close();self.b.deleteLater();APP.processEvents()
    def finish_open(self):
        self.r.animation.setCurrentTime(self.r.animation.duration());APP.processEvents()
    def finish_page(self):
        if self.r.page_fade.animation.state()==RUNNING:
            self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration())
        APP.processEvents()
    def assert_revealing(self):
        self.finish_page()
        self.assertTrue(self.r.plot.isVisible());self.assertFalse(self.r.plot.reveal.pending)
        self.assertEqual(self.r.plot.reveal.animation.state(),RUNNING)
        self.assertLess(self.r.plot.reveal.progress,.2)
    def test_both_tabs_start_reveal_only_after_new_plot_is_visible(self):
        for page in ('models','overview','models'):
            self.r.set_page(page);self.assert_revealing()
            plot=self.r.plot;plot.reveal.animation.setCurrentTime(90);first=plot.grab().toImage()
            plot.reveal.animation.setCurrentTime(400);second=plot.grab().toImage()
            self.assertNotEqual(first,second)
    def test_identical_and_unrelated_refresh_leave_both_plot_clocks_untouched(self):
        for page in ('overview','models'):
            self.r.set_page(page);self.finish_page()
            p=self.r.plot;p.reveal.animation.setCurrentTime(180)
            progress=p.reveal.progress;ms=p.reveal.animation.currentTime();scroll=self.r.scroll
            refreshed=copy.deepcopy(self.r.snapshot)
            self.r.set_snapshot(refreshed)
            refreshed=copy.deepcopy(refreshed);refreshed['report']['all_total']+=5000
            refreshed['report']['sessions']+=1;self.r.set_snapshot(refreshed)
            self.assertIs(self.r.plot,p);self.assertIs(self.r.scroll,scroll)
            self.assertEqual(p.reveal.progress,progress);self.assertEqual(p.reveal.animation.currentTime(),ms)
            self.assertEqual(p.reveal.animation.state(),RUNNING)
    def test_changed_chart_data_updates_existing_plot_without_skipping_animation(self):
        for page in ('overview','models'):
            self.r.set_page(page);self.finish_page()
            p=self.r.plot;p.reveal.animation.setCurrentTime(150);progress=p.reveal.progress
            refreshed=copy.deepcopy(self.r.snapshot)
            refreshed['report']['hours'][3]+=100
            refreshed['report']['daily_models'][0]['total']+=100
            self.r.set_snapshot(refreshed)
            self.assertIs(self.r.plot,p);self.assertEqual(p.reveal.progress,progress)
            self.assertEqual(p.reveal.animation.state(),RUNNING)
            if page=='overview':self.assertEqual(p.report['hours'][3],12100)
            else:self.assertEqual(p.series['total'],sum(x['total'] for x in refreshed['report']['daily_models']))
    def test_background_snapshots_do_not_rebuild_columns_mid_entry(self):
        p=self.r.plot;p.ensure_layers();p.reveal.animation.setCurrentTime(150);builds=p.layer_builds
        for value in (700_000,900_000):
            refreshed=copy.deepcopy(self.r.snapshot);refreshed['report']['hours'][3]=value
            self.r.set_snapshot(refreshed)
            with patch.object(p,'render_layers',side_effect=AssertionError('background data changed active entry')):p.grab()
            self.assertEqual(p.layer_builds,builds);self.assertTrue(p._pending_chart_data)
        p.reveal.animation.setCurrentTime(p.reveal.animation.duration());p.grab()
        self.assertFalse(p._pending_chart_data);self.assertEqual(p.layer_builds,builds+1)
        self.assertEqual(p.report['hours'][3],900_000)
    def test_periods_and_models_reuse_plot_rows_and_cached_aggregation(self):
        with patch('daily_report.model_series',wraps=model_series) as aggregate:
            self.r.set_page('models');APP.processEvents();p=self.r.plot;scroll=self.r.scroll;rows=list(self.r.model_rows)
            self.assertEqual(aggregate.call_count,1)
            for period in ('7d','30d','all','7d'):
                self.r.set_period(period);self.assert_revealing()
                self.assertIs(self.r.plot,p);self.assertIs(self.r.scroll,scroll)
                self.assertEqual(self.r.model_rows,rows)
            self.assertEqual(aggregate.call_count,3)
            for model in ('gpt-6.1-sol','gpt-6-sol','gpt-6-sol'):
                self.r.select_model(model);self.assert_revealing();self.assertIs(self.r.plot,p)
            self.assertEqual(aggregate.call_count,3)
            self.assertIsNone(self.r.selected_model)
    def test_latest_rapid_interaction_wins_and_discarded_plot_stays_stopped(self):
        old=self.r.plot
        self.r.set_page('models');self.r.set_period('7d');self.r.select_model('gpt-6-sol')
        self.r.set_period('30d');self.r.select_model('gpt-6.1-sol')
        self.assert_revealing()
        self.assertEqual(len(self.r.plot.series['bins']),30)
        self.assertEqual(self.r.plot.selected,'gpt-6.1-sol')
        self.assertEqual(old.reveal.animation.state(),QAbstractAnimation.State.Stopped)
    def test_updates_while_opening_preserve_window_frame_then_start_new_chart(self):
        self.r.dismiss();self.finish_open();self.r.open();self.r.animation.setCurrentTime(100)
        key=self.r._frame.cacheKey();geometry=self.r.geometry()
        self.r.set_page('models');self.r.set_period('7d')
        refreshed=copy.deepcopy(sample());refreshed['report']['messages']=999;self.r.set_snapshot(refreshed)
        self.assertEqual(self.r._frame.cacheKey(),key);self.assertEqual(self.r.geometry(),geometry)
        self.finish_open();self.assert_revealing()
        self.assertEqual(self.r.report['messages'],999);self.assertEqual(len(self.r.plot.series['bins']),7)
    def test_noop_checked_tabs_do_not_restart_animation_or_uncheck_themselves(self):
        self.r.set_page('models');APP.processEvents();p=self.r.plot;p.reveal.animation.setCurrentTime(200)
        self.r.page_buttons['models'].click();self.r.range_buttons['all'].click()
        self.assertTrue(self.r.page_buttons['models'].isChecked());self.assertTrue(self.r.range_buttons['all'].isChecked())
        self.assertIs(self.r.plot,p);self.assertEqual(p.reveal.animation.currentTime(),200)
    def test_reversing_close_resumes_chart_from_its_frozen_progress(self):
        p=self.r.plot;p.reveal.animation.setCurrentTime(210);progress=p.reveal.progress
        self.r.dismiss();self.r.animation.setCurrentTime(90)
        self.assertEqual(p.reveal.animation.state(),QAbstractAnimation.State.Stopped)
        self.r.open();self.finish_open()
        self.assertIs(self.r.plot,p);self.assertAlmostEqual(p.reveal.progress,progress,places=5)
        self.assertEqual(p.reveal.animation.state(),RUNNING)
        p.reveal.animation.setCurrentTime(620);self.assertEqual(p.reveal.progress,1.)
    def test_hover_emits_only_changed_hour_and_clears_outside_chart(self):
        p=self.r.plot;p.grab();emitted=[];p.hoverText.connect(emitted.append)
        center=p.hits[3][0].center()
        for pos in (center,center+QPointF(.1,0),QPointF(1,1),QPointF(2,1)):
            APP.sendEvent(p,QMouseEvent(QEvent.Type.MouseMove,pos,pos,Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
        self.assertEqual(emitted,[p.hits[3][1],''])

if __name__=='__main__':unittest.main()
