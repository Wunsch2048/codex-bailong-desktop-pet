import os,json,sqlite3,tempfile,time,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch,Mock
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtGui import QTextCursor
from activity_targets import ActivityTargets
from enhanced_core import Session,RolloutTail
from session_read_state import conversation_names,ReadAcknowledgements
from log_catalog import LogCatalog
from status_indicator import StatusIndicator
from chat_window import ChatWindow
from performance_metrics import Metrics
APP=QApplication.instance() or QApplication([])
def sid(i):return f'00000000-0000-4000-8000-{i:012d}'
def row(kind,**args):return json.dumps(dict(type='event_msg',payload=dict(type=kind,**args)))+'\n'

class TargetTests(unittest.TestCase):
    def test_five_parallel_tasks_all_get_ipc_and_names_among_200_history(self):
        now=[0];t=ActivityTargets(lambda:now[0]);sessions={sid(i):Session(done=i>=5,updated=i) for i in range(205)}
        t.sync(sessions,[(sid(204),'old')],[sid(3)]);seen=set();names=set()
        for _ in range(8):
            ids=t.ipc_targets();self.assertLessEqual(len(ids),4);seen.update(ids);names.update(t.choose('names',128));now[0]+=8.1
        self.assertTrue({sid(i) for i in range(5)}<=seen);self.assertIn(sid(204),seen);self.assertEqual(names,set(sessions))
    def test_lease_is_stable_with_spare_idle_slots_and_slow_task_not_expired(self):
        now=[0];t=ActivityTargets(lambda:now[0]);sessions={sid(i):Session(done=i!=0) for i in range(10)}
        t.sync(sessions);a=t.ipc_targets();now[0]=1;t.sync(sessions);self.assertEqual(t.ipc_targets(),a)
        now[0]=28801;t.sync(sessions);self.assertIn(sid(0),t.pinned())
    def test_history_bounded_but_unread_active_and_children_have_distinct_lifetimes(self):
        t=ActivityTargets();sessions={sid(i):Session(done=i>=5) for i in range(1000)};sessions[sid(999)].source_subagent=True
        t.sync(sessions,[(sid(500),'t')]);self.assertNotIn(sid(999),t.entries);self.assertIn(sid(500),t.pinned());self.assertLessEqual(len(t.entries),262)
    def test_names_over_128_include_renamed_and_archived_thread(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);db=sqlite3.connect(home/'state_5.sqlite');db.execute('CREATE TABLE threads(id,name,title)')
            db.executemany('INSERT INTO threads VALUES(?,?,?)',[(sid(i),'名称'+str(i),'原名') for i in range(205)]);db.commit();db.close()
            names=conversation_names(home,[sid(i) for i in range(205)]);self.assertEqual(len(names),205);self.assertEqual(names[sid(204)],'名称204')
            db=sqlite3.connect(home/'state_5.sqlite');db.execute('UPDATE threads SET name=? WHERE id=?',('改名',sid(204)));db.commit();db.close()
            self.assertEqual(conversation_names(home,[sid(204)])[sid(204)],'改名')
    def test_database_seed_filters_child_source_even_without_agent_path(self):
        from session_read_state import active_conversations
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);db=sqlite3.connect(home/'thread_history_1.sqlite');db.execute('CREATE TABLE thread_turns(thread_id,turn_id,status,rollout_ordinal)');db.executemany('INSERT INTO thread_turns VALUES (?,?,?,?)',[(sid(i),'t','inProgress',1) for i in (1,2)]);db.commit();db.close()
            db=sqlite3.connect(home/'state_5.sqlite');db.execute('CREATE TABLE threads(id,name,title,has_user_event,archived,agent_path,source)');db.executemany('INSERT INTO threads VALUES (?,?,?,?,?,?,?)',[(sid(1),'主会话','',1,0,'/root','vscode'),(sid(2),'子会话','',1,0,None,json.dumps({'subagent':{}}))]);db.commit();db.close()
            self.assertEqual([e['session'] for e in active_conversations(home)],[sid(1)])
    def test_rotation_does_not_end_compaction_and_next_snapshot_can_end_it(self):
        from codex_live_status import LifecycleProjection
        from test_live_compaction import snapshot,SID,DECODER
        import msgspec
        out=[];p=LifecycleProjection(lambda *v:out.append(v))
        p.accept(DECODER.decode(msgspec.json.encode(snapshot(compact=True))),{SID});p.forget(SID,clear=False)
        self.assertEqual(len(out),1);p.accept(DECODER.decode(msgspec.json.encode(snapshot(compact=False))),{SID});self.assertEqual(out[-1][1],False)
    def test_ui_retains_all_active_but_only_displays_two(self):
        from conversation_roster import ConversationRoster
        r=ConversationRoster()
        for i in range(205):r.observe(dict(session=sid(i),state='working'))
        chosen,extra=r.selection([]);self.assertEqual(len(chosen),2);self.assertEqual(extra,203)
    def test_unread_backlog_does_not_delay_five_active_targets_for_minutes(self):
        now=[0];t=ActivityTargets(lambda:now[0]);sessions={sid(i):Session(done=i>=5) for i in range(205)}
        t.sync(sessions,[(sid(i),'t') for i in range(5,205)]);active=set()
        for _ in range(2):active.update(t.ipc_targets());now[0]+=8.1
        self.assertTrue({sid(i) for i in range(5)}<=active)

class LogTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);(self.home/'sessions').mkdir()
    def tearDown(self):self.temp.cleanup()
    def log(self,i,child=False):
        p=self.home/'sessions'/('rollout-'+sid(i)+'.jsonl')
        p.write_text(json.dumps(dict(type='session_meta',payload=dict(id=sid(i),source={'subagent':{}} if child else 'vscode')))+'\n'+row('task_started',turn_id='t'),encoding='utf-8');return p
    def test_five_slow_tasks_survive_many_child_logs_and_finish_once(self):
        parents=[self.log(i) for i in range(5)];tail=RolloutTail(self.home);tail.poll()
        for i in range(5,70):self.log(i,True)
        tail.last_scan=0;tail.poll();tail.poll();tail.poll()
        events=[]
        for p in parents:
            with p.open('a') as out:out.write(row('task_complete'))
        events+=tail.poll();events+=tail.poll()
        self.assertEqual(len([e for e in events if e['kind']=='complete']),5)
        self.assertFalse(any(tail.reducer.sessions[e['session']].source_subagent for e in events if e.get('session')))
    def test_archive_move_preserves_offset_and_does_not_replay_old_turn(self):
        p=self.log(1);tail=RolloutTail(self.home);tail.poll();a=self.home/'archived_sessions';a.mkdir();p2=a/p.name;p.rename(p2)
        tail.last_scan=0;self.assertFalse(any(e['kind']=='complete' for e in tail.poll()))
        with p2.open('a') as out:out.write(row('task_complete'))
        self.assertEqual(len([e for e in tail.poll() if e['kind']=='complete']),1)
    def test_db_seed_and_log_alias_become_one_identity(self):
        self.log(1);tail=RolloutTail(self.home);tail.reducer.sessions[sid(1)]=Session(done=False,turn='t');tail.set_pins([sid(1)]);tail.poll()
        self.assertEqual(len(tail.reducer.sessions),1)
    def test_new_task_seeded_from_database_is_live_after_initial_discovery(self):
        tail=RolloutTail(self.home);tail.poll();p=self.log(1)
        tail.reducer.sessions[sid(1)]=Session(done=False,turn='t');tail.set_pins([sid(1)])
        with p.open('a') as out:out.write(row('task_complete'))
        tail.last_scan=0;self.assertEqual(len([e for e in tail.poll() if e['kind']=='complete']),1)
    def test_inherited_old_turn_in_new_file_is_silent_but_new_append_is_live(self):
        tail=RolloutTail(self.home);tail.poll();p=self.log(1)
        old=[dict(type='event_msg',timestamp='2020-01-01T00:00:00Z',payload=dict(type=kind,turn_id='past')) for kind in ('task_started','task_complete')]
        p.write_text(''.join(json.dumps(v)+'\n' for v in old));tail.last_scan=0
        self.assertFalse(any(e['kind']=='complete' for e in tail.poll()))
        with p.open('a') as out:out.write(row('task_started',turn_id='new')+row('task_complete'))
        self.assertEqual(len([e for e in tail.poll() if e['kind']=='complete']),1)
    def test_directory_cache_catches_changes_and_full_fallback_after_sleep(self):
        c=LogCatalog(self.home);c.discover(now=0);folder=self.home/'sessions';before=folder.stat().st_mtime_ns;p=self.log(1)
        # NTFS may coalesce immediately adjacent directory timestamps. Make the
        # fixture's change explicit instead of depending on wall-clock precision.
        os.utime(folder,ns=(before+1_000_000_000,before+1_000_000_000))
        self.assertIn(p,c.discover(now=1,check=True))
        old=c.last_full;c.discover(now=100);self.assertGreater(c.last_full,old)
    def test_imported_archive_is_history_and_never_notifies(self):
        tail=RolloutTail(self.home);tail.poll();archive=self.home/'archived_sessions';archive.mkdir()
        (archive/('rollout-'+sid(99)+'.jsonl')).write_text(row('task_started',turn_id='past')+row('task_complete'))
        tail.last_scan=0;self.assertFalse(any(e['kind']=='complete' for e in tail.poll()))
    def test_cached_idle_never_reenumerates_files_and_append_still_detected(self):
        p=self.log(1);tail=RolloutTail(self.home);tail.poll()
        with patch('log_catalog.os.walk',side_effect=AssertionError('idle full scan')):
            tail.last_scan=0;tail.poll()
            with p.open('a') as out:out.write(row('task_complete'))
            self.assertEqual(len([e for e in tail.poll() if e['kind']=='complete']),1)

