"""Public Codex Resets feed. No Codex credentials or conversation data are sent."""
import hashlib
import json
import math
import re
import time
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from enhanced_core import clean_text

API_URL='https://codex-resets.com/api/resets?locale=zh-CN'
SOURCE_URL='https://codex-resets.com/zh-CN'
BEIJING=timezone(timedelta(hours=8))

def epoch(value):
    try:
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            return float(value) if math.isfinite(value) and 0<value<253402271999 else None
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:return None
        return dt.timestamp()
    except (ValueError,TypeError,OverflowError):return None

def local_time(value):
    stamp=epoch(value)
    if stamp is None:return ''
    try:return datetime.fromtimestamp(stamp,BEIJING).strftime('%m/%d %H:%M')
    except (ValueError,OSError,OverflowError):return ''

def account_reset_text(value,now=None):
    stamp=epoch(value)
    if stamp is None:return '下次重置：未提供'
    now=time.time() if now is None else now
    return ('重置时间已到 · 待刷新' if stamp<=now else '下次 '+local_time(stamp))

def normalized_item(item,scheduled=False):
    if not isinstance(item,dict):return None
    stamp=epoch(item.get('announced_at'))
    if stamp is None:return None
    text=item.get('display_text') or item.get('text') or ''
    text=clean_text(re.sub(r'https?://\S+','',text),110)
    raw_id=str(item.get('tweet_id') or '')
    ident=raw_id if re.fullmatch(r'\d{5,30}',raw_id) else hashlib.sha256(f"{stamp}|{item.get('reset_type')}".encode()).hexdigest()[:24]
    result={'id':ident,'announced':stamp,'reset_type':str(item.get('reset_type') or 'unknown')[:24], 'text':text}
    if scheduled:result['scheduled']=epoch(item.get('scheduled_for'))
    return result

def normalize_feed(data):
    if not isinstance(data,dict) or not isinstance(data.get('events'),list) or 'scheduled' not in data:
        raise ValueError('重置消息数据格式已变化')
    events=[]
    for item in data['events'][:200]:
        event=normalized_item(item)
        if event and event['id'] not in {e['id'] for e in events}:events.append(event)
    scheduled=normalized_item(data.get('scheduled'),scheduled=True)
    if data.get('scheduled') is not None and scheduled is None:
        raise ValueError('重置安排数据不完整')
    return {'events':sorted(events,key=lambda e:e['announced'],reverse=True),'scheduled':scheduled}

def schedule_key(item):
    return f"{item['id']}:{item.get('scheduled')}:{item['reset_type']}"

def pending_reset(snapshot):
    """Old cache compatibility; a passed deadline alone never resolves an announcement."""
    return (snapshot or {}).get('pending',(snapshot or {}).get('scheduled'))

def local_refill_applies(event,pending):
    """Only a late, non-natural weekly refill may lower the local display priority.

    This is account evidence, never proof that the public reset caused it.
    In particular a reset card used before the estimate must not consume it.
    """
    if not isinstance(event,dict) or not isinstance(pending,dict):return False
    if pending.get('reset_type')=='banked' or event.get('window')!='一周' or event.get('kind')!='extra':return False
    observed=epoch(event.get('observed'));announced=epoch(pending.get('announced'));scheduled=epoch(pending.get('scheduled'))
    return bool(observed is not None and announced is not None and scheduled is not None and observed>=max(announced,scheduled))

def locally_reset(snapshot):
    pending=pending_reset(snapshot);record=(snapshot or {}).get('local_reset')
    return bool(isinstance(pending,dict) and isinstance(record,dict) and record.get('scope')=='account_only' and
                record.get('schedule')==schedule_key(pending) and local_refill_applies(record,pending))

def reset_has_priority(snapshot):
    return bool(pending_reset(snapshot) and not locally_reset(snapshot))

