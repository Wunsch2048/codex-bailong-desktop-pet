"""Read public releases and stage a verified installer; never install silently."""
from dataclasses import dataclass,replace
from pathlib import Path,PurePosixPath
import hashlib,json,os,re,sys,urllib.request,urllib.error,urllib.parse,zipfile,time

REPOSITORY='Wunsch2048/codex-bailong-desktop-pet'
API='https://api.github.com/repos/'+REPOSITORY+'/releases/latest'
MAX_PACKAGE=2_147_483_647
class UpdateError(Exception):pass
class UpdateCancelled(UpdateError):pass
class NoRelease(UpdateError):pass

def program_updates_supported():
    """程序安装与历史安装维护只支持 Windows，动画资源独立判断"""
    return sys.platform=='win32'

def version_tuple(value):
    match=re.fullmatch(r'v?((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))',str(value))
    if not match:raise UpdateError('版本号格式不受支持')
    return tuple(int(v) for v in match[1].split('.'))

def release_url(tag):return 'https://github.com/'+REPOSITORY+'/releases/tag/'+tag
def asset_url(value,tag,name):
    p=urllib.parse.urlsplit(str(value));expected='/'+REPOSITORY+'/releases/download/'+tag+'/'
    if p.scheme!='https' or p.hostname!='github.com' or p.username or p.password or p.port not in (None,443) or not p.path.startswith(expected) or urllib.parse.unquote(p.path[len(expected):])!=name or p.query or p.fragment:
        raise UpdateError('更新文件地址与本项目不匹配')
    return str(value)

@dataclass(frozen=True)
class Release:
    version:str
    tag:str
    asset_name:str
    download_url:str
    size:int
    sha256:str
    notes:str=''
    published:str=''
    checksum_url:str=''
    kind:str='full'
    material_id:str=''
    program_info_url:str=''
    fallback:object=None
    reason:str=''
    optional_materials:bool=False
    animation_info_name:str=''
    animation_info_url:str=''
    animation_info_sha:str=''
    animation_info_size:int=0
    animation_catalog:object=None
    animation_tier:str=''
    minimum_program_version:str=''
    @property
    def url(self):return release_url(self.tag)

def parse_release(data,*,allow_program=True):
    """按平台能力选择公开附件，动画模式不选择程序或完整安装包"""
    if not isinstance(data,dict) or data.get('draft') or data.get('prerelease'):raise NoRelease('暂无公开稳定版本')
    tag=str(data.get('tag_name',''));version='.'.join(map(str,version_tuple(tag)))
    names=(f'bailong-desktop-pet-{version}-windows-x64.zip',f'白龙桌宠-{version}-一键部署包.zip')
    assets=data.get('assets') or []
    if not allow_program:
        animation_name=f'bailong-desktop-pet-{version}-animation.json'
        assets=[a for a in assets if a.get('name') in (animation_name,'SHA256SUMS.txt')]
        if not any(a.get('name')==animation_name and a.get('state')=='uploaded' for a in assets):raise NoRelease('该公开版没有动画补丁；当前平台的程序请手动更新')
    asset=next((a for name in names for a in assets if a.get('name')==name and a.get('state')=='uploaded'),None)
    full_asset=asset
    program_name=f'bailong-desktop-pet-{version}-program.zip';info_name=f'bailong-desktop-pet-{version}-program.json'
    program=next((a for a in assets if a.get('name')==program_name and a.get('state')=='uploaded'),None)
    info=next((a for a in assets if a.get('name')==info_name and a.get('state')=='uploaded' and type(a.get('size')) is int and 0<a['size']<=65536),None)
    animation_name=f'bailong-desktop-pet-{version}-animation.json'
    animation=next((a for a in assets if a.get('name')==animation_name and a.get('state')=='uploaded' and type(a.get('size')) is int and 0<a['size']<=131072),None)
    if not asset and not (program and info) and not animation:raise UpdateError('该版本尚未提供可安装的更新包')
    if program and info:asset=program
    elif animation:asset=animation
    size=asset.get('size')
    if type(size) is not int or not 0<size<=MAX_PACKAGE:raise UpdateError('更新文件大小异常')
    digest=str(asset.get('digest') or '').lower();sha=digest[7:] if re.fullmatch(r'sha256:[0-9a-f]{64}',digest) else ''
    checksum=next((a for a in assets if a.get('name')=='SHA256SUMS.txt' and a.get('state')=='uploaded' and 0<a.get('size',0)<=65536),None)
    result=Release(version,tag,asset['name'],asset_url(asset.get('browser_download_url'),tag,asset['name']),size,sha,str(data.get('body') or '')[:20000],str(data.get('published_at') or ''),asset_url(checksum['browser_download_url'],tag,'SHA256SUMS.txt') if checksum else '')
    if program and info:
        fallback=parse_release(dict(data,assets=[a for a in assets if a is not program and a is not info and a is not animation])) if full_asset else None
        result=replace(result,kind='program',program_info_url=asset_url(info['browser_download_url'],tag,info_name),fallback=fallback)
    elif animation:result=replace(result,kind='animation')
    if animation:
        digest=str(animation.get('digest') or '')
        result=replace(result,animation_info_name=animation_name,animation_info_url=asset_url(animation.get('browser_download_url'),tag,animation_name),
            animation_info_sha=digest[7:] if re.fullmatch('sha256:[0-9a-f]{64}',digest) else '',animation_info_size=animation['size'])
    return result

