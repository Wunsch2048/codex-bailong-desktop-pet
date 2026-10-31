"""验证 niri 原生拖动接入共享收纳状态和单一动画画布"""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QGraphicsOpacityEffect
from linux_app import niri, surfaces
import test_native_interactions as native

APP = native.APP


class LinuxDragPanelTests(unittest.TestCase):
    def setUp(self):
        """使用真实角色和面板，隔离素材能力、合成器通信和用户目录"""
        native.InteractionTests.setUp(self)
        self.pet._materials_missing = False
        self.point = self.pet.screen().availableGeometry().center() - self.pet.rect().center()
        controller = self.controller = QObject()
        controller.pet = self.pet
        controller.windows = {}
        controller.restored = True
        controller.last = self.point
        controller.actual_position = lambda: QPoint(self.point)
        controller.actual_screen = self.pet.screen
        controller.cancel_move = Mock()
        controller.request_move = Mock(side_effect=self.move)
        controller.save_timer = SimpleNamespace(stop=Mock())
        controller.reveal = SimpleNamespace(start=Mock(), stop=Mock())
        controller.opacity = QGraphicsOpacityEffect(self.pet.bubble)
        controller.opacity.setOpacity(1)
        self.pet.bubble.setGraphicsEffect(controller.opacity)
        controller.surfaces = surfaces.Surfaces(controller)
        controller.surfaces.bind(self.pet.bubble)
        controller.position = self.pet.position_bubble
        self.pet._niri_windows = controller
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(self.pet, 'play', side_effect=lambda action, mode='idle', **kw: setattr(self.pet, 'mode', mode)))
        niri.install(self.stack)

    def move(self, point):
        """模拟已确认的合成器位置，不触发真实 IPC"""
        self.point = QPoint(point)

    def settle(self):
        """结束共享形变和原生交接，不依赖墙钟等待"""
        t = self.pet.bubble.size_transition
        for _ in range(3):
            APP.processEvents()
            t.complete()
            t.release_landing()
        APP.processEvents()

    def tearDown(self):
        """取消拖动并回收辅助窗口和时钟，再恢复原类方法"""
        self.pet._niri_drag = False
        self.pet.cancel_pointer()
        self.controller.surfaces.finish_pet_drag()
        self.controller.surfaces.timer.stop()
        native.InteractionTests.tearDown(self)
        self.stack.close()

    def drag(self):
        """从真实按下入口进入 niri 原生拖动"""
        p = self.pet
        press = SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton,
                                position=lambda: QPointF(30, 30),
                                globalPosition=lambda: QPointF(self.point + QPoint(30, 30)))
        event = SimpleNamespace(buttons=lambda: Qt.MouseButton.LeftButton,
                                position=lambda: QPointF(60, 60), accept=Mock())
        p.mousePressEvent(press)
        with patch.object(p.windowHandle(), 'startSystemMove', return_value=True):
            p.mouseMoveEvent(event)
        self.assertTrue(p._niri_drag)
        self.assertTrue(p.drag_panel.active)

    def release(self):
        """模拟合成器真正结束拖动时的离开和重新进入"""
        for kind in (QEvent.Type.Leave, QEvent.Type.Enter):
            niri.NiriWindows.eventFilter(self.controller, self.pet, SimpleNamespace(type=lambda: kind))
        self.settle()

    def test_collect_follow_and_restore_preserve_saved_mode(self):
        """收纳动画先播放，随后跟随；普通模式恢复且紧凑偏好不被改写"""
        p = self.pet
        for mode in ('auto', 'mini', 'minimal'):
            with self.subTest(mode=mode):
                p.apply_settings(dict(bubble_mode=mode), save=False)
                self.settle()
                p.bubble.expanded = mode == 'auto'
                p.bubble.redraw()
                self.settle()
                self.drag()
                t = p.bubble.size_transition
                if t.running:
                    self.assertFalse(self.controller.surfaces.drag_bubble and self.controller.surfaces.drag_bubble.isVisible())
                    target = QPoint(t.target_rect.topLeft())
                    self.point += QPoint(25, 10)
                    p.position_bubble()
                    self.assertEqual(t.target_rect.topLeft(), target + QPoint(25, 10))
                self.settle()
                self.assertTrue(self.controller.surfaces.drag_bubble.isVisible())
                self.assertEqual(p.bubble.compact_kind(), 'minimal' if mode == 'minimal' else 'mini')
                self.release()
                self.assertFalse(p.drag_panel.active)
                self.assertEqual(p.settings['bubble_mode'], mode)
                self.assertFalse(p.bubble.expanded)
                self.assertEqual(p.bubble.is_compact(), mode != 'auto')
                niri.NiriWindows.reveal_bubble(self.controller)
                self.assertFalse(self.controller.surfaces.drag_bubble.isVisible())

    def test_edge_drop_and_drag_out_keep_original_mode(self):
        """松手执行共享贴边逻辑，拖出侧边接受保留入场状态参数"""
        p = self.pet
        p.apply_settings(dict(bubble_mode='mini'), save=False)
        self.settle()
        self.drag()
        self.point.setX(p.screen().availableGeometry().left())
        self.release()
        self.assertTrue(p.edge_dock.active)
        self.assertTrue(p.bubble.is_minimal())
        niri.NiriWindows.reveal_bubble(self.controller)
        self.drag()
        self.settle()
        self.assertFalse(p.edge_dock.active)
        self.assertTrue(p.bubble.is_island())
        self.assertEqual(p.settings['bubble_mode'], 'mini')
        self.pet._niri_drag = False
        p.cancel_pointer()
        self.settle()
        self.assertFalse(p.drag_panel.active)
        self.assertEqual(p.settings['bubble_mode'], 'mini')

    def test_walk_completion_retains_route_and_manual_stop_discards_it(self):
        """新主线分段走动的落地参数透传，手动打断仍清理待发位移"""
        self.pet.roaming.queue = [(350, 300)]
        self.pet.stop_walk(land=True, preserve_route=True)
        self.assertEqual(self.pet.roaming.queue, [(350, 300)])
        self.controller.cancel_move.reset_mock()
        self.pet.stop_walk()
        self.assertFalse(self.pet.roaming.queue)
        self.controller.cancel_move.assert_called_once_with()

    def test_hiding_during_native_drag_releases_canvas_and_restores_opacity(self):
        """隐藏打断原生拖动后撤销收纳和辅助时钟，重新显示时主面板可见"""
        self.drag()
        self.settle()
        self.assertEqual(self.controller.opacity.opacity(), 0)
        niri.NiriWindows.eventFilter(self.controller, self.pet, SimpleNamespace(type=lambda: QEvent.Type.Hide))
        self.assertFalse(self.pet._niri_drag)
        self.assertFalse(self.pet.drag_panel.active)
        self.assertFalse(self.controller.surfaces.drag_bubble.timer.isActive())
        self.assertFalse(self.controller.surfaces.drag_bubble.isVisible())
        self.settle()
        self.assertEqual(self.controller.opacity.opacity(), 1)
        self.controller.reveal.stop.assert_called()

    def test_delayed_drag_reveal_cannot_interrupt_the_next_expansion(self):
        """拖动后的旧显示回调不能暴露动画中间态，最终交接也不能恢复为透明"""
        from surface_morph import complete_frame
        bubble = self.pet.bubble
        for mode in ('mini', 'minimal'):
            with self.subTest(mode=mode):
                self.pet.apply_settings(dict(bubble_mode=mode), save=False)
                self.settle()
                bubble.size_transition._hold_icon(True)
                expected = complete_frame(bubble).toImage()
                self.controller.opacity.setOpacity(0)
                if mode == 'mini':
                    bubble.island.expand.emit()
                else:
                    bubble.minimal_quota.click()
                APP.processEvents()
                transition = bubble.size_transition
                if transition._linux_stage == 'preparing':
                    transition.release_landing()
                self.assertEqual(transition._linux_stage, 'playing')
                self.assertEqual(transition.morph.start.frame.toImage(), expected)
                niri.NiriWindows.reveal_bubble(self.controller)
                self.assertEqual(self.controller.opacity.opacity(), 0)
                self.assertTrue(transition.landing.isVisible())
                self.settle()
                self.assertEqual(self.controller.opacity.opacity(), 1)
                self.assertFalse(transition.landing.isVisible())
                self.controller.reveal.stop.assert_called()

    def test_repeated_capsule_navigation_and_movement_preserve_live_pixels(self):
        """从原生离屏缓冲读稳定帧，覆盖移动后展开及展开中拖动的局部刷新"""
        bubble = self.pet.bubble
        bubble.quota([dict(name='一周', remaining=61, resetsAt=None)])
        self.pet.apply_settings(dict(bubble_mode='mini'), save=False)
        self.settle()
        for cycle in range(6):
            with self.subTest(cycle=cycle):
                if cycle % 3 == 1:
                    self.drag()
                    self.point += QPoint(20, 10)
                    self.pet.position_bubble()
                    self.release()
                bubble.island.expand.emit()
                if cycle % 3 == 2:
                    self.drag()
                    self.point += QPoint(-20, -10)
                    self.pet.position_bubble()
                    self.release()
                self.settle()
                niri.NiriWindows.reveal_bubble(self.controller)
                bubble.size_transition._hold_icon(True)
                bubble.quota_summary_card.update()
                APP.processEvents()
                # QWidget.grab 会重新绘制并可能掩盖缺块，屏幕接口直接读取离屏平台的缓冲
                frame = bubble.screen().grabWindow(int(bubble.winId())).toImage()
                self.assertFalse(frame.isNull())
                image = frame.convertToFormat(QImage.Format.Format_RGBA8888)
                pixels = bytes(image.constBits())
                stride = image.bytesPerLine()
                ratio = image.devicePixelRatioF()
                inset = round(20 * ratio)
                for y in range(inset, image.height() - inset):
                    self.assertTrue(all(a == 255 for a in pixels[y * stride + inset * 4 + 3:y * stride + (image.width() - inset) * 4:4]))
                quota = bubble.quota_summary_card
                point = quota.mapTo(bubble, QPoint())
                rect = QRect(round(point.x() * ratio), round(point.y() * ratio),
                             round(quota.width() * ratio), round(quota.height() * ratio))
                ink = sum(image.pixelColor(x, y).lightness() < 180
                          for y in range(rect.top(), rect.bottom())
                          for x in range(rect.left(), rect.right()))
                self.assertGreater(ink, 100, '额度正文不能只有不透明背景')
                bubble.compact_requested()
                self.settle()
                self.assertTrue(bubble.is_island())


if __name__ == '__main__':
    unittest.main()
