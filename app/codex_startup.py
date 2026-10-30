"""Optional per-user Codex launch companion. No Qt or character assets loaded."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil

POLL_SECONDS=2
WATCH_FLAG='--watch-codex'

def data_dir():return Path(os.environ['LOCALAPPDATA'])/'BailongEnhanced'
def install_root():return __import__('storage_locations').install_root()
def preference_path():return data_dir()/'codex-startup.json'
def startup_path():return Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup/BailongCodexSync.lnk'
def read_json(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');os.replace(temp,path)
def enabled():return read_json(preference_path()).get('enabled') is True

def app_command():
    if getattr(sys,'frozen',False):return [sys.executable]
    return [str(Path(sys.executable).with_name('pythonw.exe')),str(Path(__file__).with_name('enhanced.py'))]

def supports_watcher(exe):
    try:return tuple(map(int,Path(exe).parent.name.split('-')[0].split('.'))) >= (0,8,1)
    except ValueError:return False

def register(exe=None,previous_root=None):
    """Installer calls this inside its existing recoverable entry transaction."""
    path=startup_path()
    command=[str(exe)] if exe is not None else app_command()
    from windows_entries import startup_entry
    startup_entry(path,path.with_suffix('.vbs'),command+[WATCH_FLAG],enabled() and (exe is None or supports_watcher(exe)),previous_root)

def ensure_watcher(executable=None):
    if enabled():
        return spawn(([str(executable)] if executable else app_command())+[WATCH_FLAG])

def spawn(command):
    env=os.environ.copy()
    for key in ('BAILONG_DEPLOY_TOKEN','BAILONG_DEPLOY_RECEIPT'):env.pop(key,None)
    return subprocess.Popen(command,creationflags=0x08000000,close_fds=True,env=env)

def stop_watchers(root=None):
    root=Path(root or install_root()).resolve();manifest=read_json(root/'installations.json')
    known={(root/'versions'/name/'BailongEnhanced.exe').resolve() for name in manifest.get('versions',[]) if isinstance(name,str) and (root/'versions'/name).resolve().parent==(root/'versions').resolve()}
    stopped=[]
    for process in psutil.process_iter(['exe']):
        try:
            if process.info['exe'] and Path(process.info['exe']).resolve() in known and WATCH_FLAG in process.cmdline():
                process.terminate();stopped.append(process)
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    if not stopped:return
    _,alive=psutil.wait_procs(stopped,timeout=3)
    if alive:raise OSError('启动监听尚未退出，请稍后重试。')

def configure(value,executable=None):
    """Keep prior preference and startup registration if the OS refuses a write."""
    pref=preference_path();entry=startup_path();legacy=entry.with_suffix('.vbs')
    before=pref.read_bytes() if pref.exists() else None
    old_entry=entry.read_bytes() if entry.exists() else None
    old_legacy=legacy.read_bytes() if legacy.exists() else None
    try:
        atomic(pref,dict(enabled=bool(value)));register(executable)
        if value:ensure_watcher(executable)
    except OSError:
        if before is None:pref.unlink(missing_ok=True)
        else:pref.write_bytes(before)
        if old_entry is None:entry.unlink(missing_ok=True)
        else:entry.write_bytes(old_entry)
        if old_legacy is None:legacy.unlink(missing_ok=True)
        else:legacy.write_bytes(old_legacy)
        raise

def desktop_executable(path):
    """Exclude Codex CLI, ChatGPT-only packages and Electron helper processes."""
    value=str(path).lower().replace('/','\\')
    name=value.rsplit('\\',1)[-1]
    if name not in ('chatgpt.exe','codex.exe'):return False
    if '\\openai.codex_' in value:return True
    # Codex++'s managed Store copy retains OpenAI.Codex_ in its path above.
    # Also accept a standalone Codex GUI only when its Electron bundle exists.
    return name=='codex.exe' and (Path(path).parent/'resources/app.asar').is_file()

def desktop_sessions():
    sessions=set();uncertain=False
    for process in psutil.process_iter(['name']):
        try:
            if (process.info['name'] or '').lower() not in ('codex.exe','chatgpt.exe'):continue
            if not desktop_executable(process.exe()):continue
            if any(arg.startswith('--type=') for arg in process.cmdline()[1:]):continue
            sessions.add((process.pid,process.create_time()))
        except psutil.AccessDenied:uncertain=True
        except (psutil.NoSuchProcess,OSError):pass
    return sessions if sessions or not uncertain else None

class LaunchGate:
    def __init__(self):self.sessions=set();self.absent=0
    def observe(self,current):
        if current is None:return False
        if not current:
            self.absent+=1
            if self.absent>=2:self.sessions=set()
            return False
        self.absent=0;launch=not self.sessions or self.sessions.isdisjoint(current)
        self.sessions=set(current)
        return launch

def current_command():
    if not getattr(sys,'frozen',False):return app_command()
    root=install_root();current=read_json(root/'installations.json').get('current','')
    if not isinstance(current,str) or not current:return app_command()
    folder=root/'versions'/current
    if folder.resolve().parent!=(root/'versions').resolve():return None
    exe=folder/'BailongEnhanced.exe'
    return [str(exe)] if exe.is_file() and supports_watcher(exe) else None

def main():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.CreateMutexW(None,False,'Local\\BailongCodexSyncV1')
    if not handle:return 1
    if ctypes.get_last_error()==183:kernel.CloseHandle(handle);return 0
    gate=LaunchGate();state=dict(pid=os.getpid(),started=time.time(),launches=0)
    path=data_dir()/'codex-watch-state.json';replacement=None
    try:
        while enabled():
            try:
                # Install/rollback owns its launch transaction; do not race it.
                state['paused_for_deployment']=(install_root()/'deployment-journal.json').exists()
                if not state['paused_for_deployment']:
                    command=current_command()
                    if command is None:
                        raise OSError('当前安装入口暂不可用，等待下次检查')
                    if getattr(sys,'frozen',False) and Path(command[0]).resolve()!=Path(sys.executable).resolve():
                        replacement=command;break
                    sessions=desktop_sessions()
                    if gate.observe(sessions):
                        try:
                            spawn(command+['--from-codex'])
                            state.update(launches=state['launches']+1,last_launch=time.time())
                        except OSError:
                            gate.sessions=set()
                            raise
                    state['codex_open']=None if sessions is None else bool(sessions)
                state.pop('error',None)
            except (OSError,ValueError,psutil.Error) as error:
                # A temporary process/entry read failure must not kill the
                # independent listener needed for the next Codex launch.
                state['error']=str(error)[:180]
            now=time.time()
            signature=(state.get('codex_open'),state.get('paused_for_deployment'),state.get('error'),state['launches'])
            if signature!=state.get('_signature') or now-state.get('written',0)>=30:
                state['_signature']=signature;state['written']=now
                try:atomic(path,{k:v for k,v in state.items() if k!='_signature'})
                except OSError:
                    state.pop('_signature',None) # retry diagnostics next poll
            time.sleep(POLL_SECONDS)
    finally:kernel.CloseHandle(handle)
    if replacement and enabled():spawn(replacement+[WATCH_FLAG])
    return 0


class ExitGate:
    """Only close after this run actually observed Codex, never on unknown data."""
    def __init__(self):self.reset()
    def reset(self):self.seen=False;self.absent=0
    def observe(self,current):
        if current is None:self.absent=0;return False
        if current:self.seen=True;self.absent=0;return False
        if not self.seen:return False
        self.absent+=1
        return self.absent>=3
