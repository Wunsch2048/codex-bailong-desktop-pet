"""Categorised expanded details; live data, explanations and sources stay separate."""
from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QWidget,QLabel,QVBoxLayout,QHBoxLayout,QTabWidget,QScrollArea,QFrame,QStackedWidget,QApplication
from compact_bubble import font,FONT_CSS,source_button,Announcement
from reset_watch import pending_reset,schedule_text,account_reset_text
from ring_widgets import draw_metric_icon
from quota_summary_data import quota_items,today_tokens
from ui_theme import hide_scrollbars


class MetricIcon(QWidget):
    def __init__(self,kind,parent=None):
        super().__init__(parent);self.kind=kind;self.setFixedSize(24,24)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#e9e0f1')));p.drawEllipse(QRectF(1,1,22,22))
        draw_metric_icon(p,QPointF(12,12),self.kind,14)


class DetailCard(QWidget):
    def __init__(self,title,warning=False,parent=None):
        super().__init__(parent);self.warning=warning
        self.body=QVBoxLayout(self);self.body.setContentsMargins(10,9,10,10);self.body.setSpacing(6)
        label=self.text(title,size=12,strong=True)
        label.setObjectName('detail_section_title')
    def text(self,text,size=12,strong=False,muted=False,warning=False):
        size=max(11,min(size,11) if muted and not warning else size)
        label=QLabel(str(text));label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True)
        color='#915e74' if warning else '#706879' if muted else '#393343'
        set_theme_style(label,FONT_CSS+f'font-size:{size}px;font-weight:{600 if size>14 else 500};color:{color};background:transparent;')
        self.body.addWidget(label);return label
    def add_metric(self,name,value,icon):
        row=QHBoxLayout();row.setSpacing(7);row.addWidget(MetricIcon(icon))
        title=QLabel(name);set_theme_style(title,FONT_CSS+'font-size:12px;color:#706879;');row.addWidget(title,1)
        number=QLabel(value);set_theme_style(number,FONT_CSS+'font-size:20px;font-weight:600;color:#514360;');row.addWidget(number)
        self.body.addLayout(row)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(theme_color('#fbf4f7' if self.warning else '#f5f1f7')))
        p.setPen(QPen(QColor(theme_color('#e9dce5' if self.warning else '#e9e0f0')),1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),9,9)


