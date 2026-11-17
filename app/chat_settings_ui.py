"""In-card chat settings, grouped by connection and conversation behavior."""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QHBoxLayout,QLabel,QPlainTextEdit,QPushButton,QScrollArea,QVBoxLayout,QWidget

from chat_config import CHAT_DEFAULT,load_chat_config,save_chat_preferences
from chat_window import ChatNotice,chat_symbol
from choice_controls import ChoiceCombo
from number_controls import IntegerField
from settings_controls import SlidingSegments
from theme_runtime import set_theme_style
from typography import FONT_CSS
from ui_theme import hide_scrollbars


def heading(text):
    label=QLabel(text)
    set_theme_style(label,FONT_CSS+'font-size:12px;font-weight:600;color:#393343;background:transparent;')
    return label


def page_link(text,slot):
    button=QPushButton(text+' ›')
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    set_theme_style(button,'QPushButton{'+FONT_CSS+'font-size:12px;color:#393343;background:#f5f2f7;border:0;'
        'border-radius:7px;text-align:left;padding:7px 9px;}QPushButton:hover{background:#e8dff0;}')
    button.clicked.connect(slot)
    return button


class ChatSettingsPane(QWidget):
    def __init__(self,chat,title,back):
        super().__init__(chat)
        self.chat=chat
        self.setObjectName('chat_settings_pane')
        set_theme_style(self,'QWidget#chat_settings_pane{background:#fcfafc;}')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout=self.layout_box=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0);layout.setSpacing(8)
        top=QHBoxLayout();top.setContentsMargins(0,0,0,0);top.setSpacing(6)
        top.addWidget(chat_symbol('‹','返回',back));top.addWidget(heading(title),1);layout.addLayout(top)
        self.scroll=hide_scrollbars(QScrollArea())
        self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        set_theme_style(self.scroll,'QScrollArea{background:transparent;border:0;}')
        body=QWidget()
        self.scroll.setWidget(body)
        body.setAutoFillBackground(False);self.scroll.viewport().setAutoFillBackground(False)
        self.body=QVBoxLayout(body);self.body.setContentsMargins(3,0,3,0);self.body.setSpacing(7)
        layout.addWidget(self.scroll,1)


class ChatSettingsPage(ChatSettingsPane):
    def __init__(self,chat):
        super().__init__(chat,'聊天设置',chat.return_to_chat)
        self.body.addWidget(heading('聊天服务'))
        self.service=SlidingSegments([('ChatGPT 套餐','chatgpt'),('自定义 API','custom')],compact=True)
        self.body.addWidget(self.service)
        self.service.currentIndexChanged.connect(lambda _:chat.choose_service(self.service.currentData()))
        self.connection=ChatNotice();self.body.addWidget(self.connection)
        self.custom=page_link('服务连接',lambda:chat.provider(from_settings=True))
        self.body.addWidget(self.custom)
        self.account=QWidget();box=QVBoxLayout(self.account);box.setContentsMargins(0,0,0,0);box.setSpacing(6)
        self.connect_button=QPushButton('连接 ChatGPT');self.connect_button.clicked.connect(chat.connect_account);box.addWidget(self.connect_button)
        self.cancel_button=QPushButton('取消授权');self.cancel_button.clicked.connect(chat.cancel_account_job);box.addWidget(self.cancel_button)
        self.models=ChoiceCombo();self.models.setAccessibleName('选择 ChatGPT 模型');box.addWidget(self.models)
        self.models.currentIndexChanged.connect(self.choose_model)
        self.disconnect=QPushButton('断开本机授权');self.disconnect.clicked.connect(chat.disconnect_account);box.addWidget(self.disconnect)
        self.body.addWidget(self.account)
        self.feedback=ChatNotice();self.body.addWidget(self.feedback)
        self.body.addSpacing(5)
        self.body.addWidget(heading('对话'))
        self.preferences=page_link('回复风格与历史',chat.open_chat_preferences);self.body.addWidget(self.preferences)
        self.body.addStretch()

    def choose_model(self,_):
        model=self.models.currentData()
        if model is not None:self.chat.choose_service('chatgpt',model)

    def sync(self,config,summary,connected):
        source=config.get('service','custom')
        locked=bool(self.chat.account_job)
        with QSignalBlocker(self.service):
            self.service.setCurrentIndex(self.service.findData(source),False)
        self.service.setEnabled(bool(config) and not self.chat.busy)
        self.connection.setText(summary)
        self.custom.setVisible(source=='custom')
        self.account.setVisible(source=='chatgpt')
        self.connect_button.setText('重新连接 ChatGPT' if connected else '连接 ChatGPT')
        self.connect_button.setVisible(not locked)
        self.cancel_button.setVisible(locked)
        self.disconnect.setVisible(connected and not locked)
        models=[('自动选择',''),*((label,key) for key,label in self.chat.chatgpt_models.items())]
        if config.get('chatgpt_model') and not any(key==config['chatgpt_model'] for _,key in models):
            models.append((config['chatgpt_model'],config['chatgpt_model']))
        blocked=self.models.blockSignals(True)
        if models!=[(self.models.itemText(i),self.models.itemData(i)) for i in range(self.models.count())]:
            self.models.clear()
            for title,key in models:self.models.addItem(title,key)
        self.models.setCurrentIndex(self.models.findData(config.get('chatgpt_model','')))
        self.models.blockSignals(blocked)
        self.models.setVisible(connected and len(models)>1 and not locked)


