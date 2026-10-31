"""验证 Linux 入口迁移与 Codex 数据目录边界"""
from argparse import Namespace
from contextlib import ExitStack
from pathlib import Path
import json
import itertools
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from linux_app import launcher


class LauncherTests(unittest.TestCase):
    """正式入口必须保留用户状态，且不能把桌宠文件写入 Codex 目录"""
    def test_startup_preserves_saved_switches_with_or_without_old_markers(self):
        """实际装配入口保留合法偏好，迁移标记不改变三个开关"""
        from desktop_core import normalized
        pet = Mock()
        pet.apply_settings.side_effect = lambda values, save=True: pet.settings.update(values)
        args = Namespace(desktop='niri', codex_home=Path('/unused/codex'), codex_cli=Path('/unused/cli'))
        with ExitStack() as stack:
            for target in ('autostart.install', 'codex_watch.install', 'live.install', 'live.start', 'ui.install', 'niri.install', 'niri.attach'):
                stack.enter_context(patch('linux_app.' + target))
            stack.enter_context(patch('desktop.DesktopPet', return_value=pet))
            stack.enter_context(patch('enhanced.ResetThread'))
            keys = ('wandering', 'random_actions', 'commentary')
            for values in itertools.product((False, True), repeat=3):
                for markers in ({}, dict(linux_behaviors_ready=True, linux_wandering_ready=True)):
                    with self.subTest(values=values, markers=markers):
                        saved = dict(zip(keys, values), **markers)
                        pet.settings = normalized(saved)
                        pet.apply_settings.reset_mock()
                        for _ in range(2):
                            launcher.create_pet(stack, args)
                            self.assertEqual({k: pet.settings[k] for k in keys}, dict(zip(keys, values)))
                        self.assertFalse(pet.settings['sound'])
                        self.assertTrue(all(call.kwargs.get('save') is False for call in pet.apply_settings.call_args_list))
            pet.settings = normalized(dict(wandering=False))
            launcher.create_pet(stack, args)
            self.assertFalse(pet.settings['wandering'])
            self.assertTrue(pet.settings['random_actions'])
            self.assertTrue(pet.settings['commentary'])

    def test_new_state_defaults_do_not_rewrite_an_existing_file(self):
        """新安装默认开启行为，已有设置文件逐字保留"""
        with tempfile.TemporaryDirectory() as folder, patch('material_store.MaterialStore') as store:
            store.return_value.current = 'light'
            state = Path(folder)
            with patch.object(launcher, 'ROOT', state):
                launcher.prepare_state(state)
                config = state / 'settings.json'
                self.assertTrue(all(json.loads(config.read_text())[key] for key in ('wandering', 'random_actions', 'commentary')))
                previous = '{"wandering": false, "random_actions": false, "commentary": false}'
                config.write_text(previous)
                launcher.prepare_state(state)
                self.assertEqual(config.read_text(), previous)

    def test_environment_is_separate(self):
        """真实数据源与桌宠写入目录保持独立"""
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ):
            root = Path(folder)
            args = Namespace(data_dir=root / 'pet', codex_home=root / 'codex')
            state = launcher.environment(args)
            self.assertEqual(state, root / 'pet/BailongEnhanced')
            self.assertEqual(os.environ['CODEX_HOME'], str(args.codex_home))
            self.assertFalse(args.codex_home.exists())
            self.assertEqual(os.environ['QT_QPA_PLATFORM'], 'wayland')

    def test_migrate_once_without_resetting_settings(self):
        """迁移已保存偏好后，后续启动不得覆盖修改或重选素材"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / 'work/linux-validation/state-live/BailongEnhanced'
            legacy.mkdir(parents=True)
            (legacy / 'settings.json').write_text('{"scale": 1.2}')
            state = root / 'state'
            state.mkdir()
            with patch.object(launcher, 'ROOT', root), patch('material_store.MaterialStore') as store, patch('linux_app.live.prepare_materials') as materials:
                store.return_value.current = 'hd'
                launcher.prepare_state(state)
                self.assertEqual(json.loads((state / 'settings.json').read_text()), {'scale': 1.2})
                (state / 'settings.json').write_text('{"scale": 1.5}')
                launcher.prepare_state(state)
                self.assertEqual(json.loads((state / 'settings.json').read_text()), {'scale': 1.5})
                materials.assert_not_called()

    def test_reject_codex_as_writable_state(self):
        """启动参数不能绕过真实 Codex 数据目录的写入边界"""
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, WAYLAND_DISPLAY='test', NIRI_SOCKET='test'):
            with self.assertRaises(SystemExit) as result:
                launcher.arguments(['--codex-home', folder, '--codex-cli', '/bin/true', '--data-dir', folder + '/pet'])
            self.assertEqual(result.exception.code, 2)

    def test_kde_arguments_discover_cli_on_path(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CURRENT_DESKTOP':'KDE', 'DISPLAY':':0'}, clear=True):
            cli = Path(folder) / 'codex'
            cli.write_text('#!/bin/sh\nexit 0\n')
            cli.chmod(0o755)
            with patch('linux_app.launcher.shutil.which', side_effect=lambda name: str(cli) if name == 'codex' else '/usr/bin/bwrap'):
                args = launcher.arguments(['--codex-home', folder, '--data-dir', folder + '-state'])
            self.assertEqual((args.desktop, args.qt_platform), ('kde', 'xcb'))
            self.assertEqual(args.codex_cli, cli)

    def test_kde_environment_selects_xcb_before_importing_qt(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, QT_QPA_PLATFORM='wayland'):
            args = Namespace(data_dir=Path(folder), codex_home=Path(folder) / 'codex', qt_platform='xcb')
            launcher.environment(args)
            self.assertEqual(os.environ['QT_QPA_PLATFORM'], 'xcb')


if __name__ == '__main__':
    unittest.main()
