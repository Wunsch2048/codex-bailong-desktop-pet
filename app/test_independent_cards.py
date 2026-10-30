import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest,time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QToolButton
from PySide6.QtCore import QPoint,Qt,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from desktop import DesktopPet
from desktop_core import normalized

APP=QApplication.instance() or QApplication([])

class IndependentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.patches=[patch(module+'.'+key,root/('settings.json' if key=='CONFIG' else '')) for module in ('enhanced','desktop') for key in ('CONFIG','STATE_DIR')]
        for p in self.patches:p.start()
        self.pet=DesktopPet(monitor=False);self.pet.apply_settings(dict(wandering=False,random_actions=False));self.pet.show();APP.processEvents()
    def tearDown(self):
        self.pet.close();APP.processEvents()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def finish(self):self.pet.bubble.size_transition.complete();self.pet.bubble.size_transition.release_landing();APP.processEvents()
    def test_card_only_pauses_decode_and_keeps_quota_status_and_notifications(self):
        p=self.pet;p.apply_settings(dict(character_visible=False));APP.processEvents()
        self.assertFalse(p.isVisible());self.assertTrue(p.bubble.isVisible());self.assertIsNone(p.bubble.parentWidget());self.assertIs(p.bubble.owner_pet(),p)
        self.assertFalse(p.tick.isActive());self.assertIsNone(p.player.thread)
        p.update_quota([dict(name='一周',remaining=63,resetsAt=None)],time.time(),'session')
        p.on_activity(dict(kind='status',session='fake',turn='one',state='thinking',active=1,text='验收状态'))
        self.assertEqual(p.bubble.windows[0]['remaining'],63);self.assertTrue(p.bubble.isVisible());self.assertIsNone(p.player.thread)
        with patch.object(p,'notify'),patch.object(p,'refresh_quota'):p.on_activity(dict(kind='complete',session='fake',turn='one',title='验收'))
        self.assertTrue(p.bubble.status_indicator.unread);self.assertFalse(p.isVisible());self.assertIsNone(p.player.thread)
        with patch('pet.Pet.play_click_sound') as sound:p.choose(p.variants[0],interactive=True,manual=True);sound.assert_not_called()
        self.assertIsNone(p.player.thread)
    def test_restore_character_and_global_hide_recover_respect_preference(self):
        p=self.pet;p.apply_settings(dict(character_visible=False));p.toggle_pet();self.assertFalse(p.bubble.isVisible())
        p.bubble.redraw();self.assertFalse(p.bubble.isVisible());p.recover();self.assertTrue(p.bubble.isVisible());self.assertFalse(p.isVisible())
        p.apply_settings(dict(character_visible=True));self.assertTrue(p.isVisible());self.assertTrue(p.tick.isActive());self.assertIsNotNone(p.player.thread)
    def test_fullscreen_yield_hides_surfaces_but_tray_owner_stays_alive(self):
        p=self.pet;p.set_fullscreen_yield(True);self.assertTrue(p._fullscreen_yielded);self.assertFalse(p.isVisible());self.assertFalse(p.bubble.isVisible())
        p.set_fullscreen_yield(False);self.assertFalse(p._fullscreen_yielded);self.assertTrue(p.isVisible());self.assertTrue(p.bubble.isVisible())
    def test_modes_are_persistent_peers_and_minimal_has_only_one_button(self):
        p=self.pet;p.apply_settings(dict(character_visible=False));b=p.bubble
        for mode,size in [('minimal',54),('mini',210),('minimal',54),('auto',268)]:
            b.set_mode(mode);self.finish();self.assertEqual(b.width(),size);self.assertEqual(p.settings['bubble_mode'],mode)
        b.set_mode('minimal');self.finish()
        self.assertTrue(b.is_minimal());self.assertFalse(b.is_island());self.assertEqual(b.height(),54)
        visible=[w for w in b.findChildren(QToolButton) if w.isVisible()];self.assertEqual([w.objectName() for w in visible],['minimal_quota'])
        self.assertTrue(b.status_view.isHidden());self.assertTrue(b.status_indicator.isHidden())
        b.task_updated(dict(kind='status'));self.assertTrue(b.is_minimal())
        b.minimal_quota.click();self.finish();self.assertFalse(b.is_compact());self.assertFalse(b.expanded)
        self.assertEqual(b.bubble_mode,'minimal');self.assertEqual(p.settings['bubble_mode'],'minimal')
        compact=next(w for w in b.findChildren(QToolButton,'bubble_compact') if w.isVisible())
        compact.click();self.finish();self.assertTrue(b.is_minimal());self.assertEqual(b.width(),54)
        b.minimal_quota.click();self.finish();self.assertFalse(b.is_minimal())
        b.evaluate_mode(b.last_task_update+91);self.finish();self.assertTrue(b.is_minimal())
        self.assertEqual(p.settings['bubble_mode'],'minimal')
    def test_drag_preserves_mode_and_saved_anchor_across_sizes(self):
        p=self.pet;p.apply_settings(dict(character_visible=False));b=p.bubble;b.set_mode('minimal');self.finish()
        target=b.pos()+QPoint(-60,-80);p.move_card(target);center=b.geometry().center().x();bottom=b.geometry().bottom()
        anchor=dict(p.settings['card_anchor']);b.set_mode('auto');self.finish()
        self.assertAlmostEqual(b.geometry().center().x(),center,delta=1);self.assertEqual(b.geometry().bottom(),bottom)
        self.assertEqual(p.settings['card_anchor'],anchor)
        b.set_mode('minimal');self.finish();circle=b.minimal_quota
        start=circle.mapToGlobal(circle.rect().center());end=start+QPoint(-25,0)
        for kind,global_pos,button,buttons in ((QEvent.Type.MouseButtonPress,start,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton),(QEvent.Type.MouseMove,end,Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton),(QEvent.Type.MouseButtonRelease,end,Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)):
            event=QMouseEvent(kind,QPointF(circle.mapFromGlobal(global_pos)),QPointF(global_pos),button,buttons,Qt.KeyboardModifier.NoModifier);APP.sendEvent(circle,event)
        self.assertTrue(b.is_minimal());self.assertFalse(b.size_transition.running)
    def test_settings_draft_saves_mode_even_when_current_page_is_editor(self):
        p=self.pet;p.open_settings();self.finish();s=p.settings_dialog
        s.fields['character_visible'].setChecked(False);s.mode.setCurrentIndex(s.mode.findData('minimal'));s.apply();APP.processEvents()
        self.assertFalse(p.isVisible());self.assertEqual(p.bubble.panel_page,'settings');self.assertTrue(p.bubble.isVisible())
        p.bubble.return_to_status();self.finish();self.assertTrue(p.bubble.is_minimal());self.assertEqual(p.settings['bubble_mode'],'minimal')
    def test_video_ownership_and_normalization_keep_independent_card_covered(self):
        from video_yield import VideoYield
        p=self.pet
        class Holder:pet=p
        self.assertTrue(VideoYield.owned(Holder(),p.bubble));self.assertEqual(normalized({'bubble_mode':'minimal'})['bubble_mode'],'minimal')
        self.assertEqual(normalized({'bubble_mode':'garbage'})['bubble_mode'],'auto')
        self.assertEqual(normalized({'video_fullscreen_yield':False})['fullscreen_yield_mode'],'off')
        self.assertEqual(normalized({'video_fullscreen_yield':True})['fullscreen_yield_mode'],'video')
        self.assertEqual(normalized({'fullscreen_yield_mode':'all'})['fullscreen_yield_mode'],'game_video')
        self.assertFalse(normalized({'fullscreen_yield_mode':'all'})['video_fullscreen_yield'])

if __name__=='__main__':unittest.main()
