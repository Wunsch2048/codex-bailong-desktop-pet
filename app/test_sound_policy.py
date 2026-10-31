"""Sound stays inside genuine visible interaction; test windows stay silent."""
import os,sys,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from pet import Pet

@unittest.skipUnless(sys.platform=='win32','Windows audio sink')
class AudioSinkPolicyTests(unittest.TestCase):
    def test_isolated_native_probe_never_reaches_windows_audio(self):
        with patch.dict(os.environ,{'BAILONG_ISOLATED':'1'}),patch('pet.QApplication.platformName',return_value='windows'),patch('winsound.PlaySound') as audio:
            Pet.play_click_sound(SimpleNamespace());audio.assert_not_called()
    def test_offscreen_synthetic_click_is_silent_even_without_isolation_flag(self):
        with patch.dict(os.environ,{'BAILONG_ISOLATED':'0'}),patch('pet.QApplication.platformName',return_value='offscreen'),patch('winsound.PlaySound') as audio:
            Pet.play_click_sound(SimpleNamespace());audio.assert_not_called()
    def test_normal_windows_manual_audio_sink_is_preserved(self):
        with patch.dict(os.environ,{'BAILONG_ISOLATED':'0'}),patch('pet.QApplication.platformName',return_value='windows'),patch('winsound.PlaySound') as audio:
            Pet.play_click_sound(SimpleNamespace());audio.assert_called_once()

class PendingClickTests(unittest.TestCase):
    import test_edge_dock as fixture
    setUp=fixture.DockTests.setUp
    tearDown=fixture.DockTests.tearDown
    def test_hide_cancels_delayed_click_without_starting_a_new_action(self):
        self.p.last_click=time.monotonic();self.p.click_timer.start(30)
        with patch.object(self.p,'choose') as choose:
            self.p.hide();QTest.qWait(60);choose.assert_not_called()
        self.assertFalse(self.p.click_timer.isActive());self.assertIsNone(self.p.last_click)
    def test_close_cancels_click_before_the_next_window_pumps_events(self):
        self.p.last_click=time.monotonic();self.p.click_timer.start(30)
        with patch.object(self.p,'choose') as choose:
            self.p.close();QTest.qWait(60);choose.assert_not_called()
        self.assertFalse(self.p.click_timer.isActive());self.assertIsNone(self.p.last_click)

if __name__=='__main__':unittest.main()
