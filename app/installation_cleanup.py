"""Explicit, previewed cleanup; retain current, two recent versions and running binaries."""
from pathlib import Path
import json,shutil
from deployment_state import owned_destination
from PySide6.QtCore import QThread,Signal

class CleanupJob(QThread):
    done=Signal(object);failed=Signal(str)
    def __init__(self,root,data_root,approved,parent=None):super().__init__(parent);self.root=root;self.data_root=data_root;self.approved=approved
    def run(self):
        try:self.done.emit(cleanup(self.root,self.data_root,self.approved))
        except Exception as error:self.failed.emit(str(error)[:300])

def cleanup_plan(root):
    import psutil
    from installer import read_manifest
    root=Path(root).resolve();m=read_manifest(root)
    keep={m.get('current',''),*m.get('pinnedVersions',[])}
    recent=0;seen={m.get('current','').split('-')[0]}
    for name in m['versions']:
        path=owned_destination(root,name)
        version=name.split('-')[0]
        if path.exists() and version not in seen:
            keep.add(name);seen.add(version);recent+=1
            if recent>=2:break
    for process in psutil.process_iter(['exe']):
        try:
            if process.info['exe']:
                exe=Path(process.info['exe']).resolve()
                if exe.parent.parent==root/'versions':keep.add(exe.parent.name)
        except (psutil.Error,OSError):continue
    versions=[n for n in m['versions'] if n not in keep]
    for name in versions:owned_destination(root,name)
    base=root/'deployment-backups'
    if base.is_symlink() or base.is_junction():raise ValueError('备份目录不能是链接')
    backups=[]
    if base.is_dir():
        candidates=[]
        for p in sorted(base.iterdir(),reverse=True):
            if p.is_symlink() or p.is_junction() or not p.is_dir():continue
            try:info=json.loads((p/'backup.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            if info.get('complete') is True:candidates.append((p,info))
        for i,(p,info) in enumerate(candidates):
            if i>=2 and info.get('previous') not in keep:backups.append(p.name)
    return dict(current=m.get('current',''),versions=versions,backups=backups,kept=sorted(keep-{''}))

def cleanup(root,data_root,approved):
    from PySide6.QtCore import QLockFile
    from installer import read_manifest,write_manifest
    from shared_assets import cleanup_new
    from deployment_state import recover
    root=Path(root).resolve();lock=QLockFile(str(Path(data_root)/'deployment.lock'))
    if not lock.tryLock(0):raise OSError('安装或维护正在运行，请稍后重试')
    try:
        if any((root/n).exists() for n in ('deployment-journal.json','maintenance-journal.json','uninstall-pending.json')):raise OSError('有未完成的维护事务，请先恢复')
        current=cleanup_plan(root)
        if current!=approved:raise OSError('安装版本发生变化，请重新预览')
        m=read_manifest(root);removed=[]
        for name in approved['versions']:
            folder=owned_destination(root,name)
            if folder.exists():
                if any(p.is_symlink() or p.is_junction() for p in folder.rglob('*')):raise ValueError('版本中存在链接，停止清理')
                shutil.rmtree(folder)
            m['versions'].remove(name);m.get('sharedAssets',{}).pop(name,None);write_manifest(m,root);removed.append(name)
        for name in approved['backups']:
            p=root/'deployment-backups'/name
            if p.parent.resolve()!=root/'deployment-backups' or p.is_symlink() or p.is_junction():raise ValueError('备份路径无效')
            if any(f.is_symlink() or f.is_junction() for f in p.rglob('*')):raise ValueError('备份中存在链接')
            shutil.rmtree(p)
        shared=root/'shared-assets'
        if shared.is_dir() and not shared.is_symlink() and not shared.is_junction():cleanup_new(root,[p.stem for p in shared.iterdir() if p.is_file() and p.suffix=='.webp'])
        return dict(versions=len(removed),backups=len(approved['backups']))
    finally:lock.unlock()
