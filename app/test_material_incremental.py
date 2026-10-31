import copy
import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch

from app_updates import UpdateCancelled
from material_store import MaterialStore, MaterialError
import test_material_store as fixtures


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MaterialStoreTests('test_fresh_default_light_and_missing_hd_preference_falls_back')
        self.fixture.setUp()
        self.old = self.fixture.store
        self.old_root = self.old.import_hd(self.fixture.source)
        self.payload = dict(self.fixture.payload)
        # Large unchanged item makes transfer savings measurable, rather than
        # just asserting that a helper was called.
        self.payload['quality/action.webp'] = bytes(range(256)) * 4096
        (self.old_root/'quality/action.webp').write_bytes(self.payload['quality/action.webp'])
        self.old._receipt(self.old_root, 'hd')
        self.payload['added.webp'] = b'new animation' * 4000
        self.catalog = copy.deepcopy(self.fixture.catalog)
        spec = self.catalog['tiers']['hd']
        spec['id'] = 'updatedhd'
        spec['files'] = [dict(path=p, bytes=len(b), sha256=hashlib.sha256(b).hexdigest()) for p,b in self.payload.items()]
        spec['bytes'] = sum(f['bytes'] for f in spec['files'])
        spec['url'] = 'https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/materials-updatedhd/bailong-hd-updatedhd.zip'
        self.archive = self.pack(self.payload)
        spec.update(archiveBytes=len(self.archive), archiveSha256=hashlib.sha256(self.archive).hexdigest())
        self.store = MaterialStore(self.fixture.app,self.fixture.state,catalog_override=self.catalog)
        self.requests = []; self.transferred = 0

    def tearDown(self): self.fixture.tearDown()

    def pack(self, payload, compression=zipfile.ZIP_STORED):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,'w',compression) as archive:
            for name,data in payload.items(): archive.writestr(name,data)
        return buffer.getvalue()

    def transport(self, url, headers):
        requested = headers.get('Range'); self.requests.append(requested)
        if requested:
            start,end = map(int,requested[6:].split('-'))
            data = self.archive[start:end+1]
            status = 206
            response_headers = {'Content-Range':f'bytes {start}-{end}/{len(self.archive)}','Content-Length':str(len(data))}
        else:
            data = self.archive; status = 200; response_headers = {'Content-Length':str(len(data))}
        owner = self
        class Response(io.BytesIO):
            def read(self,n=-1):
                data = super().read(n); owner.transferred += len(data); return data
        response = Response(data); response.status = status; response.headers = response_headers
        return response

    def run_download(self, **kwargs):
        return self.store.ensure('hd',opener=kwargs.pop('opener',self.transport),**kwargs)

    def test_reuses_verified_old_bytes_and_reads_only_changed_zip_entries(self):
        root = self.run_download()
        self.assertEqual((root/'added.webp').read_bytes(),self.payload['added.webp'])
        self.assertEqual((root/'quality/action.webp').read_bytes(),self.payload['quality/action.webp'])
        self.assertLess(self.transferred,len(self.archive)//4)
        self.assertNotIn(None,self.requests)
        self.assertEqual(self.store.current,'light')
        self.assertTrue(self.old_root.exists())
        # Copies, not hard links: damage to old files cannot alter the new cache.
        (self.old_root/'quality/action.webp').write_bytes(b'damage')
        self.store.verify(root,'hd')

    def test_range_ignored_falls_back_to_same_full_zip(self):
        def ignored(url,headers): return self.transport(url,{})
        root = self.run_download(opener=ignored)
        self.store.verify(root,'hd'); self.assertIn(None,self.requests)

    def test_fresh_install_downloads_full_zip(self):
        with patch('material_incremental.reuse_files',return_value=set()): root = self.run_download()
        self.assertEqual(self.requests,[None]); self.store.verify(root,'hd')

    def test_corrupt_old_file_is_downloaded_not_reused(self):
        (self.old_root/'quality/action.webp').write_bytes(b'x'*len(self.payload['quality/action.webp']))
        root = self.run_download(); self.store.verify(root,'hd')
        self.assertGreater(self.transferred,len(self.payload['quality/action.webp']))

    def test_renamed_content_and_all_local_files_need_no_network(self):
        for f in self.catalog['tiers']['hd']['files']:
            if f['path']=='quality/action.webp': f['path']='renamed.webp'
        self.catalog['tiers']['hd']['files'] = [f for f in self.catalog['tiers']['hd']['files'] if f['path']!='added.webp']
        root = self.run_download(opener=lambda *a:self.fail('all files already local'))
        self.assertEqual((root/'renamed.webp').read_bytes(),self.payload['quality/action.webp'])

    def test_bad_remote_entry_hash_never_commits(self):
        damaged = dict(self.payload); damaged['added.webp'] = b'x'*len(damaged['added.webp'])
        self.archive = self.pack(damaged)
        with self.assertRaisesRegex(MaterialError,'校验失败'): self.run_download()
        self.assertFalse(self.store.tier_root('hd').exists())
        self.assertTrue(self.old_root.exists())

    def test_cancel_during_reuse_or_download_preserves_active_resources(self):
        stop = [False]
        def progress(n,t,phase):
            if phase=='downloading': stop[0]=True
        with self.assertRaises(UpdateCancelled): self.run_download(cancel=lambda:stop[0],progress=progress)
        self.assertFalse(self.store.tier_root('hd').exists()); self.assertTrue(self.old_root.exists())

    def test_partial_range_read_never_commits(self):
        def short(url,headers):
            response = self.transport(url,headers)
            data = response.getvalue()[:-1]
            short = io.BytesIO(data); short.status=response.status; short.headers=response.headers
            return short
        with self.assertRaises(MaterialError): self.run_download(opener=short)
        self.assertFalse(self.store.tier_root('hd').exists())

    def test_deflated_zip_is_supported_without_archive_in_memory(self):
        self.archive = self.pack(self.payload,zipfile.ZIP_DEFLATED)
        spec=self.catalog['tiers']['hd']; spec.update(archiveBytes=len(self.archive),archiveSha256=hashlib.sha256(self.archive).hexdigest())
        root=self.run_download(); self.store.verify(root,'hd')

    def test_extra_zip_entries_are_rejected_before_commit(self):
        self.archive = self.pack(dict(self.payload,unexpected=b'bad'))
        self.catalog['tiers']['hd']['archiveBytes']=len(self.archive)
        with self.assertRaises(MaterialError): self.run_download()
        self.assertFalse(self.store.tier_root('hd').exists())


if __name__=='__main__': unittest.main()
