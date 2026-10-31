"""Pet docking does not mutate card preferences or move an independent panel."""
import os,json,tempfile,unittest,copy
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect,QPoint,QSize,QEvent,QEventLoop
from desktop import DesktopPet
from edge_dock import candidate
APP=QApplication.instance() or QApplication([])
def settle(p):
 for _ in range(5):p.bubble.size_transition.complete();APP.processEvents()
class DockTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.patches=[patch('enhanced.CONFIG',self.root/'settings.json'),patch('enhanced.STATE_DIR',self.root),patch('desktop.CONFIG',self.root/'settings.json'),patch('desktop.STATE_DIR',self.root),patch('codex_startup.enabled',return_value=False)]
  for x in self.patches:x.start()
  self.p=DesktopPet(monitor=False);self.p.tick.stop();self.p.motion_timer.stop();self.p.apply_settings(dict(random_actions=False,wandering=False,drag_physics=False,bubble_mode='mini',on_top=False),save=False);self.p.show();settle(self.p)
 def tearDown(self):
  self.p.close();settle(self.p)
  for x in reversed(self.patches):x.stop()
  self.tmp.cleanup()
 def dock(self,side='left'):
  p=self.p;a=p.screen().availableGeometry();p.move(a.left() if side=='left' else a.right()-p.width()+1,a.top()+100)
  self.assertTrue(p.edge_dock.try_dock());p.edge_dock.animation.stop();p.edge_dock._advance(1.);settle(p)
 def test_candidate_uses_logical_bounds_including_negative_monitor_coordinates(self):
  a=QRect(-1600,-200,1600,900);size=QSize(256,256)
  self.assertEqual(candidate(QPoint(-1600,0),size,a),'left');self.assertEqual(candidate(QPoint(-256,0),size,a),'right');self.assertIsNone(candidate(QPoint(-700,0),size,a))
 def test_dock_circle_and_undock_restore_saved_capsule_preference(self):
  p=self.p;p.save_settings();mode=p.settings['bubble_mode'];self.dock()
  self.assertTrue(p.bubble.is_minimal());self.assertEqual(p.settings['bubble_mode'],mode)
  p.save_settings();self.assertEqual(json.loads((self.root/'settings.json').read_text(encoding='utf-8'))['bubble_mode'],mode)
  p.edge_dock.clear(immediate=True);settle(p);self.assertTrue(p.bubble.is_island());self.assertEqual(p.settings['bubble_mode'],mode)
 def test_attached_circle_anchors_to_folded_head_not_empty_canvas(self):
  from PySide6.QtCore import QRectF
  p=self.p
  for side in ('left','right'):
   p.edge_dock.clear(immediate=True);self.dock(side);p.position_bubble()
   from edge_dock import pose
   head=pose(QRectF(p.rect()),side,1.).mapRect(QRectF(p.width()*.30,p.height()*.10,p.width()*.45,p.height()*.42)).intersected(QRectF(p.rect()))
   head.translate(p.x(),p.y())
   self.assertLessEqual(abs(p.bubble.geometry().bottom()+1-head.top()-p.height()*.025),2)
   self.assertEqual(p.settings['bubble_mode'],'mini')
 def test_morph_and_settled_position_use_one_docked_target_on_both_sides(self):
  p=self.p;b=p.bubble;t=b.size_transition
  for side in ('left','right'):
   p.edge_dock.clear(immediate=True);settle(p)
   area=p.screen().availableGeometry();p.move(area.left() if side=='left' else area.right()-p.width()+1,area.top()+200)
   self.assertTrue(p.edge_dock.try_dock());target=QRect(t.target_rect)
   p.edge_dock.animation.stop();p.edge_dock._advance(1.);settle(p)
   self.assertEqual(b.geometry(),target);p.position_bubble();self.assertEqual(b.geometry(),target)
   self.assertEqual(b.content_geometry(),target)
 def test_saved_minimal_moves_continuously_with_pose_without_a_second_morph(self):
  p=self.p;b=p.bubble;p.apply_settings(dict(bubble_mode='minimal'),save=False);settle(p)
  area=p.screen().availableGeometry();p.move(area.left(),area.top()+200);p.position_bubble();start=QRect(b.geometry())
  self.assertTrue(p.edge_dock.try_dock());p.edge_dock.animation.stop()
  self.assertFalse(b.size_transition.running)
  p.edge_dock._advance(0.);self.assertEqual(b.geometry(),start)
  p.edge_dock._advance(.5);middle=QRect(b.geometry())
  p.edge_dock._advance(1.);end=QRect(b.geometry())
  self.assertNotEqual(start,end)
  self.assertAlmostEqual(middle.x(),(start.x()+end.x())/2,delta=1)
  self.assertAlmostEqual(middle.y(),(start.y()+end.y())/2,delta=1)
  p.edge_dock.clear();p.edge_dock.animation.stop();p.edge_dock._advance(.5);self.assertEqual(b.geometry(),middle)
  p.edge_dock._advance(0.);self.assertEqual(b.geometry(),start)
 def test_separated_normal_panel_keeps_position_anchor_and_page(self):
  p=self.p;p.apply_settings(dict(panel_detached=True,bubble_mode='auto'),save=False);p.bubble.auto_compact=False;p.bubble.redraw();settle(p)
  p.move_card(QPoint(250,200));settle(p);p.remember_card_anchor(p.bubble.geometry());anchor=copy.deepcopy(p.settings['card_anchor']);pos=p.bubble.pos()
  self.dock();self.assertEqual(p.bubble.pos(),pos);self.assertEqual(p.settings['card_anchor'],anchor);self.assertFalse(p.bubble.is_compact())
  p.open_settings();settle(p);size=p.bubble.size();p.edge_dock.clear(immediate=True);settle(p)
  self.assertEqual(p.bubble.panel_page,'settings');self.assertEqual(p.bubble.size(),size);self.assertEqual(p.settings['card_anchor'],anchor)
 def test_no_resources_hidden_character_and_disabled_option_never_dock(self):
  p=self.p;a=p.screen().availableGeometry();p.move(a.left(),100)
  p._materials_missing=True;self.assertFalse(p.edge_dock.try_dock());p._materials_missing=False
  for values in (dict(character_visible=False),dict(character_visible=True,edge_docking=False)):
   p.apply_settings(values,save=False);settle(p);self.assertFalse(p.edge_dock.try_dock());self.assertFalse(p.bubble._edge_compact)
 def test_detached_capsule_keeps_its_mode_and_position_when_character_docks(self):
  p=self.p;p.apply_settings(dict(panel_detached=True,bubble_mode='mini'),save=False);settle(p)
  p.move_card(QPoint(250,180));settle(p);pos=p.bubble.pos();anchor=copy.deepcopy(p.settings['card_anchor'])
  self.dock();self.assertTrue(p.bubble.is_island());self.assertFalse(p.bubble._edge_compact)
  self.assertEqual(p.bubble.pos(),pos);self.assertEqual(p.settings['card_anchor'],anchor)
 def test_disabling_or_hiding_a_docked_character_restores_normal_compact_policy(self):
  self.dock();p=self.p;p.apply_settings(dict(character_visible=False),save=False);settle(p)
  self.assertFalse(p.edge_dock.active);self.assertFalse(p.bubble._edge_compact);self.assertEqual(p.settings['bubble_mode'],'mini');self.assertTrue(p.bubble.is_island())
 def test_minimal_opens_normal_and_shrinks_without_persisting_override(self):
  p=self.p;self.dock();p.bubble.open_normal_from_minimal();settle(p);self.assertFalse(p.bubble.is_compact())
  p.bubble.compact_requested();settle(p);self.assertTrue(p.bubble.is_minimal());self.assertEqual(p.settings['bubble_mode'],'mini')
 def test_drop_does_not_treat_the_same_mouse_as_a_new_hover(self):
  self.dock();p=self.p
  with patch('edge_dock.QCursor.pos',return_value=p.frameGeometry().center()):
   p.edge_dock.reveal(temporary=True);p.edge_dock.animation.setCurrentTime(p.edge_dock.animation.duration())
   self.assertFalse(p.edge_dock.temporary);self.assertEqual(p.edge_dock.amount,1.)
 def test_only_a_real_pointer_departure_arms_the_next_hover(self):
  self.dock();p=self.p
  with patch('edge_dock.QCursor.pos',return_value=p.frameGeometry().center()):
   p.edge_dock.leave();p.edge_dock.observe_pointer();p.edge_dock.reveal(temporary=True)
   self.assertTrue(p.edge_dock.drop_latched);self.assertFalse(p.edge_dock.temporary)
  with patch('edge_dock.QCursor.pos',return_value=p.frameGeometry().topLeft()-QPoint(30,30)):p.edge_dock.leave()
  self.assertFalse(p.edge_dock.drop_latched)
  p.edge_dock.reveal(temporary=True);p.edge_dock.animation.setCurrentTime(p.edge_dock.animation.duration())
  self.assertTrue(p.edge_dock.temporary);self.assertEqual(p.edge_dock.amount,0.)
 def test_drop_guard_adds_no_hover_poll_timer(self):
  self.dock();p=self.p
  with patch('edge_dock.QCursor.pos',return_value=p.frameGeometry().center()):
   p.edge_dock.reveal(temporary=True);self.assertFalse(p.edge_dock.hover_timer.isActive())
 def test_fullscreen_hides_without_hover_or_pose_timers_and_tray_recovery_reveals(self):
  self.dock();p=self.p
  with patch('edge_dock.QCursor.pos',return_value=p.frameGeometry().topLeft()-QPoint(30,30)):p.edge_dock.observe_pointer()
  p.edge_dock.reveal(temporary=True);self.assertTrue(p.edge_dock.hover_timer.isActive())
  p.set_fullscreen_yield(True);self.assertFalse(p.edge_dock.hover_timer.isActive());self.assertEqual(p.edge_dock.animation.state(),p.edge_dock.animation.State.Stopped)
  self.assertFalse(p.isVisible());p.set_fullscreen_yield(False);p.recover();settle(p);self.assertFalse(p.edge_dock.active)
 def test_visible_peek_has_working_hits_on_both_sides_without_new_native_window(self):
  p=self.p;handle=int(p.winId())
  for side in ('left','right'):
   p.edge_dock.clear(immediate=True);settle(p);self.dock(side);self.assertEqual(int(p.winId()),handle)
   im=p.grab().toImage();opaque=0
   for y in range(3,p.height()-3,5):
    for x in range(3,p.width()-3,5):
     if all(im.pixelColor(x+dx,y+dy).alpha()>200 for dx,dy in ((0,0),(-2,0),(2,0),(0,-2),(0,2))):opaque+=1;self.assertTrue(p.alpha_hit(x,y))
   self.assertGreater(opaque,20)
   self.assertFalse(p.status_animation_allowed());p.start_walk();self.assertFalse(p.walking)

if __name__=='__main__':unittest.main()