class ChatPreferencesPage(ChatSettingsPane):
    def __init__(self,chat):
        super().__init__(chat,'回复风格与历史',chat.open_chat_settings)
        self.body.addWidget(heading('回复风格'))
        self.prompt=hide_scrollbars(QPlainTextEdit());self.prompt.setFixedHeight(82)
        set_theme_style(self.prompt,'QPlainTextEdit{'+FONT_CSS+'font-size:12px;color:#393343;background:#f5f2f7;'
            'border:1px solid #ded2e7;border-radius:7px;padding:5px;}QPlainTextEdit:focus{border-color:#8b78a6;}')
        self.prompt.setAccessibleName('角色系统提示词');self.body.addWidget(self.prompt)
        self.body.addSpacing(5);self.body.addWidget(heading('发给模型的历史'))
        self.body.addWidget(ChatNotice('控制每次请求带上的历史，已保存的聊天记录会保留。'))
        self.count=IntegerField();self.count.setRange(2,200);self.count.setSuffix(' 条')
        self.chars=IntegerField();self.chars.setRange(1000,200000);self.chars.setSingleStep(1000);self.chars.setSuffix(' 字符')
        for title,field in (('消息上限',self.count),('字符上限',self.chars)):
            self.body.addWidget(QLabel(title));self.body.addWidget(field)
        self.status=ChatNotice();self.body.addWidget(self.status);self.body.addStretch()
        self.save_button=QPushButton('保存');self.save_button.setProperty('role','primary')
        self.save_button.clicked.connect(self.save);self.layout_box.addWidget(self.save_button,0,Qt.AlignmentFlag.AlignRight)
        try:config=load_chat_config(chat.root)
        except OSError as error:
            config=CHAT_DEFAULT;self.status.setText(str(error));self.save_button.setEnabled(False)
        self.prompt.setPlainText(config['system_prompt'])
        self.count.setValue(config['history_messages']);self.chars.setValue(config['history_chars'])

    def save(self):
        try:save_chat_preferences(self.chat.root,self.prompt.toPlainText(),self.count.value(),self.chars.value())
        except OSError as error:self.status.setText('对话设置未保存。'+str(error));return
        self.chat.open_chat_settings()
        self.chat.settings_page.feedback.setText('对话设置已保存。')
