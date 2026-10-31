"""验证 Linux 退出联动与协议跳转，保持原退出和未读确认规则"""
from argparse import Namespace
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication
from codex_navigation import CodexNavigation
from codex_startup import ExitGate
from desktop import DesktopPet
from linux_app import codex_watch, live

APP = QApplication.instance() or QApplication([])
SID = '11111111-1111-4111-8111-111111111111'


class PresencePet(QObject):
    """保留真实信号、轮询与退出规则，隔离素材、网络和用户窗口"""
    codexPresence = Signal(object)
    poll_codex_presence = DesktopPet.poll_codex_presence
    observe_codex_presence = DesktopPet.observe_codex_presence

    def __init__(self):
        """只装配退出检测所需的原成员"""
        super().__init__()
        self.settings = {'codex_exit': True}
        self._codex_exit_gate = ExitGate()
        self._codex_polling = self._codex_closing = False
        self.closed = False
        self.codexPresence.connect(self.observe_codex_presence)
        self.codex_timer = QTimer(self)
        self.codex_timer.setInterval(2000)
        self.codex_timer.timeout.connect(self.poll_codex_presence)

    def close(self):
        """记录确认退出，避免关闭测试应用"""
        self.closed = self._codex_closing = True
        self.codex_timer.stop()


class IntegrationTests(unittest.TestCase):
    """覆盖 Linux 绑定、真实异步交接和外部工具失败"""
    def wait(self, condition):
        """处理 Qt 信号直到工作线程完成，超时使测试失败"""
        deadline = time.monotonic() + 3
        while not condition():
            APP.processEvents()
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.005)

    def test_exit_uses_linux_detector_and_windows_gate(self):
        """未见启动、未知状态、短暂消失、重新出现都不得提前退出"""
        pet = PresencePet()
        with patch.object(codex_watch, 'desktop_sessions') as sessions, ExitStack() as stack:
            codex_watch.install(stack, Namespace(), Path('/source'))
            for current in (set(), set(), set(), {(1, 10)}, set(), None,
                            set(), set(), {(2, 20)}, set(), set()):
                sessions.return_value = current
                pet.poll_codex_presence()
                self.wait(lambda: not pet._codex_polling)
                self.assertFalse(pet.closed)
            sessions.return_value = set()
            pet.settings['codex_exit'] = False
            calls = sessions.call_count
            pet.poll_codex_presence()
            self.assertEqual(sessions.call_count, calls)
            self.assertFalse(pet.closed)
            # 原设置应用会重置 ExitGate，重新启用时不能继承此前的缺席次数
            pet._codex_exit_gate.reset()
            pet.settings['codex_exit'] = True
            for current in (set(), {(3, 30)}, set(), set()):
                sessions.return_value = current
                pet.poll_codex_presence()
                self.wait(lambda: not pet._codex_polling)
                self.assertFalse(pet.closed)
            sessions.return_value = set()
            pet.poll_codex_presence()
            self.wait(lambda: pet.closed)
        pet.deleteLater()

    def test_linux_start_enables_existing_exit_timer(self):
        """Linux 数据启动路径必须接通原定时器"""
        from types import SimpleNamespace
        pet = PresencePet()
        pet.bubble = SimpleNamespace()
        pet.on_activity = lambda event: None
        pet.refresh_quota = lambda: None
        with patch('enhanced.ActivityThread'), patch('PySide6.QtCore.QTimer.singleShot'):
            live.start(pet, Path('/codex'))
        self.assertTrue(pet.codex_timer.isActive())
        self.assertEqual(pet.codex_timer.interval(), 2000)
        pet.close()
        pet.deleteLater()

    def test_protocol_dispatch_and_host_environment(self):
        """使用注册协议和参数数组，宿主工具不继承打包 Qt 路径"""
        result = subprocess.CompletedProcess([], 0, 'chatgpt.desktop\n', '')
        env = dict(LD_LIBRARY_PATH='/bundle', LD_LIBRARY_PATH_ORIG='/host',
                   QT_PLUGIN_PATH='/bundle/plugins', QML2_IMPORT_PATH='/bundle/qml',
                   QT_QPA_PLATFORM='wayland', QT_QPA_PLATFORMTHEME='', WAYLAND_DISPLAY='wayland-1')
        with patch.dict(os.environ, env), patch('sys.frozen', True, create=True), patch.object(live.subprocess, 'run', return_value=result) as run:
            live.open_codex('rollout-2026-10-29-' + SID)
            self.assertEqual(run.call_args_list[0].args[0], ['xdg-mime', 'query', 'default', 'x-scheme-handler/codex'])
            self.assertEqual(run.call_args.args[0], ['xdg-open', 'codex://threads/' + SID])
            child = run.call_args.kwargs['env']
            self.assertEqual(child['LD_LIBRARY_PATH'], '/host')
            self.assertEqual(child['WAYLAND_DISPLAY'], 'wayland-1')
            self.assertNotIn('QT_PLUGIN_PATH', child)
            self.assertNotIn('QML2_IMPORT_PATH', child)
            self.assertNotIn('QT_QPA_PLATFORM', child)
            self.assertEqual(os.environ['QT_PLUGIN_PATH'], '/bundle/plugins')
            live.open_codex()
            self.assertEqual(run.call_args.args[0], ['xdg-open', 'codex://launch'])

    def test_bad_ids_missing_handler_and_dispatch_errors(self):
        """失败须反馈原气泡，不打开浏览器或任意会话作为回退"""
        with patch.object(live.subprocess, 'run') as run:
            for sid in ('bad', '../escape', SID + '?prompt=run'):
                with self.assertRaises(OSError):
                    live.open_codex(sid)
            run.assert_not_called()
        ok = subprocess.CompletedProcess([], 0, 'codex.desktop\n', '')
        cases = [([subprocess.CompletedProcess([], 0, '', '')], '未找到', 1),
                 ([ok, subprocess.CompletedProcess([], 4, '', 'failed')], '无法打开', 2),
                 ([FileNotFoundError()], 'xdg-utils', 1),
                 ([ok, subprocess.TimeoutExpired('xdg-open', 8)], '超时', 2)]
        for effects, message, calls in cases:
            with self.subTest(message=message), patch.object(live.subprocess, 'run', side_effect=effects) as run:
                with self.assertRaisesRegex(OSError, message):
                    live.open_codex(SID)
                self.assertEqual(run.call_count, calls)

    def test_navigation_binding_is_async_and_restored(self):
        """沿用原导航线程，系统派发阻塞时 GUI 仍可处理事件"""
        import desktop, desktop_services
        original = desktop.open_codex, desktop_services.open_codex
        entered, release = threading.Event(), threading.Event()
        def dispatch(command, **kwargs):
            """模拟桌面派发等待，不执行外部程序"""
            if command[0] == 'xdg-open':
                entered.set()
                release.wait(3)
            return subprocess.CompletedProcess(command, 0, 'codex.desktop\n', '')
        nav = CodexNavigation(lambda sid: desktop.open_codex(sid))
        try:
            with ExitStack() as stack, patch.object(live.subprocess, 'run', side_effect=dispatch):
                live.install(stack, Path('/codex'), Path('/cli'))
                self.assertIs(desktop.open_codex, live.open_codex)
                self.assertIs(desktop_services.open_codex, live.open_codex)
                nav.open(SID)
                self.wait(entered.is_set)
                ticks = []
                QTimer.singleShot(0, lambda: ticks.append(True))
                APP.processEvents()
                self.assertEqual(ticks, [True])
                self.assertTrue(nav.busy)
                release.set()
                self.wait(lambda: not nav.busy)
            self.assertEqual((desktop.open_codex, desktop_services.open_codex), original)
        finally:
            release.set()
            nav.close()
            nav.deleteLater()
            APP.processEvents()


if __name__ == '__main__':
    unittest.main()
