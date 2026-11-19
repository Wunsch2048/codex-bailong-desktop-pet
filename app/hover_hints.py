"""Small non-activating bubbles shared by header actions and the quota tray."""
from settings_controls import play_animation
from popup_motion import POPUP_OPEN,POPUP_CLOSE,POPUP_OPEN_MS,POPUP_CLOSE_MS,POPUP_FULL_SIZE_MS,anchored_start,popup_sample
from theme_registry import color as theme_color,palette
import weakref
from PySide6.QtCore import Qt,QAbstractAnimation,QObject,QEvent,QPoint,QPointF,QRect,QRectF,QSize,QTimer,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QColor,QCursor,QFontMetrics,QPainter,QPainterPath,QPen
from PySide6.QtWidgets import QWidget,QToolTip,QApplication
from typography import ui_font
from ui_theme import SURFACE,INK,MUTED,BORDER
from settings_controls import motion_enabled

HOVER_DELAY_MS=500
DETAIL_WIDTH=294
DETAIL_MIN_HEIGHT=96
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
        self.setFont(ui_font(12));self.title='';self.subtitle='';self.level=0.;self.below=False;self.tip_x=20.;self.motion_origin=None;self.motion_side=False
        self.animation=QVariantAnimation(self);self.animation.valueChanged.connect(self._advance)
        self.animation.finished.connect(self._finished);self._closing=False;self._exit_frames=None;self._interrupted=None;self.hide()

    def present(self,title,subtitle,anchor,screen,*,card_top=None,topmost=True,owner=None,geometry=None,initial_level=0.):
        self.title=str(title);self.subtitle=str(subtitle)
        width,height=self.hint_size()
        bubble=getattr(owner,'bubble',None) or (owner if hasattr(owner,'owner_pet') else None)
        if bubble is not None:
            from surface_policy import card_layer,update_qt_layer
            update_qt_layer(self,card_layer(bubble))
        elif bool(self.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)!=bool(topmost):
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
        self.motion_origin=None;self.motion_side=False
        if geometry is None:self.setGeometry(left,top,width,height)
        else:
            self.setGeometry(geometry)
            self.below=geometry.center().y()>anchor.center().y()
            local=anchor.center()-geometry.topLeft()
            self.motion_side=geometry.left()>anchor.right() or geometry.right()<anchor.left()
            x=max(1,min(geometry.width()-1,local.x()))
            y=max(1,min(geometry.height()-1,local.y()))
            self.motion_origin=QPointF(x,y)
        self.setAccessibleName(self.title)
        self.setAccessibleDescription(self.subtitle)
        if not self.isVisible():
            self.level=initial_level
            # Opaque hints publish their complete first frame. Animated hints
            # still start with a clear backing store.
            self.native_seeded=False
            if QApplication.platformName()=='windows':
                from native_landing import publish
                try:self.native_seeded=publish(self,self.grab() if initial_level>=1. else None)
                except OSError:self.native_seeded=False
            self.show()
        self.raise_()
        self._animate(1.)
        # An already opaque surface has no alpha delta to drive paintEvent.
        # Moving a layered window alone can retain its old pixels.
        self.update()

    def hint_size(self):
        title_metrics=QFontMetrics(ui_font(13,True))
        metrics=QFontMetrics(ui_font(12))
        width=max(title_metrics.horizontalAdvance(self.title)+2,metrics.horizontalAdvance(self.subtitle))+24
        width=max(42,min(280,width))
        if not self.subtitle:return width,34
        flags=Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft
        height=metrics.boundingRect(QRect(0,0,width-22,1000),flags,self.subtitle).height()
        return width,max(58,height+38)

    def _animate(self,target):
        if self.animation.state()==QAbstractAnimation.State.Running and self.animation.endValue()==target:return
        if not self._closing and target==1. and self.level>=POPUP_FULL_SIZE_MS/POPUP_OPEN_MS:
            return
        if self._shell_is_settling():self.level=1.
        interrupted=self.motion_sample() if 0.<self.level<1. else None
        self.animation.stop()
        self._closing=not target
        if interrupted is None:self._exit_frames=None
        self._interrupted=(self.level,interrupted) if interrupted is not None else None
        if self.level==target:self.update();self._finished();return
        if not motion_enabled():
            self.level=target;self.update();self._finished();return
        if self._closing and self.level>=1.:
            sharp=self.grab()
            if not sharp.isNull():
                size=QSize(max(1,round(sharp.width()/5)),max(1,round(sharp.height()/5)))
                soft=sharp.scaled(size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
                soft=soft.scaled(sharp.size(),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
                soft.setDevicePixelRatio(sharp.devicePixelRatioF())
                self._exit_frames=(sharp,soft)
        start=self.level;blocked=self.animation.blockSignals(True)
        try:
            self.animation.setDuration(POPUP_OPEN_MS if target else POPUP_CLOSE_MS)
            self.animation.setEasingCurve(QEasingCurve.Type.Linear)
            self.animation.setStartValue(start);self.animation.setEndValue(target);self.animation.setCurrentTime(0)
        finally:self.animation.blockSignals(blocked)
        self.level=start;play_animation(self.animation)

    def dismiss(self,immediate=False):
        if immediate:
            self.animation.stop();self.level=0.;self._closing=False;self._exit_frames=None;self._interrupted=None;self.hide()
        elif self.isVisible():self._animate(0.)

    def motion_sample(self):
        if self._interrupted is not None:
            start,frame=self._interrupted
            target=0. if self._closing else 1.
            progress=min(1.,abs(self.level-start)/max(.001,abs(target-start)))
            progress=1.-(1.-progress)**3
            finish=(*frame[:4],0.,frame[-1]) if self._closing else POPUP_OPEN[-1][1:]
            return tuple(a+(b-a)*progress for a,b in zip(frame,finish))
        if self._closing:
            return popup_sample(POPUP_CLOSE,(1.-self.level)*POPUP_CLOSE_MS)
        width,height,travel,inset,alpha,blur=popup_sample(POPUP_OPEN,self.level*POPUP_OPEN_MS)
        if self.height()<80 and self.level>=POPUP_FULL_SIZE_MS/POPUP_OPEN_MS:travel=0.
        extent=(self.width() if self.motion_side else self.height())-2
        first_row=min(.73,max(.19,24./max(1.,extent)))
        height=first_row+(1.-first_row)*(height-.19)/.81
        return width,height,travel,inset,alpha,blur

    def motion_bounds(self):
        area=QRectF(self.rect()).adjusted(1,1,-1,-1)
        origin=self.motion_origin if self.motion_origin is not None else QPointF(self.tip_x,area.top() if self.below else area.bottom())
        width,height,travel,inset,_,_=self.motion_sample()
        # Rotate the measured track around the trigger if screen avoidance
        # places the popup on a different side.
        if self.motion_side:
            w=area.width()*height;h=area.height()*width
            offset=max(-.9,travel*area.width())
            x=area.left()+offset if origin.x()<area.center().x() else area.right()-w-offset
            y=anchored_start(area.top(),area.height(),h,origin.y(),inset)
        else:
            w=area.width()*width;h=area.height()*height
            x=anchored_start(area.left(),area.width(),w,origin.x(),inset)
            offset=max(-.9,travel*area.height())
            y=area.top()+offset if origin.y()<area.center().y() else area.bottom()-h-offset
        # The subpixel overshoot uses the existing one-pixel transparent
        # margin. The native surface and its interaction area stay fixed.
        return QRectF(x,y,w,h).intersected(QRectF(self.rect()))

    def _shell_is_settling(self):
        return (not self._closing and self._interrupted is None
                and POPUP_FULL_SIZE_MS/POPUP_OPEN_MS<=self.level<1.)

    def paint_shell(self,painter,shape):
        if self._shell_is_settling():
            edge=self.motion_bounds()
            shape=shape.translated(edge.left()-1.,edge.top()-1.)
        surface=QColor(theme_color(SURFACE))
        surface.setAlpha(255)
        painter.setBrush(surface)
        painter.setPen(QPen(QColor(theme_color(BORDER)),1))
        painter.drawPath(shape)

    def paint_panel_shell(self,painter,body):
        frame=QPainterPath();frame.addRoundedRect(body,9,9)
        self.paint_shell(painter,frame)

    def apply_motion(self,painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.level<=0:return False
        if self.level>=1. or self._shell_is_settling():return True
        rect=self.motion_bounds()
        _,_,_,_,alpha,blur=self.motion_sample()
        contour=QPainterPath()
        radius=min(9.,max(4.,min(rect.width(),rect.height())*.14))
        contour.addRoundedRect(rect,radius,radius)
        painter.setOpacity(alpha)
        if self._exit_frames is None:painter.fillPath(contour,QColor(theme_color(SURFACE)))
        painter.setClipPath(contour,Qt.ClipOperation.IntersectClip)
        # Move the content with the exposed edge at its native text size.
        if self.motion_side:painter.translate(rect.left()-1.,0.)
        else:painter.translate(0.,rect.top()-1.)
        if self._exit_frames is not None:
            sharp,soft=self._exit_frames
            painter.setOpacity(alpha*(1.-blur));painter.drawPixmap(QPointF(),sharp)
            painter.setOpacity(alpha*blur);painter.drawPixmap(QPointF(),soft)
            return False
        return True

    def _advance(self,value):self.level=float(value);self.update()
    def _finished(self):
        if self.level<=0 or self.level>=1.:
            self._exit_frames=None;self._interrupted=None
        if self.level<=0:self._closing=False;self.hide()
    def paintEvent(self,event):
        p=QPainter(self);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.GlobalColor.transparent);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if not self.apply_motion(p):return
        body=QRectF(1,5 if self.below else 1,self.width()-2,self.height()-6)
        shape=QPainterPath();shape.addRoundedRect(body,9,9)
        arrow=QPainterPath();edge=body.top() if self.below else body.bottom()
        arrow.moveTo(self.tip_x-4,edge);arrow.lineTo(self.tip_x,edge-4 if self.below else edge+4)
        arrow.lineTo(self.tip_x+4,edge);arrow.closeSubpath();shape=shape.united(arrow)
        self.paint_shell(p,shape)
        p.setFont(ui_font(13,True));p.setPen(QColor(theme_color(INK)))
        if self.subtitle:
            p.drawText(body.adjusted(10,4,-10,-body.height()+23),Qt.AlignmentFlag.AlignVCenter,self.title)
            p.setPen(QColor(theme_color(BORDER)));p.drawLine(QPointF(10,body.top()+26),QPointF(body.right()-10,body.top()+26))
            p.setFont(ui_font(12));p.setPen(QColor(theme_color(MUTED)))
            p.drawText(body.adjusted(10,30,-10,-4),Qt.AlignmentFlag.AlignVCenter|Qt.TextFlag.TextWordWrap,self.subtitle)
        else:p.drawText(body,Qt.AlignmentFlag.AlignCenter,self.title)
        p.end()


def detail_size(host,height):
    normal_width=getattr(host.window(),'normal_card_width',None)
    width=normal_width() if normal_width else DETAIL_WIDTH
    area=host.screen().availableGeometry()
    return min(width,max(1,area.width()-4)),min(max(1,area.height()-4),max(DETAIL_MIN_HEIGHT,height))


def detail_position(host,anchor,size):
    from public_status import bubble_position
    card=host.window()
    return bubble_position(QRect(card.mapToGlobal(QPoint()),card.size()),anchor,size,host.screen().availableGeometry(),near_anchor=True)


class DetailHint(HintBubble):
    def paint_detail(self,painter,value):
        theme=palette()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(),Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if not self.apply_motion(painter):return None
        body=QRectF(1,1,self.width()-2,self.height()-2)
        self.paint_panel_shell(painter,body)
        painter.setBrush(QColor(theme['panel']));painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(body.adjusted(5,3,-5,-body.height()+28),6,6)
        title_font=ui_font(13,True);value_font=ui_font(16,True)
        width=max(0,self.width()-22)
        value_width=min(width,QFontMetrics(value_font).horizontalAdvance(value))
        title_width=max(0,width-value_width-(8 if value_width else 0))
        title=QFontMetrics(title_font).elidedText(self.title,Qt.TextElideMode.ElideRight,title_width)
        painter.setFont(title_font);painter.setPen(QColor(theme['ink']))
        painter.drawText(QRectF(11,6,title_width,21),Qt.AlignmentFlag.AlignVCenter,title)
        painter.setFont(value_font);painter.setPen(QColor(theme['accentText']))
        painter.drawText(QRectF(11+width-value_width,6,value_width,21),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,value)
        painter.setPen(QColor(theme['border']));painter.drawLine(11,30,self.width()-11,30)
        return theme


class HeaderHintBubble(DetailHint):
    comparison_value=None
    comparison_size=(DETAIL_WIDTH,DETAIL_MIN_HEIGHT)

    def hint_size(self):
        return super().hint_size() if self.comparison_value is None else self.comparison_size

    def paintEvent(self,event):
        if self.comparison_value is None:return super().paintEvent(event)
        painter=QPainter(self);theme=self.paint_detail(painter,self.comparison_value)
        if theme is None:return
        painter.setFont(ui_font(11));painter.setPen(QColor(theme['muted']))
        painter.drawText(QRectF(11,37,self.width()-22,self.height()-46),
                         Qt.AlignmentFlag.AlignTop|Qt.TextFlag.TextWordWrap,self.subtitle)


class HeaderHints(QObject):
    """Delay first entry, keep adjacent button changes and data refresh stable."""
    def __init__(self,bubble):
        super().__init__(bubble);self.popup=HeaderHintBubble();self.target=None;self.rebuilding=False;self.role=None;self._hold_hover_layout=False
        self.delay=QTimer(self);self.delay.setSingleShot(True);self.delay.setInterval(HOVER_DELAY_MS);self.delay.timeout.connect(self._show)
        self.leave=QTimer(self);self.leave.setSingleShot(True);self.leave.setInterval(60);self.leave.timeout.connect(self._finish_leave)
        self.watch=QTimer(self);self.watch.setInterval(100);self.watch.timeout.connect(self._check_hover)
        bubble.destroyed.connect(self.popup.deleteLater)

    def _target(self):
        value=self.target() if self.target else None
        try:return value if value is not None and value.isVisible() else None
        except RuntimeError:return None

    def dismiss(self,immediate=False):
        self.delay.stop();self.leave.stop();self.watch.stop();self.target=None;self.rebuilding=False;self.role=None;self._hold_hover_layout=False;self.popup.dismiss(immediate)

    def _hint(self,widget):
        detail=widget.property('quotaComparisonHint')
        if detail:return str(widget.property('quotaComparisonTitle') or '额度对照'),str(detail)
        return str(widget.property('headerActionHint') or '')[:4],''

    def refresh_target(self,widget):
        if not self.target or self.target() is not widget:return
        if not widget.isVisible() or not self._hint(widget)[0]:self.dismiss(True)
        elif self.popup.isVisible():self._show()

    def _check_hover(self):
        if self.rebuilding:return
        button=self._target()
        if button is None or not QRect(button.mapToGlobal(QPoint()),button.size()).contains(QCursor.pos()):
            if not self.leave.isActive():self.leave.start()

    def _finish_leave(self):
        button=self._target()
        if button is None or not QRect(button.mapToGlobal(QPoint()),button.size()).contains(QCursor.pos()):
            self.dismiss()

    def keep_hover_during_layout(self):
        button=self._target()
        if not self.popup.isVisible() or button is None:return False
        if not QRect(button.mapToGlobal(QPoint()),button.size()).contains(QCursor.pos()):return False
        self._hold_hover_layout=True;self.rebuilding=True;self.role=button.objectName()
        self.delay.stop();self.leave.stop()
        return True

    def settle_hover_layout(self):
        if not self._hold_hover_layout:return
        self._hold_hover_layout=False;self._restore_header()

    def preserve_for_rebuild(self):
        button=self._target();transition=getattr(self.parent(),'size_transition',None)
        if not self.popup.isVisible() or button is None or (transition and (transition.running or transition.preparing)):return
        self.role=button.objectName();self.rebuilding=True;self.leave.stop();self.delay.stop()
        QTimer.singleShot(0,self,self._restore_header)

    def _restore_header(self):
        if not self.rebuilding or self._hold_hover_layout:return
        self.rebuilding=False;role=self.role;self.role=None
        for button in self.parent().findChildren(QWidget):
            if not self._hint(button)[0]:continue
            if button.objectName()==role and button.isVisible() and QRect(button.mapToGlobal(QPoint()),button.size()).contains(QCursor.pos()):
                self.target=weakref.ref(button);self._show();return
        self.dismiss(True)

    def _show(self):
        if self._hold_hover_layout:return
        b=self.parent();button=self._target();transition=getattr(b,'size_transition',None)
        if button is None or not b.isVisible() or (transition and (transition.running or transition.preparing)):
            self.dismiss(True);return
        text,detail=self._hint(button)
        if not text:self.dismiss(True);return
        point=button.mapToGlobal(QPoint());anchor=QRect(point,button.size())
        report=getattr(b,'report',None)
        owner=report if report is not None and report.isVisible() else b
        self.popup.comparison_value=button.property('quotaComparisonValue')
        if self.popup.comparison_value is not None:
            width,_=detail_size(button,DETAIL_MIN_HEIGHT)
            flags=Qt.AlignmentFlag.AlignLeft|Qt.TextFlag.TextWordWrap
            height=QFontMetrics(ui_font(11)).boundingRect(QRect(0,0,max(1,width-22),1000),flags,detail).height()+46
            self.popup.comparison_size=detail_size(button,height)
            target=detail_position(button,anchor,self.popup.comparison_size)
            self.popup.present(text,detail,anchor,button.screen(),owner=owner,
                               topmost=bool(b.windowFlags()&Qt.WindowType.WindowStaysOnTopHint),geometry=target)
            self.watch.start()
            return
        top=anchor.top() if button.objectName().startswith('theme_dot_') else b.mapToGlobal(QPoint()).y()
        self.popup.present(text,detail,anchor,button.screen(),card_top=top,
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
        if obj is b:
            if kind in (QEvent.Type.Hide,QEvent.Type.Close):self.dismiss(True)
            elif kind in (QEvent.Type.Move,QEvent.Type.Resize) and not self.rebuilding and self.popup.isVisible():
                self.preserve_for_rebuild()
        if obj is not b and not b.isAncestorOf(obj):return False
        if kind==QEvent.Type.ToolTip:
            QToolTip.hideText();event.accept();return True
        if not self._hint(obj)[0]:return False
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
        self.menu=None;self.set_context_menu(tray.contextMenu())
        parent.destroyed.connect(self.popup.deleteLater)

    def set_context_menu(self,menu):
        if self.menu is menu:return
        if self.menu is not None:self.menu.aboutToShow.disconnect(self._menu_opening)
        self.menu=menu
        if menu is not None:menu.aboutToShow.connect(self._menu_opening)

    def _menu_opening(self):
        self.hovering=False;self.delay.stop();self.watch.stop();self.popup.dismiss(True)

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
