import hashlib,json,os,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import installer
from desktop_core import VERSION
from directory_deploy import inspect_source,populate_directory,backup_data,deploy_directory
import test_deployment_transaction as transaction_tests
from contextlib import closing

class SourceTests(unittest.TestCase):
    def test_large_database_backup_has_a_bounded_size_based_allowance(self):
        from directory_deploy import backup_budget
        self.assertEqual(backup_budget(4*1024*1024),15)
        self.assertGreater(backup_budget(3*1024**3),90)
        self.assertGreater(backup_budget(4*1024*1024,2*1024**3),60)
        self.assertEqual(backup_budget(2*1024**4),180)
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
        self.make('BailongEnhanced.exe',b'executable')
    def tearDown(self):self.tmp.cleanup()
    def make(self,name,content):
        p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
        records={q.relative_to(self.source).as_posix():dict(bytes=q.stat().st_size,sha256=hashlib.sha256(q.read_bytes()).hexdigest()) for q in self.source.rglob('*') if q.is_file() and q.name!='payload-manifest.json'}
        (self.source/'payload-manifest.json').write_text(json.dumps(dict(version=VERSION,files=records)),encoding='utf-8')
    def test_copies_all_verified_files_and_uses_private_executable(self):
        self.make('outputs/白龙桌宠素材/a.webp',b'asset');dest=self.root/'new';dest.mkdir()
        populate_directory(self.source,dest,VERSION)
        self.assertEqual((dest/'BailongEnhanced.exe').read_bytes(),b'executable')
        self.assertFalse(os.path.samefile(self.source/'BailongEnhanced.exe',dest/'BailongEnhanced.exe'))
        self.assertTrue(os.path.samefile(self.source/'outputs/白龙桌宠素材/a.webp',dest/'outputs/白龙桌宠素材/a.webp'))
    def test_assets_copy_when_hardlinks_are_not_supported(self):
        self.make('outputs/白龙桌宠素材/a.webp',b'asset');dest=self.root/'new';dest.mkdir()
        with patch('directory_deploy.os.link',side_effect=OSError('cross-volume')):populate_directory(self.source,dest,VERSION)
        self.assertEqual((dest/'outputs/白龙桌宠素材/a.webp').read_bytes(),b'asset')
        self.assertFalse(os.path.samefile(self.source/'outputs/白龙桌宠素材/a.webp',dest/'outputs/白龙桌宠素材/a.webp'))
    def test_missing_manifest_corruption_and_extra_files_are_rejected(self):
        for kind in ('missing','corrupt','extra','version'):
            self.make('BailongEnhanced.exe',b'executable');manifest=self.source/'payload-manifest.json'
            if kind=='missing':manifest.unlink()
            elif kind=='corrupt':(self.source/'BailongEnhanced.exe').write_bytes(b'broken')
            elif kind=='extra':(self.source/'untracked.txt').write_text('unknown')
            else:
                data=json.loads(manifest.read_text());data['version']='0.0.0';manifest.write_text(json.dumps(data))
            with self.assertRaises((ValueError,OSError)):inspect_source(self.source,VERSION)
            (self.source/'untracked.txt').unlink(missing_ok=True)
    def test_manifest_traversal_windows_ads_case_alias_and_bad_hash(self):
        for name in ('../outside','C:/outside','dir\\outside','a/../b','/outside','BailongEnhanced.EXE'):
            self.make('BailongEnhanced.exe',b'executable');path=self.source/'payload-manifest.json';data=json.loads(path.read_text())
            data['files'][name]=dict(bytes=1,sha256='a'*64);path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):inspect_source(self.source,VERSION)
    def test_source_changed_during_copy_never_passes_destination_verification(self):
        dest=self.root/'new';dest.mkdir();import shutil
        real=shutil.copy2
        def corrupt(src,dst):
            result=real(src,dst)
            if Path(dst).name=='BailongEnhanced.exe':Path(dst).write_bytes(b'bad')
            return result
        with patch('directory_deploy.shutil.copy2',side_effect=corrupt),self.assertRaises(ValueError):populate_directory(self.source,dest,VERSION)
    def test_database_backup_includes_committed_wal_and_excludes_downloads(self):
        data=self.root/'data';data.mkdir();(data/'settings.json').write_text('{"preserve":true}')
        (data/'runtime.json').write_text('ephemeral');(data/'updates').mkdir();(data/'updates/large.zip').write_bytes(b'download')
        db=sqlite3.connect(data/'tokens.sqlite3');db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE events(value)');db.execute('INSERT INTO events VALUES(42)');db.commit()
        install=self.root/'install';install.mkdir()
        try:backup=backup_data(data,install,'previous')
        finally:db.close()
        self.assertEqual((backup/'settings.json').read_bytes(),(data/'settings.json').read_bytes())
        with closing(sqlite3.connect(backup/'tokens.sqlite3')) as copy:self.assertEqual(copy.execute('SELECT value FROM events').fetchone()[0],42)
        self.assertFalse((backup/'runtime.json').exists());self.assertFalse((backup/'updates').exists())
        self.assertTrue(json.loads((backup/'backup.json').read_text())['complete'])
    def test_broken_build_does_not_stop_current_program(self):
        (self.source/'BailongEnhanced.exe').write_bytes(b'bad')
        with patch('installer.stop_existing') as stop,self.assertRaises(ValueError):deploy_directory(self.source,False,self.root/'install',self.root/'data')
        stop.assert_not_called()
    @unittest.skipUnless(os.name=='nt','Windows junctions')
    def test_directory_junction_is_rejected(self):
        import subprocess
        junction=self.root/'junction'
        subprocess.run(['cmd','/c','mklink','/J',str(junction),str(self.source)],capture_output=True,check=True)
        try:
            with self.assertRaises(ValueError):inspect_source(junction,VERSION)
            with patch('installer.stop_existing') as stop,self.assertRaises(ValueError):deploy_directory(junction,False,self.root/'install',self.root/'data')
            stop.assert_not_called()
        finally:junction.rmdir()

