"""Local, read-only Codex activity adapter and desktop motion primitives."""
import json
import math
import os
import re
import time
from dataclasses import dataclass,field
from datetime import datetime
from pathlib import Path
from status_reactions import tool_activity
from session_read_state import session_id,is_subagent_metadata,rollout_alias


def clean_text(text, limit=180):
    if not isinstance(text, str):
        return ''
    text = re.sub(r'<(?:environment_context|in-app-browser-context|external_codex_apps_open_page)[\s\S]*?(?:</[^>]+>|/>)', '', text)
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]+)\b', '[已隐藏凭据]', text)
    text = re.sub(r'```[\s\S]*?```', '[代码片段]', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit] + ('…' if len(text) > limit else '')


def content_text(content):
    if isinstance(content, str):
        return clean_text(content)
    if not isinstance(content, list):
        return ''
    return clean_text(' '.join(c.get('text', '') for c in content if isinstance(c, dict)))


def safe_time(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return time.time()


def operation_kinds(payload):
    """Read tool names only; never turn arbitrary code/content into UI text."""
    name=str(payload.get('name','')).lower()
    names=[name]
    if name in ('functions.exec','exec','multi_tool_use.parallel'):
        args=payload.get('arguments',payload.get('input',''))
        if isinstance(args,str):
            # exec is a wrapper: identify only explicit nested tool invocations.
            names=re.findall(r'\btools\.([A-Za-z0-9_]+)\s*\(',args) or [name]
    kinds=[]
    for tool in names:
        kind='read' if any(v in tool.lower() for v in ('read_file','read_mcp','view_image')) else tool_activity(tool)
        if kind not in kinds:kinds.append(kind)
    return kinds


def operation_label(kinds,finished=False,failed=False):
    labels={'edit':('正在编辑文件','编辑了文件'),'execute':('正在运行命令','运行了命令'),
            'research':('正在查找资料','查找了资料'),'read':('正在读取文件','读取了文件'),
            'create':('正在生成内容','生成了内容'),'tool':('正在使用工具','使用了工具')}
    text=' · '.join(labels.get(kind,labels['tool'])[int(finished)] for kind in kinds)
    return text+(' · 未成功' if failed else '')


def windows_from_limits(limits):
    if not isinstance(limits, dict):
        return []
    # Read both rollout and official app-server spellings.
    if 'rateLimitsByLimitId' in limits:
        limits = (limits.get('rateLimitsByLimitId') or {}).get('codex') or {}
    elif 'rateLimits' in limits:
        limits = limits.get('rateLimits') or {}
    windows = []
    for key in ('primary', 'secondary'):
        item = limits.get(key)
        if not isinstance(item, dict):
            continue
        used = item.get('usedPercent', item.get('used_percent'))
        minutes = item.get('windowDurationMins', item.get('window_minutes'))
        if not isinstance(used, (int, float)) or isinstance(used, bool) or not math.isfinite(used) or not 0 <= used <= 100:
            continue
        if not isinstance(minutes, (int, float)) or minutes <= 0:
            continue
        name = {300: '5小时', 10080: '一周'}.get(minutes, f'{minutes:g}分钟')
        window={'name': name, 'remaining': round(100-used, 1),
                'resetsAt': item.get('resetsAt', item.get('resets_at'))}
        plan=limits.get('planType',limits.get('plan_type'))
        if plan:window['plan']=str(plan).lower()[:40]
        windows.append(window)
    return windows


@dataclass
class Session:
    title: str = 'Codex 对话'
    state: str = 'idle'
    message: str = '等待新的 Codex 消息'
    turn: str = ''
    closed_turn: str = ''
    done: bool = True
    source_subagent: bool = False
    provenance_known: bool = False
    display: str = ''
    calls: dict = field(default_factory=dict)
    compacting: bool = False
    waiting_reason: str = ''
    updated: float = 0


class ActivityReducer:
    def __init__(self):
        self.sessions = {}
        self.last_quota = None

    def _status(self,sid,s,activity='commentary',user_message=False,turn_started=False):
        waiting=s.waiting_reason if not s.done else ''
        label={'input':'等待你的输入','approval':'等待你的批准'}.get(waiting)
        return dict(kind='status',session=sid,state='waiting' if waiting else 'working' if s.compacting else s.state,
                    text=label or ('正在压缩上下文' if s.compacting else s.message),title=s.title,turn=s.turn,
                    activity='waiting' if waiting else 'compact' if s.compacting else activity,display=label or ('正在压缩上下文' if s.compacting else s.display),
                    compacting=s.compacting,waiting_reason=waiting,waiting=sum(bool(x.waiting_reason) and not x.done for x in self.sessions.values()),
                    user_message=user_message,turn_started=turn_started,active=sum(not x.done or x.compacting for x in self.sessions.values()))

    def terminate(self,sid,status,turn):
        s=self.sessions.get(sid)
        if not s or s.source_subagent or s.done or not turn or s.turn!=turn or status not in ('completed','failed','interrupted'):return []
        s.done=True;s.closed_turn=turn;s.compacting=False;s.waiting_reason=''
        s.state='complete' if status=='completed' else 'interrupted'
        s.message=s.display={'completed':'任务已完成','failed':'任务执行失败','interrupted':'任务已中断'}[status]
        events=[]
        if status=='completed':events.append(dict(kind='complete',session=sid,turn=turn,title=s.title,text=s.message))
        return events+[self._status(sid,s)]

    def set_waiting(self,sid,reason,turn=''):
        s=self.sessions.setdefault(sid,Session())
        if s.source_subagent or s.done or reason not in ('','input','approval'):return []
        if turn and s.turn and turn!=s.turn:return []
        if reason==s.waiting_reason:return []
        s.waiting_reason=reason
        return [self._status(sid,s)]

    def set_compacting(self,sid,value,turn=''):
        s=self.sessions.setdefault(sid,Session())
        if s.source_subagent or bool(value)==s.compacting:return []
        if value and s.done and (not turn or turn==s.closed_turn or turn==s.turn):return []
        if turn and s.turn and turn!=s.turn and not s.done:return []
        if turn and (not s.turn or s.done):s.turn=turn;s.closed_turn=''
        s.compacting=bool(value)
        return [self._status(sid,s)]

    def apply(self, sid, obj, historical=False):
        s = self.sessions.setdefault(sid, Session())
        s.updated=time.monotonic()
        kind = obj.get('type')
        p = obj.get('payload') or {}
        if not isinstance(p, dict):
            return []
        stamp = safe_time(obj.get('timestamp'))
        events = []
        if kind == 'session_meta':
            # A child rollout can contain the parent's inherited session_meta.
            # Only its own first header establishes provenance, permanently.
            # In forked rollouts session_id may still be the parent's ID.
            # id identifies the file's actual owner.
            owner=p.get('id') or p.get('session_id')
            if not s.provenance_known and (not owner or session_id(owner)==session_id(sid)):
                s.source_subagent=is_subagent_metadata(p);s.provenance_known=True
        if s.source_subagent:
            return []
        limits = p.get('rate_limits')
        if limits is None and isinstance(p.get('info'), dict):
            limits = p['info'].get('rate_limits')
        windows = windows_from_limits(limits)
        if windows and (not self.last_quota or stamp >= self.last_quota['observed']):
            self.last_quota = {'kind': 'quota', 'windows': windows, 'observed': stamp, 'source': 'session'}
            if not historical:
                events.append(self.last_quota)
        typ = p.get('type')
        if s.closed_turn and s.turn==s.closed_turn:
            new_turn=str(p.get('turn_id') or '') if kind=='event_msg' and typ in ('task_started','turn_started') else ''
            if new_turn and new_turn!=s.closed_turn:s.closed_turn=''
            else:return events
        changed = False
        user_message = False
        if kind=='compacted':
            # A saved compaction record proves completion, never its start.
            if s.compacting:s.compacting=False;changed=True
        elif kind=='event_msg' and typ in ('context_compaction_started','compaction_started'):
            s.compacting=True;changed=True
        elif kind=='event_msg' and typ in ('context_compaction_completed','context_compacted','compaction_completed'):
            if s.compacting:s.compacting=False;changed=True
        elif kind == 'event_msg' and typ in ('task_started', 'turn_started'):
            s.compacting=False;s.waiting_reason=''
            s.turn = str(p.get('turn_id') or stamp)
            s.done = False
            s.state, s.message = 'thinking', '收到任务，正在思考…'
            changed = True
        elif kind == 'event_msg' and typ == 'user_message':
            user_message = True
            s.title = clean_text(p.get('message', ''), 42) or s.title
            s.done = False
            s.state, s.message = 'thinking', '正在处理：' + s.title
            changed = True
        elif kind == 'event_msg' and typ in ('task_complete', 'task_completed'):
            changed=s.compacting
            s.compacting=False;s.waiting_reason=''
            if not s.done:
                s.done = True
                s.state, s.message = 'complete', '任务已完成，可以查看 Codex 回复啦。'
                if not historical:
                    events.append({'kind': 'complete', 'session': sid, 'turn': s.turn, 'title': s.title, 'text': s.message})
                changed = True
        elif kind == 'event_msg' and typ in ('turn_aborted', 'task_aborted', 'turn_cancelled'):
            s.compacting=False;s.waiting_reason=''
            s.done = True
            s.state, s.message = 'interrupted', '任务已暂停或被中断'
            changed = True
        elif kind == 'event_msg' and typ == 'item_completed':
            item = p.get('item') or {}
            it = item.get('type')
            if it == 'UserMessage':
                user_message = True
                s.title = content_text(item.get('content'))[:42] or s.title
                s.state, s.message, s.done = 'thinking', '正在处理：' + s.title, False
                changed = True
            elif it == 'AgentMessage':
                text = content_text(item.get('content'))
                if text:
                    s.state, s.message = ('responding' if item.get('phase') == 'final_answer' else 'working'), text
                    changed = True
            elif it in ('CommandExecution', 'McpToolCall', 'FileChange', 'WebSearch', 'Extension'):
                label = {'CommandExecution': '执行命令', 'McpToolCall': '调用工具', 'FileChange': '修改文件', 'WebSearch': '查找资料', 'Extension': '使用扩展工具'}[it]
                failed = item.get('status') in ('failed', 'error')
                s.state, s.message = 'working', (label + ('暂未成功，继续处理中…' if failed else '已返回，继续处理中…'))
                s.done = False
                changed = True
        elif kind == 'response_item' and typ == 'message' and p.get('role') == 'user':
            user_message = True
            s.title = clean_text(content_text(p.get('content')), 42) or s.title
            s.state, s.message, s.done = 'thinking', '正在处理：' + s.title, False
            changed = True
        elif kind == 'response_item' and typ in ('function_call', 'custom_tool_call'):
            s.state, s.message = 'working', '正在调用工具：' + clean_text(p.get('name', '工具'), 45)
            s.done = False
            changed = True
        elif kind == 'response_item' and typ == 'message' and p.get('role') == 'assistant':
            text = content_text(p.get('content'))
            if text:
                s.state, s.message = 'responding' if p.get('phase') in ('final', 'final_answer') else 'working', text
                changed = True
        elif kind == 'response_item' and typ == 'reasoning' and not s.done:
            # Never read or display hidden model reasoning.
            s.state, s.message = 'thinking', '正在思考下一步…'
            changed = True
        # Short public operation summaries are independent of commentary prose.
        # Preserve a completed operation through commentary until a real next
        # operation/thinking/final lifecycle event replaces it.
        if changed:
            if user_message or typ in ('task_started','turn_started'):
                s.display='正在思考';s.calls.clear()
            elif s.state=='complete':s.display='任务已完成'
            elif s.state=='interrupted':s.display='任务已中断';s.calls.clear()
            elif s.state=='responding':s.display='正在整理回复'
            elif kind=='response_item' and typ in ('function_call','custom_tool_call'):
                kinds=operation_kinds(p);call=str(p.get('call_id',''))
                if call:s.calls[call]=kinds
                while len(s.calls)>64:s.calls.pop(next(iter(s.calls)))
                s.display=operation_label(kinds)
            elif kind=='event_msg' and typ=='item_completed':
                item=p.get('item') or {};it=item.get('type')
                kinds={'CommandExecution':['execute'],'FileChange':['edit'],'WebSearch':['research'],'McpToolCall':operation_kinds(item),'Extension':['tool']}.get(it)
                if kinds:s.display=operation_label(kinds,True,item.get('status') in ('failed','error'))
            elif s.state=='thinking':s.display='正在思考下一步'
            if not s.display:s.display='正在处理任务'
        elif kind=='response_item' and typ in ('function_call_output','custom_tool_call_output'):
            kinds=s.calls.pop(str(p.get('call_id','')),None)
            if kinds and not s.done:
                s.state='working';s.display=operation_label(kinds,True);changed=True
        if changed and not historical:
            activity='commentary'
            if s.state=='thinking':activity='thinking'
            elif s.state=='responding':activity='reply'
            elif s.state not in ('working',):activity=s.state
            elif kind=='response_item' and typ in ('function_call','custom_tool_call'):
                kinds=operation_kinds(p)
                activity=next((v for v in ('edit','read','research','execute') if v in kinds),tool_activity(p.get('name','')))
            elif kind=='event_msg' and typ=='item_completed':
                item=p.get('item') or {};it=item.get('type')
                activity='retry' if item.get('status') in ('failed','error') else {'CommandExecution':'execute','FileChange':'edit','WebSearch':'research','McpToolCall':tool_activity(item.get('name',item.get('tool_name','')))}.get(it,'commentary')
            events.append(self._status(sid,s,activity,user_message,kind=='event_msg' and typ in ('task_started','turn_started')))
        return events


class RolloutTail:
    """Discovery is bounded separately from append reads of all known active tasks."""
    def __init__(self, home=None):
        from log_catalog import LogCatalog
        self.home=__import__('codex_connection').data_home(home);self.reducer=ActivityReducer()
        self.catalog=LogCatalog(self.home);self.files={};self.last_scan=0;self.seeded=False
        self.health=dict(state='unknown',code='starting');self.pins=set();self.generation=None
        self.discovered=set();self.file_ids={};self.queue=[];self.by_id={}
        self.rate_observer=None
    def set_pins(self,ids):self.pins={session_id(s) for s in ids}
    def poll(self):
        from performance_metrics import METRICS
        now=time.monotonic();events=[];errors=0;readable=0
        if self.last_scan==0:self.catalog.last_check=-1e9
        paths=self.catalog.discover();self.last_scan=now;errors+=self.catalog.errors
        if self.generation!=self.catalog.revision:
            self.file_ids={p:rollout_alias(p) for p in paths}
            self.generation=self.catalog.revision;new=paths-self.discovered
            def modified(p):
                try:return p.stat().st_mtime
                except OSError:return 0
            ordered=sorted(new,key=modified,reverse=True)
            self.queue.extend((p,self.seeded) for p in (ordered if self.seeded else ordered[:16]))
            self.discovered=set(paths);self.by_id={session_id(self.file_ids[p]):p for p in sorted(paths,key=lambda p:(self.home/'sessions') in p.parents)}
        active={session_id(sid) for sid,s in self.reducer.sessions.items() if not s.source_subagent and (not s.done or s.compacting)}
        important=active|self.pins
        # DB-active/unread/displayed identities are read even if their log has
        # not changed for hours or moved to the archive directory.
        candidates=[(self.by_id[s],False) for s in important if s in self.by_id]
        candidates+=self.queue[:32];self.queue=self.queue[32:]
        live_new={p for p,is_new in self.queue+candidates if is_new}
        for path,is_new in candidates:
            if path in self.files:continue
            previous=next((p for p in self.files if session_id(self.files[p]['sid'])==session_id(self.file_ids[path]) and p not in paths),None)
            if previous is not None:self.files[path]=self.files.pop(previous);continue
            sid=self.file_ids[path];canonical=session_id(sid)
            is_new=path in live_new and (self.home/'sessions') in path.parents
            if canonical!=sid and canonical in self.reducer.sessions and sid not in self.reducer.sessions:
                self.reducer.sessions[sid]=self.reducer.sessions.pop(canonical)
            try:
                st=path.stat();recognized=False
                with path.open('rb') as header:meta=json.loads(header.readline(4*1024*1024))
                if isinstance(meta,dict) and meta.get('type')=='session_meta':
                    self.reducer.apply(sid,meta,historical=True);recognized=True
            except (ValueError,UnicodeError):recognized=False
            except OSError:errors+=1;continue
            self.files[path]=dict(sid=sid,offset=0 if is_new else max(0,st.st_size-512000),buffer=b'',history=not is_new,
                skip=not is_new and st.st_size>512000,recognized=recognized,touched=now,discovery_cutoff=st.st_ctime if is_new else None)
        for path,state in list(self.files.items()):
            if path not in paths:
                # Keep identity/state for a slow task; rebind its moved log.
                self.files.pop(path,None);continue
            try:
                size=path.stat().st_size
                if size<state['offset']:state.update(offset=0,buffer=b'',history=True,skip=False)
                if size==state['offset']:
                    readable+=1;state['history']=False;continue
                with METRICS.span('activity_read'),path.open('rb') as f:
                    f.seek(state['offset']);raw=f.read(4*1024*1024);state['offset']=f.tell();readable+=1
                METRICS.add('activity_bytes',bytes_read=len(raw));state['touched']=now
            except OSError:errors+=1;continue
            lines=(state['buffer']+raw).split(b'\n');state['buffer']=lines.pop()
            if len(state['buffer'])>4*1024*1024:state['buffer']=b'';state['skip']=True
            if state['skip'] and lines:lines.pop(0);state['skip']=False
            sid=state['sid']
            # A DB seed can use UUID while the log has a rollout-* alias.
            canonical=session_id(sid)
            if canonical!=sid and canonical in self.reducer.sessions and sid not in self.reducer.sessions:
                self.reducer.sessions[sid]=self.reducer.sessions.pop(canonical)
            for line in lines:
                try:obj=json.loads(line)
                except (ValueError,UnicodeError):continue
                if not isinstance(obj,dict):continue
                if obj.get('type') in ('session_meta','event_msg','response_item','turn_context'):state['recognized']=True
                historical=state['history'] or (state.get('discovery_cutoff') is not None and safe_time(obj.get('timestamp'))<state['discovery_cutoff'])
                if self.rate_observer and obj.get('type')=='event_msg' and isinstance(obj.get('payload'),dict):
                    self.rate_observer(sid,obj['payload'],safe_time(obj.get('timestamp')),historical=historical)
                events.extend(self.reducer.apply(sid,obj,historical=historical))
            if state['offset']>=size:state['history']=False;state['discovery_cutoff']=None
        # Keep 32 recently used files plus every active/unread/displayed one.
        active={session_id(sid) for sid,s in self.reducer.sessions.items() if not s.source_subagent and (not s.done or s.compacting)}
        important|=active
        recent=sorted(self.files,key=lambda p:self.files[p]['touched'],reverse=True)[:32]
        self.files={p:v for p,v in self.files.items() if p in recent or session_id(v['sid']) in important}
        protected={p.stem for p in self.files}|important
        disposable=sorted((sid for sid,s in self.reducer.sessions.items() if sid not in protected and session_id(sid) not in important and s.done),key=lambda sid:self.reducer.sessions[sid].updated,reverse=True)
        for sid in disposable[256:]:self.reducer.sessions.pop(sid,None)
        if not self.seeded:
            self.seeded=True
            if self.reducer.last_quota:events.append(self.reducer.last_quota)
            events.append(dict(kind='status',state='idle' if self.files else 'offline',text='已找到本机 Codex 会话，等待新消息' if self.files else '尚未找到本机 Codex 会话，请打开 Codex 并发送消息',title='Codex 状态',active=0))
        recognized=any(v.get('recognized') for v in self.files.values())
        self.health=dict(state='degraded' if errors or readable and not recognized else 'available' if readable else 'unavailable',code='logs_unreadable' if errors else 'logs_schema' if readable and not recognized else 'logs_idle' if readable else 'logs_missing')
        return events



def motion_step(x, y, tx, ty, speed, dt, bounds):
    left, top, right, bottom = bounds
    tx, ty = max(left,min(tx,right)), max(top,min(ty,bottom))
    dx,dy=tx-x,ty-y
    distance=math.hypot(dx,dy)
    step=max(0,speed)*min(max(dt,0),0.1)
    if distance <= step or distance < 0.5:
        return tx,ty,True
    return max(left,min(right,x+dx/distance*step)),max(top,min(bottom,y+dy/distance*step)),False
