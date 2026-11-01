import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import hashlib,io,json,sys,tempfile,threading,unittest,zipfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_updates import Release,parse_release,check_release,UpdateError,UpdateCancelled,API,REPOSITORY
from program_updates import stage_program,program_paths,verify_ready,local_materials,MaterialMismatch,prune_program_cache,safe
from build_program_update import package
from version import VERSION
from test_app_updates import Response,payload

class ProgramUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'new';self.old=self.root/'old';self.cache=self.root/'data/updates'
        self.media={'idle.webp':b'light-asset-content','素材清单.json':b'{"fixture":true}'}
        from test_material_publication import fixture_catalog
        self.catalog=fixture_catalog(self.media);self.light=self.catalog['tiers']['light']
        self.files={'BailongEnhanced.exe':b'MZnew-program','_internal/runtime.dll':os.urandom(700000),'app/material_catalog.json':json.dumps(self.catalog).encode(),**{'outputs/白龙桌宠素材/'+n:b for n,b in self.media.items()}}
        for n,b in self.files.items():
            p=self.source/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
        self.manifest=dict(version=VERSION,files={n:dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in self.files.items()})
        (self.source/'payload-manifest.json').write_text(json.dumps(self.manifest),encoding='utf-8')
        self.old.mkdir();(self.old/'app').mkdir();(self.old/'app/material_catalog.json').write_text(json.dumps(self.catalog),encoding='utf-8')
        for n,b in self.media.items():
            p=self.old/'outputs/白龙桌宠素材'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
        result=package(self.source,self.root/'packages');self.bytes=Path(result['archive']).read_bytes();self.info=Path(result['metadata']).read_bytes()
        self.release=Release(VERSION,'v'+VERSION,Path(result['archive']).name,'https://github.com/'+REPOSITORY+'/releases/download/v'+VERSION+'/'+Path(result['archive']).name,len(self.bytes),result['sha256'],kind='program',material_id=self.light['id'])
    def tearDown(self):self.tmp.cleanup()
    def opener(self,url,headers=None):
        offset=int(headers['Range'][6:-1]) if headers and headers.get('Range') else 0
        return Response(self.bytes[offset:],206 if offset else 200,{'Content-Range':f'bytes {offset}-{len(self.bytes)-1}/{len(self.bytes)}'})
    def release_data(self,full=True):
        p=payload(VERSION)
        if not full:p['assets']=[]
        for name,size,sha in [(self.release.asset_name,len(self.bytes),self.release.sha256),(f'bailong-desktop-pet-{VERSION}-program.json',len(self.info),'b'*64)]:
            p['assets'].append(dict(name=name,size=size,digest='sha256:'+sha,state='uploaded',browser_download_url=f'https://github.com/{REPOSITORY}/releases/download/v{VERSION}/{name}'))
        return p
    def test_package_contains_all_program_files_and_no_animations(self):
        with zipfile.ZipFile(io.BytesIO(self.bytes)) as z:
            self.assertIn('BailongEnhanced.exe',z.namelist());self.assertIn('_internal/runtime.dll',z.namelist());self.assertFalse(any(n.startswith('outputs/') for n in z.namelist()))
    def test_program_packaging_refuses_catalog_without_download_contract(self):
        catalog=dict(self.catalog);catalog.pop('releaseVersion')
        data=json.dumps(catalog).encode();(self.source/'app/material_catalog.json').write_bytes(data)
        self.manifest['files']['app/material_catalog.json']=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        (self.source/'payload-manifest.json').write_text(json.dumps(self.manifest),encoding='utf-8')
        destination=self.root/'refused'
        with self.assertRaisesRegex(UpdateError,'缺少发布下载目录'):package(self.source,destination)
        self.assertFalse(destination.exists())
        from build_card_only import prepare
        with self.assertRaisesRegex(UpdateError,'缺少发布下载目录'):prepare(self.source,destination)
        self.assertFalse(destination.exists())
    def test_preflight_selects_program_without_downloading_it_and_keeps_notes(self):
        calls=[]
        def fetch(url,*a):calls.append(url);return Response(json.dumps(self.release_data()).encode() if url==API else self.info)
        r=check_release('0.7.7',fetch,app_root=self.old)
        self.assertEqual(r.kind,'program');self.assertEqual(r.material_id,self.light['id']);self.assertIsNotNone(r.fallback)
        self.assertEqual(len(calls),2);self.assertNotIn(self.release.download_url,calls);self.assertIn('测试内容',r.notes)
    def test_changed_or_corrupt_materials_select_full_before_download(self):
        legacy_info=json.loads(self.info);legacy_info.pop('optionalMaterials',None)
        for kind in ('missing','changed-id'):
            with self.subTest(kind=kind):
                if kind=='missing':(self.old/'outputs/白龙桌宠素材/idle.webp').write_bytes(b'bad')
                else:
                    cat=json.loads((self.old/'app/material_catalog.json').read_text());cat['tiers']['light']['id']='f'*24;(self.old/'app/material_catalog.json').write_text(json.dumps(cat))
                r=check_release('0.7.7',lambda url,*a:Response(json.dumps(self.release_data()).encode() if url==API else json.dumps(legacy_info).encode()),app_root=self.old)
                self.assertEqual(r.kind,'full');self.assertIn('完整',r.reason)
    def test_card_only_program_update_needs_no_animation_download(self):
        empty=self.root/'card-only';empty.mkdir()
        r=check_release('0.7.7',lambda url,*a:Response(json.dumps(self.release_data()).encode() if url==API else self.info),app_root=empty)
        self.assertEqual(r.kind,'program');self.assertTrue(r.optional_materials)
        source=stage_program(r,self.cache,empty,opener=self.opener)
        manifest=json.loads((source/'payload-manifest.json').read_text(encoding='utf-8'))
        self.assertFalse(any(n.startswith('outputs/') for n in manifest['files']))
        self.assertTrue((source/'BailongEnhanced.exe').is_file())
    def test_standalone_card_payload_keeps_core_integrity_without_assets(self):
        from build_card_only import prepare
        target=prepare(self.source,self.root/'card-payload')
        self.assertFalse((target/'outputs').exists())
        self.assertTrue((target/'app/material_catalog.json').is_file())
    def test_bad_sidecar_without_full_package_never_downloads_or_installs(self):
        with self.assertRaises(UpdateError):check_release('0.7.7',lambda url,*a:Response(json.dumps(self.release_data(False)).encode() if url==API else b'{}'),app_root=self.old)
    def test_stage_reuses_only_matching_assets_and_replaces_all_program_files(self):
        old_sha=hashlib.sha256((self.old/'outputs/白龙桌宠素材/idle.webp').read_bytes()).hexdigest()
        stages=[];source=stage_program(self.release,self.cache,self.old,lambda n,t,p:stages.append(p),opener=self.opener)
        self.assertEqual((source/'BailongEnhanced.exe').read_bytes(),self.files['BailongEnhanced.exe']);self.assertIn('materials',stages)
        self.assertTrue(os.path.samefile(source/'outputs/白龙桌宠素材/idle.webp',self.old/'outputs/白龙桌宠素材/idle.webp'))
        self.assertEqual(verify_ready(source,self.cache,VERSION,self.release.sha256),source/'BailongEnhanced.exe')
        self.assertEqual(hashlib.sha256((self.old/'outputs/白龙桌宠素材/idle.webp').read_bytes()).hexdigest(),old_sha)
        self.assertFalse((source/'program-update.json').exists())
    def test_materials_changed_after_check_refuse_program_and_keep_old(self):
        (self.old/'outputs/白龙桌宠素材/idle.webp').write_bytes(b'corrupt')
        with self.assertRaises(MaterialMismatch):stage_program(self.release,self.cache,self.old,opener=lambda *a:self.fail('must not download'))
        self.assertFalse(program_paths(self.cache,VERSION)['receipt'].exists())
    def test_archive_checksum_and_post_stage_tampering_are_rejected(self):
        with self.assertRaises(UpdateError):stage_program(replace(self.release,sha256='0'*64),self.cache,self.old,opener=self.opener)
        source=stage_program(self.release,self.cache,self.old,opener=self.opener);(source/'BailongEnhanced.exe').write_bytes(b'tampered')
        with self.assertRaises(UpdateError):verify_ready(source,self.cache,VERSION,self.release.sha256)
    def test_cancel_preserves_partial_and_resume_finishes_without_changing_old(self):
        stop=threading.Event()
        def progress(n,total,phase):
            if phase=='downloading' and n:stop.set()
        with self.assertRaises(UpdateCancelled):stage_program(self.release,self.cache,self.old,progress,stop.is_set,self.opener)
        paths=program_paths(self.cache,VERSION);self.assertTrue(paths['part'].exists());self.assertFalse(paths['source'].exists())
        result=stage_program(self.release,self.cache,self.old,opener=self.opener);self.assertTrue(result.is_dir())
    def test_zip_traversal_duplicates_links_and_core_corruption_rejected(self):
        for kind in ('traversal','duplicate','link','corrupt','missing'):
            buf=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(self.bytes)) as old,zipfile.ZipFile(buf,'w') as z:
                for i in old.infolist():
                    if kind=='missing' and i.filename=='_internal/runtime.dll':continue
                    data=old.read(i)
                    if kind=='link' and i.filename=='BailongEnhanced.exe':i.external_attr=0o120777<<16
                    if kind=='corrupt' and i.filename=='BailongEnhanced.exe':data=b'X'*len(data)
                    z.writestr(i,data)
                if kind=='traversal':z.writestr('../escape',b'bad')
                if kind=='duplicate':z.writestr('BailongEnhanced.exe',b'duplicate')
            data=buf.getvalue();release=replace(self.release,size=len(data),sha256=hashlib.sha256(data).hexdigest())
            with self.subTest(kind=kind),self.assertRaises(UpdateError):stage_program(release,self.root/('cache-'+kind),self.old,opener=lambda *a:Response(data))
        self.assertFalse((self.root/'escape').exists())
    def test_windows_aliases_and_symlinks_cannot_escape(self):
        for n in ('../outside','C:/x','a\\b','file.','file ','NUL.txt','a/CON','a//b','/abs'):
            with self.subTest(n=n),self.assertRaises(UpdateError):safe(self.root,n)
    def test_completed_cleanup_keeps_future_downloads_and_unrelated_files(self):
        stage_program(self.release,self.cache,self.old,opener=self.opener);(self.cache/'notes.txt').write_text('keep')
        prune_program_cache(self.cache,'0.7.7');self.assertTrue(program_paths(self.cache,VERSION)['receipt'].exists())
        prune_program_cache(self.cache,VERSION);self.assertFalse((self.cache/VERSION/'program').exists());self.assertEqual((self.cache/'notes.txt').read_text(),'keep')
    def test_cache_removed_before_prune_scan_is_ignored(self):
        self.cache.mkdir(parents=True)
        original=Path.iterdir
        def vanished(path):
            if path==self.cache:raise FileNotFoundError(path)
            return original(path)
        with patch.object(Path,'iterdir',vanished):prune_program_cache(self.cache,VERSION)
    def test_cleanup_leaves_all_files_intact_while_update_helper_is_running(self):
        from types import SimpleNamespace
        source=stage_program(self.release,self.cache,self.old,opener=self.opener);paths=program_paths(self.cache,VERSION)
        with patch('psutil.process_iter',return_value=[SimpleNamespace(info=dict(exe=str(source/'BailongEnhanced.exe')))]):prune_program_cache(self.cache,VERSION)
        self.assertTrue(paths['archive'].is_file());self.assertTrue((source/'_internal/runtime.dll').is_file());self.assertTrue(paths['receipt'].is_file())
    def test_apply_verifies_and_uses_backup_transaction_and_preserves_hd_preference(self):
        source=stage_program(self.release,self.cache,self.old,opener=self.opener);data=self.cache.parent;(data/'settings.json').write_text('{"custom":true}');(data/'material-preferences.json').write_text('{"tier":"hd"}')
        install=self.root/'sandbox';install.mkdir();(install/'versions/old').mkdir(parents=True);(install/'versions/old/BailongEnhanced.exe').write_bytes(b'old');(install/'installations.json').write_text('{"current":"old","versions":["old"]}')
        from program_update_apply import apply_update
        with patch('installer.stop_existing',return_value=None),patch('installer.subprocess.Popen',return_value=Mock(pid=42)),patch('deployment_state.wait_ready',return_value=dict(version=VERSION,pid=42,windowReady=True,serverReady=True)):
            result=apply_update(source,install,data)
        self.assertTrue(Path(result['backup']).is_dir());self.assertEqual((Path(result['backup'])/'material-preferences.json').read_text(),'{"tier":"hd"}')
        self.assertTrue((install/'versions/old/BailongEnhanced.exe').is_file());self.assertTrue(Path(result['executable']).is_file())
    def test_corrupt_stage_rejected_before_stopping_old_or_backing_up(self):
        source=stage_program(self.release,self.cache,self.old,opener=self.opener);(source/'_internal/runtime.dll').write_bytes(b'bad')
        from program_update_apply import apply_update
        with patch('installer.stop_existing') as stop,self.assertRaises((ValueError,UpdateError)):apply_update(source,self.root/'sandbox',self.cache.parent)
        stop.assert_not_called()
    def test_new_process_not_ready_restores_old_manifest_and_retains_data_backup(self):
        source=stage_program(self.release,self.cache,self.old,opener=self.opener);data=self.cache.parent;(data/'settings.json').write_text('{"custom":true}')
        install=self.root/'sandbox';(install/'versions/old').mkdir(parents=True);(install/'versions/old/BailongEnhanced.exe').write_bytes(b'old');(install/'installations.json').write_text('{"current":"old","versions":["old"]}')
        from program_update_apply import apply_update
        with patch('installer.stop_existing',return_value=None),patch('installer.subprocess.Popen',return_value=Mock(pid=42)),patch('deployment_state.wait_ready',side_effect=OSError('new process failed')),patch('deployment_state.stop_version'),self.assertRaises(OSError):apply_update(source,install,data)
        self.assertEqual(json.loads((install/'installations.json').read_text())['current'],'old')
        self.assertEqual([p.name for p in (install/'versions').iterdir()],['old']);self.assertEqual((data/'settings.json').read_text(),'{"custom":true}')
        self.assertTrue(list((install/'deployment-backups').glob('*/settings.json')))

if __name__=='__main__':unittest.main()