def allowed_redirect(url):
    p=urllib.parse.urlsplit(url);host=p.hostname or ''
    allowed=host in ('api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com') or bool(re.fullmatch(r'github-production-release-asset-[a-z0-9-]+\.s3\.amazonaws\.com',host))
    return p.scheme=='https' and allowed and not p.username and not p.password and p.port in (None,443)

class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed_redirect(newurl):raise UpdateError('更新下载被重定向到未识别的地址')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def open_url(url,headers=None):
    if not allowed_redirect(url):raise UpdateError('更新地址不受支持')
    request=urllib.request.Request(url,headers={'User-Agent':'Bailong-Desktop-Updater','Accept':'application/vnd.github+json' if url==API else 'application/octet-stream',**(headers or {})})
    return urllib.request.build_opener(GitHubRedirect()).open(request,timeout=12)

def check_cancel(cancel):
    if cancel():raise UpdateCancelled('下载已暂停，可稍后继续')

def read_small(url,limit,opener=open_url,cancel=lambda:False):
    check_cancel(cancel)
    with opener(url) as response:
        data=response.read(limit+1)
    check_cancel(cancel)
    if len(data)>limit:raise UpdateError('更新信息过大，请到 GitHub 查看')
    return data

def ensure_checksum(release,opener=open_url,cancel=lambda:False):
    if release.sha256:return release
    if not release.checksum_url:raise UpdateError('该版本没有可验证的校验值，暂不能在应用内安装')
    text=read_small(release.checksum_url,65536,opener,cancel).decode('utf-8-sig')
    found=next((m[1].lower() for line in text.splitlines() if (m:=re.fullmatch(r'([0-9A-Fa-f]{64})\s+\*?(.+)',line)) and m[2]==release.asset_name),None)
    if not found:raise UpdateError('安装包校验值缺失，暂不能在应用内安装')
    return replace(release,sha256=found)

