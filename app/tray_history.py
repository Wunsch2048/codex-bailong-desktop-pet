"""Reconcile this installation's Shell history after an upgrade, with exact backups.

The application keeps versioned binaries for rollback. Windows treats their paths
as separate tray identities. Reconcile once after a successful launch rather than
polling the registry or replacing the versioned installation scheme.
"""
import base64
import json
import ntpath
import os
import struct
import sys
import time
import uuid
from pathlib import Path

KEY=r'Control Panel\NotifyIconSettings'
LEGACY_UID=0xB410
PROMOTED='IsPromoted'
ORDER='UIOrderList'

def reconcile_fixed(state,host):
    """One migration to the stable host, not a per-version cleanup strategy."""
    from stable_tray import TRAY_GUID
    from storage_locations import install_root
    from deployment_state import owned_destination
    from desktop_core import atomic_json
    import winreg,psutil
    root=install_root().resolve();host=Path(host).resolve()
    if host!=root/'tray/BailongTray.exe':return
    marker=Path(state)/'fixed-tray-migration.json'
    try:
        old=json.loads(marker.read_text(encoding='utf-8'))
        if old.get('guid')==TRAY_GUID and old.get('host')==str(host):return
    except (OSError,ValueError):pass
    for _ in range(30):
        if not (root/'deployment-journal.json').exists():break
        time.sleep(.5)
    else:return
    manifest=json.loads((root/'installations.json').read_text(encoding='utf-8'))
    owned={path_key(str(owned_destination(root,n)/'BailongEnhanced.exe')) for n in manifest['versions']}
    records=snapshot(winreg);keep=[r for r in records if path_key(r['exe'])==path_key(str(host))]
    if len(keep)!=1:return
    fields={n:v for n,v,t in keep[0]['values']}
    if str(fields.get('IconGuid','')).strip('{}').lower()!=TRAY_GUID:return
    active=set()
    for p in psutil.process_iter(['exe']):
        try:
            if p.info['exe']:active.add(path_key(p.info['exe']))
        except psutil.Error:pass
    retired=[r for r in records if path_key(r['exe']) in owned and path_key(r['exe']) not in active and r['uid'] in (0,LEGACY_UID)]
    donors=sorted(retired,key=lambda r:r.get('promoted')==1,reverse=True)
    keep=keep[0];promotion=keep.get('promoted')
    if promotion not in (0,1) and donors:promotion=donors[0].get('promoted')
    inherit=bool(keep.get('promoted')==0 and donors and donors[0].get('promoted')==1)
    if inherit:promotion=1
    approved=dict(keep=keep,remove=retired,promoted=promotion,retired=[],inheritPin=inherit)
    backup=Path(state)/'tray-history-backups'/('fixed-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json')
    result=apply_plan(winreg,approved,backup)
    atomic_json(marker,dict(guid=TRAY_GUID,host=str(host),**result))


def path_key(path):
    return ntpath.normcase(ntpath.normpath(path)) if isinstance(path,str) and ntpath.isabs(path) else ''


def plan(records,owned,current,active=(),preferred='',retired=(),inherit_previous=False):
    """Match exact known paths/UIDs; never infer ownership from an EXE name."""
    current=path_key(current);owned={path_key(p) for p in owned}-{''}
    active={path_key(p) for p in active}-{''}
    if not current or current not in owned:return None
    candidates=[r for r in records if r.get('name','').isdigit()
                and path_key(r.get('exe')) in owned and r.get('uid') in (0,LEGACY_UID)]
    keep=[r for r in candidates if path_key(r['exe'])==current and r['uid']==0]
    if len(keep)!=1:return None  # Wait for Shell to register the new icon first.
    target=keep[0]
    remove=[r for r in candidates if r is not target
            and (path_key(r['exe'])==current or path_key(r['exe']) not in active)]
    donors=[r for r in remove if r['uid']==0 and r.get('promoted') in (0,1)]
    preferred=path_key(preferred)
    donors.sort(key=lambda r:path_key(r['exe'])==preferred,reverse=True)
    promotion=target.get('promoted')
    if promotion not in (0,1) and donors:promotion=donors[0]['promoted']
    # A newly registered version normally starts with IsPromoted=0, even when
    # the user pinned its predecessor. Inherit that pin once per deployment;
    # ordinary restarts must continue respecting the current version's choice.
    inherit_pin=bool(inherit_previous and promotion==0 and preferred and
        any(path_key(r['exe'])==preferred and r['promoted']==1 for r in donors))
    if inherit_pin:promotion=1
    existing={r['name'] for r in records}
    retired=[n for n in retired if isinstance(n,str) and n.isdigit()
             and int(n)<2**64 and n not in existing]
    return dict(keep=target,remove=remove,promoted=promotion,retired=retired,inheritPin=inherit_pin)


