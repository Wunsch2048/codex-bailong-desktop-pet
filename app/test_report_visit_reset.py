"""A new panel visit resets model UI; cached data and in-visit reading survive."""
import os,copy,weakref,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from PySide6.QtCore import QEvent,QAbstractAnimation
from PySide6.QtTest import QTest
import test_daily_report as fixture
from compact_bubble import CompactBubble
APP=fixture.APP

class ModelVisitTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ReportUiTests();self.f.setUp();self.r=self.f.r
        data=fixture.sample()
        data['report']['daily_models'] += [dict(day='2026-10-17',model='demo-'+str(i),total=1000+i,input=800,output=200,known=True) for i in range(24)]
        self.r.set_snapshot(data);self.r.open();self.f.complete();self.r.set_page('models');self.finish_page()
    def tearDown(self):self.f.tearDown()
    def finish_page(self):
        self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration());APP.processEvents()
    def choose_and_scroll(self):
        self.r.set_period('7d');self.r.select_model('demo-3');APP.processEvents()
        self.r.scroll.verticalScrollBar().setValue(self.r.scroll.verticalScrollBar().maximum())
        self.assertGreater(self.r.scroll.verticalScrollBar().value(),0)
    def test_full_exit_resets_selection_period_scroll_and_smooth_target_while_reusing_data(self):
        r=self.r;plot=r.plot;self.choose_and_scroll();area=r.scroll
        area._smooth_scroll.target=area.verticalScrollBar().maximum()
        r.dismiss();self.f.complete();self.assertFalse(r.isVisible())
        with patch('daily_report.model_series',wraps=fixture.model_series) as series:
            r.open();self.f.complete();r.set_page('models');self.finish_page();series.assert_not_called()
        self.assertIs(r.plot,plot);self.assertEqual(r.period,'all');self.assertIsNone(r.selected_model)
        self.assertEqual(area.verticalScrollBar().value(),0);self.assertEqual(area._smooth_scroll.target,0)
        self.assertEqual(area._smooth_scroll.animation.state(),QAbstractAnimation.State.Stopped)
        self.assertFalse(r.clear_filter.isVisible());self.assertFalse(any(row.isChecked() for row in r.model_rows))
    def test_direct_model_reopen_resets_too(self):
        self.choose_and_scroll();self.r.dismiss();self.f.complete();self.r.open(page='models');self.f.complete()
        self.assertEqual(self.r.page,'models');self.assertEqual(self.r.period,'all');self.assertIsNone(self.r.selected_model)
        self.assertEqual(self.r.scroll.verticalScrollBar().value(),0)
    def test_in_visit_page_return_and_background_refresh_do_not_reset(self):
        self.choose_and_scroll();r=self.r;position=r.scroll.verticalScrollBar().value()
        r.set_page('overview');self.finish_page();r.set_page('models');self.finish_page()
        self.assertEqual((r.period,r.selected_model),('7d','demo-3'));self.assertEqual(r.scroll.verticalScrollBar().value(),position)
        data=copy.deepcopy(r.snapshot);data['report']['all_total']+=1000;r.set_snapshot(data);APP.processEvents()
        self.assertEqual((r.period,r.selected_model),('7d','demo-3'));self.assertEqual(r.scroll.verticalScrollBar().value(),position)
    def test_cancelled_close_is_same_visit_and_yesterday_cost_entry_keeps_scope(self):
        self.choose_and_scroll();r=self.r;r.dismiss();r.animation.setCurrentTime(80)
        r.open(page='models');self.f.complete();self.assertEqual((r.period,r.selected_model),('7d','demo-3'))
        r.set_page('overview');self.finish_page();r.open_yesterday_cost();self.finish_page()
        self.assertEqual((r.page,r.period),('projects','yesterday'))

class ExplanationEntryTests(unittest.TestCase):
    def settle(self,b):
        for _ in range(4):b.size_transition.complete();APP.processEvents()
    def test_common_hover_non_toggle_and_fixed_entry_height_including_long_notice(self):
        b=CompactBubble();b.reset_snapshot={'pending':dict(id='long',scheduled=None,reset_type='regular',text='需要说明的公告。'*180)}
        b.show();b.toggle_details();self.settle(b)
        try:
            for tab in (0,1,2):
                b.details_tabs.setCurrentIndex(tab);self.settle(b);height=b.height();button=b.details_tabs.help_button
                self.assertEqual(button.property('headerActionHint'),'使用说明');self.assertFalse(button.isCheckable())
                hints=b.inline_explanations;APP.sendEvent(button,QEvent(QEvent.Type.Enter));self.assertTrue(hints.delay.isActive())
                hints.target=weakref.ref(button);hints._show();self.assertTrue(hints.popup.isVisible());hints.dismiss(True)
                button.click();self.settle(b);self.assertEqual(b.panel_page,'help');self.assertEqual(b.height(),height)
                self.assertFalse(button.isChecked());self.assertEqual(b.editor_stack.height(),height-94)
                b.return_to_status();self.settle(b);self.assertEqual(b.height(),height);self.assertFalse(b.details_tabs.help_button.isChecked())
        finally:b.close();b.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
