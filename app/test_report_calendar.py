"""Calendar navigation uses real report surfaces and bounded data scopes."""
import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QRect
import test_daily_report as fixture
from test_quota_compare_ui import row
from report_dates import date_bounds, quota_days, range_key

APP=fixture.APP
sample=fixture.sample


class ReportCalendarTests(unittest.TestCase):
    setUp=fixture.ReportUiTests.setUp
    tearDown=fixture.ReportUiTests.tearDown

    def open_page(self,page,data):
        r=self.r;r.set_snapshot(data);r.open()
        fixture.ReportUiTests.complete(self);r.set_page(page)
        r.page_fade.clear();APP.processEvents()
        return r

    def test_calendar_background_keeps_surface_and_grid_theme_colors(self):
        from PySide6.QtCore import QPoint
        from theme_registry import color, current, palette
        from theme_runtime import apply_theme
        previous=current();colors=dict(palette())
        r=self.open_page('models',sample());r.set_period('7d');r.model_date_entry.click()
        r.page_fade.clear();c=r.calendar;APP.processEvents()
        try:
            for theme in ('starfield','division','bailong'):
                apply_theme(theme,{},roots=(r,));APP.processEvents()
                frame=c.grab().toImage();ratio=frame.devicePixelRatio()
                def at(point):
                    return frame.pixelColor(round(point.x()*ratio),round(point.y()*ratio)).name()
                grid=c.grid.mapTo(c,QPoint(2,c.grid.height()//2))
                self.assertEqual(at(grid),color('#f5f0f8'),theme)
                self.assertEqual(at(QPoint(6,grid.y())),palette()['surface'],theme)
        finally:apply_theme(previous,colors,roots=(r,))

    def test_selected_model_controls_real_calendar_marks_and_scope(self):
        data=sample();data['report'].update(day='2026-11-16',daily_models=[
            dict(day='2026-10-13',model='a',total=41,input=40,output=1,known=True),
            dict(day='2026-11-10',model='b',total=100,input=80,output=20,known=True)])
        r=self.open_page('models',data);r.select_model('a');r.set_period('30d')
        self.assertEqual(r.selected_model,'a')
        r.model_date_entry.click();c=r.calendar
        self.assertIsNotNone(c);r.page_fade.clear();APP.processEvents()
        self.assertFalse(c.buttons[date(2026,11,1)].isEnabled())
        self.assertTrue(c.buttons[date(2026,10,1)].marker)
        c.buttons[date(2026,10,1)].click()
        c.apply.click();self.assertIsNone(r.calendar)
        self.assertEqual((r.plot.series['start'],r.plot.series['end'],r.plot.selected),('2026-10-01','2026-10-31','a'))
        self.assertEqual(r.plot.series['total'],41)
        r.set_period('7d');r.model_date_entry.click();c=r.calendar
        self.assertFalse(any(cell.marker for cell in c.buttons.values()))
        c.jump.click()
        self.assertTrue(c.buttons[date(2026,10,13)].marker)
        self.assertEqual(c.selected,date(2026,10,12))

    def test_quota_reset_day_keeps_both_cycles_and_calendar_width_morph(self):
        stamp=lambda y,m,d,h=0:datetime(y,m,d,h).timestamp()
        shared=stamp(2026,11,11,23)
        current=row(id='new',start=shared,reset_at=stamp(2026,11,18,23))
        old=row(id='old',start=stamp(2026,11,4),end=shared,closed=True)
        self.assertEqual(quota_days(dict(old,end=stamp(2026,11,11)))[1],date(2026,11,10))
        data=sample();data['report']['day']='2026-11-16';data['quota_history']={'cycles':[current,old]}
        r=self.open_page('cycle',data);r.cycle_view.choice.showPopup()
        c=r.calendar;self.assertIsNotNone(c)
        r.page_fade.clear();APP.processEvents()
        c.buttons[date(2026,11,11)].click()
        self.assertEqual(c.switch.count(),2)
        c.switch.setCurrentIndex(c.switch.findData('old'))
        self.assertEqual(c.selected,'old')
        b=self.b
        b.toggle_details();t=b.size_transition
        self.assertTrue(r.follow.committed)
        parts=r.follow.module_morph.shared_parts
        self.assertTrue(any(key.startswith('calendar/') and key.endswith('fixed-center-date') for key in parts),list(parts))
        t.advance(.5);self.assertGreater(r.follow.geometry().width(),r.follow.start.width())
        t.complete();r.follow.release();APP.processEvents()
        self.assertEqual(c.geometry(),QRect(r.surface.rect()))
        c.apply.click();self.assertIsNone(r.calendar);self.assertEqual(r.cycle_view.selected_id,'old')

    def test_cost_entry_selects_historical_day_and_ignores_wrong_worker_range(self):
        data=sample();data['projects']={'yesterday':'2026-10-17','calendar_days':['2026-10-11','2026-10-17'],'ranges':{'yesterday':[]}}
        r=self.open_page('projects',data)
        with patch.object(r,'_watch_project_range',return_value=True) as watch:
            r.set_period('yesterday');view=r.project_view;view.date_button.click()
            c=r.calendar;self.assertIsNotNone(c)
            c.buttons[date(2026,10,11)].click();c.apply.click()
            bounds=date_bounds('yesterday',date(2026,10,11));key=range_key(bounds)
            watch.assert_called_with(bounds)
            self.assertEqual(view.period,key)
            self.assertEqual(view.date_button.text(),'2026.10.11')
            self.assertTrue(view.data['calendar_loading'])
            r.set_snapshot(dict(data,projects=dict(data['projects'],ranges={**data['projects']['ranges'],key:[]})))
            self.assertFalse(view.data.get('calendar_loading'))
            self.assertTrue(view.date_button.isVisible())
            r.set_period('all');r.set_snapshot(data)
            r.set_period('yesterday')
            self.assertFalse(view.data.get('calendar_loading'))
            self.assertIn(key,view.data['ranges'])
            watch.assert_called_with(bounds,refresh=False)

    def test_default_week_and_month_are_available_without_requesting_a_query(self):
        data=sample();day=date(2026,10,17)
        keys={period:range_key(date_bounds(period,day)) for period in ('7d','30d')}
        data['projects']={'yesterday':day.isoformat(),'ranges':{key:[] for key in keys.values()}}
        r=self.open_page('projects',data)
        with patch.object(r,'_watch_project_range',return_value=True) as watch:
            for period in ('7d','30d','7d','30d'):
                r.set_period(period)
                self.assertEqual(r.project_view.period,keys[period])
                self.assertFalse(r.project_view.data.get('calendar_loading'))
            self.assertTrue(all(call.args==(None,) for call in watch.call_args_list))

    def test_empty_current_cost_range_reports_initial_indexing(self):
        data=sample();day=date(2026,10,17);key=range_key(date_bounds('7d',day))
        data['projects']={'yesterday':day.isoformat(),'initial_pending':True,'ranges':{key:[]}}
        r=self.open_page('projects',data);r.set_period('7d')
        self.assertIn('正在整理项目记录',r.project_view.summary.text())
        r.set_snapshot({**data,'projects':{**data['projects'],'initial_pending':False}})
        self.assertIn('没有匹配项目',r.project_view.summary.text())

    def test_actions_stay_visible_on_short_calendar_and_same_month_reuses_buttons(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QScrollArea,QWidget
        from report_calendar import ReportCalendar
        host=QWidget();host.resize(240,180);host.show()
        first,second=date(2026,11,1),date(2026,11,3)
        calendar=ReportCalendar(host,'projects','yesterday',first,second,(first,second))
        calendar.setGeometry(host.rect());calendar.show();APP.processEvents()
        try:
            area=calendar.findChild(QScrollArea);button=calendar.buttons[second]
            self.assertGreater(area.verticalScrollBar().maximum(),0)
            self.assertTrue(calendar.compact_title.isVisible())
            self.assertTrue(calendar.page_title.isHidden())
            loc=calendar.apply.mapTo(calendar,QPoint())
            self.assertTrue(calendar.rect().contains(QRect(loc,calendar.apply.size())))
            area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
            self.assertEqual(calendar.apply.mapTo(calendar,QPoint()),loc)
            button.click();button.click()
            self.assertIs(calendar.buttons[second],button)
            self.assertTrue(button.isChecked())
            self.assertEqual(calendar.selected,second)
        finally:host.close();host.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main()
