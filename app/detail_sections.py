"""Categorised expanded details; live data, explanations and sources stay separate."""
from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent,QUrl,QTimer
from PySide6.QtGui import QPainter,QColor,QPen,QDesktopServices
from PySide6.QtWidgets import QWidget,QLabel,QVBoxLayout,QHBoxLayout,QTabWidget,QScrollArea,QFrame,QStackedWidget,QApplication,QToolButton
from compact_bubble import font,FONT_CSS,source_button,Announcement,action_button
from reset_watch import pending_reset,schedule_text,account_reset_text,local_time,SOURCE_URL
from ring_widgets import draw_metric_icon
from quota_summary_data import quota_items,today_tokens
from ui_theme import hide_scrollbars
from token_calendar import compact_tokens
from datetime import datetime
from reset_watch import BEIJING
import math


def detail_label(value,size=11,muted=False,strong=False):
    label=QLabel(str(value));label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True)
    set_theme_style(label,FONT_CSS+f'font-size:{size}px;font-weight:{600 if strong else 500};color:{"#706879" if muted else "#393343"};background:transparent;')
    return label


class DetailInfoButton(QToolButton):
    """The preview's 16px stroked information icon, independent of glyph fonts."""
    def paintEvent(self,event):
        from theme_registry import palette
        colors=palette();p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse() or self.isChecked():
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(colors['selected']));p.drawRoundedRect(QRectF(self.rect()),5,5)
        p.setPen(QPen(QColor(colors['accentText'] if self.isChecked() else colors['muted']),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush);center=QPointF(self.rect().center())+QPointF(.5,.5)
        p.drawEllipse(center,6,6);p.drawLine(center+QPointF(0,-1),center+QPointF(0,3));p.drawLine(center+QPointF(0,-3.5),center+QPointF(0,-3.2))


class DetailRow(QWidget):
    def __init__(self,title,sub,value='',secondary='',action=None,parent=None):
        super().__init__(parent);row=QHBoxLayout(self);row.setContentsMargins(1,7,1,7);row.setSpacing(12)
        left=QVBoxLayout();left.setSpacing(2);left.addWidget(detail_label(title))
        if sub:left.addWidget(detail_label(sub,10,True))
        row.addLayout(left,1)
        if action is not None:row.addWidget(action,0,Qt.AlignmentFlag.AlignVCenter)
        else:
            right=QVBoxLayout();right.setSpacing(2)
            for text,size,muted in ((value,12,False),(secondary,10,True)):
                if text:
                    label=detail_label(text,size,muted);label.setAlignment(Qt.AlignmentFlag.AlignRight);right.addWidget(label)
            row.addLayout(right)
    def paintEvent(self,event):
        from theme_registry import palette
        p=QPainter(self);p.setPen(QColor(palette()['track']));p.drawLine(0,self.height()-1,self.width(),self.height()-1)

class DetailScrollArea(QScrollArea):
    def wheelEvent(self,event):
        # At either end of a detail page, continue through a constrained outer
        # card. A nested reader must not trap the wheel on a small screen.
        bar=self.verticalScrollBar();delta=event.pixelDelta().y() or event.angleDelta().y()
        edge=(delta>0 and bar.value()==bar.minimum()) or (delta<0 and bar.value()==bar.maximum())
        parent=self.parentWidget()
        while edge and parent is not None:
            if isinstance(parent,QScrollArea):
                outer=parent.verticalScrollBar();old=outer.value()
                step=event.pixelDelta().y() or round(event.angleDelta().y()/120*outer.singleStep()*QApplication.wheelScrollLines())
                outer.setValue(old-step)
                if outer.value()!=old:event.accept();return
            parent=parent.parentWidget()
        super().wheelEvent(event)


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
        self.body=QVBoxLayout(self);self.body.setContentsMargins(2,5,2,9);self.body.setSpacing(5)
        label=self.text(title,size=12,strong=True)
        label.setObjectName('detail_section_title')
    def text(self,text,size=12,strong=False,muted=False,warning=False):
        size=max(11,min(size,11) if muted and not warning else size)
        label=QLabel(str(text));label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True)
        color='#915e74' if warning else '#706879' if muted else '#393343'
        set_theme_style(label,FONT_CSS+f'font-size:{size}px;font-weight:{600 if size>14 else 500};color:{color};background:transparent;')
        self.body.addWidget(label);return label
    def add_metric(self,name,value,icon):
        row=QHBoxLayout();row.setSpacing(7)
        title=QLabel(name);set_theme_style(title,FONT_CSS+'font-size:12px;color:#706879;');row.addWidget(title,1)
        number=QLabel(value);set_theme_style(number,FONT_CSS+'font-size:14px;font-weight:600;color:#514360;');row.addWidget(number)
        self.body.addLayout(row)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme_color('#e9dce5' if self.warning else '#e9e0f0')),1))
        p.drawLine(2,self.height()-1,self.width()-2,self.height()-1)


