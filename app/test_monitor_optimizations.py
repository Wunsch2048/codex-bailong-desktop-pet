"""Small regressions for borrowed accounting/lifecycle invariants; no live data."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,sqlite3,unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QWidget,QLabel
from project_cost import migrate,snapshot,pricing_revision
from project_cost_store import migrate as source_migrate,active_events,active_event_stream
from token_rate import MetadataCollector,RateStore
from refresh_flow import CompletionRefresh

APP=QApplication.instance() or QApplication([])

class CostProjectionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');migrate(self.db);source_migrate(self.db)
    def tearDown(self):self.db.close()
    def event(self,key='e',session='s',tokens=1000,model='gpt-6.1-sol',known=1,path='d:/project'):
        return (key,1000,session,path,model,tokens,tokens*8//10,tokens*6//10,tokens*2//10,known)
    def source(self,path,rev,session,ids,stamp=1000):
        self.db.execute('INSERT INTO cost_source_active VALUES(?,?,?,?,?,?,?,?)',
            (path,rev,session,0,json.dumps(dict(session=session,last_stamp=stamp)),json.dumps(dict(mtime=stamp)),0,0))
        self.db.executemany('INSERT INTO cost_source_events VALUES(?,?,?)',[(path,rev,key) for key in ids])
    def test_stream_selects_canonical_deduplicates_and_keeps_missing_log_history(self):
        self.db.executemany('INSERT INTO cost_revision_events VALUES(?,?,?,?,?,?,?,?,?,?)',
            [self.event('a'),self.event('b'),self.event('old'),self.event('orphan')])
        self.source('new','r2','s',['a','b'],2000);self.source('copy','r1','s',['a'])
        self.db.executemany('INSERT INTO cost_events VALUES(?,?,?,?,?,?,?,?,?,?)',
            [self.event('legacy'),self.event('retained','missing')])
        rows,conflicts=active_event_stream(self.db)
        self.assertNotIsInstance(rows,list)
        self.assertEqual({r[0] for r in rows},{'a','b','retained'});self.assertEqual(conflicts,0)
        self.db.execute("INSERT INTO cost_source_events VALUES('copy','r1','old')")
        rows,conflicts=active_events(self.db)
        self.assertEqual({r[0] for r in rows},{'a','b','retained'});self.assertEqual(conflicts,1)
    def test_lower_corrected_source_replaces_old_without_max_or_double_count(self):
        self.db.executemany('INSERT INTO cost_revision_events VALUES(?,?,?,?,?,?,?,?,?,?)',
            [self.event('old',tokens=2000),self.event('corrected',tokens=500)])
        self.source('old','a','s',['old']);self.source('new','b','s',['corrected'],2000)
        data=snapshot(self.db,2001,dict(pending=False,errors=0))
        self.assertEqual(data['ranges']['all'][0]['tokens'],500)
        self.assertEqual(data['source_conflicts'],1)
    def test_prices_revision_recomputes_known_cost_and_zero_is_free(self):
        self.db.execute('INSERT INTO cost_events VALUES(?,?,?,?,?,?,?,?,?,?)',self.event())
        before=snapshot(self.db,2001,{})
        with patch.dict('project_cost.RATES',{'gpt-6.1-sol':(0,0,0)}):
            after=snapshot(self.db,2001,{})
        self.assertNotEqual(before['price_revision'],after['price_revision'])
        row=after['ranges']['all'][0]
        self.assertEqual((row['cost'],row['pending_tokens'],row['price_coverage']),(0,0,1))
        self.assertEqual(pricing_revision({'a':(1,2,3),'b':(4,5,6)}),pricing_revision({'b':(4,5,6),'a':(1,2,3)}))
    def test_incomplete_event_does_not_unprice_same_model_day(self):
        self.db.executemany('INSERT INTO cost_events VALUES(?,?,?,?,?,?,?,?,?,?)',
            [self.event('good'),self.event('bad',known=0)])
        row=snapshot(self.db,2001,{})['ranges']['all'][0]
        self.assertEqual((row['tokens'],row['pending_tokens'],row['priced_tokens']),(2000,1000,1000))
        self.assertAlmostEqual(row['cost'],.00246)
    def test_pending_reasons_are_exclusive_and_never_erase_known_cost(self):
        self.db.executemany('INSERT INTO cost_events VALUES(?,?,?,?,?,?,?,?,?,?)',[
            self.event('priced'),self.event('unknown',model='unknown'),self.event('incomplete',model='unknown',known=0),
            self.event('unassigned',path='')])
        data=snapshot(self.db,2001,{})
        row=next(r for r in data['ranges']['all'] if r['id']=='d:/project')
        self.assertGreater(row['cost'],0);self.assertEqual(row['priced_tokens'],1000)
        self.assertAlmostEqual(row['price_coverage'],1/3)
        self.assertEqual(row['pending_reasons'],dict(unknown_model=1000,incomplete_counts=1000))
        self.assertEqual(sum(row['pending_reasons'].values()),row['pending_tokens'])
        self.assertEqual(next(r for r in data['ranges']['all'] if not r['id'])['pending_reasons'],dict(unknown_project=1000))
        from project_cost_ui import ProjectCosts
        view=ProjectCosts();view.data=data;body=view.detail_body(row)
        from PySide6.QtWidgets import QPushButton
        pending=next(button for button in body.findChildren(QPushButton) if '待定价' in button.text())
        pending.click()
        text='\n'.join(label.text() for label in view.findChildren(QLabel))
        self.assertIn('模型暂无单价',text);self.assertIn('输入 / 输出记录不完整',text)
        body.deleteLater();view.deleteLater();APP.processEvents()

class RateLifecycleTests(unittest.TestCase):
    def setUp(self):self.store=RateStore(':memory:');self.collector=MetadataCollector(self.store)
    def tearDown(self):self.store.close()
    def feed(self,kind,**kwargs):return self.collector.ingest('local','s',dict(type=kind,**kwargs),1000)
    def usage(self,n,**kwargs):return self.feed('token_count',info=dict(total_token_usage=dict(input_tokens=n,output_tokens=n,reasoning_output_tokens=0)),**kwargs)
    def start(self):self.usage(100);self.feed('task_started',turn_id='t');self.usage(200)
    def test_abort_and_failed_completion_cannot_record_stale_turn(self):
        for kind in ('task_aborted','turn_failed','task_cancelled'):
            self.start();self.feed(kind,turn_id='t')
            self.assertFalse(self.feed('task_complete',turn_id='t',duration_ms=1000)['recorded'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM rate_samples').fetchone()[0],0)
    def test_duplicate_complete_after_new_usage_never_rewrites_sample(self):
        self.start();self.assertTrue(self.feed('task_complete',turn_id='t',duration_ms=1000)['recorded'])
        self.usage(300)
        self.assertFalse(self.feed('task_complete',turn_id='t',duration_ms=1000)['recorded'])
        self.assertEqual(self.store.db.execute('SELECT output_tokens FROM rate_samples').fetchone()[0],100)
    def test_mismatched_usage_does_not_change_active_turn(self):
        self.start();self.usage(900,turn_id='other')
        self.assertTrue(self.feed('task_complete',turn_id='t',duration_ms=2000)['recorded'])
        self.assertEqual(self.store.query(999,1001)['bins'][0]['task_tokens_per_second'],50)
    def test_invalid_usage_invalidates_sample_without_removing_other_statistics(self):
        self.start();self.usage(True)
        self.assertFalse(self.feed('task_complete',turn_id='t',duration_ms=1000)['recorded'])
    def test_late_inactive_usage_updates_baseline_but_does_not_reopen_turn(self):
        self.start();self.feed('task_complete',turn_id='t',duration_ms=1000)
        self.usage(300,turn_id='t');self.feed('task_started',turn_id='next');self.usage(400,turn_id='next')
        self.assertTrue(self.feed('task_complete',turn_id='next',duration_ms=1000)['recorded'])
        self.assertEqual(self.store.db.execute("SELECT output_tokens FROM rate_samples WHERE turn='next'").fetchone()[0],100)

class CompletionRefreshTests(unittest.TestCase):
    def test_burst_has_immediate_and_trailing_refresh_without_restarting_deadline(self):
        host=QWidget();clock=[100.];calls=[]
        gate=CompletionRefresh(host,lambda:calls.append(clock[0]),clock=lambda:clock[0])
        gate.request();clock[0]=101;gate.request();deadline=gate.timer.remainingTime()
        clock[0]=103;gate.request()
        self.assertEqual(calls,[100]);self.assertLessEqual(gate.timer.remainingTime(),deadline)
        clock[0]=115;gate.request()
        self.assertEqual(calls,[100,115]);self.assertFalse(gate.timer.isActive())
        host.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