def release_without_api(opener=open_url,cancel=lambda:False,*,allow_program=True):
    """备用下载通道保持相同的平台筛选、仓库和 SHA 校验"""
    sums=read_small('https://github.com/'+REPOSITORY+'/releases/latest/download/SHA256SUMS.txt',65536,opener,cancel).decode('utf-8-sig')
    if not allow_program:return patch_without_api(sums,opener,cancel,allow_program=False)
    candidates=[]
    for line in sums.splitlines():
        match=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(bailong-desktop-pet-(\d+\.\d+\.\d+)-windows-x64\.zip)',line)
        if match:candidates.append((match[1].lower(),match[2],match[3]))
    if not candidates:
        return patch_without_api(sums,opener,cancel)
    if len(candidates)!=1:raise UpdateError('备用通道缺少唯一完整包校验值')
    sha,name,version=candidates[0];version='.'.join(map(str,version_tuple(version)));tag='v'+version
    base='https://github.com/'+REPOSITORY+'/releases/download/'+tag+'/'
    check_cancel(cancel)
    with opener(base+name,{'Range':'bytes=0-0'}) as response:
        content_range=response.headers.get('Content-Range','')
        match=re.fullmatch(r'bytes 0-\d+/(\d+)',content_range)
        if getattr(response,'status',200)==206 and not match:raise UpdateError('备用通道文件大小响应无效')
        size=int(match[1]) if match else int(response.headers.get('Content-Length','0'))
    if not 0<size<=MAX_PACKAGE:raise UpdateError('备用更新包大小无效')
    full=Release(version,tag,name,asset_url(base+name,tag,name),size,sha,
        '通过 GitHub 下载通道核验更新。完整更新说明请点击“在 GitHub 查看”。',checksum_url=base+'SHA256SUMS.txt',reason='GitHub API 暂不可用，已通过下载通道核验更新')
    records={m[2]:m[1].lower() for line in sums.splitlines() if (m:=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)',line))}
    if f'bailong-desktop-pet-{version}-animation.json' in records:return patch_without_api(sums,opener,cancel)
    program=f'bailong-desktop-pet-{version}-program.zip';info=f'bailong-desktop-pet-{version}-program.json'
    if program in records and info in records:
        try:
            raw=read_small(base+info,65536,opener,cancel)
            if hashlib.sha256(raw).hexdigest()!=records[info]:raise UpdateError('程序包描述校验失败')
            with opener(base+program,{'Range':'bytes=0-0'}) as response:
                match=re.fullmatch(r'bytes 0-\d+/(\d+)',response.headers.get('Content-Range',''))
                if getattr(response,'status',200)==206 and not match:raise UpdateError('程序包大小响应无效')
                n=int(match[1]) if match else int(response.headers.get('Content-Length','0'))
            if not 0<n<=MAX_PACKAGE:raise UpdateError('程序包大小无效')
            return replace(full,asset_name=program,download_url=asset_url(base+program,tag,program),size=n,sha256=records[program],kind='program',program_info_url=base+info,fallback=full)
        except UpdateCancelled:raise
        except (UpdateError,OSError,ValueError):pass
    return full

def patch_without_api(sums,opener,cancel,*,allow_program=True):
    """只读取当前平台允许的补丁描述和载荷信息"""
    records={m[2]:m[1].lower() for line in sums.splitlines() if (m:=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)',line))}
    kinds='(?:program|animation)' if allow_program else 'animation'
    versions={m[1] for name in records if (m:=re.fullmatch(r'bailong-desktop-pet-(\d+\.\d+\.\d+)-'+kinds+r'\.json',name))}
    if not versions and not allow_program:raise NoRelease('该公开版没有动画补丁；当前平台的程序请手动更新')
    if len(versions)!=1:raise UpdateError('备用通道补丁版本不明确')
    version=versions.pop();version_tuple(version);tag='v'+version
    base='https://github.com/'+REPOSITORY+'/releases/download/'+tag+'/'
    assets=[]
    for suffix in (('program.json','animation.json') if allow_program else ('animation.json',)):
        name=f'bailong-desktop-pet-{version}-{suffix}'
        if name not in records:continue
        raw=read_small(base+name,131072,opener,cancel)
        if hashlib.sha256(raw).hexdigest()!=records[name]:raise UpdateError('备用通道补丁描述校验失败')
        assets.append(dict(name=name,size=len(raw),state='uploaded',browser_download_url=base+name,digest='sha256:'+records[name]))
    name=f'bailong-desktop-pet-{version}-program.zip'
    if allow_program and name in records:
        check_cancel(cancel)
        with opener(base+name,{'Range':'bytes=0-0'}) as response:
            match=re.fullmatch(r'bytes 0-\d+/(\d+)',response.headers.get('Content-Range',''))
            if getattr(response,'status',200)==206 and not match:raise UpdateError('程序包大小响应无效')
            size=int(match[1]) if match else int(response.headers.get('Content-Length','0'))
        assets.append(dict(name=name,size=size,state='uploaded',browser_download_url=base+name,digest='sha256:'+records[name]))
    assets.append(dict(name='SHA256SUMS.txt',size=len(sums.encode()),state='uploaded',browser_download_url=base+'SHA256SUMS.txt'))
    return replace(parse_release(dict(tag_name=tag,assets=assets,body='补丁内容请在 GitHub 查看。'),allow_program=allow_program),reason='已通过 GitHub 下载通道核验补丁')

def prepare_release(release,current,opener,cancel,app_root,state_dir=None,program_version=None):
    if version_tuple(release.version)>version_tuple(current):
        if release.kind=='program':
            from program_updates import local_materials,MaterialMismatch
            from pet import ROOT
            try:
                info=json.loads(read_small(release.program_info_url,65536,opener,cancel))
                if info.get('schema')!=1 or info.get('kind')!='program' or info.get('version')!=release.version or not re.fullmatch('[0-9a-f]{24}',str(info.get('materialId',''))):raise MaterialMismatch('纯程序包说明不匹配')
                optional=info.get('optionalMaterials') is True
                if not optional:local_materials(app_root or ROOT,info['materialId'],cancel)
                release=ensure_checksum(replace(release,material_id=info['materialId'],optional_materials=optional),opener,cancel)
            except UpdateCancelled:raise
            except (UpdateError,OSError,ValueError,KeyError,AttributeError) as exc:
                if not release.fallback:raise UpdateError('本机暂不能使用该纯程序包，且该版本未提供完整包') from exc
                release=replace(release.fallback,reason='本地素材不兼容或程序包说明不可用，改用完整安装包')
        if release.animation_info_url:
            from animation_updates import prepare
            state_dir=state_dir or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced'
            release=prepare(release,release.version if release.kind=='program' else (program_version or current),state_dir,opener,cancel)
        release=ensure_checksum(release,opener,cancel)
    return release

def check_release(current,opener=open_url,cancel=lambda:False,app_root=None,state_dir=None,program_version=None,*,allow_program=True):
    """在主通道和备用通道中使用相同的附件能力与实际程序版本"""
    try:
        release=parse_release(json.loads(read_small(API,2_000_000,opener,cancel)),allow_program=allow_program)
        return prepare_release(release,current,opener,cancel,app_root,state_dir,program_version)
    except urllib.error.HTTPError as exc:
        if exc.code==404:raise NoRelease('暂无公开稳定版本') from None
        if exc.code in (403,429):
            try:return prepare_release(release_without_api(opener,cancel,allow_program=allow_program),current,opener,cancel,app_root,state_dir,program_version)
            except UpdateCancelled:raise
            except UpdateError:raise
            except (OSError,ValueError,AttributeError,UnicodeError):
                limited=exc.code==429 or exc.headers and exc.headers.get('X-RateLimit-Remaining')=='0'
                raise UpdateError('GitHub API 检查次数暂时受限，备用下载通道也未连接成功；可在 GitHub 手动下载或稍后重试' if limited else 'GitHub 拒绝更新请求，备用通道也未连接成功；请检查网络后重试') from None
        raise UpdateError('获取更新信息失败，请稍后重试') from None
    except (OSError,ValueError,UnicodeError):raise UpdateError('暂时无法连接 GitHub，请稍后重试') from None

def cache_paths(root,version):
    version_tuple(version);root=Path(root).absolute();root.mkdir(parents=True,exist_ok=True)
    if root.is_symlink() or root.is_junction():raise UpdateError('更新缓存目录不受支持')
    base=root/version
    if base.is_symlink() or base.is_junction():raise UpdateError('更新缓存目录不受支持')
    base.mkdir(exist_ok=True)
    paths=dict(part=base/'package.zip.part',archive=base/'package.zip',installer=base/f'白龙桌宠-{version}-一键部署.exe',staging=base/'installer.download',receipt=base/'receipt.json')
    for path in paths.values():
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root.resolve()):raise UpdateError('更新缓存路径异常')
    return paths

def digest_file(path,cancel=lambda:False):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):check_cancel(cancel);digest.update(chunk)
    return digest.hexdigest()

