"""Verified program-only updates; borrow only unchanged animation files."""
import json,os,re,shutil,stat,time,zipfile
from pathlib import Path,PurePosixPath
from app_updates import UpdateError,check_cancel,digest_file,version_tuple,download_archive
from desktop_core import atomic_json

PREFIX='outputs/白龙桌宠素材/'
class MaterialMismatch(UpdateError):pass

def stage_failure(error,exe_written=False):
    """Report an OS security error, without declaring every missing file a virus."""
    current=error;seen=set()
    while current is not None and id(current) not in seen:
        seen.add(id(current));code=getattr(current,'winerror',None)
        if code in (225,226):
            return f'Windows安全防护阻止或移除了更新文件（错误{code}）。请查看保护历史记录，并反馈检测名称。'
        name=getattr(current,'filename',None)
        if exe_written and isinstance(current,FileNotFoundError) and name and Path(name).name.casefold()=='bailongenhanced.exe':
            return '主程序解压后无法读取，可能被安全软件隔离。请查看保护历史记录；尚不能据此判断误报。'
        current=current.__cause__ or current.__context__
    return str(error)[:120]

def cleanup_stage(path,base,preparation_failed):
    try:remove_owned_tree(path,base)
    except (OSError,UpdateError):
        # Quarantine/access errors during cleanup must not replace the original
        # actionable extraction failure with a generic worker error.
        if not preparation_failed:raise

def safe(root,name):
    if not isinstance(name,str) or '\\' in name or ':' in name or not name:raise UpdateError('程序包路径无效')
    parts=name.split('/');p=PurePosixPath(name)
    if p.is_absolute() or any(v in ('','.','..') or v[-1:] in ('.',' ') or any(ord(c)<32 for c in v) or v.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))} for v in parts):raise UpdateError('程序包路径无效')
    root=Path(root).absolute();target=root.joinpath(*parts)
    for q in (target,*target.parents):
        if q==root.parent:break
        if q.is_symlink() or q.is_junction():raise UpdateError('程序包路径不能是链接或联接')
    if not target.resolve().is_relative_to(root.resolve()):raise UpdateError('程序包路径越界')
    return target

def manifest_files(data):
    files=data.get('files',{})
    if not isinstance(files,dict) or not 1<=len(files)<=20000:raise UpdateError('程序清单无效')
    seen=set()
    for name,f in files.items():
        safe(Path.cwd(),name)
        if name.casefold() in seen or name in ('payload-manifest.json','program-update.json'):raise UpdateError('程序清单路径重复')
        seen.add(name.casefold())
        if not isinstance(f,dict) or type(f.get('bytes')) is not int or not 0<=f['bytes']<2**31 or not re.fullmatch('[0-9a-f]{64}',str(f.get('sha256',''))):raise UpdateError('程序清单校验值无效')
    if 'BailongEnhanced.exe' not in files or 'app/material_catalog.json' not in files:raise UpdateError('程序包缺少必要文件')
    return files

def local_materials(app_root,material_id,cancel=lambda:False):
    root=Path(app_root)
    try:
        catalog=json.loads((root/'app/material_catalog.json').read_text(encoding='utf-8'));tier=catalog['tiers']['light']
        if catalog.get('schema')!=1 or tier['id']!=material_id:raise MaterialMismatch('素材版本变化，需使用完整安装包')
        assets=root/'outputs/白龙桌宠素材'
        dev=root/'build/materials/light'
        if dev.is_dir():assets=dev
        if not 1<=len(tier['files'])<=128:raise MaterialMismatch('本地素材目录无效')
        seen=set()
        for f in tier['files']:
            check_cancel(cancel);p=safe(assets,f['path'])
            if f['path'].casefold() in seen:raise MaterialMismatch('本地素材目录重复')
            seen.add(f['path'].casefold())
            if p.stat().st_size!=f['bytes'] or digest_file(p,cancel)!=f['sha256']:raise MaterialMismatch('本地素材缺失或损坏，需使用完整安装包')
        return assets,tier
    except (OSError,ValueError,KeyError,TypeError) as exc:raise MaterialMismatch('本地素材不完整，需使用完整安装包') from exc

