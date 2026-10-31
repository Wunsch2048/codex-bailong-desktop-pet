"""Remote-screen restore must not retain undersized decoded frames."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import Mock,patch
from PySide6.QtCore import QObject
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from decode_runtime import display_decode_size
from desktop import DesktopPet
APP=QApplication.instance() or QApplication([])

class Owner(QObject):
    desired_decode_size=DesktopPet.desired_decode_size
    request_decode_sync=DesktopPet.request_decode_sync
    sync_decode_size=DesktopPet.sync_decode_size
    def __init__(self):
        super().__init__();self.settings={'scale':1};self.dpr=.5;self.frame_size=128
        self.player=Mock(size=128);self.sustained=Mock(active=False)
        self.player.resize.side_effect=lambda size:QPixmap(size,size)
        self.update_frame=Mock()
    def devicePixelRatioF(self):return self.dpr
    def height(self):raise AssertionError('Transient native height is not display policy')

class DecodeGeometryTests(unittest.TestCase):
    def test_physical_policy_preserves_fractional_dpi_and_source_cap(self):
        for scale,dpr,result in ((1,1,256),(1,1.25,320),(1,1.5,384),(.5,1,128),(2.5,2,720)):
            self.assertEqual(display_decode_size(scale,dpr),result)
    def test_restored_display_uses_configured_size_not_transient_native_height(self):
        owner=Owner();owner.dpr=1
        self.assertEqual(owner.desired_decode_size(),256)
        owner.sync_decode_size();self.assertEqual(owner.frame_size,256)
        self.assertEqual(owner.frames[0].width(),256);self.assertEqual(owner._hit_image.width(),256)
    def test_metric_requests_read_settled_dpi_and_coalesce(self):
        owner=Owner();queued=[]
        with patch('desktop.QTimer.singleShot',side_effect=lambda delay,context,callback:queued.append(callback)):
            owner.request_decode_sync();owner.request_decode_sync()
        self.assertEqual(len(queued),1)
        owner.dpr=1;queued[0]()
        owner.player.resize.assert_called_once_with(256)
        self.assertFalse(owner._decode_sync_pending)
    def test_same_metrics_do_not_redecode(self):
        owner=Owner();queued=[]
        with patch('desktop.QTimer.singleShot',side_effect=lambda delay,context,callback:queued.append(callback)):owner.request_decode_sync()
        queued[0]();owner.player.resize.assert_not_called()

if __name__=='__main__':unittest.main()
