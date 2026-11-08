"""Keep a translucent raster window layered across Qt flag changes.

Qt 6.9's Windows setWindowFlags first replaces GWL_EXSTYLE, then restores
WS_EX_LAYERED in a later initialize call. Clearing WindowTransparentForInput
therefore briefly makes an exposed alpha window an ordinary rectangle. Keep
the existing layered bit in WM_STYLECHANGING, before Windows applies it.
Qt still owns input, focus, topmost and all other flags; no second HWND,
timers, opacity changes or after-the-fact repair are needed.
"""
import sys
from PySide6.QtCore import Qt


def preserve_layered_style(widget,event_type,message):
    if sys.platform!='win32' or event_type not in (b'windows_generic_MSG',b'windows_dispatcher_MSG'):
        return False
    import ctypes
    from ctypes import wintypes
    msg=wintypes.MSG.from_address(int(message))
    if msg.message!=0x7c or (msg.wParam&0xffffffff)!=0xffffffec or not msg.lParam:
        return False
    if not widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
        return False
    # STYLESTRUCT contains two 32-bit DWORDs even in a 64-bit process.
    styles=(ctypes.c_uint32*2).from_address(msg.lParam)
    if styles[0]&0x80000 and not styles[1]&0x80000:
        styles[1]|=0x80000
        return True
    return False