def download_archive(release,paths,progress=lambda *a:None,cancel=lambda:False,opener=open_url):
    if not re.fullmatch('[0-9a-f]{64}',release.sha256):raise UpdateError('更新包校验值缺失')
    archive=paths['archive'];part=paths['part']
    if not archive.exists():
        offset=part.stat().st_size if part.exists() else 0
        if offset>release.size:part.unlink();offset=0
        if offset<release.size:
            check_cancel(cancel);progress(offset,release.size,'downloading')
            with opener(release.download_url,{'Range':f'bytes={offset}-'} if offset else {}) as response:
                status=getattr(response,'status',200)
                if offset and status==206:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if not match or int(match[1])!=offset or int(match[3])!=release.size:raise UpdateError('续传响应异常，请稍后重试')
                elif status==200:offset=0
                else:raise UpdateError('下载响应异常，请稍后重试')
                mode='ab' if offset else 'wb';last=0.;progress(offset,release.size,'downloading')
                with part.open(mode) as output:
                    while True:
                        check_cancel(cancel);chunk=response.read(256*1024)
                        if not chunk:break
                        offset+=len(chunk)
                        if offset>release.size:raise UpdateError('下载文件大小与发布信息不一致')
                        output.write(chunk);now=time.monotonic()
                        if now-last>=.2:progress(offset,release.size,'downloading');last=now
            if offset!=release.size:raise UpdateError('下载未完成，可稍后继续')
        progress(release.size,release.size,'verifying')
        if digest_file(part,cancel)!=release.sha256:
            part.unlink(missing_ok=True);raise UpdateError('安装包校验未通过，请重新下载')
        part.replace(archive)
    elif archive.stat().st_size!=release.size or digest_file(archive,cancel)!=release.sha256:
        archive.unlink();raise UpdateError('缓存校验未通过，请重新下载')
    return archive

