"""Local startup, encrypted credentials, character imports and diagnostics."""
import base64
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image
from desktop_core import atomic_json

def command():
    if getattr(sys,'frozen',False):return '"'+sys.executable+'"'
    return '"'+str(Path(sys.executable).with_name('pythonw.exe'))+'" "'+str(Path(__file__).with_name('enhanced.py'))+'"'

def startup_paths():
    root=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup'
    return root/'BailongEnhanced.vbs',root/'白龙桌宠增强版.lnk'

def autostart_enabled():
    vbs,link=startup_paths()
    from windows_entries import command_parts,command_matches,legacy_command
    expected=command_parts(command())
    if link.exists():return command_matches(link,expected)
    old=legacy_command(vbs)
    return old is not None and [os.path.normcase(x) for x in old]==[os.path.normcase(x) for x in expected]

def set_autostart(enabled):
    vbs,link=startup_paths();vbs.parent.mkdir(parents=True,exist_ok=True)
    from windows_entries import startup_entry,command_parts
    startup_entry(link,vbs,command_parts(command()),enabled)

class Blob(ctypes.Structure):
    _fields_=[('size',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]

def protect(value,decrypt=False):
    raw=base64.b64decode(value) if decrypt else value.encode('utf-8')
    buf=ctypes.create_string_buffer(raw);source=Blob(len(raw),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    function=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    ok=function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out))
    if not ok:raise OSError('Windows 凭据加密服务不可用')
    try:
        result=ctypes.string_at(out.data,out.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(out.data)

class SecretStore:
    def __init__(self,path):self.path=Path(path)
    def read(self):
        try:data=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:return {}
        except (OSError,ValueError,UnicodeError,RecursionError):
            raise OSError('无法读取 credentials.dpapi.json；请检查权限或从用户数据备份恢复，原文件未改动。') from None
        if not isinstance(data,dict) or any(not isinstance(k,str) or not k or not isinstance(v,str) or not v for k,v in data.items()):
            raise OSError('credentials.dpapi.json 结构损坏；请从用户数据备份恢复，原文件未改动。')
        return data
    def get(self,name):
        value=self.read().get(name)
        try:return protect(value,True) if value else ''
        except (OSError,ValueError,TypeError,UnicodeError):raise OSError('无法解密本地密钥；请使用保存时的 Windows 用户，或重新填写密钥。') from None
    def put(self,name,value):
        data=self.read()
        if value:data[name]=protect(value)
        else:data.pop(name,None)
        atomic_json(self.path,data)

def checked_path(root,name):
    relative=Path(name)
    if relative.is_absolute() or relative.drive or '..' in relative.parts or ':' in str(name):raise ValueError('素材清单必须使用目录内的相对路径')
    p=(root/relative).resolve()
    if not p.is_relative_to(root.resolve()):raise ValueError('素材路径超出了角色目录')
    if not p.is_file():raise ValueError('缺少素材：'+str(name))
    return p

def all_items(manifest):
    result=[manifest['idle']]+manifest.get('additionalIdleAnimations',[])+manifest.get('variants',[])
    for key in ('dragAnimation','landingAnimation','quotaAnimation'):
        if manifest.get(key):result.append(manifest[key])
    for group in ('clickAnimations','moveAnimations','turnAnimations','workAnimations'):
        result.extend(v for v in manifest.get(group,[]) if isinstance(v,dict))
    unique={str(v.get('playbackFile') or v.get('file')):v for v in result}
    return list(unique.values())

def validate_character(root):
    root=Path(root).resolve();manifest_file=root/'素材清单.json'
    if not manifest_file.exists():manifest_file=root/'manifest.json'
    if manifest_file.exists():manifest=json.loads(manifest_file.read_text(encoding='utf-8-sig'))
    else:
        groups={'idle':[],'click':[],'move':[],'turn':[],'drag':[],'landing':[],'random':[]}
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.suffix.lower() not in ('.webp','.gif','.webm'):continue
            parent=path.parent.name.lower()
            category=next((k for k,words in {'idle':('idle','待机'),'click':('click','点击'),'move':('move','移动'),'turn':('turn','转向'),'drag':('drag','拖拽'),'landing':('landing','落地')}.items() if any(w in parent for w in words)),'random')
            groups[category].append(dict(id=path.stem,name=path.stem,file=str(path.relative_to(root)).replace('\\','/'),durationMs=4000))
        if not groups['idle']:raise ValueError('请提供素材清单，或至少一个名为 idle / 待机 的素材子目录')
        manifest=dict(character=root.name,idle=groups['idle'][0],additionalIdleAnimations=groups['idle'][1:],variants=groups['random'],clickAnimations=groups['click'],moveAnimations=groups['move'],turnAnimations=groups['turn'])
        if groups['drag']:manifest['dragAnimation']=groups['drag'][0]
        if groups['landing']:manifest['landingAnimation']=groups['landing'][0]
    if not isinstance(manifest.get('idle'),dict):raise ValueError('角色包需要 idle 待机素材')
    manifest.setdefault('variants',[])
    from sustained_assets import seam_items,profile_paths
    items=all_items(manifest)+seam_items(manifest)
    for item in manifest.get('workAnimations',[]):
        if item.get('sustained'):profile_paths(root,item)
    if len(items)>500:raise ValueError('每个角色最多导入500段素材')
    for item in items:
        name=item.get('playbackFile') or item.get('file','')
        path=checked_path(root,name)
        if path.suffix.lower() not in ('.webp','.gif','.webm'):raise ValueError('支持 WebP、GIF、WebM')
        item.setdefault('id',path.stem);item.setdefault('name',item['id'])
        try:duration=float(item.get('durationMs',4000))
        except (TypeError,ValueError):raise ValueError('动画时长无效')
        if not 50<=duration<=60000:raise ValueError('每段动画时长需在50毫秒至60秒之间')
        if path.suffix.lower()!='.webm':
            with Image.open(path) as im:
                if im.width*im.height>16777216:raise ValueError('动画分辨率过大')
                for frame in range(im.n_frames):im.seek(frame);im.load()
        scale=float(item.get('renderScale',1))
        if not .1<=scale<=3:raise ValueError('素材缩放参数无效')
        offset=item.get('renderOffset',[0,0])
        if len(offset)!=2 or any(abs(float(v))>2 for v in offset):raise ValueError('素材偏移参数无效')
    return manifest

def import_character(source,destination):
    source=Path(source).resolve();manifest=validate_character(source)
    key=hashlib.sha256(str(source).encode()).hexdigest()[:12]
    dest=Path(destination)/key;dest.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='import-',dir=dest.parent))
    try:
        converted={}
        for item in all_items(manifest)+__import__('sustained_assets').seam_items(manifest):
            name=item.get('playbackFile') or item['file'];src=checked_path(source,name)
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
            if src.suffix.lower()=='.webm':
                from optional_tools import find_ffmpeg
                converter=find_ffmpeg()
                if not converter:raise ValueError('导入 WebM 需要 FFmpeg；请在角色页选择本机转换工具。WebP/GIF 可直接导入。')
                target=target.with_suffix('.webp')
                # libvpx preserves a WebM alpha plane when supplied by the source.
                for codec in ('libvpx-vp9','libvpx'):
                    result=subprocess.run([converter,'-v','error','-c:v',codec,'-i',str(src),'-t','60','-vf','scale=720:720:force_original_aspect_ratio=decrease,pad=720:720:(ow-iw)/2:(oh-ih)/2:color=black@0','-an','-loop','0','-c:v','libwebp_anim','-y',str(target)],capture_output=True,timeout=150,creationflags=0x08000000 if sys.platform=='win32' else 0)
                    if not result.returncode:break
                if result.returncode:raise ValueError('WebM转换失败，请先导出透明WebP或GIF')
                converted[name]=str(target.relative_to(stage)).replace('\\','/')
            else:shutil.copy2(src,target)
        def rewrite(value):
            if isinstance(value,dict):
                original=value.get('playbackFile') or value.get('file')
                if original in converted:value['playbackFile']=converted[original]
                for child in value.values():rewrite(child)
            elif isinstance(value,list):
                for child in value:rewrite(child)
        rewrite(manifest)
        atomic_json(stage/'素材清单.json',manifest);validate_character(stage)
        if dest.exists():
            dest=dest.with_name(key+'-'+str(__import__('time').time_ns()))
        stage.rename(dest)
        return dest.name,manifest
    except Exception:
        # Remove only a freshly created staging directory within our character library.
        if stage.is_relative_to(Path(destination).resolve()) and stage.name.startswith('import-'):shutil.rmtree(stage)
        raise