class LocalResetEvidence:
    """Persist live account observations separately from the public-feed worker."""
    def __init__(self,path):
        self.path=Path(path)
        try:
            self.state=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self.state,dict):raise ValueError()
        except (OSError,ValueError):self.state={}
    def observe(self,windows,observed,source,announcement=None):
        if source!='live' or not isinstance(observed,(int,float)) or not math.isfinite(observed):return
        old=self.state.get('window');window=next((w for w in windows if w.get('name')=='一周'),None)
        if window is None:window=next((w for w in windows if w.get('name')=='5小时'),None)
        if window is None:return
        value=window.get('remaining')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100:return
        stamp=epoch(window.get('resetsAt'))
        if isinstance(old,dict) and observed<=old.get('observed',0):return
        current=dict(name=window['name'],remaining=value,reset=stamp,observed=observed,plan=window.get('plan',''))
        if isinstance(old,dict) and old.get('name')==window['name']:
            increase=value-old.get('remaining',value)
            advanced=stamp and old.get('reset') and stamp>old['reset']+60
            refilled=value>=99 and increase>=10
            pending=pending_reset(announcement)
            announced_refill=(window['name']=='一周' and isinstance(pending,dict) and
                not locally_reset(announcement) and
                isinstance(pending.get('announced'),(int,float)) and
                observed>=pending['announced'] and increase>=10)
            rolled=advanced and old['reset']<=observed+120
            from quota_history import capacity_doubled
            expanded=(window['name']=='一周' and stamp and old.get('reset') and
                abs(stamp-old['reset'])<=60 and
                (not old.get('plan') or old['plan']==current['plan']) and
                capacity_doubled(old.get('remaining',value),value,current['plan']))
            if not expanded and (rolled or increase>1 and (advanced or refilled or announced_refill)):
                self.state['reset']=dict(observed=observed,window=window['name'],remaining=value,
                    kind='natural' if rolled else 'extra')
        self.state['window']=current
        from desktop_core import atomic_json
        try:atomic_json(self.path,self.state)
        except OSError:pass  # Keep valid in-memory evidence if persistence is unavailable.
    def decorate(self,snapshot):
        if snapshot is None:return None
        snapshot=dict(snapshot);pending=pending_reset(snapshot);event=self.state.get('reset')
        if local_refill_applies(event,pending):
            snapshot['local_reset']=dict(event,schedule=schedule_key(pending),scope='account_only')
        else:snapshot.pop('local_reset',None)
        return snapshot

def confirms(event,pending):
    return (event.get('reset_type')==pending.get('reset_type') and
            (event.get('id')==pending.get('id') or event.get('announced',0)>=pending.get('announced',0)))

def schedule_text(snapshot,now=None):
    now=time.time() if now is None else now
    item=pending_reset(snapshot)
    if not snapshot:return '下轮额外重置：正在查询…'
    if not item:return '下轮额外重置：暂未公布'
    title='备用重置' if item.get('reset_type')=='banked' else '额外重置'
    if locally_reset(snapshot):return title+'：本机有额度补充，来源未确认；公告仍待确认'
    stamp=epoch(item.get('scheduled'))
    if stamp is None:return f'{title}已安排 · 时间待公布'
    if stamp<=now:return f'{title}预计 {local_time(stamp)} · 已过，待确认'
    return f'{title}预计最晚 {local_time(stamp)}（北京时间）'

class ResetFetchError(RuntimeError):
    def __init__(self,code,message):super().__init__(message);self.code=code

class ResetCacheError(OSError):
    def __init__(self,snapshot,alerts):
        super().__init__('最新公告已获取，但本地缓存保存失败');self.snapshot=snapshot;self.alerts=alerts

def reset_failure(error,phase='fetch'):
    code=getattr(error,'code',None)
    if isinstance(error,ResetCacheError) or phase=='cache':code='cache_write';message='最新公告已获取，缓存保存失败'
    elif isinstance(error,ResetFetchError):message=str(error)
    elif isinstance(error,FileNotFoundError):code='runtime_file';message='程序联网组件不完整，请更新或修复安装'
    else:code='unexpected';message='公告查询暂时失败'
    record=dict(state='unavailable',code=code,message=message,phase=phase,checked=time.time(),errorType=type(error).__name__)
    if code in ('unexpected','runtime_file'):
        import traceback
        record['origin']=[dict(file=Path(frame.filename).name,function=frame.name,line=frame.lineno) for frame in traceback.extract_tb(error.__traceback__)[-6:]]
        if isinstance(error,OSError):
            record['osError']=error.errno
            if error.filename:record['missingFile']=Path(error.filename).name
    return record

