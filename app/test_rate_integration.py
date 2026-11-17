"""In-memory replay: restart, duplicate, moved file, truncation and inspection lifecycle."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import io,json,sqlite3,unittest
from datetime import datetime,timedelta
from types import SimpleNamespace
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from rate_index import update,snapshot
from token_charts import TokenChartCard
from rate_chart import rate_text

APP=QApplication.instance() or QApplication([])
class Log:
    stem='session'
    def __init__(self,name='a'):self.name=name;self.data=b''
    def __str__(self):return self.name
    def stat(self):return SimpleNamespace(st_size=len(self.data))
    def open(self,mode):return io.BytesIO(self.data)
    def append(self,payload,kind='event_msg',day=1):
        event=dict(timestamp=datetime(2026,10,day,12).astimezone().isoformat(),type=kind,payload=payload)
        self.data+=(json.dumps(event)+'\n').encode()
def turn(log,name,out,duration):
    log.append(dict(type='task_started',turn_id=name))
    log.append(dict(type='token_count',info=dict(total_token_usage=dict(input_tokens=100,output_tokens=out,reasoning_output_tokens=0))))
    log.append(dict(type='task_complete',turn_id=name,duration_ms=duration,time_to_first_token_ms=1200))

class RateIntegration(unittest.TestCase):
    def setUp(self):self.db=sqlite3.connect(':memory:');self.log=Log();self.log.append(dict(id='s'),'session_meta');self.now=datetime(2026,10,2,13).timestamp()
    def tearDown(self):self.db.close()
    def test_hourly_output_splits_at_hour_boundary_and_does_not_wait_for_completion(self):
        self.db.execute('CREATE TABLE usage(session TEXT,stamp REAL,output_tokens INTEGER,known INTEGER)')
        boundary=datetime(2026,10,2,11).timestamp()
        rows=[('a',boundary-30,0,1),('a',boundary+30,600,1),
              ('a',boundary+400,20000,1),('a',boundary+420,None,0),
              ('a',boundary+460,400,1),('a',boundary+480,200,1),
              ('b',boundary-30,0,1),('b',boundary+30,1200,1),
              ('c',boundary+3600,0,1),('c',boundary+3950,9000,1)]
        self.db.executemany('INSERT INTO usage VALUES (?,?,?,?)',rows)
        rates=snapshot(self.db,self.now,include_output=True)
        self.assertEqual(rates['today'][10:13],[None,None,None])
        self.assertEqual(rates['today_output'][10:13],[
            dict(rate=15.,sampled_seconds=60.),dict(rate=13.75,sampled_seconds=80.),None])
    def test_restart_baseline_and_weighted_rate_survive_duplicate_or_moved_log(self):
        self.log.append(dict(type='task_started',turn_id='first'));update(self.db,[self.log],budget=1)
        self.log.append(dict(type='token_count',info=dict(total_token_usage=dict(input_tokens=100,output_tokens=100,reasoning_output_tokens=0))))
        self.log.append(dict(type='task_complete',turn_id='first',duration_ms=10000,time_to_first_token_ms=1000))
        update(self.db,[self.log],budget=1);turn(self.log,'second',400,10000);update(self.db,[self.log],budget=1)
        self.assertEqual(snapshot(self.db,self.now)['yesterday_mean']['rate'],20)
        moved=Log('b');moved.data=self.log.data;update(self.db,[self.log,moved],budget=1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM rate_samples').fetchone()[0],2)
        self.assertEqual(snapshot(self.db,self.now)['yesterday_mean']['samples'],2)
    def test_existing_paginated_turn_is_repaired_without_duplicate_samples(self):
        from unittest.mock import patch
        self.log.data=b''
        self.log.append(dict(id='s',history_base=dict(thread_id='s')),'session_meta')
        self.log.append(dict(type='task_started',turn_id='first'))
        total=dict(input_tokens=1_000_100,output_tokens=5_020,reasoning_output_tokens=20)
        recent=dict(input_tokens=100,output_tokens=20,reasoning_output_tokens=0)
        self.log.append(dict(type='token_count',info=dict(total_token_usage=total,last_token_usage=recent)))
        self.log.append(dict(type='task_complete',turn_id='first',duration_ms=10000))
        with patch('rate_index.continuation',return_value=False):
            update(self.db,[self.log],budget=1)
        self.assertEqual(snapshot(self.db,self.now)['yesterday_mean']['rate'],502)
        self.db.execute("UPDATE rate_files SET state=json_remove(state,'$.segment_checked')")
        for _ in range(2):
            self.assertEqual(update(self.db,[self.log],budget=1)['errors'],0)
            self.assertEqual(self.db.execute('SELECT input_tokens,output_tokens FROM rate_samples').fetchall(),[(100,20)])
            self.assertEqual(snapshot(self.db,self.now)['yesterday_mean']['rate'],2)

    def test_late_attach_counter_reset_and_partial_tail_do_not_invent_rate_or_starve_other_files(self):
        self.log.data=b'';turn(self.log,'unknown',200,10000);self.log.data+=b'{unfinished'
        other=Log('z');other.append(dict(id='real'),'session_meta');turn(other,'known',100,5000)
        progress=update(self.db,[self.log,other],budget=1)
        self.assertFalse(progress['pending']);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM rate_samples').fetchone()[0],1)
        self.assertEqual(snapshot(self.db,self.now)['yesterday_mean']['rate'],20)
    def test_clock_budget_is_resumable_not_starting_every_pass_at_first_file(self):
        logs=[]
        for i in range(10):
            log=Log(str(i));log.append(dict(id=str(i)),'session_meta');turn(log,str(i),100,1000);logs.append(log)
        from unittest.mock import patch
        for _ in range(40):
            values=iter([0,0,0,0,.2,.2,.2,.2])
            with patch('rate_index.time.monotonic',side_effect=lambda:next(values,.2)):
                update(self.db,logs,budget=.15)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM rate_samples').fetchone()[0],10)

class ChartInspection(unittest.TestCase):
    def test_hover_changes_bin_hides_with_chart_and_never_uses_native_tooltip(self):
        now=datetime(2026,10,2,13).timestamp();rates=[None]*24;rates[3]=dict(rate=12.3,first_token_ms=1500,samples=2)
        snap=dict(today='2026-10-02',hours=list(range(24)),history_days={'2026-10-02':100},rates=dict(today=rates))
        card=TokenChartCard(snap,period='day',now=now);card.resize(121,78);card.show();APP.processEvents();plot=card.plot;plot.reveal.progress=1;plot.grab()
        plot.inspect_at(plot.hits[3][0].center());plot.show_inspection();APP.processEvents()
        self.assertTrue(plot._popup.isVisible());self.assertEqual(plot._popup.record['label'],'03:00–04:00');self.assertIn('12.3',rate_text(plot._popup.record['rate_item']))
        plot.inspect_at(plot.hits[4][0].center());self.assertEqual(plot._popup.record['label'],'04:00–05:00');self.assertEqual(plot.toolTip(),'')
        card.hide();APP.processEvents();self.assertFalse(plot._popup.isVisible());card.close();card.deleteLater();APP.processEvents()
    def test_long_history_uses_same_bucket_boundaries_as_model_page(self):
        from token_analytics import model_series
        day=datetime(2026,1,1);history={(day+timedelta(days=i)).strftime('%Y-%m-%d'):i for i in range(100)}
        card=TokenChartCard(dict(history_days=history),period='all',now=(day+timedelta(days=99)).timestamp())
        model=model_series(dict(day=max(history),daily_models=[
            dict(day=date,model='m',total=value,input=0,output=value,known=True) for date,value in history.items()]),'all')
        self.assertEqual([(b['start'],b['end'],b['value']) for b in card.plot.series['bins']],
                         [(b['start'],b['end'],b['total']) for b in model['bins']])
        self.assertLessEqual(len(card.plot.series['bins']),24)
        card.close();card.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
