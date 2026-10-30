"""Autonomous motion must respect manual placement and the horizontal limit."""
import random
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from desktop_core import DEFAULTS,normalized,local_roam_bounds,local_roam_target

def controller():
    return SimpleNamespace(cancel=Mock(),queue=[],foreground_changed=Mock(return_value=False),
        speed=lambda x,y,base:base,may_timeout=lambda x,y:True,wait_factor=1.)


class WanderingTests(unittest.TestCase):
    def test_upgraded_settings_default_to_horizontal_and_reject_invalid_home(self):
        current=normalized({'move_range':.75})
        self.assertTrue(current['wander_horizontal_only'])
        self.assertEqual(current['move_range'],.75)
        self.assertEqual(normalized({'move_range':.75,'wander_range_revision':1})['move_range'],.75)
        self.assertEqual(normalized({'move_range':.5})['move_range'],.5)
        self.assertIsNone(current['wander_home'])
        self.assertFalse(normalized({'wander_horizontal_only':False})['wander_horizontal_only'])
        self.assertIsNone(normalized({'wander_home':{'screen':'one','rx':float('nan'),'ry':.5}})['wander_home'])

    def test_horizontal_range_reaches_both_edges_but_stops_outside_center(self):
        area=(0,0,1920,1080);size=(256,256);home=(1620,800)
        bounds=local_roam_bounds(home,size,area,DEFAULTS['move_range'],True)
        self.assertEqual(bounds[0],8)
        self.assertEqual(bounds[2],1656)
        self.assertEqual(bounds[1],bounds[3])
        rng=random.Random(13);current=home;crossings=0
        for _ in range(1000):
            target=local_roam_target(current,bounds,55,True,rng.uniform,DEFAULTS['move_range'])
            self.assertIsNotNone(target)
            x,y=target
            self.assertGreaterEqual(x,bounds[0]);self.assertLessEqual(x,bounds[2])
            self.assertEqual(y,home[1])
            self.assertTrue(x<=148 or x>=1516)
            crossings+=abs(x-current[0])>1000
            current=target
        self.assertGreater(crossings,50)

    def test_shorter_horizontal_range_still_uses_its_edges(self):
        home=(1620,800);bounds=local_roam_bounds(home,(256,256),(0,0,1920,1080),.5,True)
        self.assertGreater(bounds[0],800)
        self.assertEqual(bounds[2],1656)
        rng=random.Random(25)
        for x in (home[0],sum((bounds[0],bounds[2]))/2):
            target=local_roam_target((x,home[1]),bounds,55,True,rng.uniform,.5)
            self.assertIsNotNone(target)
            self.assertTrue(target[0]<=bounds[0]+140 or target[0]>=bounds[2]-140)

    def test_free_mode_stays_local_on_offset_monitor(self):
        area=(-1600,80,1600,900);size=(256,256);home=(-1450,680)
        bounds=local_roam_bounds(home,size,area,.75,False)
        self.assertLess(bounds[2],-1100)
        rng=random.Random(91);current=home;changed_height=False
        for _ in range(200):
            target=local_roam_target(current,bounds,55,False,rng.uniform)
            self.assertIsNotNone(target)
            x,y=target
            self.assertLessEqual(bounds[0],x);self.assertLessEqual(x,bounds[2])
            self.assertLessEqual(bounds[1],y);self.assertLessEqual(y,bounds[3])
            changed_height|=abs(y-current[1])>1
            current=target
        self.assertTrue(changed_height)

    def test_autonomous_arrival_plays_landing_before_idle(self):
        from desktop import DesktopPet
        landing={'id':'landing'}
        pet=SimpleNamespace(roaming=controller(),locomotion=SimpleNamespace(active=False,cancel=Mock()),walking=True,walk_target=(20,0,(0,0,100,100)),mode='walk',
            gate=SimpleNamespace(state='walk'),manifest={'landingAnimation':landing},
            play=Mock(return_value=True),idle=Mock())
        DesktopPet.stop_walk(pet,land=True)
        self.assertFalse(pet.walking)
        self.assertIsNone(pet.walk_target)
        pet.play.assert_called_once_with(landing,'landing')
        pet.idle.assert_not_called()

    def test_interrupted_walk_returns_to_idle_without_landing(self):
        from desktop import DesktopPet
        pet=SimpleNamespace(roaming=controller(),locomotion=SimpleNamespace(active=False,cancel=Mock()),walking=True,walk_target=(20,0,(0,0,100,100)),mode='walk',
            gate=SimpleNamespace(state='walk'),manifest={'landingAnimation':{'id':'landing'}},
            play=Mock(return_value=True),idle=Mock())
        DesktopPet.stop_walk(pet)
        pet.play.assert_not_called()
        pet.idle.assert_called_once_with()

    def test_motion_arrival_uses_landing_path(self):
        from desktop import DesktopPet
        now=time.monotonic()
        pet=SimpleNamespace(roaming=controller(),settings_dialog=None,bubble=SimpleNamespace(panel_page='status',report=None),edge_dock=SimpleNamespace(observe_pointer=Mock()),locomotion=SimpleNamespace(active=False),enhanced_ready=True,motion_clock=time.perf_counter(),
            isVisible=lambda:True,throwing=False,walking=True,dragging=False,
            walk_target=(20,0,(0,0,100,100)),_fx=10.,_fy=0.,walk_speed=55.,gesture_until=now+10,
            settings={'wander_horizontal_only':False,'action_gap':2,'random_interval':25},
            move=Mock(),position_bubble=Mock(),stop_walk=Mock(),save_settings=Mock(),
            next_talk=now+100)
        with patch('desktop.motion_step',return_value=(20.,0.,True)):
            DesktopPet._move_frame(pet)
        pet.stop_walk.assert_called_once_with(land=True,preserve_route=False)
        pet.save_settings.assert_called_once_with()

    def test_horizontal_timeout_does_not_stop_in_screen_center(self):
        from desktop import DesktopPet
        now=time.monotonic()
        pet=SimpleNamespace(roaming=controller(),settings_dialog=None,bubble=SimpleNamespace(panel_page='status',report=None),edge_dock=SimpleNamespace(observe_pointer=Mock()),locomotion=SimpleNamespace(active=False),enhanced_ready=True,motion_clock=time.perf_counter(),
            isVisible=lambda:True,throwing=False,walking=True,dragging=False,
            walk_target=(1656,800,(8,8,1656,816)),_fx=850.,_fy=800.,walk_speed=137.5,
            gesture_until=now-1,settings={'wander_horizontal_only':True,'action_gap':2,'random_interval':25},
            move=Mock(),position_bubble=Mock(),stop_walk=Mock(),save_settings=Mock(),
            next_talk=now+100)
        with patch('desktop.motion_step',return_value=(852.,800.,False)):
            DesktopPet._move_frame(pet)
        pet.stop_walk.assert_not_called()
        pet.save_settings.assert_not_called()

    def test_horizontal_timeout_may_stop_near_target(self):
        from desktop import DesktopPet
        now=time.monotonic()
        pet=SimpleNamespace(roaming=controller(),settings_dialog=None,bubble=SimpleNamespace(panel_page='status',report=None),edge_dock=SimpleNamespace(observe_pointer=Mock()),locomotion=SimpleNamespace(active=False),enhanced_ready=True,motion_clock=time.perf_counter(),
            isVisible=lambda:True,throwing=False,walking=True,dragging=False,
            walk_target=(1656,800,(8,8,1656,816)),_fx=1550.,_fy=800.,walk_speed=137.5,
            gesture_until=now-1,settings={'wander_horizontal_only':True,'action_gap':2,'random_interval':25},
            move=Mock(),position_bubble=Mock(),stop_walk=Mock(),save_settings=Mock(),
            next_talk=now+100)
        with patch('desktop.motion_step',return_value=(1552.,800.,False)):
            DesktopPet._move_frame(pet)
        pet.stop_walk.assert_called_once_with(land=True,preserve_route=False)


if __name__=='__main__':unittest.main()
