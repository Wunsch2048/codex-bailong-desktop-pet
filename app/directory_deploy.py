"""Local deployment from a verified frozen application directory, without ZIPs.

Uses the same readiness, entry transaction, crash recovery and rollback as the
public installer. Program files are copied into a fresh version; never patched
in place. Only immutable WebP content is subsequently shared by hash.
"""
import hashlib,json,os,re,shutil,sqlite3,time,uuid
from contextlib import closing
from pathlib import Path,PurePosixPath
from deployment_state import verify_payload,atomic

def plain_path(path):
    path=Path(path)
    if path.is_symlink() or path.is_junction():raise ValueError('部署路径不能是链接或目录联接')
    return path

def inspect_source(source,version):
    source=Path(source).absolute()
    for p in [source,*source.parents]:plain_path(p)
    if not source.is_dir():raise ValueError('本地构建目录不存在')
    manifest=plain_path(source/'payload-manifest.json')
    data=json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('version')!=version or not isinstance(data.get('files'),dict) or not data['files']:raise ValueError('本地构建缺少匹配的完整校验清单')
    normalized=set()
    for name,value in data['files'].items():
        if not isinstance(name,str):raise ValueError('构建文件路径无效')
        path=PurePosixPath(name)
        if '\\' in name or ':' in name or path.is_absolute() or path.as_posix()!=name or any(p in ('.','..') for p in path.parts):raise ValueError('构建文件路径无效')
        if name.casefold() in normalized or name=='payload-manifest.json':raise ValueError('构建文件路径重复')
        normalized.add(name.casefold())
        if not isinstance(value,dict) or not isinstance(value.get('bytes'),int) or value['bytes']<0 or not re.fullmatch('[0-9a-f]{64}',str(value.get('sha256',''))):raise ValueError('构建文件校验记录无效')
    actual=set()
    for p in source.rglob('*'):
        plain_path(p)
        if p.is_file():actual.add(p.relative_to(source).as_posix())
    if actual!=set(data['files'])|{'payload-manifest.json'}:raise ValueError('本地构建包含未登记文件或缺失文件')
    if 'BailongEnhanced.exe' not in data['files']:raise ValueError('本地构建缺少主程序')
    verify_payload(source,version)
    return data

def populate_directory(source,dest,version):
    source=Path(source);dest=Path(dest)
    data=inspect_source(source,version)
    for name in [*data['files'],'payload-manifest.json']:
        target=dest/name;target.parent.mkdir(parents=True,exist_ok=True)
        if name.startswith('outputs/白龙桌宠素材/'):
            try:os.link(source/name,target)
            except OSError:shutil.copy2(source/name,target)
        else:shutil.copy2(source/name,target)
    # Detect a source modified while copying, before any entry is changed.
    verify_payload(dest,version)
    if (dest/'payload-manifest.json').read_bytes()!=(source/'payload-manifest.json').read_bytes():raise ValueError('构建清单在部署期间发生变化')

def backup_budget(database_bytes,wal_bytes=0):
    """Bounded large-ledger allowance; tiny databases retain the old limit."""
    return min(180.,max(15.,10.+(database_bytes+wal_bytes)/(32*1024*1024)))

def backup_data(data_root,install_root,previous):
    """Closed-app JSON snapshots and SQLite backup API; exclude asset/download caches."""
    data_root=plain_path(Path(data_root).absolute());install_root=Path(install_root).resolve()
    base=plain_path(install_root/'deployment-backups');base.mkdir(parents=True,exist_ok=True)
    destination=base/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);destination.mkdir()
    proof=dict(previous=previous,complete=False,files={})
    atomic(destination/'backup.json',proof)
    if data_root.exists():
        for path in sorted(data_root.iterdir()):
            plain_path(path)
            if not path.is_file() or path.name in ('runtime.json','codex-connection-check.json'):continue
            if path.suffix.lower() not in ('.json','.sqlite','.sqlite3','.db'):continue
            target=destination/path.name
            if path.suffix.lower() in ('.sqlite','.sqlite3','.db'):
                if re.fullmatch(r'token-usage-source-[0-9a-f]{16}\.sqlite3',path.name):
                    from index_maintenance import before_backup
                    repair=before_backup(path)
                    proof.setdefault('databaseMaintenance',{})[path.name]=repair
                wal=path.with_name(path.name+'-wal')
                deadline=time.monotonic()+backup_budget(path.stat().st_size,wal.stat().st_size if wal.exists() else 0)
                def progress(*unused):
                    if time.monotonic()>deadline:raise OSError('用户数据库备份超时，未切换新版')
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as src,closing(sqlite3.connect(target)) as dst:
                    src.backup(dst,pages=128,progress=progress,sleep=.01)
                    if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise OSError('用户数据库备份校验失败')
            else:shutil.copy2(path,target)
            with target.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
            proof['files'][path.name]=dict(bytes=target.stat().st_size,sha256=sha)
    proof['complete']=True;atomic(destination/'backup.json',proof)
    return destination

def restore_data(data_root,backup,install_root):
    """Restore a closed application's verified snapshot, including SQLite sidecars."""
    data_root=plain_path(Path(data_root).absolute());base=plain_path(Path(install_root).resolve()/'deployment-backups')
    backup=plain_path(Path(backup).absolute())
    if backup.parent!=base or backup.resolve()!=backup:raise ValueError('数据备份路径无效')
    proof=json.loads((backup/'backup.json').read_text(encoding='utf-8'))
    if proof.get('complete') is not True or not isinstance(proof.get('files'),dict):raise ValueError('用户数据备份未完成')
    def eligible(name):return Path(name).suffix.lower() in ('.json','.sqlite','.sqlite3','.db') and name not in ('runtime.json','codex-connection-check.json')
    for name,record in proof['files'].items():
        if Path(name).name!=name or not eligible(name):raise ValueError('用户数据备份文件名无效')
        path=plain_path(backup/name)
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if path.stat().st_size!=record['bytes'] or sha!=record['sha256']:raise ValueError('用户数据备份校验失败')
    data_root.mkdir(parents=True,exist_ok=True)
    for path in data_root.iterdir():
        plain_path(path)
        if not path.is_file():continue
        if eligible(path.name) and path.name not in proof['files']:path.unlink()
        elif path.name.endswith(('-wal','-shm')) and eligible(path.name.rsplit('-',1)[0]):path.unlink()
    for name in proof['files']:
        target=data_root/name;temp=target.with_name(name+'.restore.tmp')
        shutil.copy2(backup/name,temp);os.replace(temp,target)

def deploy_directory(source,startup,root=None,data_root=None,progress=print):
    from installer import ROOT,DATA,deploy,VERSION
    source=Path(source).absolute();root=Path(root or ROOT).resolve();data_root=Path(data_root or DATA)
    inspect_source(source,VERSION)  # Reject corrupt/unversioned builds before stopping the old pet.
    from installer import read_manifest
    previous=read_manifest(root).get('current','')
    backup=None
    def snapshot(old):
        nonlocal backup
        progress('旧版已退出，正在备份设置、聊天与统计数据…')
        backup=backup_data(data_root,root,previous)
        return backup
    exe=deploy(None,startup,root=root,data_root=data_root,progress=progress,after_stop=snapshot,
               populate=lambda dest:populate_directory(source,dest,VERSION))
    result=dict(version=VERSION,current=exe.parent.name,previous=previous,executable=str(exe),backup=str(backup),fullInstallerGenerated=False)
    try:atomic(root/'last-local-deployment.json',result)
    except OSError:result['recordWarning']='新版已经提交，但本地部署摘要写入失败；安装清单与数据备份仍保留'
    return result
