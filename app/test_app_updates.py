"""Public release checks and resumable staging with isolated synthetic packages."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,io,json,hashlib,tempfile,zipfile,threading,time
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app_updates import *
from update_controller import UpdateController
from update_widgets import UpdatePanel
APP=QApplication.instance() or QApplication([])

def payload(version='0.7.3',digest='a'*64):
    tag='v'+version;name=f'bailong-desktop-pet-{version}-windows-x64.zip'
    return dict(tag_name=tag,draft=False,prerelease=False,body='# 更新\n- 测试内容',assets=[dict(name=name,size=100,state='uploaded',digest='sha256:'+digest,browser_download_url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}')])

class Response(io.BytesIO):
    def __init__(self,data,status=200,headers=None):super().__init__(data);self.status=status;self.headers=headers or {}

class ReleaseTests(unittest.TestCase):
    def test_versions_include_legacy_and_minor_carry_and_never_downgrade(self):
        self.assertGreater(version_tuple('0.7.2'),version_tuple('v0.6.50'));self.assertGreater(version_tuple('0.8.0'),version_tuple('0.7.9'));self.assertGreater(version_tuple('1.0.0'),version_tuple('0.9.9'));self.assertGreater(version_tuple('1.0.0'),version_tuple('0.10.0'))
        for v in ('0.7.2-beta','../escape','00.7.2','0.7','1;run'):
            with self.assertRaises(UpdateError):version_tuple(v)
    def test_exact_asset_and_repo_required_and_no_drafts_or_prereleases(self):
        p=payload();r=parse_release(p);self.assertEqual(r.version,'0.7.3');self.assertEqual(r.sha256,'a'*64)
        for key in ('draft','prerelease'):
            with self.assertRaises(NoRelease):parse_release(dict(p,**{key:True}))
        p['assets'][0]['browser_download_url']='https://github.com/other/repo/package.zip'
        with self.assertRaises(UpdateError):parse_release(p)
    def test_partial_asset_missing_windows_package_and_bad_size_refused(self):
        for changes in (dict(state='starter'),dict(size=True),dict(size=-2),dict(size=MAX_PACKAGE+1),dict(name='Source code.zip')):
            p=payload();p['assets'][0].update(changes)
            with self.assertRaises(UpdateError):parse_release(p)
    def test_checksum_fallback_is_bound_to_exact_asset_name(self):
        p=payload();p['assets'][0]['digest']=None;name=p['assets'][0]['name'];url=f'https://github.com/{REPOSITORY}/releases/download/v0.7.3/SHA256SUMS.txt'
        p['assets'].append(dict(name='SHA256SUMS.txt',size=100,state='uploaded',browser_download_url=url))
        def fetch(address,headers=None):return Response(json.dumps(p).encode() if address==API else ('b'*64+'  '+name+'\n').encode())
        self.assertEqual(check_release('0.7.2',fetch).sha256,'b'*64)
        def wrong(address,headers=None):return Response(json.dumps(p).encode() if address==API else ('b'*64+'  wrong.zip\n').encode())
        with self.assertRaises(UpdateError):check_release('0.7.2',wrong)
    def test_older_public_version_does_not_require_download_or_checksum_fetch(self):
        p=payload('0.6.50');p['assets'][0]['digest']=None;calls=[]
        def fetch(address,headers=None):calls.append(address);return Response(json.dumps(p).encode())
        self.assertEqual(check_release('0.7.2',fetch).version,'0.6.50');self.assertEqual(calls,[API])
    def test_network_rate_limit_and_no_release_messages(self):
        for code,kind in ((403,UpdateError),(429,UpdateError),(404,NoRelease),(500,UpdateError)):
            with patch('app_updates.read_small',side_effect=urllib.error.HTTPError(API,code,'test',{},None)), patch('app_updates.release_without_api',side_effect=UpdateError('offline fallback')):
                with self.assertRaises(kind):check_release('0.7.2')
    def test_redirects_only_to_https_github_storage(self):
        self.assertTrue(allowed_redirect('https://release-assets.githubusercontent.com/file'))
        for url in ('http://github.com/file','https://github.com.evil.test/file','https://user:pass@github.com/file','https://localhost/file','file:///C:/payload.exe'):
            self.assertFalse(allowed_redirect(url))

class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cache=self.root/'updates';self.exe=b'MZ'+os.urandom(700000);self.bytes=self.package(self.exe)
        self.release=replace(parse_release(payload()),size=len(self.bytes),sha256=hashlib.sha256(self.bytes).hexdigest());self.calls=[]
    def tearDown(self):self.tmp.cleanup()
    def package(self,data,entry='release/白龙桌宠-0.7.3-一键部署.exe',extra=False):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_STORED) as z:
            z.writestr(entry,data)
            if extra:z.writestr('other/白龙桌宠-0.7.3-一键部署.exe',data)
        return stream.getvalue()
    def opener(self,url,headers=None):
        headers=headers or {};self.calls.append(dict(headers));offset=int(headers['Range'][6:-1]) if headers.get('Range') else 0
        return Response(self.bytes[offset:],206 if offset else 200,{'Content-Range':f'bytes {offset}-{len(self.bytes)-1}/{len(self.bytes)}'})
    def test_stages_only_the_correct_exe_and_records_verified_hashes(self):
        phases=[];path=stage_installer(self.release,self.cache,lambda n,total,phase:phases.append(phase),opener=self.opener)
        self.assertEqual(path.read_bytes(),self.exe);self.assertEqual(path.parent.parent,self.cache)
        receipt=json.loads((path.parent/'receipt.json').read_text());self.assertEqual(receipt['installerSha256'],hashlib.sha256(self.exe).hexdigest());self.assertEqual(receipt['archiveSha256'],self.release.sha256)
        self.assertIn('verifying',phases);self.assertEqual(phases[-1],'ready')
    def test_cancel_and_range_resume_keep_progress_and_exact_final_data(self):
        cancelled=threading.Event();data=self.bytes
        class CancelResponse(Response):
            def read(self,n=-1):value=super().read(n);cancelled.set();return value
        with self.assertRaises(UpdateCancelled):stage_installer(self.release,self.cache,cancel=cancelled.is_set,opener=lambda *args:CancelResponse(data))
        paths=cache_paths(self.cache,'0.7.3');offset=paths['part'].stat().st_size;self.assertGreater(offset,0);self.assertLess(offset,len(data));self.assertFalse(paths['installer'].exists())
        path=stage_installer(self.release,self.cache,opener=self.opener);self.assertEqual(self.calls[0]['Range'],f'bytes={offset}-');self.assertEqual(path.read_bytes(),self.exe)
    def test_server_ignoring_range_restarts_cleanly(self):
        cache_paths(self.cache,'0.7.3')['part'].write_bytes(self.bytes[:20])
        path=stage_installer(self.release,self.cache,opener=lambda *args:Response(self.bytes));self.assertEqual(path.read_bytes(),self.exe)
    def test_invalid_content_range_does_not_append_wrong_bytes(self):
        paths=cache_paths(self.cache,'0.7.3');paths['part'].write_bytes(self.bytes[:20])
        with self.assertRaises(UpdateError):stage_installer(self.release,self.cache,opener=lambda *args:Response(self.bytes,206,{'Content-Range':'bytes 0-4/5'}))
        self.assertEqual(paths['part'].read_bytes(),self.bytes[:20])
    def test_truncated_download_can_continue(self):
        with self.assertRaises(UpdateError):stage_installer(self.release,self.cache,opener=lambda *args:Response(self.bytes[:100]))
        self.assertEqual(stage_installer(self.release,self.cache,opener=self.opener).read_bytes(),self.exe)
    def test_bad_hash_never_stages_installer_and_can_retry(self):
        wrong=replace(self.release,sha256='0'*64)
        with self.assertRaises(UpdateError):stage_installer(wrong,self.cache,opener=self.opener)
        paths=cache_paths(self.cache,'0.7.3');self.assertFalse(paths['part'].exists());self.assertFalse(paths['installer'].exists())
        self.assertEqual(stage_installer(self.release,self.cache,opener=self.opener).read_bytes(),self.exe)
    def test_zip_paths_duplicate_exes_and_non_executable_refused(self):
        for data in (self.package(self.exe,'../../白龙桌宠-0.7.3-一键部署.exe'),self.package(self.exe,'C:/白龙桌宠-0.7.3-一键部署.exe'),self.package(self.exe,extra=True),self.package(b'not executable')):
            cache=Path(tempfile.mkdtemp(dir=self.root));r=replace(self.release,size=len(data),sha256=hashlib.sha256(data).hexdigest())
            with self.assertRaises(UpdateError):stage_installer(r,cache,opener=lambda *args:Response(data))
            self.assertFalse(cache_paths(cache,'0.7.3')['installer'].exists())
        self.assertFalse((self.root/'白龙桌宠-0.7.3-一键部署.exe').exists())
    def test_cached_verified_archive_is_reused_without_network(self):
        stage_installer(self.release,self.cache,opener=self.opener)
        with patch('app_updates.open_url',side_effect=AssertionError('Network not needed')):
            self.assertEqual(stage_installer(self.release,self.cache,opener=lambda *args:(_ for _ in ()).throw(AssertionError())).read_bytes(),self.exe)
    def test_completed_cache_cleanup_preserves_unrelated_files_and_future_downloads(self):
        stage_installer(self.release,self.cache,opener=self.opener);unrelated=self.cache/'notes.txt';unrelated.write_text('keep');future=self.cache/'0.7.4';future.mkdir();(future/'package.zip.part').write_bytes(b'keep')
        prune_completed(self.cache,'0.7.3');self.assertFalse((self.cache/'0.7.3').exists());self.assertTrue(unrelated.exists());self.assertEqual((future/'package.zip.part').read_bytes(),b'keep')
    def test_locked_installer_keeps_receipt_for_a_later_cleanup(self):
        stage_installer(self.release,self.cache,opener=self.opener);paths=cache_paths(self.cache,'0.7.3');unlink=Path.unlink
        def locked(path,*args,**kwargs):
            if path==paths['installer']:raise PermissionError('running installer')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',locked):prune_completed(self.cache,'0.7.3')
        self.assertTrue(paths['receipt'].is_file());self.assertTrue(paths['installer'].is_file())
        prune_completed(self.cache,'0.7.3');self.assertFalse(paths['receipt'].parent.exists())

class ControllerTests(unittest.TestCase):
    def wait(self,condition):
        deadline=time.monotonic()+3
        while not condition():APP.processEvents();time.sleep(.003);self.assertLess(time.monotonic(),deadline)
    def test_check_only_never_downloads_and_older_public_version_cannot_install(self):
        with tempfile.TemporaryDirectory() as folder:
            c=UpdateController('0.7.2',Path(folder),allow_auto=False);panel=UpdatePanel(c);panel.show()
            try:
                with patch('update_controller.check_release',return_value=parse_release(payload('0.6.50'))),patch('update_controller.stage_installer') as download:
                    c.check();self.wait(lambda:c.job is None);download.assert_not_called();self.assertEqual(c.state['phase'],'current');self.assertFalse(c.download_install());self.assertIn('本机版本较新',panel.status.text());self.assertFalse(panel.install.isVisible())
            finally:c.shutdown();panel.close();panel.deleteLater();c.deleteLater();APP.processEvents()
    def test_new_release_requires_click_and_emits_installer_only_after_verified_job(self):
        with tempfile.TemporaryDirectory() as folder:
            c=UpdateController('0.7.2',Path(folder),allow_auto=False);ready=[];c.installerReady.connect(ready.append)
            try:
                with patch('update_controller.check_release',return_value=parse_release(payload())),patch('update_controller.stage_installer',return_value=Path(folder)/'installer.exe') as download:
                    c.check();self.wait(lambda:c.job is None);self.assertEqual(c.state['phase'],'available');download.assert_not_called();self.assertEqual(ready,[])
                    c.download_install();self.wait(lambda:c.job is None);self.assertEqual(ready,[str(Path(folder)/'installer.exe')])
            finally:c.shutdown();c.deleteLater();APP.processEvents()
    def test_duplicate_checks_are_coalesced_and_shutdown_is_async(self):
        gate=threading.Event()
        def slow(*args,**kw):gate.wait(2);return parse_release(payload())
        with tempfile.TemporaryDirectory() as folder:
            c=UpdateController('0.7.2',Path(folder),allow_auto=False)
            try:
                with patch('update_controller.check_release',side_effect=slow) as query:
                    self.assertTrue(c.check());self.assertFalse(c.check());self.assertFalse(c.shutdown());gate.set();self.wait(lambda:c.job is None);self.assertEqual(query.call_count,1);self.assertFalse(c.download_install())
            finally:gate.set();c.shutdown();c.deleteLater();APP.processEvents()
    def test_automatic_checks_stop_when_disabled_and_never_auto_download(self):
        with tempfile.TemporaryDirectory() as folder:
            c=UpdateController('0.7.2',Path(folder),allow_auto=True)
            try:c.configure(True);self.assertTrue(c.initial.isActive());c.configure(False);self.assertFalse(c.initial.isActive());self.assertFalse(c.timer.isActive());self.assertFalse(c.install_requested)
            finally:c.shutdown();c.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
