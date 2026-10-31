"""Shared canonical identities, priorities and fair per-channel service."""
import time
from session_read_state import session_id

class ActivityTargets:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.entries={};self.served={};self.lease=();self.lease_until=0
    def sync(self,sessions,pending=(),displayed=(),visited=()):
        now=self.clock();active=set();children=set()
        for alias,state in sessions.items():
            sid=session_id(alias)
            if state.source_subagent:children.add(sid);continue
            item=self.entries.setdefault(sid,dict(alias=alias,active=False,unread=False,shown=False,touched=now))
            item['alias']=alias
            if not state.done or state.compacting:active.add(sid)
        unread={session_id(k[0]) for k in pending if isinstance(k,(list,tuple)) and len(k)==2}
        shown={session_id(s) for s in displayed};seen={session_id(s) for s in visited}
        for sid in unread|shown|seen:
            self.entries.setdefault(sid,dict(alias=sid,active=False,unread=False,shown=False,touched=now))
        for sid in children:self.entries.pop(sid,None)
        for sid,item in self.entries.items():
            item.update(active=sid in active,unread=sid in unread,shown=sid in shown)
            if sid in seen:item['touched']=now
        disposable=sorted((s for s,v in self.entries.items() if not (v['active'] or v['unread'] or v['shown'])),key=lambda s:self.entries[s]['touched'],reverse=True)
        for sid in disposable[256:]:self.entries.pop(sid,None)
        for channel,history in self.served.items():self.served[channel]={s:t for s,t in history.items() if s in self.entries}
    def choose(self,channel,limit,candidates=None):
        history=self.served.setdefault(channel,{})
        # Least recently served is the first key: priority breaks ties, so a
        # fifth task and old unread items cannot permanently starve.
        def rank(sid):
            v=self.entries[sid];priority=0 if v['active'] else 1 if v['unread'] else 2 if v['shown'] else 3
            return history.get(sid,-1e9),priority,-v['touched'],sid
        chosen=sorted(self.entries if candidates is None else candidates,key=rank)[:limit];stamp=self.clock()
        for sid in chosen:history[sid]=stamp
        return chosen
    def ipc_targets(self,limit=4,lease_seconds=8):
        now=self.clock();important={s for s,v in self.entries.items() if v['active'] or v['unread'] or v['shown']}
        pool=important or set(self.entries)
        allowed=pool if len(pool)>=limit else set(self.entries)
        if now<self.lease_until and set(self.lease)<=allowed and (len(important)>limit or important<=set(self.lease)):return self.lease
        # IPC rotates the important pool; idle history fills spare slots only.
        history=self.served.setdefault('ipc',{});all_entries=self.entries
        active={s for s in pool if all_entries[s]['active']};other=pool-active
        if active and other and limit>1:
            chosen=self.choose('ipc',min(len(active),limit-1),active)
            chosen+=self.choose('ipc',limit-len(chosen),other)
        else:chosen=self.choose('ipc',limit,pool)
        if len(chosen)<limit:
            extra=sorted((s for s in all_entries if s not in chosen),key=lambda s:history.get(s,-1e9))[:limit-len(chosen)]
            chosen+=extra
            for sid in extra:history[sid]=now
        self.lease=tuple(chosen);self.lease_until=now+lease_seconds;return self.lease
    def alias(self,sid):return self.entries.get(session_id(sid),{}).get('alias',sid)
    def pinned(self):return {sid for sid,v in self.entries.items() if v['active'] or v['unread'] or v['shown']}
