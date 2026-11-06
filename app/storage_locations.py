"""Explicit install/material locations and verified background tree migration."""
import hashlib,json,os,shutil,sys,time,uuid
from pathlib import Path,PurePosixPath

MARKER='.bailong-storage.json'

def data_dir():return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced'


def configure_data_environment():
    """Honor this managed install's data binding across different launch hosts.

    MSIX hosts can virtualize LocalAppData. Keep the registered running data
    rather than accidentally adopting an older namesake outside that host.
    Uninstalled candidates and isolated probes must keep their own environment.
    """
    if sys.platform!='win32' or not getattr(sys,'frozen',False) or os.environ.get('BAILONG_ISOLATED')=='1':return None
    exe=Path(sys.executable).absolute()
    if exe.parent.parent.name!='versions':return None
    install=exe.parent.parent.parent.resolve()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BailongEnhanced') as key:
            registered=winreg.QueryValueEx(key,'InstallLocation')[0]
            bound=winreg.QueryValueEx(key,'DataLocation')[0]
        if not isinstance(registered,str) or Path(registered).resolve()!=install:return None
        if not isinstance(bound,str):return None
        data=Path(bound)
        if not data.is_absolute() or data.name.casefold()!='bailongenhanced':return None
        data=plain(data)
        os.environ['LOCALAPPDATA']=str(data.parent)
        return data
    except (OSError,ValueError,TypeError):return None

def registered_install_root():
    if sys.platform!='win32':return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BailongEnhanced') as key:
            value=winreg.QueryValueEx(key,'InstallLocation')[0]
            try:bound_data=winreg.QueryValueEx(key,'DataLocation')[0]
            except OSError:bound_data=None
        if bound_data:
            if not isinstance(bound_data,str) or Path(bound_data).resolve()!=data_dir().resolve():return None
        else:
            # Before custom locations existed, every legacy install used this
            # exact default. Windows folder APIs can also reflect overridden env.
            default=data_dir().parent/'Programs/BailongEnhanced'
            if not isinstance(value,str) or Path(value).resolve()!=default.resolve():return None
        p=Path(value)
        return p if p.is_absolute() and p.name.casefold()=='bailongenhanced' else None
    except (OSError,TypeError,ValueError,KeyError):return None

def install_root():
    if os.environ.get('BAILONG_ISOLATED')=='1':return data_dir().parent/'Programs/BailongEnhanced'
    exe=Path(sys.executable).absolute()
    if getattr(sys,'frozen',False) and exe.parent.parent.name=='versions':
        return exe.parent.parent.parent
    return registered_install_root() or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Programs/BailongEnhanced'

def material_root(state):
    state=Path(state);path=state/'material-location.json'
    if not path.exists():return state/'materials'
    value=json.loads(path.read_text(encoding='utf-8'))
    p=Path(value['path'])
    if value.get('schema')!=1 or not p.is_absolute():raise ValueError('动画目录配置无效')
    plain(p)
    return p

def save_material_root(state,path):
    from desktop_core import atomic_json
    path=plain(path)
    atomic_json(Path(state)/'material-location.json',dict(schema=1,path=str(path)))

def plain(path):
    p=Path(path).absolute()
    if not p.is_absolute() or p==Path(p.anchor):raise ValueError('请选择独立的应用文件夹')
    for part in (p,*p.parents):
        if part.is_symlink() or part.is_junction():raise ValueError('目录不能是符号链接或目录联接')
    return p.parent.resolve()/p.name

