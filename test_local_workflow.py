"""Exercise the actual local orchestrator without launching or stopping any pet."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import build_local as local

class LocalWorkflowTests(unittest.TestCase):
    def test_versioned_material_catalog_preserves_verified_release_urls(self):
        from build_materials import retain_publication_catalog
        from animation_updates import validate_catalog
        from app_updates import UpdateError
        root=Path(__file__).resolve().parent
        catalog=json.loads((root/'app/material_catalog.json').read_text(encoding='utf-8'))
        published=copy.deepcopy(catalog);published['releaseVersion']='1.3.0'
        for name,tier in published['tiers'].items():
            tier.update(url=f'https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/v1.3.0/bailong-desktop-pet-1.3.0-animation-{name}.zip',archiveBytes=1024,archiveSha256='a'*64)
        validate_catalog(published,'1.3.0')
        self.assertEqual(retain_publication_catalog(catalog,published),published)
        self.assertIs(retain_publication_catalog(catalog,dict(catalog,releaseVersion=None)),catalog)
        changed=copy.deepcopy(catalog);changed['tiers']['light']['files'][0]['bytes']+=1
        with self.assertRaises(ValueError):retain_publication_catalog(changed,published)
        unsafe=copy.deepcopy(published);unsafe['tiers']['hd']['url']='https://example.com/assets.zip'
        with self.assertRaises(UpdateError):retain_publication_catalog(catalog,unsafe)

    def test_safe_print_escapes_text_for_legacy_console_encodings(self):
        class AsciiConsole:
            encoding='ascii'
            def __init__(self):self.value=''
            def write(self,text):
                text.encode('ascii')
                self.value+=text
                return len(text)
            def flush(self):pass
        console=AsciiConsole()
        with patch('sys.stdout',console):local.safe_print('构建应用目录')
        self.assertIn(r'\u6784\u5efa',console.value)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'app').mkdir();(self.root/'app/example.py').write_text('answer=42')
        (self.root/'app/tray_host.cs').write_text('// fixed tray source fixture')
        (self.root/'build_tray_host.py').write_text('# tray compiler fixture')
        self.stage=self.root/'release/BailongEnhanced';self.stage.mkdir(parents=True);(self.stage/'BailongEnhanced.exe').write_bytes(b'compiled-placeholder')
        self.proof=dict(version=local.VERSION,executableSha256=local.sha(self.stage/'BailongEnhanced.exe'),tlsRuntime=dict(passed=True,certificateVerification=True,hostnameVerification=True,offline=True))
        self.patch=patch.object(local,'ROOT',self.root);self.patch.start()
        receipt=self.root/'本地实装/回归验收/current-regressions.json';receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps(dict(passed=True,scope='full',expectedModules=['test_local_workflow','test_release_retention','test_release_version'],modules=3,tests=1,sourceHashes=local.source_hashes())),encoding='utf-8')
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_acceptance_only_allows_a_matching_same_screen_activity_home_move(self):
        home=dict(screen='screen',rx=.2,ry=.3);new=dict(screen='screen',rx=.6,ry=.7)
        before=dict(theme='cyber',wander_home=home,screen_position=home)
        after=dict(before,wander_home=new,screen_position=new)
        self.assertEqual(local.settings_differences(before,after),[])
        self.assertEqual(local.settings_differences(before,dict(after,theme='bailong')),['theme'])
        self.assertIn('wander_home',local.settings_differences(before,dict(before,wander_home=new)))
        self.assertIn('wander_home',local.settings_differences(before,dict(after,wander_home=dict(new,rx=1.5))))

    def test_verified_local_deploy_has_lock_ready_validation_and_no_package_command(self):
        lock=Mock();lock.tryLock.return_value=True
        result=dict(current='new',previous='old',backup='backup',executable='new.exe')
        with patch('PySide6.QtCore.QLockFile',return_value=lock),patch('installer.DATA',self.root/'user-data'),patch('installer.startup_preference',return_value=False),patch('directory_deploy.deploy_directory',return_value=result) as deploy,patch.object(local,'verify_installed',return_value=dict(passed=True)) as verify:
            self.assertEqual(local.install_verified(self.proof,self.stage),0)
        deploy.assert_called_once_with(self.stage,False);verify.assert_called_once_with(result);lock.unlock.assert_called_once()
        report=local.read(self.root/'本地实装/最终验收.json');self.assertEqual(report['regression']['tests'],1)
    def test_existing_same_version_package_does_not_fail_after_deploy(self):
        (self.root/'release'/('old-'+local.VERSION+'.zip')).write_bytes(b'previous')
        lock=Mock();lock.tryLock.return_value=True
        result=dict(current='new',previous='old',backup='backup',executable='new.exe')
        with patch('PySide6.QtCore.QLockFile',return_value=lock),patch('installer.DATA',self.root/'user-data'),patch('installer.startup_preference',return_value=False),patch('directory_deploy.deploy_directory',return_value=result),patch.object(local,'verify_installed',return_value=dict(passed=True)):
            self.assertEqual(local.install_verified(self.proof,self.stage),0)
    def test_targeted_receipt_cannot_authorize_deploy(self):
        path=self.root/'本地实装/回归验收/current-regressions.json';value=local.read(path);value['scope']='targeted';path.write_text(json.dumps(value),encoding='utf8')
        with patch('directory_deploy.deploy_directory') as deploy,self.assertRaises(ValueError):local.install_verified(self.proof,self.stage)
        deploy.assert_not_called()
    def test_unknown_test_module_cannot_write_full_receipt(self):
        import subprocess,sys
        real=Path(__file__).parent
        result=subprocess.run([sys.executable,str(real/'quality_check.py'),'audit-invalid','nonexistent_test_module'],cwd=real,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Unknown test modules',result.stdout+result.stderr)
    def test_changed_source_or_lock_collision_prevents_deploy(self):
        (self.root/'app/example.py').write_text('answer=43')
        with patch('directory_deploy.deploy_directory') as deploy,self.assertRaises(ValueError):local.install_verified(self.proof,self.stage)
        deploy.assert_not_called()
    def test_deploy_verified_rejects_changed_executable_before_stop_or_build(self):
        path=self.root/'本地实装/构建验收.json';path.write_text(json.dumps(self.proof))
        (self.stage/'BailongEnhanced.exe').write_bytes(b'changed')
        lock=Mock();lock.tryLock.return_value=True
        with patch('PySide6.QtCore.QLockFile',return_value=lock),patch.object(local,'verify_code'),patch.object(local,'install_verified') as install,patch.object(local.subprocess,'run') as build,self.assertRaises(ValueError):local.main(['--deploy-verified'])
        build.assert_not_called();install.assert_not_called()
    def test_default_build_calls_application_only_and_preserves_verified_handoff(self):
        plan=local.validation_plan(['test_local_workflow'])
        with patch.object(local.subprocess,'run') as run,patch.object(local,'verify_code',return_value=dict(passed=True)),patch.object(local,'verify_tls_runtime',return_value=self.proof['tlsRuntime']) as tls,patch.object(local,'native_matrix',return_value=[]) as native,patch.object(local,'snapshot_source',return_value=self.root/'snapshot'),patch.object(local,'install_verified',return_value=0) as deploy:
            self.assertEqual(local.build_and_deploy(SimpleNamespace(build_only=False,validation=plan)),0)
        tls.assert_not_called();native.assert_not_called()
        command=run.call_args.args[0];self.assertEqual(Path(command[1]).name,'build_release.py');self.assertNotIn('--package',command)
        self.assertEqual(deploy.call_args.args[0]['executableSha256'],local.sha(self.stage/'BailongEnhanced.exe'))
        self.assertFalse(deploy.call_args.args[0]['fullInstallerGenerated'])
        self.assertEqual(deploy.call_args.args[0]['validation']['mode'],'targeted')
    def test_targeted_scope_can_deploy_only_with_the_matching_plan_and_sources(self):
        plan=local.validation_plan(['test_local_workflow'])
        receipt=local.read(self.root/'本地实装/回归验收/current-regressions.json')
        receipt.update(scope='targeted',modules=1,records=[dict(module='test_local_workflow',returncode=0,tests=1)])
        self.assertEqual(local.validate_regression(receipt,plan),plan)
        with self.assertRaises(ValueError):local.validate_regression(receipt)
        with self.assertRaises(ValueError):local.validate_regression(receipt,local.validation_plan(['test_release_version']))
        receipt['sourceHashes']={}
        with self.assertRaises(ValueError):local.validate_regression(receipt,plan)
    def test_local_scope_is_explicit_and_full_checks_are_for_release(self):
        with self.assertRaises(ValueError):local.validation_plan([])
        with self.assertRaises(ValueError):local.validation_plan(['unknown'])
        plan=local.validation_plan(['test_local_workflow'])
        self.assertFalse(plan['tls']);self.assertFalse(plan['native'])
        release=local.validation_plan(release=True)
        self.assertEqual(release['modules'],local.expected_tests());self.assertTrue(release['tls']);self.assertTrue(release['native'])
    def test_release_gate_rejects_a_stale_receipt(self):
        with patch.object(local,'validate_regression') as validate:
            local.require_release_regression();validate.assert_called_once()
    def test_local_command_runs_only_declared_modules(self):
        lock=Mock();lock.tryLock.return_value=True
        with patch('PySide6.QtCore.QLockFile',return_value=lock),patch.object(local.subprocess,'run') as run,patch.object(local,'build_and_deploy',return_value=0) as build:
            self.assertEqual(local.main(['--build-only','--tests','test_local_workflow']),0)
        self.assertEqual(run.call_args.args[0][2:],['current','test_local_workflow'])
        self.assertEqual(build.call_args.args[0].validation['mode'],'targeted')
    def test_missing_frozen_tls_proof_cannot_authorize_deploy(self):
        del self.proof['tlsRuntime']
        with patch('directory_deploy.deploy_directory') as deploy,self.assertRaisesRegex(ValueError,'TLS'):local.install_verified(self.proof,self.stage)
        deploy.assert_not_called()
    def test_ssl_runtime_data_is_bundled_and_missing_required_file_stops_build(self):
        from build_release import ssl_runtime_data
        module=self.root/'ssl.py';module.write_text("file='codex-rejected-cas.pem'")
        with self.assertRaises(OSError):ssl_runtime_data(module)
        pem=module.with_name('codex-rejected-cas.pem');pem.write_bytes(b'public certificate data')
        self.assertEqual(ssl_runtime_data(module),['--add-data',str(pem)+';.'])
        pem.unlink();module.write_text('standard ssl implementation');self.assertEqual(ssl_runtime_data(module),[])

if __name__=='__main__':unittest.main()
