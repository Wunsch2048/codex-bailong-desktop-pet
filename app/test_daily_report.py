import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,sqlite3,tempfile,unittest,time
from contextlib import closing
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from PySide6.QtCore import Qt,QEvent,QPoint,QPointF,QAbstractAnimation
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication,QToolButton,QToolTip,QLabel
from token_calendar import TokenUsageIndex
from token_analytics import model_series,token_analogy,UNKNOWN
from compact_bubble import CompactBubble
from daily_report import DailyReport,ModelRow
from PySide6.QtTest import QTest

APP=QApplication.instance() or QApplication([])

def event(day,hour,kind,payload):
    return dict(timestamp=datetime(2026,10,day,hour).astimezone().isoformat(),type=kind,payload=payload)
def count(day,hour,total,a,b):return event(day,hour,'event_msg',dict(type='token_count',info=dict(total_token_usage=dict(total_tokens=total,input_tokens=a,output_tokens=b))))

class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name);(self.home/'sessions').mkdir();self.path=self.home/'sessions/rollout-test.jsonl'
        self.index=TokenUsageIndex(self.home/'usage.sqlite3',self.home);self.now=datetime(2026,10,18,12).timestamp()
    def tearDown(self):self.tmp.cleanup()
    def write(self,rows,mode='w'):
        with self.path.open(mode,encoding='utf-8') as f:
            for r in rows:f.write(json.dumps(r)+'\n')
    def fixture(self):return [
        event(16,10,'session_meta',dict(id='s')),
        event(16,10,'turn_context',dict(model='model-A')),count(16,10,100,80,20),
        event(17,3,'event_msg',dict(type='task_started',turn_id='t')),
        event(17,3,'event_msg',dict(type='user_message',message='hello')),
        event(17,3,'response_item',dict(type='message',role='user',content=[dict(text='environment context')])),
        event(17,3,'event_msg',dict(type='agent_message',message='public reply')),
        event(17,3,'response_item',dict(type='message',role='assistant',content=[dict(text='public reply\n')])),
        count(17,3,300,240,60),event(17,8,'turn_context',dict(model='model-B')),count(17,8,600,480,120),
        count(18,9,700,560,140)]
    def test_scopes_models_messages_and_hourly_deltas(self):
        self.write(self.fixture());s=self.index.poll(self.now);r=s['report']
        self.assertEqual(s['all_total'],700);self.assertEqual(r['sessions'],1);self.assertEqual(r['active_days'],3)
        self.assertEqual(r['all_total'],700);self.assertEqual(r['favorite_model'],'model-B')
        self.assertEqual(r['messages'],2);self.assertEqual(r['yesterday_total'],500);self.assertEqual(r['peak_hour'],8)
        self.assertEqual(len(r['hours']),24);self.assertEqual(r['hours'][3],200);self.assertEqual(r['hours'][8],300)
        series=model_series(r,'7d');self.assertEqual(series['total'],600)
        self.assertEqual({m['model']:m['total'] for m in series['models']},{'model-A':300,'model-B':300})
        self.assertTrue(all(m['known'] and m['input']+m['output']==m['total'] for m in series['models']))
        self.assertEqual(series['end'],'2026-10-17');self.assertEqual(len(series['bins']),7)
    def test_restart_and_model_change_after_incremental_offset(self):
        self.write(self.fixture()[:3]);self.index.poll(self.now)
        self.write([event(17,8,'turn_context',dict(model='model-B')),count(17,8,400,320,80)],'a')
        r=TokenUsageIndex(self.index.path,self.home).poll(self.now)['report']
        self.assertEqual({x['model']:x['total'] for x in model_series(r,'all')['models']},{'model-A':100,'model-B':300})
        self.assertEqual(self.index.poll(self.now)['report'],r)
    def test_migration_keeps_old_totals_including_deleted_logs(self):
        with closing(sqlite3.connect(self.index.path)) as db,db:
            db.execute('CREATE TABLE files (path TEXT PRIMARY KEY,offset INTEGER,highwater INTEGER)')
            db.execute('CREATE TABLE usage (fingerprint TEXT PRIMARY KEY,stamp REAL,tokens INTEGER)')
            db.execute('INSERT INTO usage VALUES (?,?,?)',('deleted-history',datetime(2026,10,1).timestamp(),50))
        self.write(self.fixture());r=self.index.poll(self.now)['report']
        self.assertEqual(r['all_total'],750);self.assertTrue(r['metadata_incomplete'])
        self.assertEqual(next(m for m in model_series(r,'all')['models'] if m['model']==UNKNOWN)['total'],50)
        with closing(sqlite3.connect(self.index.path)) as db,db:
            text='\n'.join(db.iterdump());self.assertNotIn('public reply',text);self.assertNotIn('environment context',text)
    def test_time_ranges_and_analogy_change_with_actual_totals(self):
        self.write(self.fixture());r=self.index.poll(self.now)['report']
        self.assertEqual(len(model_series(r,'30d')['bins']),30)
        self.assertNotEqual(token_analogy(100000),token_analogy(200000))
        from book_reference import catalog
        size=catalog()['books'][0]['tokens']
        self.assertIn('1.0',token_analogy(size));self.assertIn('2.0',token_analogy(size*2))
    def test_midnight_rollover_summarizes_previous_calendar_day(self):
        self.write(self.fixture());r=self.index.poll(datetime(2026,10,19,0,1).timestamp())['report']
        self.assertEqual(r['day'],'2026-10-18');self.assertEqual(r['yesterday_total'],100)

