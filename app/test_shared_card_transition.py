"""Shared content keeps its identity and progress across normal/detail cards."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QPainter,QPixmap
from PySide6.QtWidgets import QApplication,QWidget
from compact_bubble import CompactBubble
from quota_summary import QuotaSummary
from surface_morph import pixel_size
from spring_motion import container_progress

APP=QApplication.instance() or QApplication([])

class SharedCardTransitionTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.windows=[dict(name='一周',remaining=73,resetsAt=None)]
        self.b.status='正在编辑文件';self.b.redraw();self.b.move(200,500);self.b.show();APP.processEvents();self.b.size_transition.complete();APP.processEvents()
    def tearDown(self):
        self.b.size_transition.complete();self.b.close();self.b.deleteLater();APP.processEvents()
    def transition(self):
        self.b.toggle_details();self.b.size_transition.animation.pause();return self.b.size_transition
    def test_reused_content_keeps_complete_endpoint_pixels_and_does_not_render_root_again(self):
        from surface_morph import complete_frame,SurfaceState
        b=self.b;content=complete_frame(b);original=content.toImage().copy()
        render=QWidget.render
        def guarded(widget,*args,**kwargs):
            if widget is b.content:raise AssertionError('duplicate target rendering')
            return render(widget,*args,**kwargs)
        with patch.object(QWidget,'render',guarded):end=SurfaceState.capture(b,frame=content,content=content)
        self.assertEqual(bytes(original.constBits()),bytes(end.frame.toImage().constBits()))
        self.assertEqual(content.toImage().pixelColor(0,0).alpha(),0)
        self.assertEqual(end.frame.toImage().pixelColor(0,0).alpha(),0)
    def test_layout_settling_ignores_inactive_pages_but_handles_a_hidden_preparation_root(self):
        from PySide6.QtWidgets import QStackedWidget,QVBoxLayout,QLabel
        from panel_transition import settle_visible
        root=QWidget();layout=QVBoxLayout(root);stack=QStackedWidget();layout.addWidget(stack)
        pages=[]
        for name in ('visible','inactive'):
            page=QWidget();QVBoxLayout(page).addWidget(QLabel(name));stack.addWidget(page);pages.append(page)
        root.show();APP.processEvents();root.hide()
        active=settle_visible(root)
        self.assertIn(pages[0],active);self.assertNotIn(pages[1],active)
        stack.setCurrentIndex(1);active=settle_visible(root)
        self.assertIn(pages[1],active);self.assertNotIn(pages[0],active)
        root.deleteLater();APP.processEvents()
    def test_conversation_text_stays_visible_between_endpoints(self):
        for sid in ('a','b'):
            self.b.roster.observe(dict(session=sid,state='working',active=1,title='检查会话 '+sid,display='正在编辑文件'))
        self.b.redraw();APP.processEvents()
        for direction in ('expand','collapse'):
            t=self.transition();m=t.morph;canvas=t.canvas_rect;ratio=self.b.devicePixelRatioF()
            part=m.shared_parts['conversations']
            for value in (.2,.4,.6,.8):
                image=QPixmap(pixel_size(canvas.width(),ratio),pixel_size(canvas.height(),ratio));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
                p=QPainter(image);m.paint(p,value,canvas);p.end();painted=image.toImage()
                rect=part.geometry(container_progress(value)).translated(-canvas.x(),-canvas.y()).toAlignedRect()
                dark=sum(1 for y in range(rect.top()+1,rect.bottom()) for x in range(rect.left()+1,rect.right())
                         if painted.pixelColor(pixel_size(x,ratio),pixel_size(y,ratio)).lightness()<180)
                self.assertGreater(dark,20,(direction,value,'status row background hid its text'))
            t.animation.resume();t.complete();APP.processEvents()
    def test_common_sections_have_one_path_in_both_directions(self):
        required={'heading','conversations','quota','statistics','today_tokens',*(f'action_{i}' for i in range(4))}
        for _ in range(2):
            t=self.transition();m=t.morph
            self.assertTrue(required<=set(m.shared_parts))
            for index,image in enumerate(m.body_frames):
                for part in m.shared_parts.values():
                    self.assertEqual(image.toImage().pixelColor(part.pixel_rects[index].center()).alpha(),0)
            for part in m.shared_parts.values():
                self.assertEqual(part.geometry(0),part.rects[0]);self.assertEqual(part.geometry(1),part.rects[1])
                for value in (0,.2,.4,.6,.8,1):
                    self.assertTrue(m.geometry(value).adjusted(-1,-1,1,1).contains(part.geometry(container_progress(value))))
            t.animation.resume();t.complete();APP.processEvents()
    def test_playback_only_uses_prepared_rasters_and_retains_buffers(self):
        t=self.transition();m=t.morph;before={k:p.buffer_builds for k,p in m.shared_parts.items()}
        ratio=self.b.devicePixelRatioF();canvas=t.canvas_rect
        image=QPixmap(pixel_size(canvas.width(),ratio),pixel_size(canvas.height(),ratio));image.setDevicePixelRatio(ratio)
        with patch.object(QWidget,'render',side_effect=AssertionError('layout/render during animation')):
            for at in (.1,.25,.4,.55,.7,.85,.95,1):
                image.fill(Qt.GlobalColor.transparent);p=QPainter(image);m.paint(p,at,canvas);p.end()
        self.assertEqual(before,{k:p.buffer_builds for k,p in m.shared_parts.items()})
    def test_expand_preserves_quota_and_chart_progress(self):
        calls=[];original=QuotaSummary.begin_reveal
        def begin(widget):calls.append(widget);return original(widget)
        with patch.object(QuotaSummary,'begin_reveal',begin):self.transition()
        self.assertFalse(calls)
        self.assertAlmostEqual(next(iter(self.b.quota_summary_card.values.values())),.73)
        self.assertEqual(self.b.deck.content.plot.reveal.progress,1.)
    @patch("compact_bubble.time.time",return_value=1800000001.)
    def test_pure_size_toggles_reuse_details_but_new_quota_invalidates_them(self,clock):
        self.b.toggle_details();self.b.size_transition.complete();APP.processEvents();first=self.b.details_tabs
        self.b.toggle_details();self.b.size_transition.complete();APP.processEvents()
        self.assertFalse(first.isVisible())
        self.b.toggle_details();self.b.size_transition.complete();APP.processEvents();self.assertIs(self.b.details_tabs,first)
        self.b.windows=[dict(name='一周',remaining=17,resetsAt=None)];self.b.redraw();APP.processEvents()
        self.assertIsNot(self.b.details_tabs,first)
    def test_expired_prepared_details_are_rebuilt_on_next_open(self):
        self.b.toggle_details();self.b.size_transition.complete();APP.processEvents();first=self.b.details_tabs
        self.b.toggle_details();self.b.size_transition.complete();APP.processEvents()
        self.b._details_cache_until=0
        self.b.toggle_details();self.b.size_transition.complete();APP.processEvents();self.assertIsNot(self.b.details_tabs,first)
    def test_capsule_and_editor_routes_keep_the_existing_transition(self):
        self.b.set_mode('mini');self.b.size_transition.animation.pause()
        self.assertFalse(self.b.size_transition.morph.shared_parts)
        self.b.size_transition.complete();APP.processEvents()
        self.b.set_mode('auto');self.b.size_transition.complete();APP.processEvents()
        self.b.show_page('settings',QWidget());self.b.size_transition.animation.pause()
        self.assertFalse(self.b.size_transition.morph.shared_parts)
    def test_long_session_names_and_details_keep_separate_paths(self):
        self.b.roster.observe(dict(session='test-a',state='working',active=1,title='共享区域连贯移动与性能排查',display='正在编辑文件'))
        self.b.roster.observe(dict(session='test-b',state='working',active=1,title='数据图表交互表现检查',display='运行了命令'))
        self.b.redraw();APP.processEvents();self.b.size_transition.complete();APP.processEvents()
        t=self.transition();keys=set(t.morph.shared_parts)
        for sid in ('test-a','test-b'):
            self.assertIn('conversation_title_'+sid,keys);self.assertIn('conversation_detail_'+sid,keys)
            self.assertEqual(t.morph.shared_parts['conversation_detail_'+sid].fit,'left')
    def test_reset_card_uses_the_same_moving_summary(self):
        self.b.select_dashboard('reset');APP.processEvents()
        t=self.transition()
        self.assertIn('statistics_reset',t.morph.shared_parts)
        self.assertIn('quota',t.morph.shared_parts)

if __name__=='__main__':unittest.main()
