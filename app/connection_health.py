"""Small privacy-safe capability ledger. Unknown/failed reads never mean zero."""
import copy,hashlib,time,math

CAPABILITIES={'tasks':'任务状态','completion':'完成提醒','read':'自动已读','quota':'账户额度','tokens':'Token 统计','compaction':'压缩状态'}
TTL={'tasks':25,'completion':25,'read':25,'quota':300,'tokens':100,'compaction':25}
LABELS={'available':'正常','degraded':'受限','unavailable':'不可用','unknown':'待检测'}
REASONS={
    'wsl_stopped':'所选 WSL 发行版未运行或不可用；请启动后重试。',
    'wsl_logs_only':'WSL 使用日志状态；Windows 桌面实时通道和自动已读不适用。',
    'starting':'等待本次检测。',
    'ok':'最近一次读取正常。',
    'logs_idle':'日志监测就绪，等待新任务。',
    'logs_missing':'尚无本机日志；打开 Codex 并发送一次消息。',
    'logs_unreadable':'日志读取受限；检查目录与访问权限。',
    'logs_schema':'暂不识别日志格式；保留已有状态。',
    'read_missing':'缺少已读证据；可点完成图标手动确认。',
    'read_schema':'当前已读格式不支持；可手动确认。',
    'database_busy':'数据库暂忙，稍后自动重试。',
    'index_maintenance':'正在整理本机统计索引，已有统计会保留；完成后继续更新。',
    'codex_closed':'Codex 未运行；打开后继续自动确认。',
    'authentication':'请在 Codex 中重新登录。',
    'network':'额度接口暂不可达；检查网络后重试。',
    'timeout':'额度查询超时；稍后重试。',
    'cli_missing':'未找到 CLI；检查连接路径。',
    'no_windows':'账户未提供额度窗口，不代表 0% 或无限。',
    'quota_unknown':'接口未给出可识别的剩余额度；显示未知。',
    'cli_native_exit':'Codex进程异常退出，自动额度查询已暂停，可点击刷新重试。',
    'cli_startup_failed':'Codex未能启动，自动额度查询已暂停，可点击刷新重试。',
    'cli_startup_timeout':'Codex启动未响应，自动额度查询已暂停，可点击刷新重试。',
    'cli_startup_blocked':'Codex上次启动失败，自动额度查询保持暂停，可点击刷新重试。',
    'quota_expired':'额度窗口已到期，等待重新查询。',
    'token_partial':'部分日志不可读，保留已知统计。',
    'token_cached':'源日志缺失，当前显示本机历史统计。',
    'token_missing':'未找到可读日志，暂不能确认用量。',
    'token_schema':'日志格式暂不识别，不能确认新的用量。',
    'ipc_disconnected':'实时通道未连接，普通日志状态仍独立工作。',
    'ipc_protocol':'实时协议暂不兼容，普通日志状态仍独立工作。',
    'ipc_waiting':'实时通道已连接，等待会话快照。',
    'ipc_ready':'实时会话快照读取正常。',
    'stale':'暂未收到新的检测结果，保留上次数据。',
    'unavailable':'读取暂不可用，稍后重试。',
}

def sample(state,code='ok',success_at=None):
    result=dict(state=state,code=code)
    if success_at is not None:result['success_at']=success_at
    return result

class CapabilityHealth:
    def __init__(self,home,previous=None,clock=time.time):
        self.clock=clock;self.home_key=hashlib.sha256(str(home).encode()).hexdigest()[:20];self.records={}
        previous=previous if isinstance(previous,dict) else {}
        old=previous.get('capabilities',{}) if previous.get('home_key')==self.home_key else {}
        old=old if isinstance(old,dict) else {}
        for key in CAPABILITIES:
            value=old.get(key,{});last=value.get('last_success') if isinstance(value,dict) else None
            valid=isinstance(last,(float,int)) and not isinstance(last,bool) and math.isfinite(last) and 0<=last<=self.clock()+5
            self.records[key]=dict(state='unknown',code='starting',checked=0,last_success=last if valid else None)
    def record(self,key,value):
        if key not in self.records or not isinstance(value,dict):return
        state=value.get('state','unknown');state=state if state in LABELS else 'unknown'
        code=value.get('code','unavailable');code=code if code in REASONS else 'unavailable'
        now=self.clock();old=self.records[key];stamp=value.get('success_at')
        if stamp is None and state=='available':stamp=now
        if not isinstance(stamp,(int,float)) or isinstance(stamp,bool) or not math.isfinite(stamp) or stamp<0 or stamp>now+5:stamp=None
        self.records[key]=dict(state=state,code=code,checked=now,last_success=max(old['last_success'] or 0,stamp) if stamp is not None else old['last_success'])
    def update(self,values):
        for key,value in values.items():self.record(key,value)
    def snapshot(self):
        result=copy.deepcopy(self.records);now=self.clock()
        for key,value in result.items():
            if value['state']=='available' and now-value['checked']>TTL[key]:value.update(state='degraded',code='stale')
        return dict(home_key=self.home_key,capabilities=result)

def success_time(value,now=None):
    now=time.time() if now is None else now
    if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0 or value>now+5:return '尚无成功记录'
    return time.strftime('%H:%M:%S' if time.localtime(value)[:3]==time.localtime(now)[:3] else '%m/%d %H:%M',time.localtime(value))