def _read_order(reg):
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER,KEY,0,reg.KEY_READ) as key:
            raw,kind=reg.QueryValueEx(key,ORDER)
    except FileNotFoundError:return None
    if kind!=reg.REG_BINARY or not isinstance(raw,bytes) or len(raw)%8:
        raise ValueError('托盘排序索引格式未知，保留历史记录')
    return raw


def order_without(raw,identities):
    """Keep every unrelated ID, byte order and relative position unchanged."""
    if raw is None:return None
    retired={int(n) for n in identities}
    return b''.join(raw[i:i+8] for i in range(0,len(raw),8)
                    if struct.unpack_from('<Q',raw,i)[0] not in retired)


def retired_from_backups(directory,owned,missing):
    """Recover a prior interrupted cleanup, only for exact owned paths."""
    owned={path_key(p) for p in owned}-{''};missing=set(missing);found=set()
    if not missing or not Path(directory).is_dir():return found
    # This runs once in a background worker, and only when dangling IDs exist.
    files=sorted(Path(directory).glob('*.json'),key=lambda p:p.name,reverse=True)[:32]
    for file in files:
        try:
            if file.stat().st_size>8*1024*1024:continue
            saved=json.loads(file.read_text(encoding='utf-8'))
            if saved.get('schema')!=1 or saved.get('registry')!=KEY:continue
            for row in saved.get('plan',{}).get('remove',[]):
                name=row.get('name');values={n:v for n,v,t in row.get('values',[])}
                if (name in missing and path_key(row.get('exe')) in owned
                        and row.get('uid') in (0,LEGACY_UID)
                        and values.get('ExecutablePath')==row['exe']
                        and values.get('UID')==row['uid']):found.add(name)
        except (OSError,ValueError,TypeError,KeyError,AttributeError):continue
    return found


def snapshot(reg):
    records=[]
    try:parent=reg.OpenKey(reg.HKEY_CURRENT_USER,KEY,0,reg.KEY_READ)
    except FileNotFoundError:return records
    with parent:
        count=reg.QueryInfoKey(parent)[0]
        for i in range(count):
            try:
                name=reg.EnumKey(parent,i)
                if not name.isdigit():continue
                with reg.OpenKey(parent,name,0,reg.KEY_READ) as key:
                    if reg.QueryInfoKey(key)[0]:continue
                    values=[]
                    for index in range(reg.QueryInfoKey(key)[1]):
                        n,v,t=reg.EnumValue(key,index)
                        values.append([n,{'base64':base64.b64encode(v).decode('ascii')} if isinstance(v,bytes) else v,t])
                fields={n:v for n,v,t in values}
                records.append(dict(name=name,exe=fields.get('ExecutablePath',''),uid=fields.get('UID'),
                                    promoted=fields.get(PROMOTED),values=values))
            except FileNotFoundError:continue
    return records


def _same_record(reg,record):
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER,KEY+'\\'+record['name'],0,reg.KEY_READ) as key:
            if reg.QueryValueEx(key,'ExecutablePath')[0]!=record['exe'] or reg.QueryInfoKey(key)[0]!=0:return False
            if record['uid'] is not None:return reg.QueryValueEx(key,'UID')[0]==record['uid']
            fields={n:v for n,v,t in record['values']}
            return bool(fields.get('IconGuid')) and reg.QueryValueEx(key,'IconGuid')[0]==fields['IconGuid']
    except FileNotFoundError:return False