def fetch_feed(opener=None):
    request=urllib.request.Request(API_URL,headers={
        'User-Agent':'BailongDesktopPet/'+__import__('version').VERSION+' (+https://codex-resets.com)',
        'Accept':'application/json', 'Cache-Control':'no-cache'})
    # urllib's global opener retains the proxy configuration from its first
    # request. A long-running companion must follow subsequent Windows changes.
    opener=opener or urllib.request.build_opener().open;started=time.monotonic()
    for attempt in range(2):
        remaining=10-(time.monotonic()-started)
        if remaining<=0:raise ResetFetchError('timeout','公告连接超时，保留上次记录')
        try:
            with opener(request,timeout=min(8,remaining)) as response:
                raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise ResetFetchError('response_size','公告响应过大，保留上次记录')
            try:return normalize_feed(json.loads(raw.decode('utf-8-sig')))
            except (ValueError,UnicodeError) as error:raise ResetFetchError('schema','公告格式变化，保留上次记录') from error
        except urllib.error.HTTPError as error:
            code='http_'+str(error.code);message=f'公告服务 HTTP {error.code}，稍后重试'
            retry=error.code in (408,429,500,502,503,504)
        except (urllib.error.URLError,TimeoutError,ssl.SSLError,OSError) as error:
            reason=getattr(error,'reason',error)
            if isinstance(reason,ssl.SSLCertVerificationError):code='certificate';message='公告证书验证失败，请检查系统时间或网络代理';retry=False
            elif isinstance(reason,(TimeoutError,)) or 'timed out' in str(reason).lower():code='timeout';message='公告连接超时，保留上次记录';retry=True
            else:code='network';message='公告网络连接失败，保留上次记录';retry=True
        if not retry or attempt==1:raise ResetFetchError(code,message)
        time.sleep(.1)

class ResetTracker:
    def __init__(self,path):
        self.path=Path(path)
        try:
            state=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(state,dict) or not isinstance(state.get('seen'),list):raise ValueError()
            self.state=state
        except (OSError,ValueError):self.state={'initialized':False,'seen':[],'schedules':[]}

    @property
    def snapshot(self):return self.state.get('snapshot')

    def update(self,feed,now=None):
        now=time.time() if now is None else now
        seen=set(self.state.get('seen',[]))
        schedules=set(self.state.get('schedules',[]))
        alerts=[]
        # First fetch establishes a baseline; never alert for historical resets.
        if self.state.get('initialized'):
            new=[e for e in feed['events'] if e['id'] not in seen]
            if new:
                e=new[0]
                label='备用重置额度消息' if e['reset_type']=='banked' else '额度重置消息'
                alerts.append({'kind':'confirmed','title':'Codex '+label,
                               'text':f"站点收录 {local_time(e['announced'])}：{e['text'] or '有新的重置公告，请查看来源。'}"})
        # Preserve the most recent IDs rather than arbitrary set ordering.
        ordered=list(dict.fromkeys([e['id'] for e in feed['events']]+self.state.get('seen',[])))[:256]
        schedule_ids=list(dict.fromkeys(([schedule_key(feed['scheduled'])] if feed.get('scheduled') else [])+self.state.get('schedules',[])))[:128]
        # Missing schedule data is not proof of fulfilment. Retain an announcement
        # across polls/restarts until a matching confirmed event supersedes it.
        pending=pending_reset(self.snapshot)
        resolved=list(self.state.get('resolved',[]))
        candidate=feed.get('scheduled')
        if candidate and candidate['id'] not in resolved:
            if pending is None or candidate.get('announced',0)>=pending.get('announced',0):pending=candidate
        confirmation=next((e for e in feed['events'] if pending and confirms(e,pending)),None)
        if confirmation:
            resolved=list(dict.fromkeys([pending['id']]+resolved))[:128]
            pending=None
        snapshot={'scheduled':pending,'pending':pending,'latest':feed['events'][0] if feed['events'] else None,'checked':now}
        if self.state.get('initialized') and pending and schedule_key(pending) not in schedules:
            alerts.append({'kind':'scheduled','title':'Codex 有新的重置安排','text':schedule_text(snapshot,now)})
        state={'initialized':True,'seen':ordered,'schedules':schedule_ids,'resolved':resolved,'snapshot':snapshot}
        from desktop_core import atomic_json
        try:atomic_json(self.path,state)
        except OSError:
            self.state=state
            raise ResetCacheError(snapshot,alerts) from None
        self.state=state
        return snapshot,alerts
