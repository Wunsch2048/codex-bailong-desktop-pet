"""Compact service row and in-place detail on the existing realtime bubble."""
from html import escape
from datetime import datetime
from PySide6.QtCore import Qt,QRect,QRectF,QPoint,QPropertyAnimation,QEasingCurve,QEvent
from PySide6.QtGui import QPainter,QColor,QPen,QTextDocument
from compact_bubble import font
from theme_registry import palette
from public_status import shared,bubble_position,service_colors
from settings_controls import motion_enabled,play_animation

def service_bubble(Base):
    class SessionRateBubble(Base):
        def __init__(self,focusable=False):
            super().__init__();self.service=shared();self.service.changed.connect(self.status_changed)
            self.focusable=focusable
            if focusable:
                self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus,False)
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,False)
            self.page='sessions';self.host=None;self.doc=QTextDocument();self.detail_scroll=0;self._detail_key=None
            self.geometry_motion=QPropertyAnimation(self,b'geometry',self);self.geometry_motion.setDuration(200);self.geometry_motion.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.setMouseTracking(True)
        def hint_size(self):
            width=min(294,getattr(self,'width_limit',294));height=140 if len(self.rows)==2 else 64+max(1,len(self.rows))*38
            if self.page=='service':height=round(self.doc.size().height())+42
            return width,max(50,min(self.limit,height))
        def inspect(self,value,host,page=None):
            opening=not self.isVisible();self.host=host;self.rows=list(value.get('details') or []);self.total=value.get('rate')
            if opening:self.page=page or 'sessions';self.scroll=0;self.detail_scroll=0
            elif page is not None:self.page=page
            area=host.screen().availableGeometry();self.limit=max(50,min(340,area.height()-4));self.width_limit=max(50,min(294,area.width()-4))
            self.prepare_document();owner=host.window();report=getattr(owner,'report',None)
            if report is not None and report.isVisible():owner=report
            anchor=QRect(host.mapToGlobal(QPoint()),host.size());card=QRect(host.window().mapToGlobal(QPoint()),host.window().size())
            target=bubble_position(card,anchor,self.hint_size(),area);topmost=bool(owner.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
            # Native flags/transient ownership are a hover-lifetime decision.
            # Reapplying them to an already visible Tool can hide its HWND.
            previous=getattr(self,'_placement',None)
            if not opening and previous is not None:
                from shiboken6 import isValid
                if isValid(previous[1]):owner,topmost=previous[1:]
            placement=(target,owner,topmost)
            if opening or placement!=getattr(self,'_placement',None):
                old=self.geometry();self.geometry_motion.stop()
                previous=getattr(self,'_placement',None)
                if opening:
                    self.present('服务状态' if self.focusable else '会话实时速率','',anchor,host.screen(),owner=owner,topmost=topmost,geometry=target,initial_level=1.)
                elif previous is None or previous[1:]!=placement[1:]:
                    self.present(self.title,'',anchor,host.screen(),owner=owner,topmost=topmost,geometry=old)
                self.below=False
                if not opening and motion_enabled():
                    self.geometry_motion.setStartValue(old);self.geometry_motion.setEndValue(target);play_animation(self.geometry_motion)
                else:self.setGeometry(target)
                self._placement=placement
            self.scroll=max(0,min(self.scroll,max(0,64+len(self.rows)*38-self.height())))
            self.update();self.service.request()
            if opening and self.focusable:self.activateWindow();self.setFocus()
        def status_changed(self,value):
            self._detail_key=None
            if self.host is not None and self.isVisible():self.inspect(dict(details=self.rows,rate=self.total),self.host)
        def prepare_document(self):
            theme=palette();value=self.service.value;key=(str(value),theme,self.width_limit)
            if key==self._detail_key:return
            self._detail_key=key;tone=value['tone'];ink,dot=service_colors(theme,tone)
            previous=value.get('previous');checked=value.get('checked');stamp=datetime.fromtimestamp(checked).strftime('%H:%M') if checked else '未更新'
            text=f'<h3 style="color:{ink}">{escape(value["title"])}</h3><p style="color:{theme["muted"]}">公开服务状态　{stamp}</p>'
            if previous:text+='<p>上次记录 '+datetime.fromtimestamp(previous['checked']).strftime('%m/%d %H:%M')+' '+escape(previous['title'])+'</p>'
            incidents=value.get('incidents',[])
            for row in incidents:text+='<h4>'+escape(row['name'])+'</h4><p>'+escape(row['body']).replace('\n','<br>')+'</p>'
            if not incidents and tone=='ok':text+='<p>公开状态页未报告异常。</p>'
            text+='<p style="color:'+theme['muted']+'">公开状态与本机会话速率分别统计。这里可查看服务进展，具体会话表现见速率列表。</p><p style="color:'+theme['muted']+'">来源 status.openai.com</p>'
            self.doc.setDefaultFont(font(11));self.doc.setDefaultStyleSheet('body{color:'+theme['ink']+'}h3{font-size:12px;font-weight:600;margin:5px 0}h4{font-size:11px;margin:8px 0 3px}p{margin:5px 0;line-height:135%}')
            self.doc.setHtml('<body>'+text+'</body>');self.doc.setTextWidth(self.width_limit-22)
        def wheelEvent(self,event):
            if self.page=='sessions':super().wheelEvent(event);return
            delta=event.pixelDelta().y() or event.angleDelta().y()/120*38
            self.detail_scroll=max(0,min(self.detail_scroll-delta,max(0,self.doc.size().height()-self.height()+39)));self.update();event.accept()
        def mouseReleaseEvent(self,event):
            if event.button()!=Qt.MouseButton.LeftButton:return
            if not self.focusable:return
            if self.page=='sessions' and event.position().y()>=self.height()-29:self.page='service';self.detail_scroll=0
            elif self.page=='service' and event.position().y()<30:
                if event.position().x()>self.width()-30:self.dismiss(True);return
                self.page='sessions'
            else:return
            if self.host:self.inspect(dict(details=self.rows,rate=self.total),self.host)
        def hideEvent(self,event):
            self.geometry_motion.stop();super().hideEvent(event)
        def event(self,event):
            if event.type()==QEvent.Type.WindowDeactivate and getattr(self,'focusable',False):self.dismiss(True)
            return super().event(event)
        def paintEvent(self,event):
            if self.page=='sessions':
                super().paintEvent(event)
                p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setOpacity(self.level);theme=palette();y=self.height()-29
                p.fillRect(QRectF(2,y,self.width()-4,23),QColor(theme['surface']));p.setPen(QColor(theme['border']));p.drawLine(10,y,self.width()-10,y)
                value=self.service.value;ink,dot=service_colors(theme,value['tone']);p.setFont(font(11));p.setPen(QColor(theme['muted']));p.drawText(11,y+18,'服务')
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(dot));p.drawEllipse(QRectF(43,y+10,5,5));p.setPen(QColor(ink));p.drawText(54,y+18,value['title'])
                checked=value.get('checked');stamp=datetime.fromtimestamp(checked).strftime('%H:%M') if checked else '未更新'
                p.setPen(QColor(theme['muted']));p.drawText(QRectF(self.width()-80,y+2,69,22),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,stamp+(' ›' if self.focusable else ''));return
            theme=palette();p=QPainter(self);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source);p.fillRect(self.rect(),Qt.GlobalColor.transparent);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver);p.setOpacity(self.level);p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QColor(theme['border']));p.setBrush(QColor(theme['surface']));p.drawRoundedRect(QRectF(1,1,self.width()-2,self.height()-2),9,9)
            p.setFont(font(11));p.setPen(QColor(theme['accentText']));p.drawText(11,21,'‹ 会话速率');p.drawText(self.width()-23,21,'×')
            p.setClipRect(QRectF(10,29,self.width()-20,self.height()-35));p.translate(10,29-self.detail_scroll);self.doc.drawContents(p)
    return SessionRateBubble
