"""A flag update must not temporarily discard the translucent HWND surface."""
import os,sys,ctypes,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtCore import Qt,QByteArray
from PySide6.QtWidgets import QWidget,QApplication
from native_window_style import preserve_layered_style

APP=QApplication.instance() or QApplication([])

@unittest.skipUnless(sys.platform=='win32','Windows native message layout')
class LayeredStyleTests(unittest.TestCase):
    def setUp(self):
        self.widget=QWidget();self.widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    def tearDown(self):self.widget.close();self.widget.deleteLater()
    def message(self,old=0x800a8,new=0x80,index=-20,kind=0x7c):
        from ctypes import wintypes
        styles=(ctypes.c_uint32*2)(old,new);msg=wintypes.MSG()
        msg.message=kind;msg.wParam=index&((1<<(ctypes.sizeof(ctypes.c_size_t)*8))-1);msg.lParam=ctypes.addressof(styles)
        return msg,styles
    def apply(self,msg,event_type=b'windows_generic_MSG'):
        return preserve_layered_style(self.widget,event_type,ctypes.addressof(msg))
    def test_layered_survives_while_input_and_other_flags_change(self):
        for old,new in ((0x800a8,0x80),(0x800a0,0x8000008),(0x80080,0x28)):
            msg,styles=self.message(old,new)
            self.assertTrue(self.apply(msg));self.assertEqual(styles[0],old);self.assertEqual(styles[1],new|0x80000)
    def test_existing_layered_style_is_not_rewritten(self):
        msg,styles=self.message(new=0x80088)
        self.assertFalse(self.apply(msg));self.assertEqual(styles[1],0x80088)
    def test_initial_creation_does_not_force_layered_early(self):
        msg,styles=self.message(old=0x80,new=0xa8)
        self.assertFalse(self.apply(msg));self.assertEqual(styles[1],0xa8)
    def test_opaque_windows_keep_requested_style(self):
        self.widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,False)
        msg,styles=self.message();self.assertFalse(self.apply(msg));self.assertEqual(styles[1],0x80)
    def test_normal_style_and_committed_messages_are_untouched(self):
        for index,kind in ((-16,0x7c),(-20,0x7d),(-20,0x84)):
            msg,styles=self.message(index=index,kind=kind)
            self.assertFalse(self.apply(msg));self.assertEqual(styles[1],0x80)
    def test_qbytearray_and_dispatcher_message_types(self):
        for kind in (QByteArray(b'windows_generic_MSG'),b'windows_dispatcher_MSG'):
            msg,styles=self.message();self.assertTrue(self.apply(msg,kind));self.assertEqual(styles[1],0x80080)
    def test_unknown_platform_and_event_do_not_dereference_message(self):
        self.assertFalse(preserve_layered_style(self.widget,b'xcb_generic_event_t',0))
        with patch('native_window_style.sys.platform','linux'):
            self.assertFalse(preserve_layered_style(self.widget,b'windows_generic_MSG',0))
    def test_null_style_payload_is_ignored(self):
        msg,styles=self.message();msg.lParam=0;self.assertFalse(self.apply(msg))

if __name__=='__main__':unittest.main()
