import copy,hashlib,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from PIL import Image
from app_updates import API,REPOSITORY,UpdateError,UpdateCancelled,check_release,parse_release
from animation_updates import commit,effective_version,load_override,stage,validate_catalog
from material_store import MaterialStore

class Response(io.BytesIO):
    def __init__(self,data):super().__init__(data);self.headers={'Content-Length':str(len(data))};self.status=200

class AnimationUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.app=self.root/'app';self.state=self.root/'state';self.state.mkdir();(self.app/'app').mkdir(parents=True)
        self.base=self.make_catalog('base','white');self.new=self.make_catalog('next','purple')
        (self.app/'app/material_catalog.json').write_text(json.dumps(self.base),encoding='utf-8')
        target=self.app/'outputs/白龙桌宠素材';target.mkdir(parents=True)
        for file in (self.root/'base/light').iterdir():(target/file.name).write_bytes(file.read_bytes())
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from build_animation_update import package
        self.dest=self.root/'release';self.version='1.0.6'
        self.data=package(self.root/'next/catalog.json',self.root/'next/light',self.root/'next/hd',self.dest,self.version,'1.0.5')
        self.payload=dict(tag_name='v'+self.version,assets=[dict(name=p.name,state='uploaded',size=p.stat().st_size,digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest(),browser_download_url=self.url(p.name)) for p in self.dest.iterdir() if p.name!='animation-catalog-1.0.6.json'])
    def tearDown(self):self.temp.cleanup()
    def url(self,name):return f'https://github.com/{REPOSITORY}/releases/download/v{self.version}/{name}'
    def make_catalog(self,folder,color):
        catalog=dict(schema=1,default='light',tiers={});base=self.root/folder
        for tier,size in [('light',512),('hd',720)]:
            path=base/tier;path.mkdir(parents=True)
            Image.new('RGBA',(size,size),color).save(path/'idle.webp',format='WEBP',lossless=True)
            (path/'素材清单.json').write_text(json.dumps(dict(idle=dict(id='idle',file='idle.webp'))),encoding='utf-8')
            files=[dict(path=p.name,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in path.iterdir()];files.sort(key=lambda f:f['path'])
            identity=hashlib.sha256(json.dumps(files,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
            catalog['tiers'][tier]=dict(id=identity,resolution=size,files=files,bytes=sum(f['bytes'] for f in files))
        (base/'catalog.json').write_text(json.dumps(catalog),encoding='utf-8');return catalog
    def opener(self,url,headers=None):
        if url==API:return Response(json.dumps(self.payload).encode())
        if url.endswith('/latest/download/SHA256SUMS.txt'):return Response((self.dest/'SHA256SUMS.txt').read_bytes())
        return Response((self.dest/url.rsplit('/',1)[-1]).read_bytes())
    def release(self):return check_release('1.0.5',self.opener,app_root=self.app,state_dir=self.state)
    def test_pure_animation_staging_commit_restart_and_rollback_retains_old_files(self):
        release=self.release();self.assertEqual(release.kind,'animation')
        self.assertTrue(release.asset_name.endswith('-animation-light.zip'))
        ready=stage(release,self.app,self.state,lambda *args:None,lambda:False,self.opener)
        self.assertFalse((self.state/'animation-release.json').exists())
        old=(self.app/'outputs/白龙桌宠素材/idle.webp').read_bytes()
        ready['store'].activate(ready['tier'],ready['root']);commit(ready)
        with patch('version.VERSION','1.0.5'):
            store=MaterialStore(self.app,self.state)
            self.assertEqual(store.catalog['releaseVersion'],'1.0.6');self.assertNotEqual(store.root,store.base)
            self.assertEqual(effective_version('1.0.5',self.state),'1.0.6')
        self.assertEqual(old,(self.app/'outputs/白龙桌宠素材/idle.webp').read_bytes())
        self.assertEqual(store.patch_previous['catalog'],self.base)
        with patch('version.VERSION','1.0.7'):
            self.assertEqual(MaterialStore(self.app,self.state).catalog['releaseVersion'],'1.0.6')
        self.assertEqual(effective_version('1.0.7',self.state),'1.0.7')
        from dataclasses import replace
        rollback=replace(release,version='1.0.5',animation_catalog=self.base,animation_tier='',minimum_program_version='1.0.5')
        prior=stage(rollback,self.app,self.state,lambda *a:None,lambda:False,self.opener);prior['store'].activate(prior['tier'],prior['root']);commit(prior)
        self.assertIsNone(load_override('1.0.5',self.state));self.assertTrue(ready['root'].is_dir())
    def test_hash_mismatch_and_cancel_never_commit(self):
        release=self.release();name=release.asset_name
        (self.dest/name).write_bytes(b'broken')
        with self.assertRaises((ValueError,UpdateError)):stage(release,self.app,self.state,lambda *a:None,lambda:False,self.opener)
        self.assertFalse((self.state/'animation-release.json').exists())
        with self.assertRaises(UpdateCancelled):stage(release,self.app,self.state,lambda *a:None,lambda:True,self.opener)
    def test_card_only_retains_preference_and_downloads_no_animations(self):
        (self.state/'material-preferences.json').write_text(json.dumps(dict(tier='hd',cardOnly=True)))
        release=self.release();ready=stage(release,self.app,self.state,lambda *a:None,lambda:False,lambda *a: (_ for _ in ()).throw(AssertionError('unexpected animation download')))
        self.assertIsNone(ready['root']);commit(ready)
        self.assertTrue(ready['store'].card_only)
        self.assertFalse((self.state/'materials').exists())
    def test_rate_limited_api_and_program_only_releases_have_download_fallback(self):
        def limited(url,headers=None):
            if url==API:raise HTTPError(url,429,'rate limited',{},None)
            return self.opener(url,headers)
        release=check_release('1.0.5',limited,state_dir=self.state)
        self.assertEqual(release.kind,'animation');self.assertEqual(release.version,self.version)
    def test_minimum_version_and_catalog_escape_are_rejected(self):
        with self.assertRaises(UpdateError):check_release('1.0.4',self.opener,state_dir=self.state)
        catalog=copy.deepcopy(self.data['catalog']);catalog['tiers']['light']['files'][0]['path']='../outside'
        with self.assertRaises(ValueError):validate_catalog(catalog,self.version)
        catalog=copy.deepcopy(self.data['catalog']);catalog['tiers']['hd']['url']='https://example.org/file.zip'
        with self.assertRaises(UpdateError):validate_catalog(catalog,self.version)
    def test_combined_release_prefers_program_and_keeps_animation_descriptor(self):
        extra=[dict(name=f'bailong-desktop-pet-{self.version}-program'+ext,state='uploaded',size=300,digest='sha256:'+'a'*64,browser_download_url=self.url(f'bailong-desktop-pet-{self.version}-program'+ext)) for ext in ('.zip','.json')]
        release=parse_release(dict(self.payload,assets=self.payload['assets']+extra))
        self.assertEqual(release.kind,'program');self.assertTrue(release.animation_info_url)
        self.assertIsNone(release.fallback)
    def test_program_only_rate_limit_fallback_does_not_require_full_installer(self):
        name=f'bailong-desktop-pet-{self.version}-program'
        meta=json.dumps(dict(schema=1,kind='program',version=self.version,materialId='a'*24,optionalMaterials=True)).encode()
        files={name+'.json':meta,name+'.zip':b'program-fixture'}
        sums=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in files.items()).encode()
        def opener(url,headers=None):
            if url==API:raise HTTPError(url,429,'limited',{},None)
            return Response(sums if url.endswith('SHA256SUMS.txt') else files[url.rsplit('/',1)[-1]])
        release=check_release('1.0.5',opener,state_dir=self.state)
        self.assertEqual(release.kind,'program');self.assertIsNone(release.fallback)
    def test_live_player_queues_patch_then_commits_at_action_boundary(self):
        from desktop import DesktopPet
        from types import SimpleNamespace
        from unittest.mock import Mock
        ready=stage(self.release(),self.app,self.state,lambda *a:None,lambda:False,self.opener)
        fake=SimpleNamespace(materials=Mock(job=None),updates=Mock(),_pending_material=None,
            settings=dict(character='builtin'),material_store=MaterialStore(self.app,self.state),queue_material=Mock())
        DesktopPet.queue_animation_update(fake,ready)
        self.assertFalse((self.state/'animation-release.json').exists());fake.queue_material.assert_called_once()
        fake._pending_material=(ready['tier'],ready['root']);fake.asset_root=fake.material_store.root
        fake.manifest=dict(idle=dict(id='idle',file='idle.webp'));fake.idles=[];fake.variants=[]
        fake.sustained=Mock();fake.player=Mock();fake.cache={};fake.pinned_frames={};fake.gate=SimpleNamespace(state='task');fake.reactions=Mock();fake._materials_missing=False
        with patch('desktop.StreamPlayer'):
            self.assertTrue(DesktopPet.apply_material(fake))
        self.assertTrue((self.state/'animation-release.json').is_file());fake.updates.animation_applied.assert_called_once_with(ready)
        self.assertEqual(fake.gate.state,'idle');self.assertEqual(fake.asset_root,ready['root'])
    def test_animation_rollback_never_downgrades_program_version_or_leaves_dead_install_button(self):
        from update_controller import UpdateController
        from dataclasses import replace
        c=UpdateController('1.0.7',self.state/'updates',allow_auto=False)
        c.animation_applied(dict(release=replace(self.release(),version='1.0.5')))
        self.assertEqual(c.current,'1.0.7');self.assertEqual(c.state['latest'],'1.0.7');self.assertFalse(c.install_requested)
    def test_update_cleanup_tolerates_cache_removed_by_another_operation(self):
        from app_updates import prune_completed
        with patch('program_updates.prune_program_cache'),patch.object(Path,'is_dir',return_value=True),patch.object(Path,'is_symlink',return_value=False),patch.object(Path,'is_junction',return_value=False),patch.object(Path,'iterdir',side_effect=FileNotFoundError('cache disappeared')):
            prune_completed(self.state/'updates','1.0.5')
    def test_explicit_removal_covers_bundled_and_patch_media_without_double_deleting(self):
        from material_removal import removal_plan
        ready=stage(self.release(),self.app,self.state,lambda *a:None,lambda:False,self.opener)
        ready['store'].activate(ready['tier'],ready['root']);commit(ready)
        plan=removal_plan(ready['store'],include_embedded=True)
        targets={(item['root'],item['name']) for item in plan}
        self.assertEqual(len(plan),len(targets))
        self.assertIn((str(self.app/'outputs/白龙桌宠素材'),'idle.webp'),targets)
        self.assertIn((str(ready['root']),'idle.webp'),targets)
