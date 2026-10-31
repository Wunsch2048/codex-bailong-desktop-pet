"""Linux 新版界面适配只改变平台接入，保留上游布局与绘制"""
from contextlib import ExitStack
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch
import unittest

from PySide6.QtCore import QEvent, QPoint, QRect, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QGraphicsOpacityEffect, QMenu
from compact_bubble import CompactBubble
from daily_report import DailyReport
from desktop_settings import SettingsDialog
from hover_hints import HintBubble, TrayHints
from linux_app import surfaces, ui
from test_settings_controls import PetStub

APP = QApplication.instance() or QApplication([])


class LinuxUiTests(unittest.TestCase):
    """覆盖 niri 原点转换、StatusNotifier 文本及本机来源约束"""
    def tearDown(self):
        """释放测试窗口，不接触日常桌宠和配置"""
        for widget in APP.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_hint_uses_card_origin_even_when_owned_by_report(self):
        """日报可能有不同的 Qt 虚拟原点，顶栏锚点仍须使用卡片原点"""
        bubble = CompactBubble()
        bubble.move(20, 30)
        report = DailyReport(bubble)
        report.move(100, 200)
        controller = QObject()
        controller.pet = SimpleNamespace(bubble=bubble, closing=False, isVisible=lambda: False)
        manager = surfaces.Surfaces(controller)
        manager.bind(bubble)
        manager.bind(report)
        manager.entries[bubble]['point'] = QPoint(280, 390)
        manager.entries[report]['point'] = QPoint(280, 80)
        popup = HintBubble()
        virtual = QWidget.mapToGlobal(bubble, QPoint())
        anchor = QRect(virtual + QPoint(45, 10), bubble._header_actions[0].size())
        with ExitStack() as stack:
            original = HintBubble.present
            observed = stack.enter_context(patch.object(HintBubble, 'present', wraps=original))
            surfaces.install(stack)
            popup.present('数据', '', anchor, bubble.screen(), card_top=virtual.y(), owner=report)
            values = observed.call_args
            self.assertEqual(values.args[3].topLeft(), QPoint(325, 400))
            self.assertEqual(values.kwargs['card_top'], 390)
            self.assertEqual(popup.windowType(), Qt.WindowType.ToolTip)
            self.assertIs(popup.windowHandle().transientParent(), report.windowHandle())
            self.assertIn(popup, manager.entries)
            self.assertEqual(popup.windowHandle().mask().boundingRect(), QRect(-1, -1, 1, 1))
            self.assertEqual(popup.geometry().topLeft(), manager.entries[popup]['point'])
            self.assertLessEqual(abs(popup.geometry().bottom() - bubble.y()), 2)
            self.assertEqual(bubble.pos(), QPoint(280, 390))
            local = QWidget.mapToGlobal(report, QPoint()) + popup.pos() - report.pos()
            self.assertEqual(QWidget.pos(popup), local)
            popup.present('刷新', '', anchor, bubble.screen(), card_top=virtual.y(), owner=bubble)
            self.assertIs(popup.windowHandle().transientParent(), bubble.windowHandle())
            self.assertIs(popup._linux_popup_parent, bubble)
            self.assertEqual(QWidget.pos(popup), QWidget.mapToGlobal(bubble, QPoint()) + popup.pos() - bubble.pos())
        manager.timer.stop()

    def test_adjacent_hints_reposition_the_same_popup_without_hover_delay(self):
        """首次悬停仍等待，已显示的提示在按钮间直接改内容与原生位置"""
        bubble = CompactBubble()
        bubble.show()
        APP.processEvents()
        controller = QObject()
        controller.pet = SimpleNamespace(bubble=bubble, closing=False)
        controller.windows = {}
        controller.action = Mock()
        manager = surfaces.Surfaces(controller)
        manager.bind(bubble)
        manager.entries[bubble]['point'] = QPoint(280, 390)
        hints = bubble.inline_explanations
        with ExitStack() as stack:
            surfaces.install(stack)
            hints.eventFilter(bubble._header_actions[0], QEvent(QEvent.Type.Enter))
            self.assertTrue(hints.delay.isActive())
            self.assertFalse(hints.popup.isVisible())
            hints.delay.stop()
            hints._show()
            popup = hints.popup
            popup.animation.setCurrentTime(popup.animation.duration())
            handle = popup.windowHandle()
            for index, title in ((1, '数据'), (2, '收起'), (3, '详情'), (0, '刷新')):
                previous = QWidget.pos(popup)
                hints.eventFilter(bubble._header_actions[index], QEvent(QEvent.Type.Enter))
                self.assertEqual(popup.title, title)
                self.assertFalse(hints.delay.isActive())
                self.assertEqual(popup.level, 1.)
                self.assertIs(popup.windowHandle(), handle)
                self.assertNotEqual(QWidget.pos(popup), previous)
                self.assertEqual(QWidget.pos(popup), QWidget.mapToGlobal(bubble, QPoint()) + popup.pos() - bubble.pos())
                self.assertEqual(popup.windowType(), Qt.WindowType.ToolTip)
                manager.sync()
            controller.action.assert_not_called()
            self.assertFalse(bubble.content.testAttribute(Qt.WidgetAttribute.WA_NativeWindow))
            hints.dismiss(True)
            self.assertFalse(hints.watch.isActive())
            self.assertFalse(popup.isVisible())
            from live_rate_ui import SessionRateBubble
            inspector = SessionRateBubble()
            inspector.present('速率', '', QRect(bubble.pos(), bubble.size()), bubble.screen(), owner=bubble)
            self.assertEqual(inspector.windowType(), Qt.WindowType.Tool)
            self.assertIsNone(getattr(inspector, '_linux_popup_parent', None))
            inspector.close()
        manager.timer.stop()

    def test_tray_text_and_settings_are_scoped_to_linux(self):
        """原提示生成和设置草稿保留，适配退出后原方法恢复"""
        original = SettingsDialog.build_page_2
        with ExitStack() as stack:
            stack.enter_context(patch('desktop_settings.autostart_enabled', return_value=False))
            stack.enter_context(patch('codex_startup.enabled', return_value=False))
            ui.install(stack)
            pet = PetStub()
            dialog = SettingsDialog(pet, embedded=True)
            self.assertEqual(dialog.path_source.currentData(), 'windows')
            self.assertEqual(dialog.path_source.buttons['windows'].text(), 'Linux 本机')
            self.assertFalse(dialog.path_source.buttons['wsl'].isEnabled())
            self.assertTrue(dialog.fields['codex_exit'].isEnabled())
            self.assertIn('图形桌面', dialog.startup.text())
            self.assertNotIn('Windows', dialog.codex_startup.text())
            tray = QSystemTrayIcon(pet)
            hints = TrayHints(tray, pet)
            hints.set_text('周额度 86%', '下次重置 10/30 18:00')
            self.assertEqual(tray.toolTip(), '周额度 86%\n下次重置 10/30 18:00')
            self.assertFalse(hints.watch.isActive())
            hints.close()
        self.assertIs(SettingsDialog.build_page_2, original)

    def test_tray_refresh_keeps_actions_and_updates_original_state(self):
        """桌面缓存的动作不能失效，状态和命令继续来自共享菜单实现"""
        from PySide6.QtGui import QAction
        from desktop import DesktopPet
        pet = QWidget()
        pet.settings = dict(character_visible=True, bubble=True, panel_detached=False, no_move=False, wandering=True)
        pet._desktop_hidden = False
        pet.bubble = SimpleNamespace(bubble_mode='mini')
        pet.tray_menu = QMenu(pet)
        pet.build_menu = MethodType(DesktopPet.build_menu, pet)
        pet.menu_command = MethodType(DesktopPet.menu_command, pet)
        pet.execute_command = Mock()
        with ExitStack() as stack:
            ui.install(stack)
            DesktopPet.populate_tray(pet)
            self.assertEqual(len(pet.tray_menu.actions()), 7)
            actions = {a.objectName(): a for a in pet.tray_menu.findChildren(QAction) if a.objectName()}
            pet._desktop_hidden = True
            pet.settings['character_visible'] = False
            pet.bubble.bubble_mode = 'auto'
            for _ in range(3):
                DesktopPet.populate_tray(pet)
                current = {a.objectName(): a for a in pet.tray_menu.findChildren(QAction) if a.objectName()}
                self.assertEqual(current, actions)
            self.assertEqual(actions['command_visible'].text(), '显示桌面组件')
            self.assertFalse(actions['command_character'].isChecked())
            self.assertTrue(actions['command_mode_auto'].isChecked())
            self.assertFalse(actions['command_mode_mini'].isChecked())
            actions['command_settings'].trigger()
            APP.processEvents()
            pet.execute_command.assert_called_once_with('settings', False)


    def test_transition_has_one_visible_renderer_and_unmaps_idle_helper(self):
        """准备期原窗不动，动画期仅临时画布可见，结束后没有额外窗口"""
        bubble = CompactBubble()
        bubble.move(100, 300)
        bubble.show()
        APP.processEvents()
        controller = QObject()
        controller.pet = SimpleNamespace(bubble=bubble, closing=False, isVisible=lambda: False)
        controller.windows = {}
        controller.reveal = QTimer(controller)
        controller.opacity = QGraphicsOpacityEffect(bubble)
        controller.opacity.setOpacity(1)
        bubble.setGraphicsEffect(controller.opacity)
        manager = surfaces.Surfaces(controller)
        manager.bind(bubble)
        transition = bubble.size_transition
        with ExitStack() as stack:
            surfaces.install(stack)
            for navigate in (lambda: bubble.set_mode('mini'), lambda: bubble.set_mode('auto'),
                             lambda: bubble.set_mode('mini'), bubble.toggle_details):
                source = bubble.geometry()
                navigate()
                self.assertEqual(transition._linux_stage, 'preparing')
                self.assertEqual(bubble.geometry(), source)
                self.assertEqual(controller.opacity.opacity(), 1)
                self.assertIsNone(transition.landing.image)
                canvas = transition.landing.geometry()
                transition.release_landing()
                self.assertEqual(transition._linux_stage, 'playing')
                self.assertEqual(controller.opacity.opacity(), 0)
                transition.animation.setCurrentTime(transition.animation.duration() // 2)
                self.assertEqual(transition.landing.geometry(), canvas)
                transition.complete()
                self.assertEqual(transition._linux_stage, 'landing')
                self.assertEqual(controller.opacity.opacity(), 0)
                self.assertEqual(transition.landing.geometry(), canvas)
                self.assertIsNotNone(transition.landing.image)
                transition.release_landing()
                self.assertEqual(controller.opacity.opacity(), 1)
                self.assertFalse(transition.landing.isVisible())
                self.assertFalse(transition.landing_timer.isActive())
            bubble.set_mode('mini')
            transition.complete()
            transition.release_landing()
            self.assertEqual(controller.opacity.opacity(), 1)
            self.assertFalse(transition.landing.isVisible())
            bubble.set_mode('auto')
            bubble.hide()
            self.assertEqual(controller.opacity.opacity(), 1)
            self.assertFalse(transition.landing.isVisible())
            self.assertFalse(transition.landing_timer.isActive())
        manager.timer.stop()

    def test_attached_popup_overlaps_native_move_with_original_animation(self):
        """附着角色时仅等 popup 暴露，原动画期间完成目标定位并保留排队导航"""
        pet = QWidget()
        pet.show()
        bubble = CompactBubble()
        bubble.move(100, 300)
        bubble.show()
        APP.processEvents()
        pet.bubble = bubble
        pet.closing = False
        controller = QObject()
        controller.pet = pet
        controller.windows = {}
        controller.reveal = QTimer(controller)
        controller.opacity = QGraphicsOpacityEffect(bubble)
        controller.opacity.setOpacity(1)
        bubble.setGraphicsEffect(controller.opacity)
        manager = surfaces.Surfaces(controller)
        manager.bind(bubble)
        transition = bubble.size_transition
        with ExitStack() as stack:
            surfaces.install(stack)
            bubble.set_mode('mini')
            self.assertIs(transition.landing._linux_popup_parent, pet)
            self.assertEqual(transition.landing.windowType(), Qt.WindowType.ToolTip)
            # 原生子表面会绕过气泡的绘制透明度，并声明不透明矩形
            for child in (bubble.content, transition.cover):
                self.assertFalse(child.testAttribute(Qt.WidgetAttribute.WA_NativeWindow))
                self.assertIsNone(child.windowHandle())
            self.assertEqual(transition.landing_timer.interval(), 0)
            APP.processEvents()
            if transition._linux_stage == 'preparing':
                transition.release_landing()
            self.assertEqual(transition._linux_stage, 'playing')
            self.assertEqual(transition.animation.duration(), 440)
            self.assertEqual(bubble.geometry(), transition.target_rect)
            self.assertEqual(controller.opacity.opacity(), 0)
            bubble.set_mode('auto')
            self.assertEqual(bubble._pending_mode, 'auto')
            transition.complete()
            self.assertEqual(bubble.bubble_mode, 'auto')
            self.assertEqual(transition.animation.duration(), 480)
            self.assertIn(transition._linux_stage, ('preparing', 'playing'))
            APP.processEvents()
            if transition._linux_stage == 'preparing':
                transition.release_landing()
            transition.complete()
            self.assertEqual(transition.landing_timer.interval(), 0)
            transition.release_landing()
            self.assertEqual(controller.opacity.opacity(), 1)
            self.assertFalse(transition.landing.isVisible())
            self.assertFalse(transition.running)
            for child in (bubble.content, transition.cover):
                self.assertFalse(child.testAttribute(Qt.WidgetAttribute.WA_NativeWindow))
                self.assertIsNone(child.windowHandle())
        manager.timer.stop()

    def test_moving_during_navigation_translates_the_prepared_canvas(self):
        """程序化移动与开合重叠时，末帧和真实卡片使用同一角色锚点"""
        pet = QWidget()
        pet.move(200, 400)
        pet.show()
        pet.closing = False
        controller = QObject()
        controller.pet = pet
        controller.windows = {}
        controller.reveal = QTimer(controller)
        controller.opacity = QGraphicsOpacityEffect()
        controller.opacity.setOpacity(1)
        manager = surfaces.Surfaces(controller)
        with ExitStack() as stack:
            surfaces.install(stack)
            bubble = CompactBubble(pet)
            pet.bubble = bubble
            bubble.setGraphicsEffect(controller.opacity)
            bubble.show()
            manager.bind(bubble)
            APP.processEvents()
            bubble.compact_requested()
            transition = bubble.size_transition
            for stage in ('preparing', 'playing', 'landing'):
                with self.subTest(stage=stage):
                    self.assertEqual(transition._linux_stage, stage)
                    rect = QRect(transition.landing.geometry())
                    target = QRect(transition.target_rect if transition.running else bubble.geometry())
                    delta = QPoint(30, -20)
                    pet.move(pet.pos() + delta)
                    manager.sync()
                    self.assertEqual(transition.landing.geometry(), rect.translated(delta))
                    self.assertEqual(transition.target_rect if transition.running else bubble.geometry(), target.translated(delta))
                    if stage == 'preparing':
                        APP.processEvents()
                        transition.release_landing()
                    elif stage == 'playing':
                        transition.complete()
            transition.release_landing()
            self.assertEqual(controller.opacity.opacity(), 1)
            self.assertFalse(transition.landing.isVisible())
            bubble.close()
        manager.timer.stop()

    def test_drag_editor_uses_same_anchor_regardless_of_entry_position(self):
        """编辑页从不同入口位置拖动时均上下避让，触边返回及再次拖动使用相同锚点"""
        pet = QWidget()
        pet.settings = {}
        pet.closing = False
        pet.resize(128, 128)
        pet.show()
        bubble = CompactBubble(pet)
        pet.bubble = bubble
        bubble.panel_page = 'settings'
        bubble._editor_positioned = True
        bubble.show()
        APP.processEvents()
        controller = QObject()
        controller.pet = pet
        manager = surfaces.Surfaces(controller)
        area = APP.primaryScreen().availableGeometry()
        bubble.content.resize(200, 180)
        low = QPoint(area.center().x(), area.bottom() - 130)
        high = QPoint(area.center().x(), area.top() + 10)
        with ExitStack() as stack:
            surfaces.install(stack)
            for initial in (QPoint(100, 100), QPoint(450, 20)):
                pet.move(low)
                bubble.move(initial)
                manager.begin_pet_drag()
                preview = manager.drag_bubble
                for point in (low, high, low, high, low):
                    pet.move(point)
                    preview.refresh()
                    expected = QPoint(point.x() + (pet.width() - bubble.content.width()) // 2,
                                      point.y() + pet.height() + 8 if point == high else point.y() - bubble.content.height() - 8)
                    self.assertEqual(bubble.pos(), expected)
                    self.assertEqual(preview.pos(), QWidget.mapToGlobal(pet, QPoint()) + expected - point)
                    self.assertTrue(bubble._editor_positioned)
                    self.assertFalse(QRect(expected, bubble.content.size()).intersects(pet.geometry()))
                final = QPoint(bubble.pos())
                manager.finish_pet_drag()
                self.assertEqual(bubble.pos(), final)
        manager.timer.stop()

    def test_drag_popup_keeps_original_layout_without_native_children(self):
        """拖动画布复用原布局，在边缘翻转，隐藏后不保留窗口或刷新时钟"""
        pet = QWidget()
        pet.settings = {}
        pet.closing = False
        pet.resize(256, 256)
        pet.move(200, 300)
        pet.show()
        bubble = CompactBubble(pet)
        pet.bubble = bubble
        bubble.show()
        APP.processEvents()
        controller = QObject()
        controller.pet = pet
        manager = surfaces.Surfaces(controller)
        manager.bind(bubble)
        with ExitStack() as stack:
            surfaces.install(stack)
            manager.begin_pet_drag()
            preview = manager.drag_bubble
            self.assertTrue(preview.isVisible())
            self.assertTrue(preview.timer.isActive())
            self.assertEqual(preview.windowType(), Qt.WindowType.ToolTip)
            self.assertFalse(bubble.content.testAttribute(Qt.WidgetAttribute.WA_NativeWindow))
            self.assertFalse(bubble.size_transition.cover.testAttribute(Qt.WidgetAttribute.WA_NativeWindow))
            for point in (QPoint(200, 300), QPoint(0, 0)):
                pet.move(point)
                preview.refresh()
                target = bubble.content_geometry()
                expected = QWidget.mapToGlobal(pet, QPoint()) + target.topLeft() - pet.pos()
                self.assertEqual(preview.pos(), expected)
                self.assertEqual(preview.size(), target.size())
            pet.settings['panel_detached'] = True
            preview.refresh()
            self.assertFalse(preview.isVisible())
            self.assertFalse(preview.timer.isActive())
            manager.finish_pet_drag()
        manager.timer.stop()


if __name__ == '__main__':
    unittest.main()