def destination(path,kind,source=None):
    p=plain(path)
    if source:
        old=plain(source)
        if p==old or p.is_relative_to(old) or old.is_relative_to(p):raise ValueError('新旧目录不能相同或相互包含')
    state=plain(data_dir())
    if kind=='program' and (p.is_relative_to(state) or state.is_relative_to(p)):raise ValueError('程序目录不能包含用户数据目录')
    if p.exists() and any(p.iterdir()):
        try:marker=json.loads((p/MARKER).read_text(encoding='utf-8'))
        except (OSError,ValueError):raise ValueError('请选择空文件夹，避免覆盖已有文件') from None
        if marker.get('kind')!=kind or marker.get('source')!=str(Path(source).absolute() if source else ''):
            raise ValueError('目标文件夹已被其他内容占用')
    return p

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def copy_tree(source,target,kind,cancel=lambda:False,progress=lambda *a:None):
    """No source removal here. Retain partial owned destinations for safe retry."""
    source=plain(source);target=destination(target,kind,source)
    records=[];directories=[]
    if source.exists():
        for folder,children,files in os.walk(source,followlinks=False):
            base=plain(folder);directories.append(base.relative_to(source).as_posix())
            for name in children:plain(base/name)
            for name in files:
                p=plain(base/name)
                if p==source/MARKER:continue
                s=p.stat();records.append((p.relative_to(source).as_posix(),s.st_size,s.st_mtime_ns,s.st_dev,s.st_ino))
    total=sum(x[1] for x in records)
    target.mkdir(parents=True,exist_ok=True)
    from desktop_core import atomic_json
    atomic_json(target/MARKER,dict(schema=1,kind=kind,source=str(source),target=str(target)))
    physical={((d,i) if i else name):size for name,size,mtime,d,i in records}
    if shutil.disk_usage(target).free<sum(physical.values())+16*1024*1024:raise OSError('目标磁盘剩余空间不足')
    copied=[];links={};done=0
    for name,size,mtime,device,inode in records:
        if cancel():raise InterruptedError('目录迁移已取消，原目录继续保留')
        src=plain(source/name);dst=plain(target/name);dst.parent.mkdir(parents=True,exist_ok=True)
        before=src.stat();sha=digest(src)
        if (before.st_size,before.st_mtime_ns)!=(size,mtime):raise OSError('迁移期间源文件已变化，请重试')
        if not dst.is_file() or dst.stat().st_size!=size or digest(dst)!=sha:
            temp=dst.with_name(dst.name+'.moving-'+uuid.uuid4().hex)
            key=(device,inode) if inode else None
            if key in links:
                try:os.link(links[key],temp)
                except OSError:shutil.copy2(src,temp)
            else:shutil.copy2(src,temp)
            os.replace(temp,dst)
        if digest(dst)!=sha or digest(src)!=sha:raise OSError('迁移校验失败，原目录已保留')
        if inode:links[(device,inode)]=dst
        copied.append(dict(path=name,bytes=size,sha256=sha));done+=size;progress(done,total,'moving')
    return dict(schema=1,kind=kind,source=str(source),target=str(target),files=copied,directories=directories)

def clean_source(plan):
    """Only delete unchanged files listed in the user's confirmed migration."""
    source=plain(plan['source']);target=plain(plan['target'])
    if source==target or source.is_relative_to(target) or target.is_relative_to(source):raise ValueError('迁移目录相互包含')
    marker=json.loads((target/MARKER).read_text(encoding='utf-8'))
    if marker.get('source')!=str(source) or marker.get('kind')!=plan['kind']:raise ValueError('迁移凭证不匹配')
    for name in [*[item['path'] for item in plan['files']],*plan['directories']]:
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name:raise ValueError('迁移路径无效')
    for item in plan['files']:
        rel=PurePosixPath(item['path'])
        if rel.is_absolute() or '..' in rel.parts or '\\' in item['path'] or ':' in item['path']:raise ValueError('迁移文件路径无效')
        src=plain(source/rel);dst=plain(target/rel)
        if not src.exists():continue
        if src.stat().st_size!=item['bytes'] or digest(src)!=item['sha256'] or digest(dst)!=item['sha256']:
            raise OSError('原目录有变化，未清理变化文件')
        src.unlink()
    if (source/MARKER).exists():(source/MARKER).unlink()
    for name in sorted(plan['directories'],key=lambda p:len(PurePosixPath(p).parts),reverse=True):
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name:raise ValueError('迁移目录路径无效')
        p=plain(source/name)
        try:p.rmdir()
        except OSError:pass
    return not source.exists()

def cleanup_main(plan_path):
    """Run from the new install, after the old maintenance window exits."""
    import psutil
    path=Path(plan_path).absolute();root=install_root().absolute()
    if path.parent!=root or path.name!='location-migration.json':raise ValueError('清理凭证位置无效')
    plan=json.loads(path.read_text(encoding='utf-8'))
    if plain(plan['target'])!=root:raise ValueError('清理目标与当前安装不匹配')
    deadline=time.monotonic()+600
    def waiting():
        try:return psutil.Process(plan['wait_pid']).create_time()==plan.get('wait_created')
        except psutil.NoSuchProcess:return False
    while waiting():
        if time.monotonic()>=deadline:return 1
        time.sleep(.3)
    try:
        plan['sourceCleaned']=clean_source(plan)
    except (OSError,ValueError) as exc:plan['cleanupError']=str(exc)[:200]
    from desktop_core import atomic_json
    atomic_json(path,plan)
    return 0 if plan.get('sourceCleaned') else 1