class CompletionTests(unittest.TestCase):
    def test_200_unread_survive_restart_and_old_seen_survives_memory_eviction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'notices.json';a=StatusIndicator();a.set_store(p)
            for i in range(205):self.assertTrue(a.notify_complete(dict(session=sid(i),turn='t')))
            a.acknowledge(sid(0));b=StatusIndicator();b.set_store(p)
            self.assertEqual(len(b.unread),204);self.assertFalse(b.notify_complete(dict(session=sid(0),turn='t')))
            self.assertTrue(b.notify_complete(dict(session=sid(0),turn='next')));a.deleteLater();b.deleteLater();APP.processEvents()
    def test_unknown_read_evidence_does_not_clear_large_pending_set(self):
        with tempfile.TemporaryDirectory() as d:
            a=ReadAcknowledgements();pending=[(sid(i),'t') for i in range(205)]
            self.assertEqual(a.poll(d,pending,now=28800),[])
    def test_exact_read_receipts_cover_more_than_128_and_leave_one_unread(self):
        with tempfile.TemporaryDirectory() as d:
            h=Path(d);(h/'.codex-global-state.json').write_text(json.dumps({'electron-thread-read-state-v1':dict(version=1,unreadByIdentity={'user':{'local:host':[sid(1)]}})}))
            db=sqlite3.connect(h/'state_5.sqlite');db.execute('CREATE TABLE thread_read_receipts(thread_id,last_published_turn)');db.executemany('INSERT INTO thread_read_receipts VALUES (?,?)',[(sid(i),'t') for i in range(205)]);db.commit();db.close()
            pending=[(sid(i),'t') for i in range(205)];a=ReadAcknowledgements();self.assertEqual(a.poll(h,pending,now=0),[])
            seen=a.poll(h,pending,now=4.1);self.assertEqual(len(seen),204);self.assertNotIn((sid(1),'t'),seen)

class StreamTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        class Pet(QWidget):
            settings={};manifest={}
            def save_settings(self):pass
        self.pet=Pet();self.chat=ChatWindow(self.pet,self.temp.name);self.chat.show();APP.processEvents()
        self.chat.session['messages']=[dict(role='user',content='历史文字\n'*1000)];self.chat.busy=True;self.stream=Mock();self.chat.stream=self.stream;self.chat.render()
    def tearDown(self):
        self.chat.stream=None;self.chat.busy=False;self.chat.stop();self.chat.close();self.chat.deleteLater();self.pet.deleteLater();APP.processEvents();self.temp.cleanup()
    def test_300_deltas_are_coalesced_without_full_reset_or_losing_selection(self):
        c=self.chat.transcript.textCursor();c.setPosition(5);c.setPosition(15,QTextCursor.MoveMode.KeepAnchor);self.chat.transcript.setTextCursor(c);selected=c.selectedText();self.chat.transcript.verticalScrollBar().setValue(0)
        with patch.object(self.chat.transcript,'setPlainText',wraps=self.chat.transcript.setPlainText) as reset:
            for _ in range(300):self.chat.on_delta(self.stream,'追加')
            self.chat.flush_stream();reset.assert_not_called()
        self.assertEqual(self.chat.transcript.textCursor().selectedText(),selected);self.assertEqual(self.chat.transcript.verticalScrollBar().value(),0)
        self.assertTrue(self.chat.transcript.toPlainText().endswith('追加'*300))
    def test_done_before_timer_flush_does_not_lose_or_duplicate_tail(self):
        self.chat.on_delta(self.stream,'完整回复');self.chat.on_done(self.stream,'完整回复')
        self.assertEqual(self.chat.transcript.toPlainText().count('完整回复'),1);self.assertFalse(self.chat.stream_timer.isActive())
    def test_stop_and_late_delta_never_resurrect_cancelled_reply(self):
        self.chat.on_delta(self.stream,'未完成');self.chat.stop();self.chat.on_delta(self.stream,'迟到');self.chat.flush_stream()
        self.assertNotIn('未完成',self.chat.transcript.toPlainText());self.assertNotIn('迟到',self.chat.transcript.toPlainText())
    def test_profiling_disabled_by_default_and_contains_only_aggregates(self):
        m=Metrics(False);m.add('paint');self.assertEqual(m.snapshot(),{})
        m=Metrics(True)
        with m.span('paint'):pass
        self.assertEqual(set(m.snapshot()['paint']),{'calls','totalMs','maxMs','bytes'})

if __name__=='__main__':unittest.main()
