import os,time,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QToolButton,QWidget
from PySide6.QtCore import QRect,QEvent,Qt,QPoint
from PySide6.QtTest import QTest
from compact_bubble import CompactBubble
from island_widgets import selected_quota,QuotaSatellite
from ui_theme import contrast,SURFACE,INK,MUTED,ISLAND,ON_ISLAND,ISLAND_ICON,ACCENT
APP=QApplication.instance() or QApplication([])

class QuotaPriorityTests(unittest.TestCase):
    def test_short_window_priority_exhaustion_reset_pending_and_fresh_recovery(self):
        five=dict(name='5小时',remaining=20,resetsAt=2000);week=dict(name='一周',remaining=80,resetsAt=9000)
        self.assertEqual(selected_quota([week,five],1000)['name'],'5小时')
        five['remaining']=0;self.assertEqual(selected_quota([five,week],1000)['name'],'一周')
        pending=selected_quota([five,week],2000);self.assertEqual(pending['name'],'5小时');self.assertIsNone(pending['remaining'])
        five.update(remaining=100,resetsAt=20000);self.assertEqual(selected_quota([week,five],2001)['remaining'],100)
    def test_unknown_and_zero_never_fabricate_quota(self):
        self.assertIsNone(selected_quota([],100)['remaining'])
        self.assertEqual(selected_quota([dict(name='5小时',remaining=0)],100)['remaining'],0)
        self.assertIsNone(selected_quota([dict(name='一周',remaining=70,resetsAt=99)],100)['remaining'])

class SatelliteReadabilityTests(unittest.TestCase):
    def test_compact_percentage_preserves_boundary_meaning_and_accessible_precision(self):
        cases=((0,'0%'),(.2,'<1%'),(44.5,'45%'),(59.2,'59%'),(99.9,'99%'),(100,'100%'))
        for value,label in cases:
            widget=QuotaSatellite([dict(name='一周',remaining=value)],'')
            self.assertEqual(widget.value_text(),label)
            self.assertIn(f'{value:g}%',widget.accessibleName())
            self.assertIn('一周',widget.accessibleName())
            widget.deleteLater()
        for value in (None,True,float('nan'),float('inf'),-1,101):
            widget=QuotaSatellite([dict(name='5小时',remaining=value)],'')
            self.assertEqual(widget.value_text(),'—');self.assertIn('未知',widget.accessibleName())
            widget.deleteLater()
    def test_numeric_label_fits_inside_open_arc_at_current_dpi(self):
        from PySide6.QtGui import QFontMetricsF
        for value in (0,.2,1,15,59,99.9,100,None):
            widget=QuotaSatellite([dict(name='一周',remaining=value)],'')
            bounds=None
            for font,text,origin in widget._text_runs:
                part=QFontMetricsF(font).tightBoundingRect(text).translated(origin)
                bounds=part if bounds is None else bounds.united(part)
            self.assertAlmostEqual(bounds.center().x(),20)
            self.assertAlmostEqual(bounds.center().y(),20)
            for point in (bounds.topLeft(),bounds.topRight(),bounds.bottomLeft(),bounds.bottomRight()):
                self.assertLess((point.x()-20)**2+(point.y()-20)**2,14**2)
            widget.deleteLater()
    def test_full_ring_has_track_at_bottom_and_clockwise_balance(self):
        from theme_registry import palette
        for value in (0,50,100,None):
            widget=QuotaSatellite([dict(name='一周',remaining=value)],'')
            widget.move(10000,10000);widget.show();APP.processEvents();image=widget.grab().toImage()
            def at(x,y):return image.pixelColor(round(x*image.devicePixelRatio()),round(y*image.devicePixelRatio())).name()
            self.assertEqual(widget.size().width(),38)
            from theme_registry import color
            self.assertEqual(at(19,36),color(ISLAND))
            self.assertEqual(at(33,19),palette()['pillAccent'] if value in (50,100) else palette()['pillTrack'])
            self.assertEqual(at(5,19),palette()['pillAccent'] if value==100 else palette()['pillTrack'])
            self.assertNotEqual(at(19,33),color(ISLAND))
            widget.hide();widget.deleteLater()
    def test_reveal_keeps_label_static_and_does_not_remeasure_fonts(self):
        from unittest.mock import patch
        widget=QuotaSatellite([dict(name='一周',remaining=59)],'')
        widget.show();APP.processEvents();label=widget._label
        with patch('island_widgets.ui_font',side_effect=AssertionError('Font constructed while painting')):
            widget.reveal.progress=0;first=widget.grab().toImage()
            widget.reveal.progress=1;last=widget.grab().toImage()
        self.assertNotEqual(first,last);self.assertEqual(widget._label,label)
        widget.begin_reveal();widget.start_reveal();self.assertTrue(widget.reveal.animation.state().value)
        widget.hide();self.assertFalse(widget.reveal.animation.state().value);self.assertFalse(widget.timer.isActive())
        widget.deleteLater()
    def test_satellite_click_still_opens_quota_details(self):
        b=CompactBubble();b.windows=[dict(name='一周',remaining=59)]
        try:
            b.set_mode('mini');b.size_transition.complete();b.show();APP.processEvents()
            satellite=b.island.parentWidget().findChild(QuotaSatellite)
            QTest.mouseClick(satellite,Qt.MouseButton.LeftButton)
            b.size_transition.complete();APP.processEvents()
            self.assertFalse(b.is_island());self.assertTrue(b.expanded)
        finally:b.close();b.deleteLater();APP.processEvents()

