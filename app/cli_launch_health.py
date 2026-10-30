"""Persist a failed CLI startup until manual retry or executable replacement."""
import hashlib,json,os,threading,time
from pathlib import Path

_LOCK=threading.RLock()
_MEMORY={}
STARTUP_ERRORS={'cli_native_exit','cli_startup_failed','cli_startup_timeout','cli_startup_blocked'}

def state_path(path=None):
    if path is False:return None
    return Path(path) if path is not None else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced/quota-cli-startup.json'

def identity(executable):
    path=Path(executable).resolve()
    try:st=path.stat();stamp=(st.st_size,st.st_mtime_ns)
    except OSError:stamp=(None,None)
    return hashlib.sha256(repr((str(path).casefold(),stamp)).encode()).hexdigest()

def load(path=None):
    path=state_path(path)
    if path is None:return {}
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) and data.get('code') in STARTUP_ERRORS else {}
    except (OSError,ValueError):return dict(_MEMORY.get(str(path),{}))

def save(data,path=None):
    path=state_path(path)
    if path is None:return
    with _LOCK:
        if len(_MEMORY)>=4 and str(path) not in _MEMORY:_MEMORY.pop(next(iter(_MEMORY)))
        _MEMORY[str(path)]=dict(data)
    try:
        with _LOCK:
            path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');os.replace(temp,path)
    except OSError:pass

def record(executable,code,exit_code=None,path=None,phase='launch'):
    save(dict(identity=identity(executable),executable=str(Path(executable).resolve()),code=code,exit_code=exit_code,phase=phase,time=time.time()),path)

def blocked(executable,path=None):return load(path).get('identity')==identity(executable)