def apply_plan(reg,approved,backup_path):
    """A verified durable snapshot must exist before touching any Shell record."""
    backup_path=Path(backup_path)
    original_order=_read_order(reg)
    content=dict(schema=1,registry=KEY,created=time.time(),plan=approved,
                 order=None if original_order is None else base64.b64encode(original_order).decode('ascii'))
    raw=json.dumps(content,ensure_ascii=False,indent=2).encode('utf-8')
    backup_path.parent.mkdir(parents=True,exist_ok=True)
    with backup_path.open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    if backup_path.read_bytes()!=raw:raise OSError('托盘记录备份校验失败')
    target=approved['keep']
    if not _same_record(reg,target):raise OSError('当前托盘图标已变化，保留历史记录')
    if _read_order(reg)!=original_order:raise OSError('托盘顺序已变化，保留历史记录')
    value=approved['promoted']
    if value in (0,1) and (target.get('promoted') not in (0,1) or approved.get('inheritPin')):
        with reg.OpenKey(reg.HKEY_CURRENT_USER,KEY+'\\'+target['name'],0,reg.KEY_READ|reg.KEY_SET_VALUE) as key:
            try:current_promotion=reg.QueryValueEx(key,PROMOTED)[0]
            except FileNotFoundError:current_promotion=None
            if current_promotion==target.get('promoted'):
                reg.SetValueEx(key,PROMOTED,0,reg.REG_DWORD,value)
    removed=[];skipped=[]
    for record in approved['remove']:
        # Recheck all raw values: a concurrent preference change or Shell
        # update must never be discarded based on an obsolete snapshot.
        if not _same_record(reg,record):skipped.append(record['name']);continue
        with reg.OpenKey(reg.HKEY_CURRENT_USER,KEY+'\\'+record['name'],0,reg.KEY_READ) as key:
            values=[]
            for index in range(reg.QueryInfoKey(key)[1]):
                n,v,t=reg.EnumValue(key,index)
                values.append([n,{'base64':base64.b64encode(v).decode('ascii')} if isinstance(v,bytes) else v,t])
        if sorted(values,key=lambda v:v[0])!=sorted(record['values'],key=lambda v:v[0]):
            skipped.append(record['name']);continue
        reg.DeleteKey(reg.HKEY_CURRENT_USER,KEY+'\\'+record['name']);removed.append(record['name'])
    retire=removed+list(approved.get('retired',()))
    # Only IDs whose identity keys are still absent can be removed from order.
    absent=[]
    for name in retire:
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER,KEY+'\\'+name,0,reg.KEY_READ):pass
        except FileNotFoundError:absent.append(name)
    updated=order_without(original_order,absent)
    order_changed=False;order_skipped=False
    if updated!=original_order:
        with reg.OpenKey(reg.HKEY_CURRENT_USER,KEY,0,reg.KEY_READ|reg.KEY_SET_VALUE) as key:
            if reg.QueryValueEx(key,ORDER)==(original_order,reg.REG_BINARY):
                reg.SetValueEx(key,ORDER,0,reg.REG_BINARY,updated);order_changed=True
            else:order_skipped=True  # Never overwrite a concurrent user reorder.
    return dict(removed=removed,skipped=skipped,backup=str(backup_path),currentKey=target['name'],
                orderChanged=order_changed,orderSkipped=order_skipped)


