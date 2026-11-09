"""Fast, bounded overlays over an authoritative local-day usage snapshot.

The snapshot's usage rowid ceiling makes reconciliation independent of worker
timing: rows indexed later cannot prematurely subtract a visible live delta.
"""
import hashlib,json,math,sqlite3,threading,time
from pathlib import Path
from datetime import datetime,timedelta
from collections import OrderedDict
from contextlib import closing

class LiveTodayTotal:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock();self.water=OrderedDict();self.events=OrderedDict();self.base=None
        self.generation=time.monotonic_ns();self.revision=0;self._membership=None;self._confirmed=set();self._day=None
    def ingest(self,path,obj,historical=False):
        if not isinstance(obj,dict):return
        payload=obj.get('payload') or {}
        if not isinstance(payload,dict):return
        if payload.get('type')!='token_count':return
        info=payload.get('info') or {}
        if not isinstance(info,dict):return
        usage=info.get('total_token_usage') or {}
        if not isinstance(usage,dict):return
        valid=lambda n:type(n) is int and 0<=n<2**62
        total=usage.get('total_tokens');a=usage.get('input_tokens');b=usage.get('output_tokens')
        if not valid(total):
            if not valid(a) or not valid(b):return
            total=a+b
        try:stamp=datetime.fromisoformat(obj['timestamp'].replace('Z','+00:00')).timestamp()
        except (KeyError,ValueError,TypeError,AttributeError):return
        if not math.isfinite(stamp) or stamp>time.time()+5:return
        with self.lock:
            path=str(path);previous=self.water.get(path);self.water[path]=max(previous or 0,total);self.water.move_to_end(path)
            while len(self.water)>256:self.water.popitem(last=False)
            if historical or previous is None or total<=previous:return
            identity=json.dumps([obj['timestamp'],total,a,b],separators=(',',':'));key=hashlib.sha256(identity.encode()).hexdigest()
            self.events.setdefault(key,(stamp,total-previous))
            while len(self.events)>2048:self.events.popitem(last=False)
            self.revision+=1
    def reconcile(self,snapshot):
        if snapshot.get('unavailable') or not isinstance(snapshot.get('days'),dict) or type(snapshot.get('_usage_rowid')) is not int:return
        with self.lock:
            self.base=dict(days=dict(snapshot['days']),month=snapshot.get('month'),rowid=snapshot['_usage_rowid'],checked=snapshot.get('checked',0),partial=bool(snapshot.get('partial')))
            self.revision+=1;self._membership=None
    def snapshot(self,now=None):
        now=time.time() if now is None else now;today=datetime.fromtimestamp(now).strftime('%Y-%m-%d')
        with self.lock:
            if self._day!=today:
                self._day=today;self.revision+=1
                start=datetime.fromtimestamp(now).replace(hour=0,minute=0,second=0,microsecond=0)
                self._day_start=start.timestamp();self._day_end=(start+timedelta(days=1)).timestamp()
            base=self.base
            if not base or base['month']!=today[:7]:return None
            count=base['days'].get(today,0)
            if type(count) is not int or count<0:return None
            for key,(stamp,delta) in list(self.events.items()):
                if stamp<self._day_start:self.events.pop(key)
            keys=tuple(k for k,(stamp,delta) in self.events.items() if self._day_start<=stamp<self._day_end and stamp<=now)
            signature=(base['rowid'],base['checked'],keys)
            if keys and signature!=self._membership:
                try:
                    with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.03)) as db:
                        confirmed=set()
                        for start in range(0,len(keys),128):
                            chunk=keys[start:start+128]
                            confirmed.update(r[0] for r in db.execute('SELECT fingerprint FROM usage WHERE rowid<=? AND stamp<=? AND fingerprint IN ('+','.join('?' for _ in chunk)+')',(base['rowid'],base['checked'],*chunk)))
                    self._membership=signature;self._confirmed=confirmed
                except (OSError,sqlite3.Error,ValueError):return None
            overlay=sum(self.events[k][1] for k in keys if k not in self._confirmed)
            return dict(day=today,count=count+overlay,partial=base['partial'],generation=self.generation,revision=self.revision)
