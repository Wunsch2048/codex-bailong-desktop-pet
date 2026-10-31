"""User initiated, OpenAI-compatible SSE chat, separate from Codex monitoring."""
from theme_runtime import set_theme_style
import copy
import json
import time
import uuid
from pathlib import Path
from PySide6.QtCore import Qt,Signal,QTimer,QUrl,QRectF,QPointF
from PySide6.QtGui import QTextCursor,QDesktopServices,QTextBlockFormat,QTextCharFormat,QColor,QPainter,QPainterPath,QPen,QFontMetricsF
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QPushButton,
    QPlainTextEdit,QTextEdit,QLabel,QCheckBox,QDialog,QFormLayout,QLineEdit,QSpinBox,QStackedWidget,QScrollArea,QMenu,QFrame,QToolButton)
from desktop_core import atomic_json
from choice_controls import ChoiceCombo as QComboBox
from number_controls import IntegerField as QSpinBox
from inline_confirmation import InlineConfirmation
from chat_config import (CHAT_DEFAULT,load_chat_config,save_chat_config,load_provider_key,
    provider_key_present,clear_provider_key,delete_chat_provider)
from chat_protocol import ProviderValidationError,normalize_provider,endpoint_for
from ui_theme import hide_scrollbars
from typography import FONT_CSS,ui_font
from theme_registry import color as theme_color


class ChatNotice(QLabel):
    """Errors stay selectable; empty routine state does not reserve a text row."""
    def __init__(self,text='',parent=None):
        super().__init__(parent);self.setTextFormat(Qt.TextFormat.PlainText);self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_theme_style(self,FONT_CSS+'font-size:11px;color:#706879;background:transparent;')
        self.setText(text)
    def setText(self,text):
        super().setText(text);self.setVisible(bool(text))


