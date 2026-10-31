"""Keep settings captures populated and header actions correct through reuse."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QToolButton,QLabel
from surface_morph import complete_frame,pixel_size
from test_project_cost_motion import ink_count

class EditorHandoffTests(unittest.TestCase):
    import test_edge_dock as fixture
    def setUp(self):
        self.fixture.DockTests.setUp(self)
        # Compare layout pixels at one glyph phase, not two clock instants.
        self.p.bubble.status_indicator.clock=lambda:0.
    tearDown=fixture.DockTests.tearDown
    def target(self):
        transition=self.p.bubble.size_transition
        if transition.same_size_fade:return transition.cover.next_image.copy(),transition.cover.geometry()
        if transition.morph is not None:return transition.morph.end.frame.copy(),None
        return complete_frame(self.p.bubble),None
    def test_status_settings_both_targets_have_body_and_remain_usable_after_reuse(self):
        b=self.p.bubble;b.set_mode('auto');self.fixture.settle(self.p);b.show_status(True);self.fixture.settle(self.p)
        for _ in range(2):
            self.p.open_settings();image,_=self.target();self.assertGreater(ink_count(image),400)
            self.fixture.settle(self.p);self.assertEqual(b.panel_page,'settings')
            self.assertFalse(b.editor_codex_button.isVisible());self.assertTrue(self.p.settings_dialog.isVisible())
            b.return_to_status();image,_=self.target();self.assertGreater(ink_count(image),400)
            self.fixture.settle(self.p);self.assertEqual(b.panel_page,'status');self.assertTrue(b.updatesEnabled())
    def test_settings_header_hides_codex_when_reusing_chat_header(self):
        b=self.p.bubble;chat=QLabel('合成聊天页');settings=QLabel('合成设置页')
        b.show_page('chat',chat);self.fixture.settle(self.p);self.assertTrue(b.editor_codex_button.isVisible())
        b.show_page('settings',settings);self.fixture.settle(self.p);self.assertFalse(b.editor_codex_button.isVisible())
        b.show_page('chat',chat);self.fixture.settle(self.p);self.assertTrue(b.editor_codex_button.isVisible())
        b.return_to_status();self.fixture.settle(self.p)
    def test_settings_target_raster_matches_stable_body(self):
        b=self.p.bubble;b.set_mode('auto');self.fixture.settle(self.p);b.show_status(True);self.fixture.settle(self.p)
        self.p.open_settings();image,rect=self.target();self.fixture.settle(self.p);stable=complete_frame(b)
        if rect is not None:
            ratio=stable.devicePixelRatioF();stable=stable.copy(QRect(pixel_size(rect.x(),ratio),pixel_size(rect.y(),ratio),pixel_size(rect.width(),ratio),pixel_size(rect.height(),ratio)))
        self.assertEqual(image.toImage(),stable.toImage())

if __name__=='__main__':unittest.main()
