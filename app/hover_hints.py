"""Small non-activating bubbles shared by header actions and the quota tray."""
from settings_controls import play_animation
from theme_registry import color as theme_color
import weakref
from PySide6.QtCore import Qt,QObject,QEvent,QPoint,QRect,QRectF,QTimer,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QColor,QCursor,QFontMetrics,QPainter,QPainterPath,QPen
from PySide6.QtWidgets import QWidget,QToolTip
from typography import ui_font
from ui_theme import SURFACE,INK,MUTED,BORDER
from settings_controls import motion_enabled

HOVER_DELAY_MS=500
_TRAY_HOOKS={}


class HintBubble(QWidget):
    """One reused, input-transparent tool surface; never resizes the card."""
    def __init__(self):
        flags=Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowDoesNotAcceptFocus|Qt.WindowType.WindowTransparentForInput
        super().__init__(None,flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFont(ui_font(12));self.title='';self.subtitle='';self.level=0.;self.below=False;self.tip_x=20.
        self.animation=QVariantAnimation(self);self.animation.valueChanged.connect(self._advance)
        self.animation.finished.connect(self._finished);self.hide()

    def present(self,title,subtitle,anchor,screen,*,card_top=None,topmost=True,owner=None):
        self.animation.stop();self.title=str(title);self.subtitle=str(subtitle)
        width,height=self.hint_size()
        if bool(self.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)!=bool(topmost):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,bool(topmost))
        # A report is an owned native Tool window above the main card. Merely
        # raising an unrelated Tool surface does not establish that hierarchy.
        self.winId()
        if owner is not None:owner.winId()
        parent=owner.windowHandle() if owner is not None else None
        if self.windowHandle().transientParent() is not parent:self.windowHandle().setTransientParent(parent)
        area=screen.availableGeometry();cx=anchor.center().x()
        left=max(area.left()+2,min(cx-width//2,area.right()-width-1))
        edge=anchor.top() if card_top is None else card_top
        top=edge-height+1;self.below=top<area.top()+2
        if self.below:top=anchor.bottom()+2
        top=max(area.top()+2,min(top,area.bottom()-height-1))
        self.tip_x=max(12.,min(float(width-12),float(cx-left)))
        self.setGeometry(left,top,width,height);self.setAccessibleName(self.title)
        self.setAccessibleDescription(self.subtitle)
        if not self.isVisible():self.level=0.;self.show()
        self.raise_()
        self._animate(1.)
        # An already opaque surface has no alpha delta to drive paintEvent.
        # Moving a layered window alone can retain its old pixels.
        self.update()

    def hint_size(self):
        metrics=QFontMetrics(self.font());width=max(metrics.horizontalAdvance(self.title),metrics.horizontalAdvance(self.subtitle))+22
        return max(42,min(260,width)),50 if self.subtitle else 32

    def _animate(self,target):
        self.animation.stop()
        if not motion_enabled():
            self.level=target;self.update();self._finished();return
        start=self.level;blocked=self.animation.blockSignals(True)
        try:
            self.animation.setDuration(160 if target else 120)
            self.animation.setEasingCurve(QEasingCurve.Type.OutCubic if target else QEasingCurve.Type.InCubic)
            self.animation.setStartValue(start);self.animation.setEndValue(target);self.animation.setCurrentTime(0)
        finally:self.animation.blockSignals(blocked)
        self.level=start;play_animation(self.animation)

    def dismiss(self,immediate=False):
        if immediate:
            self.animation.stop();self.level=0.;self.hide()
        elif self.isVisible():self._animate(0.)

    def _advance(self,value):self.level=float(value);self.update()
    def _finished(self):
        if self.level<=0:self.hide()
    def paintEvent(self,event):
        p=QPainter(self);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.GlobalColor.transparent);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setOpacity(self.level)
        body=QRectF(1,5 if self.below else 1,self.width()-2,self.height()-6)
        shape=QPainterPath();shape.addRoundedRect(body,9,9)
        arrow=QPainterPath();edge=body.top() if self.below else body.bottom()
        arrow.moveTo(self.tip_x-4,edge);arrow.lineTo(self.tip_x,edge-4 if self.below else edge+4)
        arrow.lineTo(self.tip_x+4,edge);arrow.closeSubpath();shape=shape.united(arrow)
        p.setPen(QPen(QColor(theme_color(BORDER)),1));p.setBrush(QColor(theme_color(SURFACE)));p.drawPath(shape)
        p.setFont(self.font());p.setPen(QColor(theme_color(INK)))
        if self.subtitle:
            p.drawText(body.adjusted(10,5,-10,-body.height()+23),Qt.AlignmentFlag.AlignVCenter,self.title)
            p.setPen(QColor(theme_color(MUTED)));p.drawText(body.adjusted(10,22,-10,-4),Qt.AlignmentFlag.AlignVCenter,self.subtitle)
        else:p.drawText(body,Qt.AlignmentFlag.AlignCenter,self.title)
        p.end()


class HeaderHints(QObject):
    """Delay first entry, keep adjacent button changes and data refresh stable."""
    def __init__(self,bubble):
        super().__init__(bubble);self.popup=HintBubble();self.target=None;self.rebuilding=False;self.role=None
        self.delay=QTimer(self);self.delay.setSingleShot(True);self.delay.setInterval(HOVER_DELAY_MS);self.delay.timeout.connect(self._show)
        self.leave=QTimer(self);self.leave.setSingleShot(True);self.leave.setInterval(60);self.leave.timeout.connect(self.dismiss)
        self.watch=QTimer(self);self.watch.setInterval(100);self.watch.timeout.connect(self._check_hover)
        bubble.destroyed.connect(self.popup.deleteLater)

    def _target(self):
        value=self.target() if self.target else None
        try:return value if value is not None and value.isVisible() else None
        except RuntimeError:return None

    def dismiss(self,immediate=False):
        self.delay.stop();self.leave.stop();self.watch.stop();self.target=None;self.rebuilding=False;self.role=None;self.popup.dismiss(immediate)

    def _check_hover(self):
        if self.rebuilding:return
        button=self._target()
        if button is None or not QRect(button.mapToGlobal(QPoint()),button.size()).contains(QCursor.pos()):
            if not self.leave.isActive():self.leave.start()

    def preserve_for_rebuild(self):
        button=self._target();transition=getattr(self.parent(),'size_transition',None)
        if not self.popup.isVisible() or button is None or (transition and (transition.running or transition.preparing)):return
        self.role=button.objectName();self.rebuilding=True;self.leave.stop();self.delay.stop()
        QTimer.singleShot(0,self,self._restore_header)

    def _restore_header(self):
        if not self.rebuilding:return
        self.rebuilding=False;role=self.role;self.role=None
        for button in self.parent().findChildren(QWidget):
            if not button.property('headerActionHint'):continue
            if button.objectName()==role and button.isVisible() and QRect(button.mapToGlobal(QPoint()),button.size()).contains(QCursor.pos()):
                self.target=weakref.ref(button);self._show();return
        self.dismiss(True)

    def _show(self):
        b=self.parent();button=self._target();transition=getattr(b,'size_transition',None)
        if button is None or not b.isVisible() or (transition and (transition.running or transition.preparing)):
            self.dismiss(True);return
        text=str(button.property('headerActionHint') or '')[:4]
        if not text:self.dismiss(True);return
        point=button.mapToGlobal(QPoint());anchor=QRect(point,button.size())
        report=getattr(b,'report',None)
        owner=report if report is not None and report.isVisible() else b
        top=anchor.top() if button.objectName().startswith('theme_dot_') else b.mapToGlobal(QPoint()).y()
        self.popup.present(text,'',anchor,button.screen(),card_top=top,
                           topmost=bool(b.windowFlags()&Qt.WindowType.WindowStaysOnTopHint),owner=owner)
        self.watch.start()

    def eventFilter(self,obj,event):
        # Style/palette/paint storms are irrelevant to hover lifetime. Do not
        # traverse widget ancestry while Qt is polishing or tearing down forms.
        kind=event.type()
        if kind not in (QEvent.Type.Hide,QEvent.Type.Close,QEvent.Type.Move,QEvent.Type.Resize,QEvent.Type.ToolTip,QEvent.Type.Enter,QEvent.Type.Leave,QEvent.Type.MouseButtonPress,QEvent.Type.ParentChange):return False
        from shiboken6 import isValid
        if not isinstance(obj,QWidget) or not isValid(obj):return False
        b=self.parent()
        if b is None or not isValid(b):return False
        if obj is not b and not b.isVisible():return False
        if obj is b and (kind in (QEvent.Type.Hide,QEvent.Type.Close) or (kind in (QEvent.Type.Move,QEvent.Type.Resize) and not self.rebuilding)):self.dismiss(True)
        if obj is not b and not b.isAncestorOf(obj):return False
        if kind==QEvent.Type.ToolTip:
            QToolTip.hideText();event.accept();return True
        hint=obj.property('headerActionHint')
        if not hint:return False
        if self.rebuilding and kind in (QEvent.Type.Leave,QEvent.Type.Hide,QEvent.Type.ParentChange):return False
        if kind==QEvent.Type.Enter:
            self.leave.stop()
            if self._target() is obj and (self.delay.isActive() or self.popup.isVisible()):return False
            self.target=weakref.ref(obj)
            if self.popup.isVisible():self._show()
            else:self.delay.start()
        elif kind==QEvent.Type.Leave and self.target and self.target() is obj:
            self.delay.stop()
            if self.popup.isVisible():self.leave.start()
            else:self.target=None
        elif kind in (QEvent.Type.MouseButtonPress,QEvent.Type.Hide,QEvent.Type.ParentChange) and self.target and self.target() is obj:self.dismiss(True)
        return False


class TrayMouseHook:
    """Subclass only this process's Qt tray receiver; keep Qt click/menu handling."""
    def __init__(self,enter,leave):
        self.enter=enter;self.leave=leave;self.hwnd=None;self.callback=None;self.error=''

    def attach(self,hwnd):
        if self.hwnd:return True
        import ctypes,os
        from ctypes import wintypes as w
        user=ctypes.WinDLL('user32',use_last_error=True);pid=w.DWORD()
        user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value!=os.getpid():raise ValueError('Tray receiver must belong to this process')
        self.library=ctypes.WinDLL('comctl32',use_last_error=True)
        prototype=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM,ctypes.c_size_t,ctypes.c_size_t)
        self.library.DefSubclassProc.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];self.library.DefSubclassProc.restype=ctypes.c_ssize_t
        self.library.SetWindowSubclass.argtypes=[w.HWND,prototype,ctypes.c_size_t,ctypes.c_size_t];self.library.SetWindowSubclass.restype=w.BOOL
        self.library.RemoveWindowSubclass.argtypes=[w.HWND,prototype,ctypes.c_size_t];self.library.RemoveWindowSubclass.restype=w.BOOL
        def receive(handle,message,wp,lp,identity,data):
            try:
                if message==0x8065 and (lp>>16)&0xffff==0:
                    code=lp&0xffff
                    if code in (0x0200,0x0406):self.enter()
                    elif code in (0x0201,0x0203,0x007b,0x0400,0x0401):self.leave()
                elif message==0x0082:self.hwnd=None;_TRAY_HOOKS.pop(int(handle),None);self.leave()
            except Exception as error:self.error=str(error)
            return self.library.DefSubclassProc(handle,message,wp,lp)
        self.callback=prototype(receive)
        if not self.library.SetWindowSubclass(hwnd,self.callback,id(self),0):raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd=hwnd;_TRAY_HOOKS[int(hwnd)]=self;return True

    def close(self):
        if self.hwnd:
            if self.library.RemoveWindowSubclass(self.hwnd,self.callback,id(self)):
                _TRAY_HOOKS.pop(int(self.hwnd),None);self.hwnd=None


