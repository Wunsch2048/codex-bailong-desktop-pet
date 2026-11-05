"""Read-only foreground video detection; no page titles, URLs or media controls."""
import ctypes
from ctypes import wintypes
import os,time
import psutil

PLAYERS={'potplayermini.exe','potplayermini64.exe','potplayer.exe','vlc.exe','mpv.exe','mpvnet.exe',
    'mpc-hc.exe','mpc-hc64.exe','mpc-be.exe','mpc-be64.exe','wmplayer.exe','videoui.exe','video.ui.exe',
    'mediaplayer.exe','wmplayerlegacy.exe','kmplayer.exe','kmplayer64.exe','qqplayer.exe','splayer.exe'}
BROWSERS={'chrome.exe','msedge.exe','firefox.exe','brave.exe','vivaldi.exe','opera.exe','arc.exe',
    '360se.exe','360chrome.exe','qqbrowser.exe','sogouexplorer.exe'}
# Windows exposes no universal "this is a game" flag.  The combined policy
# therefore excludes known shell, browser, office and developer windows, then
# treats an unknown process that truly fills a monitor as a game candidate.
NON_GAME_PROCESSES={'explorer.exe','applicationframehost.exe','searchhost.exe','shellexperiencehost.exe',
    'startmenuexperiencehost.exe','textinputhost.exe','dwm.exe','taskmgr.exe','mspaint.exe','notepad.exe',
    'winword.exe','excel.exe','powerpnt.exe','outlook.exe','onenote.exe','write.exe','calc.exe',
    'code.exe','devenv.exe','pycharm64.exe','idea64.exe','notepad++.exe','steamwebhelper.exe',
    'gamebar.exe','obs64.exe','obs32.exe','teams.exe','slack.exe','discord.exe','wechat.exe','qq.exe'}
NON_GAME_CLASSES={'progman','workerw','shell_traywnd','cabinetwclass','applicationframewindow',
    'windows.ui.core.corewindow','chrome_widgetwin_1','mozillawindowclass','opera_windowclass'}
VIDEO_ROLES=('video','视频','影片','video player','视频播放器','影片播放器')
FULLSCREEN_LABELS=('全屏','full screen','fullscreen')
PLAY_LABELS=('播放','暂停','play','pause')
SEEK_LABELS=('进度','时间','seek','timeline','time','progress')

def intersection(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))

def fills_monitor(rect,monitor,tolerance=3):
    return len(rect)==4 and all(abs(a-b)<=tolerance for a,b in zip(rect,monitor))

def video_coverage(rect,monitor):
    """Accept centered letterboxing, while rejecting ordinary embedded players."""
    l,t,r,b=rect;x,y,z,w=monitor;mw,mh=z-x,w-y
    if mw<=0 or mh<=0 or r<=l or b<=t:return False
    if intersection(rect,monitor)<(r-l)*(b-t)*.96:return False
    centered=abs((l+r-x-z)/2)<=mw*.035 and abs((t+b-y-w)/2)<=mh*.035
    fills_axis=(r-l>=mw*.975 or b-t>=mh*.975)
    return centered and fills_axis and intersection(rect,monitor)>=mw*mh*.22

def game_fullscreen(frame):
    """Return whether an unknown monitor-filling process is a game candidate."""
    if not frame or not frame.get('fullscreen'):return False
    process=str(frame.get('process') or '').casefold();window_class=str(frame.get('cls') or '').casefold()
    if not process or process in PLAYERS or process in BROWSERS or process in NON_GAME_PROCESSES:return False
    return window_class not in NON_GAME_CLASSES

class MONITORINFO(ctypes.Structure):
    _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD)]

