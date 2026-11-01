"""Equal footer, with a fixed right-hand unit and value-only fade."""
from PySide6.QtCore import Qt,QRectF,QRect,QPoint,QEvent,QVariantAnimation,QEasingCurve,QTimer
import time
from PySide6.QtGui import QPainter,QColor,QFontMetrics,QCursor
from PySide6.QtWidgets import QWidget,QToolTip
from compact_bubble import font,INK,MUTED
from theme_registry import color as theme_color
from live_rate import display
from settings_controls import motion_enabled,play_animation
from hover_hints import HintBubble
from theme_registry import palette
from datetime import datetime

class SessionRateBubble(HintBubble):
    def __init__(self):
        super().__init__();self.rows=[];self.total=None;self.scroll=0;self.limit=340
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput,False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,False)
    def hint_size(self):return 294,max(78,min(self.limit,45+len(self.rows)*38))
    def inspect(self,value,host):
        reopening=not self.isVisible();self.rows=list(value.get('details') or []);self.total=value.get('rate')
        if reopening:self.scroll=0
        self.limit=max(60,min(340,host.screen().availableGeometry().height()-6))
        owner=host.window();report=getattr(owner,'report',None)
        if report is not None and report.isVisible():owner=report
        anchor=QRect(host.mapToGlobal(QPoint()),host.size())
        topmost=bool(owner.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
        geometry=(anchor,host.screen().availableGeometry(),self.hint_size(),owner,topmost)
        # Sampling changes the rows, not the hover lifetime or its entry clock.
        if reopening or geometry!=getattr(self,'_placement',None):
            self.present('会话实时速率','',anchor,host.screen(),owner=owner,topmost=topmost)
            self._placement=geometry
        self.scroll=max(0,min(self.scroll,max(0,45+len(self.rows)*38-self.height())))
        self.setAccessibleDescription('\n'.join(str(r.get('name') or r.get('session'))+' '+display(r.get('rate'))+' tok/s' for r in self.rows));self.update()
    def wheelEvent(self,event):
        delta=event.pixelDelta().y() or event.angleDelta().y()/120*38
        self.scroll=max(0,min(self.scroll-delta,max(0,45+len(self.rows)*38-self.height())));self.update();event.accept()
    def paintEvent(self,event):
        p=QPainter(self);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source);p.fillRect(self.rect(),Qt.GlobalColor.transparent);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setOpacity(self.level);theme=palette();body=QRectF(1,5 if self.below else 1,self.width()-2,self.height()-6)
        p.setPen(QColor(theme['border']));p.setBrush(QColor(theme['surface']));p.drawRoundedRect(body,9,9)
        p.setFont(font(11,True));p.setPen(QColor(theme['ink']));p.drawText(body.adjusted(10,5,-10,-body.height()+26),Qt.AlignmentFlag.AlignVCenter,'会话实时速率')
        p.setFont(font(11));p.setPen(QColor(theme['accentText']));p.drawText(body.adjusted(125,5,-10,-body.height()+26),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,'合计 '+display(self.total)+' tok/s')
        p.save();p.setClipRect(body.adjusted(9,32,-9,-4))
        if not self.rows:
            p.setFont(font(11));p.setPen(QColor(theme['muted']));p.drawText(body.adjusted(10,32,-10,-4),Qt.AlignmentFlag.AlignVCenter,'等待会话输出和有效采样')
        for i,row in enumerate(self.rows):
            y=body.top()+33+i*38-self.scroll
            if y+38<33 or y>body.bottom():continue
            name=str(row.get('name') or '会话 '+str(row.get('session',''))[-8:])
            p.setFont(font(11));p.setPen(QColor(theme['ink']));name=QFontMetrics(p.font()).elidedText(name,Qt.TextElideMode.ElideRight,164)
            p.drawText(QRectF(11,y,164,18),Qt.AlignmentFlag.AlignVCenter,name)
            p.setFont(font(11,True));p.drawText(QRectF(174,y,self.width()-185,18),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,display(row.get('rate'))+' tok/s')
            stamp=row.get('sampled_at');interval=row.get('interval');status='等待新采样' if row.get('waiting') or row.get('rate') is None else '最近观测'
            detail=(datetime.fromtimestamp(stamp).strftime('%H:%M:%S')+'  ' if stamp else '')+status
            if interval is not None:detail+=f'  /  {interval:.0f}秒区间'
            p.setFont(font(10));p.setPen(QColor(theme['muted']));p.drawText(QRectF(11,y+17,self.width()-22,17),Qt.AlignmentFlag.AlignVCenter,detail)
        p.restore()

