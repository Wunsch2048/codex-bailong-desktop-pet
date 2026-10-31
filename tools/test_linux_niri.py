"""验证气泡布局与 Linux 入口的原生拖动边界"""
import unittest
from PySide6.QtCore import QRect, QPoint
from linux_app.niri import bubble_position


class LayoutTests(unittest.TestCase):
    """固定间距与边缘翻转必须保持原有逻辑像素布局"""
    def test_center_and_gap(self):
        """非零工作区原点不应叠加到窗口坐标"""
        point = bubble_position(832, 425, (256, 256), (268, 188), 188, QRect(0, 25, 1920, 1055))
        self.assertEqual(point, QPoint(826, 229))

    def test_top_flips_below(self):
        """气泡在顶部空间不足时转到角色下方"""
        point = bubble_position(400, 80, (256, 256), (268, 188), 188, QRect(0, 25, 1920, 1055))
        self.assertEqual(point, QPoint(394, 344))

    def test_edges_and_fractional_coordinates(self):
        """浮点布局坐标按逻辑像素取整并保持气泡在输出范围内"""
        area = QRect(0, 25, 1920, 1055)
        point = bubble_position(0.2, 500.2, (256, 256), (268, 188), 188, area)
        self.assertEqual(point, QPoint(0, 304))
        point = bubble_position(1800, 500, (256, 256), (268, 188), 188, area)
        self.assertEqual(point.x(), 1652)


