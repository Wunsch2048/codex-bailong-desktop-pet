"""Cold/reused tool surfaces are seeded before native visibility, never at idle."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QRect,QRectF,QPoint,Qt,QEvent
from PySide6.QtGui import QPixmap,QColor
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest
from hover_hints import HintBubble
from panel_transition import NativeLanding
from linked_report_motion import LinkedReportMotion
from quota_summary import QuotaSummary

APP=QApplication.instance() or QApplication([])

class ColdHoverTests(unittest.TestCase):
    def setUp(self):self.owner=QWidget();self.owner.show();APP.processEvents();self.widgets=[]
    def tearDown(self):
        for w in self.widgets:w.close();w.deleteLater()
        self.owner.close();self.owner.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
    def test_hint_cold_and_reused_show_seed_transparent_pixels_before_show(self):
        popup=HintBubble();self.widgets.append(popup);events=[];show=popup.show
        def publish(w,image):events.append(('publish',w.isVisible(),image));return True
        def shown():events.append(('show',popup.native_seeded,None));show()
        with patch('hover_hints.QApplication.platformName',return_value='windows'),patch('native_landing.publish',side_effect=publish),patch.object(popup,'show',side_effect=shown):
            for title in ('刷新','详情'):
                popup.present(title,'',QRect(100,200,24,24),self.owner.screen(),owner=self.owner,topmost=False)
                self.assertEqual(events[-2:], [('publish',False,None),('show',True,None)])
                self.assertEqual(popup.level,0.);popup.dismiss(True)
    def test_visible_hint_data_update_does_not_clear_native_store_or_drop_alpha(self):
        popup=HintBubble();self.widgets.append(popup)
        popup.present('额度 80%','等待刷新',QRect(100,200,24,24),self.owner.screen(),owner=self.owner,topmost=False,initial_level=1.)
        with patch('hover_hints.QApplication.platformName',return_value='windows'),patch('native_landing.publish') as publish:
            popup.present('额度 79%','等待刷新',QRect(100,200,24,24),self.owner.screen(),owner=self.owner,topmost=False)
            self.assertEqual(popup.level,1.);publish.assert_not_called();self.assertTrue(popup.isVisible())
    def test_chart_seeds_transparent_then_paints_complete_amount_and_cost_columns(self):
        from rate_chart import ChartBubble
        popup=ChartBubble();self.widgets.append(popup)
        record=dict(label='00:00–01:00',rows=[('Token 用量','13.70M Token',None),('gpt-6.1-sol','11.08M','#ffcc00')],
                    model_count=1,costs={'Token 用量':'$13.47','gpt-6.1-sol':'$12.77'})
        with patch('hover_hints.QApplication.platformName',return_value='windows'),patch('native_landing.publish',return_value=True) as publish:
            popup.inspect(record,QRect(120,250,8,20),self.owner)
            self.assertIsNone(publish.call_args.args[1])
            popup.animation.setCurrentTime(popup.animation.duration())
        frame=popup.grab().toImage()
        self.assertEqual(frame.width(),254)
        self.assertIn('$12.77',popup.accessibleDescription())
        for top,bottom in ((31,51),(62,82),(88,108)):
            self.assertGreater(len({frame.pixel(x,y) for x in range(140,240) for y in range(top,bottom)}),12)
    def test_windows_context_menu_uses_platform_menu_class(self):
        from PySide6.QtWidgets import QMenu
        from popup_motion import ContextMenu
        with patch('popup_motion.QApplication.platformName',return_value='windows'):
            menu=ContextMenu(self.owner)
            self.widgets.append(menu)
            self.assertIs(type(menu),QMenu)

    def test_short_tray_hint_stays_still_through_settle_and_data_refresh(self):
        popup=HintBubble();self.widgets.append(popup)
        anchor=QRect(100,700,24,24)
        with patch('hover_hints.motion_enabled',return_value=True),patch('hover_hints.play_animation',side_effect=lambda anim:anim.start()):
            popup.present('周额度 58%','下次重置 11/26',anchor,self.owner.screen())
            self.assertLess(popup.height(),80)
            bounds=[]
            for ms in (228,248,276,308):
                popup.animation.setCurrentTime(ms)
                clock=popup.animation.currentTime()
                bounds.append(popup.motion_bounds())
                popup.present('周额度 57%','下次重置 11/26',anchor,self.owner.screen())
                self.assertEqual(popup.animation.currentTime(),clock)
            self.assertTrue(all(rect==bounds[0] for rect in bounds))

    def test_popup_follows_center_and_off_center_triggers_continuously(self):
        from PySide6.QtCore import QPointF
        from popup_motion import AnchoredPopupEffect
        popup=HintBubble();self.widgets.append(popup)
        popup.resize(202,102);popup.level=42/335
        menu=AnchoredPopupEffect(self.owner);menu.level=popup.level
        for x in (41.,100.,101.,102.,161.):
            popup.motion_origin=QPointF(x,1.)
            menu.pivot=popup.motion_origin
            ratio=(x-1.)/200.
            hover=popup.motion_bounds()
            self.assertAlmostEqual((x-hover.left())/hover.width(),ratio,delta=.04)
            self.assertAlmostEqual(menu.reveal_rect(QRectF(1,1,200,100),menu.sample()).left(),hover.left())
        popup.motion_side=True;popup.motion_origin=QPointF(1.,51.)
        self.assertAlmostEqual(popup.motion_bounds().center().y(),51.)

    def test_hover_reveal_keeps_text_scale_and_softens_exit(self):
        from PySide6.QtGui import QPainter
        popup=HintBubble();self.widgets.append(popup)
        with patch('hover_hints.motion_enabled',return_value=True),patch('hover_hints.play_animation',side_effect=lambda animation:animation.start()):
            popup.present('会话实时速率','等待会话输出和有效采样',QRect(110,10,85,18),self.owner.screen())
            popup.resize(popup.width(),110)
            geometry=popup.geometry()
            popup.animation.setCurrentTime(16)
            first=popup.motion_bounds()
            popup.animation.setCurrentTime(42)
            second=popup.motion_bounds()
            self.assertGreater(second.height(),first.height())
            self.assertGreater(abs(second.top()-first.top()),2.)
            popup.animation.setCurrentTime(115)
            self.assertGreater(popup.motion_bounds().height(),second.height())
            self.assertLess(popup.motion_bounds().height(),popup.height())
            frame=QPixmap(popup.size());painter=QPainter(frame)
            try:
                self.assertTrue(popup.apply_motion(painter))
                self.assertEqual((painter.transform().m11(),painter.transform().m22()),(1.,1.))
                self.assertEqual(painter.transform().dx(),0.)
            finally:painter.end()
            samples=[];frames=[]
            for time in (228,248,276,308):
                popup.animation.setCurrentTime(time);samples.append(popup.motion_bounds())
                frames.append(popup.grab().toImage())
                self.assertEqual(popup.geometry(),geometry)
                self.assertTrue(QRectF(popup.rect()).contains(samples[-1]))
            self.assertNotEqual(frames[0],frames[1])
            interior=QRect(8,8,frames[0].width()-16,frames[0].height()-16)
            self.assertTrue(all(image.copy(interior)==frames[0].copy(interior) for image in frames[1:]))
            settled,overshoot,rebound,rest=samples
            self.assertEqual(settled.height(),overshoot.height())
            self.assertLess(overshoot.top(),settled.top())
            self.assertGreater(rebound.top(),settled.top())
            self.assertEqual(rest,settled)
            popup.animation.setCurrentTime(popup.animation.duration())
            popup.dismiss()
            self.assertIsNotNone(popup._exit_frames)
            self.assertNotEqual(popup._exit_frames[0].toImage(),popup._exit_frames[1].toImage())
            popup.animation.setCurrentTime(45)
            self.assertEqual(popup.geometry(),geometry);self.assertGreater(popup.level,0.)
            before=popup.motion_bounds()
            popup._animate(1.)
            self.assertEqual(before,popup.motion_bounds())
            popup.animation.setCurrentTime(popup.animation.duration())
            self.assertIsNone(popup._exit_frames)
            self.assertTrue(popup.isVisible());self.assertEqual(popup.level,1.)

    def test_detail_motion_faces_trigger_when_avoidance_moves_tip_to_the_side(self):
        from public_status import bubble_position
        popup=HintBubble();self.widgets.append(popup)
        area=self.owner.screen().availableGeometry()
        card=QRect(area.left()+8,area.top()+8,220,225)
        anchor=QRect(card.left()+39,card.top()+54,37,28)
        target=bubble_position(card,anchor,(200,110),area)
        self.assertTrue(area.contains(target));self.assertFalse(target.intersects(card))
        popup.present('额度','',anchor,self.owner.screen(),owner=self.owner,geometry=target)
        self.assertTrue(popup.motion_side);self.assertEqual(popup.motion_origin.x(),1.)
        self.assertEqual(popup.motion_origin.y(),anchor.center().y()-target.y())

    def test_guard_submits_target_bitmap_before_cold_show_and_again_after(self):
        guard=NativeLanding(self.owner);self.widgets.append(guard);image=QPixmap(60,40);image.fill(QColor('red'));events=[]
        def publish(w,pixels):events.append((w.isVisible(),pixels is image));return True
        with patch('native_landing.publish',side_effect=publish):guard.present(image,QRect(10,10,60,40))
        self.assertEqual(events,[(False,True),(True,True)]);self.assertTrue(guard.pre_show_published);self.assertTrue(guard.native_published)
    def test_open_report_parks_guards_hidden_instead_of_showing_empty_native_windows(self):
        report=QWidget();self.widgets.append(report);report.bubble=self.owner;report.requested=True;report.show();motion=LinkedReportMotion(report)
        for guard in (motion.landing,motion.shield):
            with patch.object(guard,'prepare',wraps=guard.prepare) as prepare:
                motion.park(guard);prepare.assert_not_called();self.assertFalse(guard.isVisible());self.assertIsNone(guard.image)
    def test_quota_hover_recovers_after_layout_show_without_another_mouse_move(self):
        card=QuotaSummary([dict(name='一周',remaining=80)]);self.widgets.append(card);card.resize(121,102);card.show();APP.processEvents()
        point=card.mapToGlobal(card.row_rect(0).center().toPoint())
        with patch.object(card,'underMouse',return_value=True),patch('quota_summary.QCursor.pos',return_value=point):
            card._sync_hover();self.assertEqual(card.active,0);card.hide();self.assertIsNone(card.active)
            card.show();APP.processEvents();self.assertEqual(card.active,0)
    def test_token_background_scan_updates_open_inspection_without_hiding(self):
        from datetime import datetime
        from token_charts import TokenPlot
        now=datetime(2026,10,2,13).timestamp();data=dict(today='2026-10-02',month='2026-10',days={'2026-10-02':100},hours=list(range(24)))
        plot=TokenPlot(data,'day',now=now);self.widgets.append(plot);plot.resize(160,80);plot.show();APP.processEvents();plot.reveal.animation.stop();plot.reveal.progress=1.;plot.grab()
        plot.inspect_at(plot.hits[3][0].center());plot.show_inspection();self.assertTrue(plot._popup.isVisible());before=plot._popup.record['amount']
        new=dict(data,hours=[n+100 for n in data['hours']])
        with patch.object(plot._popup,'hide',wraps=plot._popup.hide) as hide:plot.set_data(new,'day',now);hide.assert_not_called()
        self.assertTrue(plot._popup.isVisible());self.assertNotEqual(plot._popup.record['amount'],before)
        plot.set_data(new,'7d',now);self.assertFalse(plot._popup.isVisible())
    def test_idle_pointer_keeps_inspection_after_leave_and_resize(self):
        from datetime import datetime
        from token_charts import TokenPlot
        now=datetime(2026,10,2,13).timestamp()
        plot=TokenPlot(dict(today='2026-10-02',hours=list(range(24))),'day',now=now);self.widgets.append(plot)
        plot.resize(160,80);plot.show();APP.processEvents();plot.reveal.animation.stop();plot.reveal.progress=1.;plot.ensure_layers()
        position=plot.hits[3][0].center()
        plot.inspect_at(position);plot.show_inspection()
        with patch('rate_chart.QCursor.pos',return_value=plot.mapToGlobal(position.toPoint())):
            APP.sendEvent(plot,QEvent(QEvent.Type.Leave));plot.check_inspection_pointer()
            self.assertTrue(plot._popup.isVisible())
            plot.resize(162,80);plot.check_inspection_pointer()
            self.assertTrue(plot._popup.isVisible());self.assertEqual(plot._inspection,3)
        with patch('rate_chart.QCursor.pos',return_value=plot.mapToGlobal(QPoint(-5,0))):
            plot.check_inspection_pointer()
            self.assertEqual(plot._inspection,-1)
            plot._popup.animation.setCurrentTime(plot._popup.animation.duration());self.assertFalse(plot._popup.isVisible())

    def test_card_rebuild_and_status_height_keep_the_open_chart_popup(self):
        from datetime import date,timedelta
        from compact_bubble import CompactBubble
        b=CompactBubble();self.widgets.append(b);b.move(220,210);b.show();APP.processEvents()
        b.token_snapshot={'history_days':{str(date.today()-timedelta(days=1)):100,str(date.today()):200}}
        b.redraw();APP.processEvents()
        plot=b.status_hover_plot()
        plot.reveal.animation.stop();plot.reveal.progress=1.;plot.ensure_layers()
        hit=plot._combo_records[-1]['rect'].center();point=plot.mapToGlobal(hit.toPoint())
        plot.inspect_at(hit);plot.show_inspection();popup=plot._popup
        popup.animation.setCurrentTime(popup.animation.duration())
        self.assertTrue(popup.isVisible())
        with patch('rate_chart.QCursor.pos',return_value=point),patch.object(popup,'hide',wraps=popup.hide) as hide:
            b.token_snapshot={'history_days':{str(date.today()-timedelta(days=1)):100,str(date.today()):300}}
            b.redraw();APP.processEvents()
            self.assertIs(b.status_hover_plot(),plot);self.assertTrue(popup.isVisible())
            self.assertIn('300',popup.record['amount'])
            b.roster.observe(dict(session='first',state='working'));b.refresh_status()
            b.roster.observe(dict(session='second',state='working'));b.refresh_status()
            t=b.size_transition;self.assertTrue(t.running)
            t.animation.setCurrentTime(t.animation.duration()//2)
            self.assertTrue(popup.isVisible())
            t.complete();APP.processEvents()
            self.assertTrue(popup.isVisible());hide.assert_not_called()
        b.select_dashboard('reset')
        self.assertFalse(popup.isVisible())

    def test_details_can_stay_adjacent_to_controls_inside_tall_card(self):
        from public_status import bubble_position
        area=QRect(0,0,800,600)
        card=QRect(70,30,290,510)
        for anchor in (QRect(95,474,121,22),QRect(137,262,35,19),QRect(137,36,35,19)):
            with self.subTest(anchor=anchor):
                target=bubble_position(card,anchor,(268,110),area,near_anchor=True)
                self.assertTrue(area.contains(target));self.assertFalse(target.intersects(anchor))
                between=(anchor.left()-target.right(),target.left()-anchor.right(),
                         anchor.top()-target.bottom(),target.top()-anchor.bottom())
                self.assertEqual(max(between),9)

    def test_daily_and_model_background_refresh_keep_hover_while_filter_change_clears_it(self):
        import copy
        import test_daily_report as fixture
        from daily_report import ReportPlot
        from token_analytics import model_series
        for mode in ('line','bars'):
            data=fixture.sample()['report'];series=model_series(data,'7d') if mode=='bars' else None
            plot=ReportPlot(data,mode=mode,series=series);self.widgets.append(plot);plot.resize(246,94);plot.show();APP.processEvents();plot.reveal.animation.stop();plot.reveal.progress=1.;plot.grab()
            plot.inspect_at(plot._combo_records[0]['rect'].center());plot.show_inspection();self.assertTrue(plot._popup.isVisible())
            new=copy.deepcopy(data);new['hours'][0]+=100;new_series=model_series(new,'7d') if mode=='bars' else None
            with patch.object(plot._popup,'hide',wraps=plot._popup.hide) as hide:plot.set_data(new,new_series);hide.assert_not_called()
            self.assertTrue(plot._popup.isVisible())
            plot._popup.animation.setCurrentTime(plot._popup.animation.duration());self.assertEqual(plot._popup.level,1.)
            plot.set_data(new,new_series,selected='different-model');self.assertFalse(plot._popup.isVisible())
            plot.close()

