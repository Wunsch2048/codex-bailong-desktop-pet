"""Read-only local IPC follower. Retain lifecycle metadata, never message text.

Codex desktop stream protocol 11 uses four-byte little-endian JSON frames.
Typed decoding skips unknown fields in C, including reasoning and tool output.
Only initialize/follow/unfollow and negative discovery responses are sent.
"""
import ctypes,json,os,struct,threading,time
from uuid import UUID
import msgspec

NULL=msgspec.Raw(b'null')

class Item(msgspec.Struct):
    type:str=''
    id:str=''
    completed:bool|None=None

class Turn(msgspec.Struct):
    turnId:str|None=None
    status:str=''
    items:list[Item]=[]

class Entry(msgspec.Struct):
    value:str=''

class Island(msgspec.Struct):
    entries:list[Entry]=[]

class History(msgspec.Struct):
    entitiesByKey:dict[str,Turn]={}
    islands:list[Island]=[]

class TurnHistory(msgspec.Struct):
    kind:str=''
    history:History|None=None

class RuntimeStatus(msgspec.Struct):
    type:str=''
    activeFlags:list[str]=[]

class State(msgspec.Struct):
    turns:list[Turn]=[]
    turnHistory:TurnHistory|None=None
    threadRuntimeStatus:RuntimeStatus|None=None

class Patch(msgspec.Struct):
    op:str=''
    path:list[str|int]=[]
    value:msgspec.Raw=NULL

class Change(msgspec.Struct):
    type:str=''
    baseRevision:int=-1
    revision:int=-1
    conversationState:State|None=None
    patches:list[Patch]=[]

class Params(msgspec.Struct):
    conversationId:str=''
    hostId:str=''
    change:Change|None=None

class Result(msgspec.Struct):
    clientId:str=''

class Envelope(msgspec.Struct):
    type:str=''
    method:str=''
    requestId:str=''
    version:int=0
    params:Params|None=None
    result:Result|None=None

DECODER=msgspec.json.Decoder(Envelope)

def valid_id(value):
    try:return str(UUID(value))
    except (ValueError,TypeError,AttributeError):return None

def patch_type(path):
    if not path:return State
    if path==['threadRuntimeStatus']:return RuntimeStatus|None
    if path[:1]==['threadRuntimeStatus']:
        if path[1:]==['type']:return str
        if path[1:]==['activeFlags']:return list[str]
        if len(path)==3 and path[1]=='activeFlags' and isinstance(path[2],int):return str
        return None
    if path[:1]==['turnHistory']:
        rest=path[1:]
        if not rest:return TurnHistory|None
        if rest==['kind']:return str
        if rest==['history']:return History|None
        if rest[:2]==['history','islands']:
            if len(rest)==2:return list[Island]
            if len(rest)==3:return Island
            if rest[-1]=='entries':return list[Entry]
            if len(rest)>=5 and rest[-2]=='entries':return Entry
            if rest[-1]=='value':return str
            return None
        if rest==['history','entitiesByKey']:return dict[str,Turn]
        if rest[:2]!=['history','entitiesByKey'] or len(rest)<3:return None
        rest=rest[3:]
    elif path[:1]==['turns']:
        if len(path)==1:return list[Turn]
        rest=path[2:]
    else:return None
    if not rest:return Turn
    if rest in (['status'],['turnId']):return str|None
    if rest==['items']:return list[Item]
    if rest[:1]==['items']:
        if len(rest)==2:return Item
        if len(rest)==3 and rest[-1] in ('type','id'):return str
        if len(rest)==3 and rest[-1]=='completed':return bool|None
    return None

def apply_patch(state,patch):
    path=patch.path;kind=patch_type(path)
    if kind is None or patch.op not in ('add','replace','remove'):return state
    value=None if patch.op=='remove' else msgspec.to_builtins(msgspec.json.decode(patch.value,type=kind))
    if not path:return value if isinstance(value,dict) else {}
    target=state
    for key in path[:-1]:
        try:target=target[key]
        except (KeyError,IndexError,TypeError):return state
    key=path[-1]
    if isinstance(target,dict):
        if patch.op=='remove':target.pop(key,None)
        else:target[key]=value
    elif isinstance(target,list) and isinstance(key,int) and 0<=key<=len(target):
        if patch.op=='add':target.insert(key,value)
        elif key<len(target):
            if patch.op=='remove':target.pop(key)
            else:target[key]=value
    return state

def latest_turn(state):
    turns=list(state.get('turns') or []);canonical=state.get('turnHistory') or {}
    if canonical.get('kind')=='canonical':
        history=canonical.get('history') or {};entities=history.get('entitiesByKey') or {}
        ordered=[entities[e['value']] for island in history.get('islands',[]) for e in island.get('entries',[]) if e.get('value') in entities]
        turns=ordered+turns
    return next((t for t in reversed(turns) if t.get('turnId') or t.get('status') not in ('completed','failed')),None)

