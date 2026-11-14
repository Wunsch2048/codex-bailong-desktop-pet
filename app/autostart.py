"""Start the pet on a desktop GPT process's absent-to-present transition."""
import ctypes,json,os,subprocess,sys,time
from pathlib import Path
from datetime import datetime
import psutil

from platform_paths import app_root
ROOT=app_root()

def gpt_is_open():
    for process in psutil.process_iter(['name','exe']):
        try:
            name=(process.info['name'] or '').lower()
            path=(process.info['exe'] or '').lower().replace('/', '\\')
            if name=='chatgpt.exe' and any(package in path for package in ('\\openai.codex_', '\\openai.chatgpt_')):
                return True
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    return False

def launch_pet():
    if getattr(sys,'frozen',False):
        return subprocess.Popen([sys.executable],cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW).pid
    python=Path(sys.executable).with_name('pythonw.exe')
    return subprocess.Popen([str(python),str(ROOT/'app/pet.py')],cwd=ROOT,
                            creationflags=subprocess.CREATE_NO_WINDOW).pid

def startup_entry():
    buffer=ctypes.create_unicode_buffer(32768)
    result=ctypes.windll.shell32.SHGetFolderPathW(None,7,None,0,buffer)
    if result!=0:raise RuntimeError('无法找到当前用户的Windows启动文件夹。')
    return Path(buffer.value)/'BailongPetAutostart.vbs'

def enable_autostart():
    if getattr(sys,'frozen',False):command=f'"{sys.executable}" --autostart'
    else:command=f'"{Path(sys.executable).with_name("pythonw.exe")}" "{ROOT / "app/autostart.py"}"'
    script='Option Explicit\nDim shell\nSet shell = CreateObject("WScript.Shell")\n'
    script+=f'shell.CurrentDirectory = "{ROOT}"\n'
    script+='shell.Run "'+command.replace('"','""')+'", 0, False\n'
    startup_entry().write_text(script,encoding='utf-16')
    args=[sys.executable,'--autostart'] if getattr(sys,'frozen',False) else [str(Path(sys.executable).with_name('pythonw.exe')),str(ROOT/'app/autostart.py')]
    subprocess.Popen(args,cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)

def disable_autostart():
    entry=startup_entry()
    if entry.is_file():entry.unlink()
    state_file=ROOT/'app/自启动状态.json'
    if state_file.is_file():
        state=json.loads(state_file.read_text(encoding='utf-8'))
        try:
            process=psutil.Process(state['pid']);command=process.cmdline()
            # Only stop a monitor from this exact installation, never a reused PID.
            is_this_monitor=('--autostart' in command and Path(command[0]).resolve()==Path(sys.executable).resolve()) or any(str(ROOT/'app/autostart.py')==arg for arg in command)
            if is_this_monitor:process.terminate()
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass

def main():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    handle=kernel.CreateMutexW(None,False,'Local\\BailongPetAutostartV1')
    if not handle:return 1
    if ctypes.get_last_error()==183:return 0
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    previous=False
    state={'pid':os.getpid(),'started':datetime.now().isoformat(timespec='seconds')}
    (ROOT/'app').mkdir(exist_ok=True)
    try:
        while True:
            current=gpt_is_open()
            if current and not previous:
                try:
                    state.update(lastLaunch=datetime.now().isoformat(timespec='seconds'),petPid=launch_pet())
                    state.pop('error',None)
                except Exception as error:state['error']=str(error)
            if current!=previous or 'gptOpen' not in state:
                state['gptOpen']=current
                (ROOT/'app/自启动状态.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
            previous=current
            time.sleep(2)
    finally:kernel.CloseHandle(handle)

if __name__=='__main__':sys.exit(main())
