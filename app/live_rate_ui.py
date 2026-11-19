"""Equal footer, with a fixed right-hand unit and directional numeric roll."""
from PySide6.QtCore import Qt,QRectF,QRect,QPoint,QEvent,QTimer
import time
from PySide6.QtGui import QPainter,QColor,QFontMetrics,QFontMetricsF,QCursor
from PySide6.QtWidgets import QWidget,QToolTip
from compact_bubble import font,INK,MUTED
from theme_registry import color as theme_color
from live_rate import display,summarize_rates
from hover_hints import DetailHint,detail_size,detail_position
from public_status import shared,service_colors
from ui_theme import status_footer_path

class SessionRateBubble(DetailHint):
    def __init__(self):
        super().__init__();self.rows=[];self.total=None;self.scroll=0;self.size_limit=(294,340)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput,False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,False)
        self.service=shared();self.service.changed.connect(self.status_changed)

    def hint_size(self):return self.size_limit
    def status_changed(self,value):
        if self.isVisible():self.update()
    def inspect(self,value,host):
        opening=not self.isVisible()
        self.rows=list(value.get('details') or []);self.total=value.get('rate')
        if opening:self.scroll=0
        self.size_limit=detail_size(host,min(340,64+max(1,len(self.rows))*self.row_height()))
        owner=host.window();report=getattr(owner,'report',None)
        if report is not None and report.isVisible():owner=report
        anchor=QRect(host.mapToGlobal(QPoint()),host.size());screen=host.screen()
        topmost=bool(owner.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
        previous=getattr(self,'_placement',None)
        if not opening and previous:
            from shiboken6 import isValid
            if isValid(previous[-2]):owner,topmost=previous[-2:]
        target=detail_position(host,anchor,self.size_limit)
        placement=(target,anchor,owner,topmost)
        if opening or placement!=previous:
            self.present('会话实时速率','',anchor,screen,owner=owner,topmost=topmost,geometry=target)
            self._placement=placement
        self.scroll=max(0,min(self.scroll,self.scroll_limit()))
        self.setAccessibleDescription('\n'.join(str(r.get('name') or r.get('session'))+' '+display(r.get('rate'))+' tok/s' for r in self.rows))
        self.update()
        if opening:self.service.request()
    def wheelEvent(self,event):
        delta=event.pixelDelta().y() or event.angleDelta().y()/120*self.row_height()
        self.scroll=max(0,min(self.scroll-delta,self.scroll_limit()));self.update();event.accept()
    def row_height(self):return 25
    def scroll_limit(self):return max(0,64+len(self.rows)*self.row_height()-self.height())
    def paintEvent(self,event):
        p=QPainter(self);recent=self.total is not None and summarize_rates(self.rows)['recent']
        theme=self.paint_detail(p,('刚刚输出 ' if recent else '合计 ')+display(self.total)+' tok/s')
        if theme is None:return
        content=QRectF(11,33,max(0,self.width()-22),max(0,self.height()-63))
        p.save();p.setClipRect(content,Qt.ClipOperation.IntersectClip)
        if not self.rows:
            p.setFont(font(11));p.setPen(QColor(theme['muted']))
            text=QFontMetrics(p.font()).elidedText('等待会话输出和有效采样',Qt.TextElideMode.ElideRight,int(content.width()))
            p.drawText(content,Qt.AlignmentFlag.AlignVCenter,text)
        for i,row in enumerate(self.rows):
            y=content.top()+i*self.row_height()-self.scroll
            if y+self.row_height()<content.top() or y>content.bottom():continue
            name=str(row.get('name') or '会话 '+str(row.get('session',''))[-8:])
            if row.get('recent'):name='刚刚  '+name
            width=max(10,self.width()-124)
            p.setFont(font(12));p.setPen(QColor(theme['ink']));name=QFontMetrics(p.font()).elidedText(name,Qt.TextElideMode.ElideRight,width)
            p.drawText(QRectF(11,y,width,18),Qt.AlignmentFlag.AlignVCenter,name)
            p.setFont(font(13,True));p.drawText(QRectF(width+14,y,self.width()-width-25,18),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,display(row.get('rate'))+' tok/s')
        p.restore()
        y=self.height()-29
        p.setPen(QColor(theme['border']));p.drawLine(10,y,self.width()-10,y)
        value=self.service.value;ink,dot=service_colors(theme,value['tone'])
        p.setFont(font(11));p.setPen(QColor(theme['muted']));p.drawText(11,y+18,'服务')
        p.setFont(font(12,True))
        center=y+18+QFontMetricsF(p.font(),p.device()).tightBoundingRect(value['title']).center().y()+.5
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(dot));p.drawEllipse(QRectF(43,center-2.5,5,5))
        p.setPen(QColor(ink));p.drawText(54,y+18,value['title'])

