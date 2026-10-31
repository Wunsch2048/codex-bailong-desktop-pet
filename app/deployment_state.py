"""Recoverable entry snapshots and nonce-bound local startup confirmation."""
import base64,hashlib,json,os,shutil,subprocess,time,uuid
from pathlib import Path

def atomic(path,value):
    path=Path(path);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');os.replace(temp,path)

def entry_paths(root,system):
    paths=[Path(root)/'installations.json']
    if system:
        import ctypes
        def folder(csidl):
            buffer=ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None,csidl,None,0,buffer):raise OSError('无法确定快捷方式目录')
            return Path(buffer.value)
        desktop=folder(16);start=folder(11);startup=folder(7)
        paths.extend([desktop/'白龙桌宠增强版.lnk',desktop/'白龙桌宠.lnk',start/'Programs/白龙桌宠增强版.lnk',startup/'BailongEnhanced.vbs',startup/'白龙桌宠增强版.lnk',startup/'BailongCodexSync.vbs',startup/'BailongCodexSync.lnk'])
    return paths

REGISTRY=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BailongEnhanced'
def registry_snapshot():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,REGISTRY) as key:
            values=[];i=0
            while True:
                try:name,value,kind=winreg.EnumValue(key,i)
                except OSError as error:
                    if error.winerror==259:break
                    raise
                values.append([name,{'bytes':base64.b64encode(value).decode()} if isinstance(value,bytes) else value,kind]);i+=1
            return values
    except FileNotFoundError:return None

def capture_entries(root,system):
    values={}
    for path in entry_paths(root,system):
        if path.is_symlink():raise OSError('安装入口不能是符号链接')
        values[str(path)]=base64.b64encode(path.read_bytes()).decode() if path.exists() else None
    return dict(files=values,registry=registry_snapshot() if system else None,system=system)

def restore_entries(root,snapshot,system):
    expected={str(p) for p in entry_paths(root,system)}
    optional={p for p in expected if Path(p).name in ('BailongCodexSync.vbs','BailongCodexSync.lnk')}
    files=set(snapshot['files'])
    if not expected-optional<=files<=expected:raise ValueError('恢复入口范围无效')
    for name,value in snapshot['files'].items():
        path=Path(name)
        if path.is_symlink():raise ValueError('恢复入口不能是符号链接')
        if value is None:path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.restore.tmp')
            temp.write_bytes(base64.b64decode(value,validate=True));os.replace(temp,path)
    if system:
        import winreg
        old=snapshot['registry']
        if old is None:
            try:winreg.DeleteKey(winreg.HKEY_CURRENT_USER,REGISTRY)
            except FileNotFoundError:pass
        else:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,REGISTRY) as key:
                current=[];i=0
                while True:
                    try:current.append(winreg.EnumValue(key,i)[0]);i+=1
                    except OSError as error:
                        if error.winerror==259:break
                        raise
                for name in current:winreg.DeleteValue(key,name)
                for name,value,kind in old:
                    if isinstance(value,dict) and 'bytes' in value:value=base64.b64decode(value['bytes'])
                    winreg.SetValueEx(key,name,0,kind,value)

def owned_destination(root,name):
    root=Path(root).resolve();versions=root/'versions';dest=versions/name
    if not isinstance(name,str) or not name or dest.is_symlink() or dest.is_junction() or versions.is_symlink() or versions.is_junction() or dest.resolve().parent!=versions.resolve():raise ValueError('暂存版本路径无效')
    return dest.resolve()

def stop_version(exe):
    import psutil
    victims=[]
    for p in psutil.process_iter(['exe']):
        try:
            if p.info['exe'] and Path(p.info['exe']).resolve()==Path(exe).resolve():p.terminate();victims.append(p)
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    _,alive=psutil.wait_procs(victims,timeout=5)
    for p in alive:p.kill()
    if alive:psutil.wait_procs(alive,timeout=5)