class DirectoryTransactionTests(unittest.TestCase):
    setUp=transaction_tests.TransactionTests.setUp
    tearDown=transaction_tests.TransactionTests.tearDown
    register=transaction_tests.TransactionTests.register
    restored=transaction_tests.TransactionTests.restored
    def source(self):
        directory=self.root/'source';directory.mkdir()
        with zipfile.ZipFile(self.payload) as archive:archive.extractall(directory)
        return directory
    def test_ready_before_switch_and_previous_kept_without_zip_loader(self):
        source=self.source()
        def ready(*a):self.assertEqual(installer.read_manifest(self.root)['current'],'old')
        with patch('installer.zipfile.ZipFile',side_effect=AssertionError('ZIP must not be used')):
            exe=installer.install(None,self.root,populate=lambda d:populate_directory(source,d,VERSION),before_commit=ready)
        self.assertTrue(self.old.is_file());self.assertFalse((exe.parent/'白龙安装管理.exe').exists())
    def test_partial_directory_copy_and_failed_startup_restore_old_entries(self):
        source=self.source()
        def broken(dest):(dest/'part').write_bytes(b'partial');raise OSError('copy interrupted')
        for populate in (broken,lambda d:populate_directory(source,d,VERSION)):
            with self.assertRaises(OSError):installer.install(None,self.root,populate=populate,before_commit=lambda *a:(_ for _ in ()).throw(OSError('not ready')))
            self.restored()
    def test_backup_failure_restarts_old_and_never_switches_entries(self):
        source=self.source()
        with patch('installer.stop_existing',return_value=self.old),patch('directory_deploy.backup_data',side_effect=OSError('disk full')),patch('installer.subprocess.Popen') as start,self.assertRaises(OSError):
            deploy_directory(source,False,self.root,self.root/'data')
        start.assert_called_once();self.restored()

if __name__=='__main__':unittest.main()