def sample():
    return dict(report=dict(day='2026-10-17',sessions=185,messages=123,all_total=2200000000,active_days=6,peak_hour=15,favorite_model='gpt-6.1-sol',yesterday_total=156000,
         hours=[0,0,0,12000,0,0,0,0,0,4000,12000,0,16000,12000,10000,58000,8000,8000,0,0,0,0,8000,0],
         daily_models=[dict(day=f'2026-10-{day:02}',model=m,total=value,input=round(value*.8),output=round(value*.2),known=True)
             for day,value in [(12,1200),(13,30000),(14,12000),(15,56000),(16,78000),(17,30000)] for m in ('gpt-6.1-sol','gpt-6-sol')]))

class ReportUiTests(unittest.TestCase):
    def test_daily_cost_scope_and_unknown_do_not_reuse_stale_day(self):
        data=sample();row=dict(id='archived',name='归档项目',path='D:/p',cost=2.,parts=[1.,.2,.8],tokens=1000,pending_tokens=0,models=[],sessions=1,archived=True)
        data['projects']=dict(yesterday=data['report']['day'],ranges={'yesterday':[row],'all':[row]})
        self.r.set_snapshot(data);self.r.open();self.complete()
        self.assertGreater(self.r.daily_cost.width(),200);self.assertEqual(self.r.daily_cost.amount,2.)
        self.assertEqual(self.r.surface.height(),473);self.assertEqual(self.r.scroll.verticalScrollBar().maximum(),0)
        self.r.open_yesterday_cost();self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration());APP.processEvents()
        self.assertEqual(self.r.period,'yesterday');self.assertEqual(self.r.project_view.archive,'all');self.assertEqual(self.r.project_view.list.count(),2)
        self.r.set_page('overview');self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration())
        data['projects']['yesterday']='2026-10-16';self.r.daily_cost.set_data(data['report'],data['projects'])
        self.assertIsNone(self.r.daily_cost.amount)

    def test_explanations_use_local_fixed_canvas_and_return_without_navigation(self):
        from project_cost_ui import ExplanationOverlay
        self.r.open();self.complete()
        info=next(b for b in self.r.scroll.widget().findChildren(QToolButton) if b.text()=='估算说明')
        info.click();APP.processEvents();self.assertFalse(info.isChecked())
        overlay=next(w for w in self.r.scroll.viewport().findChildren(ExplanationOverlay) if w.isVisible())
        self.assertIsNotNone(overlay);self.assertEqual(overlay.geometry(),self.r.scroll.viewport().rect())
        # A locally positioned explanation must paint an opaque theme surface,
        # otherwise the cost list remains readable through its paragraphs.
        from theme_registry import color
        image=overlay.grab().toImage()
        self.assertEqual(image.pixelColor(image.width()-2,image.height()-2).name(),color('#fcfafc'))
        overlay.back.click();APP.processEvents();self.assertEqual(self.r.page,'overview');self.assertFalse(info.isChecked())
        info.click();APP.processEvents();self.assertFalse(info.isChecked())
        overlay=next(w for w in self.r.scroll.viewport().findChildren(ExplanationOverlay) if w.isVisible())
        overlay.back.click();APP.processEvents();self.assertFalse(info.isChecked())
        self.r.set_page('cycle');self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration());APP.processEvents()
        self.r.cycle_view.rules_button.click();APP.processEvents()
        overlay=self.r.cycle_view.explanation
        self.assertEqual(overlay.geometry(),self.r.scroll.viewport().rect());self.assertFalse(self.r.cycle_view.rules_button.isChecked())
        overlay.back.click();APP.processEvents();self.assertEqual(self.r.page,'cycle')

    def test_page_direction_follows_tab_order_without_moving_navigation(self):
        self.r.open();self.complete();nav=self.r.nav_panel;position=nav.pos()
        with patch('settings_controls.motion_enabled',return_value=True):
            for page,direction in [('projects',1),('models',-1),('cycle',1),('overview',-1)]:
                self.r.set_page(page);self.assertEqual(self.r.page_fade.direction,direction)
                self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration());APP.processEvents()
        self.assertIs(self.r.nav_panel,nav);self.assertEqual(nav.pos(),position)

    def test_capsule_and_minimal_hosts_keep_a_readable_report_width(self):
        for mode in ('mini','minimal'):
            self.b.set_mode(mode);self.b.size_transition.complete();APP.processEvents()
            self.r.open();self.complete();self.r.set_page('models')
            self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration());APP.processEvents()
            self.assertGreaterEqual(self.r.surface.width(),268)
            self.assertGreater(self.r.surface.width(),self.b.width())
            self.assertEqual(self.r.content_geometry().bottom()+1,self.b.y()-self.r.GAP)
            control=self.r.period_control
            self.assertLessEqual(control.mapTo(self.r.surface,control.rect().topRight()).x(),self.r.surface.width()-8)
            self.r.dismiss();self.complete()
    def test_period_change_drops_any_outdated_page_snapshot(self):
        self.r.open();self.complete()
        # This test exercises cancellation of an active page transition.
        # Hosted Windows may disable animations globally; control that input
        # instead of assuming the runner's accessibility preference is ours.
        with patch('settings_controls.motion_enabled',return_value=True):self.r.set_page('models')
        self.assertIsNotNone(self.r.page_fade.frame)
        self.r.set_period('7d')
        self.assertIsNone(self.r.page_fade.frame)
        self.assertEqual(len(self.r.plot.series['bins']),7)

    def test_period_change_with_reduced_motion_has_no_outdated_snapshot(self):
        self.r.open();self.complete()
        with patch('settings_controls.motion_enabled',return_value=False):self.r.set_page('models')
        self.assertIsNone(self.r.page_fade.frame)
        self.r.set_period('7d')
        self.assertIsNone(self.r.page_fade.frame)
        self.assertEqual(len(self.r.plot.series['bins']),7)

    def test_page_cache_reuses_views_and_refreshes_data_changed_offscreen(self):
        import copy
        self.r.open();self.complete();overview=self.r.plot
        self.r.set_page('models');models=self.r.plot
        self.r.set_page('overview');self.assertIs(self.r.plot,overview)
        changed=copy.deepcopy(self.r.snapshot);changed['report']['hours'][2]+=999
        changed['report']['daily_models'].append(dict(day='2026-10-17',model='new-model',total=900,input=800,output=100,known=True))
        self.r.set_snapshot(changed);self.r.set_page('models')
        self.assertIs(self.r.plot,models);self.assertTrue(any(row.item['model']=='new-model' for row in self.r.model_rows))
        self.r.set_page('cycle');self.r.set_page('models')
        self.assertTrue(any(row.item['model']=='new-model' for row in self.r.model_rows))
        self.r.set_page('overview');self.assertEqual(self.r.plot.report['hours'][2],999)
        self.assertEqual(len(self.r._body_cache),3)
    def test_cached_model_page_updates_after_data_arrives_while_report_is_closed(self):
        import copy
        self.r.open();self.complete();self.r.set_page('models');plot=self.r.plot
        self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration())
        self.r.dismiss();self.complete()
        changed=copy.deepcopy(self.r.snapshot);changed['report']['daily_models'][0]['total']+=12345
        self.r.set_snapshot(changed);self.r.open();self.complete()
        self.assertEqual(self.r.page,'overview')
        self.assertEqual(self.r.page_buttons['overview'].text(),'日报')
        self.r.set_page('models')
        self.assertIs(self.r.plot,plot)
        self.assertEqual(self.r.plot.series['total'],sum(row['total'] for row in changed['report']['daily_models']))
    def test_new_open_defaults_to_daily_but_explicit_quota_entry_keeps_its_target(self):
        self.r.open(page='cycle');self.complete();self.assertEqual(self.r.page,'cycle')
        self.r.dismiss();self.complete();self.r.open();self.complete()
        self.assertEqual(self.r.page,'overview')
        self.assertEqual(self.r.page_buttons['overview'].text(),'日报')
    def test_project_detail_is_only_retained_within_current_visit(self):
        row=dict(id='one',name='项目',path='D:/one',tokens=1000,cost=.1,parts=[.08,.01,.01],pending_tokens=0,sessions=1,models=[],archived=False)
        data=sample();data['projects']=dict(ranges={'all':[row]})
        self.r.set_snapshot(data);self.r.open();self.complete();self.r.set_page('projects');APP.processEvents()
        view=self.r.project_view;view.select(row);APP.processEvents()
        self.assertEqual(view.selected,'one')
        # Ordinary data updates and temporary child hides must not navigate.
        self.r.set_snapshot(dict(data,checked=123));self.assertEqual(view.selected,'one')
        view.hide();view.show();self.assertEqual(view.selected,'one')
        self.r.set_page('models');self.r.set_page('projects');APP.processEvents()
        self.assertIs(self.r.project_view,view);self.assertIsNone(view.selected)
        self.assertIs(view.stack.currentWidget(),view.list)
        view.select(row);APP.processEvents();self.r.dismiss();self.complete()
        self.r.open(page='projects');self.complete();self.assertIsNone(self.r.project_view.selected)
        self.assertIs(self.r.project_view.stack.currentWidget(),self.r.project_view.list)

    def test_filter_scope_keeps_token_and_search_aligned_with_time_control(self):
        self.r.open();self.complete();self.r.set_page('models');APP.processEvents()
        row=self.r.scope_row;total=self.r.scope_model_total;period=self.r.period_control
        self.assertTrue(total.isVisible());self.assertEqual(total.mapTo(row,total.rect().center()).y(),period.mapTo(row,period.rect().center()).y())
        self.r.set_page('projects');APP.processEvents();search=self.r.scope_project_search
        self.assertTrue(search.isVisible());self.assertEqual(search.mapTo(row,search.rect().center()).y(),period.mapTo(row,period.rect().center()).y())
        self.assertLessEqual(search.mapTo(row,search.rect().bottomRight()).x(),period.mapTo(row,period.rect().topLeft()).x())
        self.assertIs(self.r.project_view.search,search.edit);self.assertEqual(self.r.project_view.list.verticalScrollBar().width(),6)
        self.assertFalse(search.button.grab().isNull())
        self.r.set_page('models');self.r.set_page('projects');APP.processEvents();self.assertIs(self.r.project_view.search,search.edit)
    def test_page_motion_keeps_an_opaque_background_without_text_crossfade(self):
        from PySide6.QtGui import QPixmap,QPainter,QColor
        from PySide6.QtCore import QRect
        from data_page_motion import paint_pages
        first=QPixmap(60,40);first.fill(QColor('red'))
        second=QPixmap(60,40);second.fill(QColor('blue'))
        for direction in (-1,1):
            for progress in (.25,.5,.75):
                mixed=QPixmap(60,40);mixed.fill(Qt.GlobalColor.transparent)
                painter=QPainter(mixed);paint_pages(painter,QRect(0,0,60,40),first,second,progress,direction);painter.end()
                image=mixed.toImage()
                self.assertEqual({image.pixelColor(x,20).name() for x in range(60)},{'#ff0000','#0000ff'})
                self.assertTrue(all(image.pixelColor(x,20).alpha()==255 for x in range(60)))
    def test_cycle_to_overview_measures_complete_body_before_resize(self):
        self.r.open();self.complete()
        for width in (268,420,560):
            self.b.setFixedWidth(width);self.r.sync_geometry();initial=self.r.surface.size()
            for page in ('cycle','overview','models','overview','cycle','overview'):
                self.r.set_page(page)
                self.assertEqual(self.r.surface.size(),initial,(width,page))
                APP.processEvents()
                self.assertEqual(self.r.surface.size(),initial,(width,page))
    def setUp(self):
        self.b=CompactBubble();self.b.move(100,650);self.b.show();APP.processEvents()
        self.r=DailyReport(self.b);self.b.report=self.r;self.r.set_snapshot(sample())
    def tearDown(self):
        self.r.animation.stop();self.r.close();self.b.close();self.b.deleteLater();APP.processEvents()
    def complete(self):self.r.animation.setCurrentTime(self.r.animation.duration());APP.processEvents()
    def test_hidden_until_manual_open_then_animated_above_and_same_width(self):
        self.assertFalse(self.r.isVisible());self.assertFalse(self.r.requested)
        self.r.open();self.r.animation.setCurrentTime(80);middle=self.r.visible_height()
        self.assertEqual(self.r.content_geometry().width(),self.b.width());self.assertEqual(self.r.content_geometry().x(),self.b.x())
        self.assertEqual(self.r.content_geometry().bottom()+1,self.b.y()-6)
        self.assertGreater(middle,1);self.complete();self.assertGreater(self.r.visible_height(),middle)
        self.r.dismiss();self.r.animation.setCurrentTime(130);self.assertTrue(self.r.isVisible());self.complete();self.assertFalse(self.r.isVisible())
    def test_native_reopen_paints_zero_frame_before_opacity_is_restored(self):
        from unittest.mock import patch
        r=self.r;r.open();self.complete();r.dismiss();self.complete();r.setWindowOpacity(.8)
        opacity=r.windowOpacity();observed=[];show=r.show
        def native_show():
            observed.append((r.windowOpacity(),r.fraction,r.surface.isHidden(),r._frame is not None));show()
        with patch('daily_report.QApplication.platformName',return_value='windows'),patch('panel_transition.present_barrier'),patch.object(r,'show',side_effect=native_show):r.open()
        self.assertEqual(observed,[(0.,0.,True,True)]);self.assertAlmostEqual(r.windowOpacity(),opacity)
    def test_native_reopen_failure_does_not_leave_report_invisible(self):
        from unittest.mock import patch
        r=self.r;r.setWindowOpacity(.7);opacity=r.windowOpacity()
        with patch('daily_report.QApplication.platformName',return_value='windows'),patch.object(r,'_prepare_frame',side_effect=RuntimeError('capture failed')):
            with self.assertRaises(RuntimeError):r.open()
        self.assertAlmostEqual(r.windowOpacity(),opacity)
    def test_overview_has_no_range_filter_model_page_filters_totals(self):
        self.r.open();self.complete()
        self.assertFalse([b for b in self.r.findChildren(QToolButton) if b.objectName().startswith('report_range_') and not b.isHidden()])
        self.r.set_page('models');APP.processEvents()
        nav=self.r.period_control.parentWidget()
        for widget in [*self.r.page_buttons.values(),self.r.period_control]:
            # Time controls now live on the scope row below the tab row.
            host=self.r.nav_panel
            from PySide6.QtCore import QRect
            self.assertTrue(host.rect().contains(QRect(widget.mapTo(host,widget.rect().topLeft()),widget.size())),widget.objectName())
        self.assertEqual(len([b for b in self.r.findChildren(QToolButton) if b.objectName().startswith('report_range_') and not b.isHidden()]),3)
        model=self.r.findChildren(ModelRow)[-1];model.click();self.assertEqual(self.r.selected_model,model.item['model'])
        self.r.set_period('7d');self.assertEqual(len(self.r.plot.series['bins']),7);self.r.set_period('30d');self.assertEqual(len(self.r.plot.series['bins']),30)
    def test_cycle_page_shows_local_usage_and_gated_estimate(self):
        self.r.open();self.complete()
        self.r.set_page('cycle');APP.processEvents()
        self.assertEqual(self.r.page_buttons['cycle'].text(),'额度')
        self.assertEqual(self.r.layout.itemAt(0).widget().findChildren(QLabel)[0].text(),'数据面板')
        self.assertEqual(self.r.day_label.text(),'')
        self.assertTrue(self.r.period_control.isHidden())
        self.assertEqual(self.r.cycle_view.estimate.text(),'—')
        item=dict(id='test',start=1760000000,end=1760050000,through=1760050000,reset_at=1760600000,
            kind='natural',closed=False,remaining=75,used=150000,estimated_total=600000,
            per_percent=6000,complete=True,fresh=True,records=3,drop=25,comparison_reason='尚无可比历史',change=None)
        data=sample();data['quota_history']=dict(cycles=[item])
        self.r.set_snapshot(data)
        self.assertEqual(self.r.cycle_view.used.text(),'150.0K')
        self.assertEqual(self.r.cycle_view.estimate.text(),'600.0K')
        self.assertIn('75%',self.r.cycle_view.detail.text())
        APP.processEvents()
        self.assertEqual(self.r.scroll.verticalScrollBar().maximum(),0)
        self.assertTrue(self.r.cycle_view.note.isHidden() or self.r.cycle_view.rules.isHidden())
        self.assertTrue(self.r.cycle_view.rules_button.isVisible())
        data=dict(data,quota_history=dict(cycles=[dict(item,estimated_total=None,complete=False)]))
        self.r.set_snapshot(data)
        self.assertEqual(self.r.cycle_view.estimate.text(),'—')
        self.assertIn('受限',self.r.cycle_view.quality.text())
    def test_overview_fits_and_model_overflow_remains_scrollable_without_bar(self):
        self.r.open();self.complete();APP.processEvents()
        area=self.r.scroll
        self.assertEqual(area.verticalScrollBar().maximum(),0)
        self.assertFalse(area.verticalScrollBar().isVisible())
        self.assertTrue(area.viewport().rect().contains(self.r.note_label.mapTo(area.viewport(),self.r.note_label.rect().bottomRight())))
        height=self.r.height()
        self.r.set_page('models');APP.processEvents()
        self.assertEqual(self.r.height(),height)
        self.assertFalse(self.r.scroll.verticalScrollBar().isVisible())
        data=sample()
        data['report']['daily_models']=[dict(day='2026-10-17',model='model-'+str(i),total=1000,input=800,output=200,known=True) for i in range(12)]
        self.r.set_snapshot(data);QTest.qWait(20)
        self.assertGreater(self.r.scroll.verticalScrollBar().maximum(),0)
        self.assertFalse(self.r.scroll.verticalScrollBar().isVisible())
        bar=self.r.scroll.verticalScrollBar();bar.setValue(bar.maximum());self.assertGreater(bar.value(),0)
        self.r.set_page('overview');APP.processEvents()
        self.assertEqual(self.r.scroll.verticalScrollBar().maximum(),0)
        self.assertFalse(self.r.scroll.verticalScrollBar().isVisible())
    def test_page_changes_keep_chrome_and_only_fade_body(self):
        self.r.open();self.complete();APP.processEvents()
        title=self.r.header_title;nav=self.r.page_buttons['models'].parentWidget()
        header_geometry=title.parentWidget().geometry();nav_geometry=nav.geometry()
        with patch('settings_controls.motion_enabled',return_value=True):
            for page in ('models','cycle','overview'):
                self.r.set_page(page);APP.processEvents()
                self.assertIs(self.r.header_title,title)
                self.assertIs(self.r.page_buttons['models'].parentWidget(),nav)
                self.assertEqual(title.parentWidget().geometry(),header_geometry)
                self.assertEqual(nav.geometry(),nav_geometry)
                self.assertTrue(self.r.page_fade.geometry().top()>=nav.geometry().bottom())
            self.r.page_fade.animation.setCurrentTime(self.r.page_fade.animation.duration())
            self.assertFalse(self.r.page_fade.isVisible())
    def test_native_tooltips_suppressed_but_inline_hover_still_works(self):
        self.b.redraw();APP.processEvents();button=self.b.findChild(QToolButton,'bubble_report')
        with patch.object(QToolTip,'showText') as show:
            APP.sendEvent(button,QHelpEvent(QEvent.Type.ToolTip,QPoint(3,3),button.mapToGlobal(QPoint(3,3))))
            show.assert_not_called()
        self.assertFalse(QToolTip.isVisible())
        from quota_summary import QuotaSummary
        quota=next(w for w in self.b.findChildren(QuotaSummary) if w.isVisible());point=quota.row_rect(0).center().toPoint()
        with patch.object(QToolTip,'showText') as show:
            APP.sendEvent(quota,QHelpEvent(QEvent.Type.ToolTip,point,quota.mapToGlobal(point)))
            show.assert_not_called()
        self.r.open();self.complete();self.r.plot.grab();values=[];self.r.plot.hoverText.connect(values.append)
        self.assertEqual(len(self.r.plot.hits),24)
        self.assertEqual(self.r.report['hours'],sample()['report']['hours'])
    def test_refresh_never_opens_report_and_resize_remains_aligned(self):
        self.r.set_snapshot(sample());self.assertFalse(self.r.isVisible())
        self.r.open();self.complete();self.b.toggle_details();self.b.size_transition.complete();APP.processEvents()
        self.assertEqual(self.r.content_geometry().width(),self.b.width());self.assertEqual(self.r.content_geometry().x(),self.b.x())
        self.b.hide();self.assertFalse(self.r.isVisible());self.assertFalse(self.r.requested)
    def test_large_y_axis_values_have_full_font_height_and_width(self):
        data=sample();data['report']['hours'][15]=17270000
        self.r.set_snapshot(data);self.r.open();self.complete();plot=self.r.plot
        plot.grab();chart=plot.chart_rect();fm=plot._axis_metrics
        self.assertIn('17.27M',plot._axis_labels)
        self.assertEqual(chart.left(),3)  # Daily line plot intentionally has no Y labels.
        plot.mode='bars';plot.series={'bins':[{'total':17270000,'values':{}}]};plot._measure_axes();chart=plot.chart_rect();fm=plot._axis_metrics
        for text in plot._axis_labels:
            self.assertGreaterEqual(chart.left()-6-fm.horizontalAdvance(text),1)
        self.assertGreaterEqual(chart.top()-fm.height()/2,1)
        self.assertLess(chart.bottom()+fm.height()/2,plot.height())

