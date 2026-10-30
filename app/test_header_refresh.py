"""Native-widget acceptance for compact headings and one refresh per surface."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,copy,time
from PySide6.QtCore import Qt,QPoint,QRect,QEvent,QAbstractAnimation
from PySide6.QtWidgets import QApplication,QToolButton,QWidget,QToolTip
from PySide6.QtTest import QTest
from compact_bubble import CompactBubble
from daily_report import DailyReport
from refresh_indicator import RefreshButton

APP=QApplication.instance() or QApplication([])

def settle(bubble):
    APP.processEvents();bubble.size_transition.complete();APP.processEvents()

class HeaderRefreshTests(unittest.TestCase):
    def setUp(self):
        self.bubble=CompactBubble();self.bubble.move(400,700);settle(self.bubble)
    def tearDown(self):
        self.bubble.close();self.bubble.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
    def test_header_hover_works_without_activating_the_card(self):
        b=self.bubble;b.show();settle(b)
        other=QWidget();other.move(800,40);other.show();APP.setActiveWindow(other);APP.processEvents()
        try:
            self.assertFalse(b.isActiveWindow())
            button=b._header_actions[1]
            QTest.mouseMove(button,QPoint(5,5))
            deadline=time.monotonic()+2
            popup=b.inline_explanations.popup
            while not popup.isVisible() and time.monotonic()<deadline:QTest.qWait(20)
            self.assertTrue(popup.isVisible())
            self.assertEqual(popup.title,'数据')
            self.assertFalse(QToolTip.isVisible())
            self.assertFalse(b.isActiveWindow())
        finally:
            b.inline_explanations.dismiss(True);other.close();other.deleteLater();APP.processEvents()
    def event(self,state='working',session='a',**extra):
        data=dict(session=session,state=state,active=1,display='正在编辑文件',**extra)
        self.bubble.roster.observe(data);self.bubble.status_indicator.observe(data)
        self.bubble.refresh_status();settle(self.bubble)
    def bounds(self,widget):return QRect(widget.mapTo(self.bubble,QPoint()),widget.size())
    def assert_header_fits(self):
        b=self.bubble;targets=b._header_actions;name=b._status_title.parentWidget()
        for target in targets:
            self.assertEqual((target.width(),target.height()),(26,26))
            self.assertEqual(target.text(),'');self.assertTrue(target.accessibleName())
            self.assertTrue(b.rect().contains(self.bounds(target)))
            self.assertFalse(self.bounds(name).intersects(self.bounds(target)))
        for i,target in enumerate(targets):
            for other in targets[i+1:]:self.assertFalse(self.bounds(target).intersects(self.bounds(other)))
        self.assertEqual(b._status_title.height(),26)
    def test_common_headings_fit_on_first_paint_and_live_updates(self):
        b=self.bubble
        for expanded in (False,True):
            b.expanded=expanded
            for state,reason,expected in [('working','','Codex'),('waiting','approval','待你确认'),('waiting','input','待你输入'),('waiting','','待你操作'),('interrupted','','已中断')]:
                b.roster.items.clear();b.status_indicator.unread=[]
                event=dict(session='a',state=state,active=0 if state=='interrupted' else 1,waiting_reason=reason)
                b.roster.observe(event);b.status_indicator.observe(event);b.redraw();settle(b)
                initial=(b._status_title.text(),self.bounds(b._status_title),self.bounds(b._status_title.parentWidget()))
                self.assertEqual(initial[0],expected);self.assert_header_fits()
                b.refresh_status();settle(b)
                self.assertEqual(initial,(b._status_title.text(),self.bounds(b._status_title),self.bounds(b._status_title.parentWidget())))
                self.assert_header_fits()
    def test_multiple_running_sessions_use_count_badge_and_unread_replaces_codex(self):
        self.event(session='a');self.event(session='b')
        b=self.bubble
        self.assertEqual(b._status_title.text(),'Codex');self.assertEqual(b._status_badge.text(),'2')
        self.assertTrue(b._status_badge.isVisible());self.assert_header_fits()
        b.status_indicator.unread=[('done-a','t'),('done-b','t')];b.refresh_status();settle(b)
        self.assertEqual(b._status_title.text(),'2条待查看');self.assertFalse(b._status_badge.isVisible());self.assert_header_fits()
    def test_each_dashboard_page_has_one_refresh_and_click_does_not_rebuild_chart(self):
        b=self.bubble;calls=[];b.refreshAllRequested.connect(lambda:calls.append('all'))
        for expanded in (False,True):
            b.expanded=expanded;b.redraw();settle(b)
            for page in ('tokens','reset'):
                b.select_dashboard(page);settle(b)
                visible=[w for w in b.findChildren(RefreshButton) if w.isVisible()]
                self.assertEqual(visible,[b.refresh_button])
                deck=b.deck;content=deck.content
                b.refresh_button.click();b.refresh_button.click()
                self.assertTrue(b.refresh_busy);self.assertFalse(b.refresh_button.isEnabled())
                self.assertIs(b.deck,deck);self.assertIs(b.deck.content,content)
                b.finish_refresh();self.assertFalse(b.refresh_busy)
        self.assertEqual(calls,['all']*4)
    def test_refresh_widget_survives_status_mode_changes_and_background_flags(self):
        b=self.bubble;button=b.refresh_button;b.request_refresh_all()
        b.set_token_busy(True);b.set_quota_busy(True);b.redraw();settle(b)
        self.assertIs(button,b.refresh_button);self.assertFalse(button.isEnabled())
        b.set_token_busy(False);b.set_quota_busy(False);self.assertFalse(button.isEnabled())
        b.expanded=True;b.redraw();settle(b);self.assertIs(button,b.refresh_button)
        b.finish_refresh(False);self.assertTrue(button.isEnabled())
        b.set_mode('mini');settle(b);self.assertFalse(button.isVisible())
        b.set_mode('auto');settle(b);self.assertIs(button,b.refresh_button);self.assertTrue(button.isVisible())
    def test_background_poll_does_not_replace_manual_refresh_feedback(self):
        b=self.bubble;b.request_refresh_all()
        b.set_token_busy(True);b.set_token_busy(False)
        self.assertTrue(b.refresh_busy);self.assertFalse(b.refresh_button.isEnabled())
        b.finish_refresh();self.assertFalse(b.refresh_busy);self.assertTrue(b.refresh_button.isEnabled())
    def test_data_arrival_keeps_chart_progress_and_quota_current_value(self):
        from test_daily_report import sample
        from quota_summary import QuotaSummary
        b=self.bubble;b.token_snapshot=sample()
        b.windows=[dict(name='一周',remaining=73,resetsAt=time.time()+86400)];b.redraw();settle(b)
        plot=b.deck.content.plot;quota=next(w for w in b.findChildren(QuotaSummary) if w.isVisible())
        quota.animation.setCurrentTime(quota.animation.duration());cached=dict(quota.values)
        self.assertEqual(plot.reveal.progress,1.)
        b.request_refresh_all();button=b.refresh_button
        b.token_snapshot=copy.deepcopy(b.token_snapshot);b.token_snapshot['total']=300
        b.quota([dict(name='一周',remaining=68,resetsAt=time.time()+86400)]);settle(b)
        self.assertEqual(b.deck.content.plot.reveal.progress,1.)
        fresh=next(w for w in b.findChildren(QuotaSummary) if w.isVisible())
        self.assertEqual(fresh.starts,cached);self.assertTrue(all(v>0 for v in fresh.values.values()))
        self.assertIs(button,b.refresh_button);self.assertTrue(button.busy)
        plot=b.deck.content.plot;plot.begin_reveal();plot.start_reveal();plot.reveal.animation.setCurrentTime(220)
        progress=plot.reveal.progress;b.redraw();settle(b)
        self.assertGreaterEqual(b.deck.content.plot.reveal.progress,progress)
        self.assertEqual(b.deck.content.plot.reveal.animation.state(),QAbstractAnimation.State.Running)
        b.finish_refresh()
    def test_daily_report_has_one_icon_refresh_persistent_across_pages(self):
        b=self.bubble;r=DailyReport(b);b.report=r;r.requested=True;r.show();r.surface.show();APP.processEvents()
        calls=[];r.refreshRequested.connect(lambda:calls.append('report'));button=r.refresh_button
        self.assertEqual(button.text(),'');self.assertEqual((button.width(),button.height()),(28,28))
        button.click();button.click();self.assertEqual(calls,['report']);self.assertTrue(r.refresh_busy)
        r.set_page('models');APP.processEvents();self.assertIs(r.refresh_button,button)
        self.assertFalse(button.isEnabled())
        r.finish_refresh();self.assertTrue(button.isEnabled())
        visible=[w for w in r.findChildren(RefreshButton) if w.isVisible()]
        self.assertEqual(visible,[button])
    def test_waiting_reason_is_not_carried_after_resume(self):
        self.event('waiting',waiting_reason='approval')
        self.assertEqual(self.bubble._status_title.text(),'待你确认')
        self.event('working')
        self.assertEqual(self.bubble._status_title.text(),'Codex')
        self.assertEqual(self.bubble.roster.items['a']['waiting_reason'],'')

if __name__=='__main__':unittest.main()
