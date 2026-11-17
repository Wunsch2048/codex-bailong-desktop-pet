"""Compact read-only rate-card page inside the quota panel."""
from datetime import datetime
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QScrollArea,QToolButton,QLabel
from quota_compare_ui import text_label
from theme_runtime import set_theme_style
from typography import FONT_CSS
from ui_theme import PRIMARY,PANEL,SELECTED,INK,MUTED,hide_scrollbars
from choice_controls import ChoiceCombo
from official_credit_rates import SOURCE,shared
from data_page_motion import ReportSubpage


class OfficialRatesPage(ReportSubpage):
    def __init__(self,parent,controller=None,back_text='‹ 额度',entry_frame=None):
        super().__init__(parent);self.setObjectName('officialRatesPage')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
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
        layout.addLayout(nav)
        self.area=QScrollArea();self.area.setWidgetResizable(True);hide_scrollbars(self.area)
        self.area.setMinimumSize(0,0)
        set_theme_style(self.area,'QScrollArea{border:0;background:transparent;}');layout.addWidget(self.area,1)
        body=QWidget();self.area.setWidget(body)
        body.setAutoFillBackground(False);self.area.viewport().setAutoFillBackground(False)
        content=self.content=QVBoxLayout(body);content.setContentsMargins(0,0,0,0);content.setSpacing(6)
        content.addWidget(text_label('官方 API 价表' if api else '官方 Credits 价表',14,True))
        note=text_label('标准速度 / 短上下文 / USD 每百万 Token' if api else '标准速度 / 每百万 Token\n输入／缓存输入／输出，单位均为 Credits。');note.setWordWrap(True);content.addWidget(note)
        scope=text_label('新价格从本机记录后应用，之前的估算沿用旧价。' if api else '公开计价参考，订阅额度仍按实际余额估算。');scope.setWordWrap(True);content.addWidget(scope)
        self.status=text_label();self.status.setWordWrap(True);content.addWidget(self.status)
        self.check_time=text_label();content.addWidget(self.check_time)
        self.latest_label=text_label('最新价表',12,True);content.addWidget(self.latest_label)
        self.history=ChoiceCombo();self.history.setAccessibleName('查看价表历史版本');self.history.currentIndexChanged.connect(self.select_version);content.addWidget(self.history)
        self.rows=QWidget();content.addWidget(self.rows)
        source=QToolButton();source.setText('官方来源  ↗');source.setCursor(Qt.CursorShape.PointingHandCursor)
        source.setAccessibleName('打开官方 API 定价说明' if api else '打开官方 Credits 定价说明')
        set_theme_style(source,'QToolButton{'+FONT_CSS+f'color:{PRIMARY};background:{PANEL};border:0;border-radius:6px;padding:5px;}}QToolButton:hover{{background:{SELECTED};}}')
        source.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(self.controller.cache.data['source'])));content.addWidget(source,0,Qt.AlignmentFlag.AlignLeft)
        content.addStretch()
        self.controller.changed.connect(self.sync)
        self.sync()
        self.show_page(entry_frame)
        self.controller.ensure_due()
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
        has_history=len(versions)>1
        self.latest_label.setVisible(not has_history);self.history.setVisible(has_history);self.history.setEnabled(has_history)
        self.render_rows()
    def render_rows(self,reset=False):
        versions=self.controller.cache.data['versions']
        index=self.selected if isinstance(self.selected,int) and 0<=self.selected<len(versions) else len(versions)-1
        version=versions[index] if versions else None
        key=(index,version['revision'] if version else None)
        if key==self.rows_key:return
        scrollbar=self.area.verticalScrollBar()
        position=0 if reset else scrollbar.value()
        self.rows_key=key
        rows=QWidget(self.area.widget())
        rows_layout=QVBoxLayout(rows);rows_layout.setContentsMargins(0,0,0,0);rows_layout.setSpacing(5)
        if not version:rows_layout.addWidget(text_label('联网取得价表后显示模型单价'))
        else:
            stamp=text_label('本版本首次记录 '+datetime.fromtimestamp(version['observed_at']).strftime('%Y/%m/%d %H:%M'));stamp.setWordWrap(True);rows_layout.addWidget(stamp)
            for model in version['rates'].values():
                card=QWidget();card.setObjectName('officialRateModel');set_theme_style(card,f'background:{PANEL};border-radius:8px;')
                box=QVBoxLayout(card);box.setContentsMargins(8,6,8,6);box.setSpacing(3)
                title=text_label(model['name'],12,True);title.setWordWrap(True);box.addWidget(title)
                line=QHBoxLayout();line.setSpacing(6)
                for label,value in zip(('输入','缓存','输出'),model['rates']):
                    column=QVBoxLayout();column.setSpacing(0);column.addWidget(text_label(label))
                    column.addWidget(text_label('—' if value is None else f'{value:,.4f}'.rstrip('0').rstrip('.'),12,True));line.addLayout(column,1)
                box.addLayout(line);rows_layout.addWidget(card)
        old=self.rows
        self.content.replaceWidget(old,rows);self.rows=rows;rows.show();old.hide();old.deleteLater()
        self.content.activate()
        scrollbar.setValue(position)