def restore_backup(reg,backup_path):
    """Explicit undo: recreate missing backed-up keys, never overwrite live keys."""
    saved=json.loads(Path(backup_path).read_text(encoding='utf-8'))
    if saved.get('schema')!=1 or saved.get('registry')!=KEY:raise ValueError('托盘备份格式无效')
    records=saved['plan']['remove'];restored=[]
    for record in records:
        if (not record['name'].isdigit() or int(record['name'])>=2**64
                or record['uid'] not in (0,LEGACY_UID) or not path_key(record['exe'])):
            raise ValueError('托盘备份记录无效')
        values={n:(v,t) for n,v,t in record['values']}
        if values.get('ExecutablePath',(None,None))[0]!=record['exe'] or values.get('UID',(None,None))[0]!=record['uid']:
            raise ValueError('托盘备份身份不一致')
    for record in records:
        path=KEY+'\\'+record['name']
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER,path):pass
            continue
        except FileNotFoundError:pass
        with reg.CreateKey(reg.HKEY_CURRENT_USER,path) as key:
            for n,v,t in record['values']:
                if isinstance(v,dict):v=base64.b64decode(v['base64'],validate=True)
                reg.SetValueEx(key,n,0,t,v)
        restored.append(record['name'])
    if restored:
        # Explicit rollback restores IDs without undoing later user reordering.
        current=_read_order(reg)
        if current is not None:
            known={str(v[0]) for v in struct.iter_unpack('<Q',current)}
            append=b''.join(struct.pack('<Q',int(n)) for n in restored if n not in known)
            if append:
                with reg.OpenKey(reg.HKEY_CURRENT_USER,KEY,0,reg.KEY_READ|reg.KEY_SET_VALUE) as key:
                    if reg.QueryValueEx(key,ORDER)==(current,reg.REG_BINARY):
                        reg.SetValueEx(key,ORDER,0,reg.REG_BINARY,current+append)
    return restored


def reconcile(state,extra_owned=()):
    """Installed production only. Tests/portable copies never modify user history."""
    if sys.platform!='win32' or os.environ.get('BAILONG_ISOLATED')=='1' or not getattr(sys,'frozen',False):return
    import winreg
    from storage_locations import install_root
    root=install_root().resolve();current=Path(sys.executable).resolve()
    if current.parent.parent!=root/'versions':return
    # A fresh process can be ready before the installer commits its manifest.
    # Wait only in this one background job; never clean an uncommitted update
    # or leave the maintenance permanently skipped because startup was fast.
    for unused in range(30):
        manifest=json.loads((root/'installations.json').read_text(encoding='utf-8'))
        if manifest.get('current')==current.parent.name and not (root/'deployment-journal.json').exists():break
        time.sleep(.5)
    else:return
    from deployment_state import owned_destination
    owned=[str(owned_destination(root,n)/'BailongEnhanced.exe') for n in manifest['versions']]
    owned+=list(extra_owned)
    import psutil
    active=[]
    for process in psutil.process_iter(['exe']):
        try:
            if process.info['exe']:active.append(process.info['exe'])
        except psutil.Error:continue
    records=snapshot(winreg)
    previous=''
    try:
        receipt=json.loads((root/'last-local-deployment.json').read_text(encoding='utf-8'))
        if receipt.get('current')==current.parent.name:previous=str(owned_destination(root,receipt['previous'])/'BailongEnhanced.exe')
    except (OSError,KeyError,ValueError):pass
    order=_read_order(winreg)
    missing=({str(v[0]) for v in struct.iter_unpack('<Q',order)}-{r['name'] for r in records}) if order else set()
    retired=retired_from_backups(Path(state)/'tray-history-backups',owned,missing)
    marker=Path(state)/'tray-history-last.json'
    try:last=json.loads(marker.read_text(encoding='utf-8'))
    except (OSError,ValueError):last={}
    migration_checked=last.get('version')==current.parent.name and last.get('preferenceMigrationChecked') is True
    approved=plan(records,owned,str(current),active,previous,retired,inherit_previous=not migration_checked)
    if approved is None:return
    from desktop_core import atomic_json
    if not (approved['remove'] or approved['retired'] or approved['inheritPin']):
        if not migration_checked:atomic_json(marker,dict(version=current.parent.name,preferenceMigrationChecked=True,currentKey=approved['keep']['name'],removed=[],skipped=[]))
        return
    backup=Path(state)/'tray-history-backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json')
    result=apply_plan(winreg,approved,backup)
    atomic_json(marker,dict(version=current.parent.name,preferenceMigrationChecked=True,**result))
