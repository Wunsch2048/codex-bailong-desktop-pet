"""Portable Codex discovery; inspect paths and capabilities, never credentials."""
import os,json,shutil,subprocess,sys,time
from pathlib import Path
from functools import lru_cache

def paths_file():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced/connection-paths.json'

@lru_cache(maxsize=8)
def _saved_paths(filename):
    # Freeze overrides for this process. Running monitors must not mix homes
    # after the editor saves new paths; the next app start adopts the file.
    try:
        value=json.loads(Path(filename).read_text(encoding='utf-8'))
        return {key:str(value.get(key,'')) for key in ('home','cli','source','wsl_distro','wsl_user','wsl_home','wsl_cli','wsl_path')} if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}

def saved_paths():return dict(_saved_paths(str(paths_file())))

def validate_paths(values):
    if values.get('source')=='wsl':
        from wsl_codex import validate
        return validate(values)
    result={key:str(values.get(key,'')).strip().strip('"') for key in ('home','cli')}
    if 'source' in values:result.update({key:str(values.get(key,'')) for key in ('source','wsl_distro','wsl_user','wsl_home','wsl_cli','wsl_path')});result['source']='windows'
    if result['home']:
        from wsl_codex import unc_parts
        if unc_parts(result['home']):raise ValueError('这是 WSL 数据目录，请先将连接来源切换为 WSL。')
        home=Path(os.path.expandvars(result['home'])).expanduser().resolve()
        if not home.is_dir() or not any((home/name).exists() for name in ('sessions','archived_sessions','state_5.sqlite','.codex-global-state.json')):
            raise ValueError('请选择 Codex 数据目录，其中应包含 sessions、state_5.sqlite 或本地状态文件。')
        try:next(home.iterdir(),None)
        except OSError as error:raise ValueError('所选数据目录不可读取。') from error
        result['home']=str(home)
    if result['cli']:
        cli=Path(os.path.expandvars(result['cli'])).expanduser().resolve()
        if not cli.is_file():raise ValueError('所选 CLI 文件不存在。')
        if cli.name.lower()=='codex.exe' and (cli.parent/'resources/codex.exe').is_file():
            raise ValueError('这是 Codex 桌面主程序；请选择同目录 resources 中的 codex.exe。')
        try:
            done=subprocess.run([str(cli),'--version'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=5,creationflags=0x08000000 if os.name=='nt' else 0)
        except (OSError,subprocess.TimeoutExpired) as error:raise ValueError('CLI 版本检测失败或超时。') from error
        import re
        if done.returncode or not re.search(r'codex(?:-cli)?\s+\d+\.\d+',done.stdout,re.I):raise ValueError('所选文件未返回可识别的 Codex CLI 版本。')
        result['cli']=str(cli)
    return result

def save_paths(values,destination=None):
    from desktop_core import atomic_json
    atomic_json(destination or paths_file(),values)

def user_environment(name):
    if sys.platform!='win32':return ''
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:return str(winreg.QueryValueEx(key,name)[0])
    except OSError:return ''

def data_home(home=None):
    saved=saved_paths()
    if home is None and saved.get('source')=='wsl':
        from wsl_codex import unc
        try:return Path(unc(saved['wsl_distro'],saved['wsl_home']))
        except (KeyError,ValueError):return Path(r'\\wsl$\Invalid-Bailong-Profile\__unconfigured__')
    value=home or os.environ.get('BAILONG_CODEX_HOME') or os.environ.get('CODEX_HOME') or saved_paths().get('home') or user_environment('CODEX_HOME') or Path.home()/'.codex'
    from wsl_codex import unc_parts
    if unc_parts(value):return Path(value)
    return Path(os.path.expandvars(str(value).strip().strip('"'))).expanduser().resolve()

def is_wsl_source(home=None):
    if home is None:return saved_paths().get('source')=='wsl'
    from wsl_codex import unc_parts
    return unc_parts(home) is not None

def source_identity(home):
    from wsl_codex import identity
    return identity(home)

def session_state_dir(default):
    from wsl_codex import state_dir
    return state_dir(default,data_home())

def cli_command(executable,*args):
    if is_wsl_source():
        from wsl_codex import command
        return command(saved_paths(),*args)
    if is_wsl_source(data_home()):raise RuntimeError('检测到 WSL 目录，请在设置中选择 WSL 来源后重试。')
    return [executable,*args]

def child_environment():
    from process_launch import external_environment
    env=external_environment()
    if is_wsl_source():env.pop('CODEX_HOME',None)
    else:env['CODEX_HOME']=str(data_home())
    return env

def packaged_roots():
    roots=set()
    try:
        import psutil
        for p in psutil.process_iter(['name']):
            try:
                if (p.info['name'] or '').lower() in ('chatgpt.exe','codex.exe'):
                    path=Path(p.exe())
                    if 'openai.codex_' in str(path).lower():roots.add(path.parent)
            except (psutil.NoSuchProcess,psutil.AccessDenied,OSError):pass
    except ImportError:pass
    if not roots and sys.platform=='win32':
        try:
            result=subprocess.run(['powershell.exe','-NoProfile','-Command',"Get-AppxPackage -Name OpenAI.Codex | Select-Object -ExpandProperty InstallLocation"],capture_output=True,text=True,timeout=5,creationflags=0x08000000)
            roots.update(Path(line.strip())/'app' for line in result.stdout.splitlines() if line.strip())
        except (OSError,subprocess.TimeoutExpired):pass
    return roots

def find_executable():
    if is_wsl_source():
        from wsl_codex import executable
        return executable()
    override=(os.environ.get('BAILONG_CODEX') or saved_paths().get('cli','')).strip().strip('"')
    if override:
        path=Path(os.path.expandvars(override)).expanduser()
        located=str(path) if path.is_file() else shutil.which(override)
        if located:return located
        raise RuntimeError('BAILONG_CODEX 指向的程序不存在，请修正该机器的 Codex CLI 路径。' if os.environ.get('BAILONG_CODEX') else '已保存的 CLI 路径不存在，请在设置 → Codex中重新选择。')
    local=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')
    cache=local/'OpenAI/Codex/bin';candidates=list(cache.glob('*/codex.exe')) if cache.is_dir() else []
    if (cache/'codex.exe').is_file():candidates.append(cache/'codex.exe')
    if candidates:
        try:return str(max(candidates,key=lambda p:p.stat().st_mtime))
        except OSError:pass
    for name in ('codex.exe','codex'):
        candidate=shutil.which(name)
        if candidate and (sys.platform!='win32' or Path(candidate).suffix.lower()=='.exe'):return candidate
    for root in packaged_roots():
        # The app/Codex.exe GUI is intentionally excluded; use its real CLI.
        candidate=root/'resources/codex.exe'
        if candidate.is_file():return str(candidate)
    npm=Path(os.environ.get('APPDATA') or Path.home()/'AppData/Roaming')/'npm/node_modules/@openai'
    for pattern in ('codex/vendor/*/codex/codex.exe','codex-win32-*/vendor/*/codex/codex.exe'):
        for path in npm.glob(pattern):
            if path.is_file():return str(path)
    raise RuntimeError('未找到 Codex CLI。请先安装并打开 Codex；特殊安装可设置 BAILONG_CODEX。')

def check_connection(query_quota=True,cancel=None):
    from desktop_services import codex_desktop_open
    from session_read_state import read_tracking_probe
    from quota import read_quota,quota_windows
    from desktop_core import VERSION
    from connection_health import sample
    home=data_home();wsl=is_wsl_source()
    if wsl:
        from wsl_codex import running
        online=running(saved_paths().get('wsl_distro',''))
        if not online:
            report=dict(version=VERSION,checked=time.time(),source='wsl',wsl_distro=saved_paths().get('wsl_distro',''),wsl_running=False,codex_home=str(home),home_exists=False,session_log_found=False,cli_found=False,quota_read=False,capabilities={key:sample('unavailable','wsl_stopped') for key in ('tasks','completion','read','quota','tokens','compaction')})
            report['summary']=connection_summary(report);return report
    read=read_tracking_probe(home)
    report=dict(version=VERSION,checked=time.time(),desktop_open=codex_desktop_open(),codex_home=str(home),home_exists=home.is_dir(),sessions_exists=(home/'sessions').is_dir(),read_tracking_available=read['state']=='available',cli_found=False,quota_read=False,capabilities={'read':read})
    report.update(source='wsl' if wsl else 'windows',wsl_distro=saved_paths().get('wsl_distro','') if wsl else '',wsl_running=wsl)
    if report['desktop_open'] is False and read['state']=='available':read.update(state='degraded',code='codex_closed')
    try:report['cli']=find_executable();report['cli_found']=True
    except RuntimeError as error:report['cli_error']=str(error)
    try:
        from enhanced_core import RolloutTail
        tail=RolloutTail(home);tail.poll();status=dict(tail.health)
        if status['state']=='available':status['success_at']=time.time()
        report['session_log_found']=bool(tail.files)
        report['capabilities'].update(tasks=status,completion=dict(status))
    except Exception:
        report['session_log_found']=False;report['capabilities'].update(tasks=sample('unavailable','logs_unreadable'),completion=sample('unavailable','logs_unreadable'))
    if query_quota and report['cli_found']:
        try:
            report['quota_windows']=quota_windows(read_quota(timeout=10,cancel=cancel,attempts=1,log_path=False,manual=True),allow_empty=True);report['quota_read']=True
            known=any(isinstance(w.get('remaining'),(int,float)) for w in report['quota_windows'])
            report['capabilities']['quota']=sample('available' if known else 'degraded','ok' if known else 'quota_unknown' if report['quota_windows'] else 'no_windows',time.time())
        except Exception as error:
            code=getattr(error,'code','unavailable');code=code if code in ('authentication','network','timeout','cli_missing','wsl_stopped') else 'unavailable'
            report['quota_error_code']=code;report['capabilities']['quota']=sample('unavailable',code)
    elif not report['cli_found']:report['capabilities']['quota']=sample('unavailable','cli_missing')
    root=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced'
    try:
        config=json.loads((root/'chat.json').read_text(encoding='utf-8'));report['chat_configured']=bool(config.get('providers'))
    except (OSError,ValueError):report['chat_configured']=False
    report['summary']=connection_summary(report);return report

def connection_summary(r):
    lines=['Codex 连接检查',
           ('WSL：'+r.get('wsl_distro','')+('  运行中' if r.get('wsl_running') else '  未运行或不可用')) if r.get('source')=='wsl' else '桌面应用：'+('已运行' if r.get('desktop_open') is True else '未运行或权限暂不可确认'),
           'CLI：'+('已找到' if r.get('cli_found') else '未找到，请先打开 Codex'),
           '本机状态 / Token：'+('已找到会话日志' if r.get('session_log_found') else '尚无会话，请在 Codex 中发送一次消息'),
           '账户额度：'+('查询成功' if r.get('quota_read') else '暂不可用，请检查 Codex 登录、网络及 CLI'),
           '自动已读：'+('支持当前 Codex 本地标记' if r.get('read_tracking_available') else '当前版本无可读标记，可点桌宠图标确认'),
           '独立闲聊：'+('已有服务配置；密钥仅属于当前机器用户' if r.get('chat_configured') else '需在聊天页单独配置模型服务'),
           '数据目录：'+r.get('codex_home','')]
    return '\n'.join(lines)
