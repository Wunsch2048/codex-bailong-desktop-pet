import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint
import test_native_interactions as native
APP=native.APP

class DragPanelTests(unittest.TestCase):
    setUp=native.InteractionTests.setUp
    tearDown=native.InteractionTests.tearDown
    drag=native.InteractionTests.drag
    def settle(self):
        b=self.pet.bubble;b.size_transition.complete();b.size_transition.release_landing();APP.processEvents()
    def prepare(self,mode='auto',expanded=False):
        p=self.pet;p.apply_settings(dict(bubble_mode=mode,on_top=False,panel_detached=False),save=False)
        self.settle();p.bubble.expanded=expanded;p.bubble.redraw();p.bubble.show();self.settle()
    def release(self):
        with patch.object(self.pet.edge_dock,'try_dock',return_value=False):self.pet.mouseReleaseEvent(self.press)
        self.settle()
    def test_normal_and_large_restore_normal(self):
        for expanded in (False,True):
            self.prepare(expanded=expanded);self.drag()
            self.assertTrue(self.pet.bubble.is_island());self.assertTrue(self.pet.bubble.isVisible())
            self.release();self.assertFalse(self.pet.bubble.is_compact());self.assertFalse(self.pet.bubble.expanded)
    def test_compact_choice_is_preserved_without_saved_mode_change(self):
        for mode in ('mini','minimal'):
            self.prepare(mode);before=dict(self.pet.settings);self.drag()
            self.assertEqual(self.pet.bubble.compact_kind(),'mini' if mode=='mini' else 'minimal')
            self.release();self.assertTrue(self.pet.bubble.is_compact());self.assertEqual(self.pet.settings['bubble_mode'],before['bubble_mode'])
    def test_drag_out_of_edge_builds_capsule_once_and_release_keeps_same_ring(self):
        from island_widgets import QuotaSatellite
        for mode in ('auto','mini'):
            self.pet.edge_dock.clear(immediate=True);self.settle();self.prepare(mode)
            p=self.pet;b=p.bubble;area=p.screen().availableGeometry();p.move(area.left(),area.top()+200)
            self.assertTrue(p.edge_dock.try_dock());p.edge_dock.animation.setCurrentTime(240);self.settle()
            self.assertTrue(b.is_minimal())
            with patch.object(b,'redraw',wraps=b.redraw) as redraw:
                self.drag();self.settle();self.assertTrue(b.is_island());self.assertFalse(p.edge_dock.active)
                self.assertEqual(redraw.call_count,1)
                ring=next(w for w in b.content.findChildren(QuotaSatellite) if w.isVisibleTo(b.content))
                ring.reveal.animation.setCurrentTime(180);progress=ring.reveal.progress
                self.release()
                self.assertEqual(redraw.call_count,1,'Release must not rebuild an unchanged capsule')
                self.assertIs(next(w for w in b.content.findChildren(QuotaSatellite) if w.isVisibleTo(b.content)),ring)
                self.assertGreaterEqual(ring.reveal.progress,progress);self.assertFalse(ring.reveal.pending)
                self.assertTrue(b.is_island());self.assertEqual(b.bubble_mode,mode)
    def test_drag_out_in_minimal_mode_keeps_ring_and_does_not_replay_entry(self):
        p=self.pet;b=p.bubble;self.prepare('minimal');area=p.screen().availableGeometry();p.move(area.left(),area.top()+200)
        self.assertTrue(p.edge_dock.try_dock());p.edge_dock.animation.setCurrentTime(240);self.settle()
        ring=b.minimal_quota;ring.reveal.animation.setCurrentTime(620)
        with patch.object(b,'redraw',wraps=b.redraw) as redraw:
            self.drag();self.settle();self.assertIs(b.minimal_quota,ring);self.assertEqual(redraw.call_count,0)
            self.assertEqual(ring.reveal.progress,1.);self.assertFalse(ring.reveal.pending)
            self.release();self.assertIs(b.minimal_quota,ring);self.assertEqual(redraw.call_count,0)
            self.assertEqual(b.geometry(),b.content_geometry(docked=False))
    def test_open_minimal_returns_to_normal_then_keeps_minimal_preference(self):
        self.prepare('minimal');self.pet.bubble.open_normal_from_minimal();self.settle()
        self.drag();self.assertTrue(self.pet.bubble.is_minimal());self.release()
        self.assertFalse(self.pet.bubble.is_compact());self.assertEqual(self.pet.bubble.bubble_mode,'minimal')
    def test_detached_and_hidden_panels_are_untouched(self):
        self.prepare();p=self.pet;p.apply_settings(dict(panel_detached=True),save=False);self.settle()
        original=p.bubble.geometry();self.drag();self.assertEqual(p.bubble.geometry(),original);self.release()
        p.apply_settings(dict(panel_detached=False),save=False);p.bubble.enabled=False;p.bubble.hide()
        self.drag();self.assertFalse(p.bubble.isVisible());self.release();self.assertFalse(p.bubble.isVisible())
    def test_prepared_canvas_moves_without_rebuilding_rasters(self):
        self.prepare();self.drag();t=self.pet.bubble.size_transition
        self.assertTrue(t.running);m=t.morph;frames=m.body_frames;before=t.target_rect.topLeft()
        delta=QPoint(37,21);self.pet.move(self.pet.pos()+delta);self.pet.position_bubble()
        self.assertEqual(t.target_rect.topLeft(),before+delta);self.assertIs(m.body_frames,frames)
        self.release()
    def test_lost_capture_restores_normal(self):
        self.prepare(expanded=True);self.drag();self.pet.cancel_pointer();self.settle()
        self.assertFalse(self.pet.bubble.is_compact());self.assertFalse(self.pet.bubble.expanded)
    def test_quick_release_and_new_drag_do_not_restore_large_card(self):
        self.prepare(expanded=True)
        for _ in range(3):
            self.drag();self.release()
            self.assertFalse(self.pet.bubble.expanded);self.assertFalse(self.pet.bubble.is_compact())
    def test_follow_translation_is_additive_for_prepared_endpoints(self):
        self.prepare(expanded=True);self.drag();t=self.pet.bubble.size_transition
        before=t.morph.end.rect.topLeft();frames=t.morph.body_frames
        for _ in range(20):
            self.pet.move(self.pet.pos()+QPoint(2,1));self.pet.position_bubble()
        self.assertEqual(t.morph.end.rect.topLeft(),before+QPoint(40,20))
        self.assertIs(t.morph.body_frames,frames);self.release()
    def test_attached_auto_card_stays_minimal_after_real_edge_drop_and_fresh_status(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QPointF,Qt
        import time
        self.prepare('auto',expanded=True);p=self.pet;b=p.bubble
        area=p.screen().availableGeometry();origin=p.frameGeometry().center()
        press=SimpleNamespace(button=lambda:Qt.MouseButton.LeftButton,globalPosition=lambda:QPointF(origin))
        target=origin+QPoint(area.left()-p.x(),0)
        move=SimpleNamespace(buttons=lambda:Qt.MouseButton.LeftButton,globalPosition=lambda:QPointF(target))
        p.mousePressEvent(press);p.mouseMoveEvent(move);p.mouseReleaseEvent(press);self.settle()
        self.assertTrue(p.edge_dock.active);self.assertTrue(b.is_minimal())
        now=max(time.monotonic(),b._manual_grace_until+.1);b.last_task_update=now;b.evaluate_mode(now)
        self.settle();self.assertTrue(b.is_minimal(),'Fresh task must not reopen a docked compact surface')
    def test_edge_compact_policy_overrides_idle_auto_decisions_without_changing_preference(self):
        import time
        for mode in ('auto','mini','minimal'):
            self.prepare(mode);b=self.pet.bubble;b.set_edge_compact(True);self.settle()
            for codex_open in (True,False):
                b.codex_open=codex_open;b.last_task_update=time.monotonic();b.evaluate_mode()
                self.settle();self.assertTrue(b.is_minimal());self.assertEqual(b.bubble_mode,mode)
            b.set_edge_compact(False);self.settle();self.assertEqual(b.bubble_mode,mode)

class RingEntryTests(unittest.TestCase):
    def test_hidden_capsule_reenters_and_redraw_preserves_clock(self):
        from compact_bubble import CompactBubble
        from island_widgets import QuotaSatellite
        b=CompactBubble();b.windows=[dict(name='一周',remaining=59)];b.show()
        def settle():b.size_transition.complete();b.size_transition.release_landing();APP.processEvents()
        def ring():return next(w for w in b.content.findChildren(QuotaSatellite) if w.isVisibleTo(b.content))
        try:
            b.set_mode('mini');settle();w=ring();w.reveal.animation.setCurrentTime(620)
            b.hide();b.show();APP.processEvents();w=ring()
            self.assertLess(w.reveal.progress,1.)
            w.reveal.animation.setCurrentTime(140);progress=w.reveal.progress;b.redraw();APP.processEvents()
            self.assertAlmostEqual(ring().reveal.progress,progress,delta=.04)
            self.assertTrue(ring().reveal.animation.state().value)
        finally:b.close();b.deleteLater();APP.processEvents()
    def test_pending_reveal_waits_for_native_handoff(self):
        from compact_bubble import CompactBubble
        from island_widgets import QuotaSatellite
        b=CompactBubble();b.windows=[dict(name='一周',remaining=59)];b.show();APP.processEvents()
        try:
            b.set_mode('mini')
            w=next(w for w in b.content.findChildren(QuotaSatellite) if w.isVisibleTo(b.content))
            self.assertTrue(b.size_transition.running);w.start_reveal()
            self.assertTrue(w.reveal.pending);self.assertEqual(w.reveal.progress,0.)
            b.size_transition.complete();b.size_transition.release_landing();APP.processEvents()
            self.assertTrue(w.reveal.animation.state().value)
        finally:b.close();b.deleteLater();APP.processEvents()
