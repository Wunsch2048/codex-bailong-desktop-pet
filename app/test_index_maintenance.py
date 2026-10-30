import os,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from index_maintenance import IndexMaintenance,prune_slice,identity,digest
from project_cost import migrate
from project_cost_store import migrate as migrate_sources,active_events

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'tokens.sqlite3'
        with closing(sqlite3.connect(self.path)) as db,db:
            migrate(db);migrate_sources(db);db.execute('DROP TABLE cost_index_maintenance')
            db.execute('CREATE TABLE untouched(id TEXT PRIMARY KEY,value BLOB,note TEXT)')
            db.execute('INSERT INTO untouched VALUES(?,?,?)',('user',b'\0\xff','保存的统计'))
            db.execute('PRAGMA user_version=17');db.execute('PRAGMA application_id=123')
            db.execute('INSERT INTO cost_revision_events VALUES(?,?,?,?,?,?,?,?,?,?)',('live',1,'s','project:x','known',10,8,6,2,1))
            db.execute('INSERT INTO cost_revision_events VALUES(?,?,?,?,?,?,?,?,?,?)',('work',2,'s','project:x','unknown',20,None,None,None,0))
            db.execute('INSERT INTO cost_source_active VALUES(?,?,?,?,?,?,?,?)',('path','active','s',10,'{}','{}',0,0))
            db.execute('INSERT INTO cost_source_work VALUES(?,?,?,?,?)',('path','work',20,'{}','{}'))
            db.executemany('INSERT INTO cost_source_events VALUES(?,?,?)',[('path','active','live'),('path','work','work')]+[('path','old'+str(i),'live') for i in range(800)])
    def tearDown(self):self.tmp.cleanup()
    def drive(self,job,until=None):
        for _ in range(500):
            if until and job.state and job.state['phase']==until:return None
            result=job.step(budget=.025)
            if not result['pending']:return result
        self.fail('maintenance did not terminate')
    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT * FROM untouched').fetchall(),db.execute('SELECT * FROM cost_revision_events ORDER BY id').fetchall(),db.execute('SELECT * FROM cost_source_active').fetchall(),db.execute('SELECT * FROM cost_source_work').fetchall()
    def test_compacts_orphans_preserves_all_records_work_and_sqlite_metadata(self):
        before=self.rows();size=self.path.stat().st_size;job=IndexMaintenance(self.path)
        self.assertEqual(self.drive(job)['state'],'completed');self.assertEqual(before,self.rows())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cost_source_events').fetchone()[0],2)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],17);self.assertEqual(db.execute('PRAGMA application_id').fetchone()[0],123)
        self.assertLess(self.path.stat().st_size,size)
        self.assertTrue(job.file('backup').is_file());self.assertFalse(job.file('retired').exists())
        self.assertEqual(IndexMaintenance(self.path).step()['state'],'not_needed')
    def test_paused_copy_resumes_after_new_instance_and_never_changes_source_early(self):
        original=identity(self.path);job=IndexMaintenance(self.path)
        self.assertTrue(job.step(stop=lambda:True)['pending']);self.assertFalse(job.journal.exists())
        job.step(budget=0);self.assertEqual(identity(self.path),original)
        self.assertEqual(self.drive(IndexMaintenance(self.path))['state'],'completed')
    def test_source_changed_during_copy_restarts_and_preserves_new_record(self):
        job=IndexMaintenance(self.path);job.step(budget=0)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("INSERT INTO untouched VALUES('later',X'11','new')")
        self.drive(job)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM untouched').fetchone()[0],2)
    def test_preview_verifies_without_renaming_or_changing_source(self):
        before=identity(self.path);job=IndexMaintenance(self.path,workspace=self.root/'preview',preview_only=True)
        self.assertEqual(self.drive(job)['state'],'verified_preview');self.assertEqual(identity(self.path),before)
        self.assertTrue(job.file('candidate').exists());self.assertFalse(job.file('retired').exists())
    def test_failed_candidate_rename_restores_original_and_can_retry(self):
        before=self.rows();job=IndexMaintenance(self.path);self.drive(job,until='ready')
        real=os.replace
        def fail(src,dst):
            if Path(src)==job.file('candidate'):raise PermissionError('injected busy')
            return real(src,dst)
        with patch('index_maintenance.os.replace',side_effect=fail):self.assertTrue(job.step()['pending'])
        self.assertEqual(self.rows(),before);self.assertTrue(self.path.exists())
        self.assertEqual(self.drive(job)['state'],'completed')
    def test_crash_between_old_and_new_rename_recovers_original_then_completes(self):
        before=self.rows();job=IndexMaintenance(self.path);self.drive(job,until='ready')
        job.state['phase']='swapping';job.save();os.replace(self.path,job.file('retired'))
        next_job=IndexMaintenance(self.path);self.drive(next_job);self.assertEqual(before,self.rows())
    def test_unknown_layout_is_refused_with_original_untouched(self):
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('CREATE TABLE special(id TEXT PRIMARY KEY) WITHOUT ROWID')
        before=identity(self.path)
        with self.assertRaises(ValueError):IndexMaintenance(self.path).step()
        self.assertEqual(identity(self.path),before)
    def test_bounded_sweep_never_removes_active_or_pending_membership(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            removed=prune_slice(db,limit=7);self.assertLessEqual(removed,7)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cost_source_events WHERE revision IN ('active','work')").fetchone()[0],2)
    def test_table_rowids_and_empty_event_key_are_retained(self):
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("INSERT INTO cost_source_events(rowid,path,revision,event) VALUES(9000,'path','active','')")
        self.drive(IndexMaintenance(self.path))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT rowid FROM cost_source_events WHERE event='' ").fetchone()[0],9000)
    def test_committed_wal_data_is_retained_and_open_writer_defers_swap(self):
        writer=sqlite3.connect(self.path);writer.execute('PRAGMA journal_mode=WAL');writer.execute("INSERT INTO untouched VALUES('wal',X'01','wal row')");writer.commit()
        job=IndexMaintenance(self.path);self.drive(job,until='ready')
        # Windows must not replace an index another connection still owns.
        self.assertTrue(job.step()['pending']);self.assertTrue(self.path.exists());writer.close()
        # Closing the writer changes layout; rebuild from a fresh snapshot.
        self.drive(job)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT note FROM untouched WHERE id='wal'").fetchone()[0],'wal row')
    def test_disk_failure_during_backup_never_replaces_source(self):
        job=IndexMaintenance(self.path);before=self.rows()
        with patch('index_maintenance.shutil.copy2',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.drive(job)
        self.assertEqual(before,self.rows());self.assertFalse(job.file('retired').exists())
        self.drive(IndexMaintenance(self.path));self.assertEqual(before,self.rows())
    def test_changed_verified_copy_is_rejected_before_source_rename(self):
        before=self.rows();job=IndexMaintenance(self.path);self.drive(job,until='ready')
        with closing(sqlite3.connect(job.file('candidate'))) as db,db:db.execute("UPDATE untouched SET note='corrupt'")
        with self.assertRaises(ValueError):job.step()
        self.assertEqual(self.rows(),before);self.assertFalse(job.file('retired').exists())
    def test_transient_journal_replacement_lock_is_retried(self):
        from index_maintenance import atomic
        real=os.replace;calls=[]
        def flaky(src,dst):
            calls.append(1)
            if len(calls)==1:raise PermissionError('brief reader lock')
            return real(src,dst)
        target=self.root/'checkpoint.json'
        with patch('index_maintenance.os.replace',side_effect=flaky):atomic(target,{'saved':True})
        self.assertEqual(json.loads(target.read_text('utf-8')),{'saved':True});self.assertEqual(len(calls),2)
    def test_prebackup_repairs_only_owned_index_and_backup_keeps_same_statistics(self):
        from directory_deploy import backup_data
        new=self.root/'token-usage-source-0123456789abcdef.sqlite3';self.path.rename(new);self.path=new
        before=self.rows();backup=backup_data(self.root,self.root/'install','old')
        self.assertEqual(self.rows(),before)
        proof=json.loads((backup/'backup.json').read_text('utf-8'))
        self.assertEqual(proof['databaseMaintenance'][new.name]['state'],'completed')
        with closing(sqlite3.connect(backup/new.name)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cost_source_events').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT * FROM untouched').fetchall(),before[0])
    def test_postswap_check_failure_restores_original_and_reports_deferred(self):
        from index_maintenance import before_backup
        before=self.rows()
        with patch.object(IndexMaintenance,'complete',side_effect=ValueError('injected final validation')):
            result=before_backup(self.path)
        self.assertEqual(result['state'],'deferred');self.assertEqual(self.rows(),before)
    def test_index_worker_prepare_completes_and_then_is_idle(self):
        from token_calendar import TokenUsageIndex
        index=TokenUsageIndex(self.root/'unused.sqlite3',self.root);index.path=self.path
        for _ in range(500):
            result=index.prepare()
            if not result['pending']:break
        self.assertEqual(result['state'],'completed')
        with patch.object(index._maintenance,'step',side_effect=AssertionError('finished maintenance kept running')):
            self.assertEqual(index.prepare(),result)

if __name__=='__main__':unittest.main()
