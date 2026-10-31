"""Recent local output-counter changes. Never reuse completed-turn averages."""
import math,time
from collections import deque

class LiveOutputRate:
    def __init__(self):self.sessions={}
    def ingest(self,sid,payload,stamp,*,historical=False,now=None):
        now=time.monotonic() if now is None else now
        if sid not in self.sessions and len(self.sessions)>=128:self.sessions.pop(next(iter(self.sessions)))
        s=self.sessions.setdefault(sid,dict(water=None,last_stamp=None,active=False,points=deque(maxlen=32),seen=0.,rate=None,ttl=12.,interval=None,sampled_at=None))
        kind=payload.get('type')
        if kind in ('task_started','turn_started'):
            s.update(active=not historical,rate=None,seen=now,points=deque(maxlen=32))
            if s['water'] is not None and not historical:s['points'].append((stamp,s['water']))
        elif kind in ('task_complete','task_completed','task_aborted','turn_aborted','turn_completed','turn_cancelled'):
            s.update(active=False,rate=None);s['points'].clear()
        elif kind=='token_count':
            info=payload.get('info');usage=info.get('total_token_usage') if isinstance(info,dict) else None
            out=usage.get('output_tokens') if isinstance(usage,dict) else None
            if type(out) is not int or not 0<=out<2**53:return
            previous=s['water'];previous_stamp=s['last_stamp'];s['water']=out;s['last_stamp']=stamp
            if historical:return
            if not isinstance(stamp,(int,float)) or not math.isfinite(stamp):return
            # Old backlog timestamps must not masquerade as output arriving now.
            if time.time()-stamp>15 or stamp-time.time()>5:return
            if previous is not None and out<previous:s['points'].clear();s['rate']=None
            if not s['active']:
                # A fresh increase can attach to a task that predates our 512KB tail/bootstrap.
                if previous is None or out<=previous or previous_stamp is None or not 0<stamp-previous_stamp<=300:return
                s['active']=True;s['points'].append((previous_stamp,previous))
            points=s['points']
            if points and stamp<=points[-1][0]:return
            points.append((stamp,out))
            while len(points)>2 and points[1][0]<stamp-10:points.popleft()
            if len(points)>=2:
                elapsed=stamp-points[0][0];delta=out-points[0][1]
                s['rate']=delta/elapsed if .1<=elapsed<=300 and delta>=0 else None;s['seen']=now
                s['interval']=elapsed;s['sampled_at']=stamp;s['ttl']=max(12.,min(180.,elapsed*2.5))
    def snapshot(self,now=None):
        now=time.monotonic() if now is None else now
        valid={sid:s for sid,s in self.sessions.items() if s['active'] and s['rate'] is not None and 0<=now-s['seen']<s['ttl']}
        details=[dict(session=sid,rate=s['rate'] if sid in valid else None,expires=s['seen']+s['ttl'] if sid in valid else None,sampled_at=s['sampled_at'],interval=s['interval'],waiting=now-s['seen']>12) for sid,s in self.sessions.items() if s['active']]
        return dict(rate=sum(s['rate'] for s in valid.values()) if valid else None,sessions=len(valid),details=details,metric='observed_output',expires=min((s['seen']+s['ttl'] for s in valid.values()),default=None))

def display(value):
    if value is None or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:return '—'
    return f'{value/1000:.1f}k' if value>=10000 else f'{value:,.1f}'