def stage_installer(release,root,progress=lambda *args:None,cancel=lambda:False,opener=open_url):
    if not re.fullmatch('[0-9a-f]{64}',release.sha256):raise UpdateError('安装包校验值缺失')
    paths=cache_paths(root,release.version);archive=paths['archive'];part=paths['part']
    try:
        download_archive(release,paths,progress,cancel,opener)
        check_cancel(cancel);progress(release.size,release.size,'extracting')
        expected=f'白龙桌宠-{release.version}-一键部署.exe'
        with zipfile.ZipFile(archive) as bundle:
            entries=[item for item in bundle.infolist() if PurePosixPath(item.filename).name==expected]
            if len(entries)!=1:raise UpdateError('安装包中没有唯一的匹配安装程序')
            entry=entries[0];parts=PurePosixPath(entry.filename)
            if parts.is_absolute() or '..' in parts.parts or any(':' in part for part in parts.parts) or '\\' in entry.filename or entry.is_dir() or not 2<=entry.file_size<=MAX_PACKAGE or (entry.external_attr>>16)&0o170000==0o120000:raise UpdateError('安装程序路径或大小异常')
            sha=hashlib.sha256();first=True
            with bundle.open(entry) as source,paths['staging'].open('wb') as output:
                while chunk:=source.read(1024*1024):
                    check_cancel(cancel)
                    if first and not chunk.startswith(b'MZ'):raise UpdateError('安装程序格式不正确')
                    first=False;sha.update(chunk);output.write(chunk)
            paths['staging'].replace(paths['installer'])
        from desktop_core import atomic_json
        atomic_json(paths['receipt'],dict(version=release.version,archiveSha256=release.sha256,installerSha256=sha.hexdigest(),asset=release.asset_name))
        progress(release.size,release.size,'ready');return paths['installer']
    except UpdateError:raise
    except (OSError,zipfile.BadZipFile,RuntimeError):raise UpdateError('下载或解压失败，可稍后重试；当前版本未改动') from None
    finally:paths['staging'].unlink(missing_ok=True)

def prune_completed(root,current):
    from program_updates import prune_program_cache
    prune_program_cache(root,current)
    root=Path(root)
    if not root.is_dir() or root.is_symlink() or root.is_junction():return
    try:entries=tuple(root.iterdir())
    except OSError:return
    for base in entries:
        if not base.is_dir() or base.is_symlink() or base.is_junction():continue
        try:
            if version_tuple(base.name)>version_tuple(current):continue
            paths=cache_paths(root,base.name)
            if not paths['receipt'].is_file():continue
            receipt=json.loads(paths['receipt'].read_text(encoding='utf-8'))
            if receipt.get('version')!=base.name:continue
            for key,path in paths.items():
                if key=='receipt':continue
                try:path.unlink(missing_ok=True)
                except OSError:pass
            if not any(path.exists() for key,path in paths.items() if key!='receipt'):paths['receipt'].unlink(missing_ok=True)
            try:base.rmdir()
            except OSError:pass
        except (OSError,ValueError,UpdateError):continue
