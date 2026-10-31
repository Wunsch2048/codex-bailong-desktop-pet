"""Directory-change polling plus a periodic full scan repairs missed changes."""
import os,time
from pathlib import Path
from performance_metrics import METRICS

class LogCatalog:
    def __init__(self,home,roots=('sessions','archived_sessions'),interval=5,full_interval=60):
        self.home=Path(home);self.roots=roots;self.interval=interval;self.full_interval=full_interval
        self.paths=set();self.directories={};self.last_check=-1e9;self.last_full=-1e9;self.errors=0;self.revision=0
    @staticmethod
    def signature(path):
        try:
            s=path.stat();return (s.st_mtime_ns,s.st_ctime_ns)
        except OSError:return None
    def discover(self,now=None,force=False,check=False):
        now=time.monotonic() if now is None else now
        if not force and not check and now-self.last_check<self.interval:return self.paths
        self.last_check=now
        dirs=self.directories or {self.home/name:None for name in self.roots}
        changed=force or now-self.last_full>=self.full_interval
        with METRICS.span('log_directory_check'):
            if not changed:changed=any(self.signature(p)!=s for p,s in dirs.items())
        if not changed:return self.paths
        paths=set();directories={};errors=0
        with METRICS.span('log_full_discovery'):
            for name in self.roots:
                root=self.home/name;directories[root]=self.signature(root)
                if not root.exists():continue
                def failed(error):
                    nonlocal errors
                    errors+=1
                for folder,children,files in os.walk(root,onerror=failed,followlinks=False):
                    p=Path(folder);directories[p]=self.signature(p)
                    children[:]=[c for c in children if not (p/c).is_symlink()]
                    paths.update(p/f for f in files if f.startswith('rollout-') and f.endswith('.jsonl'))
        # A failed partial walk never discards previously known paths.
        self.paths=paths|self.paths if errors else paths;self.directories=directories;self.errors=errors;self.last_full=now;self.revision+=1
        return self.paths
