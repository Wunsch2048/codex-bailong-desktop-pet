"""Immutable, content-addressed built-in materials, independent of app versions."""
import hashlib,json,logging,os,re,shutil,stat,tempfile,time,uuid,zipfile
from contextlib import contextmanager,nullcontext
from http.client import HTTPException
from pathlib import Path,PurePosixPath
from urllib.error import HTTPError,URLError
from desktop_core import atomic_json
from app_updates import open_url,UpdateCancelled

class MaterialError(ValueError):pass
class MaterialPhaseError(MaterialError):pass

def file_in_use(error):
    return getattr(error,'winerror',None) in (32,33)

def retry_material_io(operation,cancel=lambda:False):
    """Retry a single restartable operation on a Windows sharing violation."""
    for delay in (.1,.25,.5,None):
        cancelled(cancel)
        try:
            return operation()
        except OSError as error:
            if delay is None or not file_in_use(error):
                raise
            time.sleep(delay)

@contextmanager
def material_phase(label):
    try:
        yield
    except MaterialPhaseError:
        raise
    except MaterialError as error:
        raise MaterialPhaseError(f'{label}失败：{error}') from error
    except OSError as error:
        if file_in_use(error):
            detail='文件正被占用，请稍后再试'
        else:
            detail=error.strerror or str(error)
        raise MaterialPhaseError(f'{label}失败：{detail}') from error

@contextmanager
def material_workspace(cache,prefix,cancel=lambda:False):
    with material_phase('准备素材目录'):
        retry_material_io(lambda:cache.mkdir(parents=True,exist_ok=True),cancel)
        workspace=retry_material_io(lambda:tempfile.TemporaryDirectory(prefix=prefix,dir=cache),cancel)
    try:
        yield Path(workspace.name)
    finally:
        try:
            retry_material_io(workspace.cleanup)
        except OSError as error:
            # A verified install has already been committed, or an earlier
            # failure is propagating. Cleanup must not change either result.
            logging.getLogger(__name__).warning('素材临时目录清理失败（%s）',error)

def checked(root,name):
    if not isinstance(name,str) or '\\' in name or ':' in name:raise MaterialError('素材路径无效')
    p=PurePosixPath(name)
    if p.is_absolute() or any(v in ('','.','..') for v in name.split('/')):raise MaterialError('素材路径无效')
    root=Path(root);target=root.joinpath(*p.parts)
    if root.is_symlink() or any(v.is_symlink() or getattr(v,'is_junction',lambda:False)() for v in [target,*target.parents] if v!=root.parent and (v==root or root in v.parents)):raise MaterialError('素材目录不能使用链接跳转')
    # Windows may report another name of a multiply hard-linked file. All
    # reparse points above are rejected; validate its directory, not that alias.
    if not target.parent.resolve().is_relative_to(root.resolve()):raise MaterialError('素材路径越界')
    return target

def cancelled(cancel):
    if cancel():raise UpdateCancelled('素材操作已取消，继续使用原画质')

def hash_file(path,cancel=lambda:False):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data:=stream.read(1024*1024):cancelled(cancel);h.update(data)
    return h.hexdigest()

def write_material_entry(archive,info,target,cancel):
    with material_phase('写入动画文件'):
        retry_material_io(lambda:target.parent.mkdir(parents=True,exist_ok=True),cancel)
        output=retry_material_io(lambda:open_download_file(target,'wb'),cancel)
    with output,archive.open(info) as source:
        count=0
        while data:=source.read(256*1024):
            cancelled(cancel);count+=len(data)
            if count>info.file_size:raise MaterialError('解压大小异常')
            with material_phase('写入动画文件'):output.write(data)
        if count!=info.file_size:raise MaterialError('解压内容不完整')
        with material_phase('写入动画文件'):output.flush()

@contextmanager
def download_checkpoint(cache,tier,url,size,digest,cancel):
    from PySide6.QtCore import QLockFile

    identity=hashlib.sha256(f'{url}\n{size}\n{digest}'.encode()).hexdigest()
    with material_phase('准备下载缓存'):
        directory=checked(cache,f'partial-downloads/{tier}-{identity}')
        retry_material_io(lambda:directory.mkdir(parents=True,exist_ok=True),cancel)
        lock=QLockFile(str(checked(directory,'download.lock')))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):raise MaterialError('同一画质的下载正在进行')
    try:
        yield directory
    finally:
        lock.unlock()

def discard_archive(archive):
    try:retry_material_io(lambda:archive.unlink(missing_ok=True))
    except OSError as error:logging.getLogger(__name__).warning('素材下载缓存清理失败（%s）',error)