def compaction_state(state):
    turn=latest_turn(state)
    runtime=state.get('threadRuntimeStatus') or {}
    flagged=any(flag.lower() in ('compacting','compaction','contextcompaction') for flag in runtime.get('activeFlags',[]))
    compact=bool(turn and turn.get('status')=='inProgress' and any(i.get('type')=='contextCompaction' and i.get('completed') is False for i in turn.get('items',[])))
    return flagged or compact,(turn or {}).get('turnId') or ''

def waiting_state(state):
    """Only explicit desktop runtime flags prove that the user must act."""
    turn=latest_turn(state) or {};runtime=state.get('threadRuntimeStatus') or {}
    reason=''
    if runtime.get('type')=='active' and turn.get('status') not in ('completed','failed','interrupted'):
        flags=runtime.get('activeFlags') or []
        if 'waitingOnUserInput' in flags:reason='input'
        elif 'waitingOnApproval' in flags:reason='approval'
    return reason,turn.get('turnId') or ''

class LifecycleProjection:
    def __init__(self,emit,emit_waiting=None,emit_activity=None,emit_terminal=None):
        self.emit=emit;self.emit_waiting=emit_waiting;self.states={};self.revisions={};self.phases={};self.waiting={}
        self.emit_activity=emit_activity;self.activity_sent={};self.next_heartbeat=0
        self.emit_terminal=emit_terminal
    def heartbeat(self,now,force=None):
        if self.emit_activity is None and self.emit_terminal is None:return
        if force is None:
            if now<self.next_heartbeat:return
        for sid,state in self.states.items():
            if force is not None and sid!=force:continue
            turn=latest_turn(state) or {};runtime=state.get('threadRuntimeStatus') or {}
            if self.emit_terminal and turn.get('turnId') and turn.get('status') in ('completed','failed','interrupted'):
                self.emit_terminal(sid,turn['status'],turn['turnId'])
            # Missing runtime fields / disconnect are unknown, not idle.
            terminal=turn.get('status') in ('completed','failed','interrupted')
            if not turn.get('turnId') or not terminal and (turn.get('status')!='inProgress' or runtime.get('type') not in ('active','idle')):continue
            value=(turn['turnId'],not terminal and turn.get('status')=='inProgress' and runtime.get('type')=='active')
            previous=self.activity_sent.get(sid)
            if previous and previous[:2]==value and now-previous[2]<15:continue
            self.activity_sent[sid]=(*value,now)
            if self.emit_activity:self.emit_activity(sid,value[1],value[0])
        self.next_heartbeat=min((v[2]+15 for v in self.activity_sent.values()),default=now+15)
    def forget(self,sid,clear=True):
        phase=self.phases.pop(sid,None) if clear else self.phases.get(sid)
        if clear and phase and phase[0]:self.emit(sid,False,phase[1])
        waiting=self.waiting.pop(sid,None) if clear else self.waiting.get(sid)
        if clear and waiting and waiting[0] and self.emit_waiting:self.emit_waiting(sid,'',waiting[1])
        self.states.pop(sid,None);self.revisions.pop(sid,None)
        self.activity_sent.pop(sid,None)
    def accept(self,envelope,wanted):
        p=envelope.params
        if envelope.type!='broadcast' or envelope.method!='thread-stream-state-changed' or envelope.version!=11 or not p or p.hostId!='local' or p.conversationId not in wanted or not p.change:return
        sid=p.conversationId;c=p.change
        if c.type=='snapshot' and c.conversationState is not None:
            self.states[sid]=msgspec.to_builtins(c.conversationState)
        elif c.type=='patches':
            if sid not in self.states or c.baseRevision!=self.revisions.get(sid):return 'resync'
            state=self.states[sid]
            for patch in c.patches:state=apply_patch(state,patch)
            self.states[sid]=state
        else:return
        self.revisions[sid]=c.revision;phase=compaction_state(self.states[sid]);previous=self.phases.get(sid)
        self.phases[sid]=phase
        if phase!=previous and (phase[0] or previous and previous[0]):self.emit(sid,*phase)
        waiting=waiting_state(self.states[sid]);previous=self.waiting.get(sid)
        self.waiting[sid]=waiting
        if self.emit_waiting and waiting!=previous and (waiting[0] or previous and previous[0]):self.emit_waiting(sid,*waiting)
        self.heartbeat(time.monotonic(),force=sid)
        return 'accepted'

class Frames:
    MAX_BYTES=128*1024*1024
    def __init__(self):self.buffer=bytearray()
    def feed(self,data):
        self.buffer.extend(data);offset=0
        while len(self.buffer)-offset>=4:
            size=struct.unpack_from('<I',self.buffer,offset)[0]
            if size<=0 or size>self.MAX_BYTES:raise ValueError('Unsupported IPC frame size')
            if len(self.buffer)-offset<4+size:break
            raw=bytes(memoryview(self.buffer)[offset+4:offset+4+size]);offset+=4+size
            yield raw
        if offset:del self.buffer[:offset]

