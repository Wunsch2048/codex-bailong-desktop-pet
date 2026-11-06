"""One draft editor shared by Codex settings and the cost page."""
import copy,json,math
from datetime import date,datetime
from PySide6.QtCore import Qt,QObject,Signal,QUrl,QTimer,QEasingCurve
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QScrollArea,QSizePolicy
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply
from choice_controls import ChoiceCombo
from theme_runtime import set_theme_style
from typography import FONT_CSS
from ui_theme import hide_scrollbars
from cost_preferences import load,save
from data_page_motion import PageFade
from settings_controls import motion_enabled

class PricingEvents(QObject):changed=Signal()
def events():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance()
    if not hasattr(app,'_pricing_events'):app._pricing_events=PricingEvents(app)
    return app._pricing_events

def open_editor(parent,models=(),refresh=None):
    current=parent.findChild(PricingEditor,'pricingEditor')
    if current is not None and current.isVisible():current.raise_();return current
    return PricingEditor(parent,models,refresh)

class PricingEditor(QWidget):
    def __init__(self,parent,models=(),refresh=None,price_service=None):
        super().__init__(parent);self.refresh=refresh;self.draft=copy.deepcopy(load());self.models=set(models);self.network=QNetworkAccessManager(self);self.reply=None;self.query="";self.model_scroll=0
        from official_api_prices import shared
        self.api=price_service or shared();self.page='home';self.api.changed.connect(self.api_status_changed)
        self.outer_footer=parent.window().findChild(QWidget,'settings_footer');self.restore_footer=self.outer_footer is not None and not self.outer_footer.isHidden()
        if self.restore_footer:self.outer_footer.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True);self.setObjectName('pricingEditor')
        set_theme_style(self, """
            QWidget#pricingEditor, QWidget#pricingBody { background:#fcfafc; }
            QLabel { font-size:12px; color:#706879; background:transparent; }
            QLabel[role="title"] { font-size:15px; font-weight:600; color:#393343; }
            QLabel[role="strong"] { font-weight:600; color:#393343; }
            QWidget#pricingGroup { background:#f5f0f8; border-radius:9px; }
            QLineEdit { font-size:12px; color:#393343; background:#fcfafc;
                border:1px solid #e4dfea; border-radius:6px; padding:4px 6px; }
            QLineEdit:focus { border-color:#8b78a6; }
            QPushButton { font-size:12px; color:#514360; background:#eae1f2;
                border:1px solid transparent; border-radius:6px; padding:5px 7px; }
            QPushButton:hover { background:#e0d3eb; }
            QPushButton:focus { border-color:#8b78a6; }
            QPushButton#pricingCommit { background:#e0d3eb; color:#393343; font-weight:600; }
            QPushButton#pricingCommit:hover { background:#eae1f2; }
            QPushButton#pricingModel { text-align:left; color:#393343; font-weight:600; }
        """.replace('            QLabel {','            QLabel {' + FONT_CSS)
           .replace('            QLineEdit {','            QLineEdit {' + FONT_CSS)
           .replace('            QPushButton {','            QPushButton {' + FONT_CSS))
        layout=QVBoxLayout(self);layout.setContentsMargins(6,6,6,6);layout.setSpacing(7)
        head=QHBoxLayout()
        self.back=QPushButton();self.back.clicked.connect(self.go_back);head.addWidget(self.back)
        head.addStretch();self.heading=self.label(head,'计价设置','title');layout.addLayout(head)
        self.area=hide_scrollbars(QScrollArea());self.area.setWidgetResizable(True)
        set_theme_style(self.area,'QScrollArea{background:transparent;border:0;}');layout.addWidget(self.area,1)
        self.page_motion=PageFade(self.area.viewport());self._page_ticket=0;self._pending_api_models=False
        self.page_motion.animation.finished.connect(self.flush_api_models)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status);self.status.hide()
        foot=QHBoxLayout();foot.addStretch()
        self.cancel=QPushButton('取消');self.cancel.clicked.connect(self.go_back);foot.addWidget(self.cancel)
        self.commit=QPushButton('保存设置');self.commit.setObjectName('pricingCommit')
        self.commit.clicked.connect(self.commit_draft);foot.addWidget(self.commit);layout.addLayout(foot)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);parent.installEventFilter(self);self.setGeometry(parent.rect());self.model=None;self.home();self.show();self.raise_()
    def label(self,box,text,role=''):
        label=QLabel(text);label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText)
        label.setProperty('role',role);label.setMinimumWidth(0)
        box.addWidget(label);return label
    def notice(self,text=''):
        self.status.setText(text);self.status.setVisible(bool(text))
    def group(self,box):
        frame=QWidget();frame.setObjectName('pricingGroup');frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        inner=QVBoxLayout(frame);inner.setContentsMargins(8,7,8,7);inner.setSpacing(5)
        box.addWidget(frame);return inner
    def body(self):
        old=self.area.takeWidget()
        if old:old.hide();old.deleteLater()
        body=QWidget();body.setObjectName("pricingBody");body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        box=QVBoxLayout(body);box.setContentsMargins(0,0,0,0);box.setSpacing(7)
        self.area.setWidget(body);self.area.verticalScrollBar().setValue(0);return box
    def begin_page(self,target):
        self._page_ticket+=1;frame=None
        if self.page!=target and self.isVisible() and self.updatesEnabled() and motion_enabled():
            frame=self.page_motion.current_frame() if self.page_motion.isVisible() else PageFade.snapshot(self.area.viewport())
        direction=1 if {'home':0,'models':1,'model':2}[target]>{'home':0,'models':1,'model':2}[self.page] else -1
        self.page_motion.clear()
        if frame is not None:self.page_motion.hold(frame,self.area.viewport().rect())
        return self._page_ticket,frame,direction
    def end_page(self,transition):
        ticket,frame,direction=transition
        if frame is not None:QTimer.singleShot(0,self,lambda:self.present_page(ticket,frame,direction))
        else:self.flush_api_models()
    def present_page(self,ticket,frame,direction):
        if ticket!=self._page_ticket:return
        if not self.isVisible() or not self.updatesEnabled() or not motion_enabled():
            self.page_motion.clear();return
        try:
            from panel_transition import settle_visible
            self.page_motion.hide();settle_visible(self.area.viewport())
            if ticket!=self._page_ticket:return
            target=PageFade.snapshot(self.area.viewport())
            self.page_motion.animation.setDuration(220)
            self.page_motion.animation.setEasingCurve(QEasingCurve.Type.OutCubic if direction>0 else QEasingCurve.Type.InCubic)
            self.page_motion.present(frame,target,self.area.viewport().rect(),direction=direction)
        except Exception:
            self.page_motion.clear();raise
    def cancel_page_motion(self):
        self._page_ticket+=1;self._pending_api_models=False;self.page_motion.clear()
    def flush_api_models(self):
        if self._pending_api_models:
            self._pending_api_models=False
            if self.page=='models' and self.isVisible():self.api_status_changed()
    def home(self):
        transition=self.begin_page('home')
        from settings_controls import SlidingSegments
        self.model=None;self.page='home';self.commit.setText('保存设置');self.heading.setText('计价设置')
        self.back.setText('‹ 成本' if type(self.parentWidget()).__name__=='ProjectCosts' else '‹ 返回')
        box=self.body();price_group=self.group(box)
        self.label(price_group,'模型价格','strong');self.label(price_group,'标准 · 短上下文 · USD / 百万 Token')
        self.price_status=self.label(price_group,'')
        self.price_refresh=QPushButton('更新模型价格');self.price_refresh.clicked.connect(self.api.request);price_group.addWidget(self.price_refresh)
        self.models_button=QPushButton('查看与调整单价  ›');self.models_button.clicked.connect(self.models_page);price_group.addWidget(self.models_button)
        self.api_status_changed()
        currency_group=self.group(box);self.label(currency_group,'汇率','strong')
        self.currency=SlidingSegments([('USD','USD'),('CNY','CNY'),('HKD','HKD')],compact=True)
        self.currency.setAccessibleName('显示币种')
        self.currency.setCurrentIndex(self.currency.findData(self.draft['currency']));currency_group.addWidget(self.currency)
        self.mode=ChoiceCombo();self.mode.addItem('手动汇率','manual');self.mode.addItem('自动汇率','auto')
        self.mode.setCurrentIndex(self.mode.findData(self.draft['mode']));currency_group.addWidget(self.mode)
        fx_row=QHBoxLayout();self.fx_label=self.label(fx_row,'');self.fx_label.setWordWrap(False)
        self.fx=QLineEdit(str(self.draft['fx']) if self.draft['fx'] else '')
        self.fx.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.fx.setAccessibleName('美元换算汇率');fx_row.addWidget(self.fx,1);currency_group.addLayout(fx_row)
        fx_actions=QHBoxLayout();self.quote=self.label(fx_actions,'')
        self.fx_refresh=QPushButton('更新汇率');self.fx_refresh.clicked.connect(self.fetch_fx)
        fx_actions.addWidget(self.fx_refresh);currency_group.addLayout(fx_actions)
        self.currency.currentIndexChanged.connect(self.currency_changed);self.mode.currentIndexChanged.connect(self.mode_changed)
        self.fx.textChanged.connect(self.fx_changed);self.sync_currency()
        box.addStretch()
        if self.draft['mode']=='auto' and self.draft['currency']!='USD' and self.draft.get('fx_date','')<date.today().isoformat():self.fetch_fx()
        self.end_page(transition)
    def default_prices(self):
        from project_cost import RATES
        result=dict(RATES);versions=self.api.cache.data['versions']
        if versions:result.update({m:tuple(v['rates']) for m,v in versions[-1]['rates'].items()})
        return result
    def api_status_changed(self):
        if self.page=='home':
            self.price_refresh.setEnabled(not self.api.busy)
            data=self.api.cache.data
            if self.api.busy:text='正在读取官方单价…'
            elif self.api.cache.error:text=self.api.cache.error+('，沿用已有单价' if data['versions'] else '，沿用内置单价')
            elif data['checked_at']:text='上次检查 '+datetime.fromtimestamp(data['checked_at']).strftime('%m/%d %H:%M')+' · 每天自动更新'
            else:text='每天自动检查，手动单价优先保留'
            self.price_status.setText(text)
        elif self.page=='models' and not self.api.busy:
            versions=self.api.cache.data['versions'];key=versions[-1]['revision'] if versions else None
            if key!=self._api_rows_revision:
                if self.page_motion.isVisible():self._pending_api_models=True;return
                self.model_scroll=self.area.verticalScrollBar().value();self.models_page()
    def models_page(self):
        transition=self.begin_page('models')
        self.cancel_fx();self.model=None;self.page='models';self.commit.setText('保存设置');self.heading.setText('模型单价');self.back.setText('‹ 计价')
        box=self.body();defaults=self.default_prices()
        history=QPushButton('官方价表与历史  ›');history.clicked.connect(self.show_price_history);box.addWidget(history)
        title=QHBoxLayout();self.label(title,'模型单价','strong');title.addStretch();self.label(title,'USD / 百万 Token');box.addLayout(title)
        self.search=QLineEdit(self.query);self.search.setPlaceholderText('搜索模型');self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('搜索模型');box.addWidget(self.search)
        self.model_rows=[]
        models=set(defaults)|set(self.draft['prices'])|self.models
        official=self.api.cache.data['versions'][-1]['rates'] if self.api.cache.data['versions'] else {}
        self._api_rows_revision=self.api.cache.data['versions'][-1]['revision'] if official else None
        for model in sorted(models,key=lambda name:(name in defaults or name in self.draft['prices'],name.casefold())):
            values=self.draft['prices'].get(model,defaults.get(model,[None]*3))
            source='自定义' if model in self.draft['prices'] else '官方' if model in official else '内置'
            state='待定价' if all(v is None for v in values) else '部分定价' if None in values else source
            row=self.group(box)
            button=QPushButton(model+'  ›');button.setObjectName('pricingModel')
            button.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);button.setToolTip(model)
            button.clicked.connect(lambda checked=False,m=model:self.edit_model(m));row.addWidget(button)
            summary=QHBoxLayout()
            for title,value in zip(('输入','缓存','输出'),values):
                column=QVBoxLayout();column.setSpacing(1)
                self.label(column,title)
                self.label(column,'—' if value is None else str(value),'strong')
                summary.addLayout(column,1)
            self.label(summary,state);row.addLayout(summary)
            self.model_rows.append((model,row.parentWidget()))
        self.empty=self.label(box,'没有匹配的模型')
        box.addStretch();self.search.textChanged.connect(self.filter_models);self.filter_models(self.query)
        box.activate();self.area.verticalScrollBar().setValue(self.model_scroll)
        self.end_page(transition)
    def show_price_history(self):
        from official_rates_ui import OfficialRatesPage
        frame=PageFade.snapshot(self) if self.isVisible() and self.updatesEnabled() and motion_enabled() else None
        self.cancel_page_motion()
        self.api_status_changed()
        self.history_page=OfficialRatesPage(self,self.api,back_text='‹ 单价',entry_frame=frame)
    def filter_models(self,text):
        self.query=text
        matches=False
        for model,row in self.model_rows:
            visible=text.strip().casefold() in model.casefold()
            row.setVisible(visible);matches|=visible
        self.empty.setVisible(not matches)
    def sync_currency(self):
        if self.page!='home':return
        foreign=self.draft['currency']!='USD';automatic=self.draft['mode']=='auto'
        for widget in (self.mode,self.fx_label,self.fx):widget.setVisible(foreign)
        self.quote.setText(self.draft.get('fx_date',''))
        self.quote.setVisible(foreign and automatic and bool(self.quote.text()))
        self.fx_label.setText('1 USD = '+self.draft['currency']);self.fx.setReadOnly(automatic);self.fx_refresh.setVisible(foreign);self.fx_refresh.setEnabled(self.reply is None)
    def currency_changed(self):
        self.cancel_fx();self.notice()
        self.draft['currency']=self.currency.currentData();self.draft.pop('fx_date',None);self.draft.pop('fx_source',None)
        if self.draft['currency']!='USD':self.draft['fx']=0.;self.fx.setText('');self.notice('请填写汇率或选择自动汇率')
        else:self.fx.setText('1.0')
        self.sync_currency()
        if self.draft['mode']=='auto' and self.draft['currency']!='USD':self.fetch_fx()
    def mode_changed(self):
        self.cancel_fx();self.notice()
        self.draft['mode']=self.mode.currentData();self.sync_currency()
        if self.draft['mode']=='auto' and self.draft['currency']!='USD':self.fetch_fx()
    def fx_changed(self,text):
        try:self.draft['fx']=float(text)
        except ValueError:self.draft['fx']=0
    def fetch_fx(self):
        if self.reply:return
        currency=self.draft['currency'];request=QNetworkRequest(QUrl('https://api.frankfurter.dev/v2/rate/USD/'+currency));request.setTransferTimeout(7000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        self.reply=self.network.get(request);self.reply.readyRead.connect(self.limit_fx);self.reply.finished.connect(lambda:self.got_fx(currency));self.fx_refresh.setEnabled(False);self.notice('正在读取汇率…')
    def limit_fx(self):
        if self.reply and self.reply.bytesAvailable()>65536:self.reply.abort()
    def got_fx(self,currency):
        reply=self.reply;self.reply=None
        if self.page=='home':self.fx_refresh.setEnabled(True)
        try:
            if reply.error()!=QNetworkReply.NetworkError.NoError or reply.bytesAvailable()>65536:raise ValueError()
            value=json.loads(bytes(reply.readAll()));rate=value['rate']
            if not isinstance(rate,(int,float)) or not math.isfinite(rate) or rate<=0 or value.get('base','USD').upper()!='USD' or value.get('quote',currency).upper()!=currency:raise ValueError()
            if currency!=self.draft['currency']:return
            self.draft.update(fx=rate,fx_date=value['date'],fx_source='https://frankfurter.dev/')
            if self.page=='home':
                self.fx.setText(str(rate));self.sync_currency();self.notice('汇率已读取，保存后应用')
        except (ValueError,TypeError,KeyError):
            if self.page=='home':self.notice('汇率暂未取得，请重试或改用手动汇率')
        finally:reply.deleteLater()
    def edit_model(self,model):
        transition=self.begin_page('model')
        defaults=self.default_prices()
        if self.page=='models':self.model_scroll=self.area.verticalScrollBar().value()
        self.cancel_fx();self.notice();self.model=model;self.page='model';self.back.setText('‹ 模型单价');self.heading.setText('模型单价')
        box=self.body();group=self.group(box);self.label(group,model,'title');self.label(group,'USD / 百万 Token')
        self.price_fields=[]
        for title,value in zip(('非缓存输入','缓存输入','输出'),self.draft['prices'].get(model,defaults.get(model,[None]*3))):
            row=QHBoxLayout();caption=self.label(row,title)
            caption.ensurePolished();caption.setFixedWidth(caption.fontMetrics().horizontalAdvance("非缓存输入")+4)
            edit=QLineEdit('' if value is None else str(value))
            edit.setAlignment(Qt.AlignmentFlag.AlignRight);edit.setPlaceholderText('未定价')
            edit.setAccessibleName(title+'单价');self.price_fields.append(edit)
            row.addWidget(edit,1);group.addLayout(row)
        self.label(group,'留空为待定价，0 为免费')
        restore=QPushButton('恢复默认价' if model in defaults else '清空单价')
        restore.clicked.connect(lambda:self.restore_model(model));box.addWidget(restore,alignment=Qt.AlignmentFlag.AlignLeft)
        box.addStretch();self.commit.setText('完成')
        self.end_page(transition)
    def restore_model(self,model):
        for field,value in zip(self.price_fields,self.default_prices().get(model,[None]*3)):field.setText('' if value is None else str(value))
    def finish_model(self):
        try:
            values=[None if not field.text().strip() else float(field.text()) for field in self.price_fields]
            if any(v is not None and (not math.isfinite(v) or v<0) for v in values):raise ValueError()
        except ValueError:self.notice('请输入非负单价，或留空');return False
        defaults=self.default_prices()
        if self.model in defaults and list(defaults[self.model])==values:self.draft['prices'].pop(self.model,None)
        else:self.draft['prices'][self.model]=values
        self.notice();self.models_page();return True
    def go_back(self):
        if self.model:self.notice();self.models_page()
        elif self.page=='models':self.notice();self.home()
        else:self.close()
    def commit_draft(self):
        if self.model:self.finish_model();return
        try:
            if self.draft['mode']=='auto' and self.draft['currency']!='USD' and not self.draft.get('fx_date'):raise ValueError('请先取得自动汇率，或改用手动汇率')
            save(self.draft)
        except (ValueError,OSError) as error:self.notice('未保存：'+str(error));return
        events().changed.emit()
        if self.refresh:self.refresh()
        self.close()
    def eventFilter(self,obj,event):
        from PySide6.QtCore import QEvent
        if event.type()==QEvent.Type.Resize:self.setGeometry(obj.rect())
        elif event.type()==QEvent.Type.Hide:self.close()
        return False
    def closeEvent(self,event):
        self.cancel_page_motion()
        if self.restore_footer:
            from shiboken6 import isValid
            if isValid(self.outer_footer):self.outer_footer.show()
        self.cancel_fx()
        super().closeEvent(event)
    def hideEvent(self,event):
        if hasattr(self,'page_motion'):self.cancel_page_motion()
        super().hideEvent(event)
    def resizeEvent(self,event):
        if hasattr(self,'page_motion'):self.cancel_page_motion()
        super().resizeEvent(event)
    def cancel_fx(self):
        if self.reply:
            reply=self.reply;self.reply=None
            reply.finished.disconnect();reply.abort();reply.deleteLater()
