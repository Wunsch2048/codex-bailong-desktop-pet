"""App-owned finite detail requests; navigation does not discard completed work."""
from collections import OrderedDict
from PySide6.QtCore import QObject,Signal
from PySide6.QtWidgets import QApplication

class TurnDetails(QObject):
    changed=Signal(object,object)
    def __init__(self,parent=None):super().__init__(parent);self.entries=OrderedDict();self.jobs={};self.pending=OrderedDict()
    def lookup(self,key):
        base=key[:4]
        found=next((k for k in reversed(self.entries) if k[:4]==base),None)
        if found is None:return None,False
        self.entries.move_to_end(found);return self.entries[found],found==key
    def request(self,key,factory):
        base=key[:4]
        running=self.jobs.get(base)
        if running and running[0]==key:return running[1]
        if running or len(self.jobs)>=2:
            self.pending[base]=(key,factory);self.pending.move_to_end(base)
            while len(self.pending)>8:
                _,(old,_)=self.pending.popitem(last=False);self.changed.emit(old,dict(error='读取任务较多，请再次点入重试'))
            return running[1] if running else None
        self.pending.pop(base,None)
        job=factory();self.jobs[base]=(key,job)
        job.ready.connect(lambda rows:self.finish(key,rows));job.failed.connect(lambda text:self.failed(key,text));job.finished.connect(job.deleteLater);job.start();return job
    def finish(self,key,rows):
        turns=next((s['turns'] for s in rows if s['id']==key[1]),[])
        for old in list(self.entries):
            if old[:4]==key[:4]:del self.entries[old]
        self.entries[key]=turns
        while len(self.entries)>8:self.entries.popitem(last=False)
        self.jobs.pop(key[:4],None);self.changed.emit(key,dict(turns=turns));self.pump()
    def failed(self,key,text):
        self.jobs.pop(key[:4],None);self.changed.emit(key,dict(error=text));self.pump()
    def pump(self):
        while self.pending and len(self.jobs)<2:
            base=next((base for base in self.pending if base not in self.jobs),None)
            if base is None:return
            key,factory=self.pending.pop(base);self.request(key,factory)

def shared():
    app=QApplication.instance()
    if not hasattr(app,'_turn_details'):app._turn_details=TurnDetails(app)
    return app._turn_details