class LiveRateCard(QWidget):
    def __init__(self,value=None,parent=None):
        super().__init__(parent);self._hover_trace=__import__('collections').deque(maxlen=240);self._hover_origin=time.monotonic();self._trace_paint_at=0.;self._last_inside=None;self._rebuilding=False;self._layout_pending=False;self._pending_hint_ms=None
        self._pending_leave_until=None;self._rebuild_ticket=0;self._hold_hover_layout=False
        self.setObjectName('live_output_rate');self.setFixedHeight(20);self.value={};self.alpha=1.
        from number_roll import NumberRoll
        self.roll=NumberRoll(self,digits=True,allow_decrease=True);self.animation=self.roll.animation;self.set_data(value or {})
        self.expiry=QTimer(self);self.expiry.setSingleShot(True);self.expiry.timeout.connect(self._expire)
        self.popup=SessionRateBubble();self.destroyed.connect(self.popup.deleteLater)
        self.popup.installEventFilter(self)
        self.hint_delay=QTimer(self);self.hint_delay.setSingleShot(True);self.hint_delay.setInterval(500);self.hint_delay.timeout.connect(self._show_hint)
        self.hint_watch=QTimer(self);self.hint_watch.setInterval(100);self.hint_watch.timeout.connect(self._watch_hint)
        self.hint_leave=QTimer(self);self.hint_leave.setSingleShot(True);self.hint_leave.setInterval(180);self.hint_leave.timeout.connect(self._dismiss_if_outside)
        self.setToolTip('')
    def _trace_hover(self,event,**extra):
        if not hasattr(self,'popup'):return
        mouse=QCursor.pos();rect=QRect(self.mapToGlobal(QPoint()),self.size());pop=self.popup
        self._hover_trace.append(dict(ms=round((time.monotonic()-self._hover_origin)*1000),event=event,
            visible=self.isVisible(),rebuilding=self._rebuilding,card=[rect.x(),rect.y(),rect.width(),rect.height()],
            mouse=[mouse.x(),mouse.y()],popupVisible=pop.isVisible(),popup=[pop.x(),pop.y(),pop.width(),pop.height()],
            alpha=round(pop.level,3),insideCard=rect.contains(mouse),insidePopup=pop.geometry().contains(mouse),**extra))
    def hover_diagnostics(self):
        return dict(capacity=240,events=list(self._hover_trace))
    def eventFilter(self,obj,event):
        if obj is getattr(self,'popup',None):
            watched={QEvent.Type.Show:'popup-show',QEvent.Type.Hide:'popup-hide',QEvent.Type.Move:'popup-move',QEvent.Type.Resize:'popup-resize',QEvent.Type.WindowDeactivate:'popup-deactivate'}
            if event.type() in watched:self._trace_hover(watched[event.type()])
            elif event.type()==QEvent.Type.Paint and time.monotonic()-self._trace_paint_at>.1:
                self._trace_paint_at=time.monotonic();self._trace_hover('popup-paint')
        return super().eventFilter(obj,event)
    def set_data(self,value):
        previous=display(self.value.get('rate'));self.value=dict(value or {});current=display(self.value.get('rate'))
        self.setAccessibleName(self._rate_label()+'输出速率 '+current+' tok/s');self.alpha=1.
        self.roll.set(current,self.value.get('rate'),animate=self.isVisible())
        self.update()
        if hasattr(self,'expiry'):self._schedule()
        if hasattr(self,'popup') and self.popup.isVisible() and not self._rebuilding:self.popup.inspect(self.value,self)
    def _schedule(self):
        self.expiry.stop();expires=self.value.get('expires')
        if self.isVisible() and expires is not None:
            if expires<=time.monotonic():self._expire()
            else:self.expiry.start(max(1,round((expires-time.monotonic())*1000)+1))
    def _rate_label(self):
        return '刚刚' if self.value.get('recent') else '实时'
    def _expire(self):
        now=time.monotonic();details=[]
        for row in self.value.get('details',[]):
            expires=row.get('expires')
            if expires is None or expires>now:
                details.append(row)
            elif not row.get('recent'):
                details.append(dict(row,rate=None,expires=None,waiting=True))
        self.set_data(dict(self.value,**summarize_rates(details)))
    def _inside_card(self):return self.isVisible() and QRect(self.mapToGlobal(QPoint()),self.size()).contains(QCursor.pos())
    def _inside_hint(self):return self._inside_card() or (self.popup.isVisible() and self.popup.geometry().contains(QCursor.pos()))
    def keep_hover_during_layout(self):
        if not self.popup.isVisible() or not self._inside_hint():return False
        self._hold_hover_layout=True
        self.hint_watch.stop();self.hint_leave.stop()
        return True
    def settle_hover_layout(self):
        if not self._hold_hover_layout:return
        self._hold_hover_layout=False
        if self._rebuilding:self._finish_rebuild()
        elif self.isVisible():
            self._layout_changed();self.hint_watch.start()
        else:self._hide_hint()

    def _show_hint(self):
        self._trace_hover('show-request')
        if self._rebuilding or self._hold_hover_layout:return
        transition=getattr(self.window(),'size_transition',None)
        if transition and (transition.preparing or transition.running):
            self._hide_hint();return
        # A queued show belongs to the same hover lifetime. Once opened, the
        # pointer may already be over the interactive popup, outside the footer.
        if self.popup.isVisible():
            self._watch_hint()
            if self._inside_hint():self.popup._animate(1.);self.popup.inspect(self.value,self)
            return
        if not self._inside_card():self._hide_hint();return
        self.hint_leave.stop();self.popup.inspect(self.value,self);self.hint_watch.start()
    def _watch_hint(self):
        if self._hold_hover_layout:return
        inside=self._inside_hint()
        if inside!=self._last_inside:self._last_inside=inside;self._trace_hover('pointer-boundary',inside=inside)
        if self._rebuilding:return
        if not self.isVisible():self._hide_hint();return
        if self._inside_hint():self.hint_leave.stop()
        elif not self.hint_leave.isActive():self.hint_leave.start()
    def _dismiss_if_outside(self):
        if not self._rebuilding and not self._hold_hover_layout and not self._inside_hint():self._hide_hint(animated=True)
    def begin_rebuild(self,preserve):
        """Detach from a disposable footer, retaining one popup and its clock."""
        preserve=preserve or self._hold_hover_layout
        self._trace_hover('rebuild',preserve=bool(preserve))
        if not self._rebuilding:
            self._pending_hint_ms=self.hint_delay.remainingTime() if preserve and self.hint_delay.isActive() else None
            self._pending_leave_until=time.monotonic()+max(0,self.hint_leave.remainingTime())/1000 if preserve and self.hint_leave.isActive() else None
        if not preserve:self._hide_hint();self._pending_hint_ms=None
        self._rebuilding=True;self.hint_delay.stop();self.hint_watch.stop();self.hint_leave.stop()
        self._rebuild_ticket+=1;ticket=self._rebuild_ticket
        QTimer.singleShot(0,self,lambda:self._finish_rebuild(ticket))
    def _finish_rebuild(self,ticket=None):
        if self._hold_hover_layout or not self._rebuilding or ticket is not None and ticket!=self._rebuild_ticket:return
        self._rebuilding=False;pending=self._pending_hint_ms;self._pending_hint_ms=None
        leave_until=self._pending_leave_until;self._pending_leave_until=None
        if not self.isVisible():self._hide_hint();return
        if self.popup.isVisible():
            self.popup.inspect(self.value,self);self.hint_watch.start()
            if self._inside_hint():self.hint_leave.stop()
            elif leave_until is not None:
                remaining=round((leave_until-time.monotonic())*1000)
                if remaining<=0:self._dismiss_if_outside()
                else:self.hint_leave.start(max(1,remaining))
            else:self._watch_hint()
        elif pending is not None and self._inside_card():self.hint_delay.start(max(1,pending))
    def _layout_changed(self):
        self._layout_pending=False
        if self._hold_hover_layout or self._rebuilding or not hasattr(self,'popup') or not self.popup.isVisible():return
        if self.isVisible():self.popup.inspect(self.value,self)
        self._watch_hint()
    def _hide_hint(self,animated=False):
        from shiboken6 import isValid
        if not hasattr(self,'popup'):return
        self._trace_hover('dismiss',caller=__import__('sys')._getframe(1).f_code.co_name)
        self._rebuild_ticket+=1;self._pending_leave_until=None;self._hold_hover_layout=False
        if isValid(self.hint_delay):self.hint_delay.stop()
        if isValid(self.hint_watch):self.hint_watch.stop()
        if isValid(self.hint_leave):self.hint_leave.stop()
        if isValid(self.popup) and isValid(self.popup.animation):self.popup.dismiss(not animated)
    def enterEvent(self,event):
        if not self._rebuilding:
            self.hint_leave.stop()
            if self.popup.isVisible():
                self.popup._animate(1.);self.hint_watch.start()
            elif not self.hint_delay.isActive():self.hint_delay.start(500)
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
        if not self._rebuilding:
            # setWindowFlags and footer reparenting can hide/show within one
            # GUI transaction. Confirm visibility after that transaction instead
            # of destroying the hover lifetime on its temporary Hide event.
            QTimer.singleShot(0,self,self._confirm_hidden)
        if not self.roll.rebuilding:self.roll.snap()
        self.expiry.stop();self.alpha=1.;super().hideEvent(event)
    def _confirm_hidden(self):
        if not self._hold_hover_layout and not self._rebuilding and not self.isVisible():
            self._hide_hint()
    def paintEvent(self,event):
        expanded=getattr(self,'expanded',False);height=self.height();margin=7 if expanded else 6
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#f5f2f7' if expanded else '#e8def0')))
        p.drawPath(status_footer_path(QRectF(self.rect()),side=-1,alignment=0. if expanded else 1.))
        p.setFont(font(11 if expanded else 10));p.setPen(theme_color(MUTED));p.drawText(QRectF(margin,0,22,height),Qt.AlignmentFlag.AlignVCenter,'实时')
        if expanded:
            from typography import ui_font
            p.setFont(ui_font(10))
        unit='tok/s';unit_width=QFontMetrics(p.font()).horizontalAdvance(unit);unit_x=self.width()-margin-unit_width
        p.drawText(QRectF(unit_x,.5,unit_width,height),Qt.AlignmentFlag.AlignVCenter,unit)
        p.setOpacity(self.alpha);p.setFont(font(11 if expanded else 12,not expanded));p.setPen(theme_color(MUTED if self.value.get('recent') else INK));value=display(self.value.get('rate'))
        rect=QRectF(31,1,max(0,unit_x-35),height);self.number_rect=rect;self.unit_x=unit_x
        if QFontMetrics(p.font()).horizontalAdvance(value)>rect.width():p.setFont(font(10,True))
        self.roll.paint(p,rect)