class WindowAPI:
    def __init__(self):
        if os.name!='nt':raise OSError('Windows required')
        self.u=ctypes.WinDLL('user32',use_last_error=True)
        self.u.GetForegroundWindow.restype=wintypes.HWND
        self.u.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];self.u.GetAncestor.restype=wintypes.HWND
        self.u.GetWindow.argtypes=[wintypes.HWND,wintypes.UINT];self.u.GetWindow.restype=wintypes.HWND
        self.u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        self.u.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        self.u.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
        self.u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.u.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        for name in ('IsWindow','IsWindowVisible','IsIconic'):
            getattr(self.u,name).argtypes=[wintypes.HWND]
        self.u.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD];self.u.MonitorFromWindow.restype=wintypes.HANDLE
        self.u.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MONITORINFO)]
        self.u.GetWindowLongPtrW.argtypes=[wintypes.HWND,ctypes.c_int];self.u.GetWindowLongPtrW.restype=ctypes.c_ssize_t
        self.u.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    def foreground(self):return int(self.u.GetForegroundWindow() or 0)
    def valid(self,hwnd):return bool(hwnd and self.u.IsWindow(hwnd))
    def rect(self,hwnd):
        r=wintypes.RECT()
        if not self.u.GetWindowRect(hwnd,ctypes.byref(r)):return None
        return (r.left,r.top,r.right,r.bottom)
    def topmost(self,hwnd):return bool(self.u.GetWindowLongPtrW(hwnd,-20)&8)
    def above(self,hwnd,target):
        for _ in range(256):
            target=self.u.GetWindow(target,3)
            if not target:return False
            if target==hwnd:return True
        return False
    def set_topmost(self,hwnd,top,behind=0):
        flags=1|2|0x10|0x200  # No geometry, activation, visibility or owner-order changes.
        if self.topmost(hwnd)!=bool(top):
            if not self.u.SetWindowPos(hwnd,wintypes.HWND(-1 if top else -2),0,0,0,0,flags):return False
        if not top and self.valid(behind) and not self.topmost(behind) and self.above(hwnd,behind):
            return bool(self.u.SetWindowPos(hwnd,behind,0,0,0,0,flags))
        return True
    def stack_with(self,hwnd,anchor):
        """Place a companion immediately above its anchor without raising it."""
        if not self.valid(hwnd) or not self.valid(anchor):return False
        previous=self.u.GetWindow(anchor,3)
        if previous==hwnd:return True
        # Use the observed native order. The topmost style alone does not
        # guarantee which side of the foreground window the anchor occupies.
        insert_after=previous or wintypes.HWND(-1 if self.topmost(anchor) else 0)
        flags=1|2|0x10|0x200
        moved=bool(self.u.SetWindowPos(hwnd,insert_after,0,0,0,0,flags))
        foreground=self.foreground()
        if foreground not in (hwnd,anchor) and self.valid(foreground):
            if self.above(hwnd,foreground) and not self.above(anchor,foreground):
                return self.set_topmost(hwnd,False,foreground)
        return moved

    def snapshot(self,hwnd=None):
        hwnd=self.foreground() if hwnd is None else hwnd
        if not hwnd or not self.u.IsWindowVisible(hwnd) or self.u.IsIconic(hwnd):return None
        hwnd=int(self.u.GetAncestor(hwnd,2) or hwnd)
        pid=wintypes.DWORD();self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if not pid.value or pid.value==os.getpid():return None
        try:name=psutil.Process(pid.value).name().casefold()
        except (psutil.Error,OSError):return None
        m=MONITORINFO();m.cbSize=ctypes.sizeof(m)
        if not self.u.GetMonitorInfoW(self.u.MonitorFromWindow(hwnd,2),ctypes.byref(m)):return None
        monitor=tuple(getattr(m.rcMonitor,k) for k in ('left','top','right','bottom'))
        r=wintypes.RECT();origin=wintypes.POINT()
        if not self.u.GetClientRect(hwnd,ctypes.byref(r)) or not self.u.ClientToScreen(hwnd,ctypes.byref(origin)):return None
        client=(origin.x,origin.y,origin.x+r.right,origin.y+r.bottom)
        cls=ctypes.create_unicode_buffer(256);self.u.GetClassNameW(hwnd,cls,256)
        return dict(hwnd=hwnd,pid=pid.value,process=name,cls=cls.value,monitor=monitor,
            fullscreen=fills_monitor(client,monitor))