class DetailsTabs(QTabWidget):
    def __init__(self,bubble,parent=None):
        super().__init__(parent);self.bubble=None;self.setObjectName('detail_tabs');self.setFixedHeight(244)
        self.setFont(font(11));self.areas={};self.keys=['quota','tokens','reset','legend','more']
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        set_theme_style(self,'QTabWidget::pane{border:0;border-top:1px solid #e7deed;background:transparent;}'
            'QTabBar::tab{'+FONT_CSS+'font-size:11px;color:#706879;background:transparent;border:0;padding:3px 8px;margin-bottom:5px;}'
            'QTabBar::tab:selected{color:#514360;background:#eae2f2;border-radius:5px;}'
            'QTabBar::tab:hover{background:#f2edf6;border-radius:7px;}'
            'QScrollArea{border:0;background:transparent;}QScrollBar:vertical{background:transparent;width:8px;margin:2px 0;}'
            'QScrollBar::handle:vertical{background:#cfc0de;border-radius:4px;min-height:24px;}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}'
            'QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}')
        quota=self.page('quota','额度详情');tokens=self.page('tokens','Token明细');reset=self.page('reset','重置公告');legend=self.page('legend','使用说明');more=self.page('more','更多说明')
        self.tabBar().setTabVisible(3,False);self.tabBar().setTabVisible(4,False)
        help_button=DetailInfoButton(self);self.help_button=help_button;help_button.setObjectName('detail_help');help_button.setFixedSize(22,22)
        help_button.setFocusPolicy(Qt.FocusPolicy.NoFocus);help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        help_button.setAccessibleName('使用说明');help_button.setToolTip('说明')
        set_theme_style(help_button,'QToolButton{color:#706879;border:0;background:transparent;border-radius:6px;}QToolButton:hover{background:#eee7f5;}QToolButton:checked{background:#eae2f2;}')
        help_button.setCheckable(True);help_button.clicked.connect(bubble.show_explanations)
        help_button.move(max(0,self.width()-22),0)
        self.currentChanged.connect(lambda index:help_button.setChecked(index>=3))
        items=quota_items(bubble.windows)
        for item in items:
            title={'一周':'本周窗口','5小时':'5 小时窗口'}.get(item['name'],item['name']+'窗口')
            stamp=item['reset_at'];sub=('重置时间已到 / 等待刷新' if item['expired'] else datetime.fromtimestamp(stamp,BEIJING).strftime('%m月%d日 %H:%M')+' 重置 / 北京时间') if stamp else '重置时间未提供'
            source=next((window for window in (bubble.windows or []) if isinstance(window,dict) and window.get('name')==item['name']),{})
            plan=source.get('plan');plan=plan.strip().upper()[:30] if isinstance(plan,str) else ''
            quota.addWidget(DetailRow(title,sub,item['display'],plan))
        caption=bubble.quota_caption or ('账户额度尚未提供，未知不代表 0%。' if not bubble.windows else '')
        if caption:quota.addWidget(detail_label(caption,10,True))
        snapshot=bubble.token_snapshot
        if not snapshot:tokens.addWidget(detail_label('Token 用量正在统计中…',11,True))
        elif snapshot.get('unavailable'):tokens.addWidget(detail_label('统计暂不可用，请点击顶部刷新重试。',11,True))
        else:
            total=snapshot.get('all_total',snapshot.get('total'));known=isinstance(total,(int,float)) and not isinstance(total,bool) and math.isfinite(total) and total>=0
            stat=QWidget();stat.setFixedHeight(29);row=QHBoxLayout(stat);row.setContentsMargins(0,0,0,0)
            row.addWidget(detail_label('本机累计',11,True),1);value=detail_label((compact_tokens(total)+' Token') if known else '—',15,False,True)
            if known:value.setAccessibleDescription(f'本机累计 {total:,} Token')
            row.addWidget(value);tokens.addWidget(stat)
            if snapshot.get('partial'):tokens.addWidget(detail_label('部分日志暂不可读，统计可能不完整。',10,True))
        tokens.addWidget(detail_label('柱显示用量，线显示回合均速。\n均速包含思考、工具和等待，不代表纯生成速度。',10,True))
        tokens.addWidget(detail_label('输入包含缓存，输出包含推理，不重复相加。',10,True))
        pending=pending_reset(bubble.reset_snapshot)
        from reset_presentation import reset_view
        view=reset_view(bubble.reset_snapshot,getattr(bubble,'reset_error_details',None) or bubble.reset_feed_error)
        subtitle='暂无待落实的安排' if view['phase']=='empty' else schedule_text(bubble.reset_snapshot) if pending else view['note'] or view['display']
        external=action_button('external','公告来源',hit_size=22);external.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(SOURCE_URL)))
        reset.addWidget(DetailRow('额外重置公告',subtitle.replace(' · ',' / '),action=external))
        if pending and pending.get('text'):
            reset.addWidget(detail_label(pending['text'],11))
        reset.addWidget(detail_label('来源：Codex Resets（第三方）\n预计安排不等于账户额度已经到账。',10,True))
        if bubble.reset_feed_error:reset.addWidget(detail_label((getattr(bubble,'reset_error_details',None) or {}).get('message') or '公告连接暂不可用，等待重试。',10,True))
        for layout in (quota,tokens,reset):layout.addStretch()
        self.setCurrentIndex(self.keys.index(bubble.detail_tab) if bubble.detail_tab in self.keys else 0)
        self._page_stack=self.findChild(QStackedWidget)
        self._page_fade=None
        if self._page_stack:
            from data_page_motion import PageFade
            self._page_fade=PageFade(self._page_stack)
        self._last_index=self.currentIndex()
        self.currentChanged.connect(self._page_changed);self.bubble=bubble
        bubble.size_transition.animation.finished.connect(self._drain_navigation)
    def content_height(self,index,width):
        area=self.widget(index);body=area.widget();layout=body.layout()
        body.ensurePolished();layout.activate()
        height=layout.heightForWidth(max(40,width-2))
        if height<0:height=layout.sizeHint().height()
        return self.tabBar().sizeHint().height()+max(1,height)+8
    def setCurrentIndex(self,index):
        # Python callers and Qt's native tab bar must use the same signal path.
        super().setCurrentIndex(index)
    def _restore_index(self,index):
        blocked=self.blockSignals(True)
        try:QTabWidget.setCurrentIndex(self,index)
        finally:self.blockSignals(blocked)
    def _drain_navigation(self):
        index=getattr(self,'_pending_index',None);self._pending_index=None
        if index is not None and self.bubble.details_tabs is self and self.bubble.panel_page=='status':
            QTimer.singleShot(0,self,lambda:self.setCurrentIndex(index))
    def _page_changed(self,index):
        previous=self._last_index
        if previous==index:return
        bubble=self.bubble
        if bubble.size_transition.running:
            self._pending_index=index;self._restore_index(previous);return
        animate=bool(self.isVisible() and bubble.expanded and bubble.panel_page=='status' and not bubble.size_transition.preparing)
        if animate:
            # currentChanged also comes from C++ mouse/keyboard/accessibility
            # paths which never call our Python setCurrentIndex override.
            # Restore the settled source synchronously before capturing it.
            self._restore_index(previous);bubble.detail_tab=self.keys[previous]
            bubble.size_transition.begin()
            self._restore_index(index)
        self._last_index=index;bubble.detail_tab=self.keys[index]
        area=self.widget(index)
        if isinstance(area,QScrollArea):area.verticalScrollBar().setValue(0)
        if self._page_fade:self._page_fade.clear()
        if animate:
            bubble._fit_height();bubble.size_transition.commit()
    def hideEvent(self,event):
        if self._page_fade:self._page_fade.clear()
        super().hideEvent(event)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        button=getattr(self,'help_button',None)
        if button is not None:button.move(max(0,self.width()-button.width()),0)
    def showEvent(self,event):
        super().showEvent(event)
        self.help_button.move(max(0,self.width()-22),0);self.help_button.raise_()
    def page(self,key,title):
        area=hide_scrollbars(DetailScrollArea());area.setObjectName('detail_'+key);area.setWidgetResizable(True);area.setFrameShape(QFrame.Shape.NoFrame)
        content=QWidget();set_theme_style(content,'background:transparent;');layout=QVBoxLayout(content)
        layout.setContentsMargins(0,5,0,3);layout.setSpacing(6);area.setWidget(content)
        self.areas[key]=area;self.addTab(area,title);return layout
    def card(self,layout,title,warning=False):
        card=DetailCard(title,warning);layout.addWidget(card);return card
    def restore_scroll(self,positions):
        for key,area in self.areas.items():area.verticalScrollBar().setValue(positions.get(key,0))