class BackgroundTests(unittest.TestCase):
    def test_index_rebuild_does_not_block_status_monitor_and_cancels_on_exit(self):
        from enhanced import ActivityThread
        with tempfile.TemporaryDirectory() as folder,patch('enhanced.STATE_DIR',Path(folder)):
            worker=ActivityThread(home=folder);events=[];worker.event.connect(events.append)
            def slow_index(now=None,stop=lambda:False):
                deadline=time.monotonic()+5
                while not stop() and time.monotonic()<deadline:time.sleep(.01)
                return {}
            with patch.object(worker.token_index,'poll',side_effect=slow_index),patch.object(worker.tail,'poll',return_value=[dict(kind='status',state='working')]):
                worker.start()
                try:
                    deadline=time.monotonic()+2.6
                    while len([e for e in events if e['kind']=='status'])<2 and time.monotonic()<deadline:
                        APP.processEvents();time.sleep(.03)  # Give Python QThread workers the GIL, as app.exec() does.
                    self.assertGreaterEqual(len([e for e in events if e['kind']=='status']),2)
                    self.assertTrue(worker.token_reader.is_alive())
                finally:worker.stop.set();self.assertTrue(worker.wait(2000))
                self.assertFalse(worker.token_reader.is_alive())

if __name__=='__main__':unittest.main()
