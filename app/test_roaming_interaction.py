"""Route collection/resume exercises the real bubble transition and stop API."""
import os,time,unittest,copy
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from roaming import WalkPlan
import test_edge_dock as fixture

class InteractionTests(unittest.TestCase):
    setUp=fixture.DockTests.setUp
    tearDown=fixture.DockTests.tearDown
    def ready(self,mode='auto'):
        p=self.p;p.apply_settings(dict(wandering=True,status_actions=False,bubble_mode=mode),save=False)
        p.bubble.set_mode(mode);fixture.settle(p)
        p.bubble._minimal_normal_open=True;p.bubble.auto_compact=False;p.bubble.redraw();fixture.settle(p)
        p.gate.state='idle';p.locomotion.cancel();return p
    def test_collects_before_moving_without_saving_capsule_preference(self):
        for mode in ('auto','mini','minimal'):
            p=self.ready(mode);r=p.roaming;r.cancel();saved=copy.deepcopy(p.settings)
            self.assertFalse(r.prepare_panel(10));self.assertTrue(r.pending_start)
            self.assertFalse(p.walking);fixture.settle(p)
            self.assertTrue(r.prepare_panel(11));self.assertTrue(p.bubble.is_compact())
            self.assertEqual(p.bubble.compact_kind(),'minimal' if mode=='minimal' else 'mini')
            self.assertEqual(p.settings,saved)
            p.bubble.evaluate_mode(now=time.monotonic()+200);self.assertTrue(p.bubble.is_compact())
    def test_interruption_keeps_current_leg_and_uses_natural_stop(self):
        p=self.ready();r=p.roaming;r.queue=[(100,200)];p.walking=True;p.walk_target=(300,400,(0,0,900,900))
        with patch.object(p,'stop_walk',wraps=p.stop_walk) as stop:
            r.interrupt(20);stop.assert_called_once_with(land=True,preserve_route=True)
        self.assertEqual(r.queue,[(300,400),(100,200)]);self.assertFalse(p.walking);self.assertEqual(r.paused_until,25)
        r.activity(23);self.assertEqual(r.paused_until,28)
        p.locomotion.cancel()
        with patch.object(p,'start_walk') as start:
            r.tick(27.99);start.assert_not_called();r.tick(28);start.assert_called_once()
    def test_landing_finishes_before_resume_even_after_five_seconds(self):
        p=self.ready();r=p.roaming;r.paused_until=10
        with patch.object(p,'start_walk') as start:
            p.locomotion.phase='exit'
            r.tick(20);start.assert_not_called()
            p.locomotion.cancel();r.tick(20);start.assert_called_once()
    def test_detached_panel_is_never_collected_or_paused_by_card_click(self):
        p=self.ready();p.settings['panel_detached']=True;r=p.roaming
        before=p.bubble.size_transition.visible_geometry()
        self.assertTrue(r.prepare_panel(10));self.assertFalse(p.bubble.is_compact())
        p.walking=True;p.walk_target=(300,400,(0,0,900,900));r.interrupt(20)
        self.assertTrue(p.walking);self.assertIsNone(r.paused_until)
        self.assertEqual(before,p.bubble.size_transition.visible_geometry());p.walking=False
    def test_real_button_events_extend_pause_without_consuming_click(self):
        p=self.ready();r=p.roaming;r.paused_until=time.monotonic()-1
        before=time.monotonic();QTest.mouseClick(p.bubble,Qt.MouseButton.LeftButton,pos=QPoint(5,5))
        self.assertGreaterEqual(r.paused_until,before+5)
    def test_timeout_cannot_park_an_interrupted_route_in_the_center(self):
        r=self.p.roaming;r.last=WalkPlan((),(100,100,500,500),fast_cross=False)
        self.assertFalse(r.may_timeout(300,300));self.assertTrue(r.may_timeout(50,300))
        self.assertGreaterEqual(r.speed(300,300,55),180)
        r.last=WalkPlan((),(100,100,500,500),mode='zone')
        self.assertEqual(r.speed(300,300,55),55)
    def test_actual_walk_waits_for_collection_and_expand_interrupts_it(self):
        p=self.ready();r=p.roaming
        with patch.object(p,'underMouse',return_value=False),patch.object(p.bubble,'underMouse',return_value=False),patch.object(p,'play',return_value=True),patch.object(p,'prepare_landing'),patch.object(r,'next',return_value=((40,500),(0,0,900,900))):
            p.start_walk();self.assertFalse(p.walking);self.assertTrue(r.pending_start)
            fixture.settle(p);r.tick(time.monotonic());self.assertTrue(p.walking)
            self.assertTrue(p.bubble.is_compact())
            p.bubble.open_normal_from_minimal();fixture.settle(p)
            with patch.object(p,'stop_walk',wraps=p.stop_walk) as stop:
                r.tick(time.monotonic());stop.assert_called_once_with(land=True,preserve_route=True)
            self.assertFalse(p.walking);self.assertIsNotNone(r.paused_until)
            # Stationary hover must not prevent the five-second resume, but
            # the reopened card must finish collecting before travel starts.
            deadline=r.paused_until
            with patch('desktop.time.monotonic',return_value=deadline):
                r.tick(deadline)
                self.assertFalse(p.walking);self.assertTrue(r.pending_start)
                self.assertTrue(p.bubble.is_compact())
                self.assertTrue(p.bubble.size_transition.running or p.bubble.size_transition.preparing)
                fixture.settle(p);r.tick(deadline)
            self.assertTrue(p.walking);self.assertTrue(p.bubble.is_compact())
            self.assertIsNone(r.paused_until)

if __name__=='__main__':unittest.main()
