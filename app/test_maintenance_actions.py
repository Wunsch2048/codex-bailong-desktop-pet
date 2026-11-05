"""Maintenance buttons use the installed main EXE and report I/O failures."""
import os,json,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from desktop import DesktopPet
APP=QApplication.instance() or QApplication([])

class MaintenanceActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.state=self.root/'data';self.state.mkdir();self.config=self.state/'settings.json'
        self.values={'bubble_mode':'minimal','theme':'nightcity','capsule_action':'website','capsule_website':'https://example.org/'}
        self.config.write_text(json.dumps(self.values),encoding='utf-8')
        (self.state/'runtime.json').write_text('{"sample":true}',encoding='utf-8')
        self.pet=SimpleNamespace(settings_dialog=None,say=Mock(),record_state=Mock(),save_settings=Mock(),
            manifest={'idle':{'id':'idle'}},decode_error=None,settings={},roaming=SimpleNamespace(queue=[]))
        self.patches=[patch('desktop.STATE_DIR',self.state),patch('desktop.CONFIG',self.config),
            patch('desktop.ROOT',self.root/'read-only-program'),patch('desktop.QMessageBox.warning')]
        for item in self.patches:item.start()
        import desktop
        self.warning=desktop.QMessageBox.warning
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.tmp.cleanup()
    def manager(self,current='current'):
        folder=self.root/'install/versions/current';folder.mkdir(parents=True,exist_ok=True)
        (folder/'BailongEnhanced.exe').write_bytes(b'not-executable fixture')
        return folder,patch('storage_locations.install_root',return_value=self.root/'install'),patch('installer.read_manifest',return_value={'current':current})
    def test_manager_uses_main_exe_without_legacy_copy(self):
        folder,a,b=self.manager()
        with a,b,patch('process_launch.launch_own') as launch:DesktopPet.open_install_manager(self.pet)
        launch.assert_called_once_with([str(folder/'BailongEnhanced.exe'),'--manage'],cwd=folder,creationflags=0x08000000)
        self.assertFalse((folder/'白龙安装管理.exe').exists());self.warning.assert_not_called()
    def test_manager_rejects_paths_outside_managed_versions(self):
        for name in ('../outside','../../outside',''):
            folder,a,b=self.manager(name)
            with a,b,patch('process_launch.launch_own') as launch:DesktopPet.open_install_manager(self.pet)
            launch.assert_not_called()
        self.assertEqual(self.warning.call_count,3)
    def test_manager_launch_failure_is_reported(self):
        folder,a,b=self.manager()
        with a,b,patch('process_launch.launch_own',side_effect=OSError('blocked')):DesktopPet.open_install_manager(self.pet)
        self.assertIn('blocked',self.warning.call_args.args[2])
    def test_non_windows_manager_does_not_launch_windows_program(self):
        with patch('desktop.sys.platform','linux'),patch('process_launch.launch_own') as launch:DesktopPet.open_install_manager(self.pet)
        launch.assert_not_called();self.warning.assert_called_once()
    def test_diagnostics_export_uses_writable_user_directory(self):
        path=DesktopPet.export_diagnostics(self.pet)
        self.assertEqual(path.parent,self.state/'diagnostics');self.assertTrue(json.loads(path.read_text())['sample'])
        self.assertFalse((self.root/'read-only-program').exists());self.warning.assert_not_called()
    def test_diagnostics_record_failure_is_reported(self):
        self.pet.record_state.side_effect=PermissionError('locked')
        self.assertIsNone(DesktopPet.export_diagnostics(self.pet));self.warning.assert_called_once();self.pet.say.assert_not_called()
    def test_diagnostics_write_failure_is_reported(self):
        with patch('desktop.atomic_json',side_effect=PermissionError('disk full')):
            self.assertIsNone(DesktopPet.export_diagnostics(self.pet))
        self.warning.assert_called_once();self.pet.say.assert_not_called()
    def test_diagnostics_invalid_snapshot_is_reported(self):
        (self.state/'runtime.json').write_text('[]')
        self.assertIsNone(DesktopPet.export_diagnostics(self.pet));self.warning.assert_called_once()
    def test_settings_backup_preserves_saved_preferences(self):
        before=self.config.read_bytes();path=DesktopPet.backup_settings(self.pet)
        self.assertEqual(json.loads(path.read_text()),self.values);self.assertEqual(self.config.read_bytes(),before)
        self.warning.assert_not_called()
    def test_settings_save_failure_stops_backup(self):
        self.pet.save_settings.side_effect=PermissionError('save blocked')
        self.assertIsNone(DesktopPet.backup_settings(self.pet));self.assertFalse(list(self.state.glob('settings-backup-*')))
        self.warning.assert_called_once();self.pet.say.assert_not_called()
    def test_settings_backup_write_failure_is_reported(self):
        with patch('desktop.atomic_json',side_effect=PermissionError('write blocked')):
            self.assertIsNone(DesktopPet.backup_settings(self.pet))
        self.warning.assert_called_once();self.pet.say.assert_not_called()
    def test_restore_does_not_continue_without_backup(self):
        self.pet.backup_settings=Mock(return_value=None);self.pet.apply_settings=Mock()
        with patch('desktop.QFileDialog.getOpenFileName',return_value=(str(self.config),'')):
            DesktopPet.restore_settings(self.pet)
        self.pet.backup_settings.assert_called_once();self.pet.apply_settings.assert_not_called()
    def test_open_data_reports_file_manager_failure(self):
        with patch('desktop.QDesktopServices.openUrl',return_value=False):self.assertFalse(DesktopPet.open_data(self.pet))
        self.warning.assert_called_once()
    def test_open_data_success_uses_current_user_directory(self):
        with patch('desktop.QDesktopServices.openUrl',return_value=True) as opened:self.assertTrue(DesktopPet.open_data(self.pet))
        self.assertEqual(Path(opened.call_args.args[0].toLocalFile()).resolve(),self.state);self.warning.assert_not_called()

if __name__=='__main__':unittest.main()