class LiveStatusReader(threading.Thread):
    def __init__(self,stop,emit,emit_waiting=None,emit_activity=None,emit_terminal=None):
        super().__init__(name='BailongCodexLifecycle',daemon=True);self.stop_event=stop;self.emit=emit;self.emit_waiting=emit_waiting
        self.emit_activity=emit_activity;self.emit_terminal=emit_terminal
        self._targets=();self.lock=threading.Lock();self.connected=False
        self._health=dict(state='unknown',code='starting')
    def set_health(self,state,code,success_at=None):
        with self.lock:
            previous=self._health.get('success_at');self._health=dict(state=state,code=code)
            if success_at is not None or previous is not None:self._health['success_at']=success_at if success_at is not None else previous
    def health_snapshot(self):
        with self.lock:return dict(self._health)
    def set_targets(self,ids):
        targets=tuple(dict.fromkeys(s for value in ids if (s:=valid_id(value))))[:4]
        with self.lock:self._targets=targets
    def targets(self):
        with self.lock:return self._targets
    def run(self):
        if os.name!='nt':self.set_health('unavailable','ipc_disconnected');return
        from ctypes import wintypes
        import msvcrt
        peek=ctypes.WinDLL('kernel32',use_last_error=True).PeekNamedPipe
        peek.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p];peek.restype=wintypes.BOOL
        while not self.stop_event.is_set():
            try:
                with open(r'\\.\pipe\codex-ipc','r+b',buffering=0) as pipe:
                    def available():
                        count=wintypes.DWORD()
                        if not peek(msvcrt.get_osfhandle(pipe.fileno()),None,0,None,ctypes.byref(count),None):raise OSError('IPC disconnected')
                        return count.value
                    self._listen(pipe,available)
            except (OSError,ValueError,msgspec.MsgspecError):self.set_health('degraded','ipc_disconnected')
            finally:self.connected=False
            self.stop_event.wait(5)
    def _listen(self,pipe,available):
        client='';followed=set();frames=Frames();projection=LifecycleProjection(self.emit,self.emit_waiting,self.emit_activity,self.emit_terminal);resync_at={}
        def send(message):
            raw=msgspec.json.encode(message);packet=struct.pack('<I',len(raw))+raw
            while packet:
                n=pipe.write(packet)
                if not n:raise OSError('IPC write closed')
                packet=packet[n:]
        def follow(sid,on):send(dict(type='broadcast',method='thread-stream-following-changed',sourceClientId=client,version=1,params=dict(conversationId=sid,hostId='local',following=on)))
        send(dict(type='request',requestId='bailong-initialize',method='initialize',params=dict(clientType='bailong-desktop-pet'),version=1))
        deadline=time.monotonic()+5
        try:
            while not self.stop_event.is_set():
                if not client and time.monotonic()>deadline:raise OSError('IPC initialize timed out')
                if client:
                    wanted=set(self.targets())
                    for sid in followed-wanted:follow(sid,False);projection.forget(sid,clear=False)
                    for sid in wanted-followed:follow(sid,True)
                    followed=wanted
                    projection.heartbeat(time.monotonic())
                count=available()
                if not count:self.stop_event.wait(.05);continue
                for raw in frames.feed(pipe.read(min(count,1024*1024))):
                    envelope=DECODER.decode(raw)
                    if envelope.type=='response' and envelope.method=='initialize' and envelope.result:
                        client=envelope.result.clientId;self.connected=bool(client)
                        self.set_health('degraded','ipc_waiting')
                    elif envelope.type=='client-discovery-request':
                        send(dict(type='client-discovery-response',requestId=envelope.requestId,response=dict(canHandle=False)))
                    elif envelope.type=='request':
                        send(dict(type='response',requestId=envelope.requestId,resultType='error',error='no-handler-for-request'))
                    else:
                        result=projection.accept(envelope,followed)
                        if result=='accepted':self.set_health('available','ipc_ready',time.time())
                        elif envelope.method=='thread-stream-state-changed' and envelope.version!=11 and envelope.params and envelope.params.conversationId in followed:
                            self.set_health('degraded','ipc_protocol')
                        if result=='resync' and envelope.params:
                            sid=envelope.params.conversationId;now=time.monotonic()
                            projection.forget(sid,clear=False)
                            if now-resync_at.get(sid,-1e9)>=10:
                                resync_at[sid]=now;follow(sid,False);follow(sid,True)
                    # A long conversation's initial frame can be large. Do not
                    # retain its backing bytes while an idle pipe waits.
                    del envelope,raw
        finally:
            for sid in followed:
                try:follow(sid,False)
                except OSError:pass
            for sid in set(projection.phases)|set(projection.waiting)|followed:
                projection.forget(sid)
