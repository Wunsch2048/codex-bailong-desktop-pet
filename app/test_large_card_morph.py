"""New two-line status rows and unique detail chrome share one morph clock."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtCore import QRectF,QPointF,Qt
from PySide6.QtGui import QPixmap,QPainter,QColor
from PySide6.QtWidgets import QApplication,QWidget
from surface_morph import SurfaceState,SurfaceMorph,SharedPart,shared_descendant,mix_color
from spring_motion import container_progress

APP=QApplication.instance() or QApplication([])


def state(expanded,clip=None):
    rect=QRectF(154,238,360,480) if expanded else QRectF(200,500,268,218)
    shared={'conversations':QRectF(12,76,336,76) if expanded else QRectF(10,30,248,36),
            'conversation_title_a':QRectF(13,76,271,19) if expanded else QRectF(10,30,90,18),
            'conversation_detail_a':QRectF(13,95,334,18) if expanded else QRectF(106,30,152,18)}
    if expanded:shared['conversation_badge_a']=QRectF(289,77,58,17)
    else:shared['conversation_divider_a']=QRectF(100,30,1,18)
    exclusive={'navigation':QRectF(12,40,336,26),'details':QRectF(12,360,336,108)} if expanded else {}
    image=QPixmap(int(rect.width()),int(rect.height()));image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image);p.fillRect(image.rect(),Qt.GlobalColor.white)
    colors={'conversation_title_a':'#ee2020','conversation_detail_a':'#20bb20',
            'conversation_badge_a':'#2020ee','conversation_divider_a':'#eea020',
            'navigation':'#a020ee','details':'#20a0ee'}
    for key,bounds in (shared|exclusive).items():
        if key in colors:p.fillRect(bounds,QColor(colors[key]))
    p.end()
    return SurfaceState(rect,image,QRectF(rect.topLeft(),QPointF(rect.topLeft())),QPixmap(),False,[],
                        frame=image.copy(),frame_origin=rect.topLeft(),screen_origin=QPointF(),page='status',expanded=expanded,
                        shared_bounds=shared,exclusive_bounds=exclusive,
                        visible_bounds={key:QRectF(clip or QRectF(0,0,rect.width(),rect.height())) for key in shared|exclusive})


def render(morph,time):
    canvas=morph.bounds();image=QPixmap(canvas.size());image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image);morph.paint(p,time,canvas);p.end()
    return image.toImage(),canvas


class LargeCardMorphTests(unittest.TestCase):
    def test_transparent_status_background_does_not_become_gray_during_morph(self):
        transparent=QColor(Qt.GlobalColor.transparent);surface=QColor('#fcfafc')
        for time in (.1,.25,.5,.75,.9):
            color=mix_color(transparent,surface,time)
            self.assertEqual((color.red(),color.green(),color.blue()),(surface.red(),surface.green(),surface.blue()))
            self.assertEqual(color.alpha(),round(255*time))
    def test_new_badge_and_removed_divider_are_one_endpoint_overlays(self):
        for reverse in (False,True):
            ends=(state(False),state(True));m=SurfaceMorph(*ends[::-1] if reverse else ends)
            unique={part.key:part for part in m.exclusive_parts}
            self.assertIn('conversation_badge_a',unique);self.assertIn('conversation_divider_a',unique)
            self.assertIs(unique['conversation_badge_a'].anchor,m.shared_parts['conversations'])
            at=.1 if reverse else .65;image,canvas=render(m,at)
            badge=unique['conversation_badge_a'];center=badge.geometry(m.geometry(at),container_progress(at)).center()-QPointF(canvas.topLeft())
            pixel=image.pixelColor(center.toPoint())
            self.assertGreater(pixel.blue(),pixel.red()+30,(reverse,pixel.name()))

    def test_unique_details_use_natural_size_and_exact_live_layout_anchor(self):
        for reverse in (False,True):
            ends=(state(False),state(True));m=SurfaceMorph(*ends[::-1] if reverse else ends)
            for part in m.exclusive_parts:
                if part.overlay:continue
                for time in (0,.3,.6,1):
                    self.assertEqual(part.geometry(m.geometry(time),container_progress(time)).size(),part.local.size())
                endpoint=float(part.index)
                self.assertEqual(part.geometry(m.geometry(endpoint),endpoint),part.local.translated(part.state_rect.topLeft()))

    def test_relocation_moves_all_semantic_paths_and_clips_without_recapture(self):
        m=SurfaceMorph(state(False),state(True));at=.57;f=container_progress(at);delta=QPointF(127,-63)
        shared={key:(part.geometry(f),list(part.clips)) for key,part in m.shared_parts.items()}
        exclusive={part.key:part.geometry(m.geometry(at),f) for part in m.exclusive_parts}
        with patch.object(QWidget,'render',side_effect=AssertionError('recapture during drag')):m.translate(delta)
        for key,part in m.shared_parts.items():
            self.assertEqual(part.geometry(f),shared[key][0].translated(delta))
            self.assertEqual(part.clips,[clip.translated(delta) for clip in shared[key][1]])
        for part in m.exclusive_parts:self.assertEqual(part.geometry(m.geometry(at),f),exclusive[part.key].translated(delta))

    def test_scroll_viewport_clips_prepared_raster_and_playback(self):
        a,z=state(False),state(True,QRectF(12,80,336,30));m=SurfaceMorph(a,z)
        detail=m.shared_parts['conversation_detail_a'];badge=next(p for p in m.exclusive_parts if p.key=='conversation_badge_a')
        self.assertEqual(detail.frames[1].toImage().pixelColor(0,17).alpha(),0)
        self.assertEqual(badge.image.toImage().pixelColor(0,0).alpha(),0)
        image=QPixmap(360,480);image.fill(Qt.GlobalColor.transparent);p=QPainter(image)
        detail.paint(p,1,z.rect);badge.paint(p,1,z.rect,1,z.rect);p.end();painted=image.toImage()
        self.assertEqual(painted.pixelColor(14,111).alpha(),0)
        self.assertGreater(painted.pixelColor(14,100).alpha(),0)

    def test_unrelated_regions_do_not_erase_each_other_by_rectangle_overlap(self):
        a,z=state(False),state(True)
        for endpoint in (a,z):endpoint.shared_bounds['action_0']=QRectF(endpoint.shared_bounds['conversation_title_a'])
        part=SharedPart(a,z,'conversation_title_a')
        self.assertGreater(part.frames[0].toImage().pixelColor(1,1).alpha(),0)
        self.assertTrue(shared_descendant('conversation_badge_a','conversations'))
        self.assertFalse(shared_descendant('action_0','conversation_title_a'))

    def test_final_frame_equals_live_endpoint_in_both_directions(self):
        for a,z in ((state(False),state(True)),(state(True),state(False))):
            m=SurfaceMorph(a,z);image,canvas=render(m,1)
            target=QPixmap(canvas.size());target.fill(Qt.GlobalColor.transparent);p=QPainter(target)
            p.drawPixmap((z.rect.topLeft()-QPointF(canvas.topLeft())).toPoint(),z.frame);p.end()
            self.assertEqual(image,target.toImage())


if __name__=='__main__':unittest.main()
