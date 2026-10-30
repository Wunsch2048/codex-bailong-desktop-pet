"""Read-only Codex account adapter. No prompts, token generation or resets."""
import json, os, queue, shutil, subprocess, threading, time, sys, ctypes
from pathlib import Path
from datetime import datetime
from version import VERSION

class QuotaFailure(RuntimeError):
    def __init__(self,message,code,phase='request',retryable=False,executable=None,exit_code=None):
        super().__init__(message);self.code=code;self.phase=phase;self.retryable=retryable
        self.executable=executable;self.exit_code=exit_code

def cli_exit_failure(process,executable,phase):
    code=process.poll()
    if code is None:
        try:code=process.wait(timeout=.15)
        except subprocess.TimeoutExpired:pass
    unsigned=code & 0xffffffff if isinstance(code,int) else None
    native=sys.platform=='win32' and unsigned is not None and unsigned & 0xc0000000==0xc0000000
    if native or (phase=='initialize' and code is not None):
        shown=f'0x{unsigned:08X}' if unsigned is not None else '未知'
        return QuotaFailure('Codex启动失败（'+shown+'），已暂停自动查询，点击刷新重试。',
            'cli_native_exit' if native else 'cli_startup_failed',phase,False,executable,shown)
    return QuotaFailure('额度连接暂时中断，请稍后再试。','connection_closed',phase,True)

def classify_error(message,phase='request'):
    lower=message.lower()
    if any(s in lower for s in ('unauthorized','401','not authenticated','not logged','sign in','please log','token expired')):
        return QuotaFailure('Codex登录状态已失效，请在Codex中重新登录。','authentication',phase)
    if any(s in lower for s in ('error sending request','timed out','timeout','connection','dns','tls','certificate','502','503','504','temporarily')):
        return QuotaFailure('网络连接暂时失败，请检查网络或代理后再试。','network',phase,True)
    return QuotaFailure('额度服务暂未返回结果，请稍后再试。','service',phase)

def log_attempt(attempt,seconds,error=None,log_path=None):
    if log_path is False:return
    # Program directories and shared resources are immutable deployment payloads.
    root=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced'
    path=Path(log_path) if log_path else root/'额度查询日志.jsonl'
    event={'time':datetime.now().isoformat(timespec='seconds'),'attempt':attempt,'seconds':round(seconds,3),'result':'success' if error is None else error.code}
    if error:
        event['phase']=error.phase
        if error.exit_code:event['exit_code']=error.exit_code
        if error.executable:event['executable']=str(error.executable)
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        lines=path.read_text(encoding='utf-8').splitlines()[-199:] if path.exists() else []
        path.write_text('\n'.join(lines+[json.dumps(event,ensure_ascii=False)])+'\n',encoding='utf-8')
    except OSError:pass

def read_quota(timeout=20,cancel=None,attempts=2,log_path=None,manual=False,health_path=None):
    from cli_launch_health import load,blocked,record,save,STARTUP_ERRORS
    if not manual and load(health_path):
        executable=find_codex()
        if blocked(executable,health_path):
            raise QuotaFailure('Codex上次启动失败，自动查询已暂停，点击刷新重试。','cli_startup_blocked','launch')
    for attempt in range(1,attempts+1):
        started=time.monotonic()
        try:
            try:result=_read_quota_once(timeout,cancel)
            except OSError:raise QuotaFailure('额度连接暂时中断，请稍后再试。','connection_io','transport',True)
            log_attempt(attempt,time.monotonic()-started,log_path=log_path)
            if load(health_path):save({},health_path)
            return result
        except QuotaFailure as error:
            if error.code in STARTUP_ERRORS and error.executable:record(error.executable,error.code,error.exit_code,health_path,phase=error.phase)
            log_attempt(attempt,time.monotonic()-started,error,log_path)
            if not error.retryable or attempt==attempts or (cancel and cancel.is_set()):raise
            if cancel:
                if cancel.wait(.8):raise QuotaFailure('额度查询已取消','cancelled')
            else:time.sleep(.8)