class DetailsTabs(QTabWidget):
    def __init__(self,bubble,parent=None):
        super().__init__(parent);self.setObjectName('detail_tabs');self.setFixedHeight(244)
        self.setFont(font(12,True));self.areas={};self.keys=['quota','tokens','reset','legend']
        set_theme_style(self,'QTabWidget::pane{border:1px solid #e7deed;border-radius:10px;background:#fcfafc;top:-1px;}'
            'QTabBar::tab{'+FONT_CSS+'font-size:12px;color:#706879;background:transparent;border:0;padding:7px 15px;margin-bottom:3px;}'
            'QTabBar::tab:selected{color:#514360;background:#eae2f2;border-radius:7px;}'
            'QTabBar::tab:hover{background:#f2edf6;border-radius:7px;}'
            'QScrollArea{border:0;background:transparent;}QScrollBar:vertical{background:transparent;width:8px;margin:2px 0;}'
            'QScrollBar::handle:vertical{background:#cfc0de;border-radius:4px;min-height:24px;}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}'
            'QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}')
        quota=self.page('quota','额度');tokens=self.page('tokens','Token');reset=self.page('reset','重置');legend=self.page('legend','使用说明')
        card=self.card(quota,'账户额度')
        if not bubble.windows:card.text('账户额度尚未提供，空轨道不代表 0%。',muted=True)
        for item in quota_items(bubble.windows):
            card.add_metric(item['name']+'剩余',item['display'],'bolt' if item['name']=='5小时' else 'calendar')
            card.text(item['reset_text']+' · '+account_reset_text(item['reset_at'])+'（北京时间）',size=11,muted=True)
        card.text(bubble.quota_caption,size=11,warning=any(s in bubble.quota_caption for s in ('上次','不可用','待刷新')),muted=True)
        card=self.card(quota,'额度与重置')
        card.text('每条进度条表示该周期的剩余额度；下方时间是该周期自己的重置倒计时。本页显示精确重置时刻，未知数据不会当作零额度。',size=10,muted=True)
        card=self.card(tokens,'本机 Token 用量')
        snapshot=bubble.token_snapshot
        if not snapshot:card.text('Token 用量正在统计中…',muted=True)
        elif snapshot.get('unavailable'):card.text('Token 用量统计暂不可用，请点击顶部刷新重试。',warning=True)
        else:
            card.add_metric(snapshot.get('month','')+' 累计',f"{snapshot.get('total',0):,}",'tokens')
            card.text(today_tokens(snapshot)['description'],size=11,muted=True)
            if snapshot.get('partial'):card.text('部分日志暂不可读，当前用量统计可能不完整。',size=11,warning=True)
        card=self.card(tokens,'图表与统计口径')
        card.text('全部 / 近30天 / 近7天：用量柱状图。\n今日00–24时：每小时消耗曲线，非累计值。\n悬停图表可查看精确日期与用量。',size=11,muted=True)
        card.text('按本地日期统计，仅包含本机已记录历史。输入含缓存，输出含推理，不重复相加；长时段自动合并日期。',size=11,muted=True)
        pending=pending_reset(bubble.reset_snapshot)
        countdown=Announcement(bubble.reset_snapshot,getattr(bubble,'reset_error_details',None) or bubble.reset_feed_error,with_refresh=False)
        card=self.card(reset,countdown.view['title'])
        card.body.addWidget(countdown)
        if countdown.view['phase']=='pending':card.text(schedule_text(bubble.reset_snapshot),size=10,muted=True)
        if pending and pending.get('text'):card.text(pending['text'])
        if bubble.reset_feed_error:card.text((getattr(bubble,'reset_error_details',None) or {}).get('message') or ('重置消息连接失败 · 显示上次记录' if bubble.reset_snapshot else '重置消息暂不可用，稍后自动重试'),size=11,warning=True)
        card=self.card(reset,'公告来源')
        card.text('Codex Resets（第三方）\n预计安排不等于账户额度已到账。',size=11,muted=True)
        card.body.addWidget(source_button(),0,Qt.AlignmentFlag.AlignLeft)
        card=self.card(legend,'数据怎么看')
        for icon,title,note in [('calendar','周额度','该账户一周窗口的剩余额度，重置时间独立显示。'),('bolt','5小时额度','仅在账户提供这个限制时显示，耗尽后需等对应窗口重置。'),('clock','重置倒计时','到期显示待刷新；取得新数据后才更新余额。'),('tokens','今日 Token','本机今日实际记录的消耗量，点击可查看24小时曲线。')]:
            row=QHBoxLayout();row.setSpacing(8);row.addWidget(MetricIcon(icon),0,Qt.AlignmentFlag.AlignTop)
            labels=QVBoxLayout();labels.setSpacing(2)
            for value,size,color in [(title,11,'#514360'),(note,11,'#706879')]:
                text=QLabel(value);text.setWordWrap(True);set_theme_style(text,FONT_CSS+f'font-size:{size}px;color:{color};');labels.addWidget(text)
            row.addLayout(labels,1);card.body.addLayout(row)
        card=self.card(legend,'面板与人物')
        card.text('点击胶囊回到正常卡片；详情按钮打开大卡片。自动模式闲置后收起，手动胶囊与极简模式保持你的选择。',muted=True)
        card.text('右键“显示面板”可仅留人物；设置→面板可隐藏人物或分离两者。分离后人物和面板各自拖动，按钮保持点击功能。',muted=True)
        card=self.card(legend,'会话与提醒')
        card.text('最多同时显示两个会话；有更多会话时使用切换入口。点击会话名跳转 Codex。',muted=True)
        card.text('感叹号表示任务完成待查看，停止晃动后仍保留；点击状态图标确认，或在 Codex 查看完成回复后自动确认。仅跳转不会立即清除。',muted=True)
        card=self.card(legend,'重置与日报')
        card.text('额外重置公告优先显示，预计剩余时间使用小时分钟；公告落实或检测到本机额度重置后恢复 Token 卡，可通过页签手动切换。公告不等于余额已到账。',muted=True)
        card.text('日报独立按钮打开。概览曲线按昨日24小时统计，书本换算使用累计 Token；模型页可筛选全部、近30天、近7天。',muted=True)
        card=self.card(legend,'设置与更新')
        card.text('设置按面板、人物、Codex、素材、闲聊、维护分类。普通偏好需应用；刷新、素材下载和切换、更新安装等操作立即执行。',muted=True)
        card.text('自动更新只检查公开稳定版，不自动下载。轻量素材默认内置，高清可在素材页下载；纯程序更新可复用兼容素材。',muted=True)
        for layout in (quota,tokens,reset,legend):layout.addStretch()
        self.setCurrentIndex(self.keys.index(bubble.detail_tab) if bubble.detail_tab in self.keys else 0)
        self.currentChanged.connect(lambda i:setattr(bubble,'detail_tab',self.keys[i]))
        self._page_stack=self.findChild(QStackedWidget)
        self._page_fade=None
        if self._page_stack:
            from data_page_motion import PageFade
            self._page_fade=PageFade(self._page_stack)
        self._last_index=self.currentIndex()
        self.currentChanged.connect(self._page_changed)
    def _page_changed(self,index):
        previous=self._last_index;self._last_index=index
        if not self._page_fade or previous==index:return
        from settings_controls import motion_enabled
        old=self.widget(previous);new=self.widget(index)
        frame=self._page_fade.current_frame() if self._page_fade.isVisible() else None
        if frame is None and old is not None and self.isVisible() and motion_enabled():
            frame=self._page_fade.snapshot(old)
        self._page_fade.clear()
        if frame is None or new is None or not self.isVisible() or not motion_enabled():return
        self._page_fade.hold(frame,self._page_stack.rect())
        widgets=[new]+new.findChildren(QWidget)
        for widget in reversed(widgets):
            widget.ensurePolished()
            if widget.layout():widget.layout().activate()
        QApplication.sendPostedEvents(None,QEvent.Type.LayoutRequest)
        target=self._page_fade.snapshot(new)
        self._page_fade.present(frame,target,self._page_stack.rect(),direction=1 if index>previous else -1)
        new.repaint()
    def hideEvent(self,event):
        if self._page_fade:self._page_fade.clear()
        super().hideEvent(event)
    def page(self,key,title):
        area=hide_scrollbars(QScrollArea());area.setObjectName('detail_'+key);area.setWidgetResizable(True);area.setFrameShape(QFrame.Shape.NoFrame)
        content=QWidget();set_theme_style(content,'background:transparent;');layout=QVBoxLayout(content)
        layout.setContentsMargins(7,8,7,8);layout.setSpacing(8);area.setWidget(content)
        self.areas[key]=area;self.addTab(area,title);return layout
    def card(self,layout,title,warning=False):
        card=DetailCard(title,warning);layout.addWidget(card);return card
    def restore_scroll(self,positions):
        for key,area in self.areas.items():area.verticalScrollBar().setValue(positions.get(key,0))
