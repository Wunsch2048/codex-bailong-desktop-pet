"""Shared spring/shape language for reports and inline disclosure cards."""
from settings_controls import play_animation
from theme_registry import color as theme_color
import math
from PySide6.QtCore import Qt,QRectF,QSize,QVariantAnimation,QEasingCurve,Signal
from PySide6.QtGui import QPainter,QPainterPath,QColor,QPen
from PySide6.QtWidgets import QWidget,QSizePolicy
from spring_motion import island_response,dismiss_progress,stage,EXPAND_MS,DISMISS_MS
from surface_morph import snapshot,PANEL_RADIUS
from ui_theme import SURFACE,BORDER


def card_geometry(bounds,progress,anchor='bottom',seed_height=32.):
    f=max(0.,float(progress));width_f=f+.035*math.sin(math.pi*min(1.,f))
    seed_width=min(132.,bounds.width());seed_height=min(seed_height,bounds.height())
    width=seed_width+(bounds.width()-seed_width)*width_f
    height=seed_height+(bounds.height()-seed_height)*f
    top=bounds.top() if anchor=='top' else bounds.bottom()-height
    return QRectF(bounds.center().x()-width/2,top,width,max(0.,height))


def paint_card(p,rect,frame,progress,background=SURFACE,inset=0.,content_progress=None):
    if progress<=0. or rect.height()<=0:return
    radius=min(rect.width()/2,rect.height()/2,20.+(PANEL_RADIUS-20.)*min(1.,progress))
    path=QPainterPath();path.addRoundedRect(rect,radius,radius)
    p.save();p.setOpacity(stage(progress,0.,.09));p.fillPath(path,QColor(theme_color(background)));p.setClipPath(path)
    if frame is not None and not frame.isNull():
        entry=stage(progress,.7,1.) if content_progress is None else content_progress
        size=frame.deviceIndependentSize();scale=.975+.025*entry
        w=min(size.width(),rect.width()-2*inset)*scale;h=size.height()*scale
        target=QRectF(rect.center().x()-w/2,rect.center().y()-h/2,max(0.,w),h)
        p.setOpacity(stage(progress,0.,.09)*entry);p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(target,frame,QRectF(frame.rect()))
    p.setClipping(False);p.setOpacity(stage(progress,0.,.09));p.setPen(QPen(QColor(theme_color(BORDER)),1));p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(rect.adjusted(.5,.5,-.5,-.5),radius,radius);p.restore()


class AnimatedDisclosure(QWidget):
    """Animate a child layout, never its containing native window.

    The live form stays intact; a single snapshot handles intermediate frames.
    A hidden ancestor settles the motion and releases its image immediately.
    """
    settled=Signal(bool)
    def __init__(self,body,parent=None,background=SURFACE):
        super().__init__(parent);self.body=body;body.setParent(self);self.background=background
        self.expanded=False;self.progress=0.;self._start=0.;self._target=0.;self.full_height=1;self._frame=None;self._animating=False;self._measuring=False
        # setFixedHeight changes maximumHeight. Remember the body's own limit
        # before measuring it, especially for capped text editors.
        self._body_height_limit=body.maximumHeight()
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.setFixedHeight(0);body.hide();self.hide()
        self.animation=QVariantAnimation(self);self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.valueChanged.connect(self._advance);self.animation.finished.connect(self._finish)
    def sizeHint(self):return QSize(200,round(self.full_height*self.progress))
    def _measure(self):
        if self._measuring:return
        self._measuring=True
        try:
            width=max(1,self.width()-28);self.body.setFixedWidth(width);self.body.ensurePolished()
            if self.body.layout():self.body.layout().activate()
            height=self.body.heightForWidth(width) if self.body.hasHeightForWidth() else self.body.sizeHint().height()
            self.body.setFixedHeight(max(1,min(height,self._body_height_limit)))
            self.body.move(14,8);self.full_height=self.body.height()+16
        finally:self._measuring=False
    def set_expanded(self,value):
        value=bool(value)
        if value==self.expanded and (self._animating or self.isVisible() or not value):return
        self.animation.stop();self.expanded=value;self._start=self.progress;self._target=1. if value else 0.;previous_height=self.full_height;self._measure()
        if not self.isVisible() and not value:self._finish();return
        visible=self.isVisible() or bool(self.parentWidget() and self.parentWidget().isVisible())
        if not visible:self.show();self._finish();return
        if self._frame is None or self.full_height!=previous_height:self._frame=snapshot(self.body)
        # Mark the snapshot phase before show() delivers the first Resize.
        # Otherwise resizeEvent can briefly restore the full live form before
        # the animation emits its first value (which may still be cached 0).
        self._animating=True;self.body.hide();self.setFixedHeight(round(self.full_height*self.progress));self.show()
        self._start=self.progress;self._target=1. if value else 0.
        blocked=self.animation.blockSignals(True)
        self.animation.setDuration(max(150,round((EXPAND_MS if value else DISMISS_MS)*min(1.,abs(self._target-self._start)))))
        self.animation.setCurrentTime(0);self.animation.blockSignals(blocked);self._advance(0.);play_animation(self.animation)
    def _advance(self,value):
        f=island_response(value) if self.expanded else dismiss_progress(value)
        self.progress=max(0.,self._start+(self._target-self._start)*f)
        self.setFixedHeight(min(self.full_height+8,max(0,round(self.full_height*self.progress))))
        self.update()
    def refresh_content(self):
        self._measure()
        if self._animating:self._frame=snapshot(self.body);self.setFixedHeight(round(self.full_height*self.progress));self.update()
        elif self.expanded:self.setFixedHeight(self.full_height)
    def _finish(self):
        enabled=self.updatesEnabled();self.setUpdatesEnabled(False)
        try:
            self._animating=False;self._frame=None;self.progress=1. if self.expanded else 0.
            self.setFixedHeight(self.full_height if self.expanded else 0);self.body.setVisible(self.expanded)
            if not self.expanded:self.hide()
        finally:self.setUpdatesEnabled(enabled)
        self.update();self.settled.emit(self.expanded)
    def complete(self):
        if self._animating:self.animation.setCurrentTime(self.animation.duration())
    def hideEvent(self,event):
        if self._animating:self.animation.stop();self._finish()
        super().hideEvent(event)
    def resizeEvent(self,event):
        if event.size().width()!=event.oldSize().width():
            self._measure()
            if self._animating:self._frame=snapshot(self.body)
            elif self.expanded:self.setFixedHeight(self.full_height)
        super().resizeEvent(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Keep the outgoing text visible while its card is still large. The
        # expanding curve delays its entrance, but using that same curve in
        # reverse left a conspicuous empty card through most of the collapse.
        content=stage(self.progress,.02,.28) if self._animating and not self.expanded else None
        paint_card(p,self.visual_rect(),self._frame if self._animating else None,self.progress,self.background,8.,content)
    def visual_rect(self):
        # Reserve six pixels on each side for the spring's widest pose. The
        # border must never be clipped by the child widget during its rebound.
        bounds=QRectF(6,0,max(1,self.width()-12),self.full_height)
        rect=card_geometry(bounds,min(self.progress,1+8/max(1,self.full_height)),'top',0.)
        rect.setHeight(self.height());return rect