def codex_desktop_open():
    """Inspect package GUI processes on the monitor thread, never the UI loop."""
    from codex_connection import is_wsl_source
    if is_wsl_source():return None
    import psutil
    denied=False
    for process in psutil.process_iter(['name']):
        try:
            if (process.info['name'] or '').lower() not in ('codex.exe','chatgpt.exe'):continue
            path=process.exe().lower()
            if 'openai.codex_' in path:return True
        except psutil.AccessDenied:denied=True
        except (psutil.NoSuchProcess,OSError):pass
    return None if denied else False

def codex_conversation_url(session):
    import re
    from uuid import UUID
    from session_read_state import session_id
    try:sid=str(UUID(session_id(session)))
    except (ValueError,AttributeError,TypeError):raise OSError('该会话缺少有效的 Codex 会话 ID') from None
    if str(session).lower()!=sid and not re.fullmatch(r'rollout-[0-9Tt_.:-]+-'+re.escape(sid),str(session),re.I):
        raise OSError('该会话缺少有效的 Codex 会话 ID')
    return 'codex://threads/'+sid

def open_codex(session=None):
    from codex_connection import is_wsl_source,saved_paths
    if is_wsl_source():
        from wsl_codex import command
        args=() if session is None else ('resume',codex_conversation_url(session).rsplit('/',1)[-1])
        target=command(saved_paths(),*args)
        terminal=shutil.which('wt.exe')
        if terminal:subprocess.Popen([terminal,'new-tab','--title','Codex WSL',*target],creationflags=0x08000000 if os.name=='nt' else 0)
        else:subprocess.Popen(target,creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
        return
    if session is not None:
        url=codex_conversation_url(session)
        try:os.startfile(url)
        except OSError:raise OSError('无法打开对应会话，请确认 Codex 已安装并支持会话链接') from None
        return
    import psutil
    for p in psutil.process_iter(['name','exe']):
        try:
            name=(p.info['name'] or '').lower();exe=p.info['exe'] or ''
            if name in ('codex.exe','chatgpt.exe') and 'openai.codex_' in exe.lower():
                os.startfile(exe);return
        except (psutil.NoSuchProcess,psutil.AccessDenied,OSError):pass
    # App Execution Alias, then installed package registration (no guessed package id).
    alias=Path(os.environ.get('LOCALAPPDATA',''))/'Microsoft/WindowsApps/Codex.exe'
    if alias.is_file():os.startfile(alias);return
    script="Get-StartApps | Where-Object { $_.Name -eq 'Codex' } | Select-Object -First 1 -ExpandProperty AppID"
    try:result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,text=True,timeout=8,creationflags=0x08000000)
    except subprocess.TimeoutExpired:raise OSError('查找 Codex 安装超时，请从开始菜单打开后重试') from None
    appid=result.stdout.strip()
    if not appid:raise OSError('未找到 Codex 安装，请先从开始菜单打开一次')
    os.startfile('shell:AppsFolder\\'+appid)