def find_codex():
    from codex_connection import find_executable
    return find_executable()


def _read_quota_once(timeout=20, cancel=None):
    executable = find_codex()
    from codex_connection import child_environment,cli_command
    try:command=cli_command(executable,'app-server')
    except RuntimeError as error:raise QuotaFailure(str(error),'wsl_stopped','discovery') from error
    from process_launch import clean_dll_search
    process=None
    try:
        with clean_dll_search():
            process = subprocess.Popen(command, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=child_environment(),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as error:
        if process is not None:
            try:close_cli(process)
            except (OSError,subprocess.TimeoutExpired):pass
        code=getattr(error,'winerror',None) or error.errno
        raise QuotaFailure(f'系统未能启动Codex（{code}），自动查询已暂停，点击刷新重试。','cli_startup_failed','launch',False,executable,str(code)) from error
    messages = queue.Queue()
    def receive():
        for line in process.stdout:
            try: messages.put(json.loads(line))
            except ValueError: pass
        messages.put(None)
    threading.Thread(target=receive, daemon=True).start()
    deadline = time.monotonic() + timeout
    def send(message):
        try:process.stdin.write(json.dumps(message)+'\n'); process.stdin.flush()
        except (OSError,ValueError):raise cli_exit_failure(process,executable,'initialize' if message.get('id')==1 else 'rate_limits')
    def result(request_id):
        while time.monotonic() < deadline:
            if cancel and cancel.is_set():raise QuotaFailure('额度查询已取消','cancelled')
            try: message = messages.get(timeout=min(.1,max(.01, deadline-time.monotonic())))
            except queue.Empty: continue
            phase='initialize' if request_id==1 else 'rate_limits'
            if message is None:raise cli_exit_failure(process,executable,phase)
            if message.get('id') == request_id:
                if 'error' in message: raise classify_error(message['error'].get('message','额度读取失败'),phase)
                return message['result']
        if request_id==1:raise QuotaFailure('Codex启动未响应，自动查询已暂停，点击刷新重试。','cli_startup_timeout','initialize',False,executable)
        raise QuotaFailure('额度加载超时，请检查网络或代理后再试。','timeout','rate_limits',True)
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'bailong_pet','title':'白龙桌宠','version':VERSION}}})
        result(1); send({'method':'initialized'})
        send({'id':2,'method':'account/rateLimits/read'})
        return result(2)
    finally:
        failing=sys.exc_info()[0] is not None
        try:close_cli(process)
        except (OSError,subprocess.TimeoutExpired):
            if not failing:raise

def close_cli(process):
    try:process.stdin.close()
    except (OSError,ValueError):pass
    # stdin EOF lets the Linux process exit before terminating its Windows
    # launcher. Never use a distro-wide kill or shutdown for this request.
    if process.poll() is None:
        try:process.wait(timeout=.2)
        except subprocess.TimeoutExpired:pass
    if process.poll() is None:process.terminate()
    try:process.wait(timeout=1)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    try:process.stdout.close()
    except (OSError,ValueError):pass

def quota_windows(data,allow_empty=False):
    buckets = data.get('rateLimitsByLimitId') or {}
    bucket = buckets.get('codex') or data.get('rateLimits')
    if not bucket: raise RuntimeError('当前账户没有可读取的 Codex 额度。')
    windows=[]
    for key in ('primary','secondary'):
        window=bucket.get(key)
        if not window: continue
        minutes=window.get('windowDurationMins')
        name={300:'5小时',10080:'一周'}.get(minutes, f'{minutes}分钟' if minutes else '额度窗口')
        used=window.get('usedPercent')
        remaining=None if used is None else max(0,min(100,100-float(used)))
        item={'name':name,'remaining':remaining,'resetsAt':window.get('resetsAt')}
        if bucket.get('planType'):item['plan']=str(bucket['planType'])[:40].lower()
        windows.append(item)
    if not windows and not allow_empty: raise RuntimeError('服务器暂未提供额度窗口。')
    return windows