def recover(root,system=False):
    root=Path(root).resolve();path=root/'deployment-journal.json'
    maintenance=root/'maintenance-journal.json'
    if maintenance.exists():
        record=json.loads(maintenance.read_text(encoding='utf-8'))
        if record.get('operation')!='rollback':raise ValueError('维护恢复记录无效')
        restore_entries(root,record['snapshot'],system);maintenance.unlink()
    if not path.exists():return False
    journal=json.loads(path.read_text(encoding='utf-8'));dest=owned_destination(root,journal['new_version'])
    if journal.get('phase')=='committed':
        manifest=json.loads((root/'installations.json').read_text(encoding='utf-8'))
        if manifest['current']!=dest.name or not (dest/'BailongEnhanced.exe').is_file():raise OSError('安装提交记录不一致，请保留文件并重试')
        path.unlink();return True
    stop_version(dest/'BailongEnhanced.exe')
    restore_entries(root,journal['snapshot'],system)
    if journal.get('data_backup'):
        from installer import DATA,ROOT
        from directory_deploy import restore_data
        target=Path(journal['data_root']).absolute()
        expected=DATA.absolute() if root==ROOT.resolve() else root/'user-data'
        if target!=expected:raise ValueError('用户数据恢复目录无效')
        restore_data(target,journal['data_backup'],root)
    # Both entry restoration and boundary validation complete before removal.
    if dest.exists():shutil.rmtree(dest)
    from shared_assets import cleanup_new
    cleanup_new(root,journal.get('new_shared_objects',[]))
    path.unlink()
    if journal.get('old_running'):
        old=owned_destination(root,journal['old_running'])/'BailongEnhanced.exe'
        if old.is_file():
            from process_launch import launch_own
            launch_own([str(old)],cwd=str(old.parent),creationflags=0x08000000)
    return True

def verify_payload(dest,version):
    path=dest/'payload-manifest.json'
    if not path.exists():return  # Supports the development/test install API.
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('version')!=version:raise ValueError('安装载荷版本不匹配')
    for name,expected in data['files'].items():
        p=(dest/name).resolve()
        if not p.is_relative_to(dest.resolve()) or not p.is_file() or p.stat().st_size!=expected['bytes']:raise ValueError('安装载荷文件不完整')
        with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=expected['sha256']:raise ValueError('安装载荷校验失败')

def wait_ready(process,exe,receipt,token,version,timeout=25,stable_seconds=1):
    deadline=time.monotonic()+timeout;first=None
    while time.monotonic()<deadline:
        code=process.poll()
        if code is not None:raise OSError(f'新版桌宠在就绪前退出（0x{code & 0xffffffff:08X}），安装未提交')
        try:data=json.loads(receipt.read_text(encoding='utf-8'))
        except (OSError,ValueError):data={}
        if not isinstance(data,dict):data={}
        if (data.get('token')==token and data.get('version')==version and data.get('pid')==process.pid and
            data.get('serverReady') is True and data.get('windowReady') is True and isinstance(data.get('exe'),str) and Path(data['exe']).resolve()==exe.resolve()):
            first=first or time.monotonic()
            if time.monotonic()-first>=stable_seconds:return data
        else:first=None
        time.sleep(.1)
    raise OSError('新版桌宠未能确认本地窗口与服务就绪，安装未提交')

def write_ready_receipt(pet,server):
    token=os.environ.pop('BAILONG_DEPLOY_TOKEN','');name=os.environ.pop('BAILONG_DEPLOY_RECEIPT','')
    if not token or not name:return
    import re,sys
    if not re.fullmatch('[a-f0-9]{32}',token):return
    exe=Path(sys.executable).resolve();path=Path(name)
    if path.resolve().parent!=exe.parent or path.name!='.ready-'+token+'.json':return
    if not server.isListening() or not pet.winId():return
    from desktop_core import VERSION
    atomic(path,dict(token=token,version=VERSION,pid=os.getpid(),exe=str(exe),serverReady=True,windowReady=True))
