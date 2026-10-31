"""Contracts for ordered liquid motion and identity-preserving native paint."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import math
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPainter

from status_motion import GlyphMotion,busy_liquid_parts,idle_liquid_parts,BUSY_BREATH_SECONDS,BUSY_ROTATION_SECONDS,IDLE_ROTATION_SECONDS,BUSY_PAIRS,BUSY_GLOBAL_TURNS,BUSY_OUTER_SPEED
from status_paint import paint_liquid_glyph


def render(parts,island=False,scale=4):
    image=QImage(16*scale,16*scale,QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.scale(scale,scale)
    paint_liquid_glyph(painter,parts,island);painter.end()
    return image


def components(image):
    """Opaque connected regions, ignoring isolated antialiasing specks."""
    remaining={(x,y) for y in range(image.height()) for x in range(image.width())
               if image.pixelColor(x,y).alpha()>=128}
    regions=[]
    while remaining:
        todo=[remaining.pop()];region=set(todo)
        while todo:
            x,y=todo.pop()
            for point in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if point in remaining:
                    remaining.remove(point);region.add(point);todo.append(point)
        if len(region)>4:regions.append(region)
    return regions


class LiquidStatusTests(unittest.TestCase):
    def assertPartsClose(self,a,b,tolerance=1e-8):
        self.assertEqual(len(a),len(b))
        for left,right in zip(a,b):
            for x,y in zip(left,right):self.assertLessEqual(abs(x-y),tolerance)

    def test_full_loop_preserves_ball_and_color_identity_without_a_beat_jump(self):
        # Compare by identity, not nearest position: rotating the mint identity
        # into a lavender ball's slot cannot pass this seam check.
        for time in (0,.19,.43,.95,1.5,2.75,4.55,8.3,10.799):
            parts=busy_liquid_parts(time)
            self.assertPartsClose(parts,busy_liquid_parts(time+BUSY_ROTATION_SECONDS))
            self.assertEqual([p.mint for p in parts],[0,1,0])
            self.assertTrue(all(p.hole==0 and p.opacity==1 for p in parts))
        for beat in range(1,13):
            self.assertPartsClose(tuple(p._replace(depth=0) for p in busy_liquid_parts(beat*BUSY_BREATH_SECONDS-.001)),
                                  tuple(p._replace(depth=0) for p in busy_liquid_parts(beat*BUSY_BREATH_SECONDS+.001)),.02)
        first,last=render(busy_liquid_parts(0)),render(busy_liquid_parts(BUSY_ROTATION_SECONDS))
        self.assertEqual(bytes(first.constBits()),bytes(last.constBits()))

    def test_center_pass_alternates_with_noncentral_orbital_exchange(self):
        for beat in range(12):
            middle=busy_liquid_parts((beat+.25)*BUSY_BREATH_SECONDS)
            for part in middle:
                distance=math.hypot(part.x-8,part.y-8)
                if beat%2==0:self.assertLess(distance,1e-9)
                else:self.assertGreater(distance,2.7)
        before,after=(busy_liquid_parts(t*BUSY_BREATH_SECONDS) for t in (.96,.99))
        shifts=[]
        for a,b in zip(before,after):
            shift=math.atan2(b.y-8,b.x-8)-math.atan2(a.y-8,a.x-8)
            shifts.append(math.atan2(math.sin(shift),math.cos(shift)))
            self.assertAlmostEqual(math.hypot(a.x-8,a.y-8),math.hypot(b.x-8,b.y-8))
        expected=math.tau*BUSY_GLOBAL_TURNS*BUSY_OUTER_SPEED*(.99-.96)*BUSY_BREATH_SECONDS/BUSY_ROTATION_SECONDS
        for angle in shifts:self.assertAlmostEqual(angle,expected)
        self.assertLess(max(shifts)-min(shifts),1e-8)

    def test_neck_changes_pair_and_initiator_without_dragging_receiver(self):
        for beat,(active,receiver) in enumerate(BUSY_PAIRS):
            with self.subTest(beat=beat):
                parts=busy_liquid_parts((beat+.69)*BUSY_BREATH_SECONDS)
                edge=active if receiver==(active+1)%3 else receiver
                self.assertEqual([i for i,p in enumerate(parts) if p.bond>.5],[edge])
                for island in (False,True):self.assertEqual(len(components(render(parts,island))),2)
                first,second=parts[active],parts[receiver]
                self.assertAlmostEqual(math.hypot(first.x-second.x,first.y-second.y),37/8)
                released=busy_liquid_parts((beat+.98)*BUSY_BREATH_SECONDS)
                self.assertEqual([p.bond for p in released],[0,0,0])
                self.assertEqual(len(components(render(released))),3)
                # Global rotation is allowed; the receiver and third stay at
                # the full orbital radius while only the initiator travels.
                for phase in (.5,.6,.69,.85):
                    moving=busy_liquid_parts((beat+phase)*BUSY_BREATH_SECONDS)
                    for i in (receiver,3-active-receiver):
                        self.assertAlmostEqual(math.hypot(moving[i].x-8,moving[i].y-8),33/8)

    def test_three_colors_survive_contact_on_both_backgrounds(self):
        references={}
        for time in (0, .69*BUSY_BREATH_SECONDS,1.69*BUSY_BREATH_SECONDS,2.69*BUSY_BREATH_SECONDS):
            parts=busy_liquid_parts(time)
            for island in (False,True):
                image=render(parts,island)
                for index,part in enumerate(parts):
                    color=image.pixelColor(round(part.x*4),round(part.y*4))
                    self.assertGreater(color.alpha(),250)
                    rgb=color.getRgb()[:3];key=(island,index)
                    if key not in references:references[key]=rgb
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(rgb,references[key])),24)
        for island in (False,True):self.assertEqual(len({references[(island,i)] for i in range(3)}),3)

    def test_idle_rotates_as_rigid_triad_without_crossing_breathing_or_bonding(self):
        motion=GlyphMotion()
        self.assertTrue(motion.moving(10))
        self.assertNotEqual(motion.sample(1),motion.sample(2))
        self.assertPartsClose(idle_liquid_parts(0),idle_liquid_parts(IDLE_ROTATION_SECONDS))
        for t in (0,1,4,10,17.9):
            parts=idle_liquid_parts(t)
            self.assertEqual(len(components(render(parts))),3)
            for p in parts:
                self.assertEqual(p.bond,0);self.assertEqual(p.opacity,1)
                self.assertAlmostEqual(math.hypot(p.x-8,p.y-8),33/8)
            distance=math.hypot(parts[0].x-parts[1].x,parts[0].y-parts[1].y)
            self.assertAlmostEqual(distance,33/8*math.sqrt(3))

    def test_retarget_from_live_neck_and_warning_keeps_color_and_shape_continuous(self):
        motion=GlyphMotion();motion.set_state('busy',0,animate=False)
        now=.69*BUSY_BREATH_SECONDS
        self.assertGreater(max(p.bond for p in motion.sample(now)),.9)
        for state in ('warning','waiting','paused','busy','complete','attention'):
            before=motion.sample(now);motion.set_state(state,now)
            self.assertPartsClose(before,motion.sample(now))
            after=motion.sample(now+.06)
            self.assertNotEqual(before,after)
            for part in after:
                self.assertTrue(all(math.isfinite(v) for v in part))
                self.assertTrue(all(0<=v<=1 for v in (part.mint,part.bond,part.warm)))
            now+=.06
        warning=GlyphMotion();warning.set_state('warning',0,animate=False)
        before=warning.sample(1.)
        self.assertTrue(all(p.warm==1 for p in before))
        warning.set_state('busy',1.)
        self.assertPartsClose(before,warning.sample(1.))
        self.assertTrue(all(0<p.warm<1 for p in warning.sample(1.2)))
        self.assertTrue(all(p.warm==0 for p in warning.sample(1.6)))

    def test_settled_task_symbols_stay_distinct_visible_and_stop_moving(self):
        # Check topology as well as geometry: two pause rails, an exclamation
        # with a separate dot and one connected checkmark must survive painting.
        region_counts={'paused':2,'attention':2,'warning':2,'complete':1}
        silhouettes={}
        for state,expected in region_counts.items():
            motion=GlyphMotion();motion.set_state(state,0)
            parts=motion.sample(10)
            self.assertFalse(motion.moving(10))
            self.assertEqual(parts,motion.sample(11))
            self.assertEqual(parts[2].mint,1)
            image=render(parts)
            self.assertEqual(len(components(image)),expected)
            # Alpha silhouettes distinguish actual task symbols. Attention and
            # warning intentionally share shape, using palette and text instead.
            silhouettes[state]=bytes(image.constBits())[3::4]
            for scale in (1,2):
                small=render(parts,scale=scale)
                self.assertTrue(any(small.pixelColor(x,y).alpha()>150
                                    for x in range(small.width()) for y in range(small.height())))
                edge=small.width()-1
                self.assertTrue(all(small.pixelColor(x,y).alpha()<128
                                    for i in range(small.width())
                                    for x,y in ((i,0),(i,edge),(0,i),(edge,i))))
        self.assertEqual(len({silhouettes[s] for s in ('paused','attention','complete')}),3)


if __name__=='__main__':unittest.main()
