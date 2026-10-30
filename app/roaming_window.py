"""Read only foreground geometry on this pet's monitor. No titles or contents."""
import ctypes,os
from ctypes import wintypes

class ForegroundGeometry:
    def __init__(self):self.api=None
    def read(self,pet):
        if os.name!='nt':return None
        try:
            if self.api is None:
                from video_fullscreen import WindowAPI
                self.api=WindowAPI()
            api=self.api;hwnd=api.foreground()
            if not api.valid(hwnd) or not api.u.IsWindowVisible(hwnd) or api.u.IsIconic(hwnd):return None
            pid=wintypes.DWORD();api.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==os.getpid():return None
            rect=api.rect(hwnd)
            if not rect:return None
            from video_fullscreen import MONITORINFO
            monitor=api.u.MonitorFromWindow(int(pet.winId()),2);info=MONITORINFO();info.cbSize=ctypes.sizeof(info)
            if not monitor or not api.u.GetMonitorInfoW(monitor,ctypes.byref(info)):return None
            r=info.rcMonitor;l,t,right,bottom=max(rect[0],r.left),max(rect[1],r.top),min(rect[2],r.right),min(rect[3],r.bottom)
            if l>=right or t>=bottom:return None
            # Convert through the actual HWND client ratio. Dividing global
            # coordinates by DPR breaks negative/mixed-DPI monitor origins.
            from native_coordinates import client_position
            a=client_position(int(pet.winId()),l,t,pet.width(),pet.height())
            b=client_position(int(pet.winId()),right,bottom,pet.width(),pet.height())
            if not a or not b:return None
            return (pet.x()+a[0],pet.y()+a[1],pet.x()+b[0],pet.y()+b[1])
        except (OSError,ValueError,AttributeError):return None
