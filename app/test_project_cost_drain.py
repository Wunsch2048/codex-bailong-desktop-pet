import unittest
from unittest.mock import patch
from project_cost_drain import drain

class DrainTests(unittest.TestCase):
    def run_drain(self,count=8,interrupt=999):
        now=[0.];calls=[];published=[]
        def wait(seconds):now[0]+=seconds;return False
        def step():
            calls.append(now[0]);now[0]+=.15
            return dict(pending=len(calls)<count)
        drain(step,lambda p:published.append((now[0],p)),lambda:False,wait,
              lambda:len(calls)>=interrupt,clock=lambda:now[0])
        return calls,published,now[0]
    def test_backlog_finishes_without_thirty_second_gaps(self):
        calls,events,elapsed=self.run_drain()
        self.assertEqual(len(calls),8);self.assertLess(elapsed,3)
        self.assertFalse(events[-1][1]['pending'])
    def test_manual_refresh_preempts(self):
        calls,events,_=self.run_drain(interrupt=2)
        self.assertEqual(len(calls),2);self.assertEqual(events,[])
    def test_throttled_progress_and_bounded_work(self):
        calls,events,elapsed=self.run_drain(count=999)
        self.assertLessEqual(elapsed,20.3)
        self.assertTrue(all(b[0]-a[0]>=2 for a,b in zip(events,events[1:])))
    def test_stop_during_wait_does_no_work(self):
        calls=[]
        drain(lambda:calls.append(1),lambda p:None,lambda:False,lambda s:True,lambda:False)
        self.assertEqual(calls,[])
    def test_unfinished_source_keeps_cursor(self):
        import sqlite3,project_cost
        from pathlib import Path
        with sqlite3.connect(':memory:') as db:
            project_cost.migrate(db)
            db.execute("INSERT INTO cost_cursor VALUES('path','a')")
            def unfinished(*args):time[0]=1.;return True
            time=[0.]
            with patch.object(project_cost,'scan',side_effect=unfinished) as scan, patch('project_cost.time.monotonic',side_effect=lambda:time[0]):
                result=project_cost.update(db,[Path('b'),Path('c')])
            self.assertTrue(result['pending']);self.assertEqual(scan.call_count,1)
            self.assertEqual(db.execute('SELECT value FROM cost_cursor').fetchone()[0],'a')
    def test_worker_continues_cost_without_repolling_tokens(self):
        import threading,time
        from types import SimpleNamespace
        from enhanced import ActivityThread
        from refresh_flow import RefreshRuns
        from unittest.mock import Mock
        events=[]
        index=SimpleNamespace(poll=Mock(return_value={'projects':{'pending':True}}),
            project_step=Mock(return_value={'pending':False}),project_snapshot=Mock(return_value={'pending':False,'ranges':{}}))
        worker=SimpleNamespace(token_runs=RefreshRuns(),event=SimpleNamespace(emit=events.append),wsl=False,
            context_lock=threading.Lock(),week_cycle=None,stop=threading.Event(),token_wake=threading.Event(),
            last_token_scan=time.monotonic(),token_index=index)
        ActivityThread.read_tokens(worker)
        index.poll.assert_called_once();index.project_step.assert_called_once()
        kinds=[e['kind'] for e in events]
        self.assertLess(kinds.index('token_usage'),kinds.index('project_cost'))
        self.assertFalse(next(e for e in events if e['kind']=='token_busy' and not e['busy'])['busy'])
    def test_maintenance_defers_index_writes_without_clearing_previous_ui_snapshot(self):
        import threading,time
        from types import SimpleNamespace
        from enhanced import ActivityThread
        from refresh_flow import RefreshRuns
        from unittest.mock import Mock
        events=[];index=SimpleNamespace(prepare=Mock(return_value={'state':'copy','pending':True}),poll=Mock())
        worker=SimpleNamespace(token_runs=RefreshRuns(),event=SimpleNamespace(emit=events.append),wsl=False,
            context_lock=threading.Lock(),week_cycle=None,stop=threading.Event(),token_wake=threading.Event(),
            last_token_scan=time.monotonic(),token_index=index)
        ActivityThread.read_tokens(worker);index.poll.assert_not_called()
        self.assertIn('database_maintenance',[e['kind'] for e in events])
        self.assertNotIn('token_usage',[e['kind'] for e in events])
        self.assertTrue(any(e['kind']=='token_busy' and not e['busy'] for e in events))

if __name__=='__main__':unittest.main()
