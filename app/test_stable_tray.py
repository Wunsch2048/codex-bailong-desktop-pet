import os,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon,QPixmap,QColor
from stable_tray import StableTray,prepare_host
APP=QApplication.instance() or QApplication([])

class Socket:
    def __init__(self,data):self.data=data;self.sent=[];self.closed=False
    def readAll(self):data=self.data;self.data=b'';return data
    def write(self,data):self.sent.append(data)
    def flush(self):pass
    def disconnectFromServer(self):self.closed=True

class StableTrayTests(unittest.TestCase):
    def tray(self):
        image=QPixmap(24,24);image.fill(QColor('#75618d'));return StableTray(QIcon(image))
    def test_authenticated_handshake_sends_existing_icon_and_ready(self):
        tray=self.tray();socket=Socket((json.dumps(dict(kind='connected',secret=tray.nonce))+'\n'+json.dumps(dict(kind='ready',secret=tray.nonce,ok=True))+'\n').encode());tray.socket=socket
        tray._read();self.assertTrue(tray.ready);self.assertTrue(json.loads(socket.sent[0])['png']);self.assertEqual(tray.toolTip(),'');tray.socket=None;tray.deleteLater()
    def test_other_client_does_not_get_icon_or_register_identity(self):
        tray=self.tray();socket=Socket(b'{"kind":"connected","secret":"wrong"}\n');tray.socket=socket;tray._read()
        self.assertTrue(socket.closed);self.assertFalse(socket.sent);self.assertFalse(tray.ready);tray.socket=None;tray.deleteLater()
    def test_version_payloads_reuse_one_target_and_backup_previous_component(self):
        with tempfile.TemporaryDirectory() as folder,patch('psutil.process_iter',return_value=[]):
            root=Path(folder);a=root/'version-a.exe';b=root/'version-b.exe';a.write_bytes(b'first');b.write_bytes(b'next')
            first=prepare_host(a,root/'install');second=prepare_host(b,root/'install')
            self.assertEqual(first,second);self.assertEqual(second.read_bytes(),b'next');self.assertEqual(second.with_suffix('.previous').read_bytes(),b'first')

if __name__=='__main__':unittest.main()
