import hashlib,io,json,tempfile,threading,unittest,zipfile
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from material_store import MaterialStore,MaterialError,checked
from app_updates import UpdateCancelled

class MaterialStoreTests(unittest.TestCase):
    def test_non_object_preferences_do_not_break_restart_or_overwrite_source(self):
        for value in (None,[],"hd",0):
            with self.subTest(value=value):
                content=json.dumps(value).encode('utf-8');self.store.preference.write_bytes(content)
                restored=MaterialStore(self.app,self.state)
                self.assertEqual(restored.preferred,'light')
                self.assertEqual(restored.current,'light')
                self.assertEqual(self.store.preference.read_bytes(),content)
    def test_cached_display_hint_does_not_authorize_corrupt_materials(self):
        root=self.store.import_hd(self.source)
        self.assertTrue(self.store.known_available('hd'))
        with patch.object(self.store,'_check_available',side_effect=AssertionError('unexpected scan')):
            self.assertTrue(self.store.known_available('hd'))
        (root/'quality/action.webp').write_bytes(b'damaged')
        with self.assertRaises(MaterialError):self.store.activate('hd',root)
        self.assertFalse(self.store.known_available('hd'))
        self.assertEqual(self.store.current,'light')
    def test_cached_hint_is_initialized_for_existing_hd_even_when_using_light(self):
        self.store.import_hd(self.source)
        other=MaterialStore(self.app,self.state)
        self.assertEqual(other.current,'light');self.assertTrue(other.known_available('hd'))
    def test_default_runtime_log_is_outside_immutable_program_payload(self):
        from quota import log_attempt
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'LOCALAPPDATA':folder}),patch('sys.frozen',True,create=True),patch('sys.executable',str(Path(folder)/'immutable-program/pet.exe')):
            log_attempt(1,.01)
            self.assertTrue((Path(folder)/'BailongEnhanced/额度查询日志.jsonl').is_file())
            self.assertFalse((Path(folder)/'immutable-program').exists())
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.app=self.root/'app-root';self.state=self.root/'state'
        (self.app/'app').mkdir(parents=True);self.state.mkdir();self.source=self.root/'hd';self.source.mkdir()
        self.payload={'素材清单.json':b'{"character":"fixture"}','quality/action.webp':b'high-definition-fixture'}
        self.files=[dict(path=p,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for p,data in self.payload.items()]
        for p,data in self.payload.items():
            f=self.source/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
        self.catalog=dict(schema=1,default='light',tiers={tier:dict(id='fixture'+tier,resolution=512 if tier=='light' else 720,files=self.files,bytes=sum(r['bytes'] for r in self.files)) for tier in ('light','hd')})
        hd=self.catalog['tiers']['hd'];hd['url']='https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/materials-fixturehd/bailong-hd-fixturehd.zip'
        (self.app/'app/material_catalog.json').write_text(json.dumps(self.catalog),encoding='utf-8')
        self.base=self.app/'outputs/白龙桌宠素材';self.base.mkdir(parents=True)
        for p,data in self.payload.items():
            f=self.base/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
        self.store=MaterialStore(self.app,self.state)
    def tearDown(self):self.tmp.cleanup()
    def archive(self,payload=None,extras=None):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
            for p,data in (payload or self.payload).items():z.writestr(p,data)
            for p,data in extras or []:z.writestr(p,data)
        return buffer.getvalue()
    def response(self,data,length=None):
        r=io.BytesIO(data);r.headers={'Content-Length':str(len(data) if length is None else length)};return r
    def test_fresh_default_light_and_missing_hd_preference_falls_back(self):
        self.assertEqual(self.store.current,'light');self.assertEqual(self.store.root,self.base)
        self.store.preference.write_text('{"tier":"hd"}')
        self.assertEqual(MaterialStore(self.app,self.state).current,'light')
    def test_seed_and_restart_reuses_hd_without_copying_or_network(self):
        root=self.store.import_hd(self.source);self.store.activate('hd',root)
        new=MaterialStore(self.app,self.state);self.assertEqual(new.current,'hd');self.assertTrue(new.available('hd'))
        self.assertEqual(new.ensure('hd',opener=lambda *args:self.fail('unexpected network')),root)
        self.store.activate('light',self.base);self.assertEqual(MaterialStore(self.app,self.state).current,'light')
        self.assertTrue(root.is_dir());self.assertTrue((self.source/'素材清单.json').is_file())
    def test_app_upgrade_reuses_content_cache(self):
        root=self.store.import_hd(self.source);self.store.activate('hd',root)
        (self.app/'version.txt').write_text('unrelated new program version')
        self.assertEqual(MaterialStore(self.app,self.state).root,root)
    def test_hardlink_final_name_alias_does_not_discard_verified_hd_cache(self):
        root=self.store.import_hd(self.source);asset=root/'quality/action.webp';original=Path.resolve
        def alias(path,*args,**kwargs):
            return original(self.source/'quality/action.webp') if path==asset else original(path,*args,**kwargs)
        with patch.object(Path,'resolve',alias):
            self.assertEqual(checked(root,'quality/action.webp'),asset)
            self.assertTrue(self.store.available('hd'));self.store.activate('hd',root)
            self.assertEqual(MaterialStore(self.app,self.state).current,'hd')
            from desktop import DesktopPet
            from types import SimpleNamespace
            from sustained_assets import profile_paths
            self.assertEqual(DesktopPet.asset_path(SimpleNamespace(asset_root=root),{'file':'quality/action.webp'}),asset)
            item=dict(file='quality/action.webp',sustained=dict(start=0,end=2,sourceFrames=5,seamFrames=2,seamFile='quality/action.webp'))
            self.assertEqual(profile_paths(root,item)['source'],asset)
    def test_download_verify_commit_and_progress(self):
        events=[];root=self.store.ensure('hd',progress=lambda n,t,p:events.append((n,t,p)),opener=lambda *a:self.response(self.archive()))
        self.assertTrue(self.store.available('hd'));self.assertEqual(self.store.current,'light')
        self.assertEqual({p for n,t,p in events},{'verifying','downloading'})
        self.store.activate('hd',root);self.assertEqual(self.store.current,'hd')
        self.assertEqual(list(self.store.cache.glob('download-*')),[])
    def test_real_http_stream_via_injected_transport(self):
        data=self.archive()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def log_message(self,*a):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            self.store.ensure('hd',opener=lambda *a:urlopen('http://127.0.0.1:'+str(server.server_port),timeout=3))
            self.assertTrue(self.store.available('hd'))
        finally:server.shutdown();server.server_close();thread.join()
    def test_missing_download_address_does_not_claim_unpublished_or_change_preference(self):
        def missing(*a):raise HTTPError('fixture',404,'missing',{},None)
        with self.assertRaisesRegex(MaterialError,'下载地址暂不可用') as failure:self.store.ensure('hd',opener=missing)
        self.assertNotIn('尚未公开',str(failure.exception))
        self.assertEqual(self.store.current,'light');self.assertFalse(self.store.preference.exists())
    def test_bad_hash_never_activates(self):
        wrong=dict(self.payload);wrong['quality/action.webp']=b'X'*len(wrong['quality/action.webp'])
        with self.assertRaisesRegex(MaterialError,'校验失败'):self.store.ensure('hd',opener=lambda *a:self.response(self.archive(wrong)))
        self.assertFalse(self.store.available('hd'));self.assertEqual(self.store.current,'light')
    def test_extra_traversal_duplicate_and_symlink_entries_rejected(self):
        for extra in [('unknown.exe',b'xx'),('../escape',b'xx'),('素材清单.json',b'xx')]:
            with self.subTest(extra=extra),self.assertRaises(MaterialError):self.store.ensure('hd',opener=lambda *a:self.response(self.archive(extras=[extra])))
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:
            for p,data in self.payload.items():
                info=zipfile.ZipInfo(p);info.external_attr=(0o120777<<16);z.writestr(info,data)
        with self.assertRaises(MaterialError):self.store.ensure('hd',opener=lambda *a:self.response(buffer.getvalue()))
        self.assertFalse((self.root/'escape').exists());self.assertFalse(self.store.available('hd'))
    def test_partial_download_and_oversized_header_rejected(self):
        data=self.archive()
        for size in (len(data)+50,2**32):
            with self.assertRaises(MaterialError):self.store.ensure('hd',opener=lambda *a:self.response(data,size))
        self.assertFalse(self.store.available('hd'))
    def test_cancel_after_download_and_verification_keeps_active_tier(self):
        event=threading.Event()
        with self.assertRaises(UpdateCancelled):self.store.ensure('hd',cancel=event.is_set,progress=lambda *a:event.set(),opener=lambda *a:self.response(self.archive()))
        self.assertEqual(self.store.current,'light');self.assertFalse(self.store.available('hd'));self.assertEqual(list(self.store.cache.glob('download-*')),[])
        with self.assertRaises(UpdateCancelled):self.store.import_hd(self.source,cancel=lambda:True)
    def test_cached_file_change_invalidates_receipt(self):
        root=self.store.import_hd(self.source)
        (root/'quality/action.webp').write_bytes(b'corrupt')
        self.assertFalse(self.store.available('hd'))
        with self.assertRaises(MaterialError):self.store.activate('hd',root)
    def test_invalid_download_origin_and_paths(self):
        self.store.catalog['tiers']['hd']['url']='https://example.org/data.zip'
        with self.assertRaises(MaterialError):self.store.ensure('hd')
        for p in ('../x','/x','x\\y','C:/x','a/../x','a//x'):
            with self.subTest(p=p),self.assertRaises(MaterialError):checked(self.base,p)
    def test_light_validation_failure_preserves_hd(self):
        root=self.store.import_hd(self.source);self.store.activate('hd',root)
        (self.base/'quality/action.webp').write_bytes(b'bad')
        with self.assertRaises(MaterialError):self.store.ensure('light')
        self.assertEqual(self.store.current,'hd')

if __name__=='__main__':unittest.main()
