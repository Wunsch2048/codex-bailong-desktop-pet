"""Join background reads without confusing their busy signal with a result."""
import threading
import time


class CompletionRefresh:
    """UI-thread completion bursts: immediate first read and one trailing read.

    Only completion notifications use this gate. Explicit user refreshes and
    periodic quota reads retain their existing behavior and run coordinator.
    """
    def __init__(self,parent,refresh,clock=time.monotonic,interval=15):
        from PySide6.QtCore import QTimer
        self.refresh=refresh;self.clock=clock;self.interval=interval;self.last=None
        self.timer=QTimer(parent);self.timer.setSingleShot(True);self.timer.timeout.connect(self.request)
    def request(self):
        now=self.clock();remaining=0 if self.last is None else self.interval-(now-self.last)
        if remaining<=0:
            self.timer.stop();self.last=now;return self.refresh()
        if not self.timer.isActive():self.timer.start(max(1,__import__('math').ceil(remaining*1000)))
        return None


class RefreshRuns:
    """One running or reserved read, shared safely by UI and worker threads."""
    def __init__(self):
        self._lock = threading.Lock()
        self._serial = 0
        self._active = None

    def reserve(self):
        with self._lock:
            if self._active is not None:
                return self._active, False
            self._serial += 1
            self._active = self._serial
            return self._active, True

    @property
    def active(self):
        with self._lock:
            return self._active

    def complete(self, run):
        with self._lock:
            if self._active == run:
                self._active = None


class RefreshCoordinator:
    """UI-thread batches. Results match the actual source read, not a timer."""
    def __init__(self, finished, clock=time.monotonic, timeout=55):
        self.finished = finished
        self.clock = clock
        self.timeout = timeout
        self.batches = {}

    def active(self, scope):
        return scope in self.batches

    def begin(self, scope, sources):
        if self.active(scope):
            return False
        self.batches[scope] = dict(
            pending=dict(sources), failed=set(), deadline=self.clock()+self.timeout)
        # A missing worker is a real failed source; never leave a spinner waiting.
        for name, run in sources.items():
            if run is None:
                self.batches[scope]['pending'].pop(name, None)
                self.batches[scope]['failed'].add(name)
        self._finish_ready()
        return True

    def result(self, source, run, success):
        if run is None:
            return
        for batch in self.batches.values():
            if batch['pending'].get(source) != run:
                continue
            del batch['pending'][source]
            if not success:
                batch['failed'].add(source)
        self._finish_ready()

    def expire(self):
        now = self.clock()
        for batch in self.batches.values():
            if now >= batch['deadline']:
                batch['failed'].update(batch['pending'])
                batch['pending'].clear()
        self._finish_ready()

    def _finish_ready(self):
        ready = [(scope, sorted(batch['failed']))
                 for scope, batch in self.batches.items() if not batch['pending']]
        for scope, failed in ready:
            del self.batches[scope]
            self.finished(scope, not failed, failed)
