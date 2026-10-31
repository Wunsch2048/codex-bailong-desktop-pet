"""Manual refresh waits for real data while reusing independent background work."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from refresh_flow import RefreshCoordinator,RefreshRuns
from enhanced import EnhancedPet,ActivityThread,ResetThread

APP=QApplication.instance() or QApplication([])


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.now=0.;self.done=[]
        self.flow=RefreshCoordinator(lambda *args:self.done.append(args),lambda:self.now,timeout=5)
    def test_three_independent_results_and_shared_report(self):
        self.flow.begin('bubble',dict(quota=1,token=9,reset=2))
        self.flow.begin('report',dict(token=9))
        self.flow.result('reset',2,True)
        self.flow.result('token',9,True)
        self.assertEqual(self.done,[('report',True,[])])
        self.assertTrue(self.flow.active('bubble'))
        self.flow.result('quota',1,True)
        self.assertEqual(self.done[-1],('bubble',True,[]))
    def test_repeat_click_coalesces_and_duplicate_results_are_ignored(self):
        self.assertTrue(self.flow.begin('bubble',dict(token=1)))
        self.assertFalse(self.flow.begin('bubble',dict(token=2)))
        self.flow.result('token',1,True);self.flow.result('token',1,True)
        self.assertEqual(self.done,[('bubble',True,[])])
    def test_missing_worker_and_partial_failure_wait_for_other_sources(self):
        self.flow.begin('bubble',dict(quota=1,token=None,reset=3))
        self.flow.result('quota',1,False)
        self.assertEqual(self.done,[])
        self.flow.result('reset',3,True)
        self.assertEqual(self.done,[('bubble',False,['quota','token'])])
    def test_timeout_and_late_previous_result_cannot_finish_new_batch(self):
        self.flow.begin('report',dict(token=1));self.now=6.;self.flow.expire()
        self.assertEqual(self.done,[('report',False,['token'])])
        self.flow.begin('report',dict(token=2))
        self.flow.result('token',1,True)
        self.assertTrue(self.flow.active('report'))
        self.flow.result('token',2,True)
        self.assertEqual(self.done[-1],('report',True,[]))
    def test_busy_or_unidentified_terminal_cannot_claim_success(self):
        self.flow.begin('report',dict(token=4))
        self.flow.result('token',None,True)
        self.flow.result('reset',4,True)
        self.assertTrue(self.flow.active('report'))
    def test_reserved_worker_id_is_stable_until_actual_completion(self):
        runs=RefreshRuns();run,new=runs.reserve()
        self.assertTrue(new);self.assertEqual(runs.reserve(),(run,False))
        runs.complete(run-1);self.assertEqual(runs.active,run)
        runs.complete(run);later,new=runs.reserve()
        self.assertTrue(new);self.assertGreater(later,run)


class PipelineTests(unittest.TestCase):
    def pet(self):
        pet=SimpleNamespace(
            closing=False,bubble=SimpleNamespace(
                set_refresh_busy=Mock(),finish_refresh=Mock(),report=SimpleNamespace(
                    set_refresh_busy=Mock(),finish_refresh=Mock()),
                set_token_busy=Mock(),token_snapshot={'total':321,'report':{'total_tokens':321}},
                redraw=Mock()),
            refresh_timeout=SimpleNamespace(start=Mock(),stop=Mock()),
            activity=None,position_bubble=Mock())
        pet._refresh_finished=lambda *args:EnhancedPet._refresh_finished(pet,*args)
        pet.refresh_flow=RefreshCoordinator(pet._refresh_finished)
        return pet
    def test_refresh_launches_all_sources_once_report_joins_token(self):
        pet=self.pet()
        pet.refresh_quota=Mock(return_value=1)
        pet.refresh_tokens=Mock(return_value=2)
        pet.refresh_reset_feed=Mock(return_value=3)
        EnhancedPet.refresh_all(pet);EnhancedPet.refresh_all(pet)
        for starter in (pet.refresh_quota,pet.refresh_tokens,pet.refresh_reset_feed):
            starter.assert_called_once()
        pet.refresh_quota.assert_called_once_with(manual=True)
        EnhancedPet.refresh_report(pet)
        self.assertEqual(pet.refresh_tokens.call_count,2)
        pet.refresh_flow.result('token',2,True)
        pet.bubble.report.finish_refresh.assert_called_once_with(True)
        pet.bubble.finish_refresh.assert_not_called()
        pet.refresh_flow.result('quota',1,True);pet.refresh_flow.result('reset',3,True)
        pet.bubble.finish_refresh.assert_called_once_with(True)
    def test_report_never_starts_quota_or_reset(self):
        pet=self.pet();pet.refresh_tokens=Mock(return_value=1)
        pet.refresh_quota=Mock();pet.refresh_reset_feed=Mock()
        EnhancedPet.refresh_report(pet)
        pet.refresh_tokens.assert_called_once()
        pet.refresh_quota.assert_not_called();pet.refresh_reset_feed.assert_not_called()
    def test_failed_token_snapshot_keeps_last_data_and_reports_failure(self):
        pet=self.pet();pet.bubble.report.set_snapshot=Mock()
        pet.refresh_flow.begin('bubble',dict(token=3))
        EnhancedPet.on_activity(pet,dict(kind='token_usage',run_id=3,snapshot=dict(unavailable=True,total=0)))
        self.assertEqual(pet.bubble.token_snapshot['total'],321)
        self.assertTrue(pet.bubble.token_snapshot['refresh_failed'])
        self.assertFalse(pet.bubble.token_snapshot.get('unavailable',False))
        pet.bubble.finish_refresh.assert_called_once_with(False)
    def test_failed_refresh_preserves_visible_hourly_series_and_today_number(self):
        from token_calendar import usage_series
        from quota_summary_data import today_tokens
        pet=self.pet();pet.bubble.report.set_snapshot=Mock()
        today=datetime.now().date().isoformat()
        pet.bubble.token_snapshot=dict(today=today,month=today[:7],days={today:276},hours=list(range(24)),today_total=276)
        before=usage_series(pet.bubble.token_snapshot,'day')
        before_today=today_tokens(pet.bubble.token_snapshot)
        EnhancedPet.on_activity(pet,dict(kind='token_usage_error',run_id=1))
        self.assertEqual(usage_series(pet.bubble.token_snapshot,'day')['bins'],before['bins'])
        self.assertTrue(usage_series(pet.bubble.token_snapshot,'day')['available'])
        after_today=today_tokens(pet.bubble.token_snapshot)
        self.assertEqual(after_today['display'],before_today['display'])
        self.assertTrue(after_today['known']);self.assertTrue(after_today['partial'])
    def test_busy_false_does_not_finish_until_data_arrives(self):
        pet=self.pet();pet.bubble.report.set_snapshot=Mock()
        pet.refresh_flow.begin('bubble',dict(token=3))
        EnhancedPet.on_activity(pet,dict(kind='token_busy',busy=False,run_id=3))
        pet.bubble.finish_refresh.assert_not_called()
        EnhancedPet.on_activity(pet,dict(kind='token_usage',run_id=3,snapshot=dict(total=500)))
        pet.bubble.finish_refresh.assert_called_once_with(True)
    def test_quota_start_failure_does_not_leave_inflight(self):
        pet=self.pet();pet.quota_inflight=False;pet.quota_runs=RefreshRuns()
        pet.generation=1;pet.bubble.set_quota_busy=Mock()
        with patch('enhanced.QuotaWorker',side_effect=RuntimeError('cannot start')):
            self.assertIsNone(EnhancedPet.refresh_quota(pet))
        self.assertFalse(pet.quota_inflight);self.assertIsNone(pet.quota_runs.active)
        pet.bubble.set_quota_busy.assert_called_with(False)
    def test_unknown_quota_keeps_previous_known_values(self):
        pet=self.pet();pet.quota_runs=RefreshRuns();run,_=pet.quota_runs.reserve()
        pet.quota_windows=[dict(name='一周',remaining=70)]
        pet.bubble.set_quota_busy=Mock();pet.render_quota=Mock();pet.update_quota=Mock()
        pet.refresh_flow.begin('bubble',dict(quota=run))
        EnhancedPet.quota_ready(pet,[dict(name='一周',remaining=None)])
        pet.update_quota.assert_not_called()
        self.assertEqual(pet.quota_windows[0]['remaining'],70)
        pet.bubble.finish_refresh.assert_called_once_with(False)
    def test_old_reset_busy_false_does_not_clear_new_reservation(self):
        pet=self.pet();pet.bubble.set_reset_busy=Mock()
        pet.reset_worker=SimpleNamespace(refresh_runs=RefreshRuns())
        run,_=pet.reset_worker.refresh_runs.reserve()
        EnhancedPet._reset_busy_changed(pet,False)
        pet.bubble.set_reset_busy.assert_called_with(True)
        pet.reset_worker.refresh_runs.complete(run)
        EnhancedPet._reset_busy_changed(pet,False)
        pet.bubble.set_reset_busy.assert_called_with(False)


class WorkerTests(unittest.TestCase):
    def test_click_from_terminal_handler_never_joins_consumed_result(self):
        with tempfile.TemporaryDirectory() as folder,patch('enhanced.STATE_DIR',Path(folder)):
            worker=ActivityThread(home=folder);requests=[]
            first=worker.request_tokens()
            def on_event(event):
                if event['kind']=='token_usage':requests.append(worker.request_tokens())
            worker.event.connect(on_event)
            with patch.object(worker.token_index,'poll',return_value={'total':4}):
                worker.read_tokens()
            self.assertEqual(len(requests),1);self.assertGreater(requests[0],first)
            self.assertEqual(worker.token_runs.active,requests[0])
    def test_token_read_is_joined_and_failed_read_still_has_correct_id(self):
        with tempfile.TemporaryDirectory() as folder,patch('enhanced.STATE_DIR',Path(folder)):
            worker=ActivityThread(home=folder);events=[];worker.event.connect(events.append)
            run=worker.request_tokens();self.assertEqual(worker.request_tokens(),run)
            with patch.object(worker.token_index,'poll',return_value={'total':4}):
                worker.read_tokens()
            ready=next(event for event in events if event['kind']=='token_usage')
            self.assertEqual(ready['run_id'],run);self.assertIsNone(worker.token_runs.active)
            later=worker.request_tokens();self.assertGreater(later,run)
            with patch.object(worker.token_index,'poll',side_effect=OSError('unreadable')):
                worker.read_tokens()
            failed=next(event for event in events if event['kind']=='token_usage_error')
            self.assertEqual(failed['run_id'],later)
            self.assertEqual(events[-1],dict(kind='token_busy',busy=False,run_id=later))
    def test_reset_cached_snapshot_never_completes_manual_refresh(self):
        with tempfile.TemporaryDirectory() as folder,patch('enhanced.STATE_DIR',Path(folder)):
            worker=ResetThread();worker.tracker=Mock(snapshot={'checked':1})
            started=threading.Event();release=threading.Event();ready=[];done=[]
            worker.ready.connect(lambda *args:ready.append(args))
            worker.completed.connect(lambda *args:done.append(args))
            def fetch():
                started.set();release.wait(2);return {}
            with patch('enhanced.fetch_feed',side_effect=fetch),patch.object(worker.tracker,'update',return_value=({'checked':2},[])):
                worker.start()
                try:
                    self.assertTrue(started.wait(1))
                    run=worker.request_refresh();self.assertEqual(worker.request_refresh(),run)
                    APP.processEvents()
                    self.assertTrue(ready);self.assertFalse(ready[0][2]);self.assertEqual(done,[])
                    release.set()
                    deadline=time.monotonic()+2
                    while not done and time.monotonic()<deadline:APP.processEvents();time.sleep(.01)
                    self.assertEqual(done,[(run,True)])
                    self.assertTrue(ready[-1][2])
                finally:
                    release.set();worker.stop.set();worker.wake.set();self.assertTrue(worker.wait(2000))


if __name__=='__main__':unittest.main()
