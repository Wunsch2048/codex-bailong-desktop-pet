"""Compact read-only rate-card page inside the quota panel."""
from datetime import datetime
from PySide6.QtCore import Qt,QEvent,QUrl,QTimer,QEasingCurve
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QScrollArea,QToolButton,QLabel
from quota_compare_ui import text_label
from theme_runtime import set_theme_style
from typography import FONT_CSS
from ui_theme import PRIMARY,PANEL,SELECTED,INK,MUTED,hide_scrollbars
from choice_controls import ChoiceCombo
from official_credit_rates import SOURCE,shared
from data_page_motion import PageFade
from settings_controls import motion_enabled


class OfficialRatesPage(QWidget):
    def __init__(self,parent,controller=None,back_text='‹ 额度',entry_frame=None):
        super().__init__(parent);self.setObjectName('officialRatesPage')
        self.hide()
        entry=entry_frame
        if entry is None and parent.isVisible() and parent.updatesEnabled() and motion_enabled():entry=PageFade.snapshot(parent)
        self._motion_ticket=0;self._returning=False;self._capturing_return=False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True)
        set_theme_style(self,'QWidget#officialRatesPage{background:#fcfafc;}')
        self.controller=controller or shared();self.selected=None;self.rows_key=None
        api=self.controller.cache.data['unit']=='usd_per_million_tokens'
        layout=QVBoxLayout(self);layout.setContentsMargins(3,3,3,3);layout.setSpacing(6)
        nav=QHBoxLayout();nav.setSpacing(6)
        self.back=QToolButton();self.back.setText(back_text);self.back.clicked.connect(self.go_back)
        nav.addWidget(self.back);nav.addStretch()
        self.refresh=QToolButton();self.refresh.setText('更新价表');self.refresh.setAccessibleName('从官方更新 API 价表' if api else '从官方更新 Credits 价表')
        self.refresh.clicked.connect(self.controller.request);nav.addWidget(self.refresh)
        for button in (self.back,self.refresh):
            button.setFixedHeight(27);button.setCursor(Qt.CursorShape.PointingHandCursor)
            set_theme_style(button,'QToolButton{'+FONT_CSS+f'color:{PRIMARY};font-size:11px;background:{PANEL};border:0;border-radius:6px;padding:3px 7px;}}QToolButton:hover{{background:{SELECTED};}}QToolButton:disabled{{color:{MUTED};}}')
        layout.addLayout(nav);layout.addWidget(text_label('官方 API 价表' if api else '官方 Credits 价表',14,True))
        note=text_label('标准速度 · 短上下文 · USD / 百万 Token' if api else '标准速度 · 每百万 Token\n输入／缓存输入／输出，单位均为 Credits。');note.setWordWrap(True);layout.addWidget(note)
        scope=text_label('新价格从本机记录后应用，之前的估算沿用旧价。' if api else '公开计价参考，订阅额度仍按实际余额估算。');scope.setWordWrap(True);layout.addWidget(scope)
        self.status=text_label();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.check_time=text_label();layout.addWidget(self.check_time)
        self.history=ChoiceCombo();self.history.setAccessibleName('查看价表历史版本');self.history.currentIndexChanged.connect(self.select_version);layout.addWidget(self.history)
        self.area=QScrollArea();self.area.setWidgetResizable(True);hide_scrollbars(self.area)
        set_theme_style(self.area,'QScrollArea{border:0;background:transparent;}');layout.addWidget(self.area,1)
        self.rows=QWidget();set_theme_style(self.rows,'background:transparent;');self.rows_layout=QVBoxLayout(self.rows);self.rows_layout.setContentsMargins(0,0,0,0);self.rows_layout.setSpacing(5);self.area.setWidget(self.rows)
        source=QToolButton();source.setText('官方来源  ↗');source.setCursor(Qt.CursorShape.PointingHandCursor);source.setAccessibleName('打开官方 Credits 定价说明')
        set_theme_style(source,'QToolButton{'+FONT_CSS+f'color:{PRIMARY};background:{PANEL};border:0;border-radius:6px;padding:5px;}}QToolButton:hover{{background:{SELECTED};}}')
        source.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(self.controller.cache.data['source'])));layout.addWidget(source,0,Qt.AlignmentFlag.AlignLeft)
        self.controller.changed.connect(self.sync);parent.installEventFilter(self)
        self.page_motion=PageFade(self);self.page_motion.animation.finished.connect(self.motion_finished)
        self.sync();self.setGeometry(parent.rect());self.show();self.raise_()
        if entry is not None:
            self._motion_ticket+=1;ticket=self._motion_ticket
            self.page_motion.hold(entry,self.rect());QTimer.singleShot(0,self,lambda:self.present_entry(ticket,entry))
        self.controller.ensure_due()
    def present_entry(self,ticket,frame):
        if ticket!=self._motion_ticket:return
        if not self.isVisible() or not self.updatesEnabled() or not motion_enabled():self.page_motion.clear();return
        try:
            from panel_transition import settle_visible
            self.page_motion.hide();settle_visible(self)
            target=PageFade.snapshot(self)
            self.page_motion.animation.setDuration(220);self.page_motion.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.page_motion.present(frame,target,self.rect(),direction=1)
        except Exception:self.page_motion.clear();raise
    def go_back(self):
        if self._returning:return
        parent=self.parentWidget()
        if not self.isVisible() or not self.updatesEnabled() or not parent.isVisible() or not motion_enabled():self.close();return
        self._motion_ticket+=1
        frame=self.page_motion.current_frame() if self.page_motion.isVisible() else PageFade.snapshot(self)
        self.page_motion.clear()
        try:
            self._capturing_return=True;self.hide()
            from panel_transition import settle_visible
            settle_visible(parent);target=PageFade.snapshot(parent)
            self.show();self.raise_();self._capturing_return=False;self._returning=True
            self.page_motion.animation.setDuration(220);self.page_motion.animation.setEasingCurve(QEasingCurve.Type.InCubic)
            self.page_motion.present(frame,target,self.rect(),direction=-1)
        except Exception:
            self._capturing_return=False;self.close();raise
    def motion_finished(self):
        if self._returning:self.close()
    def cancel_motion(self):
        self._motion_ticket+=1;self._returning=False;self.page_motion.clear()
    def closeEvent(self,event):
        self.cancel_motion();super().closeEvent(event)
    def hideEvent(self,event):
        if hasattr(self,'page_motion') and not self._capturing_return:self.cancel_motion()
        super().hideEvent(event)
    def resizeEvent(self,event):
        if hasattr(self,'page_motion'):
            returning=self._returning;self.cancel_motion()
            if returning:self.close()
        super().resizeEvent(event)
    def select_version(self,*args):
        self.selected=self.history.currentData();self.render_rows(reset=True)
    def sync(self):
        cache=self.controller.cache;versions=cache.data['versions']
        self.refresh.setEnabled(not self.controller.busy)
        if self.controller.busy:message='正在检查官方价表…'
        elif cache.error:message=cache.error+('，继续使用缓存' if versions else '，稍后自动重试')
        else:message='每天自动检查，价格变化时保留旧版本'
        self.status.setText(message)
        checked=cache.data['checked_at']
        self.check_time.setText('上次成功检查 '+datetime.fromtimestamp(checked).strftime('%m/%d %H:%M') if checked else '尚无成功检查记录')
        labels=[('最新价表',None)]+[(datetime.fromtimestamp(v['observed_at']).strftime('%Y/%m/%d %H:%M')+' 记录',i) for i,v in reversed(list(enumerate(versions[:-1])))]
        old=[(self.history.itemText(i),self.history.itemData(i)) for i in range(self.history.count())]
        if old!=labels:
            blocked=self.history.blockSignals(True);self.history.clear()
            for title,value in labels:self.history.addItem(title,value)
            index=self.history.findData(self.selected);self.history.setCurrentIndex(max(0,index));self.history.blockSignals(blocked)
        self.history.setEnabled(len(versions)>1);self.render_rows()
    def render_rows(self,reset=False):
        versions=self.controller.cache.data['versions']
        index=self.selected if isinstance(self.selected,int) and 0<=self.selected<len(versions) else len(versions)-1
        version=versions[index] if versions else None
        key=(index,version['revision'] if version else None)
        if key==self.rows_key:return
        position=0 if reset else self.area.verticalScrollBar().value()
        self.rows_key=key
        while self.rows_layout.count():
            item=self.rows_layout.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
        if not version:self.rows_layout.addWidget(text_label('联网取得价表后显示模型单价'))
        else:
            stamp=text_label('本版本首次记录 '+datetime.fromtimestamp(version['observed_at']).strftime('%Y/%m/%d %H:%M'));stamp.setWordWrap(True);self.rows_layout.addWidget(stamp)
            for model in version['rates'].values():
                card=QWidget();set_theme_style(card,f'background:{PANEL};border-radius:8px;')
                box=QVBoxLayout(card);box.setContentsMargins(8,6,8,6);box.setSpacing(3)
                title=text_label(model['name'],12,True);title.setWordWrap(True);box.addWidget(title)
                line=QHBoxLayout();line.setSpacing(6)
                for label,value in zip(('输入','缓存','输出'),model['rates']):
                    column=QVBoxLayout();column.setSpacing(0);column.addWidget(text_label(label))
                    column.addWidget(text_label('—' if value is None else f'{value:,.4f}'.rstrip('0').rstrip('.'),12,True));line.addLayout(column,1)
                box.addLayout(line);self.rows_layout.addWidget(card)
        self.rows_layout.addStretch();self.rows_layout.activate();self.area.verticalScrollBar().setValue(position)
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Resize:self.setGeometry(obj.rect())
        elif event.type()==QEvent.Type.Hide:self.close()
        return False
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.go_back();event.accept();return
        super().keyPressEvent(event)
