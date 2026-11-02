"""验证 niri 走动坐标、请求合并与输入打断"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from PySide6.QtCore import QPoint, QRect, QSize
from linux_app.niri import NiriWindows


def controller():
    """使用确定性窗口布局检查实际传给合成器的移动请求"""
    screen = SimpleNamespace(geometry=lambda: QRect(-1920, 0, 1920, 1080),
                             availableGeometry=lambda: QRect(-1920, 25, 1920, 1055))
    pet = SimpleNamespace(closing=False, dragging=False, _pointer_pressed=False, settings={},
                          screen=lambda: screen, size=lambda: QSize(256, 256),
                          isVisible=lambda: True, stop_walk=Mock())
    window = dict(id=42, layout=dict(tile_pos_in_workspace_view=[100, 100], window_offset_in_tile=[0, 0]))
    c = SimpleNamespace(pet=pet, character=lambda: window, move_target=None, move_waiting=False,
                        move_timer=Mock(), move_timeout=Mock(), action=Mock())
    c.move_timer.isActive.return_value = False
    c.actual_screen = lambda: screen
    c.actual_position = lambda: NiriWindows.actual_position(c)
    c.cancel_move = lambda: NiriWindows.cancel_move(c)
    return c, window


class WalkTests(unittest.TestCase):
    """一次只提交一个相对位移，后续位移必须基于已确认坐标"""
    def test_output_origin_and_latest_target(self):
        """输出原点不应误算成额外位移，多次请求合并到最后目标"""
        c, _ = controller()
        self.assertEqual(c.actual_position(), QPoint(-1820, 100))
        NiriWindows.request_move(c, QPoint(-1810, 110))
        NiriWindows.request_move(c, QPoint(-1800, 120))
        NiriWindows.flush_move(c)
        c.action.assert_called_once_with('MoveFloatingWindow', id=42, x={'AdjustFixed': 20}, y={'AdjustFixed': 20})
        NiriWindows.request_move(c, QPoint(-1750, 130))
        NiriWindows.flush_move(c)
        self.assertEqual(c.action.call_count, 1)

    def test_next_step_uses_confirmed_position(self):
        """已确认第一步后不能重复叠加旧坐标差"""
        c, w = controller()
        NiriWindows.request_move(c, QPoint(-1800, 100))
        NiriWindows.flush_move(c)
        w['layout']['tile_pos_in_workspace_view'] = [120, 100]
        c.move_waiting = False
        NiriWindows.request_move(c, QPoint(-1780, 100))
        NiriWindows.flush_move(c)
        self.assertEqual(c.action.call_args.kwargs['x'], {'AdjustFixed': 20})

    def test_boundary_clamps_entire_character(self):
        """超出目标必须约束整个人物画布，而非只约束左上角"""
        c, _ = controller()
        NiriWindows.request_move(c, QPoint(9999, 9999))
        NiriWindows.flush_move(c)
        self.assertEqual(c.action.call_args.kwargs['x'], {'AdjustFixed': 1564})
        self.assertEqual(c.action.call_args.kwargs['y'], {'AdjustFixed': 724})

    def test_press_and_lock_discard_unsent_movement(self):
        """鼠标按下或锁定移动时排队目标被丢弃，释放后不能补发"""
        for field in ('press', 'lock', 'drag'):
            c, _ = controller()
            NiriWindows.request_move(c, QPoint(-1800, 100))
            c.pet._pointer_pressed = field == 'press'
            c.pet.dragging = field == 'drag'
            c.pet.settings['no_move'] = field == 'lock'
            NiriWindows.flush_move(c)
            self.assertIsNone(c.move_target)
            c.action.assert_not_called()
            c.move_timer.stop.assert_called_once()

    def test_timeout_stops_walk(self):
        """合成器无确认时结束走动，不在错误坐标上继续积分"""
        c, _ = controller()
        NiriWindows.request_move(c, QPoint(-1800, 100))
        NiriWindows.flush_move(c)
        NiriWindows.movement_failed(c)
        self.assertFalse(c.move_waiting)
        self.assertIsNone(c.move_target)
        c.pet.stop_walk.assert_called_once()


if __name__ == '__main__':
    unittest.main()