class ModeTests(unittest.TestCase):
    def setUp(self):self.b=CompactBubble();self.b.move(100,550);self.b.show();APP.processEvents()
    def tearDown(self):self.b.size_transition.complete();self.b.close();self.b.deleteLater();APP.processEvents()
    def finish(self):self.b.size_transition.complete();APP.processEvents()
    def test_stale_auto_collapse_never_changes_minimal_into_capsule(self):
        self.b.auto_compact=True;self.b.bubble_mode='minimal';self.b.redraw()
        self.assertTrue(self.b.is_minimal());self.assertFalse(self.b.is_island())
    def test_auto_idle_and_real_task_update_restore_original(self):
        self.b.evaluate_mode(self.b.last_task_update+91);self.finish();self.assertTrue(self.b.is_island())
        self.b.task_updated(dict(state='working'));self.finish();self.assertFalse(self.b.is_island())
    def test_closed_app_collapses_without_waiting_and_quota_updates_do_not_expand(self):
        self.b.codex_open=False;self.b.evaluate_mode();self.finish();self.assertTrue(self.b.is_island())
        stamp=self.b.last_task_update;self.b.quota([dict(name='一周',remaining=80)]);self.b.message('新额度')
        self.assertEqual(self.b.last_task_update,stamp);self.assertTrue(self.b.is_island())
    def test_manual_mini_is_persistable_and_not_opened_by_status_updates(self):
        choices=[];self.b.modeChanged.connect(choices.append);self.b.set_mode('mini');self.finish()
        self.b.task_updated(dict(state='working'));self.assertTrue(self.b.is_island());self.assertEqual(choices,['mini'])
        self.b.status_indicator.observe(dict(state='working',active=1));self.assertEqual(self.b.island.text.text(),'执行中')
        self.b.status_indicator.notify_complete(dict(session='a',turn='1'));self.assertIn('已完成',self.b.island.text.text())
        self.b.status_indicator.acknowledge();self.assertNotIn('正在检查',self.b.island.text.text())
        self.assertIsNone(self.b.findChild(QToolButton,'island_mode'))
        QTest.mouseClick(self.b.island,Qt.MouseButton.LeftButton,pos=QPoint(80,20));self.finish()
        self.assertFalse(self.b.is_island());self.assertFalse(self.b.expanded);self.assertEqual(choices[-1],'auto')
    def test_island_does_not_layout_raw_messages_or_animate_invisible_scroller(self):
        self.b.set_mode('mini');self.finish();size=self.b.size();self.b.message('很长的具体任务详情'*50)
        self.assertEqual(self.b.size(),size);self.assertTrue(self.b.status_view.isHidden());self.assertFalse(self.b.status_view.animation.state().value)
        self.assertEqual((size.width(),size.height()),(210,38))
        calls=[];self.b.shortcutRequested.connect(lambda:calls.append('shortcut'));self.b.findChild(QToolButton,'island_shortcut').click();self.assertEqual(calls,['shortcut'])
    def test_editing_and_report_do_not_auto_collapse(self):
        self.b.show_page('chat',QWidget());self.finish();self.b.codex_open=False;self.b.evaluate_mode(self.b.last_task_update+500)
        self.assertEqual(self.b.panel_page,'chat');self.assertFalse(self.b.is_island())
    def test_native_canvas_remains_fixed_through_both_modes_and_clicks_restore(self):
        for mode in ('mini','auto'):
            self.b.set_mode(mode);t=self.b.size_transition;rect=QRect(self.b.geometry());handle=int(self.b.winId())
            for ms in range(0,280,20):
                t.animation.setCurrentTime(ms);self.assertEqual(self.b.geometry(),rect);self.assertEqual(int(self.b.winId()),handle)
            self.finish();self.assertTrue(self.b.content.isVisible());self.assertIsNone(t.cover.image);self.assertIsNone(t.before)
    def test_mode_changes_during_transition_keep_latest_request(self):
        self.b.set_mode('mini');t=self.b.size_transition;t.animation.setCurrentTime(100);fraction=t.progress
        self.b.set_mode('auto');self.assertEqual(t.progress,fraction);self.finish();self.finish();self.assertFalse(self.b.is_island())
    def test_palette_contrast(self):
        for fg,bg in ((INK,SURFACE),(MUTED,SURFACE),(ON_ISLAND,ISLAND),(ISLAND_ICON,ISLAND)):self.assertGreaterEqual(contrast(fg,bg),4.5)
        self.assertGreaterEqual(contrast(ACCENT,SURFACE),3)
    def test_long_island_status_is_elided_to_actual_width_and_keeps_overflow(self):
        from PySide6.QtGui import QFontMetrics
        self.b.set_mode('mini');self.finish();icon=self.b.status_indicator
        icon.session_summary='已完成/执行中/一段非常长的状态描述 +62';self.b.island.refresh()
        label=self.b.island.text;self.assertLessEqual(QFontMetrics(label.font()).horizontalAdvance(label.text()),label.width())
        self.assertTrue(label.text().endswith('+62'));self.assertIn('非常长',self.b.island.accessibleName())
    def test_status_group_centers_and_moves_without_resizing_native_canvas(self):
        from PySide6.QtGui import QFontMetrics
        self.b.set_mode('mini');self.finish();island=self.b.island;outer=QRect(self.b.geometry())
        for text in ('执行中/完成','待命','思考中'):
            self.b.status_indicator.session_summary=text;island.refresh()
            self.assertTrue(island.animation.state().value)
            for ms in (0,60,125,190,250):
                island.animation.setCurrentTime(ms);self.assertEqual(self.b.geometry(),outer)
            end=island.text.x()+1+island.text.current_ink.width()
            self.assertAlmostEqual((island.icon.x()+end)/2,island.width()/2,delta=1)
            self.assertFalse(island.animation.state().value)
    def test_status_caption_pauses_for_surface_and_stops_when_hidden(self):
        from PySide6.QtCore import QAbstractAnimation
        self.b.set_mode('mini');self.finish();island=self.b.island
        self.b.status_indicator.session_summary='执行中';island.refresh();island.animation.setCurrentTime(90)
        island.freeze_motion();self.assertEqual(island.animation.state(),QAbstractAnimation.State.Paused)
        island.resume_motion();self.assertEqual(island.animation.state(),QAbstractAnimation.State.Running)
        island.hide();self.assertFalse(island.animation.state().value);self.assertEqual(island.text.progress,1.)
    def test_read_completion_disappears_and_retains_other_running_conversation(self):
        b=self.b;icon=b.status_indicator;clock=[0.];icon.clock=lambda:clock[0]
        for sid,state in [('a','complete'),('b','working')]:b.roster.observe(dict(session=sid,state=state,title='会话'+sid))
        icon.notify_complete(dict(session='a',turn='turn-a'));icon.observe(dict(session='b',state='working',active=1));b.redraw()
        self.assertEqual(len(b.status_view.text().splitlines()),2)
        clock[0]=3.;self.assertTrue(icon.acknowledge_seen([('a','turn-a')]));b.redraw()
        self.assertEqual(icon.visual(),'busy');self.assertNotIn('会话a',b.status_view.text());self.assertIn('会话b',b.status_view.text())

