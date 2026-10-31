"""Chat page layout/streaming checks with in-memory sessions and no services."""
import copy
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout
from chat_config import CHAT_DEFAULT
from chat_window import ChatWindow
from theme_registry import activate,color
from typography import install_ui_font

APP=QApplication.instance() or QApplication([])
install_ui_font(APP)


class MemorySessions:
    def __init__(self,*args):
        self.sessions=[dict(id='demo',title='演示会话',messages=[])]
    def save(self):pass
    def new(self):
        value=dict(id=str(len(self.sessions)),title='新对话',messages=[])
        self.sessions.insert(0,value);return value


class LargeChatUiTests(unittest.TestCase):
    def setUp(self):
        activate('bailong',{})
        config=copy.deepcopy(CHAT_DEFAULT)
        config.update(active='demo',providers=[dict(id='demo',name='演示服务',model='example-chat',base_url='http://localhost/v1',timeout=90)])
        self.patches=[patch('chat_window.SessionStore',MemorySessions),patch('chat_window.load_chat_config',return_value=config),patch('chat_window.provider_key_present',return_value=False)]
        for item in self.patches:item.start()
        self.pet=QWidget();self.pet.settings={};self.pet.manifest={};self.pet.save_settings=lambda:None
        self.host=QWidget();layout=QVBoxLayout(self.host);layout.setContentsMargins(0,0,0,0)
        self.chat=ChatWindow(self.pet,'unused-in-memory-chat-root',embedded=True);layout.addWidget(self.chat)
        self.host.resize(334,386);self.host.show();APP.processEvents()
    def tearDown(self):
        self.chat.shutdown();self.host.hide();self.host.deleteLater();self.pet.deleteLater();APP.processEvents()
        for item in reversed(self.patches):item.stop()
        activate('bailong',{})
    def test_long_messages_scroll_inside_fixed_composer(self):
        self.chat.session['messages']=[dict(role='assistant',content='说明内容\n'*120)];self.chat.render();APP.processEvents()
        composer=self.chat.compose.geometry()
        self.assertEqual(composer.bottom(),self.chat.chat_body.height()-1)
        self.assertLess(self.chat.transcript.geometry().bottom(),composer.top())
        self.assertGreater(self.chat.transcript.verticalScrollBar().maximum(),0)
        self.assertEqual(self.chat.transcript.verticalScrollBarPolicy(),Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(self.chat.width(),334)
    def test_real_bubble_round_trip_keeps_chat_and_provider_drafts(self):
        from compact_bubble import CompactBubble
        bubble=CompactBubble();self.pet.bubble=bubble;bubble.show();APP.processEvents()
        try:
            self.chat.input.setPlainText('尚未发出的草稿')
            bubble.show_page('chat',self.chat);bubble.size_transition.complete();APP.processEvents()
            self.assertEqual(bubble.size().toTuple(),(360,480));self.assertEqual(self.chat.size().toTuple(),(334,386))
            bubble.show_status(False);bubble.size_transition.complete();APP.processEvents()
            bubble.show_page('chat',self.chat);bubble.size_transition.complete();APP.processEvents()
            self.assertEqual(self.chat.input.toPlainText(),'尚未发出的草稿')
            self.chat.provider();editor=self.chat.provider_dialog;editor.fields['model'].setText('unsaved-model')
            bubble.show_status(False);bubble.size_transition.complete();APP.processEvents()
            bubble.show_page('chat',self.chat);bubble.size_transition.complete();APP.processEvents()
            self.assertEqual(editor.fields['model'].text(),'unsaved-model');self.assertEqual(self.chat.input.toPlainText(),'尚未发出的草稿')
            self.assertEqual(editor.size().toTuple(),(334,386))
            self.host.layout().addWidget(self.chat)
        finally:
            bubble.size_transition.complete();bubble.close();bubble.deleteLater();APP.processEvents()
    def test_provider_visit_resets_scroll_but_preserves_unsaved_draft(self):
        self.chat.input.setPlainText('尚未发送的输入');self.chat.provider();editor=self.chat.provider_dialog
        editor.advanced_toggle.setChecked(True);editor.fields['model'].setText('unsaved-model');APP.processEvents()
        bar=editor.body_scroll.verticalScrollBar();bar.setValue(bar.maximum());self.assertGreater(bar.value(),0)
        editor.reject();self.chat.provider();APP.processEvents()
        self.assertEqual(bar.value(),0);self.assertEqual(editor.fields['model'].text(),'unsaved-model')
        self.assertEqual(self.chat.input.toPlainText(),'尚未发送的输入')
        footer=editor.findChild(QWidget,'provider_footer')
        self.assertEqual(footer.geometry().bottom(),editor.height()-1)
        self.assertLess(editor.body_scroll.geometry().bottom(),footer.y())
    def test_stream_append_keeps_selection_and_scroll(self):
        self.chat.session['messages']=[dict(role='user',content='长会话\n'*80)];self.chat.busy=True;self.chat.partial='回复';self.chat.render();APP.processEvents()
        cursor=self.chat.transcript.textCursor();cursor.setPosition(6);cursor.setPosition(12,QTextCursor.MoveMode.KeepAnchor);self.chat.transcript.setTextCursor(cursor)
        selected=cursor.selectedText();bar=self.chat.transcript.verticalScrollBar();bar.setValue(0)
        with patch.object(self.chat.transcript,'setPlainText',wraps=self.chat.transcript.setPlainText) as replace:
            self.chat._stream_pending=['追加内容'];self.chat.flush_stream();replace.assert_not_called()
        self.assertEqual(self.chat.transcript.textCursor().selectedText(),selected);self.assertEqual(bar.value(),0)
        self.assertTrue(self.chat.transcript.toPlainText().endswith('回复追加内容'))
    def test_role_like_text_and_emoji_do_not_create_false_message_bubbles(self):
        self.chat.session['messages']=[dict(role='user',content='🙂\n白龙：\n这也是我的文字'),dict(role='assistant',content='我：\n这是回复引用')]
        self.chat.render()
        self.assertEqual(len(self.chat.transcript._user_ranges),1)
        block=self.chat.transcript.document().findBlockByNumber(1)
        self.assertEqual(block.text(),'白龙：');self.assertGreater(block.blockFormat().leftMargin(),11)
        last=self.chat.transcript.document().lastBlock();self.assertEqual(last.blockFormat().leftMargin(),3)
    def test_theme_recolors_document_without_losing_selection(self):
        self.chat.session['messages']=[dict(role='user',content='主题预览'),dict(role='assistant',content='保留选择与输入')];self.chat.render()
        cursor=self.chat.transcript.textCursor();cursor.setPosition(4);cursor.setPosition(6,QTextCursor.MoveMode.KeepAnchor);self.chat.transcript.setTextCursor(cursor)
        selected=cursor.selectedText();self.chat.input.setPlainText('保留草稿')
        activate('cyber',{});self.chat.transcript.refresh_theme_colors()
        block=self.chat.transcript.document().lastBlock();fragment=block.begin().fragment()
        self.assertEqual(fragment.charFormat().foreground().color().name(),color('#393343'))
        self.assertEqual(self.chat.transcript.textCursor().selectedText(),selected);self.assertEqual(self.chat.input.toPlainText(),'保留草稿')
    def test_reply_actions_fit_on_first_reply_and_copy_only_its_content(self):
        self.chat.session['messages']=[dict(role='user',content='问题'),dict(role='assistant',content='这是回复内容')];self.chat.render();APP.processEvents()
        transcript=self.chat.transcript
        for button in (transcript.copy_button,transcript.retry_button):
            self.assertTrue(transcript.actions.rect().contains(button.geometry()))
            self.assertGreaterEqual(button.width(),button.fontMetrics().horizontalAdvance(button.text()))
        with patch('PySide6.QtWidgets.QApplication.clipboard') as clipboard:
            transcript.copy_button.click();clipboard.return_value.setText.assert_called_once_with('这是回复内容')
    def test_enter_sends_shift_enter_keeps_newline(self):
        events=[];self.chat.input.send.connect(lambda:events.append('send'))
        # Replace only the connected action; no provider request is involved.
        self.chat.input.send.disconnect(self.chat.send)
        self.chat.input.setFocus();QTest.keyClick(self.chat.input,Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.chat.input.toPlainText(),'\n');self.assertEqual(events,[])
        QTest.keyClick(self.chat.input,Qt.Key.Key_Return);self.assertEqual(events,['send'])


if __name__=='__main__':unittest.main()