class LiveRateCard(QWidget):
    def __init__(self,value=None,parent=None):
        super().__init__(parent);self._rebuilding=False;self._layout_pending=False;self._pending_hint_ms=None
        self.setObjectName('live_output_rate');self.setFixedHeight(20);self.value={};self.alpha=1.
        self.animation=QVariantAnimation(self);self.animation.setDuration(180);self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._advance);self.set_data(value or {})
        self.expiry=QTimer(self);self.expiry.setSingleShot(True);self.expiry.timeout.connect(self._expire)
        self.popup=SessionRateBubble();self.destroyed.connect(self.popup.deleteLater)
        self.hint_delay=QTimer(self);self.hint_delay.setSingleShot(True);self.hint_delay.setInterval(500);self.hint_delay.timeout.connect(self._show_hint)
        self.hint_watch=QTimer(self);self.hint_watch.setInterval(100);self.hint_watch.timeout.connect(self._watch_hint)
        self.hint_leave=QTimer(self);self.hint_leave.setSingleShot(True);self.hint_leave.setInterval(180);self.hint_leave.timeout.connect(self._dismiss_if_outside)
        self.setToolTip('')
    def set_data(self,value):
        previous=display(self.value.get('rate'));self.value=dict(value or {});current=display(self.value.get('rate'))
        self.setAccessibleName('实时输出速率 '+current+' tok/s');self.animation.stop()
        if current!=previous and self.isVisible() and motion_enabled():
            self.alpha=.35;self.animation.setStartValue(.35);self.animation.setEndValue(1.);play_animation(self.animation)
        else:self.alpha=1.
        self.update()
        if hasattr(self,'expiry'):self._schedule()
        if hasattr(self,'popup') and self.popup.isVisible() and not self._rebuilding:self.popup.inspect(self.value,self)
    def _schedule(self):
        self.expiry.stop();expires=self.value.get('expires')
        if self.isVisible() and expires is not None:
            if expires<=time.monotonic():self._expire()
            else:self.expiry.start(max(1,round((expires-time.monotonic())*1000)+1))
    def _expire(self):
        details=[dict(r,rate=None if r.get('expires') is not None and r['expires']<=time.monotonic() else r.get('rate'),waiting=True) for r in self.value.get('details',[])]
        valid=[r for r in details if r.get('rate') is not None]
        self.value=dict(self.value,rate=sum(r['rate'] for r in valid) if valid else None,expires=min((r['expires'] for r in valid),default=None),details=details)
        self.animation.stop();self.alpha=1.;self.setAccessibleName('实时输出速率 '+display(self.value.get('rate'))+' tok/s');self.update();self._schedule()
        if hasattr(self,'popup') and self.popup.isVisible() and not self._rebuilding:self.popup.inspect(self.value,self)
    def _inside_card(self):return self.isVisible() and QRect(self.mapToGlobal(QPoint()),self.size()).contains(QCursor.pos())
    def _inside_hint(self):return self._inside_card() or (self.popup.isVisible() and self.popup.geometry().contains(QCursor.pos()))
    def _show_hint(self):
        if self._rebuilding:return
        transition=getattr(self.window(),'size_transition',None)
        if not self._inside_card() or (transition and (transition.preparing or transition.running)):
            self._hide_hint();return
        self.hint_leave.stop();self.popup.inspect(self.value,self);self.hint_watch.start()
    def _watch_hint(self):
        if self._rebuilding:return
        if not self.isVisible():self._hide_hint();return
        if self._inside_hint():self.hint_leave.stop()
        elif not self.hint_leave.isActive():self.hint_leave.start()
    def _dismiss_if_outside(self):
        if not self._rebuilding and not self._inside_hint():self._hide_hint()
    def begin_rebuild(self,preserve):
        """Detach from a disposable footer, retaining one popup and its clock."""
        if not self._rebuilding:
            self._pending_hint_ms=self.hint_delay.remainingTime() if preserve and self.hint_delay.isActive() else None
        if not preserve:self._hide_hint();self._pending_hint_ms=None
        self._rebuilding=True;self.hint_delay.stop();self.hint_watch.stop();self.hint_leave.stop()
        QTimer.singleShot(0,self,self._finish_rebuild)
    def _finish_rebuild(self):
        if not self._rebuilding:return
        self._rebuilding=False;pending=self._pending_hint_ms;self._pending_hint_ms=None
        if not self.isVisible():self._hide_hint();return
        if self.popup.isVisible():
            if not self._inside_hint():self._hide_hint();return
            self.popup.inspect(self.value,self);self.hint_watch.start()
        elif pending is not None and self._inside_card():self.hint_delay.start(max(1,pending))
    def _layout_changed(self):
        self._layout_pending=False
        if self._rebuilding or not hasattr(self,'popup') or not self.popup.isVisible():return
        if self.isVisible():self.popup.inspect(self.value,self)
        self._watch_hint()
    def _hide_hint(self):
        from shiboken6 import isValid
        if not hasattr(self,'popup'):return
        if isValid(self.hint_delay):self.hint_delay.stop()
        if isValid(self.hint_watch):self.hint_watch.stop()
        if isValid(self.hint_leave):self.hint_leave.stop()
        if isValid(self.popup) and isValid(self.popup.animation):self.popup.dismiss(True)
    def enterEvent(self,event):
        if not self._rebuilding:
            self.hint_leave.stop()
            if not self.popup.isVisible() and not self.hint_delay.isActive():self.hint_delay.start(500)
        super().enterEvent(event)
    def leaveEvent(self,event):
        if not self._rebuilding:
            self.hint_delay.stop()
            if self.popup.isVisible():self.hint_watch.start();self._watch_hint()
        super().leaveEvent(event)
    def event(self,event):
        if event.type()==QEvent.Type.ToolTip:QToolTip.hideText();event.accept();return True
        if event.type() in (QEvent.Type.Move,QEvent.Type.Resize) and not self._rebuilding and not self._layout_pending:
            self._layout_pending=True;QTimer.singleShot(0,self,self._layout_changed)
        return super().event(event)
    def showEvent(self,event):super().showEvent(event);self._schedule()
    def _advance(self,value):self.alpha=float(value);self.update()
    def hideEvent(self,event):
        if not self._rebuilding:self._hide_hint()
        self.animation.stop();self.expiry.stop();self.alpha=1.;super().hideEvent(event)
    def paintEvent(self,event):
        expanded=getattr(self,'expanded',False);height=self.height();margin=7 if expanded else 6
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#f5f2f7' if expanded else '#e8def0')));p.drawRoundedRect(QRectF(self.rect()),6,6)
        p.setFont(font(11 if expanded else 10));p.setPen(theme_color(MUTED));p.drawText(QRectF(margin,0,22,height),Qt.AlignmentFlag.AlignVCenter,'实时')
        if expanded:
            from typography import ui_font
            p.setFont(ui_font(10))
        unit='tok/s';unit_width=QFontMetrics(p.font()).horizontalAdvance(unit);unit_x=self.width()-margin-unit_width
        p.drawText(QRectF(unit_x,0,unit_width,height),Qt.AlignmentFlag.AlignVCenter,unit)
        p.setOpacity(self.alpha);p.setFont(font(11 if expanded else 12,not expanded));p.setPen(theme_color(INK));value=display(self.value.get('rate'))
        rect=QRectF(31,0,max(0,unit_x-35),height);self.number_rect=rect;self.unit_x=unit_x
        if QFontMetrics(p.font()).horizontalAdvance(value)>rect.width():p.setFont(font(10,True))
        p.drawText(rect,Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,value)
