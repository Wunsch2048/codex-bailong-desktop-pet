"""Single-arc refresh action; repaint only its small vector while visible."""
from theme_registry import color as theme_color
import math
import time
from PySide6.QtCore import Qt,QPointF,QRectF,QTimer
from PySide6.QtGui import QColor,QIcon,QPainter,QPainterPath,QPen
from PySide6.QtWidgets import QToolButton,QStyle,QStyleOptionToolButton

REFRESH_SECONDS=2.0
BRAKE_SECONDS=.28
FEEDBACK_SECONDS=1.1
RESTORE_SECONDS=.2


class RefreshButton(QToolButton):
    def __init__(self,parent=None,clock=None):
        super().__init__(parent)
        self.clock=clock or time.monotonic
        self.busy=False;self.result=None;self.started=0.;self.finished_at=None
        self.finish_angle=0.;self.finish_scale=1.
        self._motion_offset=0.;self._hidden_at=self.clock();self._motion_holds={'hidden'}
        self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self._tick)

    def _motion_now(self):
        return (self._hidden_at if self._hidden_at is not None else self.clock())-self._motion_offset

    def set_busy(self,value):
        value=bool(value)
        if value==self.busy:return
        self.busy=value;self.result=None;self.finished_at=None
        if value:self.started=self._motion_now()
        self.setEnabled(not value);self._sync();self.update()

    def finish(self,success=True):
        angle,scale,_,_=self.pose()
        self.finish_angle=angle;self.finish_scale=scale
        self.busy=False;self.result='partial' if success=='partial' else bool(success);self.finished_at=self._motion_now()
        self.setEnabled(True);self._sync();self.update()

    def pose(self):
        from settings_controls import motion_enabled
        if not motion_enabled():return (0.,1.,0.,1.) if self.result is not None else (0.,1.,1.,0.)
        now=self._motion_now()
        if self.busy:
            t=max(0.,now-self.started)
            return (360*t/REFRESH_SECONDS, .975+.025*math.cos(math.tau*t/REFRESH_SECONDS),1.,0.)
        if self.finished_at is None:return (0.,1.,1.,0.)
        t=max(0.,now-self.finished_at)
        brake=min(t,BRAKE_SECONDS)
        angle=self.finish_angle+360/REFRESH_SECONDS*(brake-brake*brake/(2*BRAKE_SECONDS))
        mix=min(1.,t/BRAKE_SECONDS);mix=mix*mix*(3-2*mix)
        scale=self.finish_scale+(1-self.finish_scale)*mix
        if t<BRAKE_SECONDS:return (angle,scale,1-mix,mix)
        if t<BRAKE_SECONDS+FEEDBACK_SECONDS:return (angle,1.,0.,1.)
        mix=min(1.,(t-BRAKE_SECONDS-FEEDBACK_SECONDS)/RESTORE_SECONDS)
        mix=mix*mix*(3-2*mix)
        return (0.,1.,mix,1-mix)

    def _sync(self):
        if self.finished_at is not None and self._motion_now()-self.finished_at>=BRAKE_SECONDS+FEEDBACK_SECONDS+RESTORE_SECONDS:
            self.finished_at=None;self.result=None
        from settings_controls import motion_enabled
        running=motion_enabled() and self.isVisible() and not self._motion_holds and (self.busy or self.finished_at is not None)
        if running and not self.timer.isActive():self.timer.start()
        elif not running:self.timer.stop()

    def _tick(self):
        self._sync()
        if self.updatesEnabled():self.update()

    def motion_policy_changed(self):self._sync();self.update()

    def freeze_motion(self,reason='surface'):
        if not self._motion_holds:self._hidden_at=self.clock()
        self._motion_holds.add(reason);self.timer.stop()

    def resume_motion(self,reason='surface'):
        self._motion_holds.discard(reason)
        if not self._motion_holds and self._hidden_at is not None:
            self._motion_offset+=self.clock()-self._hidden_at;self._hidden_at=None
        self._sync()

    def showEvent(self,event):
        super().showEvent(event);self.resume_motion('hidden')

    def hideEvent(self,event):
        self.freeze_motion('hidden');super().hideEvent(event)

    def paintEvent(self,event):
        # Keep native hover/press/focus behavior without painting the static QIcon.
        option=QStyleOptionToolButton();self.initStyleOption(option);option.icon=QIcon()
        p=QPainter(self);self.style().drawComplexControl(QStyle.ComplexControl.CC_ToolButton,option,p,self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size=min(18,self.iconSize().width(),self.width()-6,self.height()-6)
        p.translate(self.width()/2,self.height()/2)
        if self.isDown():p.scale(.92,.92)
        p.scale(size/16,size/16)
        angle,scale,arrow_alpha,result_alpha=self.pose()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(theme_color('#75618d')),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        if arrow_alpha>.001:
            p.save();p.setOpacity(arrow_alpha);p.rotate(angle);p.scale(scale,scale);p.translate(-8,-8)
            path=QPainterPath(QPointF(13,4))
            path.cubicTo(8,-.5,1.3,3.6,2.5,9.4);path.cubicTo(3.8,15.6,12.2,16,14,11)
            p.drawPath(path)
            head=QPainterPath(QPointF(13,1));head.lineTo(13,5);head.lineTo(9,5);p.drawPath(head)
            p.restore()
        if result_alpha>.001:
            p.setOpacity(result_alpha);p.translate(-8,-8)
            if self.result is True:
                path=QPainterPath(QPointF(3,8));path.lineTo(6.4,11.3);path.lineTo(13,4.7);p.drawPath(path)
            else:
                color=QColor(theme_color('#9b7b4c' if self.result=='partial' else '#915e74'))
                p.setPen(QPen(color,1.65,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(8,3),QPointF(8,9))
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(theme_color(color));p.drawEllipse(QRectF(7.1,11.5,1.8,1.8))
