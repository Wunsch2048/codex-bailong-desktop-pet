import os,json,tempfile,zipfile,hashlib,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import installer,deployment_state as state
from desktop_core import VERSION

class ManifestSafetyTests(unittest.TestCase):
    def test_only_missing_manifest_means_fresh_install(self):
        with patch.object(Path,'read_text',side_effect=FileNotFoundError):
            self.assertEqual(installer.read_manifest(Path('unused')),dict(current='',versions=[]))
        for source in (PermissionError(),'{broken','{"current":"","versions":[1]}'):
            read=Mock(side_effect=source if isinstance(source,Exception) else None,return_value=source)
            with self.subTest(source=source),patch.object(Path,'read_text',read):
                with self.assertRaisesRegex(OSError,'现有安装记录无法读取'):installer.read_manifest(Path('unused'))

    def test_unreadable_manifest_never_stops_existing_watcher(self):
        with patch.object(Path,'read_text',side_effect=PermissionError),patch('codex_startup.stop_watchers') as stop:
            with self.assertRaises(OSError):installer.stop_existing(Path('unused'))
        stop.assert_not_called()

class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.old=self.root/'versions/old/BailongEnhanced.exe';self.old.parent.mkdir(parents=True);self.old.write_bytes(b'old')
        installer.write_manifest(dict(current='old',versions=['old']),self.root)
        self.shortcut=self.root/'desktop.lnk';self.startup=self.root/'startup.vbs'
        self.shortcut.write_bytes(b'old-target');self.startup.write_bytes(b'old-startup');self.payload=self.root/'payload.zip'
        content=b'new';manifest=dict(version=VERSION,files={'BailongEnhanced.exe':dict(bytes=3,sha256=hashlib.sha256(content).hexdigest())})
        with zipfile.ZipFile(self.payload,'w') as z:z.writestr('BailongEnhanced.exe',content);z.writestr('payload-manifest.json',json.dumps(manifest))
        self.before={p:p.read_bytes() for p in (self.root/'installations.json',self.shortcut,self.startup)}
        self.real_registry_snapshot=state.registry_snapshot
        self.patches=[patch.object(installer,'ROOT',self.root),patch.object(state,'entry_paths',return_value=list(self.before)),patch.object(state,'registry_snapshot',return_value=None),patch('winreg.DeleteKey'),patch.object(state,'stop_version'),patch.object(installer,'register',side_effect=self.register)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def register(self,*args):self.shortcut.write_bytes(b'new-target');self.startup.write_bytes(b'new-startup')
    def restored(self):
        for p,data in self.before.items():self.assertEqual(p.read_bytes(),data)
        self.assertEqual([p.name for p in (self.root/'versions').iterdir()],['old']);self.assertFalse((self.root/'deployment-journal.json').exists())
    def test_receipt_before_entry_commit_and_success_retains_rollback(self):
        def ready(exe,journal):
            self.assertEqual(self.shortcut.read_bytes(),b'old-target');self.assertEqual(installer.read_manifest(self.root)['current'],'old')
        exe=installer.install(self.payload,self.root,before_commit=ready)
        self.assertEqual(installer.read_manifest(self.root)['current'],exe.parent.name);self.assertTrue(self.old.is_file());self.assertEqual(self.shortcut.read_bytes(),b'new-target')
    def test_startup_immediate_exit_restores_old_entries_and_directory(self):
        with self.assertRaises(OSError):installer.install(self.payload,self.root,before_commit=lambda *a:state.wait_ready(Mock(poll=lambda:1),a[0],self.root/'none','a'*32,VERSION,timeout=.1))
        self.restored()
    def test_partial_registration_failure_restores_shortcut_startup_and_manifest(self):
        def fail(*args):self.shortcut.write_bytes(b'broken-new-target');raise OSError('registration failed')
        with patch.object(installer,'register',side_effect=fail),self.assertRaises(OSError):installer.install(self.payload,self.root,before_commit=lambda *a:None)
        self.restored()
    def test_manifest_write_failure_compensates_completed_registration(self):
        with patch.object(installer,'write_manifest',side_effect=OSError('disk full')),self.assertRaises(OSError):installer.install(self.payload,self.root,before_commit=lambda *a:None)
        self.restored()
    def test_disk_full_during_extraction_keeps_old_entries_and_version(self):
        with patch.object(zipfile.ZipFile,'extractall',side_effect=OSError('disk full')),self.assertRaises(OSError):installer.install(self.payload,self.root)
        self.restored()
    def test_failed_commit_removes_only_new_unreferenced_shared_assets(self):
        data=b'asset';name='outputs/白龙桌宠素材/a.webp'
        with zipfile.ZipFile(self.payload) as z:exe=z.read('BailongEnhanced.exe')
        manifest=dict(version=VERSION,files={'BailongEnhanced.exe':dict(bytes=len(exe),sha256=hashlib.sha256(exe).hexdigest()),name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())})
        with zipfile.ZipFile(self.payload,'w') as z:z.writestr('BailongEnhanced.exe',exe);z.writestr(name,data);z.writestr('payload-manifest.json',json.dumps(manifest))
        with patch.object(installer,'write_manifest',side_effect=OSError('full')),self.assertRaises(OSError):installer.install(self.payload,self.root,before_commit=lambda *a:None)
        self.restored();self.assertEqual(list((self.root/'shared-assets').glob('*')),[])
    def test_corrupt_payload_is_rejected_before_entries_change(self):
        with zipfile.ZipFile(self.payload,'a') as z:z.writestr('BailongEnhanced.exe',b'corrupt')
        with self.assertRaises(ValueError):installer.install(self.payload,self.root)
        self.restored()
    def test_failed_compensation_keeps_journal_and_new_files_for_retry(self):
        with patch.object(installer,'register',side_effect=OSError('register')),patch.object(state,'restore_entries',side_effect=OSError('permission')),self.assertRaises(OSError):installer.install(self.payload,self.root,before_commit=lambda *a:None)
        self.assertTrue((self.root/'deployment-journal.json').is_file());self.assertEqual(len(list((self.root/'versions').iterdir())),2)
        state.recover(self.root,True);self.restored()
    def test_interrupted_install_recovers_entries_and_only_staged_new_version(self):
        snapshot=state.capture_entries(self.root,True);dest=self.root/'versions/interrupted';dest.mkdir();(dest/'BailongEnhanced.exe').write_bytes(b'new')
        state.atomic(self.root/'deployment-journal.json',dict(phase='prepared',new_version='interrupted',snapshot=snapshot))
        self.shortcut.write_bytes(b'new');installer.write_manifest(dict(current='interrupted',versions=['interrupted','old']),self.root)
        self.assertTrue(state.recover(self.root,True));self.restored()
    def test_interrupted_extraction_without_executable_is_recoverable(self):
        snapshot=state.capture_entries(self.root,True);dest=self.root/'versions/interrupted';dest.mkdir();(dest/'partial.tmp').write_bytes(b'partial')
        state.atomic(self.root/'deployment-journal.json',dict(phase='extracting',new_version='interrupted',snapshot=snapshot))
        self.assertTrue(state.recover(self.root,True));self.restored()
    def test_committed_journal_cleanup_does_not_roll_back_success(self):
        state.atomic(self.root/'deployment-journal.json',dict(phase='committed',new_version='old'))
        self.assertTrue(state.recover(self.root,True));self.assertTrue(self.old.is_file())
    def test_tampered_journal_cannot_remove_outside_directory(self):
        state.atomic(self.root/'deployment-journal.json',dict(phase='prepared',new_version='../outside',snapshot={}))
        with self.assertRaises(ValueError):state.recover(self.root,True)
        self.assertTrue(self.old.is_file())
    def test_wait_ready_requires_matching_nonce_pid_version_and_live_process(self):
        p=self.root/'receipt.json';exe=self.old;proc=Mock(pid=42,poll=lambda:None)
        good=dict(token='a'*32,pid=42,version=VERSION,exe=str(exe.resolve()),windowReady=True,serverReady=True)
        p.write_text(json.dumps({**good,'token':'wrong'}))
        with self.assertRaises(OSError):state.wait_ready(proc,exe,p,'a'*32,VERSION,timeout=.01,stable_seconds=0)
        p.write_text(json.dumps(good));self.assertEqual(state.wait_ready(proc,exe,p,'a'*32,VERSION,timeout=.1,stable_seconds=0)['pid'],42)
    def test_exit_after_receipt_before_stability_interval_is_failure(self):
        p=self.root/'receipt.json';p.write_text(json.dumps(dict(token='a'*32,pid=42,version=VERSION,exe=str(self.old.resolve()),windowReady=True,serverReady=True)))
        proc=Mock(pid=42);proc.poll.side_effect=[None,1]
        with self.assertRaises(OSError):state.wait_ready(proc,self.old,p,'a'*32,VERSION,timeout=1)
    def test_registry_values_and_types_are_restored_after_partial_changes(self):
        import winreg
        values={'DisplayVersion':('old',winreg.REG_SZ),'NoModify':(1,winreg.REG_DWORD)};original=values.copy()
        key=Mock();key.__enter__=Mock(return_value=key);key.__exit__=Mock(return_value=False)
        def enum(handle,i):
            try:name=list(values)[i]
            except IndexError:
                error=OSError('end');error.winerror=259;raise error
            return name,*values[name]
        def put(handle,name,reserved,kind,value):values[name]=(value,kind)
        with patch('winreg.OpenKey',return_value=key),patch('winreg.CreateKey',return_value=key),patch('winreg.EnumValue',side_effect=enum),patch('winreg.DeleteValue',side_effect=lambda h,n:values.pop(n)),patch('winreg.SetValueEx',side_effect=put):
            snapshot=state.capture_entries(self.root,True);snapshot['registry']=self.real_registry_snapshot()
            values['DisplayVersion']=('new',winreg.REG_SZ);values['Extra']=('extra',winreg.REG_SZ)
            state.restore_entries(self.root,snapshot,True);self.assertEqual(values,original)
    def test_path_traversal_in_zip_never_touches_entries(self):
        with zipfile.ZipFile(self.payload,'a') as z:z.writestr('../escape',b'bad')
        with self.assertRaises(ValueError):installer.install(self.payload,self.root)
        self.restored()

if __name__=='__main__':unittest.main()