def program_paths(root,version):
    version_tuple(version);root=Path(root).absolute();base=safe(root,version+'/program');base.mkdir(parents=True,exist_ok=True)
    return {k:safe(base,n) for k,n in dict(part='package.zip.part',archive='package.zip',source='source',staging='source.pending',receipt='receipt.json').items()}

def remove_owned_tree(path,base):
    path=Path(path).absolute();base=Path(base).absolute()
    if path.parent.resolve()!=base.resolve() or path.name not in ('source','source.pending') or path.is_symlink() or path.is_junction():raise UpdateError('程序暂存清理范围无效')
    if path.exists():
        for p in path.rglob('*'):
            if p.is_symlink() or p.is_junction():raise UpdateError('程序暂存目录存在异常链接')
        shutil.rmtree(path)

def stage_program(release,cache,app_root,progress=lambda *a:None,cancel=lambda:False,opener=None):
    if release.kind!='program' or not release.material_id:raise UpdateError('纯程序更新信息缺失')
    progress(0,release.size,'materials');assets=tier=None
    try:assets,tier=local_materials(app_root,release.material_id,cancel)
    except MaterialMismatch:
        if not release.optional_materials:raise
    paths=program_paths(cache,release.version)
    from app_updates import open_url
    archive=download_archive(release,paths,progress,cancel,opener or open_url)
    pending=paths['staging'];source=paths['source'];remove_owned_tree(pending,pending.parent);pending.mkdir()
    exe_written=False;preparation_failed=False
    try:
        check_cancel(cancel);progress(release.size,release.size,'extracting')
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist();names={i.filename for i in infos}
            if len(infos)>20002 or len(names)!=len(infos):raise UpdateError('程序包文件重复或数量异常')
            for i in infos:
                safe(pending,i.filename)
                if i.is_dir() or stat.S_ISLNK(i.external_attr>>16):raise UpdateError('程序包包含异常条目')
            def small(name):
                info=z.getinfo(name)
                if info.file_size>8*1024*1024:raise UpdateError('程序包说明过大')
                return json.loads(z.read(info))
            descriptor=small('program-update.json');manifest=small('payload-manifest.json');files=manifest_files(manifest)
            if descriptor.get('schema')!=1 or descriptor.get('kind')!='program' or descriptor.get('version')!=release.version or manifest.get('version')!=release.version or descriptor.get('materialId')!=release.material_id:raise UpdateError('程序包版本或素材标识不匹配')
            optional=release.optional_materials and descriptor.get('optionalMaterials') is True
            if assets is None:
                if not optional:raise MaterialMismatch('程序包不支持无动画更新')
                target_catalog=small('app/material_catalog.json')
                tier=target_catalog['tiers']['light']
                if target_catalog.get('schema')!=1 or tier.get('id')!=release.material_id or not 1<=len(tier['files'])<=128:raise UpdateError('目标素材目录无效')
            media={PREFIX+f['path']:dict(bytes=f['bytes'],sha256=f['sha256']) for f in tier['files']}
            if {n:f for n,f in files.items() if n.startswith(PREFIX)}!=media:raise MaterialMismatch('程序包素材清单变化，需使用完整安装包')
            core={n:f for n,f in files.items() if n not in media}
            if names!=set(core)|{'program-update.json','payload-manifest.json'}:raise UpdateError('程序包缺少文件或混入素材')
            if sum(f['bytes'] for f in core.values())>2**31:raise UpdateError('程序包展开体积异常')
            for n,f in core.items():
                check_cancel(cancel);info=z.getinfo(n)
                if info.file_size!=f['bytes']:raise UpdateError('程序包文件大小异常')
                p=safe(pending,n);p.parent.mkdir(parents=True,exist_ok=True)
                with z.open(info) as src,p.open('wb') as dst:
                    written=0
                    while chunk:=src.read(1024*1024):
                        check_cancel(cancel);written+=len(chunk)
                        if written>f['bytes']:raise UpdateError('程序包展开大小异常')
                        dst.write(chunk)
                if n=='BailongEnhanced.exe':exe_written=True
                if digest_file(p,cancel)!=f['sha256']:raise UpdateError('程序包文件校验失败')
            cat=json.loads((pending/'app/material_catalog.json').read_text(encoding='utf-8'))
            if cat.get('schema')!=1 or cat['tiers']['light']!=tier:raise MaterialMismatch('目标素材规格不同，需使用完整安装包')
            for n,f in media.items():
                if assets is None:continue
                check_cancel(cancel);old=safe(assets,n[len(PREFIX):]);new=safe(pending,n);new.parent.mkdir(parents=True,exist_ok=True)
                if old.stat().st_size!=f['bytes'] or digest_file(old,cancel)!=f['sha256']:raise MaterialMismatch('素材在更新期间变化，改用完整安装包')
                try:os.link(old,new)
                except OSError:shutil.copy2(old,new)
            if assets is None:manifest=dict(manifest,files=core)
            atomic_json(pending/'payload-manifest.json',manifest)
        from directory_deploy import inspect_source
        inspect_source(pending,release.version);check_cancel(cancel)
        remove_owned_tree(source,source.parent);pending.replace(source)
        atomic_json(paths['receipt'],dict(kind='program',version=release.version,archiveSha256=release.sha256,exeSha256=files['BailongEnhanced.exe']['sha256'],manifestSha256=digest_file(source/'payload-manifest.json'),materialId=release.material_id))
        progress(release.size,release.size,'ready');return source
    except (OSError,ValueError,KeyError,zipfile.BadZipFile,RuntimeError) as exc:
        preparation_failed=True
        raise UpdateError('程序包准备失败，当前版本未改动：'+stage_failure(exc,exe_written)) from exc
    finally:cleanup_stage(pending,pending.parent,preparation_failed)