class ChartEntryTests(unittest.TestCase):
    def test_compact_reveal_in_performance_mode_uses_complete_ring(self):
        from settings_controls import set_motion_mode
        set_motion_mode('performance')
        ring=QuotaSatellite([dict(name='一周',remaining=41)],'')
        try:
            ring.begin_reveal();ring.show();APP.processEvents();ring.start_reveal()
            self.assertEqual(ring.reveal.progress,1.);self.assertFalse(ring.reveal.pending)
            self.assertFalse(ring.reveal.animation.state().value)
        finally:ring.close();ring.deleteLater();set_motion_mode('quality');APP.processEvents()

    def test_compact_ring_waits_for_landing_and_resumes_refresh_without_finishing_hidden(self):
        from PySide6.QtCore import QAbstractAnimation
        b=CompactBubble();b.show();APP.processEvents()
        try:
            for mode in ('mini','minimal','mini'):
                b.set_mode(mode);t=b.size_transition
                ring=next(w for w in b.content.findChildren(QuotaSatellite) if w.isVisibleTo(b.content))
                self.assertTrue(ring.reveal.pending);self.assertEqual(ring.reveal.progress,0.)
                ring.start_reveal();self.assertEqual(ring.reveal.animation.state(),QAbstractAnimation.State.Stopped)
                t.complete();APP.processEvents();t.release_landing();APP.processEvents()
                ring=next(w for w in b.content.findChildren(QuotaSatellite) if w.isVisibleTo(b.content))
                self.assertEqual(ring.reveal.animation.state(),QAbstractAnimation.State.Running)
                ring.reveal.animation.setCurrentTime(160);before=ring.reveal.progress
                b.redraw();APP.processEvents()
                fresh=next(w for w in b.content.findChildren(QuotaSatellite) if w.isVisibleTo(b.content))
                self.assertAlmostEqual(fresh.reveal.progress,before,delta=.03)
                self.assertEqual(fresh.reveal.animation.state(),QAbstractAnimation.State.Running)
                fresh.reveal.animation.setCurrentTime(620)
        finally:b.close();b.deleteLater();APP.processEvents()

    def test_entry_starts_at_zero_survives_status_refresh_and_stops_when_hidden(self):
        from token_charts import TokenPlot
        b=CompactBubble();b.show();APP.processEvents()
        try:
            b.select_token_range('day');plot=next(w for w in b.findChildren(TokenPlot) if w.isVisible())
            self.assertEqual(plot.reveal.progress,0.);plot.reveal.animation.setCurrentTime(180);progress=plot.reveal.progress
            b.message('新状态，不应重播图表');fresh=next(w for w in b.findChildren(TokenPlot) if w.isVisible())
            self.assertAlmostEqual(fresh.reveal.progress,progress);b.set_mode('mini');b.size_transition.complete();APP.processEvents()
            self.assertFalse(fresh.reveal.animation.state().value)
        finally:b.close();b.deleteLater();APP.processEvents()
    def test_curve_head_follows_actual_segments(self):
        from chart_reveal import trace_head
        from PySide6.QtCore import QPointF
        points=[QPointF(0,0),QPointF(10,20),QPointF(20,0)]
        self.assertEqual(trace_head(points,.25),QPointF(5,10));self.assertEqual(trace_head(points,.75),QPointF(15,10))

if __name__=='__main__':unittest.main()
