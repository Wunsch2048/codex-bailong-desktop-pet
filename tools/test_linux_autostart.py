"""验证 Linux 自启动命令、登记事务与 Windows 隔离"""
from argparse import Namespace
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from linux_app import autostart


class AutostartTests(unittest.TestCase):
    """自启动登记不得修改当前实例生命周期或丢失原有服务"""
    def setUp(self):
        """每个测试使用独立配置目录"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = Namespace(codex_home=self.root/'codex', codex_cli=Path('/bin/true'), data_dir=self.root/'data')
        env = patch.dict(os.environ, XDG_CONFIG_HOME=str(self.root))
        env.start()
        self.addCleanup(env.stop)
        self.manager = autostart.Autostart(self.args, self.root)

    def test_source_preserves_venv_and_arguments(self):
        """虚拟环境解释器不能 resolve 成系统 Python"""
        with patch.object(autostart.sys, 'executable', '/project/.venv/bin/python'):
            command = autostart.launch_command(self.args, self.root)
        self.assertEqual(command[:2], ['/project/.venv/bin/python', str(self.root/'run_linux.py')])
        self.assertIn(str(self.args.data_dir), command)
        self.assertEqual(command[2:4], ['--desktop', 'auto'])

    def test_appimage_and_portable_paths(self):
        """AppImage 使用外部文件，普通便携包忽略无关继承变量"""
        package = self.root/'白龙 $版本%.AppImage'
        package.touch(); package.chmod(0o755)
        mount = self.root/'mount'; mount.mkdir()
        with patch.object(autostart.sys, 'frozen', True, create=True), patch.dict(os.environ, APPIMAGE=str(package), APPDIR=str(mount)):
            with patch.object(autostart.sys, 'executable', str(mount/'bailong-linux')):
                self.assertEqual(autostart.launch_command(self.args, self.root)[0], str(package))
                package.unlink()
                with self.assertRaises(OSError):autostart.launch_command(self.args, self.root)
            with patch.object(autostart.sys, 'executable', '/opt/Bailong/bailong-linux'):
                self.assertEqual(autostart.launch_command(self.args, self.root)[0], '/opt/Bailong/bailong-linux')

    def test_unit_escaping_and_lifecycle(self):
        """特殊路径不展开为环境变量或 systemd specifier"""
        self.assertEqual(autostart.quote('/a $x% "b"'), '"/a $$x%% \\"b\\""')
        with self.assertRaises(OSError):autostart.quote('/a\nb')
        content = self.manager.content()
        self.assertIn('PartOf=graphical-session.target', content)
        self.assertIn('WantedBy=graphical-session.target', content)
        self.assertIn('Restart=on-failure', content)
        self.assertNotIn('NIRI_SOCKET=', content)

    def test_enable_disable_never_starts_or_stops_current_pet(self):
        """开关只改变登录登记，禁用后保留服务文件"""
        with patch.object(self.manager, 'enabled', return_value=False), patch.object(self.manager, 'run') as run:
            self.manager.configure(True)
            self.assertEqual([c.args for c in run.call_args_list], [('daemon-reload',), ('enable', autostart.UNIT)])
            self.assertTrue(self.manager.path.read_text().startswith(autostart.MARKER))
            run.reset_mock()
            self.manager.configure(False)
            run.assert_called_once_with('disable', autostart.UNIT)
            self.assertTrue(self.manager.path.exists())

    def test_failed_enable_restores_previous_file(self):
        """启用失败不能把原服务命令替换成未登记的新路径"""
        old = (autostart.MARKER+'old service\n').encode()
        self.manager.write(old)
        def run(*args, **kwargs):
            """仅模拟第一次启用失败，允许执行回滚"""
            if args == ('enable', autostart.UNIT) and kwargs.get('check', True):raise OSError('synthetic failure')
        with patch.object(self.manager, 'enabled', return_value=True), patch.object(self.manager, 'run', side_effect=run):
            with self.assertRaisesRegex(OSError, 'synthetic'):self.manager.configure(True)
        self.assertEqual(self.manager.path.read_bytes(), old)

    def test_manual_unit_is_not_overwritten(self):
        """用户手工维护的同名服务必须保留"""
        self.manager.write(b'[Service]\nExecStart=/bin/true\n')
        with self.assertRaisesRegex(OSError, '手工'):self.manager.configure(True)
        self.assertFalse(self.manager.path.read_text().startswith(autostart.MARKER))

    def test_linux_bindings_restore(self):
        """三处已导入别名均使用 Linux 管理器，退出适配后恢复原函数"""
        import desktop, desktop_services, desktop_settings
        modules = (desktop, desktop_services, desktop_settings)
        originals = [(m.autostart_enabled, m.set_autostart) for m in modules]
        with ExitStack() as stack:
            autostart.install(stack, self.args, self.root)
            for module in modules:
                self.assertIsInstance(module.set_autostart.__self__, autostart.Autostart)
        for module, expected in zip(modules, originals):
            self.assertEqual((module.autostart_enabled, module.set_autostart), expected)

    def test_old_systemd_missing_unit_and_unavailable_bus(self):
        """旧版本缺失单元应显示关闭，用户总线失败必须明确报错"""
        missing = subprocess.CompletedProcess([], 1, '', 'localized missing unit')
        unloaded = subprocess.CompletedProcess([], 0, 'not-found\n', '')
        with patch.object(self.manager, 'run', side_effect=[missing, unloaded]):
            self.assertFalse(self.manager.enabled())
        with patch.object(self.manager, 'run', side_effect=OSError('bus unavailable')):
            with self.assertRaisesRegex(OSError, 'bus unavailable'):self.manager.enabled()
