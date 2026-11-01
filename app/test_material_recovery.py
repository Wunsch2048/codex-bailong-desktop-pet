"""Tiny local-only fixtures for upgrade recovery; no real downloads/user assets."""
import hashlib,io,json,os,tempfile,time,unittest,zipfile,threading
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from material_store import MaterialStore,MaterialError

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bailong-material-recovery-');self.root=Path(self.tmp.name)
        self.install=self.root/'install';self.app=self.install/'versions/current';self.old=self.install/'versions/old/outputs/白龙桌宠素材';self.state=self.root/'state'
        (self.app/'app').mkdir(parents=True);self.state.mkdir()
        self.payload={'素材清单.json':b'{"idle":{"id":"idle","file":"idle.webp"},"variants":[]}', 'idle.webp':b'unchanged-idle-bytes','added.webp':b'new-action-for-current-catalog'}
        self.files=[dict(path=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in self.payload.items()]
        self.archive=self.pack();self.requests=[]
        self.catalog=dict(schema=1,tiers={tier:dict(id='current'+tier,files=self.files if tier=='light' else [dict(path='hd-only.webp',bytes=99,sha256='a'*64)],bytes=sum(f['bytes'] for f in self.files),archiveBytes=len(self.archive),archiveSha256=hashlib.sha256(self.archive).hexdigest()) for tier in ('light','hd')})
        (self.app/'app/material_catalog.json').write_text(json.dumps(self.catalog),encoding='utf-8')
        (self.install/'installations.json').write_text(json.dumps(dict(current='current',versions=['current','old'])),encoding='utf-8')
        self.store=MaterialStore(self.app,self.state)
    def tearDown(self):self.tmp.cleanup()
    def pack(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as archive:
            for name,data in self.payload.items():archive.writestr(name,data)
        return buf.getvalue()
    def populate(self,root,omit=()):
        for name,data in self.payload.items():
            if name in omit:continue
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    def transport(self,url,headers):
        requested=headers.get('Range');self.requests.append(requested)
        if requested:
            start,end=map(int,requested[6:].split('-'));data=self.archive[start:end+1]
            response=io.BytesIO(data);response.status=206;response.headers={'Content-Range':f'bytes {start}-{end}/{len(self.archive)}','Content-Length':str(len(data))}
        else:
            response=io.BytesIO(self.archive);response.status=200;response.headers={'Content-Length':str(len(self.archive))}
        return response
    def test_complete_registered_old_install_recovers_without_network_or_preference_change(self):
        self.populate(self.old)
        with patch('material_store.open_url',side_effect=AssertionError('network')):
            root=self.store.recover_local('light')
        self.assertIsNotNone(root);self.store.verify(root,'light')
        self.store.activate('light',root,save_preference=False)
        self.assertFalse(self.store.preference.exists());self.assertEqual(self.store.current,'light')
        for name,data in self.payload.items():self.assertEqual((self.old/name).read_bytes(),data)
    def test_incomplete_old_install_stays_unready_without_network(self):
        self.populate(self.old,omit=['added.webp'])
        with patch('material_store.open_url',side_effect=AssertionError('network')):
            self.assertIsNone(self.store.recover_local('light'))
        self.assertIsNone(self.store.current);self.assertFalse(self.store.available('light'))
        self.assertEqual((self.old/'idle.webp').read_bytes(),self.payload['idle.webp'])
    def test_all_names_present_but_truncated_embedded_light_repairs_in_cache(self):
        embedded=self.app/'outputs/白龙桌宠素材';self.populate(embedded)
        (embedded/'idle.webp').write_bytes(b'truncated')
        self.store=MaterialStore(self.app,self.state)
        self.assertIsNone(self.store.current);self.assertFalse(self.store.known_available('light'))
        root=self.store.ensure('light',opener=self.transport)
        self.assertNotEqual(root,embedded);self.store.verify(root,'light')
        self.store.activate('light',root)
        self.assertEqual((embedded/'idle.webp').read_bytes(),b'truncated')
        restored=MaterialStore(self.app,self.state)
        self.assertEqual(restored.current,'light');self.assertEqual(restored.root,root)
    def test_complete_cache_without_receipt_recovers_and_retains_old_directory(self):
        root=self.store.tier_root('light');self.populate(root)
        self.assertFalse(self.store.available('light'))
        self.assertEqual(self.store.recover_local('light'),root);self.store.verify(root,'light')
        retained=list(self.store.cache.glob('retained-*'));self.assertEqual(len(retained),1)
        self.assertEqual((retained[0]/'idle.webp').read_bytes(),self.payload['idle.webp'])
    def test_corrupt_inactive_target_repairs_without_deleting_old_bytes(self):
        root=self.store.tier_root('light');self.populate(root);self.populate(self.old)
        bad=b'x'*len(self.payload['idle.webp']);(root/'idle.webp').write_bytes(bad)
        self.assertEqual(self.store.recover_local('light'),root);self.store.verify(root,'light')
        retained=list(self.store.cache.glob('retained-*'));self.assertEqual((retained[0]/'idle.webp').read_bytes(),bad)
    def test_corrupt_bytes_without_a_good_source_are_not_authorized_by_same_size(self):
        root=self.store.tier_root('light');self.populate(root);(root/'idle.webp').write_bytes(b'x'*len(self.payload['idle.webp']))
        self.assertIsNone(self.store.recover_local('light'));self.assertIsNone(self.store.current)
    def test_partial_legacy_files_are_reused_when_user_requests_missing_entries(self):
        self.populate(self.old,omit=['added.webp'])
        root=self.store.ensure('light',opener=self.transport);self.store.verify(root,'light')
        self.assertTrue(self.requests);self.assertTrue(all(request is not None for request in self.requests))
        self.assertEqual((self.old/'idle.webp').read_bytes(),self.payload['idle.webp'])
    def test_explicit_card_only_never_runs_automatic_recovery(self):
        self.populate(self.old);self.store.preference.write_text('{"tier":"light","cardOnly":true}',encoding='utf-8')
        store=MaterialStore(self.app,self.state);before=store.preference.read_bytes()
        with patch('material_incremental.candidate_roots',side_effect=AssertionError('scan')):self.assertIsNone(store.recover_local('light'))
        self.assertIsNone(store.current);self.assertEqual(store.preference.read_bytes(),before)
    def test_automatic_light_fallback_keeps_saved_hd_preference(self):
        self.populate(self.old);self.store.preference.write_text('{"tier":"hd","cardOnly":false}',encoding='utf-8')
        store=MaterialStore(self.app,self.state);before=store.preference.read_bytes()
        root=store.recover_local('light');store.activate('light',root,save_preference=False)
        self.assertEqual(store.preferred,'hd');self.assertEqual(store.current,'light');self.assertEqual(store.preference.read_bytes(),before)
    def test_active_invalid_target_is_not_replaced(self):
        root=self.store.tier_root('light');self.populate(root,omit=['added.webp']);self.store.current='light';self.store.root=root
        stage=self.store.cache/'stage';self.populate(stage)
        with self.assertRaises(MaterialError):self.store._commit(stage,root,'light')
        self.assertTrue((root/'idle.webp').exists());self.assertTrue(stage.exists())
    def test_failed_publication_restores_retained_directory(self):
        target=self.store.tier_root('light');self.populate(target,omit=['added.webp']);stage=self.store.cache/'stage';self.populate(stage)
        original=Path.replace
        def replace(path,dest):
            if path==stage:raise OSError('publication failed')
            return original(path,dest)
        with patch.object(Path,'replace',replace),self.assertRaises(OSError):self.store._commit(stage,target,'light')
        self.assertEqual((target/'idle.webp').read_bytes(),self.payload['idle.webp']);self.assertTrue(stage.exists())
    def test_manifest_traversal_does_not_recover_unregistered_directory(self):
        outside=self.install/'outside/outputs/白龙桌宠素材';self.populate(outside)
        (self.install/'installations.json').write_text('{"versions":["../outside"]}',encoding='utf-8')
        self.assertIsNone(self.store.recover_local('light'));self.assertTrue((outside/'idle.webp').exists())
    def test_old_install_discovery_has_a_bounded_manifest_prefix(self):
        self.populate(self.old)
        names=['missing'+str(i) for i in range(32)]+['old']
        (self.install/'installations.json').write_text(json.dumps(dict(versions=names)),encoding='utf-8')
        self.assertIsNone(self.store.recover_local('light'))
    def test_cancelled_local_recovery_preserves_old_resources(self):
        from app_updates import UpdateCancelled
        self.populate(self.old);event=threading.Event()
        with self.assertRaises(UpdateCancelled):self.store.recover_local('light',event.is_set,lambda *args:event.set())
        self.assertIsNone(self.store.current);self.assertEqual((self.old/'idle.webp').read_bytes(),self.payload['idle.webp'])
    def test_automatic_handoff_does_not_enable_panel_or_change_saved_preferences(self):
        from desktop import DesktopPet
        self.populate(self.old);root=self.store.recover_local('light')
        fake=SimpleNamespace(_pending_material=('light',root),_pending_material_automatic=True,_pending_animation=None,material_store=self.store,asset_root=Path('previous'),manifest={},idles=[],variants=[],sustained=Mock(),player=None,cache=Mock(),pinned_frames=Mock(),gate=SimpleNamespace(state='idle'),reactions=Mock(),_materials_missing=True,apply_settings=Mock(),idle=Mock(),apply_surface_visibility=Mock(),materials=Mock(),settings=dict(character_visible=True,bubble=False))
        with patch('PIL.Image.open'),patch('desktop.StreamPlayer',return_value=Mock()):
            self.assertTrue(DesktopPet.apply_material(fake))
        fake.apply_settings.assert_not_called();fake.apply_surface_visibility.assert_called_once()
        self.assertFalse(fake.settings['bubble']);self.assertFalse(self.store.preference.exists())
    def test_real_pet_renders_recovered_webp_without_enabling_hidden_panel(self):
        from PIL import Image
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QImage
        from desktop import DesktopPet
        app=QApplication.instance() or QApplication([])
        image=io.BytesIO();Image.new('RGBA',(16,16),(70,160,210,255)).save(image,format='WEBP',lossless=True)
        self.payload['idle.webp']=image.getvalue()
        self.catalog['tiers']['light']['files']=[dict(path=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in self.payload.items()]
        self.catalog['tiers']['light']['bytes']=sum(len(b) for b in self.payload.values())
        (self.app/'app/material_catalog.json').write_text(json.dumps(self.catalog),encoding='utf-8');self.populate(self.old)
        config=self.state/'settings.json';config.write_text('{"schema":2,"character_visible":true,"bubble":false,"wandering":false,"random_actions":false}',encoding='utf-8')
        real_store=MaterialStore;pet=None;handles=[]
        for module in ('desktop','enhanced'):
            for key,value in (('STATE_DIR',self.state),('CONFIG',config)):
                handle=patch(module+'.'+key,value);handle.start();handles.append(handle)
        try:
            with patch('material_store.MaterialStore',side_effect=lambda app_root,state:real_store(self.app,state)),patch('codex_connection.saved_paths',return_value={}),patch('codex_connection.data_home',return_value=self.root/'codex'),patch('codex_startup.enabled',return_value=False):
                pet=DesktopPet(monitor=False)
                self.assertTrue(pet._materials_missing);self.assertFalse(pet.isVisible())
                root=pet.material_store.recover_local('light');pet.queue_material('light',root,automatic=True)
                deadline=time.monotonic()+3;painted=False
                while time.monotonic()<deadline:
                    app.processEvents();frame=pet.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                    painted=any(bytes(frame.bits())[3::4])
                    if painted:break
                    time.sleep(.005)
                self.assertTrue(pet.isVisible());self.assertTrue(painted);self.assertFalse(pet._materials_missing)
                self.assertFalse(pet.settings['bubble']);self.assertFalse(pet.bubble.isVisible())
                self.assertFalse(pet.material_store.preference.exists())
        finally:
            if pet:pet.close();pet.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
            for handle in reversed(handles):handle.stop()
    def test_recovered_callback_does_not_override_new_hidden_character_choice(self):
        from PySide6.QtCore import QObject
        from material_controller import MaterialController
        parent=QObject();parent.settings=dict(character_visible=False,character='builtin')
        controller=MaterialController(self.store,parent);controller.job=SimpleNamespace(cancel=threading.Event())
        ready=[];controller.recovered.connect(lambda *args:ready.append(args))
        controller._recovered('light',Path('verified-local-root'))
        self.assertFalse(ready);self.assertIsNone(self.store.current);controller.job=None
    def test_background_recovery_and_unready_panel_are_distinct_from_card_only(self):
        from PySide6.QtWidgets import QApplication
        from material_controller import MaterialController,MaterialPanel
        app=QApplication.instance() or QApplication([]);self.populate(self.old)
        controller=MaterialController(self.store);panel=MaterialPanel(controller)
        self.assertIn('动画待补齐',panel.summary.text());ready=[];controller.recovered.connect(lambda *args:ready.append(args))
        try:
            self.assertTrue(controller.recover_local());deadline=time.monotonic()+3
            while controller.job is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertIsNone(controller.job);self.assertEqual(len(ready),1)
            self.store.activate(*ready[0],save_preference=False);controller.applied();self.assertIn('轻量',panel.summary.text())
        finally:
            controller.shutdown();panel.close();panel.deleteLater();app.processEvents()

if __name__=='__main__':unittest.main()
