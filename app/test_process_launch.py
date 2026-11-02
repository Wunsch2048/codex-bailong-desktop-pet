import os,sys,unittest,ctypes
from pathlib import Path
from unittest.mock import patch,Mock
from process_launch import own_environment,launch_own,clean_dll_search

class LaunchTests(unittest.TestCase):
    def test_explicit_environment_removals_apply_after_inherited_overlay_merge(self):
        with patch.dict(os.environ,BAILONG_DEPLOY_TOKEN='test-nonce',BAILONG_DEPLOY_RECEIPT='test-receipt'),patch('subprocess.Popen') as start:
            launch_own(['pet.exe'],env={'LOCALAPPDATA':'same-user'},remove_environment=('BAILONG_DEPLOY_TOKEN','BAILONG_DEPLOY_RECEIPT'))
        env=start.call_args.kwargs['env']
        self.assertFalse('BAILONG_DEPLOY_TOKEN' in env,'交接参数不能因环境合并而恢复')
        self.assertFalse('BAILONG_DEPLOY_RECEIPT' in env,'交接回执不能因环境合并而恢复')
        self.assertEqual(env['LOCALAPPDATA'],'same-user')
    @unittest.skipUnless(sys.platform=='win32','Windows job policy')
    def test_independent_flags_respect_host_breakaway_policy(self):
        from process_launch import independent_creationflags
        for policy,success,expected in ((0x2800,True,0x09000000),(0x2000,True,0x08000000),(0x1000,True,0x08000000),(0,False,0x08000000)):
            api=Mock()
            def query(handle,kind,pointer,size,returned):
                self.assertEqual(kind,2);pointer._obj.flags=policy;return success
            api.QueryInformationJobObject.side_effect=query
            with self.subTest(policy=policy,success=success),patch('ctypes.WinDLL',return_value=api):
                self.assertEqual(independent_creationflags(0x08000000),expected)
    def test_codex_listener_launch_is_independent_and_drops_install_nonce(self):
        """监听独立启动且不继承安装交接参数，失败时不输出完整环境"""
        import codex_startup
        with patch.dict(os.environ,BAILONG_DEPLOY_TOKEN='test-nonce',BAILONG_DEPLOY_RECEIPT='test-receipt'),patch('process_launch.launch_own') as start:
            codex_startup.spawn(['pet.exe','--watch-codex'])
        self.assertTrue(start.call_args.kwargs['independent'])
        for key in ('BAILONG_DEPLOY_TOKEN','BAILONG_DEPLOY_RECEIPT'):
            self.assertFalse(key in start.call_args.kwargs['env'],key)
    def test_independent_launch_preserves_existing_flags_and_environment(self):
        with patch('process_launch.independent_creationflags',return_value=0x09000000) as flags,patch('subprocess.Popen') as start:
            launch_own(['pet.exe','--watch-codex'],independent=True,creationflags=0x08000000)
        flags.assert_called_once_with(0x08000000)
        self.assertEqual(start.call_args.kwargs['creationflags'],0x09000000)
        self.assertEqual(start.call_args.args[0],['pet.exe','--watch-codex'])
    def test_regular_child_does_not_request_independent_lifetime(self):
        with patch('process_launch.independent_creationflags') as flags,patch('subprocess.Popen'):
            launch_own(['helper.exe'],creationflags=0x08000000)
        flags.assert_not_called()
    def test_first_upgrade_repairs_legacy_parent_qt_plugin_paths(self):
        """Windows 冻结环境必须移除旧 Qt 插件路径，失败只报告变量名"""
        from process_launch import configure_frozen_qt
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(Path.cwd()/'new-runtime'),create=True),patch.dict(os.environ,{'QT_QPA_PLATFORM_PLUGIN_PATH':'old-runtime','QT_PLUGIN_PATH':'old-runtime'}),patch('PySide6.QtCore.QCoreApplication.setLibraryPaths') as set_paths:
            configure_frozen_qt()
            self.assertFalse('QT_QPA_PLATFORM_PLUGIN_PATH' in os.environ,'QT_QPA_PLATFORM_PLUGIN_PATH')
            self.assertEqual(os.environ['QT_PLUGIN_PATH'],str(Path(sys._MEIPASS)/'PySide6/plugins'))
            set_paths.assert_called_once_with([os.environ['QT_PLUGIN_PATH']])
    def test_clean_environment_does_not_drop_account_network_or_receipt(self):
        old=str(Path.cwd()/'old-runtime')
        source={'QT_PLUGIN_PATH':old,'qt_qpa_platform_plugin_path':old,'QML2_IMPORT_PATH':old,
                'PATH':os.pathsep.join((old,str(Path(old)/'bin'),r'C:\Windows\System32')),
                'LOCALAPPDATA':'original-data','HTTPS_PROXY':'original-proxy','QT_SCALE_FACTOR':'1.5'}
        with patch.dict(os.environ,source,clear=True),patch.object(sys,'_MEIPASS',old,create=True):
            result=own_environment({'BAILONG_DEPLOY_TOKEN':'nonce'})
            self.assertNotIn('QT_PLUGIN_PATH',result);self.assertNotIn('qt_qpa_platform_plugin_path',result)
            self.assertEqual(result['PATH'],r'C:\Windows\System32');self.assertEqual(result['HTTPS_PROXY'],'original-proxy')
            self.assertEqual(result['LOCALAPPDATA'],'original-data');self.assertEqual(result['QT_SCALE_FACTOR'],'1.5')
            self.assertEqual(result['BAILONG_DEPLOY_TOKEN'],'nonce');self.assertEqual(result['PYINSTALLER_RESET_ENVIRONMENT'],'1')
            self.assertEqual(os.environ['QT_PLUGIN_PATH'],old)
    def api(self):
        api=Mock()
        def get(size,buffer):
            text=r'C:\actual-parent-dll'
            if buffer is not None:buffer.value=text
            return len(text)
        api.GetDllDirectoryW.side_effect=get;api.SetDllDirectoryW.return_value=1
        return api
    def test_actual_dll_directory_is_restored_even_when_launch_fails(self):
        api=self.api()
        with patch.object(sys,'frozen',True,create=True),patch('ctypes.windll.kernel32',api):
            with self.assertRaisesRegex(OSError,'launch failed'):
                with clean_dll_search():raise OSError('launch failed')
        self.assertEqual([c.args for c in api.SetDllDirectoryW.call_args_list],[(None,),(r'C:\actual-parent-dll',)])
    def test_dll_directory_brackets_createprocess_and_preserves_arguments(self):
        api=self.api();order=[];api.SetDllDirectoryW.side_effect=lambda value:order.append(value) or 1
        with patch.object(sys,'frozen',True,create=True),patch('ctypes.windll.kernel32',api),patch('subprocess.Popen',side_effect=lambda *a,**k:order.append('spawn') or Mock()) as launch:
            launch_own([r'C:\new\BailongEnhanced.exe','--apply-program-update'])
        self.assertEqual(order,[None,'spawn',r'C:\actual-parent-dll'])
        self.assertEqual(launch.call_args.args[0][1],'--apply-program-update')
        self.assertEqual(launch.call_args.kwargs['cwd'],r'C:\new')
    def test_native_crash_exit_code_is_reported(self):
        from deployment_state import wait_ready
        with self.assertRaisesRegex(OSError,'0xC0000005'):
            wait_ready(Mock(poll=lambda:-1073741819),Path('app.exe'),Path('absent-ready.json'),'nonce','1.7.1')
