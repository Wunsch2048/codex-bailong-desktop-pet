import random,unittest
from desktop_core import normalized
from roaming import plan,path_between,contains,crosses,inflate,center_rect,clean_zone

class RoamingTests(unittest.TestCase):
    def settings(self,**kw):return normalized(dict(wander_horizontal_only=False,**kw))
    def test_all_four_modes_produce_screen_local_routes(self):
        for area in ((0,0,1920,1080),(-1920,0,1920,1080),(0,-900,1600,900)):
            x,y,w,h=area;start=(x+w-230,y+h-230)
            for mode in ('edge','side','zone','window'):
                with self.subTest(area=area,mode=mode):
                    route=plan(start,start,area,(0,0,180,180),self.settings(wander_mode=mode),random.Random(15).uniform,(x+400,y+100,x+1000,y+650))
                    self.assertTrue(route.points,route.reason)
                    for px,py in route.points:self.assertTrue(x<=px<=x+w-180 and y<=py<=y+h-180)
    def test_route_avoids_obstacle_for_entire_character_not_only_stop(self):
        area=(0,0,1600,1000);footprint=(-30,-130,230,200);obstacle=inflate(center_rect(area,footprint),footprint)
        start=(30,400);target=(1300,400);route=path_between(start,target,(30,140,1360,790),[obstacle])
        self.assertTrue(route)
        for a,b in zip([start]+route,route):self.assertFalse(crosses(a,b,obstacle))
    def test_horizontal_may_cross_center_but_never_choose_a_center_stop(self):
        settings=normalized(dict(wander_horizontal_only=True,wander_mode='edge'))
        area=(0,0,1920,1080);start=(12,420)
        route=plan(start,start,area,(0,-100,256,256),settings,lambda a,b:b-.001)
        self.assertTrue(route.points);self.assertTrue(route.fast_cross)
        self.assertEqual(route.points[-1][1],start[1]);self.assertFalse(contains(route.points[-1],route.center))
    def test_small_screen_keeps_horizontal_edge_stops_with_attached_panel(self):
        route=plan((60,400),(60,400),(0,0,800,800),(-6,-180,262,256),normalized({}),lambda a,b:b-.001)
        self.assertTrue(route.points,route.reason);self.assertFalse(contains(route.points[-1],route.center))
    def test_side_mode_stays_on_chosen_side_and_waits_longer(self):
        route=plan((1610,600),(1610,600),(0,0,1920,1080),(0,0,256,256),self.settings(wander_mode='side',wander_side='right'),random.Random(3).uniform)
        self.assertTrue(route.points);self.assertGreater(route.wait_factor,1)
        self.assertTrue(all(p[0]>1400 for p in route.points))
    def test_manual_area_contains_the_whole_footprint(self):
        settings=self.settings(wander_mode='zone',wander_zone=[.65,.55,1,1]);area=(0,0,1920,1080);foot=(0,0,180,180)
        route=plan((1400,700),(1400,700),area,foot,settings,random.Random(2).uniform)
        self.assertTrue(route.points)
        for x,y in route.points:self.assertTrue(x>=1920*.65 and y>=1080*.55 and x+180<=1920 and y+180<=1080)
    def test_tiny_manual_area_does_not_teleport_or_escape_it(self):
        route=plan((1500,700),(1500,700),(0,0,1920,1080),(0,-180,256,256),self.settings(wander_mode='zone',wander_zone=[.9,.9,1,1]),random.Random(2).uniform)
        self.assertFalse(route.points);self.assertIn('放不下',route.reason)
    def test_horizontal_window_avoidance_does_not_use_center_permission_to_cross_window(self):
        settings=normalized(dict(wander_mode='window',wander_horizontal_only=True))
        route=plan((12,400),(12,400),(0,0,1920,1080),(0,0,180,180),settings,lambda a,b:b-.001,(600,100,1100,850))
        window=inflate((600,100,1100,850),(0,0,180,180),12)
        for target in route.points:self.assertFalse(crosses((12,400),target,window))
    def test_fullscreen_foreground_uses_edge_fallback(self):
        route=plan((20,700),(20,700),(0,0,1920,1080),(0,0,180,180),self.settings(wander_mode='window'),random.Random(4).uniform,(0,0,1920,1080))
        self.assertTrue(route.points);self.assertFalse(contains(route.points[-1],route.center))
    def test_new_foreground_covering_the_pet_allows_a_horizontal_escape(self):
        settings=normalized(dict(wander_mode='window',wander_horizontal_only=True))
        area=(0,0,1920,1080);start=(500,700);window=(400,400,1100,950)
        route=plan(start,start,area,(0,0,180,180),settings,lambda a,b:0,window)
        self.assertTrue(route.points,route.reason)
        obstacle=inflate(window,(0,0,180,180),12)
        self.assertTrue(contains(start,obstacle));self.assertFalse(contains(route.points[-1],obstacle))
    def test_mode_and_zone_restart_normalization_is_defensive(self):
        settings=normalized(dict(wander_mode='bad',wander_side='bad',wander_zone=['bad',0,1,1]))
        self.assertEqual(settings['wander_mode'],'edge');self.assertEqual(settings['wander_side'],'auto');self.assertEqual(settings['wander_zone'],clean_zone(None))
        custom=normalized(dict(wander_mode='zone',wander_zone=[.01,.6,.4,.98]))
        self.assertEqual(normalized(custom)['wander_zone'],custom['wander_zone'])

if __name__=='__main__':unittest.main()
