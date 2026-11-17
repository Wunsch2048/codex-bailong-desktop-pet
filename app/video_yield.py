"""Temporarily yield native z-order without remapping Qt windows or preferences."""
import threading,time
from PySide6.QtCore import QObject,QEvent,QTimer,Signal,Qt
from PySide6.QtWidgets import QApplication
from video_fullscreen import WindowAPI,VideoProbe,FullscreenGate,game_fullscreen,intersection

class VideoYield(QObject):
    observed=Signal(object)
    def __init__(self,pet,api=None,start=True):
        super().__init__(pet);self.pet=pet;self.api=api or WindowAPI();self.gate=FullscreenGate(True);self._mode='off'
        self.frame=None;self.changed={};self.reason='none';self.last_error=None;self.last_sample={};self.native_applied=False;self.attention_override=False
        self.stop=threading.Event();self.enabled=threading.Event();self.worker=None;self.queued=False
        self.observed.connect(self.accept,Qt.ConnectionType.QueuedConnection)
        QApplication.instance().installEventFilter(self)
        self.indicator=getattr(getattr(pet,'bubble',None),'status_indicator',None)
        if self.indicator is not None:self.indicator.changed.connect(self.reconcile)
        self.reconcile()
        if start:
            # comtypes initializes its import thread; each worker owns a separate MTA.
            try:self.probe=VideoProbe(api=self.api)
            except (ImportError,OSError) as error:self.probe=None;self.last_error=type(error).__name__
            self.worker=threading.Thread(target=self.run,name='video-fullscreen',daemon=True);self.worker.start()
    def policy(self):
        mode=self.pet.settings.get('fullscreen_yield_mode')
        if mode=='all':mode='game_video'
        if mode in ('off','video','game_video'):return mode
        return 'video' if self.pet.settings.get('video_fullscreen_yield',True) else 'off'
    def _set_gate(self,mode):
        self._mode=mode;self.gate=FullscreenGate(require_video=mode in ('video','game_video'));self.frame=None
    def run(self):
        try:
            if self.probe is not None:self.probe.browser.open_thread()
            while not self.stop.is_set():
                if self.enabled.is_set():
                    began=time.monotonic()
                    try:
                        if self._mode=='game_video' and self.probe is not None:
                            frame=self.probe.read()
                            if frame.get('fullscreen') and frame.get('video') is not True and game_fullscreen(frame):
                                frame=dict(frame,video=True,reason='game_fullscreen')
                        elif self._mode=='game_video':
                            frame=self.api.snapshot() or dict(hwnd=0,fullscreen=False,video=False,reason='none')
                            frame=dict(frame,video=game_fullscreen(frame),reason='game_fullscreen' if game_fullscreen(frame) else frame.get('reason','ordinary'))
                        elif self.probe is not None:frame=self.probe.read()
                        else:frame=dict(hwnd=0,fullscreen=False,video=None,reason='probe_unavailable')
                    except Exception as error:frame=dict(hwnd=0,fullscreen=False,video=None,reason='probe_error',error=type(error).__name__)
                    frame['probe_ms']=round((time.monotonic()-began)*1000,1)
                    if not self.stop.is_set():self.observed.emit(frame)
                if self.stop.wait(.8):break
        finally:
            if self.probe is not None:self.probe.browser.close_thread()
    def accept(self,frame,now=None):
        if self.stop.is_set():return
        self.reason=frame.get('reason','none')
        self.last_sample={key:frame.get(key) for key in ('fullscreen','video','reason','probe_ms','error')};self.last_sample['at']=time.time()
        self.frame=self.gate.update(frame,time.monotonic() if now is None else now)
        self.reconcile()
    def _pet_on_monitor(self,monitor):
        if not monitor or len(monitor)!=4:return False
        try:rect=self.api.rect(int(self.pet.winId()))
        except (AttributeError,OSError,TypeError,ValueError):rect=None
        if not rect:return False
        cx=(rect[0]+rect[2])//2;cy=(rect[1]+rect[3])//2
        return monitor[0]<=cx<monitor[2] and monitor[1]<=cy<monitor[3]
    def _set_pet_fullscreen_yield(self,hidden):
        setter=getattr(self.pet,'set_fullscreen_yield',None)
        if setter is not None:setter(bool(hidden))
        else:setattr(self.pet,'_fullscreen_yielded',bool(hidden))
    def owned(self,widget):
        policy=getattr(self.pet,'surface_policy',None)
        if policy is not None:return policy.owned(widget)
        while widget is not None:
            if widget is self.pet or widget is getattr(self.pet,'bubble',None):return True
            widget=widget.parentWidget()
        return False
    def windows(self):
        return [w for w in QApplication.topLevelWidgets() if self.owned(w) and w.isVisible() and w.testAttribute(Qt.WidgetAttribute.WA_WState_Created)]
    def reconcile(self):
        mode=self.policy()
        if mode!=self._mode:self._set_gate(mode)
        enabled=bool(mode!='off' and (mode=='game_video' or self.pet.settings.get('on_top')))
        if enabled:self.enabled.set()
        else:self.enabled.clear();self._set_gate(mode)
        frame=self.frame
        # A delayed COM result must never unpin after the foreground has changed.
        if frame and (not self.api.valid(frame['hwnd']) or self.api.foreground()!=frame['hwnd']):
            self._set_gate(mode);frame=None
        if mode=='game_video':
            # The general policy is deliberately different from video mode:
            # hide surfaces for a game or video on the pet's own monitor and
            # never let a completion reminder reclaim the topmost slot. The
            # tray icon remains alive.
            yielding=bool(enabled and frame and self._pet_on_monitor(frame.get('monitor')))
            self.attention_override=False;self.native_applied=False;self.pet._video_yielded=False
            for hwnd,widget in list(self.changed.items()):
                try:valid=widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created) and int(widget.winId())==hwnd
                except RuntimeError:valid=False
                if valid and self.api.valid(hwnd):self.api.set_topmost(hwnd,bool(self.pet.settings.get('on_top')))
                self.changed.pop(hwnd,None)
            self._set_pet_fullscreen_yield(yielding)
            return
        self._set_pet_fullscreen_yield(False)
        windows=self.windows()
        overlaps=bool(frame and any(intersection(self.api.rect(int(w.winId())) or (0,0,0,0),frame['monitor'])>0 for w in windows))
        indicator=getattr(getattr(self.pet,'bubble',None),'status_indicator',None)
        self.attention_override=bool(enabled and overlaps and indicator is not None and indicator.unread)
        yielding=bool(enabled and overlaps and not self.attention_override)
        desired={int(w.winId()):w for w in windows} if yielding else {}
        # Restore the latest preference; never resurrect a deleted HWND.
        for hwnd,widget in list(self.changed.items()):
            if hwnd not in desired:
                try:
                    if yielding and not widget.isVisible():continue
                except RuntimeError:pass
                try:valid=widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created) and int(widget.winId())==hwnd
                except RuntimeError:valid=False
                if valid and self.api.valid(hwnd):self.api.set_topmost(hwnd,bool(self.pet.settings.get('on_top')))
                self.changed.pop(hwnd,None)
        self.pet._video_yielded=yielding
        self.native_applied=False
        if yielding:
            applied=[]
            for hwnd,widget in desired.items():
                success=self.api.set_topmost(hwnd,False,frame['hwnd'])
                if success:self.changed[hwnd]=widget
                applied.append(success and (not hasattr(self.api,'topmost') or not self.api.topmost(hwnd)))
            self.native_applied=bool(applied and all(applied))
    def eventFilter(self,obj,event):
        if self.frame and event.type() in (QEvent.Type.Show,QEvent.Type.WinIdChange) and not self.queued:
            self.queued=True;QTimer.singleShot(0,self.reconcile_later)
        return False
    def reconcile_later(self):
        self.queued=False
        if not self.stop.is_set():self.reconcile()
    def shutdown(self):
        if self.indicator is not None:
            try:self.indicator.changed.disconnect(self.reconcile)
            except (RuntimeError,TypeError):pass
        self.stop.set();self.frame=None;self.reconcile()
        QApplication.instance().removeEventFilter(self)
        if self.worker:self.worker.join(.9)

def smoke_probe(path):
    """Frozen dependency/native capability smoke, independent of user pet singleton."""
    import json
    from pathlib import Path
    from video_fullscreen import BrowserVideoProbe
    probe=BrowserVideoProbe();probe.ensure();api=WindowAPI()
    from firefox_video import FirefoxVideo
    firefox=FirefoxVideo(probe.types)
    result=dict(passed=bool(probe.uia),uia=True,connectionTimeout=probe.uia.ConnectionTimeout,
        transactionTimeout=probe.uia.TransactionTimeout,nativeWindowAPI=True,firefoxIA2Loaded=bool(firefox.ole))
    Path(path).write_text(json.dumps(result,indent=2),encoding='utf-8');return 0
