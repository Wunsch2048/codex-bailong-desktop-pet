"""Plasma X11/XWayland integration; keep Qt geometry and the original drag path."""
import ctypes
from ctypes.util import find_library


from .input_shape import input_bitmap


class InputShape:
    """Shape only mouse input, preserving the character's soft visual alpha."""
    def __init__(self):
        x11 = find_library('X11')
        xext = find_library('Xext')
        if not x11 or not xext:
            raise RuntimeError('KDE 后端需要 libX11 和 libXext（X Shape）')
        self.x11 = ctypes.CDLL(x11)
        self.xext = ctypes.CDLL(xext)
        display = ctypes.c_void_p
        xid = ctypes.c_ulong
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XOpenDisplay.restype = display
        self.x11.XCloseDisplay.argtypes = [display]
        self.x11.XCreateBitmapFromData.argtypes = [display, xid, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint]
        self.x11.XCreateBitmapFromData.restype = xid
        self.x11.XFreePixmap.argtypes = [display, xid]
        self.x11.XFlush.argtypes = [display]
        self.xext.XShapeQueryVersion.argtypes = [display, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        self.xext.XShapeCombineMask.argtypes = [display, xid, ctypes.c_int, ctypes.c_int, ctypes.c_int, xid, ctypes.c_int]
        self.display = self.x11.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('无法连接 KDE 的 X11/XWayland 显示服务')
        major, minor = ctypes.c_int(), ctypes.c_int()
        if not self.xext.XShapeQueryVersion(self.display, ctypes.byref(major), ctypes.byref(minor)) or (major.value, minor.value) < (1, 1):
            self.close()
            raise RuntimeError('X11/XWayland 不支持独立鼠标命中区域（X Shape 1.1）')
        self.last = None

    def close(self):
        if self.display:
            self.x11.XCloseDisplay(self.display)
            self.display = None

    def update(self, pet):
        from PySide6.QtCore import Qt, QRectF
        from PySide6.QtGui import QImage, QPainter
        if not self.display or not pet.isVisible():
            return
        handle = pet.windowHandle()
        if handle is None:
            return
        # Qt 6.9 can retain QWidget.winId() after setWindowFlag recreates its
        # platform window. QWindow owns the current, live X11 resource.
        window = int(handle.winId())
        ratio = pet.devicePixelRatioF()
        transform = pet.frame_transform(QRectF(pet.rect()))
        frame = pet.frames[0].cacheKey() if pet.frames else None
        key = (window, frame, pet.size().width(), pet.size().height(), ratio,
               pet.settings.get('mouse_through'), transform.m11(), transform.m22(), transform.dx(), transform.dy())
        if key == self.last:
            return
        image = QImage(round(pet.width() * ratio), round(pet.height() * ratio), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        if pet.frames and not pet.settings.get('mouse_through'):
            painter = QPainter(image)
            pet.draw_frame(painter, QRectF(pet.rect()))
            painter.end()
        data = input_bitmap(image)
        bitmap = self.x11.XCreateBitmapFromData(self.display, window, data, image.width(), image.height())
        if not bitmap:
            raise RuntimeError('无法创建桌宠鼠标命中区域')
        try:
            self.xext.XShapeCombineMask(self.display, window, 2, 0, 0, bitmap, 0)
            self.x11.XFlush(self.display)
        finally:
            self.x11.XFreePixmap(self.display, bitmap)
        self.last = key


def install(stack):
    """Apply an input mask after drawing; never crop the translucent window."""
    from .overrides import replace
    from desktop import DesktopPet
    paint = DesktopPet.paintEvent

    def paint_event(pet, event):
        paint(pet, event)
        timer = getattr(pet, '_kde_shape_timer', None)
        if timer and not timer.isActive():
            # Qt may be recreating the native window while it paints. Wait for
            # that operation to finish before asking for its current X11 ID.
            timer.start(0)

    stack.enter_context(replace(DesktopPet, 'paintEvent', paint_event))


def attach(pet, stack):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    if QApplication.platformName() != 'xcb':
        raise RuntimeError('KDE 后端必须在创建 QApplication 前选择 QT_QPA_PLATFORM=xcb')
    pet._kde_input_shape = InputShape()
    stack.callback(pet._kde_input_shape.close)
    pet._kde_shape_timer = QTimer(pet)
    pet._kde_shape_timer.setSingleShot(True)
    pet._kde_shape_timer.timeout.connect(lambda: pet._kde_input_shape.update(pet))
    stack.callback(pet._kde_shape_timer.stop)
    pet.update()
