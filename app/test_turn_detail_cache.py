"""Cache lifetime follows stable source/session identity, not a view visit."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import QObject,Signal
from PySide6.QtWidgets import QApplication
from turn_detail_cache import TurnDetails
APP=QApplication.instance() or QApplication([])

class Job(QObject):
    ready=Signal(object);failed=Signal(str);finished=Signal()
    def __init__(self,*args,**kwargs):super().__init__();self.starts=0
    def start(self):self.starts+=1

class TurnCacheTests(unittest.TestCase):
    def key(self,n=1,revision='a',price='p'):return ('source','sid','all',price,n,revision)
    def rows(self):return [dict(id='sid',turns=[dict(id='t',tokens=100)])]
    def test_concurrent_reentries_share_one_pending_job(self):
        cache=TurnDetails();jobs=[]
        def factory():j=Job();jobs.append(j);return j
        first=cache.request(self.key(),factory)
        for n in range(2,6):self.assertIs(cache.request(self.key(n,str(n)),factory),first)
        self.assertEqual(len(jobs),1);self.assertEqual(first.starts,1)
    def test_new_tokens_show_previous_result_until_replacement_arrives(self):
        cache=TurnDetails();cache.finish(self.key(),self.rows());turns,exact=cache.lookup(self.key(2,'b'));self.assertFalse(exact);self.assertEqual(turns[0]['id'],'t')
        cache.finish(self.key(2,'b'),[dict(id='sid',turns=[dict(id='new')])]);self.assertTrue(cache.lookup(self.key(2,'b'))[1]);self.assertEqual(len(cache.entries),1)
    def test_latest_revision_runs_even_without_any_view_observer(self):
        cache=TurnDetails();jobs=[]
        def factory():
            job=Job();jobs.append(job);return job
        old=cache.request(self.key(),factory)
        cache.request(self.key(2,'b'),factory)
        newest=self.key(3,'c')
        cache.request(newest,factory)
        cache.pump()
        self.assertEqual(len(jobs),1)
        old.ready.emit(self.rows())
        self.assertEqual(len(jobs),2)
        jobs[1].ready.emit([dict(id='sid',turns=[dict(id='new')])])
        self.assertEqual(cache.lookup(newest),([dict(id='new')],True))
    def test_price_source_and_range_never_borrow_wrong_costs(self):
        cache=TurnDetails();cache.finish(self.key(),self.rows());self.assertEqual(cache.lookup(self.key(price='new')),(None,False));self.assertEqual(cache.lookup(('other','sid','all','p',1,'a')),(None,False));self.assertEqual(cache.lookup(('source','sid','7d','p',1,'a')),(None,False))
    def test_finished_request_survives_the_view_that_requested_it(self):
        cache=TurnDetails();job=cache.request(self.key(),Job);observer=QObject();observer.deleteLater();job.ready.emit(self.rows());self.assertTrue(cache.lookup(self.key())[1]);self.assertFalse(cache.jobs)
    def test_error_does_not_clear_last_good_cache_and_allows_retry(self):
        cache=TurnDetails();cache.finish(self.key(),self.rows());job=cache.request(self.key(2,'b'),Job);job.failed.emit('temporary');self.assertEqual(cache.lookup(self.key(2,'b'))[0][0]['id'],'t');self.assertIsNot(cache.request(self.key(2,'b'),Job),job)
    def test_cache_is_bounded_by_distinct_sessions(self):
        cache=TurnDetails()
        for n in range(20):cache.finish(('source',str(n),'all','p',1,'a'),[dict(id=str(n),turns=[])])
        self.assertEqual(len(cache.entries),8)
    def test_fast_navigation_bounds_readers_and_queued_requests(self):
        cache=TurnDetails();jobs=[]
        def factory():job=Job();jobs.append(job);return job
        for n in range(20):cache.request(('source',str(n),'all','p',1,'a'),factory)
        self.assertEqual(len(jobs),2);self.assertEqual(len(cache.jobs),2);self.assertEqual(len(cache.pending),8)
        jobs[0].failed.emit('temporary');self.assertEqual(len(jobs),3);self.assertEqual(len(cache.jobs),2)
    def test_return_before_completion_rejoins_job_and_new_view_reuses_result(self):
        from unittest.mock import patch
        from project_cost_ui import ProjectCosts
        session=dict(id='sid',name='会话名',tokens=100,cost=1,detail_revision='a')
        project=dict(id='p',name='项目',path='D:/demo',tokens=100,cost=1,parts=[1,0,0],pending_tokens=0,sessions=1,session_ids=['sid'],session_usage=[session],models=[],model_usage=[],archived=False)
        data=dict(ranges={'all':[project]},price_revision='p');cache=TurnDetails()
        with patch('turn_detail_cache.shared',return_value=cache),patch('project_cost_ui.DetailJob',Job),patch('project_cost_ui.motion_enabled',return_value=False):
            first=ProjectCosts();first.detail_index_path='mock-index';first.set_data(data,'all');first.select(project);first.open_session(session);job=first.detail_job
            first.go_back();first.open_session(session);self.assertIs(first.detail_job,job);self.assertEqual(job.starts,1)
            turn=dict(id='t',stamp=1,models=['model'],tokens=100,input=80,cached=10,output=20,cost=1,pending_tokens=0,known=True,unknown=False)
            job.ready.emit([dict(id='sid',turns=[turn])]);self.assertEqual(first.session['turns'],[turn]);first.close();first.deleteLater()
            second=ProjectCosts();second.detail_index_path='mock-index';second.set_data(data,'all');second.select(project);second.open_session(session);self.assertEqual(second.session['turns'],[turn]);self.assertIsNone(second.detail_job)
            second.close();second.deleteLater()
    def test_reentry_after_append_keeps_visible_rows_while_refreshing(self):
        from unittest.mock import patch
        from project_cost_ui import ProjectCosts,TurnRow
        session=dict(id='sid',name='会话名',tokens=100,cost=1,detail_revision='a')
        project=dict(id='p',name='项目',path='D:/demo',tokens=100,cost=1,parts=[1,0,0],pending_tokens=0,sessions=1,session_ids=['sid'],session_usage=[session],models=[],model_usage=[],archived=False)
        turn=dict(id='t',stamp=1,models=['model'],tokens=100,input=80,cached=10,output=20,cost=1,pending_tokens=0,known=True,unknown=False)
        cache=TurnDetails();cache.finish(('mock-index','sid','all','p',100,'a'),[dict(id='sid',turns=[turn])])
        with patch('turn_detail_cache.shared',return_value=cache),patch('project_cost_ui.DetailJob',Job),patch('project_cost_ui.motion_enabled',return_value=False):
            view=ProjectCosts();view.detail_index_path='mock-index';view.set_data(dict(ranges={'all':[project]},price_revision='p'),'all');view.select(project);view.open_session(dict(session,tokens=200,detail_revision='b'))
            self.assertEqual(view.session['turns'],[turn]);self.assertTrue(view.session['syncing']);self.assertEqual(len(view.findChildren(TurnRow)),1);self.assertEqual(view.detail_job.starts,1);view.close();view.deleteLater()

if __name__=='__main__':unittest.main()