def open_download_file(path,mode):
    try:status=path.lstat()
    except FileNotFoundError:pass
    else:
        if not stat.S_ISREG(status.st_mode) or status.st_nlink!=1:
            raise MaterialError('下载缓存文件类型不受支持')
    return path.open(mode)

def check_download_tree(stage,files):
    """Only catalog entries and their parent directories may be published."""
    expected={stage / entry['path'] for entry in files}
    directories={parent for path in expected for parent in path.parents if stage in parent.parents}
    allowed=expected|directories|{stage/'.verified.json'}
    pending=[stage]
    while pending:
        for path in pending.pop().iterdir():
            if path not in allowed or path.is_symlink() or path.is_junction():
                raise MaterialError('下载缓存含有未列入清单的内容')
            if path in directories:
                if not path.is_dir():raise MaterialError('素材目录结构无效')
                pending.append(path)
            elif not path.is_file():raise MaterialError('素材文件类型无效')

def download_material_archive(url,archive,maximum,expected_size,opener,cancel,progress):
    headers={'Accept':'application/octet-stream','Accept-Encoding':'identity'}
    offset=0
    if expected_size:
        with material_phase('读取下载缓存'):
            try:offset=retry_material_io(lambda:archive.stat().st_size,cancel)
            except FileNotFoundError:pass
        if offset==expected_size:return
        if offset>expected_size:offset=0
    cancelled(cancel)
    try:
        response=opener(url,dict(headers,Range=f'bytes={offset}-') if offset else headers)
    except HTTPError as exc:
        if not offset or exc.code not in (400,405,416):raise
        exc.close()
        cancelled(cancel)
        response=opener(url,headers);offset=0
    with response:
        status=getattr(response,'status',200)
        if response.headers.get('Content-Encoding','identity').lower()!='identity':
            raise MaterialError('下载素材失败：响应编码不受支持')
        if status==206 and offset:
            wanted=f'bytes {offset}-{expected_size-1}/{expected_size}'
            if response.headers.get('Content-Range')!=wanted:
                raise MaterialError('下载素材失败：续传响应范围异常')
        elif status==200:
            offset=0
        else:
            raise MaterialError('下载素材失败：响应状态异常')
        length=response.headers.get('Content-Length')
        if length is not None:
            try:length=int(length)
            except ValueError as exc:raise MaterialError('下载素材失败：素材下载大小异常') from exc
            if not 0<=length<=maximum or (expected_size and length!=expected_size-offset):
                raise MaterialError('下载素材失败：素材下载大小异常')
        total=expected_size or length or 0
        cancelled(cancel)
        with material_phase('写入下载文件'):
            output=retry_material_io(lambda:open_download_file(archive,'ab' if offset else 'wb'),cancel)
        with output:
            progress(offset,total,'downloading')
            while True:
                cancelled(cancel)
                data=response.read(256*1024)
                if not data:break
                offset+=len(data)
                if offset>(total or maximum):raise MaterialError('下载素材失败：素材下载超出上限')
                with material_phase('写入下载文件'):output.write(data)
                progress(offset,total,'downloading')
            with material_phase('写入下载文件'):output.flush()
        if total and offset!=total:raise MaterialError('下载素材失败：下载未完成，请重新点击下载继续')