class ChatGlyphButton(QToolButton):
    def __init__(self,kind,parent=None):
        super().__init__(parent);self.kind=kind
    def paintEvent(self,event):
        super().paintEvent(event);p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate((self.width()-16)/2,(self.height()-16)/2)
        p.setPen(QPen(QColor(theme_color('#ffffff' if self.property('role')=='primary' else '#75618d')),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        if self.kind=='more':
            for x in (3,8,13):p.drawEllipse(QPointF(x,8),.5,.5)
        else:
            lines={'plus':[(8,3,8,13),(3,8,13,8)],'back':[(9,3,4,8),(4,8,9,13),(4,8,13,8)],'send':[(3,9,8,3),(8,3,13,9),(8,3,8,14)]}
            for x,y,x2,y2 in lines.get(self.kind,[]):p.drawLine(QPointF(x,y),QPointF(x2,y2))


def chat_symbol(text,tip,slot,parent=None):
    button=ChatGlyphButton({'+':'plus','⋯':'more','‹':'back','↑':'send'}.get(text,text),parent);button.setToolTip(tip);button.setAccessibleName(tip)
    button.setFixedSize(25,25);button.setCursor(Qt.CursorShape.PointingHandCursor)
    set_theme_style(button,'QToolButton{'+FONT_CSS+'font-size:15px;border:0;border-radius:6px;background:transparent;color:#75618d;}'
        'QToolButton:hover{background:#e8dff0;}QToolButton:pressed{background:#e4dfea;}QToolButton:disabled{color:#8b8195;}QToolButton::menu-indicator{image:none;}'
        'QToolButton[role="primary"]{background:#8b78a6;}QToolButton[role="primary"]:hover{background:#5f4c77;}')
    if slot:button.clicked.connect(slot)
    return button


class ChatTranscript(QTextEdit):
    """Plain selectable text with message rhythm; streaming still appends only."""
    def __init__(self,parent=None):
        super().__init__(parent);self._user_ranges=[];self._message_layout=[];self._formatting=False;self._action_position=None
        self.setReadOnly(True);self.setAcceptRichText(False);self.setUndoRedoEnabled(False)
        self.setFrameShape(QFrame.Shape.NoFrame);self.setFont(ui_font(12));self.document().setDocumentMargin(0)
        self.setPlaceholderText('和白龙聊聊')
        set_theme_style(self,'QTextEdit{'+FONT_CSS+'font-size:12px;color:#393343;background:transparent;border:0;padding:0;selection-background-color:#e8dff0;selection-color:#393343;}')
        self.viewport().setAutoFillBackground(False)
        self.actions=QWidget(self.viewport());row=QHBoxLayout(self.actions);row.setContentsMargins(0,0,0,0);row.setSpacing(9)
        self.copy_button=QPushButton('复制');self.retry_button=QPushButton('重试')
        for button in (self.copy_button,self.retry_button):
            set_theme_style(button,'QPushButton{'+FONT_CSS+'font-size:10px;color:#706879;background:transparent;border:0;padding:0;}QPushButton:hover{color:#393343;}')
            button.setCursor(Qt.CursorShape.PointingHandCursor);row.addWidget(button)
        self.actions.hide();self.verticalScrollBar().valueChanged.connect(self._position_actions)
    def set_message_layout(self,messages,busy):
        parts=[];self._message_layout=[];position=0
        for message in messages:
            if parts:position+=2
            prefix='白龙\n' if message['role']=='assistant' else ''
            part=prefix+message['content'];length=len(part.encode('utf-16-le'))//2
            self._message_layout.append(dict(start=position,end=position+length,body=position+len(prefix),role=message['role'],text=message['content']))
            parts.append(part);position+=length
        self._action_position=position if messages and not busy else None
        self.copy_button.setVisible(bool(messages) and messages[-1]['role']=='assistant')
        self.actions.setVisible(self._action_position is not None)
        frame=self.document().rootFrame().frameFormat();frame.setTopMargin(5 if messages and messages[0]['role']=='user' else 0);frame.setBottomMargin(7);self.document().rootFrame().setFrameFormat(frame)
        return '\n\n'.join(parts)
    def _position_actions(self):
        if self._action_position is None:return
        cursor=QTextCursor(self.document());cursor.setPosition(min(self._action_position,self.document().characterCount()-1))
        buttons=[button for button in (self.copy_button,self.retry_button) if not button.isHidden()]
        for button in buttons:
            button.ensurePolished();button.setFixedSize(round(QFontMetricsF(button.font()).horizontalAdvance(button.text())),16)
        self.actions.resize(sum(button.width() for button in buttons)+max(0,len(buttons)-1)*9,16)
        self.actions.layout().setGeometry(self.actions.rect());self.actions.move(3,self.cursorRect(cursor).bottom()+9)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'actions'):self.refresh_theme_colors()
    def refresh_theme_colors(self):
        if self._formatting:return
        self._formatting=True
        try:
            selected=self.textCursor();bar=self.verticalScrollBar();scroll=bar.value()
            edit=QTextCursor(self.document());edit.beginEditBlock()
            self._user_ranges=[];block=self.document().begin();index=0;metric=QFontMetricsF(ui_font(12));width=self.viewport().width()
            for item in self._message_layout:
                if item['role']=='user':
                    measured=max((metric.horizontalAdvance(line) for line in item['text'].split('\n')),default=0)
                    item['width']=min(width*.88,max(24,measured+22));item['x']=width-item['width']
                    self._user_ranges.append(item)
            while block.isValid():
                while index+1<len(self._message_layout) and block.position()>=self._message_layout[index+1]['start']:index+=1
                item=self._message_layout[index] if self._message_layout else dict(start=0,end=0,body=0,role='assistant')
                text=block.text();role=item['role'];heading=role=='assistant' and block.position()==item['start'];separator=block.position()>item['end']
                first=block.position()==item['start'];last=block.position()+len(text.encode('utf-16-le'))//2>=item['end']
                cursor=QTextCursor(block);fmt=QTextBlockFormat()
                fmt.setLeftMargin(item.get('x',0)+11 if role=='user' and not separator else 3);fmt.setRightMargin(11 if role=='user' else max(3,width*.04))
                fmt.setLineHeight(12 if separator else (18.5 if heading else 22.2),QTextBlockFormat.LineHeightTypes.FixedHeight.value)
                fmt.setTopMargin(8 if role=='user' and first else (7 if role=='assistant' and not heading and block.position()!=item['body'] and not separator else 0))
                bottom=8 if role=='user' and last and not separator else (3 if heading else 0)
                if self._action_position is not None and last and index==len(self._message_layout)-1:bottom+=25
                fmt.setBottomMargin(bottom)
                cursor.setBlockFormat(fmt);char=QTextCharFormat();f=ui_font(12)
                if heading:f.setPixelSize(10)
                char.setFont(f)
                char.setForeground(QColor(theme_color('#706879' if heading else '#393343')))
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor);cursor.setCharFormat(char)
                block=block.next()
            edit.endEditBlock()
            self.setTextCursor(selected);bar.setValue(scroll);self._position_actions();self.viewport().update()
        finally:self._formatting=False
    def paintEvent(self,event):
        # Text remains one native document, so selection across messages works.
        painter=QPainter(self.viewport());painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(theme_color('#e8dff0')))
        layout=self.document().documentLayout();offset=self.verticalScrollBar().value()
        for item in self._user_ranges:
            a=layout.blockBoundingRect(self.document().findBlock(item['start']));b=layout.blockBoundingRect(self.document().findBlock(max(item['start'],item['end']-1)))
            rect=QRectF(item['x'],a.top()-offset-(5 if item['start']==0 else 8),item['width'],b.bottom()-a.top()+20.2)
            if rect.intersects(QRectF(self.viewport().rect())):
                x,y,w,h=rect.x(),rect.y(),rect.width(),rect.height();path=QPainterPath();path.moveTo(x+11,y);path.lineTo(x+w-11,y);path.quadTo(x+w,y,x+w,y+11);path.lineTo(x+w,y+h-3);path.quadTo(x+w,y+h,x+w-3,y+h);path.lineTo(x+11,y+h);path.quadTo(x,y+h,x,y+h-11);path.lineTo(x,y+11);path.quadTo(x,y,x+11,y);painter.drawPath(path)
        painter.end();super().paintEvent(event)


class ChatFoldButton(QPushButton):
    def paintEvent(self,event):
        super().paintEvent(event);p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme_color('#75618d')),1,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        x=self.width()-5;y=self.height()/2+4;direction=-1 if self.isChecked() else 1
        p.drawLine(QPointF(x-2,y-direction),QPointF(x,y+direction));p.drawLine(QPointF(x,y+direction),QPointF(x+2,y-direction))


