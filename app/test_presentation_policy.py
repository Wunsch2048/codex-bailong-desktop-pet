"""Navigation, presentation policy and movement-clock boundary regressions."""
import os,queue,threading,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from PySide6.QtCore import QRect,QAbstractAnimation
from PySide6.QtWidgets import QApplication,QWidget
from desktop_core import normalized
from settings_controls import set_motion_mode,motion_enabled,settle_motion

APP=QApplication.instance() or QApplication([])

class PresentationPolicyTests(unittest.TestCase):
    def tearDown(self):
        set_motion_mode('quality')
        for widget in APP.topLevelWidgets():widget.close()
        APP.processEvents()
    def test_performance_disables_chart_and_glyph_timers_but_keeps_current_state(self):
        from chart_reveal import ChartReveal
        from status_indicator import StatusIndicator
        from refresh_indicator import RefreshButton
        self.assertEqual(normalized({'ui_animation_mode':'invalid'})['ui_animation_mode'],'quality')
        set_motion_mode('performance');self.assertFalse(motion_enabled())
        host=QWidget();host.show();chart=ChartReveal(host);chart.prepare();chart.start()
        self.assertEqual(chart.progress,1.);self.assertFalse(chart.pending);self.assertNotEqual(chart.animation.state(),QAbstractAnimation.State.Running)
        glyph=StatusIndicator();glyph.show();glyph.state='working';glyph._sync()
        refresh=RefreshButton();refresh.show();refresh.set_busy(True);APP.processEvents()
        self.assertFalse(glyph.timer.isActive());self.assertFalse(refresh.timer.isActive())
        self.assertEqual(glyph.visual(),'busy');self.assertTrue(refresh.busy)
        with patch('settings_controls._system_motion_enabled',return_value=True):
            set_motion_mode('quality');settle_motion();self.assertTrue(glyph.timer.isActive());self.assertTrue(refresh.timer.isActive())
            set_motion_mode('performance');settle_motion();self.assertFalse(glyph.timer.isActive());self.assertFalse(refresh.timer.isActive())
    def test_fresh_project_visit_resets_scroll_back_within_visit_preserves_it(self):
        from project_cost_ui import ProjectCosts
        rows=[dict(id=str(i),name='项目'+str(i),path='D:/project/'+str(i),cost=1.,parts=[.5,.1,.4],tokens=1000,pending_tokens=0,models=[],sessions=1,archived=False) for i in range(24)]
        view=ProjectCosts();view.resize(260,350);view.set_data(dict(ranges={'all':rows}),'all');view.show();APP.processEvents()
        bar=view.list.verticalScrollBar();self.assertGreater(bar.maximum(),0);bar.setValue(bar.maximum()//2);position=bar.value()
        view.select(rows[8]);view.select(None);APP.processEvents();self.assertEqual(bar.value(),position)
        view.select(rows[8]);view.reset_navigation();APP.processEvents()
        self.assertIsNone(view.selected);self.assertEqual(bar.value(),0);self.assertEqual(view.details.verticalScrollBar().value(),0)
        self.assertIs(view.stack.currentWidget(),view.list)
    def test_segment_handoff_carries_small_overshoot_but_not_a_long_decoder_stall(self):
        from stream_player import StreamPlayer
        def segment():
            ready=threading.Event();ready.set()
            return SimpleNamespace(ready=ready,error=None,first=(bytes([255]*16),.042,1),path=Path('synthetic.webp'),size=2,end=3,start=1,stop=threading.Event(),frames=queue.Queue(),thread=None)
        player=StreamPlayer();player.ended=True;player.playhead=1.013;player.next_time=1.
        with patch('stream_player.time.perf_counter',return_value=10.):player.adopt(segment(),continuous=True)
        self.assertAlmostEqual(player.playhead,.013);self.assertAlmostEqual(player.deadline,10.029)
        player.ended=True;player.playhead=5.;player.next_time=1.;player.adopt(segment(),continuous=True)
        self.assertLess(player.playhead,player.next_time);player.close()
    def test_small_screen_reserves_space_via_host_motion_and_cancel_does_not_reopen(self):
        from compact_bubble import CompactBubble
        from daily_report import DailyReport
        bubble=CompactBubble();bubble.expanded=False;bubble.redraw();bubble.move(100,80);bubble.show()
        report=DailyReport(bubble);bubble.report=report
        original=QRect(bubble.geometry())
        target=QRect(original);target.moveTop(410)
        owner=SimpleNamespace(enhanced_ready=True,stop_walk=Mock(),position_bubble=lambda:bubble.move((target if report.requested else original).topLeft()))
        def geometry(size=None):return QRect(target if report.requested else original)
        with patch.object(bubble,'owner_pet',return_value=owner),patch.object(bubble,'content_geometry',side_effect=geometry),patch('settings_controls.motion_enabled',return_value=True):
            report.open();self.assertFalse(report.isVisible());self.assertTrue(bubble.size_transition.running)
            bubble.size_transition.animation.setCurrentTime(bubble.size_transition.animation.duration()//2)
            current=bubble.size_transition.visible_geometry()
            self.assertGreater(current.top(),original.top());self.assertLess(current.top(),target.top())
            report.dismiss();bubble.size_transition.animation.setCurrentTime(bubble.size_transition.animation.duration())
            if bubble.size_transition.running:bubble.size_transition.animation.setCurrentTime(bubble.size_transition.animation.duration())
            self.assertFalse(report.requested);self.assertFalse(report.isVisible());self.assertEqual(bubble.geometry(),original)
            with patch.object(report,'rebuild',wraps=report.rebuild) as rebuild:
                report.open(page='models');prepared=rebuild.call_count
                bubble.size_transition.animation.setCurrentTime(bubble.size_transition.animation.duration())
                self.assertEqual(rebuild.call_count,prepared)
            self.assertTrue(report.isVisible());self.assertIsNone(report._host_open_page)
            report.animation.setCurrentTime(report.animation.duration());self.assertEqual(report.page,'models')
            self.assertGreaterEqual(bubble.y(),410);self.assertFalse(bubble.size_transition.running)
            report.animation.stop();report.hide();bubble.move(original.topLeft())
            report.open();report.dismiss();report.open(page='cycle')
            bubble.size_transition.animation.setCurrentTime(bubble.size_transition.animation.duration())
            self.assertTrue(report.requested);self.assertTrue(report.isVisible());self.assertEqual(report.page,'cycle')
            report.hide();bubble.move(original.topLeft());report.open();bubble.hide()
            self.assertIsNone(report._host_open_page);self.assertFalse(report.requested)
    def test_performance_card_and_report_finish_their_handoffs_without_running_motion(self):
        from compact_bubble import CompactBubble
        from daily_report import DailyReport
        from island_widgets import QuotaSatellite
        set_motion_mode('performance')
        bubble=CompactBubble();bubble.show();APP.processEvents();bubble.toggle_details();APP.processEvents()
        self.assertFalse(bubble.size_transition.running);self.assertFalse(bubble.size_transition.preparing)
        self.assertTrue(bubble.content.isVisible())
        from test_daily_report import sample
        report=DailyReport(bubble);bubble.report=report;report.set_snapshot(sample());report.open();APP.processEvents()
        self.assertTrue(report.isVisible());self.assertFalse(report._animating);self.assertTrue(report.surface.isVisible())
        self.assertEqual(report.plot.reveal.progress,1.)
        report.set_page('models');self.assertFalse(report.page_fade.isVisible())
        quota=QuotaSatellite([dict(remaining=60,limitId='primary')],'剩余');quota.show();quota.begin_reveal();quota.start_reveal()
        self.assertEqual(quota.reveal.progress,1.);self.assertNotEqual(quota.reveal.animation.state(),QAbstractAnimation.State.Running)

if __name__=='__main__':unittest.main()
