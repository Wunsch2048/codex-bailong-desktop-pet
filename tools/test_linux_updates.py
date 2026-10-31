"""Linux 更新入口只允许兼容动画，不触发 Windows 安装与清理"""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QPushButton
from app_updates import Release
from app_updates import NoRelease, check_release
from test_app_updates import payload, Response
import json
from urllib.error import HTTPError
from desktop import DesktopPet
from desktop_settings import SettingsDialog
from linux_app import ui
from test_settings_controls import PetStub
from update_controller import UpdateController, UpdateJob
from update_widgets import UpdatePanel

APP = QApplication.instance() or QApplication([])


class LinuxUpdateTests(unittest.TestCase):
    def setUp(self):
        """所有状态只写入临时目录，平台能力固定为 Linux"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.support = patch('app_updates.program_updates_supported', return_value=False)
        self.support.start()
        self.addCleanup(self.support.stop)
        self.controller = UpdateController('1.3.0', self.root / 'updates', allow_auto=False)
        self.animation = Release('1.3.1', 'v1.3.1', 'animation.zip', '', 1, 'a' * 64,
                                 kind='animation', animation_catalog={}, minimum_program_version='1.3.0')

    def tearDown(self):
        """结束测试的控制器与控件，不留下后台任务"""
        self.controller.shutdown()
        self.controller.deleteLater()
        for widget in APP.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_manual_check_selects_animation_capability_without_installing(self):
        """关闭自动检查后手动检查仍可用，但不能选择程序包"""
        with patch.object(self.controller, '_bind') as bind:
            self.assertTrue(self.controller.check())
        job = bind.call_args.args[0]
        values = []
        job.result.connect(values.append)
        with patch('update_controller.check_release', return_value=self.animation) as query, \
             patch('update_controller.stage_installer') as stage:
            job.run()
        self.assertFalse(query.call_args.kwargs['allow_program'])
        self.assertEqual(query.call_args.kwargs['program_version'], '1.3.0')
        self.assertEqual(values, [self.animation])
        stage.assert_not_called()
        self.assertFalse(self.controller.install_requested)

    def test_program_only_release_has_no_compatible_update_even_with_api_limit(self):
        """纯程序发布在主通道和备用通道均不可安装，也不读取程序包"""
        for limited in (False, True):
            calls = []
            def opener(url, headers=None):
                """备用通道只提供公开校验清单，任何包体请求都使测试失败"""
                calls.append(url)
                if url.endswith('/releases/latest'):
                    if limited:raise HTTPError(url, 429, 'limited', {}, None)
                    return Response(json.dumps(payload('1.3.1')).encode())
                self.assertTrue(url.endswith('/SHA256SUMS.txt'))
                return Response(('a' * 64 + '  bailong-desktop-pet-1.3.1-windows-x64.zip\n').encode())
            with self.subTest(limited=limited), self.assertRaises(NoRelease):
                check_release('1.3.0', opener, state_dir=self.root, allow_program=False)
            self.assertEqual(len(calls), 2 if limited else 1)

    def test_program_and_full_packages_are_blocked_at_every_execution_entry(self):
        """直接调用控制器、工作线程或安装回调也不能启动 Windows 处理"""
        for kind in ('program', 'full'):
            with self.subTest(kind=kind):
                release = replace(self.animation, kind=kind)
                self.controller.release = release
                with patch.object(self.controller, '_bind') as bind:
                    self.assertFalse(self.controller.download_install())
                    bind.assert_not_called()
                job = UpdateJob('1.3.0', self.controller.cache, release, program_version='1.3.0')
                errors = []
                job.failed.connect(lambda phase, message: errors.append(message))
                with patch('program_updates.stage_program') as program, patch('update_controller.stage_installer') as full:
                    job.run()
                program.assert_not_called()
                full.assert_not_called()
                self.assertIn('Windows', errors[0])
                pet = SimpleNamespace(updates=self.controller)
                with patch('process_launch.launch_own') as launch, patch('program_updates.verify_ready') as verify:
                    DesktopPet.install_app_update(pet, '/unused/source')
                launch.assert_not_called()
                verify.assert_not_called()
        self.assertEqual(self.controller.state['phase'], 'error')

    def test_incompatible_result_cannot_offer_or_emit_an_installer(self):
        """旧检查结果或下载回调不能绕过控制器的平台限制"""
        emitted = []
        self.controller.installerReady.connect(emitted.append)
        self.controller.release = replace(self.animation, kind='program')
        self.controller.install_requested = True
        for selected, value in ((None, self.controller.release), (self.controller.release, '/unused/setup.exe')):
            self.controller.job = SimpleNamespace(release=selected)
            self.controller._result(value)
            self.assertEqual(self.controller.state['phase'], 'error')
            self.assertFalse(self.controller.install_requested)
        self.controller.job = None
        self.assertEqual(emitted, [])

    def test_compatible_animation_download_and_actual_minimum_version(self):
        """动画可单独暂存，下载与回退都使用实际程序版本检查最低要求"""
        self.controller.release = self.animation
        with patch.object(self.controller, '_bind') as bind:
            self.assertTrue(self.controller.download_install())
        job = bind.call_args.args[0]
        self.assertEqual(job.program_version, '1.3.0')
        values = []
        job.result.connect(values.append)
        job.release = replace(self.animation, animation_catalog={'synthetic': True})
        with patch('animation_updates.stage', return_value={'ready': True}) as stage, patch('update_controller.stage_installer') as program:
            job.run()
        stage.assert_called_once()
        program.assert_not_called()
        self.assertEqual(values, [{'ready': True}])
        errors = []
        job.failed.connect(lambda phase, message: errors.append(message))
        job.release = replace(job.release, minimum_program_version='1.4.0')
        with patch('animation_updates.stage') as stage:
            job.run()
        stage.assert_not_called()
        self.assertIn('手动更新程序', errors[0])

    def test_install_management_and_cleanup_do_not_inspect_or_change_installations(self):
        """不支持的维护调用在读取 Windows 安装登记和生成清理任务之前返回"""
        pet = SimpleNamespace(say=Mock())
        with patch('installer.read_manifest') as read, patch('installation_cleanup.cleanup_plan') as plan, patch('process_launch.launch_own') as launch:
            DesktopPet.open_install_manager(pet)
            DesktopPet.cleanup_installations(pet)
        read.assert_not_called()
        plan.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(pet.say.call_count, 2)

    def test_maintenance_page_exposes_animation_and_data_only(self):
        """真实设置页保留数据操作、动画更新及 Linux 下载入口"""
        pet = PetStub()
        pet.updates = self.controller
        pet.open_install_manager = Mock()
        with ExitStack() as stack:
            stack.enter_context(patch('desktop_settings.autostart_enabled', return_value=False))
            stack.enter_context(patch('codex_startup.enabled', return_value=False))
            ui.install(stack)
            dialog = SettingsDialog(pet, embedded=True)
            self.assertNotIn('update_checks', dialog.fields)
            panel = dialog.update_panel
            self.assertEqual(panel.check.text(), '检查动画更新')
            titles = {b.text() for b in dialog.findChildren(QPushButton)}
            self.assertNotIn('程序位置与安装管理', titles)
            self.assertNotIn('清理历史版本与备份（先预览）', titles)
            self.assertIn('备份设置（不含密钥与对话）', titles)
            link = dialog.findChild(QPushButton, 'linux_program_download')
            with patch('linux_app.ui.QDesktopServices.openUrl') as open_url:
                link.click()
            self.assertEqual(open_url.call_args.args[0].toString(), 'https://github.com/helantianshen/codex-bailong-desktop-pet/releases')
            self.controller.publish(phase='available', latest='1.3.1', package_kind='program')
            self.assertTrue(panel.install.isHidden())
            self.assertFalse(panel.install.isEnabled())
            self.controller.publish(package_kind='animation')
            self.assertFalse(panel.install.isHidden())
            self.assertEqual(panel.install.text(), '下载动画')
