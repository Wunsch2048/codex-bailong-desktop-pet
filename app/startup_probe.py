"""Isolated frozen-parent -> frozen-child Qt startup check. No account/app state."""
import ctypes,json,os,sys,subprocess
from pathlib import Path

def save(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def run(output,previous=None,child=False):
    output=Path(output)
    if child:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        app=QApplication.instance() or QApplication([])
        api=ctypes.windll.kernel32
        api.GetModuleHandleW.argtypes=[ctypes.c_wchar_p];api.GetModuleHandleW.restype=ctypes.c_void_p
        api.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint32];api.GetModuleFileNameW.restype=ctypes.c_uint32
        modules={}
        for name in ('Qt6Core.dll','qwindows.dll'):
            handle=api.GetModuleHandleW(name);buffer=ctypes.create_unicode_buffer(32768)
            if handle and api.GetModuleFileNameW(handle,buffer,len(buffer)):modules[name]=buffer.value
        base=Path(sys._MEIPASS).resolve()
        checks=dict(qtFromOwnRuntime=len(modules)==2 and all(Path(p).resolve().is_relative_to(base) for p in modules.values()),
                    noInheritedPlatformPath='QT_QPA_PLATFORM_PLUGIN_PATH' not in os.environ)
        QTimer.singleShot(0,app.quit);app.exec()
        save(output,dict(passed=all(checks.values()),checks=checks,modules=modules,exe=sys.executable))
        return 0 if all(checks.values()) else 1
    from process_launch import launch_own,clean_dll_search
    if not getattr(sys,'frozen',False) or not previous:raise ValueError('Requires frozen Windows executable and a previous runtime')
    previous=Path(previous).resolve()
    if not (previous/'PySide6/plugins/platforms/qwindows.dll').is_file():raise ValueError('Previous Qt runtime not found')
    child_output=output.with_name(output.stem+'-child.json');process=None
    changed={key:os.environ.get(key) for key in ('QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QML2_IMPORT_PATH','PATH')}
    try:
        os.environ.update(QT_PLUGIN_PATH=str(previous/'PySide6/plugins'),QT_QPA_PLATFORM_PLUGIN_PATH=str(previous/'PySide6/plugins/platforms'),QML2_IMPORT_PATH=str(previous/'PySide6/qml'))
        os.environ['PATH']=str(previous)+os.pathsep+os.environ.get('PATH','')
        cases={}
        for legacy in (False,True):
            child_output=output.with_name(output.stem+('-legacy-child.json' if legacy else '-child.json'))
            with clean_dll_search():
                if not ctypes.windll.kernel32.SetDllDirectoryW(str(previous)):raise OSError('Cannot arrange isolated parent DLL condition')
                launch=subprocess.Popen if legacy else launch_own
                env=dict(os.environ,BAILONG_ISOLATED='1') if legacy else {'BAILONG_ISOLATED':'1'}
                process=launch([sys.executable,'--startup-probe',str(child_output),'--startup-probe-child'],env=env,creationflags=0x08000000)
                code=process.wait(timeout=25)
            result=json.loads(child_output.read_text(encoding='utf-8')) if child_output.is_file() else {}
            cases['legacyParent' if legacy else 'isolatedParent']=dict(passed=code==0 and result.get('passed') is True,returncode=code,child=result)
        passed=all(case['passed'] for case in cases.values())
        save(output,dict(passed=passed,cases=cases,
            scope='Isolated frozen parent with previous-version DLL directory and Qt paths; not a reproduction of the historical access violation'))
        return 0 if passed else 1
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(2)
            except subprocess.TimeoutExpired:process.kill();process.wait(2)
        for key,value in changed.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
