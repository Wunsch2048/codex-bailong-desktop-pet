"""Opt-in aggregate timings. Never collect paths, prompts or account values."""
import os,time,threading
from contextlib import contextmanager

class Metrics:
    def __init__(self,enabled=None):
        self.enabled=os.environ.get('BAILONG_PROFILE')=='1' if enabled is None else enabled
        self.values={};self.lock=threading.Lock()
    def add(self,key,milliseconds=0,count=1,bytes_read=0):
        if not self.enabled:return
        with self.lock:
            v=self.values.setdefault(key,dict(calls=0,totalMs=0,maxMs=0,bytes=0))
            v['calls']+=count;v['totalMs']+=milliseconds;v['maxMs']=max(v['maxMs'],milliseconds);v['bytes']+=bytes_read
    @contextmanager
    def span(self,key):
        if not self.enabled:yield;return
        start=time.perf_counter()
        try:yield
        finally:self.add(key,(time.perf_counter()-start)*1000)
    def snapshot(self):
        with self.lock:return {k:{n:round(x,3) if isinstance(x,float) else x for n,x in v.items()} for k,v in self.values.items()}

METRICS=Metrics()


def measured(key):
    from functools import wraps
    def decorate(fn):
        @wraps(fn)
        def invoke(*args,**kwargs):
            with METRICS.span(key):return fn(*args,**kwargs)
        return invoke
    return decorate