class ChatSessionChoice(QComboBox):
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumHeight(29);self.setFixedHeight(29)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setFont(ui_font(12));p.setPen(QColor(theme_color('#393343')))
        metric=QFontMetricsF(p.font());text=metric.elidedText(self.currentText(),Qt.TextElideMode.ElideRight,self.width()-14)
        p.drawText(QRectF(0,0,self.width()-14,self.height()),Qt.AlignmentFlag.AlignVCenter,text)
        x=min(self.width()-6,metric.horizontalAdvance(text)+7);y=self.height()/2+2
        p.setPen(QPen(QColor(theme_color('#75618d')),1,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.drawLine(QPointF(x-2,y-1),QPointF(x,y+1));p.drawLine(QPointF(x,y+1),QPointF(x+2,y-1))

def load_json(path,default):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return copy.deepcopy(default)

def trim_messages(messages,count,chars):
    result=[];total=0
    for message in reversed(messages[-max(1,count):]):
        text=str(message.get('content',''))
        if total+len(text)>chars:
            if not result:result.append(dict(role=message['role'],content=text[-chars:]))
            break
        result.append(dict(role=message['role'],content=text));total+=len(text)
    result.reverse()
    while len(result)>1 and result[0]['role']=='assistant':result.pop(0)
    return result

class SessionStore:
    def __init__(self,root,character):
        self.path=Path(root)/('sessions-'+__import__('hashlib').sha256(character.encode()).hexdigest()[:16]+'.json')
        self.sessions=load_json(self.path,[])
        if not isinstance(self.sessions,list):self.sessions=[]
    def save(self):atomic_json(self.path,self.sessions)
    def new(self):
        session=dict(id=uuid.uuid4().hex,title='新对话',messages=[],at=time.time())
        self.sessions.insert(0,session);self.save();return session

from chat_transport import ChatStream

class ProviderDialog(QDialog):
    def __init__(self,root,parent=None,embedded=False):
        super().__init__(parent,Qt.WindowType.Widget if embedded else Qt.WindowType.Dialog);self.root=Path(root);self.path=self.root/'chat.json'
        self.embedded=embedded
        if embedded:self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName('provider_settings')
        set_theme_style(self,'QWidget#provider_settings{background:transparent;}QLabel{'+FONT_CSS+'font-size:11px;color:#706879;background:transparent;}'
            'QLineEdit,QPlainTextEdit{'+FONT_CSS+'font-size:11px;color:#393343;background:#f5f2f7;border:1px solid #ded2e7;border-radius:6px;padding:6px 8px;}'
            'QLineEdit{min-height:14px;max-height:14px;}'
            'QLineEdit:focus,QPlainTextEdit:focus{border:1px solid #8b78a6;}'
            'QPushButton{'+FONT_CSS+'font-size:11px;color:#75618d;background:#f5f2f7;border:1px solid #ded2e7;border-radius:6px;padding:5px 9px;}'
            'QPushButton:hover{background:#e8dff0;}QPushButton[role="primary"]{color:#ffffff;background:#8b78a6;border-color:#8b78a6;}'
            'QPushButton[role="primary"]:hover{background:#5f4c77;}QPushButton:disabled{color:#8b8195;background:#efebf2;}')
        self.load_error=''
        try:self.config=load_chat_config(self.root)
        except OSError as error:self.config=copy.deepcopy(CHAT_DEFAULT);self.load_error=str(error)
        self.drafts={};self.current=None;self.mutation_buttons=[]
        self.setWindowTitle('白龙聊天服务');self.resize(420,580);layout=QVBoxLayout(self)
        layout.setContentsMargins(0 if embedded else 12,0 if embedded else 12,0 if embedded else 12,0 if embedded else 12);layout.setSpacing(0)
        header=QHBoxLayout();header.setContentsMargins(0,0,0,0);header.setSpacing(5)
        if embedded:header.addWidget(chat_symbol('‹','返回聊天，保留未保存输入',self.reject))
        title=QLabel('聊天服务');set_theme_style(title,FONT_CSS+'font-size:12px;color:#393343;');header.addWidget(title,1)
        more=chat_symbol('⋯','服务管理',None);menu=QMenu(more);self.services_menu=menu.addMenu('切换服务')
        add=menu.addAction('添加服务');add.triggered.connect(lambda:QTimer.singleShot(0,self,self.add));self.mutation_buttons.append(add);menu.addSeparator()
        for text,slot in [('删除当前服务…',self.remove),('清除此服务密钥…',self.clear_key)]:
            action=menu.addAction(text);action.triggered.connect(lambda checked=False,s=slot:QTimer.singleShot(0,self,s));self.mutation_buttons.append(action)
        more.setMenu(menu);more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);header.addWidget(more);layout.addLayout(header);layout.addSpacing(8)
        self.body_scroll=hide_scrollbars(QScrollArea());self.body_scroll.setWidgetResizable(True);self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setObjectName('provider_body_scroll');set_theme_style(self.body_scroll,'QScrollArea#provider_body_scroll{background:transparent;border:0;}')
        self.body_scroll.viewport().setAutoFillBackground(False)
        body=QWidget();body.setAutoFillBackground(False);set_theme_style(body,'background:transparent;');body_layout=QVBoxLayout(body)
        body_layout.setContentsMargins(3,10,3,0);body_layout.setSpacing(0);self.body_scroll.setWidget(body);layout.addWidget(self.body_scroll,1)
        self.select=QComboBox(self);self.select.hide()
        self.confirmation=InlineConfirmation();body_layout.addWidget(self.confirmation)
        self.status=ChatNotice();body_layout.addWidget(self.status)
        form=QVBoxLayout();form.setSpacing(10);body_layout.addLayout(form)
        self.fields={}
        for key,title in [('name','服务名称'),('base_url','接口地址'),('model','模型'),('key','API 密钥')]:
            w=QLineEdit();w.setMinimumWidth(0);w.setFixedHeight(28);self.fields[key]=w
            if key=='key':w.setEchoMode(QLineEdit.EchoMode.Password);w.setPlaceholderText('留空保留；输入新密钥可替换')
            if key=='base_url':w.setPlaceholderText('基础地址或完整 Chat Completions 端点')
            field=QVBoxLayout();field.setSpacing(5);label=QLabel(title);label.setFixedHeight(16);field.addWidget(label);field.addWidget(w);form.addLayout(field)
        self.key_status=ChatNotice()
        self.fields['base_url'].textChanged.connect(self.update_endpoint)
        self.fields['key'].textChanged.connect(self.update_key_status)
        self.advanced_toggle=ChatFoldButton('高级设置');self.advanced_toggle.setCheckable(True);self.advanced_toggle.setFixedHeight(34)
        set_theme_style(self.advanced_toggle,'QPushButton{'+FONT_CSS+'font-size:11px;text-align:left;color:#75618d;background:transparent;border:0;border-top:1px solid #e4dfea;border-radius:0;padding:9px 0 0;}QPushButton:hover,QPushButton:checked{background:transparent;color:#393343;}')
        body_layout.addSpacing(9);body_layout.addWidget(self.advanced_toggle)
        self.advanced=QWidget();advanced=QFormLayout(self.advanced);advanced.setContentsMargins(0,0,0,0)
        advanced.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows);advanced.setVerticalSpacing(6)
        advanced.addRow(self.key_status)
        self.endpoint=ChatNotice();advanced.addRow('实际请求地址',self.endpoint)
        self.timeout=QSpinBox();self.timeout.setRange(5,600);advanced.addRow('超时（秒）',self.timeout)
        self.prompt=hide_scrollbars(QPlainTextEdit());self.prompt.setFixedHeight(76);self.prompt.setPlainText(self.config.get('system_prompt',CHAT_DEFAULT['system_prompt']));advanced.addRow('角色系统提示词',self.prompt)
        self.count=QSpinBox();self.count.setRange(2,200);self.count.setValue(self.config.get('history_messages',40));advanced.addRow('历史消息上限',self.count)
        self.chars=QSpinBox();self.chars.setRange(1000,200000);self.chars.setSingleStep(1000);self.chars.setValue(self.config.get('history_chars',24000));advanced.addRow('历史字符上限',self.chars)
        body_layout.addWidget(self.advanced);self.advanced.hide();self.advanced_toggle.toggled.connect(self._toggle_advanced)
        note=ChatNotice('使用 OpenAI 兼容的 Chat Completions 接口。\n仅主动发送时请求，不会自动发送 Codex 会话。');set_theme_style(note,FONT_CSS+'font-size:10px;color:#706879;background:transparent;');body_layout.addWidget(note)
        self.recovery=QPushButton('打开配置目录');self.recovery.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root))));body_layout.addWidget(self.recovery);self.recovery.hide();body_layout.addStretch()
        footer=QWidget();footer.setObjectName('provider_footer');row=QHBoxLayout(footer);row.setContentsMargins(0,9,0,0);row.setSpacing(7)
        set_theme_style(footer,'QWidget#provider_footer{border-top:1px solid #e4dfea;background:transparent;}')
        note=ChatNotice('保存不代表已验证连接');set_theme_style(note,FONT_CSS+'font-size:10px;color:#706879;background:transparent;');row.addWidget(note,1)
        save=QPushButton('保存');save.setObjectName('provider_save');save.setProperty('role','primary');save.clicked.connect(self.save);row.addWidget(save);layout.addSpacing(9);layout.addWidget(footer);self.mutation_buttons.append(save)
        set_theme_style(save,'QPushButton{'+FONT_CSS+'font-size:11px;color:#ffffff;background:#8b78a6;border:1px solid #8b78a6;border-radius:6px;padding:5px 13px;min-height:18px;max-height:18px;}QPushButton:hover{background:#5f4c77;}QPushButton:disabled{color:#8b8195;background:#efebf2;}')
        self.select.currentIndexChanged.connect(self.change);self.reload()
        if self.load_error:self.block_writes(self.load_error)
        for button in self.findChildren(QPushButton):button.setAutoDefault(False)
        from PySide6.QtGui import QShortcut,QKeySequence
        self.save_shortcut=QShortcut(QKeySequence('Ctrl+S'),self);self.save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);self.save_shortcut.activated.connect(self.save)
    def _toggle_advanced(self,visible):
        self.advanced.setVisible(visible);self.advanced_toggle.update()
    def prepare_visit(self):
        self.confirmation.cancel();self.body_scroll.verticalScrollBar().setValue(0)
    def block_writes(self,message):
        self.load_error=message
        self.status.setText('无法安全读取聊天配置或凭据：'+message+' 原文件已保留，暂停保存、删除及清密钥。请先备份配置目录，修复文件或恢复备份后重启桌宠。')
        self.recovery.show()
        for button in self.mutation_buttons:button.setEnabled(False)
    def update_endpoint(self):
        try:self.endpoint.setText(endpoint_for({'base_url':self.fields['base_url'].text()}))
        except ProviderValidationError as error:self.endpoint.setText(str(error))
    def update_key_status(self):
        if self.fields['key'].text():self.key_status.setText('新密钥待保存；不会显示已保存密钥。');return
        if self.load_error:self.key_status.setText('暂时无法读取已保存密钥状态。');return
        try:present=provider_key_present(self.root,self.current or {'id':''})
        except OSError as error:self.key_status.setText('凭据文件不可读取，原文件已保留。');self.block_writes(str(error));return
        self.key_status.setText('已保存密钥，留空保留' if present else '未保存密钥，本地免密服务可留空')
        self.fields['key'].setPlaceholderText('留空保留已存密钥' if present else '未存密钥，免密服务可留空')
    def validation_failed(self,error):
        self.status.setText(str(error)+' 配置尚未保存。')
        field=self.timeout if error.field=='timeout' else self.fields.get(error.field)
        if field:
            if field is self.timeout:self.advanced_toggle.setChecked(True)
            self.body_scroll.ensureWidgetVisible(field);field.setFocus();field.selectAll()
    def reload(self):
        self.current=None
        self.select.blockSignals(True);self.select.clear()
        for p in self.config.get('providers',[]):self.select.addItem(p.get('name','未命名'),p['id'])
        idx=self.select.findData(self.config.get('active'));self.select.setCurrentIndex(max(0,idx));self.select.blockSignals(False);self.change()
        self.services_menu.clear()
        for index,provider in enumerate(self.config.get('providers',[])):
            action=self.services_menu.addAction(provider.get('name','未命名'));action.setCheckable(True);action.setChecked(index==self.select.currentIndex())
            action.triggered.connect(lambda checked=False,i=index:self.select.setCurrentIndex(i))
    def change(self):
        self.confirmation.cancel()
        if self.current:self.drafts[self.current['id']]={**{key:w.text() for key,w in self.fields.items()},'timeout':self.timeout.value()}
        self.current=next((p for p in self.config.get('providers',[]) if p['id']==self.select.currentData()),None)
        values=self.drafts.get(self.current['id'],self.current) if self.current else {}
        for k,w in self.fields.items():w.setText(values.get(k,''))
        self.timeout.setValue(values.get('timeout',90))
        self.update_endpoint();self.update_key_status()
    def add(self):
        if self.load_error:return
        if self.current:self.drafts[self.current['id']]={**{key:w.text() for key,w in self.fields.items()},'timeout':self.timeout.value()}
        self.config.setdefault('providers',[]).append(dict(id=uuid.uuid4().hex,name='新服务',base_url='',model='',timeout=90))
        self.config['active']=self.config['providers'][-1]['id'];self.reload()
    def remove(self):
        if self.load_error or not self.current:return
        key=self.current['id'];name=self.fields['name'].text().strip() or self.current.get('name','未命名服务')
        self.confirmation.request(f'删除服务“{name}”及其已保存的密钥？聊天记录会保留。',lambda:self.remove_confirmed(key))
    def remove_confirmed(self,key):
        if self.load_error:return
        try:candidate,warning=delete_chat_provider(self.root,self.config,key)
        except OSError as error:self.status.setText('服务删除未提交，原配置仍有效。'+str(error));return
        self.config=candidate;self.drafts.pop(key,None);self.reload()
        self.status.setText('服务已删除；聊天记录保留。'+warning)
    def clear_key(self):
        if self.load_error or not self.current:return
        key=self.current['id'];name=self.fields['name'].text().strip() or self.current.get('name','未命名服务')
        self.confirmation.request(f'清除服务“{name}”的密钥？下次发送前需要重新填写。',lambda:self.clear_key_confirmed(key),'确认清除密钥')
    def clear_key_confirmed(self,key):
        if self.load_error:return
        try:committed,warning=clear_provider_key(self.root,key)
        except OSError as error:self.status.setText('密钥清除未提交，原配置仍有效。'+str(error));return
        # Only credential references change here; editing fields remain drafts.
        saved=next((p for p in committed['providers'] if p['id']==key),{})
        for provider in self.config['providers']:
            if provider['id']==key:provider['credential_id']=saved.get('credential_id','')
        if key in self.drafts:self.drafts[key]['key']=''
        if self.current and self.current['id']==key:self.fields['key'].clear();self.fields['key'].setPlaceholderText('已清除密钥，请重新填写')
        self.update_key_status();self.status.setText('密钥已清除，其他输入尚未保存。'+warning)
    def reject(self):
        self.confirmation.cancel();super().reject()
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape and self.confirmation.callback is not None:
            self.confirmation.cancel();event.accept();return
        super().keyPressEvent(event)
    def save(self):
        if self.load_error:return
        entered={key:w.text().strip() for key,w in self.fields.items()};timeout=self.timeout.value()
        try:normalized=normalize_provider({key:value for key,value in entered.items() if key!='key'}|{'timeout':timeout})
        except ProviderValidationError as error:self.validation_failed(error);return
        if not self.current:
            self.add()
            for key,value in entered.items():self.fields[key].setText(value)
            self.timeout.setValue(timeout)
        candidate=copy.deepcopy(self.config)
        current=next(p for p in candidate['providers'] if p['id']==self.current['id'])
        current.update(normalized)
        try:
            candidate.update(active=current['id'],system_prompt=self.prompt.toPlainText(),history_messages=self.count.value(),history_chars=self.chars.value())
            self.config=save_chat_config(self.root,candidate,current['id'],entered['key'])
            self.drafts.pop(current['id'],None);self.reload();self.status.setText('配置已保存；尚未验证连通，请主动发送消息验证。');self.accept()
        except OSError as error:self.status.setText('服务配置未提交；输入已保留。'+str(error))

