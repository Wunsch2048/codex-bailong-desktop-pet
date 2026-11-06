"""Range-row changes share one body-only raster transition, not a layout jump."""
import os,unittest,time
from contextlib import nullcontext
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from PySide6.QtCore import QPoint,QRect
from PySide6.QtGui import QPainter,QColor
from PySide6.QtWidgets import QWidget
import test_daily_report as report_fixture
APP=report_fixture.APP
from compact_bubble import CompactBubble
from quota_summary import QuotaSummary,quota_color
from daily_report import ReportPlot
from theme_registry import NAMES,activate,current,palette

class ScopeMotionTests(unittest.TestCase):
    def setUp(self):
        self.f=report_fixture.ReportUiTests();self.f.setUp();self.r=self.f.r;self.r.open();self.f.complete();APP.processEvents()
    def tearDown(self):self.f.tearDown()
    def finish(self):
        self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration());APP.processEvents()
    def test_scope_and_body_move_together_with_stable_navigation_and_outer_bounds(self):
        r=self.r;tabs=r.page_buttons['overview'].parentWidget();tab_rect=QRect(tabs.mapTo(r.surface,QPoint()),tabs.size())
        bounds=r.geometry();size=r.surface.size()
        with patch('settings_controls.motion_enabled',return_value=True):
            for page,direction in (('models',1),('overview',-1),('projects',1),('overview',-1)):
                r.set_page(page);motion=r.page_fade
                self.assertTrue(motion.isVisible());self.assertTrue(r._page_motion_scope)
                self.assertEqual(motion.direction,direction)
                self.assertFalse(motion.geometry().intersects(tab_rect))
                if page in ('models','projects'):
                    scope=QRect(r.scope_row.mapTo(r.surface,QPoint()),r.scope_row.size())
                    self.assertTrue(motion.geometry().contains(scope))
                for ms in (0,65,130):
                    motion.animation.setCurrentTime(ms)
                    self.assertEqual(r.geometry(),bounds);self.assertEqual(r.surface.size(),size)
                self.finish()
    def test_target_matches_landed_pixels_and_warm_pages_reuse_widgets(self):
        r=self.r
        with patch('settings_controls.motion_enabled',return_value=True),patch.object(ReportPlot,'start_reveal'):
            for page in ('models','overview','projects','overview','models'):
                r.set_page(page);APP.processEvents();motion=r.page_fade
                expected=motion.next_frame.toImage();rect=motion.geometry()
                # The chart intentionally starts its own reveal after landing.
                # Hold that separate clock while comparing the page transaction.
                with patch.object(r.plot,'start_reveal') if r.plot else nullcontext():
                    self.finish();self.assertEqual(expected,r._capture_page(rect).toImage())
            cached=r.plot;r.set_page('overview');self.finish();r.set_page('models');self.finish()
            self.assertIs(r.plot,cached)
    def test_quick_reverse_uses_current_pixels_and_same_scope_pages_remain_body_only(self):
        r=self.r
        with patch('settings_controls.motion_enabled',return_value=True):
            r.set_page('projects');r.page_fade.animation.setCurrentTime(70)
            actual=r._capture_page(r._page_rect(True),include_cover=True).toImage()
            r.set_page('overview');self.assertEqual(r.page_fade.frame.toImage(),actual);self.finish()
            r.set_page('models');self.finish();r.set_page('projects')
            self.assertFalse(r._page_motion_scope);self.assertEqual(r.page_fade.geometry(),r.scroll.geometry())
            r.hide();self.assertFalse(r.page_fade.isVisible())
    def test_performance_mode_does_not_capture_a_scope_frame(self):
        with patch('settings_controls.motion_enabled',return_value=False),patch.object(self.r,'_capture_page',wraps=self.r._capture_page) as capture:
            self.r.set_page('models');self.assertFalse(self.r.page_fade.isVisible());capture.assert_not_called()
    def test_new_scope_does_not_autofocus_first_filter_before_capture(self):
        r=self.r;states=[];capture=r._capture_page
        def observe(*args,**kwargs):
            if r.page=='models':states.append(r.period_control.buttons['all'].hasFocus())
            return capture(*args,**kwargs)
        with patch.object(r,'_capture_page',side_effect=observe):r.set_page('models')
        self.assertTrue(states);self.assertFalse(any(states));self.finish()
        self.assertFalse(r.period_control.buttons['all'].hasFocus())

class LargeCardConsistencyTests(unittest.TestCase):
    def settle(self,b):
        for _ in range(4):b.size_transition.complete();APP.processEvents()
    def test_quota_or_token_reader_matches_editors_even_above_480_and_with_two_windows(self):
        from typography import install_ui_font
        install_ui_font(APP)
        for count in (1,2):
            for five in (False,True):
                b=CompactBubble();b.windows=([dict(name='5小时',remaining=45,resetsAt=time.time()+10000)] if five else [])+[dict(name='一周',remaining=40,resetsAt=time.time()+86400)]
                b.token_snapshot=dict(total=1000,all_total=6000000000)
                for index in range(count):b.roster.observe(dict(session=str(index),state='working',title='测试',display='运行命令'))
                b.show();b.toggle_details();self.settle(b)
                try:
                    for tab in (0,1):
                        b.details_tabs.setCurrentIndex(tab);self.settle(b);height=b.height()
                        if count==2 and tab==0:self.assertGreater(height,480)
                        for page in ('settings','chat'):
                            b.show_page(page,QWidget());self.settle(b);self.assertEqual(b.height(),height)
                            self.assertEqual(b.editor_stack.height(),height-94)
                        b.return_to_status();self.settle(b);self.assertEqual(b.height(),height)
                finally:b.close();b.deleteLater();APP.processEvents()
    def test_large_and_normal_quota_numbers_use_the_same_progress_color_for_every_theme(self):
        saved=current();custom=dict(theme_accent=palette()['accent'],theme_surface=palette()['surface'],theme_ink=palette()['ink'])
        try:
            for theme in NAMES:
                if theme=='custom':continue
                activate(theme)
                for remaining in (10,30,60,90):
                    for expanded in (False,True):
                        card=QuotaSummary([dict(name='一周',remaining=remaining)],expanded=expanded);card.setFixedWidth(160 if expanded else 121);card.show();APP.processEvents()
                        colors=[]
                        class Recorder(QPainter):
                            def drawText(self,*args):
                                if args and args[-1] in (str(remaining),str(remaining)+'%','%'):colors.append(self.pen().color().name())
                                return super().drawText(*args)
                        try:
                            card._static_key=None
                            with patch('quota_summary.QPainter',Recorder):card.grab()
                            self.assertTrue(colors);self.assertTrue(all(c==quota_color(card.items[0]).name() for c in colors),(theme,remaining,expanded,colors))
                        finally:card.close();card.deleteLater();APP.processEvents()
        finally:activate(saved,custom)

if __name__=='__main__':unittest.main()
