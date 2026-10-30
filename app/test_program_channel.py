"""Publication channel tests: actual archives, no public network or deployment."""
import hashlib,json,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from program_channel import CHANNEL,from_archive,validate,write_channel

class ProgramChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.program=self.root/'bailong-desktop-pet-1.2.1-program.zip'
        with zipfile.ZipFile(self.program,'w') as z:
            z.writestr('program-update.json',json.dumps(dict(schema=1,kind='program',version='1.2.1',optionalMaterials=True)))
            z.writestr('payload-manifest.json',json.dumps(dict(version='1.2.1')))
    def tearDown(self):self.tmp.cleanup()
    def test_cumulative_archive_publishes_exact_version_size_and_digest(self):
        d=write_channel(self.root/'release','1.2.1',program=self.program)
        self.assertEqual(d['version'],'1.2.1');self.assertEqual(d['program']['bytes'],self.program.stat().st_size)
        self.assertEqual(d['program']['sha256'],hashlib.sha256(self.program.read_bytes()).hexdigest())
        p=self.root/'release'/CHANNEL
        self.assertIn(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+CHANNEL,(p.parent/'SHA256SUMS.txt').read_text())
    def test_animation_only_release_carries_last_program_without_changing_target(self):
        old=self.root/'old';new=self.root/'new';d=write_channel(old,'1.2.1',program=self.program)
        self.assertEqual(write_channel(new,'1.2.2',previous=old/CHANNEL,minimum='1.1.0'),d)
        self.assertEqual((old/CHANNEL).read_bytes(),(new/CHANNEL).read_bytes())
    def test_invalid_channel_is_rejected_before_creating_output(self):
        for change in ({'url':'https://evil.example/p.zip'},{'bytes':True},{'bytes':0},{'sha256':'missing'},{'name':'other.zip'}):
            with self.subTest(change=change):
                d=from_archive(self.program,'1.2.1');d['program'].update(change)
                old=self.root/'invalid.json';old.write_text(json.dumps(d))
                with self.assertRaises(ValueError):write_channel(self.root/'rejected','1.2.2',previous=old)
                self.assertFalse((self.root/'rejected').exists())
    def test_incompatible_or_unpublished_program_target_is_not_silently_used(self):
        d=from_archive(self.program,'1.2.1')
        for maximum,minimum in [('1.2.0',None),('1.2.2','1.2.2')]:
            with self.subTest(maximum=maximum,minimum=minimum):
                with self.assertRaises(ValueError):validate(d,maximum,minimum)
        for key,value in [('installerProtocol',2),('schema',True),('version','01.2.1')]:
            with self.subTest(key=key):
                bad=dict(d,**{key:value})
                with self.assertRaises(ValueError):validate(bad)
    def test_packaging_rejects_non_cumulative_or_mismatched_payload(self):
        with self.assertRaises(ValueError):from_archive(self.program,'1.2.2')
        with zipfile.ZipFile(self.program,'w') as z:
            z.writestr('program-update.json',json.dumps(dict(schema=1,kind='program',version='1.2.1',optionalMaterials=False)))
            z.writestr('payload-manifest.json',json.dumps(dict(version='1.2.1')))
        with self.assertRaises(ValueError):from_archive(self.program,'1.2.1')
    def test_channel_carry_needs_one_explicit_source_and_preserves_other_checksums(self):
        out=self.root/'release';out.mkdir();(out/'SHA256SUMS.txt').write_text('a'*64+'  animation.zip\n')
        for kw in ({},{'program':self.program,'previous':self.program}):
            with self.assertRaises(ValueError):write_channel(out,'1.2.1',**kw)
        write_channel(out,'1.2.1',program=self.program)
        self.assertIn('a'*64+'  animation.zip',(out/'SHA256SUMS.txt').read_text())
    def test_animation_publication_requires_compatible_previous_program_before_packaging(self):
        from build_animation_update import publication_program_channel
        with self.assertRaises(ValueError):publication_program_channel(self.root,'1.2.2','1.2.1')
        old=self.root/'old';d=write_channel(old,'1.2.1',program=self.program)
        self.assertEqual(publication_program_channel(self.root/'animation-only','1.2.2','1.2.1',old/CHANNEL),d)
        with self.assertRaises(ValueError):publication_program_channel(self.root/'animation-only','1.2.2','1.2.2',old/CHANNEL)
    def test_complete_base_packaging_preserves_channel_and_online_installer_checksums(self):
        import shutil,build_release
        root=self.root/'bundle';release=root/'release';release.mkdir(parents=True)
        shutil.copyfile(self.program,release/self.program.name)
        (release/'bailong-desktop-pet-1.2.1-program.json').write_text('{}')
        (release/'白龙桌宠-1.2.1-一键部署.exe').write_bytes(b'MZ-offline-fixture')
        online=release/'bailong-desktop-pet-1.2.1-setup.exe';online.write_bytes(b'MZ-online-fixture')
        for relative in ('发布说明/安装管理.cmd','发布说明/快速部署说明.txt','发布说明/新增功能说明.txt','发布说明/迭代历史.txt','发布说明/v1.2.1.md','发布说明/来源与授权说明.txt','app/licenses/upstream-v0.4.1-assets.txt'):
            p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
        write_channel(release,'1.2.1',program=release/self.program.name)
        with patch.object(build_release,'ROOT',root):build_release.build_windows_bundle('1.2.1')
        sums=(release/'SHA256SUMS.txt').read_text()
        for p in (online,release/CHANNEL):self.assertIn(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name,sums)

if __name__=='__main__':unittest.main()
