"""Quota rings and a switchable token-chart/reset card."""
from settings_controls import play_animation
from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
import calendar
import math
import time
from datetime import datetime
from PySide6.QtCore import Qt,QRectF,QPointF,QSize,Signal,QEvent,QVariantAnimation,QEasingCurve,QAbstractAnimation
from PySide6.QtGui import QPainter,QPen,QColor,QFontMetrics
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QToolButton,QToolTip,QStackedWidget
from compact_bubble import font,INK,MUTED,PURPLE,GREEN,AMBER,TRACK,FONT_CSS,Announcement,action_button
from reset_watch import account_reset_text,epoch,local_time,pending_reset,schedule_text,reset_has_priority
from token_calendar import compact_tokens

DASH_HEIGHT=102

def paint_deck_surface(p,rect):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    radius=10+max(0.,min(1.,(rect.height()-DASH_HEIGHT)/3))
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#f5f2f7')));p.drawRoundedRect(rect,radius,radius)

def ring_color(window):
    if window.get('remaining') is not None and window['remaining']<=15:return QColor(theme_color('#a37688'))
    return GREEN if window.get('name')=='一周' else PURPLE

from ring_widgets import QuotaRings

from token_charts import TokenChartCard
from choice_controls import ChoiceCombo

class ExpandedRangeChoice(ChoiceCombo):
    """The compact chart menu uses the same accessible in-card choice sheet."""
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font(10));p.setPen(theme_color(MUTED))
        p.drawText(QRectF(0,0,self.width()-13,self.height()),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,self.currentText())
        p.setPen(QPen(theme_color(MUTED),1.1));x=self.width()-7;y=self.height()/2
        p.drawLine(QPointF(x-2.5,y-1),QPointF(x,y+1.5));p.drawLine(QPointF(x,y+1.5),QPointF(x+2.5,y-1))

class DeckTabs(QWidget):
    """Move one selection pill, without moving controls or their layout."""
    def __init__(self):
        super().__init__();self.setFixedHeight(20);self.buttons={};self.page='tokens';self.pill=QRectF()
        self.animation=QVariantAnimation(self);self.animation.setDuration(180);self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.animation.valueChanged.connect(self._advance)
    def select(self,page,animate=True):
        self.layout().activate();self.page=page;target=QRectF(self.buttons[page].geometry())
        self.animation.stop();self._from=QRectF(self.pill);self._to=target
        if animate and self.isVisible() and not self.pill.isEmpty():play_animation(self.animation)
        else:self.pill=target;self.update()
        for key,button in self.buttons.items():button.setChecked(key==page)
    def _advance(self,f):
        a,z=self._from,self._to;old=self.pill
        self.pill=QRectF(a.x()+(z.x()-a.x())*f,z.y(),a.width()+(z.width()-a.width())*f,z.height())
        self.update(old.united(self.pill).adjusted(-1,-1,1,1).toAlignedRect())
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.buttons and self.animation.state()!=QAbstractAnimation.State.Running:self.select(self.page,False)
    def hideEvent(self,event):
        self.animation.stop()
        if self.buttons:self.pill=QRectF(self.buttons[self.page].geometry())
        super().hideEvent(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#eae3f1')));p.drawRoundedRect(self.pill,5,5)

class CardDeck(QWidget):
    selected=Signal(str)
    reset_details_requested=Signal()
    refresh_requested=Signal(str)
    token_range_changed=Signal(str)
    def __init__(self,page,snapshot,reset_snapshot,error,busy,parent=None,token_busy=False,token_range="all",expanded=False):
        super().__init__(parent);self.setObjectName('side_card_deck');self.setFixedHeight(105 if expanded else DASH_HEIGHT)
        self.expanded=expanded
        self.page=page;self.snapshot=snapshot;self.reset_snapshot=reset_snapshot;self.error=error;self.reset_busy=busy;self.token_busy=token_busy;self.token_range=token_range;self.pages={}
        layout=QVBoxLayout(self);layout.setContentsMargins(*(9,8,9,8) if expanded else (5,2,4,2));layout.setSpacing(0)
        tabs=DeckTabs();self.tabs=tabs;tabs.setFixedHeight(19 if expanded else 20);row=QHBoxLayout(tabs);row.setContentsMargins(0,0,0,0);row.setSpacing(1 if expanded else 3)
        for key,text in [('tokens','Token'),('reset','重置')]:
            button=QToolButton();button.setObjectName('card_'+key);button.setText(text);button.setCheckable(True);button.setChecked(page==key);button.setFocusPolicy(Qt.FocusPolicy.NoFocus);button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly);button.setFont(font(10 if expanded else 12,not expanded))
            button.setFixedSize(QFontMetrics(button.font()).horizontalAdvance(text)+10 if expanded else 45 if key=='tokens' else 35,19 if expanded else 20)
            button.setToolTip('Token用量柱状图与今日小时曲线' if key=='tokens' else ('有重置公告待落实，点击查看' if reset_has_priority(reset_snapshot) else '查看额外重置公告'))
            accent='#75618d'
            set_theme_style(button,'QToolButton{'+FONT_CSS+'font-size:'+('10' if expanded else '12')+'px;color:'+accent+';border:0;border-radius:5px;padding:1px;background:transparent;}QToolButton:hover:!checked{background:#f1ecf6;}')
            button.clicked.connect(lambda checked=False,k=key:self.selected.emit(k));row.addWidget(button,1);tabs.buttons[key]=button
        layout.addWidget(tabs)
        if expanded:
            self.range_menu=ExpandedRangeChoice();self.range_menu.setObjectName('expanded_token_range')
            for text,key in [('24h','day'),('全部','all'),('30天','30d'),('7天','7d')]:self.range_menu.addItem(text,key)
            self.range_menu.setCurrentIndex(self.range_menu.findData(token_range));self.range_menu.setFixedWidth(44);self.range_menu.setFixedHeight(19)
            self.range_menu.setAccessibleName('Token 图表时间范围')
            set_theme_style(self.range_menu,'QComboBox{'+FONT_CSS+'font-size:10px;color:#706879;border:0;background:transparent;padding:0;}QComboBox::drop-down{border:0;width:12px;}')
            self.range_menu.currentIndexChanged.connect(lambda _:self.token_range_changed.emit(self.range_menu.currentData()))
            row.addStretch(1);row.addWidget(self.range_menu)
        self.stack=QStackedWidget();self.stack.setFixedHeight(70 if expanded else 78);layout.addWidget(self.stack);self.set_page(page,False)
    def set_page(self,page,animate=True):
        self.page=page
        if page not in self.pages:
            content=Announcement(self.reset_snapshot,self.error,self.reset_busy,with_refresh=False,dense=True) if page=='reset' else TokenChartCard(self.snapshot,period=self.token_range,expanded=self.expanded)
            if page=='tokens':content.rangeChanged.connect(self.token_range_changed.emit)
            else:content.expand.connect(self.reset_details_requested.emit)
            content.setFixedHeight(70 if self.expanded else 78);self.pages[page]=content;self.stack.addWidget(content)
        self.content=self.pages[page];self.stack.setCurrentWidget(self.content);self.tabs.select(page,animate)
        if self.expanded:self.range_menu.setVisible(page=='tokens')
        if page=='tokens' and animate:self.content.plot.begin_reveal();self.content.plot.start_reveal()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_deck_surface(p,QRectF(self.rect()))