def explanation_page(bubble):
    """A separate reader; no long help paragraphs below the status tabs."""
    page=QWidget();page.setObjectName('large_card_explanations')
    outer=QVBoxLayout(page);outer.setContentsMargins(0,0,0,0);outer.setSpacing(8)
    back=QToolButton();back.setText('‹ 返回状态');back.setCursor(Qt.CursorShape.PointingHandCursor)
    set_theme_style(back,'QToolButton{'+FONT_CSS+'font-size:11px;background:#f5f2f7;color:#75618d;border:0;border-radius:6px;padding:6px 9px;}QToolButton:hover{background:#e8dff0;}')
    back.clicked.connect(bubble.return_to_status);outer.addWidget(back,0,Qt.AlignmentFlag.AlignLeft)
    area=hide_scrollbars(DetailScrollArea());area.setFrameShape(QFrame.Shape.NoFrame);area.setWidgetResizable(True)
    set_theme_style(area,'QScrollArea{border:0;background:transparent;}');set_theme_style(area.viewport(),'background:transparent;')
    body=QWidget();set_theme_style(body,'background:transparent;');layout=QVBoxLayout(body);layout.setContentsMargins(0,0,2,0);layout.setSpacing(10)
    for title,text in [
        ('额度与重置','周额度和5小时额度分别显示剩余比例，各自按旁边的时间重置。倒计时结束后点击刷新，查看最新额度。'),
        ('Token 用量','今日统计从本机零点开始，累计统计包含这台电脑上能读取的历史。输入包含缓存，输出包含推理。'),
        ('图表与速率','柱子表示 Token 用量，曲线表示回合平均速率。24小时按小时统计，其他范围按天统计。悬停可看中位速率和样本量。回合用时包含思考、工具执行和等待，所以更适合观察任务处理快慢。'),
        ('实时与今日','实时模块显示进行中会话的合计速率，悬停可分别查看各会话。点击今日可以打开24小时用量图。'),
        ('会话与提醒','点击任务可以跳到对应会话。完成后的提醒可点击状态图标确认，也会在 Codex 中读到完成回复后自动确认。'),
        ('额外重置公告','这里显示 Codex Resets 发布的额外重置安排，点击来源按钮可查看原文。实际余额以刷新后的账户额度为准。'),
        ('卡片与人物','胶囊点击后打开正常卡片，详情按钮打开大卡片。可以在设置里隐藏人物、切换极简额度圆，或让面板和人物分开移动。'),
        ('设置与更新','主题圆点击后先预览，保存后保留，离开设置则放弃未保存的主题。下载素材、刷新数据等按钮立即执行；程序更新由你点击下载并安装。')]:
        group=QWidget();row=QVBoxLayout(group);row.setContentsMargins(0,0,0,0);row.setSpacing(4)
        row.addWidget(detail_label(title,12,False,True));row.addWidget(detail_label(text,11,True));layout.addWidget(group)
    layout.addStretch();area.setWidget(body);outer.addWidget(area,1);return page