class TrayHints(QObject):
    """Track position only while actually hovering; no idle cursor polling."""
    def __init__(self,tray,parent):
        super().__init__(parent);self.tray=tray;self.popup=HintBubble();self.title='额度未知';self.subtitle='等待刷新'
        self.hovering=False;self.hook=TrayMouseHook(self.enter,self.dismiss)
        self.delay=QTimer(self);self.delay.setSingleShot(True);self.delay.setInterval(HOVER_DELAY_MS);self.delay.timeout.connect(self._show)
        self.watch=QTimer(self);self.watch.setInterval(100);self.watch.timeout.connect(self._check)
        tray.installEventFilter(self);tray.activated.connect(lambda *_:self.dismiss())
        if hasattr(tray,'native_hover'):tray.native_hover.connect(self.enter)
        if tray.contextMenu():tray.contextMenu().aboutToShow.connect(self.dismiss)
        parent.destroyed.connect(self.popup.deleteLater)

    def ensure_hook(self):
        import sys
        if hasattr(self.tray,'native_hover'):return  # the fixed host forwards its own Shell messages
        if sys.platform!='win32' or not self.tray.isVisible():return
        if not self.hook.hwnd:
            from silent_notify import qt_tray_window
            hwnd=qt_tray_window()
            if hwnd:
                try:self.hook.attach(hwnd)
                except (OSError,ValueError) as error:self.hook.error=str(error)

    def set_text(self,title,subtitle):
        changed=(self.title,self.subtitle)!=(title,subtitle);self.title=title;self.subtitle=subtitle
        if changed and self.popup.isVisible():self._show()

    def _inside(self):
        point=QCursor.pos();rect=self.tray.geometry()
        return self.tray.isVisible() and not rect.isEmpty() and (rect.contains(point) or (self.popup.isVisible() and self.popup.geometry().contains(point)))

    def enter(self):
        if self.tray.contextMenu() and self.tray.contextMenu().isVisible():return
        if not self._inside():return
        if not self.hovering:self.hovering=True;self.delay.start();self.watch.start()

    def _show(self):
        if not self.hovering or not self._inside():self.dismiss();return
        rect=self.tray.geometry()
        from PySide6.QtGui import QGuiApplication
        screen=QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        self.popup.present(self.title,self.subtitle,rect,screen)

    def _check(self):
        if not self._inside():self.dismiss()

    def dismiss(self):
        self.hovering=False;self.delay.stop();self.watch.stop();self.popup.dismiss()

    def close(self):
        self.dismiss();self.popup.dismiss(True);self.hook.close();self.popup.close()

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.ToolTip:self.enter();event.accept();return True
        return False
