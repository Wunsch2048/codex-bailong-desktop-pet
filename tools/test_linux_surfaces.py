"""验证面板坐标桥接与跨输出移动确认"""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from PySide6.QtCore import QPoint, QRect, QSize
from linux_app.surfaces import Surfaces


class SurfaceTests(unittest.TestCase):
    """多个表面使用独立目标，未确认位移不得重复叠加"""
    def manager(self):
        """构造明确的双屏布局及单个已登记面板"""
        widget = Mock()
        widget._linux_popup_parent = None
        widget.isVisible.return_value = True
        widget.size.return_value = QSize(268, 188)
        point = QPoint(2200, 400)
        entry = dict(point=point, waiting=None, workspace=None, sent_at=0.)
        window = dict(id=7, workspace_id=2)
        c = SimpleNamespace(windows={}, workspaces={1:'left',2:'right'}, action=Mock(), character=lambda: dict(workspace_id=2))
        transition = SimpleNamespace(landing=SimpleNamespace())
        m = SimpleNamespace(pet=SimpleNamespace(closing=False, settings={}, bubble=SimpleNamespace(size_transition=transition)), controller=c, entries={widget:entry},
                            dragging=None, window=lambda w:window, actual=lambda w:QPoint(2100,400), timer=Mock())
        return m, widget, entry, window

    def test_relative_move_waits_for_confirmation(self):
        """重复布局事件不能重复发送同一增量，新目标等待旧请求确认"""
        m,w,e,_=self.manager()
        with patch('linux_app.surfaces.QApplication.screenAt', return_value=SimpleNamespace(name=lambda:'right')):
            Surfaces.sync(m);Surfaces.sync(m)
            m.controller.action.assert_called_once_with('MoveFloatingWindow',id=7,x={'AdjustFixed':100},y={'AdjustFixed':0})
            e['point']=QPoint(2250,400)
            m.actual=lambda w:QPoint(2200,400)
            Surfaces.sync(m)
            self.assertEqual(m.controller.action.call_args.kwargs['x'],{'AdjustFixed':50})

    def test_cross_monitor_before_position(self):
        """跨屏先请求输出，不能对旧输出的原点计算位移"""
        m,w,e,window=self.manager();window['workspace_id']=1
        with patch('linux_app.surfaces.QApplication.screenAt', return_value=SimpleNamespace(name=lambda:'right')):
            Surfaces.sync(m);Surfaces.sync(m)
        m.controller.action.assert_called_once_with('MoveWindowToMonitor',id=7,output='right')

    def test_detached_drag_is_not_pulled_back(self):
        """用户拖动和隐藏期间不能补发旧的面板位置"""
        m,w,_,_=self.manager();m.dragging=w
        Surfaces.sync(m)
        m.controller.action.assert_not_called()
        m.dragging=None;w.isVisible.return_value=False
        Surfaces.sync(m)
        m.controller.action.assert_not_called()

    def test_workspace_ack_precedes_delta(self):
        """同一显示器不同工作区时先等待工作区切换"""
        m,w,e,window=self.manager();m.controller.workspaces[3]='right';window['workspace_id']=3
        with patch('linux_app.surfaces.QApplication.screenAt', return_value=SimpleNamespace(name=lambda:'right')):
            Surfaces.sync(m)
        m.controller.action.assert_called_once_with('MoveWindowToWorkspace',window_id=7,reference={'Id':2},focus=False)

    def test_parented_popup_never_receives_floating_window_moves(self):
        """原生 popup 由父表面定位，即使旧顶层窗口记录尚未移除也不能补发位移"""
        m, widget, _, _ = self.manager()
        widget._linux_popup_parent = object()
        Surfaces.sync(m)
        m.controller.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
