"""Isolate frozen child programs from the parent's Qt/DLL runtime."""
import os,sys,subprocess,threading
from pathlib import Path
from contextlib import contextmanager

_DLL_LOCK=threading.RLock()
_QT_PATHS={'QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH','PYSIDE_DESIGNER_PLUGINS'}

def configure_frozen_qt():
    """Also protect the first update launched by an older, unpatched parent."""
    if sys.platform!='win32' or not getattr(sys,'frozen',False):return
    plugins=str(Path(sys._MEIPASS)/'PySide6/plugins')
    for key in list(os.environ):
        if key.upper() in _QT_PATHS:os.environ.pop(key)
    os.environ['QT_PLUGIN_PATH']=plugins
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.setLibraryPaths([plugins])

def external_environment():
    env=os.environ.copy()
    for key in list(env):
        if key.upper() in _QT_PATHS:env.pop(key)
    bundled=getattr(sys,'_MEIPASS',None)
    if bundled:
        root=os.path.normcase(os.path.abspath(bundled))
        def inherited(path):
            try:return os.path.commonpath((root,os.path.normcase(os.path.abspath(path))))==root
            except ValueError:return False
        env['PATH']=os.pathsep.join(p for p in env.get('PATH','').split(os.pathsep) if p and not inherited(p))
    for key in list(env):
        if key.upper().startswith('_PYI_') or key.upper()=='PYINSTALLER_RESET_ENVIRONMENT':env.pop(key)
    return env

def own_environment(extra=None):
    env=external_environment()
    # A new executable owns its own bootloader/runtime, even on the same path.
    env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    if extra:env.update(extra)
    return env

@contextmanager
def clean_dll_search():
    """SetDllDirectory is process-wide: restore the actual value, even on failure."""
    if sys.platform!='win32' or not getattr(sys,'frozen',False):yield;return
    import ctypes
    with _DLL_LOCK:
        api=ctypes.windll.kernel32
        api.GetDllDirectoryW.argtypes=[ctypes.c_uint32,ctypes.c_wchar_p];api.GetDllDirectoryW.restype=ctypes.c_uint32
        api.SetDllDirectoryW.argtypes=[ctypes.c_wchar_p];api.SetDllDirectoryW.restype=ctypes.c_int
        needed=api.GetDllDirectoryW(0,None)
        value=ctypes.create_unicode_buffer(needed+1)
        if needed:api.GetDllDirectoryW(len(value),value)
        previous=value.value or None
        if not api.SetDllDirectoryW(None):raise OSError('无法隔离子程序DLL搜索目录')
        try:yield
        finally:
            if not api.SetDllDirectoryW(previous):raise OSError('无法恢复当前程序DLL搜索目录')

def launch_own(command,**options):
    options.setdefault('cwd',str(Path(command[0]).resolve().parent))
    options['env']=own_environment(options.pop('env',None))
    with clean_dll_search():return subprocess.Popen(command,**options)
