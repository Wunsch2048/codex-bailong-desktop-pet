import json,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import closing
from session_read_state import seen_completed_turns,ReadAcknowledgements

class ReadCompletionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name);self.state([])
  with closing(sqlite3.connect(self.home/'thread_history_1.sqlite',isolation_level=None)) as db:
   db.execute('CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,status TEXT,rollout_ordinal INTEGER)')
   db.executemany('INSERT INTO thread_turns VALUES(?,?,?,?)',[('a','old','completed',1),('a','done','completed',2),('b','other','completed',1)])
 def tearDown(self):self.tmp.cleanup()
 def state(self,ids):
  (self.home/'.codex-global-state.json').write_text(json.dumps({'electron-thread-read-state-v1':dict(version=1,unreadByIdentity={'account':{'local:host':ids}})}),encoding='utf-8')
 def test_missing_receipt_uses_exact_terminal_history_without_creating_database(self):
  self.assertEqual(seen_completed_turns(self.home,[('a','done')]),[('a','done')]);self.assertFalse((self.home/'state_5.sqlite').exists())
  self.assertEqual(seen_completed_turns(self.home,[('a','old'),('a','future')]),[('a','old')])
 def test_old_failed_reminder_clears_while_new_turn_is_running_only_after_read(self):
  with closing(sqlite3.connect(self.home/'thread_history_1.sqlite',isolation_level=None)) as db:
   db.execute("UPDATE thread_turns SET status='failed' WHERE turn_id='done'")
   db.execute("INSERT INTO thread_turns VALUES('a','new','inProgress',3)")
  self.state(['a','b']);watch=ReadAcknowledgements();pending=[('a','done'),('a','new'),('b','other')]
  self.assertEqual(watch.poll(self.home,pending,100),[])
  self.state(['b']);self.assertEqual(watch.poll(self.home,pending,102),[])
  self.assertEqual(watch.poll(self.home,pending,106),[('a','done')])
 def test_interrupted_is_terminal_but_unknown_status_and_missing_turn_are_not(self):
  with closing(sqlite3.connect(self.home/'thread_history_1.sqlite',isolation_level=None)) as db:
   db.execute("UPDATE thread_turns SET status='interrupted' WHERE turn_id='done'")
   db.execute("UPDATE thread_turns SET status='new-future-status' WHERE turn_id='other'")
  self.assertEqual(seen_completed_turns(self.home,[('a','done'),('b','other'),('a','missing')]),[('a','done')])
 def test_multiple_old_notices_clear_without_taking_another_sessions_read_evidence(self):
  self.state(['b']);keys=[('a','old'),('a','done'),('b','other'),('b','done')]
  self.assertEqual(seen_completed_turns(self.home,keys),keys[:2])
 def test_stale_legacy_receipt_does_not_block_confirmed_current_history(self):
  with closing(sqlite3.connect(self.home/'state_5.sqlite',isolation_level=None)) as db:
   db.execute('CREATE TABLE thread_read_receipts(thread_id TEXT,last_published_turn TEXT)');db.execute("INSERT INTO thread_read_receipts VALUES('a','old')")
  self.assertEqual(seen_completed_turns(self.home,[('a','done')]),[('a','done')])
 def test_viewing_one_session_keeps_other_unread_and_waits_for_stable_evidence(self):
  self.state(['b']);watch=ReadAcknowledgements()
  pending=[('a','done'),('b','other')]
  self.assertEqual(watch.poll(self.home,pending,100),[]);self.assertEqual(watch.poll(self.home,pending,102),[])
  self.assertEqual(watch.poll(self.home,pending,104),[('a','done')])
 def test_late_unread_publication_resets_stability_timer(self):
  watch=ReadAcknowledgements();pending=[('a','done')]
  self.assertEqual(watch.poll(self.home,pending,100),[]);self.state(['a'])
  self.assertEqual(watch.poll(self.home,pending,102),[]);self.state([])
  self.assertEqual(watch.poll(self.home,pending,104),[]);self.assertEqual(watch.poll(self.home,pending,106),[])
  self.assertEqual(watch.poll(self.home,pending,108),pending)
 def test_unknown_metadata_resets_stability_and_never_means_read(self):
  watch=ReadAcknowledgements();pending=[('a','done')];watch.poll(self.home,pending,100)
  (self.home/'.codex-global-state.json').write_text('{}');self.assertEqual(watch.poll(self.home,pending,104),[])
  self.state([]);self.assertEqual(watch.poll(self.home,pending,106),[]);self.assertEqual(watch.poll(self.home,pending,110),pending)
 def test_new_turn_never_reuses_previous_read_evidence(self):
  watch=ReadAcknowledgements();watch.poll(self.home,[('a','done')],100)
  with closing(sqlite3.connect(self.home/'thread_history_1.sqlite',isolation_level=None)) as db:db.execute("INSERT INTO thread_turns VALUES('a','new','inProgress',3)")
  self.assertEqual(watch.poll(self.home,[('a','new')],104),[])
  with closing(sqlite3.connect(self.home/'thread_history_1.sqlite',isolation_level=None)) as db:db.execute("UPDATE thread_turns SET status='completed' WHERE turn_id='new'")
  self.assertEqual(watch.poll(self.home,[('a','new')],106),[]);self.assertEqual(watch.poll(self.home,[('a','new')],110),[('a','new')])

if __name__=='__main__':unittest.main()