class DragTests(unittest.TestCase):
    """全局坐标突变不得进入原来的位移累计路径"""
    def test_docking_and_roaming_read_the_confirmed_output(self):
        """Qt 屏幕信号尚未切换时，贴边判断使用布局所属输出"""
        from contextlib import ExitStack
        from types import SimpleNamespace
        from desktop import DesktopPet
        from linux_app.niri import install
        screen = object()
        pet = SimpleNamespace(_niri_windows=SimpleNamespace(actual_screen=lambda: screen))
        with ExitStack() as stack:
            install(stack)
            self.assertIs(DesktopPet.screen(pet), screen)

    def test_missing_drag_layout_retains_last_global_origin(self):
        """跨屏原生拖动缺少布局坐标时不能退回零点，松手后使用新坐标"""
        from contextlib import ExitStack
        from types import SimpleNamespace
        from desktop import DesktopPet
        from linux_app.niri import install
        controller = SimpleNamespace(last=QPoint(2400, 420), actual_position=lambda: None)
        pet = SimpleNamespace(_niri_windows=controller)
        with ExitStack() as stack:
            install(stack)
            self.assertEqual(DesktopPet.pos(pet), QPoint(2400, 420))
            self.assertEqual(DesktopPet.y(pet), 420)
            controller.actual_position = lambda: QPoint(2150, 100)
            self.assertEqual(DesktopPet.pos(pet), QPoint(2150, 100))

    def test_layout_saves_are_skipped_while_dragging_and_debounced(self):
        """拖动不写设置，连续布局与松手交接只重启同一个保存计时器"""
        from types import SimpleNamespace
        from unittest.mock import Mock
        from linux_app.niri import NiriWindows
        pet = SimpleNamespace(walking=False, _niri_drag=True, _niri_reanchor=False,
                              save_settings=Mock(), remember_wander_home=Mock())
        controller = SimpleNamespace(pet=pet, restored=True, last=None,
            stream=SimpleNamespace(readLine=Mock(return_value=b'{"WindowLayoutsChanged":{"changes":[]}}\n')),
            restore_position=Mock(), position=Mock(), save_timer=SimpleNamespace(start=Mock()),
            move_timeout=SimpleNamespace(stop=Mock()))
        def read(previous, current):
            controller.actual_position = Mock(side_effect=(previous, current))
            controller.stream.canReadLine = Mock(side_effect=(True, False))
            NiriWindows.read(controller)
        read(QPoint(0, 0), QPoint(20, 0))
        pet.save_settings.assert_not_called()
        controller.save_timer.start.assert_not_called()
        pet._niri_drag = False
        read(QPoint(20, 0), QPoint(30, 0))
        controller.save_timer.start.assert_called_once_with()
        pet.save_settings.assert_not_called()
        controller.save_timer.start.reset_mock()
        pet._niri_reanchor = True
        read(QPoint(30, 0), QPoint(40, 0))
        controller.save_timer.start.assert_called_once_with()
        pet.remember_wander_home.assert_called_once_with()
        pet.save_settings.assert_not_called()

    def test_synthetic_release_does_not_finish_native_drag(self):
        """Qt 的模拟松手必须被忽略，离开后重新进入才结束原生拖动"""
        from types import SimpleNamespace
        from unittest.mock import Mock
        from PySide6.QtCore import QEvent
        from linux_app.niri import NiriWindows
        pet = SimpleNamespace(_niri_drag=True, _niri_left=False, mouseReleaseEvent=Mock())
        controller = SimpleNamespace(pet=pet, position=Mock(), reveal=SimpleNamespace(start=Mock()))
        event = lambda kind: SimpleNamespace(type=lambda: kind)
        self.assertTrue(NiriWindows.eventFilter(controller, pet, event(QEvent.Type.MouseButtonRelease)))
        self.assertTrue(pet._niri_drag)
        NiriWindows.eventFilter(controller, pet, event(QEvent.Type.Enter))
        self.assertTrue(pet._niri_drag)
        NiriWindows.eventFilter(controller, pet, event(QEvent.Type.Leave))
        NiriWindows.eventFilter(controller, pet, event(QEvent.Type.Enter))
        self.assertFalse(pet._niri_drag)
        pet.mouseReleaseEvent.assert_called_once()

    def test_native_move_and_lock(self):
        """只用窗口内坐标判断拖动阈值；锁定移动时不调用合成器"""
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from PySide6.QtCore import QPointF, Qt
        from desktop import DesktopPet
        from linux_app.niri import install
        event = SimpleNamespace(position=lambda: QPointF(30, 30), buttons=lambda: Qt.MouseButton.LeftButton,
                                globalPosition=Mock(side_effect=AssertionError('不应读取虚拟全局坐标')), accept=Mock())
        handle = SimpleNamespace(startSystemMove=Mock(return_value=True))
        pet = SimpleNamespace(_niri_windows=SimpleNamespace(surfaces=SimpleNamespace(begin_pet_drag=Mock()), opacity=SimpleNamespace(setOpacity=Mock()), reveal=SimpleNamespace(stop=Mock()), save_timer=SimpleNamespace(stop=Mock())), settings={}, _pointer_pressed=True, _niri_press=QPoint(10, 10),
                              windowHandle=lambda: handle, click_timer=SimpleNamespace(stop=Mock()),
                              last_click=1, drag_samples=[1], generation=0, gate=SimpleNamespace(state='idle'),
                              bubble_timer=SimpleNamespace(stop=Mock()), bubble=SimpleNamespace(hide=Mock(), size_transition=SimpleNamespace(running=False)),
                              begin_drag_panel=Mock(), play=Mock(), manifest={'dragAnimation': 'drag'}, idles=['idle'])
        original = DesktopPet.mouseMoveEvent
        with ExitStack() as stack:
            install(stack)
            DesktopPet.mouseMoveEvent(pet, event)
            handle.startSystemMove.assert_called_once()
            self.assertEqual(pet.drag_samples, [])
            self.assertIsNone(pet.last_click)
            event.accept.assert_called_once()
            self.assertTrue(pet._niri_drag)
            pet._niri_windows.save_timer.stop.assert_called_once_with()
            pet.play.assert_called_once_with('drag', 'drag')
            pet.begin_drag_panel.assert_called_once_with()
            pet._niri_windows.surfaces.begin_pet_drag.assert_called_once()
            pet.settings['no_move'] = True
            DesktopPet.mouseMoveEvent(pet, event)
            handle.startSystemMove.assert_called_once()
        self.assertIs(DesktopPet.mouseMoveEvent, original)


if __name__ == '__main__':
    unittest.main()
