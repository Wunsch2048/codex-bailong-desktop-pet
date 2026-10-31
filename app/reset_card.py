"""One countdown visual for the small reset deck and expanded details."""
from theme_registry import color as theme_color
import math
import time
from PySide6.QtCore import Qt,QRectF,QPointF,QTimer,QUrl,Signal
from PySide6.QtGui import QPainter,QPen,QColor,QFontMetrics,QDesktopServices
from PySide6.QtWidgets import QWidget
from typography import ui_font
from ui_theme import INK,MUTED,PRIMARY,SELECTED,PANEL,DANGER
from reset_presentation import reset_view
from reset_watch import SOURCE_URL

class ResetCard(QWidget):
    refresh_requested=Signal()
    expand=Signal()
    def __init__(self,snapshot,error,busy=False,parent=None,with_refresh=True,dense=False,clock=None):
        super().__init__(parent);self.snapshot=snapshot;self.error=error;self.dense=dense;self.clock=clock or time.time
        self.setObjectName('reset_countdown');self.setFixedHeight(78 if dense else 96)
        self.hovered=False;self.pressed=False;self.focus_visible=False;self.view={};self.refresh_button=None;self.source_button=None
        self.setCursor(Qt.CursorShape.PointingHandCursor if dense else Qt.CursorShape.ArrowCursor)
        if dense:self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.refresh_time)
        if with_refresh or dense:
            from compact_bubble import action_button
        if dense:
            self.source_button=action_button('external','打开 Codex Resets 公告网站',parent=self,keyboard=True)
            self.source_button.setObjectName('reset_source')
            self.source_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(SOURCE_URL)))
        if with_refresh:
            self.refresh_button=action_button('refresh','刷新重置公告',parent=self);self.refresh_button.setObjectName('reset_refresh')
            self.refresh_button.setEnabled(not busy);self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.refresh_time()
    def refresh_time(self):
        fresh=reset_view(self.snapshot,self.error,self.clock());changed=any(fresh[k]!=self.view.get(k) for k in fresh if k!='next_change');self.view=fresh
        if changed:
            self.setAccessibleName(fresh['title']+'；'+fresh['eyebrow']+' '+fresh['display']+('；点击查看公告详情' if self.dense else ''))
            self.setAccessibleDescription(fresh['description']);self.setToolTip(fresh['description']);self.update()
        self.timer.stop()
        if self.isVisible() and fresh['next_change'] is not None:
            self.timer.start(max(25,min(60000,math.ceil(fresh['next_change']*1000))))
    def showEvent(self,event):super().showEvent(event);self.refresh_time()
    def hideEvent(self,event):self.timer.stop();self.hovered=False;self.pressed=False;super().hideEvent(event)
    def resizeEvent(self,event):
        if self.source_button:self.source_button.move(max(0,self.width()-22),self.height()-22)
        if self.refresh_button:self.refresh_button.move(max(0,self.width()-22),0)
        super().resizeEvent(event)
    def note_layout(self):
        left=5 if self.dense else 0
        width=self.width()-left-(24 if self.source_button else 4 if self.dense else 0)
        text=self.view['note']
        if self.dense and self.view['phase']=='scheduled' and text.startswith('最晚 '):text=text[3:]
        return text,QRectF(left,56 if self.dense else 73,max(1,width),18)
    def enterEvent(self,event):
        if self.dense:self.hovered=True;self.update()
        super().enterEvent(event)
    def leaveEvent(self,event):self.hovered=False;self.pressed=False;self.update();super().leaveEvent(event)
    def mousePressEvent(self,event):
        if self.dense and event.button()==Qt.MouseButton.LeftButton:self.pressed=True;self.update();event.accept()
        else:super().mousePressEvent(event)
    def mouseReleaseEvent(self,event):
        clicked=self.pressed and event.button()==Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint())
        self.pressed=False;self.update()
        if clicked:self.expand.emit();event.accept()
        else:super().mouseReleaseEvent(event)
    def keyPressEvent(self,event):
        if self.dense and event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space):self.expand.emit();event.accept()
        else:super().keyPressEvent(event)
    def focusInEvent(self,event):
        self.focus_visible=event.reason() in (Qt.FocusReason.TabFocusReason,Qt.FocusReason.BacktabFocusReason,Qt.FocusReason.ShortcutFocusReason)
        self.update();super().focusInEvent(event)
    def focusOutEvent(self,event):self.focus_visible=False;self.update();super().focusOutEvent(event)
    def text_runs(self):
        """Fit hours and minutes on one baseline; compact labels keep digits large."""
        v=self.view;left=5 if self.dense else 0;available=max(1,self.width()-left-(4 if self.dense else 0))
        value_size=28 if self.dense and v['unit'] else 19 if self.dense else 36 if v['unit'] else 27
        parts=[(number,{'小时':'时','分钟':'分'}.get(label,label) if self.dense and len(v['parts'])>1 else label) for number,label in v['parts']]
        unit_font=ui_font(11 if self.dense else 13,True);gap=2 if len(parts)>1 else 4 if v['unit'] else 0
        def width(size):
            fm=QFontMetrics(ui_font(size,True));um=QFontMetrics(unit_font)
            return sum(fm.horizontalAdvance(number)+(gap+um.horizontalAdvance(label) if label else 0) for number,label in parts)+gap*(len(parts)-1)
        while value_size>12 and width(value_size)>available:value_size-=1
        value_font=ui_font(value_size,True)
        baseline=46 if self.dense else 57
        runs=[];x=left
        for number,label in parts:
            runs.append((number,value_font,QPointF(x,baseline)));x+=QFontMetrics(value_font).horizontalAdvance(number)
            if label:
                x+=gap;runs.append((label,unit_font,QPointF(x,baseline)));x+=QFontMetrics(unit_font).horizontalAdvance(label)
            x+=gap
        return tuple(runs)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.dense and (self.hovered or self.pressed or self.focus_visible):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme_color(SELECTED if self.pressed else PANEL)));p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),7,7)
        v=self.view;left=5 if self.dense else 0;available=max(1,self.width()-left-(4 if self.dense else 0))
        p.setFont(ui_font(10 if self.dense else 11,True));p.setPen(QColor(theme_color(MUTED)))
        reserved=22 if self.refresh_button else 0
        title='预计最晚还有' if self.dense and v['phase']=='scheduled' and v['eyebrow']=='预计还有' else v['eyebrow']
        eyebrow=QFontMetrics(p.font()).elidedText(title,Qt.TextElideMode.ElideRight,int(available-reserved))
        p.drawText(QRectF(left,0,available-reserved,19),Qt.AlignmentFlag.AlignVCenter,eyebrow)
        p.setPen(QColor(theme_color(DANGER if v['phase'] in ('pending','unavailable') else INK)))
        for text,face,point in self.text_runs():p.setFont(face);p.drawText(point,text)
        p.setFont(ui_font(10 if self.dense else 11,True));p.setPen(QColor(theme_color(MUTED)))
        detail_note,note_rect=self.note_layout()
        if not self.dense and v['phase']=='scheduled':detail_note+=' 北京时间'
        note=QFontMetrics(p.font()).elidedText(detail_note,Qt.TextElideMode.ElideRight,int(note_rect.width()))
        p.drawText(note_rect,Qt.AlignmentFlag.AlignVCenter,note)
