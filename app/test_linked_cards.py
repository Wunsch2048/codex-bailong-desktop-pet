import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from unittest.mock import patch
from PySide6.QtCore import QRect,QPointF,Qt
from PySide6.QtGui import QPixmap,QPainter
from PySide6.QtWidgets import QWidget
from compact_bubble import CompactBubble
from daily_report import DailyReport
from test_daily_report import sample,APP

class LinkedTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.move(120,630);self.b.show();APP.processEvents()
        self.r=DailyReport(self.b);self.b.report=self.r;self.r.set_snapshot(sample());self.r.open();self.r.animation.setCurrentTime(self.r.animation.duration());APP.processEvents()
    def tearDown(self):self.b.close();self.b.deleteLater();APP.processEvents()
    def test_open_report_morphs_with_settings_and_back_to_normal(self):
        b,r=self.b,self.r
        settings=QWidget()
        original_width=r.content_geometry().width()
        for navigate in (lambda:b.show_page('settings',settings),b.return_to_status):
            start=QRect(r.content_geometry())
            navigate()
            transition=b.size_transition
            self.assertTrue(r.requested and r.follow.committed)
            parts=r.follow.module_morph.shared_parts
            self.assertIn('chrome_0/fixed-left-title',parts)
            self.assertIn('chrome_1/fixed-left-tabs',parts)
            self.assertGreaterEqual(sum(key.startswith('body_') for key in parts),2)
            transition.animation.setCurrentTime(transition.animation.duration()//3)
            from spring_motion import container_progress
            progress=container_progress(r.follow.progress)
            cost=parts['body_hourly/report-panel/fixed-left-cost']
            self.assertIsNone(cost.buffers)
            self.assertAlmostEqual(cost.geometry(progress).left(),
                                   cost.rects[0].left()+(cost.rects[1].left()-cost.rects[0].left())*progress)
            image=r.follow.frame.toImage()
            ratio=image.devicePixelRatio()
            local=cost.geometry(progress).translated(-r.follow.canvas.x(),-r.follow.canvas.y())
            expected=cost.fixed_frames[-1].toImage()
            left=round(local.left()*ratio);top=round(local.top()*ratio)
            # Compare a solid foreground glyph pixel, not the module background.
            background=expected.pixelColor(0,0)
            ink=lambda color:sum(abs(a-b) for a,b in zip(color.getRgb(),background.getRgb()))
            x,y=max(((x,y) for x in range(3,40) for y in range(4,40)),
                    key=lambda pt:ink(expected.pixelColor(*pt)))
            self.assertGreater(ink(expected.pixelColor(x,y)),100)
            self.assertGreater(ink(image.pixelColor(left+x,top+y)),100)
            host=transition.morph.geometry(transition.raw_progress)
            middle=r.follow.geometry()
            self.assertAlmostEqual(middle.width(),host.width(),delta=1)
            self.assertAlmostEqual(middle.bottom()+r.GAP,host.top(),delta=1)
            self.assertNotEqual(middle.width(),start.width())
            self.assertNotEqual(middle.width(),transition.target_rect.width())
            transition.complete()
            r.follow.release()
            self.assertTrue(r.requested and r.surface.isVisible())
            self.assertEqual(r.content_geometry(),r.geometry_for_host(b.geometry()))
        self.assertEqual(r.content_geometry().width(),original_width)
    def test_report_uses_visible_card_edges_and_stable_native_canvas_in_both_directions(self):
        b=self.b;r=self.r
        for _ in range(2):
            initial=r.content_geometry();b.toggle_details();t=b.size_transition;t.animation.pause();self.assertTrue(r.follow.active)
            self.assertEqual(r.follow.geometry(0.).toRect(),initial);canvas=QRect(r.geometry());previous=None
            for i in range(0,100,4):
                at=i/100;t.advance(at);host=t.morph.geometry(at);report=r.follow.geometry()
                self.assertAlmostEqual(report.left(),host.left(),delta=.01);self.assertAlmostEqual(report.width(),host.width(),delta=.01)
                self.assertAlmostEqual(report.bottom()+r.GAP,host.top(),delta=1)
                self.assertEqual(r.geometry(),canvas)
                if previous:self.assertLess(abs(report.x()-previous.x()),12)
                previous=report
            target=QRect(t.target_rect);t.animation.resume();t.complete();r.follow.release()
            self.assertFalse(r.follow.active);self.assertTrue(r.surface.isVisible());self.assertEqual(r.content_geometry().x(),target.x());self.assertEqual(r.content_geometry().width(),target.width())
            self.assertEqual(r.content_geometry().bottom()+1+r.GAP,target.y())
    def _check_parts_during_width_change(self,*suffixes):
        b,r=self.b,self.r;page=r.page;scroll=r.scroll
        for navigate in (b.toggle_details,b.toggle_details):
            before=r.content_geometry()
            navigate()
            transition=b.size_transition
            self.assertTrue(r.follow.committed)
            morph=r.follow.module_morph
            for suffix in suffixes:
                matches=[part for key,part in morph.shared_parts.items() if key.endswith(suffix)]
                self.assertTrue(matches,(suffix,list(morph.shared_parts)))
                if suffix.startswith('/fixed-'):
                    self.assertTrue(all(part.fixed and part.buffers is None for part in matches))
            transition.advance(.45)
            middle=r.follow.geometry()
            self.assertNotEqual(middle.width(),before.width())
            self.assertNotEqual(middle.width(),r.follow.end.width())
            image=r.follow.frame.toImage();ratio=image.devicePixelRatio()
            local=middle.translated(-r.follow.canvas.x(),-r.follow.canvas.y())
            self.assertEqual(image.pixelColor(round(local.center().x()*ratio),round(local.center().y()*ratio)).alpha(),255)
            transition.complete();r.follow.release()
            self.assertIs(r.scroll,scroll);self.assertEqual(r.page,page)
            self.assertEqual(r.content_geometry(),r.geometry_for_host(b.geometry()))

    def _open_page(self,page):
        self.r.set_page(page)
        APP.processEvents()
        self.r.page_fade.clear()

    def test_models_and_quota_keep_native_size_labels_and_moving_chart_parts(self):
        from test_quota_compare_ui import row
        r=self.r;data=sample()
        data['quota_history']={'cycles':[row(),row(id='older',closed=True,start=1791695200)]}
        r.set_snapshot(data)
        self._open_page('models');r.select_model('gpt-6.1-sol')
        self._check_parts_during_width_change('/fixed-left-peak','/fixed-left-average','/bars','/fixed-right-date','/fixed-right-title')
        self.assertEqual(r.selected_model,'gpt-6.1-sol')
        self._open_page('cycle')
        self._check_parts_during_width_change('/report-panel8','/bars','/fixed-left-value-axis','/fixed-right-date')

    def test_model_rate_curve_and_weighted_average_follow_all_time_ranges(self):
        r=self.r;data=sample()
        data['report']['rates']={'days':{
            '2026-10-12':dict(rate=10.,output=10,duration_ms=1000),
            '2026-10-17':dict(rate=30.,output=90,duration_ms=3000)}}
        r.set_snapshot(data);self._open_page('models')
        for period in ('all','30d','7d'):
            r.set_period(period);r.plot.reveal.progress=1.;r.plot.grab()
            self.assertEqual((r.model_rate_label.text(),r.model_rate_label.unit),('25.0','tok/s'))
            self.assertEqual(len(r.plot._rate_points),2)
            self.assertTrue(any(label=='回合均速' for record in r.plot._combo_records for label,_,_ in record['rows']))
        r.select_model('gpt-6.1-sol');r.plot.grab()
        self.assertIn('全模型平均 Token 速率',r.model_rate_label.accessibleName())

    def test_cost_list_detail_and_pricing_stay_open_through_width_change(self):
        from cost_preferences import defaults
        from pricing_ui import PricingEditor
        from test_pricing_navigation import Service
        r=self.r;data=sample()
        rows=[dict(id=str(i),name='项目 '+str(i),path='D:/p',cost=2.,parts=[1.,.2,.8],
                   tokens=1000,pending_tokens=0,models=[],sessions=1,archived=False) for i in range(12)]
        data['projects']={'ranges':{'all':rows}}
        r.set_snapshot(data);self._open_page('projects');cost=r.project_view
        self._check_parts_during_width_change('/fixed-right-sort','/fixed-right-name','/progress')
        bar=cost.list.verticalScrollBar();bar.setValue(150);position=bar.value()
        self._check_parts_during_width_change('/fixed-right-name','/progress')
        self.assertEqual(bar.value(),position)
        with patch.object(cost,'request_sessions'):
            cost.select(rows[0]);APP.processEvents();cost.detail_motion.clear()
            self._check_parts_during_width_change('/report-panel10','/fixed-left-name','/report-panel-segment-pill')
        with patch('pricing_ui.load',return_value=defaults()):
            editor=PricingEditor(cost,price_service=Service())
        editor.draft['currency']='HKD'
        try:
            self._check_parts_during_width_change('/report-panel9','/report-panel-segments')
            self.assertTrue(editor.isVisible());self.assertEqual(editor.draft['currency'],'HKD')
        finally:editor.close()

    def test_quota_official_rates_page_stays_open_and_tracks_its_rows(self):
        from official_rates_ui import OfficialRatesPage
        from test_pricing_navigation import Service
        r=self.r;self._open_page('cycle')
        page=OfficialRatesPage(r.scroll.viewport(),controller=Service('credits_per_million_tokens'))
        APP.processEvents();page.cancel_motion()
        try:
            self._check_parts_during_width_change('/report-panel8','/fixed-left-control')
            self.assertTrue(page.isVisible());self.assertEqual(page.geometry(),r.scroll.viewport().rect())
        finally:page.close()
    def test_preparation_restores_updates_only_under_hidden_target_content(self):
        b=self.b;states=[];original=b.setUpdatesEnabled
        def observe(enabled):
            if enabled and b.size_transition.preparing:states.append(b.content.isVisible())
            return original(enabled)
        self.r.dismiss();self.r.animation.setCurrentTime(self.r.animation.duration())
        with patch.object(b,'setUpdatesEnabled',side_effect=observe):b.set_mode('mini')
        self.assertTrue(states);self.assertFalse(any(states));b.size_transition.complete();b.size_transition.release_landing()
        with patch.object(b,'setUpdatesEnabled',side_effect=observe):b.set_mode('auto')
        self.assertFalse(any(states));b.size_transition.complete()
    def test_landing_backing_store_is_cleared_while_visible_before_reuse(self):
        landing=self.b.size_transition.landing;image=QPixmap(60,40);image.fill(Qt.GlobalColor.red)
        landing.present(image,QRect(10,10,60,40));calls=[];repaint=landing.repaint
        with patch.object(landing,'repaint',side_effect=lambda:(calls.append((landing.isVisible(),landing.image is None)),repaint())):landing.release()
        self.assertEqual(calls,[(True,True)]);self.assertIsNone(landing.image);self.assertFalse(landing.isVisible())
        landing.prepare(QRect(20,20,60,40));self.assertEqual(landing.grab().toImage().pixelColor(30,20).alpha(),0);landing.release()
    def test_report_open_in_flight_queues_expansion_without_teleport(self):
        r=self.r;r.dismiss();r.animation.setCurrentTime(r.animation.duration());r.open();r.animation.setCurrentTime(100)
        fraction=r.fraction;geometry=QRect(r.geometry());self.b.toggle_details()
        self.assertFalse(self.b.size_transition.running);self.assertEqual(r.geometry(),geometry);self.assertEqual(r.fraction,fraction)
        r.animation.setCurrentTime(r.animation.duration());self.assertTrue(self.b.size_transition.running)
        self.b.size_transition.complete();self.assertTrue(r.requested)
    def test_mini_closes_report_without_starting_report_follow(self):
        self.b.set_mode('mini');self.assertFalse(self.r.follow.active);self.assertTrue(self.r._animating)
        self.r.animation.setCurrentTime(self.r.animation.duration());self.b.size_transition.complete()
        self.assertFalse(self.r.isVisible());self.assertFalse(self.r.follow.landing.isVisible())
    def test_latest_report_refresh_waits_for_host_handoff(self):
        import copy
        self.b.toggle_details();t=self.b.size_transition;t.animation.pause();r=self.r;key=r.follow.new.cacheKey();canvas=QRect(r.geometry())
        latest=copy.deepcopy(sample());latest['report']['messages']=12345;r.set_snapshot(latest)
        self.assertTrue(r._pending_rebuild);self.assertEqual(r.follow.new.cacheKey(),key);self.assertEqual(r.geometry(),canvas)
        t.animation.resume();t.complete();r.follow.release()
        self.assertFalse(r._pending_rebuild);self.assertEqual(r.report['messages'],12345);self.assertEqual(r.content_geometry().width(),self.b.width())
    def test_live_native_report_is_suppressed_before_any_target_layout_and_restored_after_handoff(self):
        r=self.r;f=r.follow;native=QRect(r.geometry());opacity=r.windowOpacity();f.begin()
        self.assertEqual(r.windowOpacity(),0.);self.assertTrue(f.shield.isVisible());self.assertIsNotNone(f.shield.image)
        f.commit(self.b.content_geometry().adjusted(-50,0,50,0));canvas=QRect(f.landing.geometry())
        self.assertIsNone(f.shield.image);self.assertTrue(f.landing.isVisible())
        for t in (0.,.01,.15,.4,.7,.99,1.):
            f.advance(t);self.assertEqual(r.windowOpacity(),0.);self.assertEqual(r.geometry(),native);self.assertEqual(f.landing.geometry(),canvas)
        f.finish();self.assertAlmostEqual(r.windowOpacity(),opacity);self.assertFalse(r.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertTrue(f.landing.isVisible());f.release();self.assertIsNone(f.frame);self.assertIsNone(f.landing.image)
    def test_preparation_cancel_restores_opacity_input_and_removes_both_surfaces(self):
        f=self.r.follow;f.begin();self.assertTrue(f.shield.isVisible());f.cancel()
        self.assertEqual(self.r.windowOpacity(),1.);self.assertIsNone(f.landing.image);self.assertIsNone(f.shield.image);self.assertFalse(f.active)
    def test_complementary_mix_has_no_alpha_or_background_brightness_pulse(self):
        from PySide6.QtCore import QRectF
        f=self.r.follow;f.begin();f.commit(self.b.content_geometry().translated(-50,0))
        # Complete opaque snapshots of identical colour must stay identical;
        # source-over fading two half-opacity layers previously lost alpha.
        f.old.fill(Qt.GlobalColor.red);f.new.fill(Qt.GlobalColor.red)
        for t in (.01,.2,.4,.5,.7,.99):
            f.advance(t);rect=f.geometry().translated(-f.canvas.x(),-f.canvas.y());ratio=f.frame.devicePixelRatioF()
            colour=f.frame.toImage().pixelColor(round(rect.center().x()*ratio),round(rect.center().y()*ratio))
            self.assertGreaterEqual(colour.alpha(),254);self.assertGreaterEqual(colour.red(),254);self.assertEqual(colour.green(),0)
        f.cancel()
    def test_live_status_height_changes_use_the_same_fixed_presentation_canvas(self):
        b=self.b;r=self.r;scroller=b.status_view
        for text in ('测试状态更新内容很长，需要换行并连续调整卡片高度。'*3,'正在思考'):
            scroller.set_status(text);native=None
            for ms in (40,80,130,180,240,290):
                scroller.animation.setCurrentTime(ms)
                if not r.follow.active:continue
                self.assertTrue(r.follow.status_tracking);self.assertEqual(r.windowOpacity(),0.)
                q=r.follow.geometry();self.assertAlmostEqual(q.bottom()+r.GAP,b.y(),delta=1)
                if native is None:native=QRect(r.geometry())
                self.assertEqual(r.geometry(),native)
            self.assertIsNotNone(native)
            scroller.animation.resume();scroller.animation.setCurrentTime(300);r.follow.release()
            self.assertFalse(r.follow.active);self.assertEqual(r.windowOpacity(),1.)
    def test_navigation_during_status_height_change_releases_its_previous_opacity_hold(self):
        b=self.b;r=self.r;b.status_view.set_status('正在检查较长的状态信息和日报窗口过渡。'*3);b.status_view.animation.setCurrentTime(150)
        self.assertTrue(r.follow.status_tracking);self.assertEqual(r.windowOpacity(),0.)
        b.toggle_details();self.assertFalse(r.follow.status_tracking);self.assertTrue(r.follow.active)
        b.size_transition.complete();r.follow.release();self.assertEqual(r.windowOpacity(),1.)
        self.assertFalse(r.follow.active);self.assertFalse(r.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

if __name__=='__main__':unittest.main()
