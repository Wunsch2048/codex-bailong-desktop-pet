import os,sys,json,tempfile,unittest,hashlib,shutil
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image
from PySide6.QtWidgets import QApplication
import shared_assets,optional_tools,installer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from asset_pack import encode_exact,frame_fingerprints
APP=QApplication.instance() or QApplication([])

class AssetEncodingTests(unittest.TestCase):
    def test_reencoding_preserves_all_rgba_timing_loop_and_canvas(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.webp';b=Path(d)/'b.webp'
            frames=[Image.new('RGBA',(32,32),(i,40,80,100+i)) for i in (1,2,3)]
            frames[0].save(a,save_all=True,append_images=frames[1:],lossless=True,method=0,duration=[40,42,41],loop=2)
            encode_exact(a,b);self.assertEqual(frame_fingerprints(a),frame_fingerprints(b));self.assertLessEqual(b.stat().st_size,a.stat().st_size)
    def test_invalid_container_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a';p.write_bytes(b'bad')
            with self.assertRaises(ValueError):encode_exact(p,Path(d)/'b')

class SharedAssetTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.content=b'asset-content';self.sha=hashlib.sha256(self.content).hexdigest()
    def tearDown(self):self.tmp.cleanup()
    def version(self,name):
        folder=self.root/'versions'/name;file=folder/'outputs/白龙桌宠素材/a.webp';file.parent.mkdir(parents=True);file.write_bytes(self.content)
        (folder/'payload-manifest.json').write_text(json.dumps(dict(files={'outputs/白龙桌宠素材/a.webp':dict(sha256=self.sha,bytes=len(self.content))})))
        return folder,file
    def test_two_new_versions_share_one_file_and_verify_rollback(self):
        a,p=self.version('a');b,q=self.version('b');ra=shared_assets.share(a,self.root);rb=shared_assets.share(b,self.root)
        self.assertEqual(ra[0]['mode'],'hardlink');self.assertEqual(rb[0]['mode'],'hardlink');self.assertTrue(os.path.samefile(p,q));self.assertTrue(os.path.samefile(p,shared_assets.object_path(self.root,self.sha)))
        shared_assets.verify_version(a,ra);shared_assets.verify_version(b,rb)
    def test_three_versions_keep_valid_references_to_one_object(self):
        copies=[]
        for name in ('first','second','third'):
            folder,path=self.version(name);records=shared_assets.share(folder,self.root);copies.append(path)
            shared_assets.verify_version(folder,records)
        self.assertEqual(len({(p.stat().st_dev,p.stat().st_ino) for p in copies}),1)
        self.assertGreaterEqual(copies[0].stat().st_nlink,4)
    def test_unsupported_hardlinks_keep_private_verified_files(self):
        a,p=self.version('a')
        with patch('shared_assets.os.link',side_effect=OSError('unsupported')):r=shared_assets.share(a,self.root)
        self.assertEqual(r[0]['mode'],'private');self.assertEqual(p.read_bytes(),self.content)
    def test_unreadable_store_keeps_private_copy(self):
        a,p=self.version('a');shared_assets.share(a,self.root);b,q=self.version('b')
        with patch('shared_assets.digest',side_effect=PermissionError('denied')):r=shared_assets.share(b,self.root)
        self.assertEqual(r[0]['mode'],'private');self.assertEqual(q.read_bytes(),self.content)
    def test_corrupt_shared_object_falls_back_without_modifying_old_version(self):
        a,p=self.version('a');records=shared_assets.share(a,self.root);p.write_bytes(b'corrupt')
        b,q=self.version('b');r=shared_assets.share(b,self.root)
        self.assertEqual(r[0]['mode'],'private');self.assertEqual(q.read_bytes(),self.content);self.assertEqual(p.read_bytes(),b'corrupt')
        with self.assertRaises(ValueError):shared_assets.verify_version(a,records)
    def test_cleanup_only_deletes_own_unreferenced_new_object(self):
        a,p=self.version('a');shared_assets.share(a,self.root);obj=shared_assets.object_path(self.root,self.sha)
        shared_assets.cleanup_new(self.root,[self.sha]);self.assertTrue(obj.exists())
        p.unlink();shared_assets.cleanup_new(self.root,[self.sha]);self.assertFalse(obj.exists())
    def test_invalid_object_identifier_cannot_escape_root(self):
        with self.assertRaises(ValueError):shared_assets.object_path(self.root,'../outside')

class OptionalToolTests(unittest.TestCase):
    def test_webp_import_does_not_find_or_run_converter(self):
        from desktop_services import import_character
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'source/idle').mkdir(parents=True);Image.new('RGBA',(32,32),(0,0,0,0)).save(root/'source/idle/a.webp')
            with patch('optional_tools.find_ffmpeg',side_effect=AssertionError('not needed')):key,m=import_character(root/'source',root/'characters')
            self.assertTrue((root/'characters'/key/'素材清单.json').is_file())
    def test_missing_converter_gives_actionable_webm_import_error_and_cleans_stage(self):
        from desktop_services import import_character
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'source/idle').mkdir(parents=True);(root/'source/idle/a.webm').write_bytes(b'video')
            with patch('optional_tools.find_ffmpeg',return_value=None),self.assertRaisesRegex(ValueError,'角色页选择'):import_character(root/'source',root/'characters')
            self.assertEqual(list((root/'characters').iterdir()),[])
    def test_selected_tool_is_version_checked_and_only_path_is_saved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ffmpeg.exe';p.write_bytes(b'test');config=Path(d)/'tools.json'
            with patch('optional_tools.settings_file',return_value=config),patch('optional_tools.subprocess.run',return_value=Mock(returncode=0,stdout=b'ffmpeg version 7')) as run:optional_tools.save_ffmpeg(p)
            self.assertEqual(run.call_args.args[0],[str(p.resolve()),'-version']);self.assertEqual(json.loads(config.read_text()),{'ffmpeg':str(p.resolve())})
    def test_wrong_executable_is_not_saved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.exe';p.write_bytes(b'test');config=Path(d)/'tools.json'
            with patch('optional_tools.settings_file',return_value=config),patch('optional_tools.subprocess.run',return_value=Mock(returncode=0,stdout=b'other')),self.assertRaises(ValueError):optional_tools.save_ffmpeg(p)
            self.assertFalse(config.exists())

class MaintenanceTests(unittest.TestCase):
    def test_lightweight_maintenance_has_no_install_payload_action(self):
        with patch('installer.startup_preference',return_value=False):w=installer.Installer(maintenance=True)
        w.show();APP.processEvents();self.assertFalse(w.install_button.isVisible());self.assertFalse(w.startup.isChecked());self.assertIsNone(w.job);w.close();w.deleteLater();APP.processEvents()
    def test_application_manager_routes_before_pet_single_instance(self):
        import enhanced
        with patch.object(sys,'argv',['BailongEnhanced.exe','--manage']),patch('installer.maintenance_main',return_value=0) as manage:
            self.assertEqual(enhanced.main(),0);manage.assert_called_once()

if __name__=='__main__':unittest.main()
