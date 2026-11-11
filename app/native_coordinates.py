"""Convert Win32 physical screen points through the actual HWND client area.

Never divide a global position by DPR: mixed-DPI monitors have distinct origins.
The client-size ratio also accounts for fractional-DPI rounding by Windows.
"""
import ctypes
from functools import lru_cache
from ctypes import wintypes

@lru_cache(maxsize=1)
def window_api():
    api=ctypes.WinDLL('user32',use_last_error=True)
    api.ScreenToClient.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    api.ScreenToClient.restype=wintypes.BOOL
    api.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    api.GetClientRect.restype=wintypes.BOOL
    api.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    api.GetWindowRect.restype=wintypes.BOOL
    api.GetDpiForWindow.argtypes=[wintypes.HWND]
    api.GetDpiForWindow.restype=wintypes.UINT
    api.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    api.SetWindowPos.restype=wintypes.BOOL
    return api

def client_position(hwnd,x,y,width,height,api=None):
    api=window_api() if api is None else api
    point=wintypes.POINT(x,y);rect=wintypes.RECT()
    if not api.ScreenToClient(hwnd,ctypes.byref(point)) or not api.GetClientRect(hwnd,ctypes.byref(rect)):return None
    pixels_x,pixels_y=rect.right-rect.left,rect.bottom-rect.top
    if pixels_x<=0 or pixels_y<=0 or width<=0 or height<=0:return None
    return ((point.x-rect.left)*width/pixels_x,(point.y-rect.top)*height/pixels_y)

def message_position(lparam):
    return ctypes.c_short(lparam&0xffff).value,ctypes.c_short((lparam>>16)&0xffff).value


def align_companion_position(anchor,companion,origin,size,scale,api=None):
    """Repair a frameless companion using the anchor's physical screen origin."""
    api=window_api() if api is None else api
    pet,card=wintypes.RECT(),wintypes.RECT()
    if not api.GetWindowRect(anchor,ctypes.byref(pet)) or not api.GetWindowRect(companion,ctypes.byref(card)):return
    x=pet.left+round(origin[0]*scale);y=pet.top+round(origin[1]*scale)
    width,height=(round(n*scale) for n in size)
    dpi=api.GetDpiForWindow(anchor)
    same_dpi=bool(dpi) and dpi==api.GetDpiForWindow(companion)
    move=abs(card.left-x)>2 or abs(card.top-y)>2
    resize=same_dpi and (abs(card.right-card.left-width)>2 or abs(card.bottom-card.top-height)>2)
    if not move and not resize:return
    # Let Windows deliver its DPI change before applying the new physical size.
    flags=0x0004|0x0010|0x0200
    if not resize:flags|=0x0001
    if not move:flags|=0x0002
    api.SetWindowPos(companion,None,x,y,width,height,flags)
