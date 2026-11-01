"""Contracts for the large-card redesign; synthetic data and no disk writes."""
import os,time,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication,QToolButton,QWidget
from compact_bubble import CompactBubble

APP=QApplication.instance() or QApplication([])

def settle(b):
    b.size_transition.complete()
    for _ in range(4):APP.processEvents()

class LargeCardTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.windows=[dict(name='一周',remaining=39,resetsAt=time.time()+86400)]
        for sid in ('a','b'):
            self.b.roster.observe(dict(session=sid,title='任务'+sid,state='working',display='正在检查界面'))
        self.b.redraw();self.b.show();settle(self.b)
    def tearDown(self):
        self.b.close();self.b.deleteLater();APP.processEvents()
    def test_shared_modules_restore_normal_size_and_identity(self):
        b=self.b;size=b.size();live=b.live_rate_card
        b.toggle_details();settle(b)
        self.assertEqual(b.width(),360);self.assertLessEqual(b.height(),b.expanded_height());self.assertGreater(b.height(),350)
        self.assertEqual(b.status_view.rows['a'].height(),43)
        self.assertIs(live,b.live_rate_card)
        self.assertEqual(len(b._header_actions),3)
        b.toggle_details();settle(b)
        self.assertEqual(b.size(),size);self.assertEqual(len(b._header_actions),4)
        self.assertEqual(b.status_view.rows['a'].height(),b.status_view.line_height)
        self.assertIs(live,b.live_rate_card)
    def test_task_count_change_moves_shared_modules_in_one_transition(self):
        b=self.b;b.toggle_details();settle(b);old=b.height()
        b.roster.items.pop('b');b.refresh_status()
        self.assertTrue(b.size_transition.running)
        self.assertTrue(b.size_transition.morph.shared_parts)
        self.assertIn('navigation',b.size_transition.morph.shared_parts)
        self.assertIn('task_caption',b.size_transition.morph.shared_parts)
        target=b.size_transition.target_rect.height();self.assertLess(target,old)
        b.size_transition.animation.setCurrentTime(100)
        self.assertTrue(b.size_transition.running)
        settle(b);self.assertEqual(b.height(),target)
    def test_token_baseline_and_long_reset_only_grow_as_needed(self):
        b=self.b;b.toggle_details();settle(b);base=b.height();tabs=b.details_tabs
        tabs.setCurrentIndex(1);settle(b);self.assertEqual(b.height(),base)
        tabs.setCurrentIndex(2);settle(b);self.assertGreaterEqual(b.height(),base)
        from detail_sections import detail_label
        area=tabs.areas['reset'];area.widget().layout().insertWidget(1,detail_label('公告详细内容。'*120))
        tabs.setCurrentIndex(0);settle(b);tabs.setCurrentIndex(2)
        self.assertTrue(b.size_transition.running);settle(b)
        self.assertGreater(b.height(),base);self.assertLessEqual(b.height(),b.screen().availableGeometry().height()-24)
        tabs.setCurrentIndex(1);settle(b);self.assertEqual(b.height(),base)
    def test_long_status_does_not_change_fixed_editor_height(self):
        from detail_sections import detail_label
        b=self.b;b.toggle_details();settle(b);baseline=b.height();tabs=b.details_tabs
        b.reset_snapshot={'pending':dict(id='long',scheduled=None,reset_type='regular',text='长公告内容。'*180)}
        b.redraw();settle(b);tabs=b.details_tabs
        tabs.setCurrentIndex(2);settle(b);long_height=b.height();self.assertGreater(long_height,baseline)
        for page in ('chat','settings','chat'):
            b.show_page(page,QWidget());self.assertTrue(b.size_transition.running);settle(b)
            self.assertEqual(b.height(),480);self.assertEqual(b.editor_stack.height(),386)
        b.return_to_status();settle(b);self.assertEqual(b.height(),long_height)
        b.details_tabs.setCurrentIndex(1);self.assertTrue(b.size_transition.running);settle(b)
        self.assertEqual(b.height(),baseline)
        b.show_page('settings',QWidget());settle(b);self.assertEqual(b.height(),480)
    def test_equal_height_help_navigation_has_a_valid_direction(self):
        b=self.b;b.toggle_details();settle(b)
        b.content.setFixedHeight(480);b.setFixedSize(360,480)
        b.show_explanations();settle(b);self.assertEqual(b.panel_page,'help');self.assertEqual(b.height(),480)
        b.return_to_status();settle(b);self.assertEqual(b.panel_page,'status')
    def test_equal_height_quota_tabs_slide_only_the_detail_reader(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QRect
        b=self.b;b.toggle_details();settle(b);tabs=b.details_tabs;bar=tabs.tabBar()
        baseline=b.height()
        for index in (1,0,1):
            QTest.mouseClick(bar,Qt.MouseButton.LeftButton,pos=bar.tabRect(index).center())
            transition=b.size_transition
            self.assertTrue(transition.running);self.assertTrue(transition.same_size_fade)
            viewport=tabs.currentWidget().viewport()
            expected=QRect(viewport.mapTo(b,QPoint()),viewport.size())
            self.assertEqual(transition.cover.geometry(),expected)
            self.assertGreater(transition.cover.y(),tabs.mapTo(b,QPoint()).y()+bar.height())
            for ms in (20,60,100):
                transition.animation.setCurrentTime(ms)
                self.assertEqual(b.height(),baseline)
                self.assertFalse(transition.cover.geometry().intersects(QRect(b.quota_summary_card.mapTo(b,QPoint()),b.quota_summary_card.size())))
            settle(b);self.assertEqual(b.height(),baseline)
    def test_native_tab_click_grows_and_returns_to_token_baseline(self):
        from PySide6.QtTest import QTest
        b=self.b;b.reset_snapshot={'pending':dict(id='long',scheduled=None,reset_type='regular',text='公告正文会根据当前宽度自动换行。'*120)}
        b.toggle_details();settle(b);tabs=b.details_tabs;bar=tabs.tabBar()
        def click(index):
            QTest.mouseClick(bar,Qt.MouseButton.LeftButton,pos=bar.tabRect(index).center())
        click(1);settle(b);baseline=b.height()
        from unittest.mock import patch
        b.select_dashboard('tokens');settle(b)
        plot=b.deck.content.plot
        with patch.object(plot,'begin_reveal',wraps=plot.begin_reveal) as reveal:
            click(2);self.assertTrue(b.size_transition.running);reveal.assert_not_called()
        self.assertEqual(b.size_transition.morph.shared_parts['details'].detail_direction,1)
        self.assertEqual(b.detail_tab,'reset');self.assertGreater(b.size_transition.target_rect.height(),baseline)
        settle(b);long_height=b.height()
        click(1);self.assertTrue(b.size_transition.running)
        self.assertLess(b.size_transition.target_rect.height(),long_height)
        settle(b);self.assertEqual(b.height(),baseline)
    def test_cpp_and_keyboard_switches_measure_current_notice_not_old_height(self):
        from PySide6.QtWidgets import QTabWidget,QLabel
        from PySide6.QtTest import QTest
        b=self.b;b.reset_snapshot={'pending':dict(id='long',scheduled=None,reset_type='regular',text='长公告自动适配。'*150)}
        b.toggle_details();settle(b);tabs=b.details_tabs
        QTabWidget.setCurrentIndex(tabs,1);settle(b);baseline=b.height()
        QTabWidget.setCurrentIndex(tabs,2);self.assertTrue(b.size_transition.running);settle(b)
        first=b.height();self.assertGreater(first,baseline)
        QTest.keyClick(tabs.tabBar(),Qt.Key.Key_Left);self.assertTrue(b.size_transition.running);settle(b)
        self.assertEqual(tabs.currentIndex(),1);self.assertEqual(b.height(),baseline)
        notice=next(w for w in tabs.areas['reset'].findChildren(QLabel) if w.text().startswith('长公告'))
        notice.setText('短公告。')
        QTabWidget.setCurrentIndex(tabs,2);settle(b)
        self.assertGreaterEqual(b.height(),baseline);self.assertLess(b.height(),first)
        # Give Token details an extra real line so the entire short notice
        # (including heading/source) is genuinely below that page's floor.
        from detail_sections import detail_label
        tabs.areas['tokens'].widget().layout().insertWidget(1,detail_label('补充的 Token 统计信息。'*16))
        QTabWidget.setCurrentIndex(tabs,1);settle(b);baseline=b.height()
        QTabWidget.setCurrentIndex(tabs,2);settle(b);self.assertEqual(b.height(),baseline)
        notice.setText('这是另一份更长的公告。'*180)
        QTabWidget.setCurrentIndex(tabs,1);settle(b)
        QTabWidget.setCurrentIndex(tabs,2);self.assertTrue(b.size_transition.running);settle(b)
        self.assertGreater(b.height(),baseline)
    def test_large_navigation_actions_use_shared_header_hints(self):
        b=self.b;b.toggle_details();settle(b)
        names={w.accessibleName():w.property('headerActionHint') for w in b.findChildren(QToolButton) if w.accessibleName() in ('置顶','移动')}
        self.assertEqual(names,{'置顶':'置顶','移动':'移动'})
    def test_range_menu_keeps_every_period_and_today_shortcut_in_sync(self):
        b=self.b;b.toggle_details();settle(b)
        menu=b.deck.range_menu
        self.assertEqual({menu.itemData(i) for i in range(menu.count())},{'all','30d','7d','day'})
        menu.setCurrentIndex(menu.findData('7d'));settle(b)
        self.assertEqual(b.token_range,'7d');self.assertEqual(b.deck.content.plot.period,'7d')
        b.show_today_tokens();self.assertEqual(menu.currentData(),'day')
    def test_explanation_is_accessible_without_a_fourth_text_tab(self):
        b=self.b;b.toggle_details();settle(b)
        tabs=b.details_tabs;help_button=tabs.findChild(QToolButton,'detail_help')
        self.assertFalse(tabs.tabBar().isTabVisible(3))
        help_button.click();settle(b)
        self.assertEqual(b.panel_page,'help');self.assertTrue(b._explanation_page.isVisible())
        b.return_to_status();settle(b);self.assertEqual(b.panel_page,'status');self.assertEqual(b.details_tabs.currentIndex(),0)
    def test_small_screen_scroll_keeps_background_refresh_but_resets_new_visit(self):
        b=self.b;b.expanded_height=lambda:320;b.toggle_details();settle(b)
        self.assertEqual(b.height(),320)
        area=b._status_scroll;bar=area.verticalScrollBar()
        self.assertGreater(bar.maximum(),0)
        self.assertEqual(area.verticalScrollBarPolicy(),Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bar.setValue(bar.maximum());value=bar.value()
        b.redraw();settle(b);self.assertEqual(b._status_scroll.verticalScrollBar().value(),value)
        b.toggle_details();settle(b);b.toggle_details();settle(b)
        self.assertEqual(b._status_scroll.verticalScrollBar().value(),0)
    def test_expanded_rows_have_disjoint_title_detail_and_state(self):
        b=self.b;b.toggle_details();settle(b)
        row=b.status_view.rows['a'];regions=row.transition_regions()
        self.assertFalse(regions['title'].intersects(regions['detail']))
        self.assertFalse(regions['title'].intersects(regions['badge']))
        self.assertEqual(row.conversation_id,'a')
    def test_shared_footer_and_details_do_not_leak_into_editor(self):
        b=self.b;b.toggle_details();settle(b)
        live=b.live_rate_card;details=b.details_tabs
        b.show_page('chat',QWidget());settle(b)
        self.assertFalse(live.isVisible());self.assertFalse(details.isVisible())
        b.return_to_status();settle(b)
        self.assertTrue(b.live_rate_card.isVisible());self.assertTrue(b.details_tabs.isVisible())
    def test_detail_boundary_passes_wheel_to_small_screen_outer_reader(self):
        b=self.b;b.expanded_height=lambda:320;b.toggle_details();settle(b)
        outer=b._status_scroll.verticalScrollBar();inner=b.details_tabs.areas['quota']
        inner.verticalScrollBar().setValue(inner.verticalScrollBar().maximum())
        self.assertEqual(outer.value(),0)
        e=QWheelEvent(QPointF(5,5),QPointF(5,5),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        APP.sendEvent(inner.viewport(),e)
        self.assertGreater(outer.value(),0)

if __name__=='__main__':unittest.main()
