"""Windows Shell links, without command interpreters or executable scripts."""
import ctypes,os,re,subprocess,sys,uuid
from ctypes import wintypes
from pathlib import Path

def _link_action(action):
    # Each worker owns its COM initialization; tolerate an existing apartment.
    ole=ctypes.OleDLL('ole32');ole.CoInitializeEx.argtypes=[ctypes.c_void_p,wintypes.DWORD]
    ole.CoInitializeEx.restype=ctypes.c_long
    hr=ole.CoInitializeEx(None,2);initialized=hr in (0,1)
    if not initialized and hr!=-2147417850:raise OSError('Windows 快捷方式服务初始化失败')
    link=None
    try:
        import comtypes
        from comtypes import IUnknown,GUID,COMMETHOD,HRESULT
        class IShellLinkW(IUnknown):
            _iid_=GUID('{000214F9-0000-0000-C000-000000000046}')
            _methods_=[
                COMMETHOD([],HRESULT,'GetPath',(['in'],wintypes.LPWSTR,'path'),(['in'],ctypes.c_int,'size'),(['in'],ctypes.c_void_p,'find'),(['in'],wintypes.DWORD,'flags')),
                COMMETHOD([],HRESULT,'GetIDList',(['in'],ctypes.c_void_p,'value')),
                COMMETHOD([],HRESULT,'SetIDList',(['in'],ctypes.c_void_p,'value')),
                COMMETHOD([],HRESULT,'GetDescription',(['in'],wintypes.LPWSTR,'value'),(['in'],ctypes.c_int,'size')),
                COMMETHOD([],HRESULT,'SetDescription',(['in'],wintypes.LPCWSTR,'value')),
                COMMETHOD([],HRESULT,'GetWorkingDirectory',(['in'],wintypes.LPWSTR,'value'),(['in'],ctypes.c_int,'size')),
                COMMETHOD([],HRESULT,'SetWorkingDirectory',(['in'],wintypes.LPCWSTR,'value')),
                COMMETHOD([],HRESULT,'GetArguments',(['in'],wintypes.LPWSTR,'value'),(['in'],ctypes.c_int,'size')),
                COMMETHOD([],HRESULT,'SetArguments',(['in'],wintypes.LPCWSTR,'value')),
                COMMETHOD([],HRESULT,'GetHotkey',(['in'],ctypes.c_void_p,'value')),
                COMMETHOD([],HRESULT,'SetHotkey',(['in'],wintypes.WORD,'value')),
                COMMETHOD([],HRESULT,'GetShowCmd',(['in'],ctypes.POINTER(ctypes.c_int),'value')),
                COMMETHOD([],HRESULT,'SetShowCmd',(['in'],ctypes.c_int,'value')),
                COMMETHOD([],HRESULT,'GetIconLocation',(['in'],wintypes.LPWSTR,'path'),(['in'],ctypes.c_int,'size'),(['in'],ctypes.POINTER(ctypes.c_int),'index')),
                COMMETHOD([],HRESULT,'SetIconLocation',(['in'],wintypes.LPCWSTR,'path'),(['in'],ctypes.c_int,'index')),
                COMMETHOD([],HRESULT,'SetRelativePath',(['in'],wintypes.LPCWSTR,'path'),(['in'],wintypes.DWORD,'reserved')),
                COMMETHOD([],HRESULT,'Resolve',(['in'],wintypes.HWND,'window'),(['in'],wintypes.DWORD,'flags')),
                COMMETHOD([],HRESULT,'SetPath',(['in'],wintypes.LPCWSTR,'path')),
            ]
        link=comtypes.CoCreateInstance(GUID('{00021401-0000-0000-C000-000000000046}'),interface=IShellLinkW,clsctx=1)
        return action(link)
    except Exception as error:
        if isinstance(error,OSError):raise
        raise OSError('Windows 快捷方式操作失败：'+str(error)) from error
    finally:
        link=None
        if initialized:ole.CoUninitialize()

def _plain(path):
    path=Path(path).absolute()
    for parent in (path,*path.parents):
        if parent.is_symlink() or parent.is_junction():raise OSError('快捷方式路径不能是链接或目录联接')
    return path

def write_shortcut(path,exe,arguments='',description='白龙桌宠增强版',*,stage_dir=None):
    path=_plain(path);exe=Path(exe).absolute();path.parent.mkdir(parents=True,exist_ok=True)
    stage_dir=_plain(stage_dir) if stage_dir is not None else path.parent
    temp=stage_dir/(path.name+'.'+uuid.uuid4().hex+'.tmp')
    def save(link):
        from comtypes.persist import IPersistFile
        link.SetPath(str(exe));link.SetArguments(arguments);link.SetWorkingDirectory(str(exe.parent))
        link.SetDescription(description);link.SetIconLocation(str(exe),0);link.SetShowCmd(1)
        persistence=link.QueryInterface(IPersistFile);persistence.Save(str(temp),True)
    try:
        _link_action(save)
        os.replace(temp,path)
    except BaseException:
        try:temp.unlink(missing_ok=True)
        except OSError:pass
        raise

