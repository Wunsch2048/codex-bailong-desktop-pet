import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time,unittest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtWidgets import QApplication,QLabel,QToolButton
from compact_bubble import CompactBubble,Announcement
from dashboard_cards import CardDeck
from quota_summary import QuotaSummary
from token_charts import TokenChartCard

app=QApplication.instance() or QApplication([])

def settle():
    app.processEvents()
    for window in app.topLevelWidgets():
        transition=getattr(window,'size_transition',None)
        if transition:transition.complete()
    app.processEvents()

class BubbleTests(unittest.TestCase):
    def test_pet_speech_temporarily_replaces_rows_then_restores_latest_session(self):
        b=self.bubble;b.show();settle()
        b.roster.observe(dict(session='a',state='working',title='任务A',display='正在编辑文件'))
        b.refresh_status();self.assertIn('正在编辑文件',b.status_view.text())
        b.message('测试点击台词',speech=True);self.assertEqual(b.status_view.text(),'测试点击台词')
        b.roster.observe(dict(session='a',state='working',title='任务A',display='正在运行命令'));b.refresh_status()
        self.assertEqual(b.status_view.text(),'测试点击台词')
        b.set_activity_text('等待 Codex 新消息');self.assertIn('正在运行命令',b.status_view.text())
    def test_speech_survives_redraw_and_does_not_acknowledge_completion(self):
        b=self.bubble;b.show();settle()
        b.roster.observe(dict(session='a',state='complete',title='任务A',text='完成'))
        b.status_indicator.notify_complete(dict(session='a',turn='done-1'))
        b.message('测试自动台词',speech=True);b.redraw()
        self.assertEqual(b.status_view.text(),'测试自动台词');self.assertEqual(len(b.status_indicator.unread),1)
        b.set_activity_text('完成');self.assertEqual(len(b.status_indicator.unread),1)
    def setUp(self):self.bubble=CompactBubble();self.bubble.status='正在检查代码';self.bubble.heading='Codex · 处理中'
    def tearDown(self):self.bubble.close();self.bubble.deleteLater();settle()
    def test_single_quota_uses_adjacent_default_token_chart(self):
        self.bubble.windows=[dict(name='一周',remaining=87,resetsAt=time.time()+86400)]
        self.bubble.reset_snapshot={'scheduled':None};self.bubble.redraw();settle()
        self.assertEqual(len([d for d in self.bubble.findChildren(QuotaSummary) if d.isVisible()]),1)
        self.assertEqual(len([d for d in self.bubble.findChildren(TokenChartCard) if d.isVisible()]),1)
        self.assertEqual((self.bubble.width(),self.bubble.height()),(268,186))
    def test_two_quotas_keep_exact_values_and_distinct_reset_times(self):
        now=time.time();self.bubble.windows=[dict(name='5小时',remaining=0,resetsAt=now+3600),dict(name='一周',remaining=100,resetsAt=None)]
        self.bubble.redraw();settle();cards=[d for d in self.bubble.findChildren(QuotaSummary) if d.isVisible()]
        self.assertEqual(len(cards),1);self.assertEqual([w['remaining'] for w in cards[0].items],[0,100]);self.assertIn('重置时间未知',cards[0].accessibleDescription())
        self.assertIn('北京时间',cards[0].accessibleDescription());self.assertEqual(self.bubble.height(),186)
    def test_expanded_view_preserves_full_message_and_stale_explanation(self):
        text='长状态消息，包含完整工作进度和执行结果。'*10
        self.bubble.status=text;self.bubble.quota_caption='接口暂不可用 · 下方为上次记录';self.bubble.reset_feed_error=True
        self.bubble.windows=[dict(name='一周',remaining=None,resetsAt=None)];self.bubble.redraw();small=self.bubble.height()
        self.bubble.toggle_details();settle()
        labels=[w.text() for w in self.bubble.findChildren(QLabel) if w.isVisible()]
        self.assertIn(text,labels);self.assertIn(self.bubble.quota_caption,labels)
        self.assertTrue(any('连接失败' in s or '暂不可用' in s for s in labels));self.assertGreater(self.bubble.height(),small)
    def test_unavailable_quota_is_not_rendered_as_zero(self):
        card=QuotaSummary([dict(name='5小时',remaining=None,resetsAt=None)]);self.assertIsNone(card.items[0]['remaining'])
        self.assertIn('暂不可用',card.accessibleDescription());self.assertNotIn('剩余额度：0%',card.accessibleDescription())
        card.deleteLater()
    def test_hide_quota_and_show_summary_keeps_popup_small(self):
        self.bubble.show_quota=False;self.bubble.redraw();self.assertLess(self.bubble.height(),80)
        self.assertFalse([d for d in self.bubble.findChildren(QuotaSummary) if d.isVisible()])
    def visible_button(self,name):
        return next(w for w in self.bubble.findChildren(QToolButton) if w.objectName()==name and w.isVisible())
    def test_refresh_buttons_and_shortcuts_keep_compact_footprint(self):
        events=[]
        self.bubble.windows=[dict(name='一周',remaining=80,resetsAt=None)];self.bubble.redraw();small=self.bubble.size()
        self.bubble.refreshAllRequested.connect(lambda:events.append('all'))
        self.bubble.codexRequested.connect(lambda:events.append('codex'))
        self.bubble.settingsRequested.connect(lambda:events.append('settings'))
        self.bubble.chatRequested.connect(lambda:events.append('chat'))
        self.bubble.optionRequested.connect(lambda key,value:events.append((key,value)))
        self.bubble.refresh_button.click();self.visible_button('open_codex').click()
        self.assertEqual(events,['all','codex']);self.assertEqual(self.bubble.size(),small)
        self.bubble.finish_refresh();self.visible_button('card_reset').click();self.bubble.refresh_button.click();self.assertEqual(events[-1],'all')
        self.bubble.finish_refresh()
        self.bubble.toggle_details();settle();self.visible_button('bubble_settings').click();self.visible_button('bubble_chat').click()
        self.visible_button('bubble_pin').click();self.visible_button('bubble_move').click()
        self.assertEqual(events[-4:],['settings','chat',('on_top',False),('wandering',False)])
        self.bubble.toggle_details();settle();self.assertEqual(self.bubble.size(),small)
    def test_busy_refresh_state_survives_status_redraw_and_recovers(self):
        events=[];self.bubble.windows=[dict(name='一周',remaining=80)];self.bubble.select_dashboard('reset')
        self.bubble.refreshAllRequested.connect(lambda:events.append('all'))
        self.bubble.set_refresh_busy(True);self.bubble.redraw()
        self.bubble.refresh_button.click();self.assertFalse(events)
        self.assertIn('正在刷新',self.bubble.refresh_button.toolTip())
        self.bubble.finish_refresh();self.bubble.refresh_button.click();self.assertEqual(events,['all'])
    def test_unified_refresh_keeps_busy_state_across_card_switches(self):
        events=[];self.bubble.refreshAllRequested.connect(lambda:events.append('all'))
        self.bubble.request_refresh_all();self.bubble.redraw();self.bubble.refresh_button.click();self.assertEqual(events,['all'])
        self.visible_button('card_reset').click();self.assertFalse(self.bubble.refresh_button.isEnabled())
        self.visible_button('card_tokens').click();self.assertFalse(self.bubble.refresh_button.isEnabled())
        self.bubble.finish_refresh();self.bubble.refresh_button.click();self.assertEqual(events,['all','all'])
    def test_local_reset_demotes_notice_once_and_preserves_manual_review(self):
        from reset_watch import schedule_key
        item=dict(id='notice',announced=100,scheduled=190,reset_type='regular')
        self.bubble.reset_snapshot={'pending':item};self.bubble.redraw();settle()
        self.assertEqual(self.bubble.dashboard_page,'reset')
        self.bubble.reset_snapshot=dict(self.bubble.reset_snapshot,local_reset={'schedule':schedule_key(item),'observed':200,'window':'一周','kind':'extra','scope':'account_only'})
        self.bubble.redraw();settle();self.assertEqual(self.bubble.dashboard_page,'tokens')
        self.visible_button('card_reset').click();settle();self.assertEqual(self.bubble.dashboard_page,'reset')
        self.bubble.redraw();settle();self.assertEqual(self.bubble.dashboard_page,'reset')

    def test_new_reset_has_priority_manual_switch_survives_updates_and_resolution_returns_calendar(self):
        self.assertEqual(self.bubble.dashboard_page,'tokens')
        item=dict(id='new',announced=time.time(),reset_type='regular',scheduled=time.time()+3600,text='待落实公告')
        self.bubble.reset_snapshot={'pending':item,'scheduled':item};self.bubble.redraw()
        self.assertEqual(self.bubble.dashboard_page,'reset')
        self.visible_button('card_tokens').click();self.assertEqual(self.bubble.dashboard_page,'tokens')
        self.bubble.message('刷新状态');self.bubble.set_reset_busy(True);self.bubble.redraw();self.assertEqual(self.bubble.dashboard_page,'tokens')
        item=dict(item,id='newer');self.bubble.reset_snapshot={'pending':item};self.bubble.redraw();self.assertEqual(self.bubble.dashboard_page,'reset')
        self.bubble.reset_snapshot={'pending':None,'scheduled':None};self.bubble.redraw();self.assertEqual(self.bubble.dashboard_page,'tokens')
    def test_five_hour_quota_precedes_weekly_regardless_of_input_order(self):
        card=QuotaSummary([dict(name='一周',remaining=87),dict(name='5小时',remaining=68)])
        self.assertEqual([w['name'] for w in card.items],['5小时','一周']);card.deleteLater()
    def test_chart_range_survives_redraw_refresh_and_card_switch(self):
        self.bubble.select_token_range('day');self.bubble.message('状态更新');self.bubble.redraw()
        self.visible_button('card_reset').click();self.visible_button('card_tokens').click()
        chart=next(d for d in self.bubble.findChildren(TokenChartCard) if d.isVisible())
        self.assertEqual(chart.period,'day');self.assertEqual(self.bubble.height(),186)
    def test_dense_reset_preserves_full_announcement_in_tooltip_and_expanded_details(self):
        text='这是完整公告，预计会陆续完成，不应在缩小卡片时丢失。'*4
        item=dict(id='dense',announced=time.time(),scheduled=None,reset_type='regular',text=text)
        self.bubble.reset_snapshot={'pending':item};self.bubble.redraw();settle()
        announcement=next(w for w in self.bubble.findChildren(Announcement) if w.isVisible())
        self.assertIn(text,announcement.toolTip());self.assertEqual(self.bubble.height(),186)
        self.bubble.toggle_details();settle();self.bubble.details_tabs.setCurrentIndex(2);settle()
        self.assertIn(text,[w.text() for w in self.bubble.findChildren(QLabel) if w.isVisible()])
    def test_all_shortcut_buttons_fit_inside_compact_bubble_on_both_cards(self):
        for page in ('tokens','reset'):
            self.bubble.select_dashboard(page);settle()
            for button in self.bubble.findChildren(QToolButton):
                if not button.isVisible():continue
                point=button.mapTo(self.bubble,QPoint(0,0))
                self.assertGreaterEqual(point.x(),0);self.assertGreaterEqual(point.y(),0)
                self.assertLessEqual(point.x()+button.width(),self.bubble.width());self.assertLessEqual(point.y()+button.height(),self.bubble.height())
            self.assertEqual(self.bubble.height(),186)

if __name__=='__main__':unittest.main()
