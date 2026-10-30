import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,copy,random,time
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint,QRect
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest
import test_settings_controls as controls
from desktop_settings import SettingsDialog
from desktop_core import DEFAULTS
from roaming_controller import RoamingController
from roaming import WalkPlan
APP=QApplication.instance() or QApplication([])

class RoamingUiTests(unittest.TestCase):
    def setUp(self):
        self.pet=controls.PetStub();self.pet.resize(192,192);self.pet.show()
        with patch('desktop_settings.autostart_enabled',return_value=False),patch('codex_startup.enabled',return_value=False):self.settings=SettingsDialog(self.pet,embedded=True,lazy=True)
        self.settings.resize(460,640);self.settings.show();self.settings.tabs.setCurrentIndex(1);APP.processEvents();self.editor=self.settings.roaming_editor
    def tearDown(self):self.settings.close();self.pet.close();APP.processEvents()
    def test_four_modes_edit_draft_then_save_without_resizing_the_host(self):
        before=self.settings.size();self.settings.roaming_button.click();APP.processEvents()
        self.assertTrue(self.editor.isVisible());self.assertEqual(self.settings.size(),before)
        self.assertEqual(len(self.editor.mode.buttons),4)
        for mode in ('edge','side','zone','window'):
            self.editor.mode.setCurrentIndex(self.editor.mode.findData(mode));APP.processEvents();self.assertEqual(self.settings.draft.values['wander_mode'],mode)
        self.assertEqual(self.pet.settings['wander_mode'],'edge')
        self.settings.apply();self.assertEqual(self.pet.settings['wander_mode'],'window');self.assertFalse(self.settings.draft.dirty)
    def test_manual_drag_updates_only_draft_and_discard_restores_it(self):
        self.settings.roaming_button.click();self.editor.mode.setCurrentIndex(self.editor.mode.findData('zone'));APP.processEvents()
        diagram=self.editor.diagram;rect=diagram.screen_rect()
        a=QPoint(round(rect.left()+rect.width()*.55),round(rect.top()+rect.height()*.45));b=QPoint(round(rect.left()+rect.width()*.97),round(rect.top()+rect.height()*.97))
        old=copy.deepcopy(self.pet.settings['wander_zone'])
        QTest.mousePress(diagram,Qt.MouseButton.LeftButton,pos=a);QTest.mouseMove(diagram,b);QTest.mouseRelease(diagram,Qt.MouseButton.LeftButton,pos=b);APP.processEvents()
        self.assertNotEqual(self.settings.draft.values['wander_zone'],old);self.assertEqual(self.pet.settings['wander_zone'],old)
        self.settings.reload();self.assertEqual(diagram.value(),old);self.assertFalse(self.settings.draft.dirty)
    def test_hidden_and_reduced_motion_diagram_stops_its_clock(self):
        self.settings.roaming_button.click();APP.processEvents()
        self.editor.diagram.motion_policy_changed();self.editor.hide();APP.processEvents();self.assertFalse(self.editor.diagram.clock.isActive())
        self.editor.open()
        with patch('roaming_editor.motion_enabled',return_value=False):self.editor.diagram.motion_policy_changed();self.assertFalse(self.editor.diagram.clock.isActive())
        self.settings.tabs.setCurrentIndex(0);APP.processEvents();self.assertFalse(self.editor.isVisible());self.assertFalse(self.editor.diagram.clock.isActive())
    def test_move_whole_zone_preserves_size_and_reset_stays_in_draft(self):
        self.settings.roaming_button.click();self.editor.mode.setCurrentIndex(self.editor.mode.findData('zone'));APP.processEvents()
        diagram=self.editor.diagram;diagram.setValue([.2,.2,.6,.6]);rect=diagram.screen_rect()
        def point(x,y):return QPoint(round(rect.left()+rect.width()*x),round(rect.top()+rect.height()*y))
        old=copy.deepcopy(self.pet.settings['wander_zone'])
        QTest.mousePress(diagram,Qt.MouseButton.LeftButton,pos=point(.4,.4));QTest.mouseMove(diagram,point(1,1))
        self.assertEqual(diagram.value(),[.2,.2,.6,.6])
        QTest.mouseRelease(diagram,Qt.MouseButton.LeftButton,pos=point(1,1));APP.processEvents()
        z=diagram.value();self.assertAlmostEqual(z[2]-z[0],.4);self.assertAlmostEqual(z[3]-z[1],.4)
        self.assertLessEqual(z[2],1);self.assertLessEqual(z[3],1)
        self.editor.reset_zone.click();APP.processEvents()
        from roaming import clean_zone
        self.assertEqual(diagram.value(),clean_zone(None));self.assertEqual(self.pet.settings['wander_zone'],old)
    def test_zone_corner_resizes_instead_of_translating(self):
        self.settings.roaming_button.click();self.editor.mode.setCurrentIndex(self.editor.mode.findData('zone'));APP.processEvents()
        diagram=self.editor.diagram;diagram.setValue([.2,.2,.6,.6]);rect=diagram.screen_rect()
        def point(x,y):return QPoint(round(rect.left()+rect.width()*x),round(rect.top()+rect.height()*y))
        QTest.mousePress(diagram,Qt.MouseButton.LeftButton,pos=point(.6,.6));QTest.mouseMove(diagram,point(.9,.9));QTest.mouseRelease(diagram,Qt.MouseButton.LeftButton,pos=point(.9,.9));APP.processEvents()
        z=diagram.value();self.assertAlmostEqual(z[0],.2);self.assertAlmostEqual(z[1],.2);self.assertGreater(z[2],.85);self.assertGreater(z[3],.85)
    def test_locked_position_disables_roaming_configuration_without_erasing_it(self):
        self.settings.fields['no_move'].setChecked(True)
        self.assertFalse(self.settings.roaming_button.isEnabled());self.assertFalse(self.settings.fields['wander_mode'].isEnabled())
        self.settings.fields['no_move'].setChecked(False);self.assertTrue(self.settings.roaming_button.isEnabled())

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.pet=QWidget();self.pet.resize(180,180);self.pet.move(16,400);self.pet.settings=copy.deepcopy(DEFAULTS)
        self.pet.settings.update(panel_detached=True,wander_mode='window');self.pet.bubble=SimpleNamespace(isVisible=lambda:False)
        self.controller=RoamingController(self.pet)
    def tearDown(self):self.pet.close()
    def test_geometry_only_reader_is_limited_to_once_per_second_while_moving(self):
        with patch.object(self.controller.reader,'read',return_value=(600,100,1000,700)) as read:
            self.controller.window=read.return_value
            self.assertFalse(self.controller.foreground_changed(0));self.assertFalse(self.controller.foreground_changed(.5));self.assertEqual(read.call_count,1)
            read.return_value=(650,100,1050,700);self.controller.queue=[(500,400)]
            self.assertTrue(self.controller.foreground_changed(1.1));self.assertFalse(self.controller.queue);self.assertEqual(read.call_count,2)
        self.pet.settings['wander_mode']='edge'
        with patch.object(self.controller.reader,'read') as read:self.controller.foreground_changed(3);read.assert_not_called()
    def test_center_pass_accelerates_and_cannot_time_out_in_center(self):
        self.controller.last=WalkPlan(((1500,400),),(300,200,1200,800),True)
        self.assertGreaterEqual(self.controller.speed(600,400,55),180);self.assertFalse(self.controller.may_timeout(600,400))
        self.assertEqual(self.controller.speed(20,400,55),55);self.assertTrue(self.controller.may_timeout(20,400))
    def test_policy_or_screen_change_discards_queued_positions(self):
        area=QRect(0,0,1920,1080);screen=SimpleNamespace(name=lambda:'screen')
        self.pet.settings['wander_mode']='edge';self.controller.next(screen,area,(16,400),random.Random(8).uniform)
        self.controller.queue=[(99,999)];self.pet.settings['wander_mode']='side'
        self.controller.next(screen,area,(16,400),random.Random(8).uniform)
        self.assertNotIn((99,999),self.controller.queue)
    def test_attached_panel_footprint_uses_the_transition_geometry_owner(self):
        self.pet.settings['panel_detached']=False
        self.pet.bubble=SimpleNamespace(isVisible=lambda:True,size_transition=SimpleNamespace(visible_geometry=lambda:QRect(-20,200,260,180)))
        self.assertEqual(self.controller.footprint(),(-36,-200,224,180))
        self.pet.settings['panel_detached']=True;self.assertEqual(self.controller.footprint(),(0,0,180,180))