class ChatInput(QPlainTextEdit):
    send=Signal()
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and not event.modifiers()&Qt.KeyboardModifier.ShiftModifier:
            self.send.emit();event.accept()
        else:super().keyPressEvent(event)

class ChatWindow(QWidget):
    def __init__(self,pet,root,embedded=False):
        super().__init__(pet,Qt.WindowType.Widget if embedded else Qt.WindowType.Window);self.pet=pet;self.embedded=embedded;self.root=Path(root);self.character=str(pet.settings.get('character','builtin'))
        self.store=SessionStore(root,self.character);self.session=self.store.sessions[0] if self.store.sessions else self.store.new()
        self.stream=None;self.partial='';self.busy=False;self.provider_dialog=None
        self._stream_pending=[];self._rendered_text='';self._rendered_session=None
        self.stream_timer=QTimer(self);self.stream_timer.setSingleShot(True);self.stream_timer.setInterval(33);self.stream_timer.timeout.connect(self.flush_stream)
        self.setWindowTitle('和白龙聊天');self.resize(580,650)
        self.setObjectName('chat_window')
        set_theme_style(self,'QWidget#chat_window{background:transparent;}QLabel,QCheckBox{'+FONT_CSS+'font-size:11px;color:#706879;background:transparent;}'
            'QPushButton{'+FONT_CSS+'font-size:11px;color:#75618d;background:#f5f2f7;border:1px solid #ded2e7;border-radius:6px;padding:5px 8px;}'
            'QPushButton:hover{background:#e8dff0;}QPushButton[role="primary"]{color:#ffffff;background:#75618d;border-color:#75618d;}'
            'QPushButton[role="primary"]:hover{background:#5f4c77;}QPushButton:disabled{color:#8b8195;background:#efebf2;}')
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0);self.pages=QStackedWidget();outer.addWidget(self.pages)
        self.chat_body=QWidget();self.pages.addWidget(self.chat_body);layout=QVBoxLayout(self.chat_body)
        layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        row=QHBoxLayout();row.setSpacing(5);self.sessions=ChatSessionChoice();self.sessions.setObjectName('chat_sessions');self.sessions.setMinimumWidth(0);row.addWidget(self.sessions,1)
        row.addWidget(chat_symbol('+','新建会话',self.new))
        manage=chat_symbol('⋯','会话管理',None);menu=QMenu(manage)
        for title,slot in [('清空当前会话…',self.clear),('删除当前会话…',self.delete)]:
            menu.addAction(title,lambda checked=False,s=slot:QTimer.singleShot(0,self,s))
        manage.setMenu(menu);manage.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);row.addWidget(manage)
        layout.addLayout(row);layout.addSpacing(5);self.sessions.currentIndexChanged.connect(self.switch)
        self.service_button=QPushButton();self.service_button.setObjectName('chat_service');self.service_button.setFixedHeight(27);self.service_button.clicked.connect(self.provider)
        self.service_button.setAccessibleName('配置聊天服务');self.service_button.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(self.service_button,'QPushButton{background:#f5f2f7;border:0;border-radius:7px;padding:0;min-height:27px;max-height:27px;}QPushButton:hover{background:#e8dff0;}')
        service_layout=QHBoxLayout(self.service_button);service_layout.setContentsMargins(8,0,8,0);service_layout.setSpacing(10)
        self.service_name=QLabel();self.service_model=QLabel();self.service_model.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        for label in (self.service_name,self.service_model):label.setTextFormat(Qt.TextFormat.PlainText);label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);label.setMinimumWidth(0)
        set_theme_style(self.service_name,FONT_CSS+'font-size:10px;color:#706879;background:transparent;');set_theme_style(self.service_model,FONT_CSS+'font-size:10px;color:#75618d;background:transparent;')
        service_layout.addWidget(self.service_name,1);service_layout.addWidget(self.service_model,1);layout.addWidget(self.service_button);layout.addSpacing(10);self.refresh_service_summary()
        self.confirmation=InlineConfirmation();layout.addWidget(self.confirmation)
        self.transcript=hide_scrollbars(ChatTranscript());self.transcript.setObjectName('chat_transcript');layout.addWidget(self.transcript,1)
        self.status=ChatNotice();layout.addWidget(self.status)
        self.compose=QWidget();self.compose.setObjectName('chat_compose');self.compose.setFixedHeight(82);set_theme_style(self.compose,'QWidget#chat_compose{background:#f5f2f7;border:1px solid #ded2e7;border-radius:11px;}')
        composer=QVBoxLayout(self.compose);composer.setContentsMargins(8,8,8,8);composer.setSpacing(5)
        self.input=hide_scrollbars(ChatInput());self.input.setObjectName('chat_input');self.input.setFixedHeight(34);self.input.setPlaceholderText('想说点什么…');self.input.send.connect(self.send)
        set_theme_style(self.input,'QPlainTextEdit{'+FONT_CSS+'font-size:12px;color:#393343;background:transparent;border:0;padding:0;selection-background-color:#e8dff0;selection-color:#393343;}')
        composer.addWidget(self.input)
        row=QHBoxLayout();row.setContentsMargins(0,0,0,0);row.setSpacing(5)
        hint=ChatNotice('Enter 发送 / Shift + Enter 换行');set_theme_style(hint,FONT_CSS+'font-size:9px;color:#706879;background:transparent;');row.addWidget(hint,1)
        self.retry_button=self.transcript.retry_button;self.retry_button.setAccessibleName('重试上条消息');self.retry_button.clicked.connect(self.retry)
        self.transcript.copy_button.clicked.connect(self.copy_reply)
        self.send_button=chat_symbol('↑','发送',self.send);self.send_button.setProperty('role','primary');self.send_button.setFixedSize(28,25);row.addWidget(self.send_button)
        self.stop_button=QPushButton('■');self.stop_button.setAccessibleName('停止回复');self.stop_button.setToolTip('停止');self.stop_button.setFixedSize(28,25);self.stop_button.clicked.connect(self.stop);row.addWidget(self.stop_button)
        composer.addLayout(row);layout.addSpacing(7);layout.addWidget(self.compose)
        self.follow=QCheckBox('跟随桌宠');self.follow.setChecked(pet.settings.get('chat_follow',False));self.follow.toggled.connect(self.save_follow);layout.addWidget(self.follow)
        if embedded:self.follow.hide()
        self.reload();self.follow_timer=QTimer(self);self.follow_timer.timeout.connect(self.follow_pet)
        if not embedded:self.follow_timer.start(250)
    def refresh_service_summary(self):
        try:
            config=load_chat_config(self.root)
            service=next((p for p in config.get('providers',[]) if p['id']==config.get('active')),None)
        except OSError:service=None
        self._service_name=service.get('name','聊天服务') if service else '设置聊天服务'
        self._service_model=service.get('model','') if service else '尚未配置'
        self.service_button.setToolTip(self._service_name+' / '+self._service_model)
        self._fit_service_summary()
    def _fit_service_summary(self):
        from PySide6.QtGui import QFontMetrics
        f=ui_font(11);f.setPixelSize(10)
        for widget,text in ((self.service_name,getattr(self,'_service_name','')), (self.service_model,getattr(self,'_service_model','')+'  ›')):
            widget.setText(QFontMetrics(f).elidedText(text,Qt.TextElideMode.ElideRight,max(40,widget.width())))
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'service_button'):QTimer.singleShot(0,self,self._fit_service_summary)
    def save_follow(self,value):self.pet.settings['chat_follow']=value;self.pet.save_settings()
    def follow_pet(self):
        if not self.isVisible() or self.isMinimized() or not self.follow.isChecked():return
        screen=__import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication.screenAt(self.pet.frameGeometry().center())
        if not screen:return
        a=screen.availableGeometry();x=self.pet.x()-self.width()-12
        if x<a.left():x=self.pet.x()+self.pet.width()+12
        self.move(max(a.left(),min(x,a.right()-self.width()+1)),max(a.top(),min(self.pet.y(),a.bottom()-self.height()+1)))
    def reload(self):
        self.sessions.blockSignals(True);self.sessions.clear()
        for s in self.store.sessions:self.sessions.addItem(s['title'],s['id'])
        self.sessions.setCurrentIndex(self.sessions.findData(self.session['id']));self.sessions.blockSignals(False);self.render()
    def _replace_text(self,text):
        from performance_metrics import METRICS
        with METRICS.span('chat_document_update'):
            bar=self.transcript.verticalScrollBar();at_end=bar.value()>=bar.maximum()-10;scroll=bar.value()
            # An independent end cursor leaves the user's selection untouched.
            if self._rendered_session==self.session['id'] and text.startswith(self._rendered_text):
                suffix=text[len(self._rendered_text):]
                if suffix:
                    cursor=QTextCursor(self.transcript.document());cursor.movePosition(QTextCursor.MoveOperation.End);cursor.insertText(suffix)
                    METRICS.add('chat_append',bytes_read=len(suffix.encode('utf-8')))
            elif text!=self._rendered_text or self._rendered_session!=self.session['id']:
                self.transcript.setPlainText(text);METRICS.add('chat_full_reset')
            self._rendered_text=text;self._rendered_session=self.session['id']
            bar.setValue(bar.maximum() if at_end else scroll)
    def render(self):
        self.stream_timer.stop();self._stream_pending.clear()
        messages=list(self.session['messages'])
        if self.busy:messages.append(dict(role='assistant',content=self.partial))
        text=self.transcript.set_message_layout(messages,self.busy)
        self._replace_text(text)
        self.transcript.refresh_theme_colors()
        self.send_button.setEnabled(not self.busy);self.send_button.setVisible(not self.busy)
        self.retry_button.setEnabled(not self.busy);self.retry_button.setVisible(bool(self.session['messages']) and not self.busy)
        self.stop_button.setEnabled(self.busy);self.stop_button.setVisible(self.busy)
        self.transcript._position_actions()
    def flush_stream(self):
        self.stream_timer.stop()
        if not self._stream_pending:return
        suffix=''.join(self._stream_pending);self._stream_pending.clear()
        if self.busy:self._replace_text(self._rendered_text+suffix)
    def switch(self):
        self.confirmation.cancel()
        if self.busy:self.stop()
        selected=next((s for s in self.store.sessions if s['id']==self.sessions.currentData()),None)
        if selected:self.session=selected;self.render()
    def new(self):self.confirmation.cancel();self.stop();self.session=self.store.new();self.reload()
    def clear(self):
        key=self.session['id'];name=self.session['title']
        self.confirmation.request(f'清空会话“{name}”的全部消息？会保留会话；正在生成的回复也将停止，此操作不可撤销。',lambda:self.clear_confirmed(key),'确认清空')
    def clear_confirmed(self,key):
        if self.session['id']!=key:return
        self.stop();messages=self.session['messages'];self.session['messages']=[]
        try:self.store.save();self.status.setText('当前会话消息已清空。')
        except OSError:self.session['messages']=messages;self.status.setText('清空失败，原消息已保留。')
        self.render()
    def delete(self):
        key=self.session['id'];name=self.session['title']
        self.confirmation.request(f'删除整个会话“{name}”及其消息？正在生成的回复也将停止，此操作不可撤销。',lambda:self.delete_confirmed(key))
    def delete_confirmed(self,key):
        if self.session['id']!=key:return
        self.stop();previous=self.store.sessions;remaining=[s for s in previous if s['id']!=key]
        if not remaining:remaining=[dict(id=uuid.uuid4().hex,title='新对话',messages=[],at=time.time())]
        self.store.sessions=remaining
        try:self.store.save()
        except OSError:self.store.sessions=previous;self.status.setText('删除失败，原会话已保留。');return
        self.session=remaining[0];self.reload();self.status.setText('会话已删除。')
    def provider(self):
        self.confirmation.cancel()
        if self.embedded:
            if not self.provider_dialog:
                self.provider_dialog=ProviderDialog(self.root,self,embedded=True)
                self.provider_page=self.provider_dialog
                self.pages.addWidget(self.provider_page)
                self.provider_dialog.finished.connect(self.provider_finished)
            self.provider_dialog.prepare_visit();self.pages.setCurrentWidget(self.provider_page);self.provider_dialog.show();return
        if self.provider_dialog and self.provider_dialog.isVisible():self.provider_dialog.raise_();return
        self.provider_dialog=ProviderDialog(self.root,self);self.provider_dialog.finished.connect(self.provider_finished);self.provider_dialog.show()
    def provider_finished(self,result):
        if self.embedded:self.pages.setCurrentWidget(self.chat_body)
        self.refresh_service_summary()
        if result==QDialog.DialogCode.Accepted:self.status.setText('聊天配置已保存；尚未验证连通，发送消息时才会请求服务。')
    def send(self):
        self.confirmation.cancel()
        if self.busy:return
        text=self.input.toPlainText().strip()
        if not text:return
        if len(text)>50000:self.status.setText('单条消息请控制在50000字以内。');return
        self.start(text,False)
    def retry(self):
        if self.busy:return
        messages=copy.deepcopy(self.session['messages'])
        if messages and messages[-1]['role']=='assistant':messages.pop()
        if messages and messages[-1]['role']=='user':self.start(messages[-1]['content'],True)
    def copy_reply(self):
        if self.session['messages'] and self.session['messages'][-1]['role']=='assistant':
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self.session['messages'][-1]['content'])
    def start(self,text,retry):
        try:config=load_chat_config(self.root)
        except OSError as error:self.status.setText('聊天配置无法读取，原文件和输入已保留。'+str(error));return
        provider=next((p for p in config.get('providers',[]) if p['id']==config.get('active')),None)
        if not provider:self.status.setText('请先在“聊天服务”中配置接口地址、模型和密钥。');self.provider();return
        try:provider=normalize_provider(provider);key=load_provider_key(self.root,provider)
        except ProviderValidationError as error:self.status.setText(str(error)+' 请在“聊天服务”中修改，输入已保留。');return
        except OSError as error:self.status.setText('无法读取聊天凭据，原文件和输入已保留。'+str(error));return
        messages=copy.deepcopy(self.session['messages'])
        if retry and messages and messages[-1]['role']=='assistant':messages.pop()
        if not retry:messages.append(dict(role='user',content=text))
        prompt=self.pet.manifest.get('systemPrompt') or config.get('system_prompt',CHAT_DEFAULT['system_prompt'])
        payload=[dict(role='system',content=prompt)]+trim_messages(messages,config.get('history_messages',40),config.get('history_chars',24000))
        stream=ChatStream(self);self.stream=stream;self.partial='';self.busy=True
        stream.delta.connect(lambda value:self.on_delta(stream,value));stream.done.connect(lambda value:self.on_done(stream,value))
        stream.failed.connect(lambda message:self.on_error(stream,message))
        try:stream.start(provider,key,payload)
        except (ValueError,OSError) as error:
            self.busy=False;stream.deleteLater();self.stream=None;self.status.setText(str(error));self.render();return
        self.session['messages']=messages;self.session['title']=text[:24]
        try:self.store.save()
        except OSError:
            self.stream=None;self.busy=False;stream.cancel();stream.deleteLater()
            self.status.setText('聊天记录保存失败；输入已保留，请检查磁盘空间和目录权限。');self.render();return
        self.input.clear()
        self.status.setText('白龙正在回复…');self.reload()
    def on_delta(self,stream,value):
        if stream is self.stream and self.busy:
            self.partial+=value;self._stream_pending.append(value)
            if not self.stream_timer.isActive():self.stream_timer.start()
    def on_done(self,stream,value):
        if stream is not self.stream or not self.busy:return
        self.flush_stream()
        if value:self.session['messages'].append(dict(role='assistant',content=value))
        try:
            self.store.save();self.status.setText('')
        except OSError:
            self.status.setText('回复已完成，但记录保存失败；请先复制回复，并检查磁盘空间和目录权限。')
        finally:
            self.busy=False;self.stream=None;stream.deleteLater();self.render()
    def on_error(self,stream,message):
        if stream is not self.stream or not self.busy:return
        self.busy=False;self.stream=None;stream.deleteLater();self.status.setText(message+'；上条消息已保留，可重试。');self.render()
    def stop(self):
        self.stream_timer.stop();self._stream_pending.clear()
        if self.stream:
            stream=self.stream;self.stream=None;self.busy=False;stream.cancel();stream.deleteLater()
            self.status.setText('已停止；未完成回复没有加入历史。')
        self.partial='';self.render()
    def closeEvent(self,event):self.stop();self.hide();event.ignore()
    def keyPressEvent(self,event):
        if self.embedded and event.key()==Qt.Key.Key_Escape:
            if self.confirmation.callback is not None:self.confirmation.cancel()
            elif self.provider_dialog and self.pages.currentWidget() is self.provider_page:self.provider_dialog.reject()
            else:self.pet.bubble.return_to_status()
            event.accept();return
        super().keyPressEvent(event)
    def shutdown(self):self.stop();self.follow_timer.stop();self.hide()
