"""验证 Linux Codex 启动监听的进程识别和独立生命周期"""
from argparse import Namespace
from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from linux_app import codex_watch
from linux_app.autostart import Autostart
from codex_startup import LaunchGate


class WatchTests(unittest.TestCase):
    """桌面会话只触发一次，服务与现有桌宠互不误杀"""
    def test_persistent_launch_failure_is_attempted_once_per_session(self):
        """持续错误或超时不会让同一个 Codex 会话反复请求启动"""
        for failure in (OSError('synthetic failure'), subprocess.TimeoutExpired('systemd-run', 5)):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as folder:
                stopped = Mock()
                stopped.is_set.side_effect = [False] * 6 + [True]
                output = io.StringIO()
                with patch.object(codex_watch.threading, 'Event', return_value=stopped), \
                     patch.object(codex_watch.signal, 'signal'), \
                     patch.object(codex_watch, 'desktop_sessions', return_value={(1, 10.)}), \
                     patch.object(codex_watch, 'start_pet', side_effect=failure) as start, redirect_stdout(output):
                    self.assertEqual(codex_watch.watch(Namespace(), Path(folder), Path(folder)), 0)
                start.assert_called_once()
                self.assertEqual(stopped.wait.call_count, 6)
                self.assertIn('本次会话不再自动重试', output.getvalue())

    def test_new_codex_session_can_start_after_failure(self):
        """未知状态保留尝试记录，确认退出并重新启动后允许再次拉起"""
        sessions = [{(1, 10.)}, None, {(1, 10.)}, set(), set(), {(2, 20.)}, {(2, 20.)}]
        with tempfile.TemporaryDirectory() as folder:
            stopped = Mock()
            stopped.is_set.side_effect = [False] * len(sessions) + [True]
            with patch.object(codex_watch.threading, 'Event', return_value=stopped), \
                 patch.object(codex_watch.signal, 'signal'), \
                 patch.object(codex_watch, 'desktop_sessions', side_effect=sessions), \
                 patch.object(codex_watch, 'start_pet', side_effect=[OSError('synthetic failure'), None]) as start, redirect_stdout(io.StringIO()):
                codex_watch.watch(Namespace(), Path(folder), Path(folder))
            self.assertEqual(start.call_count, 2)

    def test_process_filter_and_unknown(self):
        """CLI、Electron 子进程与其他用户不得触发桌宠"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'resources').mkdir();(root/'resources/app.asar').touch()
            def process(pid, binary, command, uid=None):
                """创建合成进程记录，不接触用户进程"""
                return SimpleNamespace(info={'name':'Codex','uids':SimpleNamespace(real=os.getuid() if uid is None else uid)},
                    pid=pid,exe=lambda:str(binary),cmdline=lambda:command,create_time=lambda:10.)
            gui=process(1,root/'Codex',['Codex'])
            cli=process(2,root/'bin/codex',['codex'])
            helper=process(3,root/'Codex',['Codex','--type=renderer'])
            other=process(4,root/'Codex',['Codex'],os.getuid()+1)
            with patch.object(codex_watch.psutil,'process_iter',return_value=[gui,cli,helper,other]):
                self.assertEqual(codex_watch.desktop_sessions(),{(1,10.)})
            denied=process(5,root/'Codex',['Codex']);denied.exe=Mock(side_effect=codex_watch.psutil.AccessDenied(5))
            with patch.object(codex_watch.psutil,'process_iter',return_value=[denied]):
                self.assertIsNone(codex_watch.desktop_sessions())

    def test_session_edges_match_windows_gate(self):
        """手动退出桌宠不重启，Codex 新会话和重新打开才触发"""
        gate=LaunchGate()
        self.assertFalse(gate.observe(set()))
        self.assertTrue(gate.observe({(1,10.)}))
        self.assertFalse(gate.observe({(1,10.)}))
        self.assertFalse(gate.observe(None))
        self.assertFalse(gate.observe({(1,10.)}))
        self.assertTrue(gate.observe({(2,20.)}))
        self.assertFalse(gate.observe(set()))
        self.assertFalse(gate.observe(set()))
        self.assertTrue(gate.observe({(2,20.)}))

    def test_watcher_service_switch_and_gui_independence(self):
        """监听开关立即启停监听服务，不操作桌宠单元"""
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,XDG_CONFIG_HOME=directory):
            args=Namespace(codex_home=Path(directory),codex_cli=Path('/bin/true'),data_dir=Path(directory))
            manager=Autostart(args,Path(directory),unit=codex_watch.WATCH_UNIT,flags=('--watch-codex',),immediate=True)
            self.assertIn('"--watch-codex"',manager.content())
            with patch.object(manager,'enabled',return_value=False),patch.object(manager,'run') as run:
                manager.configure(True)
                self.assertEqual(run.call_args.args,('restart',codex_watch.WATCH_UNIT))
                run.reset_mock();manager.configure(False)
                run.assert_called_once_with('disable','--now',codex_watch.WATCH_UNIT)

    def test_spawn_uses_separate_service_and_preserves_data_directory(self):
        """监听器停用不会通过同一 cgroup 杀死已启动的桌宠"""
        args=Namespace(codex_home=Path('/codex'),codex_cli=Path('/cli'),data_dir=Path('/pet'))
        with patch.object(codex_watch.subprocess,'run',side_effect=[subprocess.CompletedProcess([],3,'inactive\n',''),subprocess.CompletedProcess([],0,'','')]) as run:
            codex_watch.start_pet(args,Path('/source'))
            command=run.call_args.args[0]
            self.assertIn('--unit='+codex_watch.PET_UNIT,command)
            self.assertIn('--property=PartOf=graphical-session.target',command)
            self.assertEqual(command[-2:],['--data-dir','/pet'])
            self.assertNotIn('--watch-codex',command)
        with patch.object(codex_watch.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'active\n','')) as run:
            codex_watch.start_pet(args,Path('/source'))
            self.assertEqual(run.call_count,1)

    def test_settings_binding_and_qt_free_import(self):
        """监听入口不依赖 Qt，设置函数退出适配后恢复"""
        import codex_startup
        original=codex_startup.configure
        original_sessions=codex_startup.desktop_sessions
        with ExitStack() as stack:
            codex_watch.install(stack,Namespace(),Path('/source'))
            self.assertIsInstance(codex_startup.configure.__self__,Autostart)
            self.assertIs(codex_startup.desktop_sessions,codex_watch.desktop_sessions)
        self.assertIs(codex_startup.configure,original)
        self.assertIs(codex_startup.desktop_sessions,original_sessions)
        result=subprocess.run([sys.executable,'-c','import sys; from linux_app.codex_watch import watch; assert not any(n.startswith("PySide6") for n in sys.modules)'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
