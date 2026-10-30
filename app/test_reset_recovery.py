"""Public-feed recovery, cache failures and truthful partial refresh feedback."""
import io,json,ssl,tempfile,time,unittest,urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from reset_watch import fetch_feed,ResetFetchError,ResetCacheError,ResetTracker,reset_failure
APP=QApplication.instance() or QApplication([])
class ResetRecoveryTests(unittest.TestCase):
 def test_fresh_fetch_recreates_proxy_handler(self):
  with patch('urllib.request.build_opener') as factory:
   factory.return_value.open.side_effect=lambda *a,**k:io.BytesIO(b'{"events":[],"scheduled":null}')
   fetch_feed();fetch_feed();self.assertEqual(factory.call_count,2)
 def test_one_transient_failure_retries_without_credentials(self):
  opener=Mock(side_effect=[urllib.error.URLError(TimeoutError('timed out')),io.BytesIO(b'{"events":[],"scheduled":null}')])
  with patch('reset_watch.time.sleep'):self.assertEqual(fetch_feed(opener)['events'],[])
  self.assertEqual(opener.call_count,2)
  request=opener.call_args.args[0];self.assertFalse(request.has_header('Authorization'));self.assertIsNone(request.data)
 def test_certificate_failure_is_specific_and_never_bypassed(self):
  opener=Mock(side_effect=urllib.error.URLError(ssl.SSLCertVerificationError(1,'verify failed')))
  with self.assertRaises(ResetFetchError) as exc:fetch_feed(opener)
  self.assertEqual(exc.exception.code,'certificate');self.assertEqual(opener.call_count,1)
 def test_schema_error_is_not_retried_as_connection_error(self):
  opener=Mock(return_value=io.BytesIO(b'<html>unavailable</html>'))
  with self.assertRaises(ResetFetchError) as exc:fetch_feed(opener)
  self.assertEqual(exc.exception.code,'schema');self.assertEqual(opener.call_count,1)
 def test_fresh_announcement_is_available_when_cache_cannot_be_written(self):
  from enhanced import ResetThread
  now=time.time();scheduled=dict(id='new',announced=now,scheduled=now+3600,reset_type='regular',text='new schedule');feed=dict(events=[],scheduled=scheduled)
  with tempfile.TemporaryDirectory() as tmp,patch('enhanced.STATE_DIR',Path(tmp)):
   worker=ResetThread();ready=[];diagnostics=[]
   def on_ready(snapshot,alerts,fresh):ready.append((snapshot,fresh));worker.stop.set();worker.wake.set()
   worker.ready.connect(on_ready);worker.diagnostic.connect(diagnostics.append)
   with patch('enhanced.fetch_feed',return_value=feed),patch('desktop_core.atomic_json',side_effect=PermissionError('locked')):worker.run()
   self.assertEqual(ready[0][0]['pending'],scheduled);self.assertTrue(ready[0][1]);self.assertEqual(worker.tracker.snapshot['pending'],scheduled)
   self.assertEqual(diagnostics[-1]['code'],'cache_write')
 def test_only_reset_failure_reports_partial_not_total_failure(self):
  from enhanced import EnhancedPet
  from refresh_flow import RefreshCoordinator
  p=SimpleNamespace(closing=False,bubble=SimpleNamespace(set_refresh_busy=Mock(),finish_refresh=Mock(),report=None),refresh_timeout=Mock(),refresh_quota=Mock(return_value=1),refresh_tokens=Mock(return_value=2),refresh_reset_feed=Mock(return_value=3))
  p.refresh_flow=RefreshCoordinator(lambda *args:EnhancedPet._refresh_finished(p,*args))
  EnhancedPet.refresh_all(p);p.refresh_flow.result('quota',1,True);p.refresh_flow.result('token',2,True);p.refresh_flow.result('reset',3,False)
  p.bubble.finish_refresh.assert_called_once_with('partial');self.assertEqual(p.last_refresh_result['failed'],['reset'])
 def test_cache_warning_does_not_mark_fresh_schedule_as_old(self):
  from reset_presentation import reset_view
  now=time.time();snapshot={'pending':dict(id='n',announced=now,scheduled=now+3600,reset_type='regular')}
  v=reset_view(snapshot,reset_failure(OSError('locked'),'cache'),now)
  self.assertEqual(v['value'],'1');self.assertNotIn('上次',v['eyebrow']);self.assertIn('缓存',v['note'])
 def test_new_schedule_replaces_old_pending_and_local_confirmation(self):
  from reset_watch import LocalResetEvidence,reset_has_priority
  now=time.time();old=dict(id='old',announced=now-86400,scheduled=now-3600,reset_type='regular',text='old schedule')
  new=dict(id='new',announced=now-60,scheduled=now+7200,reset_type='regular',text='new schedule')
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'reset-watch.json';tracker=ResetTracker(path)
   tracker.update(dict(events=[],scheduled=old),now-3600)
   evidence=LocalResetEvidence(Path(tmp)/'evidence.json');evidence.state['reset']=dict(observed=now-1800,window='一周',kind='extra')
   self.assertFalse(reset_has_priority(evidence.decorate(tracker.snapshot)))
   snapshot,alerts=tracker.update(dict(events=[dict(old,announced=now-3600)],scheduled=new),now)
   self.assertEqual(snapshot['pending'],new);self.assertEqual(ResetTracker(path).snapshot['pending'],new)
   self.assertTrue(reset_has_priority(evidence.decorate(snapshot)))
   self.assertEqual([a['kind'] for a in alerts],['confirmed','scheduled'])
 def test_partial_button_retains_distinct_result(self):
  from compact_bubble import CompactBubble
  b=CompactBubble();b.finish_refresh('partial');self.assertEqual(b.refresh_button.result,'partial');self.assertIn('公告',b.refresh_button.accessibleDescription());b.close();b.deleteLater()
 def test_unexpected_diagnostic_retains_origin_without_private_path_or_message(self):
  try:raise FileNotFoundError(2,'private message','C:/private-user/runtime/roots.pem')
  except OSError as error:record=reset_failure(error)
  self.assertEqual(record['missingFile'],'roots.pem');self.assertTrue(record['origin'])
  self.assertNotIn('private-user',json.dumps(record));self.assertNotIn('private message',json.dumps(record));self.assertNotIn('C:/',json.dumps(record))

if __name__=='__main__':unittest.main()