class BrowserVideoProbe:
    def __init__(self):
        # Import COM support on the owner thread; the probe thread creates its own MTA.
        import comtypes,comtypes.client
        self.com=comtypes;self.client=comtypes.client;self.uia=None;self.types=None;self.known=None;self.firefox=None;self.detail={}
    def open_thread(self):self.com.CoInitializeEx(0)
    def close_thread(self):
        self.uia=None
        if self.firefox:self.firefox.clear()
        self.condition=None;self.controls=None;self.com.CoUninitialize()
    def clear(self):
        self.known=None
        if self.firefox:self.firefox.clear()
    def firefox_video(self,hwnd,monitor):
        from firefox_video import FirefoxVideo
        if self.types is None:self.types=self.client.GetModule('UIAutomationCore.dll')
        if self.firefox is None:self.firefox=FirefoxVideo(self.types)
        result=self.firefox.video(hwnd,monitor);self.detail=self.firefox.detail
        return result
    def ensure(self):
        if self.uia is not None:return
        self.types=self.client.GetModule('UIAutomationCore.dll')
        self.uia=self.client.CreateObject(self.types.CUIAutomation8,interface=self.types.IUIAutomation2)
        self.uia.ConnectionTimeout=500;self.uia.TransactionTimeout=700
        conditions=[self.uia.CreatePropertyCondition(self.types.UIA_LocalizedControlTypePropertyId,value) for value in VIDEO_ROLES]
        condition=conditions[0]
        for extra in conditions[1:]:condition=self.uia.CreateOrCondition(condition,extra)
        # Chromium versions often expose <video> as a generic Group. Confirm
        # these with media controls, never with page titles or a playing-audio flag.
        self.condition=self.uia.CreateOrCondition(condition,self.uia.CreatePropertyCondition(self.types.UIA_ControlTypePropertyId,50026))
        self.controls=self.uia.CreateOrCondition(self.uia.CreatePropertyCondition(self.types.UIA_ControlTypePropertyId,50000),self.uia.CreatePropertyCondition(self.types.UIA_ControlTypePropertyId,50015))
    def media_controls(self,element,rect):
        controls=element.FindAll(self.types.TreeScope_Descendants,self.controls)
        full=play=seek=False
        for i in range(min(controls.Length,80)):
            control=controls.GetElement(i)
            if control.CurrentIsOffscreen:continue
            bounds=control.CurrentBoundingRectangle
            if not intersection((bounds.left,bounds.top,bounds.right,bounds.bottom),rect):continue
            label=(control.CurrentName or '').casefold()
            if control.CurrentControlType==50015:
                r=control.CurrentBoundingRectangle
                seek|=bool(r.right-r.left>=(rect[2]-rect[0])*.6 and any(x in label for x in SEEK_LABELS))
            else:
                full|=any(x in label for x in FULLSCREEN_LABELS)
                play|=any(x in label for x in PLAY_LABELS)
            if full and play and seek:return True
        return False
    def video(self,hwnd,monitor):
        try:
            self.ensure();root=self.uia.ElementFromHandle(hwnd)
            elements=root.FindAll(self.types.TreeScope_Descendants,self.condition)
            found=False
            for i in range(min(elements.Length,32)):
                e=elements.GetElement(i)
                if e.CurrentIsOffscreen:continue
                r=e.CurrentBoundingRectangle
                if not video_coverage((r.left,r.top,r.right,r.bottom),monitor):continue
                key=(hwnd,tuple(e.GetRuntimeId()))
                recent=bool(self.known and self.known[0]==key and time.monotonic()-self.known[1]<2.5)
                explicit=e.CurrentLocalizedControlType.casefold() in VIDEO_ROLES
                if explicit or recent or self.media_controls(e,(r.left,r.top,r.right,r.bottom)):
                    if e.CurrentControlType==50026 and not recent:self.known=(key,time.monotonic())
                    found=True;break
            if not found:self.known=None
            return found
        except (OSError,RuntimeError,self.com.COMError):
            self.uia=None;return None

class VideoProbe:
    def __init__(self,api=None,browser=None):
        self.api=api or WindowAPI();self.browser=browser or BrowserVideoProbe()
    def read(self):
        frame=self.api.snapshot()
        if not frame:
            if hasattr(self.browser,'clear'):self.browser.clear()
            return dict(hwnd=0,fullscreen=False,video=False,reason='none')
        frame=dict(frame,video=False,reason='ordinary')
        if not frame['fullscreen']:
            if hasattr(self.browser,'clear'):self.browser.clear()
            return frame
        if frame['process'] in PLAYERS:
            frame.update(video=True,reason='player')
        elif frame['process']=='firefox.exe':
            frame.update(video=self.browser.firefox_video(frame['hwnd'],frame['monitor']),reason='firefox_ia2')
        elif frame['process'] in BROWSERS or frame['cls'].startswith('Chrome_WidgetWin'):
            frame.update(video=self.browser.video(frame['hwnd'],frame['monitor']),reason='browser')
        return frame

class FullscreenGate:
    """Debounce a real monitor-filling window, optionally requiring video."""
    def __init__(self,require_video=True):
        self.require_video=bool(require_video)
        self.active=None;self.pending=None;self.since=0.;self.missing=None
    def update(self,frame,now):
        key=(frame.get('hwnd',0),tuple(frame.get('monitor',())))
        active_key=(self.active['hwnd'],tuple(self.active['monitor'])) if self.active else None
        if not frame.get('fullscreen') or (self.active and key!=active_key):
            self.active=None;self.missing=None
        accepted=frame.get('fullscreen') and (not self.require_video or frame.get('video') is True)
        if accepted:
            self.missing=None
            if self.pending!=key:self.pending=key;self.since=now
            if now-self.since>=.45:self.active=frame
        else:
            self.pending=None
            if self.active:
                if self.missing is None:self.missing=now
                if now-self.missing>=(3. if frame.get('video') is None else .65):self.active=None
        return dict(self.active) if self.active else None

class VideoGate(FullscreenGate):
    """Compatibility alias for the video-only fullscreen policy."""
    def __init__(self):super().__init__(require_video=True)