class MaterialStore:
    def __init__(self,app_root,state_dir,catalog_override=None):
        self._known_availability={}
        self.app_root=Path(app_root);self.state=Path(state_dir);self.base=self.app_root/'outputs/白龙桌宠素材'
        from storage_locations import material_root
        self.location_error=''
        try:self.cache=material_root(self.state)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.cache=self.state/'materials';self.location_error='动画目录配置不可读，请重新选择存储位置'
        self.preference=self.state/'material-preferences.json'
        catalog_path=self.app_root/'app/material_catalog.json'
        self.catalog=json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.is_file() else None
        self.bundled_catalog=self.catalog;self.patch_previous=None
        self.embedded_light_id=self.catalog['tiers']['light']['id'] if self.catalog else None
        if catalog_override is None:
            from animation_updates import load_override
            from version import VERSION
            overlay=load_override(VERSION,self.state,self.bundled_catalog)
            if overlay:self.catalog=overlay['catalog'];self.patch_previous=overlay.get('previous')
        else:self.catalog=catalog_override
        if self.catalog:
            if self.catalog.get('schema')!=1:raise MaterialError('素材目录版本不受支持')
            for tier in self.catalog['tiers'].values():
                if not tier['id'].isalnum() or len(tier['files'])>128:raise MaterialError('素材目录无效')
                for f in tier['files']:
                    checked(self.base,f['path'])
                    if not 0<f['bytes']<2**31 or len(f['sha256'])!=64:raise MaterialError('素材校验信息无效')
        try:
            prefs=json.loads(self.preference.read_text(encoding='utf-8'))
            if not isinstance(prefs,dict):raise ValueError('画质偏好应为对象')
            self.preferred=prefs['tier']
        except (OSError,ValueError,KeyError):prefs={};self.preferred='light'
        self.card_only=bool(prefs.get('cardOnly',False))
        if self.preferred not in ('light','hd'):self.preferred='light'
        self.current='light' if self.catalog else 'hd';self.root=self.base
        # Development assets are originals; frozen base is always the light tier.
        self.development=not getattr(__import__('sys'),'frozen',False) and (self.app_root/'build/materials/light/素材清单.json').is_file()
        if self.development:self.root=self.app_root/'build/materials/light'
        # Establish display-only availability before the animated UI starts.
        # Runtime/settings snapshots must never rescan all material paths.
        light_ready=self.available('light');hd_ready=self.available('hd')
        if self.catalog:
            selected=self.preferred if self.known_available(self.preferred) else 'light' if light_ready else 'hd' if hd_ready else None
            self.current=selected if not self.card_only else None
            if self.current:self.root=self.tier_root(self.current)

    def tier_root(self,tier):
        if tier not in ('light','hd'):raise MaterialError('未知素材画质')
        if tier=='light':
            embedded=self.app_root/'build/materials/light' if self.development else self.base
            spec=self.catalog['tiers']['light'] if self.catalog else None
            if spec and spec['id']==self.embedded_light_id:
                try:
                    for f in spec['files']:
                        status=checked(embedded,f['path']).stat()
                        if not stat.S_ISREG(status.st_mode) or status.st_size!=f['bytes']:break
                    else:return embedded
                except OSError:pass
        return checked(self.cache,tier+'/'+self.catalog['tiers'][tier]['id'])

    def available(self,tier):
        result=self._check_available(tier)
        self._known_availability[tier]=result
        return result

    def known_available(self,tier):
        """Last checked display hint only; never authorizes activation or reuse."""
        return self._known_availability.get(tier,False)

    def _check_available(self,tier):
        if not self.catalog:return tier=='hd'
        root=self.tier_root(tier)
        if tier=='light' and root in (self.base,self.app_root/'build/materials/light'):return (root/'素材清单.json').is_file()
        try:
            receipt=json.loads((root/'.verified.json').read_text(encoding='utf-8'))
            if receipt['id']!=self.catalog['tiers'][tier]['id']:return False
            for f in self.catalog['tiers'][tier]['files']:
                p=checked(root,f['path']);s=p.stat()
                if receipt['files'][f['path']]!=[s.st_size,s.st_mtime_ns] or s.st_size!=f['bytes']:return False
            return True
        except (OSError,ValueError,KeyError):return False

    def verify(self,root,tier,cancel=lambda:False,progress=lambda n,t,p:None):
        files=self.catalog['tiers'][tier]['files'];total=sum(f['bytes'] for f in files);done=0
        for f in files:
            cancelled(cancel);p=checked(root,f['path'])
            size=retry_material_io(lambda:p.stat().st_size,cancel)
            if size!=f['bytes'] or retry_material_io(lambda:hash_file(p,cancel),cancel)!=f['sha256']:raise MaterialError('素材校验失败：'+f['path'])
            done+=f['bytes'];progress(done,total,'verifying')
        return True

    def _receipt(self,root,tier):
        files={}
        for f in self.catalog['tiers'][tier]['files']:
            s=checked(root,f['path']).stat();files[f['path']]=[s.st_size,s.st_mtime_ns]
        atomic_json(root/'.verified.json',dict(id=self.catalog['tiers'][tier]['id'],files=files))

    def import_hd(self,source,cancel=lambda:False,progress=lambda n,t,p:None):
        """Seed from an existing verified 720px install without changing its files."""
        target=self.tier_root('hd');self.cache.mkdir(parents=True,exist_ok=True)
        self.verify(source,'hd',cancel,progress)
        if self.available('hd'):return target
        stage=self.cache/('staging-'+uuid.uuid4().hex);stage.mkdir()
        try:
            for f in self.catalog['tiers']['hd']['files']:
                cancelled(cancel);src=checked(source,f['path']);dst=checked(stage,f['path']);dst.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(src,dst)
                except OSError:shutil.copy2(src,dst)
            self.verify(stage,'hd',cancel,progress);self._receipt(stage,'hd');self._commit(stage,target)
            return target
        finally:
            if stage.exists():shutil.rmtree(stage)

    def _commit(self,stage,target,tier='hd',cancel=lambda:False):
        cancelled(cancel)
        target=Path(target);expected=checked(self.cache,tier+'/'+self.catalog['tiers'][tier]['id'])
        if target!=expected:raise MaterialError('素材缓存位置无效')
        target.parent.mkdir(parents=True,exist_ok=True)
        retained=None
        if target.exists():
            # Never change an existing cache directory while a player may read it.
            if self.available(tier):return
            if self.current and Path(self.root)==target and not self.card_only:
                raise MaterialError('当前动画正在使用，请先切换画质后修复')
            if not target.resolve().is_relative_to(self.cache.resolve()):raise MaterialError('素材缓存位置无效')
            # Explicit removal may retain metadata or a file locked by another
            # process. Keep that remainder; publish a fresh verified directory.
            retained=self.cache/('retained-'+uuid.uuid4().hex)
            retry_material_io(lambda:target.replace(retained),cancel)
        try:retry_material_io(lambda:stage.replace(target),cancel)
        except (OSError,UpdateCancelled):
            if retained and not target.exists():
                try:retry_material_io(lambda:retained.replace(target))
                except OSError:logging.getLogger(__name__).exception('原素材目录恢复失败，已保留备份')
            raise
        self._known_availability[tier]=True

    def recover_local(self,tier,cancel=lambda:False,progress=lambda n,t,p:None):
        """Recover a complete current set locally, without network or preferences."""
        if self.card_only or self.location_error or not self.catalog:return None
        if self.available(tier):return self.tier_root(tier)
        from material_incremental import candidate_roots,reuse_files
        candidates=candidate_roots(self,tier);files=self.catalog['tiers'][tier]['files']
        needed={f['bytes'] for f in files};present=set()
        # Cheap necessary condition avoids hashing gigabytes on every startup
        # when an older pack simply lacks the new manifest/actions.
        for root,names in candidates:
            for name in names:
                cancelled(cancel)
                try:present.add(checked(root,name).stat().st_size)
                except (OSError,ValueError,TypeError):pass
        if not needed.issubset(present):return None
        with material_workspace(self.cache,'recover-',cancel) as folder:
            stage=folder/'extracted'
            retry_material_io(stage.mkdir,cancel)
            reused=reuse_files(self,tier,stage,cancel,progress,candidates)
            if len(reused)!=len(files):return None
            target=self.tier_root(tier)
            self._publish_download(stage,target,tier,cancel,progress)
            return target

    def ensure(self,tier,cancel=lambda:False,progress=lambda n,t,p:None,opener=None):
        if self.location_error:raise MaterialError(self.location_error)
        if not self.catalog:raise MaterialError('当前版本没有可切换的素材目录')
        root=self.tier_root(tier)
        if self.available(tier):
            with material_phase('校验素材'):self.verify(root,tier,cancel,progress)
            return root
        spec=self.catalog['tiers'][tier]
        version=self.catalog.get('releaseVersion')
        expected=(f'https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/v{version}/bailong-desktop-pet-{version}-animation-{tier}.zip' if version else f"https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/materials-{spec['id']}/bailong-{tier}-{spec['id']}.zip")
        url=spec.get('url',expected)
        if url!=expected:raise MaterialError('高清素材下载地址无效')
        maximum=spec['bytes']+len(spec['files'])*4096+1024*1024
        size=spec.get('archiveBytes')
        digest=spec.get('archiveSha256') or ''
        resumable=type(size) is int and 0<size<=maximum and bool(re.fullmatch(r'[0-9a-f]{64}',digest))
        checkpoint=download_checkpoint(self.cache,tier,url,size,digest,cancel) if resumable else nullcontext()
        opener=opener or open_url
        with checkpoint as saved:
            if saved is not None and self.available(tier):
                with material_phase('校验素材'):self.verify(root,tier,cancel,progress)
                return root
            workspace=nullcontext(saved) if saved is not None else material_workspace(self.cache,'download-',cancel)
            with workspace as work:
                archive=checked(work,'materials.zip.part')
                stage=checked(work,'extracted')
                with material_phase('准备素材目录'):
                    retry_material_io(lambda:stage.mkdir(exist_ok=True),cancel)
                try:
                    if resumable and not archive.exists():
                        if self._resume_entries(url,spec,stage,root,tier,opener,cancel,progress):
                            return root
                    download_material_archive(url,archive,maximum,size if resumable else None,opener,cancel,progress)
                except HTTPError as exc:
                    if exc.code==404:raise MaterialError('下载素材失败：素材下载地址暂不可用，请检查程序更新后重试；已有素材保持不变') from exc
                    raise MaterialError('下载素材失败：素材服务暂时不可用，请稍后重试') from exc
                except (URLError,HTTPException,OSError) as exc:
                    message='连接中断，重新点击可继续下载' if resumable else '连接中断，请稍后重试'
                    raise MaterialError('下载素材失败：'+message) from exc
                cancelled(cancel)
                if digest:
                    with material_phase('校验压缩包'):
                        progress(size or 0,size or 0,'verifying')
                        actual_size=retry_material_io(lambda:archive.stat().st_size,cancel)
                        actual_digest=retry_material_io(lambda:hash_file(archive,cancel),cancel)
                        if actual_size!=size or actual_digest!=digest:
                            discard_archive(archive)
                            raise MaterialError('动画补丁压缩包校验失败，请重新下载')
                with material_phase('解压素材'):
                    try:
                        with retry_material_io(lambda:zipfile.ZipFile(archive),cancel) as bundle:
                            expected_files={entry['path']:entry for entry in spec['files']}
                            infos=bundle.infolist()
                            if len(infos)!=len(expected_files) or len({info.filename for info in infos})!=len(infos):
                                raise MaterialError('素材压缩包文件数量异常')
                            for info in infos:
                                cancelled(cancel)
                                target=checked(stage,info.filename)
                                if info.filename not in expected_files or info.file_size!=expected_files[info.filename]['bytes'] or stat.S_ISLNK(info.external_attr>>16) or info.is_dir():
                                    raise MaterialError('素材压缩包内容异常')
                                write_material_entry(bundle,info,target,cancel)
                    except (zipfile.BadZipFile,RuntimeError) as exc:
                        raise MaterialError('素材压缩包无效') from exc
                self._publish_download(stage,root,tier,cancel,progress)
                if resumable:
                    discard_archive(archive)
                    try:
                        for path in work.iterdir():
                            if re.fullmatch(r'entry-\d+\.part',path.name) and path.is_file():
                                discard_archive(path)
                    except OSError as error:
                        logging.getLogger(__name__).warning('素材分段缓存清理失败（%s）',error)
        return root

    def _resume_entries(self,url,spec,stage,root,tier,opener,cancel,progress):
        from material_incremental import reuse_files,extract_missing,RangeUnavailable

        with material_phase('检查已有素材'):
            completed=set()
            for entry in spec['files']:
                cancelled(cancel)
                path=checked(stage,entry['path'])
                try:
                    size=retry_material_io(lambda:path.stat().st_size,cancel)
                except FileNotFoundError:
                    continue
                if size==entry['bytes'] and retry_material_io(lambda:hash_file(path,cancel),cancel)==entry['sha256']:
                    completed.add(entry['path'])
            reused=reuse_files(self,tier,stage,cancel,progress,completed=completed)
        if not reused:return False
        if len(reused)!=len(spec['files']):
            try:
                extract_missing(url,spec,stage,reused,opener,cancel,progress)
            except RangeUnavailable:
                progress(0,spec['archiveBytes'],'downloading')
                return False
            except MaterialPhaseError:
                raise
            except MaterialError as exc:
                raise MaterialPhaseError(f'读取分段素材失败：{exc}') from exc
            except (zipfile.BadZipFile,RuntimeError) as exc:
                raise MaterialPhaseError('解压素材失败：素材压缩包无效') from exc
        self._publish_download(stage,root,tier,cancel,progress)
        return True

    def _publish_download(self,stage,root,tier,cancel,progress):
        with material_phase('校验素材'):
            check_download_tree(stage,self.catalog['tiers'][tier]['files'])
            self.verify(stage,tier,cancel,progress)
        with material_phase('安装素材'):
            retry_material_io(lambda:self._receipt(stage,tier),cancel)
            self._commit(stage,root,tier,cancel)

    def activate(self,tier,root,*,save_preference=True):
        if Path(root)!=self.tier_root(tier) or not self.available(tier):raise MaterialError('素材尚未准备完成')
        if save_preference:
            atomic_json(self.preference,dict(schema=1,tier=tier,cardOnly=False))
            self.preferred=tier;self.card_only=False
        self.current=tier;self.root=Path(root)
