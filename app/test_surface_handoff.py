"""Geometry, native preparation and exact pixels at both capsule handoffs."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from PySide6.QtCore import QPoint,Qt
from PySide6.QtGui import QPainter,QPixmap
from PySide6.QtWidgets import QWidget
from compact_bubble import CompactBubble
from spring_motion import container_progress
from surface_morph import raster_offset,pixel_size
from test_panel_transition import APP


def frame(canvas,pixmap,pos):
    ratio=pixmap.devicePixelRatioF();image=QPixmap(pixel_size(canvas.width(),ratio),pixel_size(canvas.height(),ratio));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
    screen=APP.primaryScreen();origin=screen.geometry().topLeft()
    p=QPainter(image);p.drawPixmap(raster_offset(pos,canvas.topLeft(),ratio,origin),pixmap);p.end()
    return image.toImage()


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.move(10000,10000);self.b.show();APP.processEvents()
        self.b.status_indicator.clock=lambda:0.
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater();APP.processEvents()
    def test_container_progress_is_monotone_and_never_overshoots(self):
        values=[container_progress(i/1000) for i in range(1001)]
        self.assertEqual(values[0],0.);self.assertEqual(values[-1],1.)
        self.assertTrue(all(0<=v<=1 for v in values))
        self.assertTrue(all(z>=a for a,z in zip(values,values[1:])))
        self.assertTrue(all(v==1 for v in values[900:]))
    def test_all_capsule_routes_have_no_reverse_edge_travel(self):
        b=self.b
        for mode,target in [('mini',None),('auto',None),('mini',None),('settings',QWidget()),('mini',None),('chat',QWidget()),('mini',None),('details',None),('details',None)]:
            if mode=='details':b.toggle_details()
            elif target is None:b.set_mode(mode)
            else:b.show_page(mode,target)
            t=b.size_transition;t.animation.pause()
            rectangles=[t.morph.geometry(i/1000) for i in range(1001)]
            for getter in ('left','top','right','bottom','width','height'):
                values=[getattr(r,getter)() for r in rectangles];delta=values[-1]-values[0]
                self.assertTrue(all((z-a)*(1 if delta>=0 else -1)>=-1e-8 for a,z in zip(values,values[1:])),getter)
            t.animation.resume();t.complete()
    def test_preparation_is_frozen_but_final_capture_contains_children(self):
        b=self.b;b.size_transition.begin();self.assertFalse(b.updatesEnabled())
        b.bubble_mode='mini';b.redraw();self.assertFalse(b.updatesEnabled())
        b.size_transition.commit();self.assertTrue(b.updatesEnabled())
        self.assertTrue(b.size_transition.running)
        self.assertTrue(b.size_transition.morph.end.satellites)
    def test_status_updates_do_not_rebuild_the_landing_view(self):
        b=self.b
        for mode in ('mini','auto'):
            b.set_mode(mode);t=b.size_transition
            with patch.object(b,'redraw',wraps=b.redraw) as rebuild:
                b.message('最新状态');b.status_indicator.observe(dict(state='working',active=1));t.complete()
                self.assertEqual(rebuild.call_count,0)
                self.assertFalse(t.status_deferred)
                if mode=='auto':self.assertEqual(b.status_view.text(),'最新状态')
        b.set_mode('mini');b.size_transition.complete();b.toggle_details();t=b.size_transition
        self.assertTrue(b.expanded)
        with patch.object(b,'redraw',wraps=b.redraw) as rebuild:
            b.message('详情中的最新状态');t.complete()
            self.assertEqual(rebuild.call_count,0);self.assertEqual(b.status_view.text(),'详情中的最新状态')
    def test_endpoint_pixels_match_live_widgets(self):
        b=self.b
        for mode,target in [('mini',None),('auto',None),('mini',None),('settings',QWidget()),('mini',None),('chat',QWidget()),('mini',None),('details',None),('details',None)]:
            before=b.grab();pos=b.pos()
            if mode=='details':b.toggle_details()
            elif target is None:b.set_mode(mode)
            else:b.show_page(mode,target)
            t=b.size_transition;t.animation.pause();canvas=t.canvas_rect
            for at in (0.,1.):
                ratio=b.devicePixelRatioF();pix=QPixmap(pixel_size(canvas.width(),ratio),pixel_size(canvas.height(),ratio));pix.setDevicePixelRatio(ratio);pix.fill(Qt.GlobalColor.transparent);p=QPainter(pix)
                t.morph.paint(p,at,canvas);p.end();painted=pix.toImage()
                if at==0.:reference=frame(canvas,before,pos)
                else:
                    t.animation.resume();t.complete();reference=frame(canvas,b.grab(),b.pos())
                errors=[abs(x-y) for x,y in zip(bytes(painted.constBits()),bytes(reference.constBits()))]
                error=max(errors);alpha=max(errors[3::4]);significant=sum(max(errors[i:i+4])>2 for i in range(0,len(errors),4))
                if error>32 or alpha>1 or significant>8:
                    from pathlib import Path
                    out=Path(__file__).resolve().parent.parent/'胶囊双向过渡修复'
                    painted.save(str(out/f'{mode}-{at}-painted.png'));reference.save(str(out/f'{mode}-{at}-reference.png'))
                # A few antialiased font pixels differ with render/grab paths;
                # a missing row or a shifted edge must never be accepted.
                self.assertLessEqual(error,32,(mode,at));self.assertLessEqual(alpha,1,(mode,at));self.assertLessEqual(significant,8,(mode,at))
    def test_cancelled_preparation_releases_cover_and_restores_updates(self):
        b=self.b;t=b.size_transition;t.begin();b.hide()
        self.assertTrue(b.updatesEnabled());self.assertIsNone(t.before);self.assertIsNone(t.cover.image)
        self.assertTrue(t.cover.isHidden());b.show();self.assertTrue(b.content.isVisible())
    def test_nested_close_keeps_original_update_state(self):
        b=self.b;b.show_page('settings',QWidget());b.size_transition.complete()
        b.enabled=False;b.return_to_status();b.size_transition.complete()
        self.assertTrue(b.updatesEnabled());self.assertFalse(b.isVisible())
        b.enabled=True;b.redraw();self.assertTrue(b.updatesEnabled());self.assertTrue(b.content.isVisible())
    def test_landing_blend_never_opens_a_transparent_gap(self):
        b=self.b;b.set_mode('mini');b.size_transition.complete();b.set_mode('auto');t=b.size_transition;t.animation.pause()
        for step in range(90,100):
            t.animation.setCurrentTime(round(t.animation.duration()*step/100))
            rect=t.morph.geometry(step/100);point=rect.center()-b.pos();image=b.grab().toImage();ratio=image.devicePixelRatioF()
            self.assertEqual(image.pixelColor(round(point.x()*ratio),round(point.y()*ratio)).alpha(),255)
        t.animation.resume();t.complete()


if __name__=='__main__':unittest.main()