def read_shortcut(path):
    path=_plain(path)
    if not path.is_file():raise FileNotFoundError(path)
    def read(link):
        from comtypes.persist import IPersistFile
        persistence=link.QueryInterface(IPersistFile);persistence.Load(str(path),0)
        result={}
        for name,method in (('target','GetPath'),('arguments','GetArguments'),('cwd','GetWorkingDirectory')):
            buffer=ctypes.create_unicode_buffer(32768)
            if name=='target':link.GetPath(buffer,len(buffer),None,4)
            else:getattr(link,method)(buffer,len(buffer))
            result[name]=buffer.value
        buffer=ctypes.create_unicode_buffer(32768);index=ctypes.c_int();link.GetIconLocation(buffer,len(buffer),ctypes.byref(index))
        result.update(icon=buffer.value,iconIndex=index.value);return result
    return _link_action(read)

def command_parts(command):
    shell=ctypes.WinDLL('shell32');shell.CommandLineToArgvW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype=ctypes.POINTER(wintypes.LPWSTR)
    count=ctypes.c_int();values=shell.CommandLineToArgvW(command,ctypes.byref(count))
    if not values:raise OSError('启动命令格式无效')
    try:return [values[i] for i in range(count.value)]
    finally:
        kernel=ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree(values)

def legacy_command(path):
    try:text=Path(path).read_text(encoding='utf-16').strip()
    except (OSError,UnicodeError):return None
    pattern=r'(?:Option Explicit\s*)?(?:Dim (?:s|shell)\s*)?Set (?P<name>s|shell)\s*=\s*CreateObject\("WScript.Shell"\)\s*(?P=name)\.Run "(?P<command>(?:""|[^"])*)",\s*0,\s*False'
    match=re.fullmatch(pattern,text,re.IGNORECASE)
    return command_parts(match['command'].replace('""','"')) if match else None

def command_matches(path,command):
    try:
        info=read_shortcut(path);parts=[info['target']]+command_parts('unused '+info['arguments'])[1:]
    except OSError:return False
    return len(parts)==len(command) and all(os.path.normcase(a)==os.path.normcase(str(b)) for a,b in zip(parts,command))

def _same_family(old,command,roots=()):
    if not old or len(old)!=len(command):return False
    if [os.path.normcase(str(x)) for x in old]==[os.path.normcase(str(x)) for x in command]:return True
    before=Path(old[0]);after=Path(command[0])
    if before.name.lower()!='bailongenhanced.exe' or after.name.lower()!='bailongenhanced.exe' or old[1:]!=[str(x) for x in command[1:]]:return False
    allowed=[after.parent.parent.parent,*map(Path,roots)]
    return any(before.parent.parent==root/'versions' for root in allowed)

def quarantine_startup_residue(path,command,roots=()):
    """Move only verified leftovers from the old writer out of Startup."""
    path=_plain(path)
    if not path.parent.is_dir():return []
    pattern=re.compile(re.escape(path.name)+r'\.[0-9a-f]{32}\.tmp',re.IGNORECASE)
    moved=[]
    for candidate in path.parent.iterdir():
        if not pattern.fullmatch(candidate.name):continue
        try:
            info=read_shortcut(candidate)
            old=[info['target']]+command_parts('unused '+info['arguments'])[1:]
            if not _same_family(old,command,roots):continue
            recovery=_plain(path.parent.parent/'.bailong-shortcut-recovery')
            recovery.mkdir(exist_ok=True)
            target=recovery/(uuid.uuid4().hex+'-'+candidate.name)
            os.rename(candidate,target)
            moved.append(target)
        except OSError:continue
    return moved

def startup_entry(path,legacy,command,enabled,previous_root=None):
    """Prepare the replacement before retiring a strictly recognized old script."""
    path=Path(path);legacy=Path(legacy)
    roots=[previous_root] if previous_root else []
    if path.exists():
        info=read_shortcut(path);old=[info['target']]+command_parts('unused '+info['arguments'])[1:]
        if not _same_family(old,command,roots):raise OSError('同名启动快捷方式不属于当前程序，已保留')
    if enabled:write_shortcut(path,command[0],subprocess.list2cmdline([str(a) for a in command[1:]]),stage_dir=path.absolute().parent.parent)
    elif path.exists():path.unlink()
    old=legacy_command(legacy)
    if _same_family(old,command,roots):
        # The exact app-specific legacy path and generated script grammar are
        # both checked; never execute or retire an arbitrary script.
        legacy.unlink()
    quarantine_startup_residue(path,command,roots)

def shell_folder(csidl):
    buffer=ctypes.create_unicode_buffer(32768)
    function=ctypes.WinDLL('shell32').SHGetFolderPathW
    if function(None,csidl,None,0,buffer):raise OSError('无法确定快捷方式目录')
    return Path(buffer.value)

def install_entries(exe,desktop=None,programs=None,previous_root=None):
    exe=Path(exe).absolute();desktop=Path(desktop) if desktop is not None else shell_folder(16)
    programs=Path(programs) if programs is not None else shell_folder(2)
    write_shortcut(desktop/'白龙桌宠增强版.lnk',exe);write_shortcut(programs/'白龙桌宠增强版.lnk',exe)
    alias=desktop/'白龙桌宠.lnk'
    if not alias.is_file():return
    try:target=Path(read_shortcut(alias)['target']).absolute()
    except OSError:return
    roots=[exe.parent.parent.parent]+([Path(previous_root)] if previous_root else [])
    if target.name.lower()=='bailongenhanced.exe' and any(target.parent.parent==root/'versions' for root in roots):alias.unlink()