def verify_ready(source,cache,version,archive_sha=None,full=True):
    paths=program_paths(cache,version);source=Path(source).absolute()
    if source.resolve()!=paths['source'].resolve():raise UpdateError('程序更新暂存位置无效')
    receipt=json.loads(paths['receipt'].read_text(encoding='utf-8'))
    if receipt.get('kind')!='program' or receipt.get('version')!=version or archive_sha and receipt.get('archiveSha256')!=archive_sha:raise UpdateError('程序更新校验凭证失效')
    if digest_file(source/'payload-manifest.json')!=receipt['manifestSha256'] or digest_file(source/'BailongEnhanced.exe')!=receipt['exeSha256']:raise UpdateError('程序更新文件在校验后变化')
    if full:
        from directory_deploy import inspect_source
        inspect_source(source,version)
    return source/'BailongEnhanced.exe'

def prune_program_cache(root,current):
    root=Path(root)
    if not root.is_dir() or root.is_symlink() or root.is_junction():return
    # The cache may be removed between the directory check and enumeration.
    try:entries=tuple(root.iterdir())
    except OSError:return
    for p in entries:
        try:
            if version_tuple(p.name)>version_tuple(current) or p.is_symlink() or p.is_junction():continue
            base=p/'program';receipt=base/'receipt.json'
            if not receipt.is_file():continue
            data=json.loads(receipt.read_text(encoding='utf-8'))
            if data.get('kind')!='program' or data.get('version')!=p.name:continue
            paths=program_paths(root,p.name)
            # The newly started app may clean up while its update helper is
            # still confirming readiness. Never partially remove that runtime.
            import psutil
            executable=(paths['source']/'BailongEnhanced.exe').resolve()
            running=False
            for process in psutil.process_iter(['exe']):
                try:
                    if process.info.get('exe') and Path(process.info['exe']).resolve()==executable:running=True;break
                except (OSError,psutil.Error):continue
            if running:continue
            for key in ('staging','source'):remove_owned_tree(paths[key],base)
            for key in ('part','archive'):paths[key].unlink(missing_ok=True)
            receipt.unlink();base.rmdir()
            if not any(p.iterdir()):p.rmdir()
        except (OSError,ValueError,UpdateError):continue
