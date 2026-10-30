import os,sys,unittest,ctypes
from pathlib import Path
from unittest.mock import patch,Mock
from process_launch import own_environment,launch_own,clean_dll_search

class LaunchTests(unittest.TestCase):
    def test_first_upgrade_repairs_legacy_parent_qt_plugin_paths(self):
        from process_launch import configure_frozen_qt
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(Path.cwd()/'new-runtime'),create=True),patch.dict(os.environ,{'QT_QPA_PLATFORM_PLUGIN_PATH':'old-runtime','QT_PLUGIN_PATH':'old-runtime'}),patch('PySide6.QtCore.QCoreApplication.setLibraryPaths') as set_paths:
            configure_frozen_qt()
            self.assertNotIn('QT_QPA_PLATFORM_PLUGIN_PATH',os.environ)
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