class DesktopRouteTests(unittest.TestCase):
    # Exercise DesktopPet and the real transition owner, rather than a second
    # mock of its public API. Reuse only the isolated fixture, not its tests.
    import test_edge_dock as fixture
    setUp=fixture.DockTests.setUp
    tearDown=fixture.DockTests.tearDown
    def test_editor_captures_normal_occupancy_before_expanding_and_pauses_motion(self):
        p=self.p;p.bubble.set_mode('auto');self.fixture.settle(p)
        normal=p.roaming.footprint();p.open_settings();self.fixture.settle(p)
        self.assertEqual(p.roaming.preview_footprint,normal)
        p.roaming.queue=[(20,20)];p.walking=True;p.walk_target=(20,20,(0,0,800,800))
        with patch.object(p,'stop_walk') as stop:p._move_frame();stop.assert_called_once_with(land=True)
        p.walking=False;p.walk_target=None
    def test_route_cancellation_and_landing_keep_only_intentional_next_legs(self):
        p=self.p;p.roaming.queue=[(30,40)];p.stop_walk(land=True,preserve_route=True)
        self.assertEqual(p.roaming.queue,[(30,40)])
        p.stop_walk();self.assertFalse(p.roaming.queue)
    def test_existing_manual_press_cancels_autonomous_route(self):
        p=self.p;p.roaming.queue=[(30,40)]
        QTest.mousePress(p,Qt.MouseButton.LeftButton,pos=p.rect().center())
        self.assertFalse(p.roaming.queue)
        QTest.mouseRelease(p,Qt.MouseButton.LeftButton,pos=p.rect().center())
    def test_side_rest_survives_the_natural_landing_callback(self):
        p=self.p;p.locomotion.cancel();p.mode='landing';p.gate.state='landing';p.press_feedback=0
        p.roaming.last=WalkPlan((),(0,0,1,1),wait_factor=2.4,mode='side');p.roaming.rest_pending=True
        before=time.monotonic()
        with patch.object(p.player,'advance',return_value=(None,True)),patch.object(p,'idle'),patch.object(p,'play_status_reaction',return_value=False):p._animate_frame()
        self.assertGreaterEqual(p.next_chain,before+p.settings['action_gap']+p.settings['random_interval']*2.4)
        self.assertFalse(p.roaming.rest_pending)

if __name__=='__main__':unittest.main()
