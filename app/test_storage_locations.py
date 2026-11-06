"""Isolated migration integrity, custom locations and recovery boundaries."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import storage_locations as locations

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(self.root/'user')});self.env.start()
        self.source=self.root/'old';self.source.mkdir();(self.source/'nested').mkdir();(self.source/'nested/a.bin').write_bytes(b'animation')
        self.target=self.root/'new'
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_verified_copy_preserves_source_until_explicit_cleanup(self):
        plan=locations.copy_tree(self.source,self.target,'materials')
        self.assertEqual((self.target/'nested/a.bin').read_bytes(),b'animation')
        self.assertTrue((self.source/'nested/a.bin').exists())
        self.assertTrue(locations.clean_source(plan));self.assertFalse(self.source.exists())
    @unittest.skipUnless(locations.sys.platform=='win32','Windows registry data binding')
    def test_managed_launch_uses_registered_data_before_creating_settings(self):
        import winreg
        install=self.root/'apps/BailongEnhanced';exe=install/'versions/1.17.0-test/BailongEnhanced.exe'
        bound=self.root/'package-cache/Local/BailongEnhanced';bound.mkdir(parents=True)
        (bound/'settings.json').write_text('{"theme":"starfield"}')
        old=locations.data_dir();key=Mock();key.__enter__=Mock(return_value=key);key.__exit__=Mock(return_value=False)
        values={'InstallLocation':str(install),'DataLocation':str(bound)}
        with patch.object(locations.sys,'frozen',True,create=True),patch.object(locations.sys,'executable',str(exe)),patch.object(winreg,'OpenKey',return_value=key),patch.object(winreg,'QueryValueEx',side_effect=lambda k,n:(values[n],winreg.REG_SZ)),patch.dict(os.environ,{'BAILONG_ISOLATED':'0'}):
            self.assertEqual(locations.configure_data_environment(),bound)
            self.assertEqual(locations.data_dir(),bound)
            self.assertEqual(json.loads((locations.data_dir()/'settings.json').read_text())['theme'],'starfield')
            self.assertFalse(old.exists())
    @unittest.skipUnless(locations.sys.platform=='win32','Windows registry data binding')
    def test_data_binding_does_not_override_unrelated_install_or_isolated_probe(self):
        import winreg
        install=self.root/'apps/BailongEnhanced';exe=install/'versions/1.17.0-test/BailongEnhanced.exe'
        key=Mock();key.__enter__=Mock(return_value=key);key.__exit__=Mock(return_value=False)
        values={'InstallLocation':str(install),'DataLocation':str(self.root/'bound/BailongEnhanced')}
        before=locations.data_dir()
        with patch.object(locations.sys,'frozen',True,create=True),patch.object(locations.sys,'executable',str(exe)),patch.object(winreg,'OpenKey',return_value=key),patch.object(winreg,'QueryValueEx',side_effect=lambda k,n:(values[n],winreg.REG_SZ)):
            with patch.dict(os.environ,{'BAILONG_ISOLATED':'1'}):self.assertIsNone(locations.configure_data_environment())
            self.assertEqual(locations.data_dir(),before)
            with patch.dict(os.environ,{'BAILONG_ISOLATED':'0'}):
                for changed in ({'InstallLocation':str(self.root/'other/BailongEnhanced')},{'DataLocation':str(self.root/'unrelated')},{'DataLocation':'relative/BailongEnhanced'}):
                    earlier=dict(values);values.update(changed)
                    self.assertIsNone(locations.configure_data_environment());self.assertEqual(locations.data_dir(),before)
                    values.clear();values.update(earlier)
    def test_source_change_prevents_deleting_changed_file(self):
        plan=locations.copy_tree(self.source,self.target,'materials');(self.source/'nested/a.bin').write_bytes(b'new data')
        with self.assertRaises(OSError):locations.clean_source(plan)
        self.assertEqual((self.source/'nested/a.bin').read_bytes(),b'new data')
    def test_unknown_source_files_are_retained(self):
        plan=locations.copy_tree(self.source,self.target,'materials');(self.source/'private.txt').write_text('keep')
        self.assertFalse(locations.clean_source(plan));self.assertEqual((self.source/'private.txt').read_text(),'keep')
    def test_nonempty_unmanaged_and_overlapping_destinations_are_rejected(self):
        self.target.mkdir();(self.target/'unrelated').write_text('keep')
        for target in (self.target,self.source,self.source/'child',self.root):
            with self.subTest(target=target),self.assertRaises(ValueError):locations.destination(target,'materials',self.source)
    def test_cancelled_copy_does_not_remove_source(self):
        with self.assertRaises(InterruptedError):locations.copy_tree(self.source,self.target,'materials',cancel=lambda:True)
        self.assertTrue((self.source/'nested/a.bin').is_file())
    def test_hardlinks_remain_shared_in_destination(self):
        os.link(self.source/'nested/a.bin',self.source/'alias.bin')
        locations.copy_tree(self.source,self.target,'program')
        self.assertEqual((self.target/'alias.bin').stat().st_ino,(self.target/'nested/a.bin').stat().st_ino)
    def test_tampered_cleanup_paths_are_rejected(self):
        plan=locations.copy_tree(self.source,self.target,'materials');outside=self.root/'outside';outside.mkdir()
        plan['directories'].insert(0,'../outside')
        with self.assertRaises(ValueError):locations.clean_source(plan)
        self.assertTrue(outside.exists())
    def test_material_location_persists_and_unavailable_path_does_not_fall_back(self):
        state=self.root/'state';state.mkdir();external=self.root/'other-volume/BailongMaterials'
        locations.save_material_root(state,external)
        self.assertEqual(locations.material_root(state),external)
        self.assertFalse(external.exists())
    def test_install_discovery_uses_registered_directory_and_running_version(self):
        self.isolated=patch.dict(os.environ,BAILONG_ISOLATED='0');self.isolated.start();self.addCleanup(self.isolated.stop)
        custom=self.root/'D/Apps/BailongEnhanced'
        with patch.object(locations,'registered_install_root',return_value=custom):self.assertEqual(locations.install_root(),custom)
        exe=custom/'versions/1.1.0-time/BailongEnhanced.exe'
        with patch('sys.frozen',True,create=True),patch('sys.executable',str(exe)),patch.object(locations,'registered_install_root',return_value=self.source):
            self.assertEqual(locations.install_root(),custom)
    def test_explicit_isolation_overrides_registry_and_running_install(self):
        with patch.dict(os.environ,BAILONG_ISOLATED='1'),patch('sys.frozen',True,create=True),patch('sys.executable',str(self.root/'real/versions/1.0.0/BailongEnhanced.exe')),patch.object(locations,'registered_install_root',return_value=self.source):
            self.assertEqual(locations.install_root(),locations.data_dir().parent/'Programs/BailongEnhanced')
    def test_progress_accepts_caches_larger_than_two_gigabytes(self):
        from material_controller import MaterialMoveJob
        job=MaterialMoveJob(self.source,self.target);seen=[]
        job.progress.connect(lambda n,total,phase:seen.append((n,total)))
        size=3*1024**3;job.progress.emit(size,size,'moving')
        self.assertEqual(seen,[(size,size)])
    def test_registered_location_is_bound_to_the_same_user_data_environment(self):
        import winreg
        key=Mock();key.__enter__=Mock(return_value=key);key.__exit__=Mock(return_value=False)
        custom=self.root/'apps/BailongEnhanced'
        values={'InstallLocation':str(custom),'DataLocation':str(self.root/'different-user/BailongEnhanced')}
        with patch.object(winreg,'OpenKey',return_value=key),patch.object(winreg,'QueryValueEx',side_effect=lambda k,n:(values[n],winreg.REG_SZ)):
            self.assertIsNone(locations.registered_install_root())
            values['DataLocation']=str(locations.data_dir())
            self.assertEqual(locations.registered_install_root(),custom)
    def test_legacy_registry_cannot_escape_an_isolated_localappdata(self):
        import winreg
        key=Mock();key.__enter__=Mock(return_value=key);key.__exit__=Mock(return_value=False)
        other=self.root/'real-user/Programs/BailongEnhanced'
        def query(k,n):
            if n=='DataLocation':raise FileNotFoundError()
            return str(other),winreg.REG_SZ
        with patch.object(winreg,'OpenKey',return_value=key),patch.object(winreg,'QueryValueEx',side_effect=query):
            self.assertIsNone(locations.registered_install_root())
            other=locations.data_dir().parent/'Programs/BailongEnhanced'
            self.assertEqual(locations.registered_install_root(),other)

class ProgramMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve()
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(self.base/'user')});self.env.start()
        self.source=self.base/'old/BailongEnhanced';self.target=self.base/'new/BailongEnhanced'
        self.name='1.1.0-before';folder=self.source/'versions'/self.name;folder.mkdir(parents=True)
        (folder/'BailongEnhanced.exe').write_bytes(b'exe');(folder/'白龙安装管理.exe').write_bytes(b'manager')
        (self.source/'installations.json').write_text(json.dumps({'current':self.name,'versions':[self.name]}))
        self.old=folder/'BailongEnhanced.exe'
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_program_migration_registers_new_path_only_after_ready(self):
        from program_location import move_program
        events=[]
        with patch('installer.stop_existing',return_value=self.old),patch('installer.register',side_effect=lambda *a:events.append('register')) as register,patch('deployment_state.capture_entries',return_value={}),patch('deployment_state.wait_ready',side_effect=lambda *a:events.append('ready')),patch('program_location.subprocess.Popen',return_value=Mock(pid=123)):
            exe=move_program(self.source,self.target,False)
        self.assertEqual(events,['ready','register']);self.assertEqual(exe.parent.parent.parent,self.target)
        self.assertEqual(register.call_args.args[0],exe);self.assertTrue(self.old.exists())
        self.assertTrue((self.target/'location-migration.json').is_file())
    def test_failed_registration_restores_entries_and_restarts_old_program(self):
        from program_location import move_program
        with patch('installer.stop_existing',return_value=self.old),patch('installer.register',side_effect=OSError('registry refused')),patch('deployment_state.capture_entries',return_value={'old':True}),patch('deployment_state.restore_entries') as restore,patch('deployment_state.wait_ready'),patch('deployment_state.stop_version'),patch('program_location.subprocess.Popen',return_value=Mock(pid=123)) as launch:
            with self.assertRaises(OSError):move_program(self.source,self.target,False)
        restore.assert_called_once_with(self.source,{'old':True},True)
        self.assertEqual(launch.call_args.args[0],[str(self.old)]);self.assertTrue(self.old.exists())

    def test_migration_uses_the_actual_startup_receipt_contract(self):
        from program_location import move_program
        from deployment_state import write_ready_receipt,wait_ready
        # Exercise the producer and consumer together instead of mocking the
        # readiness check, which concealed the installation-root path mismatch.
        def launch(args,**kwargs):
            process=Mock(pid=os.getpid());process.poll.return_value=None
            if len(args)==1:
                receipt=Path(kwargs['env']['BAILONG_DEPLOY_RECEIPT'])
                self.assertEqual(receipt.parent,Path(args[0]).parent)
                with patch.dict(os.environ,kwargs['env']),patch('sys.executable',args[0]),patch('desktop_core.VERSION','1.1.0'):
                    write_ready_receipt(Mock(winId=lambda:1),Mock(isListening=lambda:True))
                self.assertTrue(receipt.is_file())
            return process
        def ready(*args):return wait_ready(*args,timeout=.5,stable_seconds=0)
        with patch('installer.stop_existing',return_value=self.old),patch('installer.register'),patch('deployment_state.capture_entries',return_value={}),patch('deployment_state.wait_ready',side_effect=ready),patch('program_location.subprocess.Popen',side_effect=launch):
            exe=move_program(self.source,self.target,False)
        self.assertEqual(exe.parent.parent.parent,self.target)
        self.assertFalse(list(exe.parent.glob('.ready-*.json')))
        self.assertTrue(self.old.is_file())

if __name__=='__main__':unittest.main()
