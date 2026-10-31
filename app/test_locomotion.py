import unittest
from types import SimpleNamespace
from unittest.mock import patch
from locomotion import Locomotion,selection,profile,travel_speed

SPEC=dict(start=28,end=59,sourceFrames=100,moveStart=24,fps=24,forwardOnly=True)
class Ready:
 def __init__(self):self.value=True
 def is_set(self):return self.value
class Segment:
 def __init__(self,path,size,start,end,cache=None):self.path=path;self.size=size;self.start=start;self.end=end;self.ready=Ready();self.error=None;self.closed=False
 def close(self):self.closed=True
class Player:
 def __init__(self):self.frame_index=0;self.ended=False;self.error=None;self.adopted=[]
 def start(self,*args,**kw):self.kw=kw;return 'first'
 def adopt(self,p,continuous=False):self.continuous=continuous;self.adopted.append((p.start,p.end));return 'next'
class LocomotionTests(unittest.TestCase):
 def test_run_moves_farther_than_walk_in_both_directions_and_respects_bounds(self):
  from enhanced_core import motion_step
  for direction in (-1,1):
   positions=[]
   for kind in ('walk','run'):
    x,y=500.,200.;target=500+direction*400
    for _ in range(20):x,y,done=motion_step(x,y,target,200,travel_speed(dict(movementKind=kind),55),.05,(0,0,1600,900))
    positions.append(abs(x-500))
   self.assertAlmostEqual(positions[0],55);self.assertAlmostEqual(positions[1],88)
   x,y,done=motion_step(500,200,500+direction*2,200,travel_speed(dict(movementKind='run'),300),.05,(0,0,1600,900))
   self.assertEqual(x,500+direction*2);self.assertTrue(done)
  self.assertEqual(travel_speed(dict(movementKind='run'),300),300)
  self.assertEqual(travel_speed(dict(movementKind='flight'),55),55)
 def test_real_walk_entry_uses_the_selected_action_speed_without_direction_bias(self):
  import os
  os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
  from PySide6.QtCore import QRect
  from PySide6.QtWidgets import QApplication
  from desktop import DesktopPet
  app=QApplication.instance() or QApplication([])
  screen=SimpleNamespace(name=lambda:'speed-fixture',availableGeometry=lambda:QRect(0,0,1920,1080))
  items=[dict(id='walk-'+d,movementKind='walk',travelDirection=d,locomotion=SPEC) for d in ('left','right')]+[dict(id='run',movementKind='run',travelDirection='both',locomotion=SPEC)]
  for direction in (-1,1):
   for running in (False,True):
    start=1200 if direction<0 else 100;target=start+direction*900
    bubble=SimpleNamespace(underMouse=lambda:False,size_transition=SimpleNamespace(running=False,preparing=False),report=None,panel_page='status')
    played=[]
    pet=SimpleNamespace(_materials_missing=False,settings_dialog=None,edge_dock=None,bubble=bubble,settings=dict(character_visible=True,panel_detached=True,no_move=False,wander_horizontal_only=True,move_speed=55,wander_home=dict(screen='speed-fixture',x=.1,y=.1)),dragging=False,throwing=False,gate=SimpleNamespace(state='idle'),frameGeometry=lambda:QRect(start,100,200,200),width=lambda:200,height=lambda:200,x=lambda:start,y=lambda:100,underMouse=lambda:False,roaming=SimpleNamespace(next=lambda *a:((target,100),(0,0,1720,880))),manifest=dict(moveAnimations=items),locomotion=SimpleNamespace(active=False),play=lambda item,state:played.append(item) or True,prepare_landing=lambda:None)
    with patch('desktop.QApplication.screenAt',return_value=screen),patch('desktop.random.random',return_value=0 if running else 1):DesktopPet.start_walk(pet)
    self.assertEqual(played[0]['movementKind'],'run' if running else 'walk')
    self.assertEqual(pet.walk_direction,direction);self.assertEqual(pet.walk_speed,88 if running else 55)
    self.assertTrue(pet.walking)
 def test_long_clip_separates_entrance_and_keeps_source_body_order(self):
  p=Player();m=Locomotion()
  with patch('locomotion.PreparedSegment',Segment):
   m.begin(p,'user.webp',205,dict(locomotion=dict(SPEC,entryEnd=27,interruptOnStop=True),durationMs=4167))
   self.assertEqual(p.kw['end_frame'],27)
   self.assertEqual((m.body.start,m.body.end),(28,59))
   m.boundary(p,205);self.assertEqual(p.adopted[-1],(28,59))
 def test_opt_in_stop_adopts_return_before_current_lap_finishes(self):
  for phase in ('enter','body'):
   with self.subTest(phase=phase),patch('locomotion.PreparedSegment',Segment):
    p=Player();m=Locomotion();m.begin(p,'user.webp',205,dict(locomotion=dict(SPEC,entryEnd=27,interruptOnStop=True),durationMs=4167))
    if phase=='body':m.boundary(p,205)
    self.assertFalse(p.ended);m.request_stop();self.assertEqual(m.poll_stop(p,205),'next')
    self.assertEqual(p.adopted[-1],(60,99));self.assertFalse(p.continuous);self.assertEqual(m.phase,'exit')
    self.assertIsNone(m.poll_stop(p,205));m.boundary(p,205);self.assertFalse(m.active)
 def test_stop_prefetch_pending_never_blocks_or_changes_legacy_playback(self):
  p=Player();m=Locomotion()
  with patch('locomotion.PreparedSegment',Segment):
   m.begin(p,'user.webp',205,dict(locomotion=dict(SPEC,interruptOnStop=True),durationMs=4167));m.request_stop()
   m.tail.ready.value=False;self.assertIsNone(m.poll_stop(p,205));self.assertEqual(p.adopted,[])
   m.tail.ready.value=True;self.assertEqual(m.poll_stop(p,205),'next')
   m.begin(p,'old.webp',205,dict(locomotion=SPEC,durationMs=4167));m.request_stop();self.assertIsNone(m.poll_stop(p,205))
 def test_invalid_optional_long_clip_controls_are_rejected(self):
  for values in (dict(entryEnd=-1),dict(entryEnd=60),dict(entryEnd=True),dict(entryEnd=1.5),dict(interruptOnStop='true')):
   with self.subTest(values=values),self.assertRaises(ValueError):profile(dict(locomotion=dict(SPEC,**values)))
 def test_exact_bridge_does_not_repeat_body_endpoints(self):
  p=Player();m=Locomotion()
  with patch('locomotion.PreparedSegment',Segment):
   item=dict(locomotion=dict(SPEC,seamFile='quality-v6/run-seam.webp',seamFrames=7,exactSeamEndpoints=True),durationMs=4167)
   m.begin(p,'clip',205,item,root='.')
   for _ in range(3):
    m.boundary(p,205);self.assertEqual(p.adopted[-1],(1,5));self.assertTrue(p.continuous)
    m.boundary(p,205);self.assertEqual(p.adopted[-1],(28,59))
   m.request_stop();m.boundary(p,205);self.assertEqual(p.adopted[-1],(60,99))
 def test_selection_uses_wings_for_any_height_change_and_direction(self):
  items=[dict(id=k+d,movementKind=k,travelDirection=d,locomotion=SPEC) for k in ('walk','flight') for d in ('left','right')]
  self.assertEqual(selection(items,-100,0)['id'],'walkleft')
  self.assertEqual(selection(items,100,1)['id'],'flightright')
  self.assertEqual(selection(items,0,-100)['movementKind'],'flight')
  self.assertIsNone(selection([],1,0))
 def test_valid_run_is_mirrored_for_left_and_never_replaces_flight(self):
  run=dict(id='run',movementKind='run',travelDirection='both',locomotion=SPEC)
  walk=dict(id='walk',movementKind='walk',travelDirection='left',locomotion=SPEC)
  flight=dict(id='fly',movementKind='flight',travelDirection='left',locomotion=SPEC)
  self.assertIs(selection([run,walk,flight],-500,0),walk)
  self.assertIs(selection([run,walk,flight],-500,0,prefer_run=True),run)
  self.assertIs(selection([run,walk,flight],-500,1,prefer_run=True),flight)
 def test_corrupt_profile_rejected_before_decoder(self):
  for values in (dict(start=-1),dict(end=100),dict(fps=60),dict(sourceFrames=True),dict(forwardOnly=False)):
   with self.assertRaises(ValueError):profile(dict(locomotion=dict(SPEC,**values)))
 def test_forward_body_repeats_then_original_outro_plays_once(self):
  p=Player();m=Locomotion()
  with patch('locomotion.PreparedSegment',Segment):
   m.begin(p,'clip.webp',205,dict(locomotion=SPEC,durationMs=4167));self.assertEqual(p.kw['end_frame'],59)
   for _ in range(3):
    self.assertEqual(m.boundary(p,205),('next',False));self.assertEqual(p.adopted[-1],(28,59))
   self.assertEqual(m.cycles,3);m.request_stop();self.assertEqual(m.boundary(p,205),('next',False));self.assertEqual(p.adopted[-1],(60,99));self.assertEqual(m.phase,'exit')
   self.assertEqual(m.boundary(p,205),(None,True));self.assertFalse(m.active)
 def test_motion_is_only_in_real_step_interval_and_never_in_outro(self):
  p=Player();m=Locomotion()
  with patch('locomotion.PreparedSegment',Segment):
   m.begin(p,'clip',205,dict(locomotion=SPEC,durationMs=4167));p.frame_index=23;self.assertFalse(m.moving(p));p.frame_index=24;self.assertTrue(m.moving(p))
   m.request_stop();self.assertFalse(m.moving(p));m.boundary(p,205);self.assertFalse(m.moving(p))
 def test_slow_prefetch_holds_last_frame_and_dpi_change_reprepares(self):
  p=Player();m=Locomotion()
  with patch('locomotion.PreparedSegment',Segment):
   m.begin(p,'clip',205,dict(locomotion=SPEC,durationMs=4167));old=m.body;old.ready.value=False
   self.assertEqual(m.boundary(p,205),(None,False));self.assertEqual(p.adopted,[])
   self.assertEqual(m.boundary(p,410),('next',False));self.assertTrue(old.closed);self.assertEqual(m.body.size,410);self.assertEqual(m.tail.size,410)
 def test_cancel_and_decoder_error_close_bounded_prefetch(self):
  p=Player();m=Locomotion()
  with patch('locomotion.PreparedSegment',Segment):
   m.begin(p,'clip',205,dict(locomotion=SPEC,durationMs=4167));a,b=m.body,m.tail;p.error='decode_error'
   self.assertEqual(m.boundary(p,205),(None,True));self.assertTrue(a.closed and b.closed);self.assertEqual(m.error,'decode_error');self.assertFalse(m.active)
 def test_seam_is_forward_and_stop_during_seam_finishes_body_before_outro(self):
  p=Player();m=Locomotion()
  with patch('locomotion.PreparedSegment',Segment):
   item=dict(locomotion=dict(SPEC,seamFile='quality-v6/move-seam.webp',seamFrames=7),durationMs=4167)
   m.begin(p,'clip',205,item,root='.');m.boundary(p,205);self.assertEqual(m.phase,'seam');self.assertEqual(p.adopted[-1],(0,6))
   m.request_stop();m.boundary(p,205);self.assertEqual(m.phase,'body');self.assertEqual(p.adopted[-1],(28,59))
   m.boundary(p,205);self.assertEqual(m.phase,'exit');self.assertEqual(p.adopted[-1],(60,99));self.assertEqual(m.boundary(p,205),(None,True))
if __name__=='__main__':unittest.main()
