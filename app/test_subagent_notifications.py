"""Forked-history provenance and migration of stuck child notifications."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,sqlite3,tempfile,unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from enhanced_core import ActivityReducer,RolloutTail
from session_read_state import is_subagent_metadata,subagent_sessions,rollout_alias
from status_indicator import StatusIndicator

APP=QApplication.instance() or QApplication([])
PARENT='01a14429-54e3-7461-8c2f-83136516256a'
CHILD='01a15019-01b0-7b61-ab1c-2b91cef1cfb8'

def meta(sid,child=False):
    return dict(type='session_meta',payload=dict(id=sid,session_id=PARENT if child else sid,source={'subagent':{'thread_spawn':{'parent_thread_id':PARENT}}} if child else 'vscode',agent_path='/root/reviewer' if child else None))

def event(typ,turn='turn'):
    return dict(type='event_msg',payload=dict(type=typ,turn_id=turn))


class ChildProvenanceTests(unittest.TestCase):
    def test_inherited_parent_header_cannot_turn_child_into_visible_chat(self):
        reducer=ActivityReducer();sid='rollout-2026-10-19T01-39-38-'+CHILD
        for item in (meta(CHILD,True),meta(PARENT),event('task_started'),event('task_complete')):
            self.assertEqual(reducer.apply(sid,item),[])
        self.assertTrue(reducer.sessions[sid].source_subagent)
        self.assertEqual(reducer.set_compacting(sid,True),[])
        main=reducer.apply(PARENT,event('task_started'))[-1]
        self.assertEqual(main['active'],1)
        self.assertEqual(sum(e['kind']=='complete' for e in reducer.apply(PARENT,event('task_complete'))),1)

    def test_foreign_header_cannot_classify_parent_or_an_unclassified_child(self):
        reducer=ActivityReducer()
        reducer.apply(PARENT,meta(CHILD,True));self.assertFalse(reducer.sessions[PARENT].provenance_known)
        reducer.apply(PARENT,meta(PARENT));self.assertFalse(reducer.sessions[PARENT].source_subagent)
        reducer.apply(PARENT,meta(CHILD,True));self.assertFalse(reducer.sessions[PARENT].source_subagent)
        self.assertTrue(reducer.apply(PARENT,event('task_started')))
        reducer.apply(CHILD,meta(PARENT));self.assertFalse(reducer.sessions[CHILD].provenance_known)
        reducer.apply(CHILD,meta(CHILD,True));self.assertEqual(reducer.apply(CHILD,event('task_started')),[])

    def test_followup_turns_after_startup_and_tail_slice_never_notify_for_child(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'sessions').mkdir()
            path=home/'sessions'/('rollout-test-'+CHILD+'.jsonl')
            # Put the inherited root header in the tail slice, outside the
            # child's own first header, matching the reported real rollout.
            rows=[meta(CHILD,True),dict(type='padding',payload={'text':'x'*520000}),meta(PARENT),event('task_started'),event('task_complete')]
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
            tail=RolloutTail(home);tail.poll()
            for turn in ('followup-1','followup-2'):
                with path.open('a',encoding='utf-8') as stream:
                    for row in (meta(PARENT),event('task_started',turn),event('task_complete',turn)):stream.write(json.dumps(row)+'\n')
                self.assertEqual(tail.poll(),[])
            self.assertTrue(tail.reducer.sessions[path.stem].source_subagent)

    def test_large_own_header_is_read_before_scanning_inherited_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'sessions').mkdir()
            path=home/'sessions'/('rollout-test-'+CHILD+'.jsonl')
            own=meta(CHILD,True);own['payload']['base_instructions']={'text':'x'*600000}
            path.write_text(''.join(json.dumps(row)+'\n' for row in (own,meta(PARENT),event('task_started'),event('task_complete'))),encoding='utf-8')
            tail=RolloutTail(home);tail.poll()
            self.assertTrue(tail.reducer.sessions[path.stem].source_subagent)
            with path.open('a',encoding='utf-8') as stream:
                for row in (event('task_started','followup'),event('task_complete','followup')):stream.write(json.dumps(row)+'\n')
            self.assertEqual(tail.poll(),[])

    def test_edited_root_rollout_uses_the_parent_chat_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'sessions').mkdir()
            path=home/'sessions'/('rollout-2026-10-25T02-10-51-'+PARENT+'_'+CHILD+'.jsonl')
            started=event('task_started');started['payload']['turn_attribution']=dict(turn_trigger='edit_user_message',initiating_agent_path=None,parent_turn_id=None)
            path.write_text(''.join(json.dumps(row)+'\n' for row in (meta(PARENT),started,event('task_complete'))),encoding='utf-8')
            self.assertEqual(rollout_alias(path),PARENT)
            tail=RolloutTail(home);tail.poll()
            self.assertNotIn(path.stem,tail.reducer.sessions)
            self.assertIn(PARENT,tail.reducer.sessions)
            with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(event('task_started','later'))+'\n')
            self.assertTrue(any(e.get('session')==PARENT for e in tail.poll()))

    def test_paginated_rollout_is_not_a_second_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'sessions').mkdir()
            original=home/'sessions'/('rollout-2026-10-25T02-10-50-'+PARENT+'.jsonl')
            page=home/'sessions'/('rollout-2026-10-25T02-10-51-'+PARENT+'_'+CHILD+'.jsonl')
            original.write_text(json.dumps(meta(PARENT))+'\n',encoding='utf-8')
            header=meta(PARENT);header['payload']['history_base']=dict(thread_id=PARENT,end_byte_offset=100)
            page.write_text(json.dumps(header)+'\n',encoding='utf-8')
            self.assertEqual(rollout_alias(page),PARENT)
            tail=RolloutTail(home);tail.poll()
            self.assertEqual(set(tail.reducer.sessions),{original.stem})
            self.assertEqual(tail.by_id[PARENT],page)


class StoredChildReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        self.store=self.home/'task-notifications.json'
        self.db=sqlite3.connect(self.home/'state_5.sqlite')
        self.db.execute('CREATE TABLE threads(id TEXT,source TEXT,agent_path TEXT)')
        self.db.executemany('INSERT INTO threads VALUES(?,?,?)',[
            (PARENT,'vscode',None),(CHILD,json.dumps(meta(CHILD,True)['payload']['source']),'/root/reviewer'),
            ('path-only','vscode','/root/worker'),('main-root','vscode','/root')])
        self.db.commit();self.icons=[]
    def tearDown(self):
        for icon in self.icons:icon.close();icon.deleteLater()
        APP.processEvents();self.db.close();self.tmp.cleanup()
    def restore(self):
        icon=StatusIndicator();self.icons.append(icon);icon.set_store(self.store,home=self.home);return icon
    def test_source_formats_and_root_path_are_distinguished(self):
        self.assertTrue(is_subagent_metadata({'source':'subagent'}))
        self.assertTrue(is_subagent_metadata({'source':json.dumps({'subagent':{}})}))
        self.assertFalse(is_subagent_metadata({'source':'vscode','agent_path':'/root'}))
        self.assertFalse(is_subagent_metadata({'parent_thread_id':PARENT,'source':'vscode'}))
        self.assertEqual(subagent_sessions(self.home,[PARENT,CHILD,'path-only','main-root','missing']),{CHILD,'path-only'})
    def test_restore_removes_all_child_turns_keeps_parent_unread_and_persists_fix(self):
        pending=[[CHILD,'child-1'],[PARENT,'parent-done'],[CHILD,'child-2'],['unknown','unknown-turn']]
        self.store.write_text(json.dumps(dict(unread=pending,seen=pending)),encoding='utf-8')
        icon=self.restore()
        expected=[(PARENT,'parent-done'),('unknown','unknown-turn')]
        self.assertEqual(icon.unread,expected);self.assertEqual(icon.visual(),'attention')
        self.assertEqual(list(icon.seen),[tuple(row) for row in pending])
        self.assertEqual(json.loads(self.store.read_text(encoding='utf-8'))['unread'],[list(row) for row in expected])
        self.assertFalse(icon.notify_complete(dict(session=CHILD,turn='child-2')))
        self.assertEqual(self.restore().unread,expected)
    def test_only_stuck_child_notices_restore_to_idle_without_checkmark(self):
        self.store.write_text(json.dumps(dict(unread=[[CHILD,'done']],seen=[[CHILD,'done']])),encoding='utf-8')
        icon=self.restore();self.assertFalse(icon.unread);self.assertEqual(icon.visual(),'idle')
    def test_blank_turn_cannot_leave_an_unacknowledgeable_notice(self):
        self.store.write_text(json.dumps(dict(unread=[['orphan',''],[PARENT,'done']],seen=[])),encoding='utf-8')
        icon=self.restore()
        self.assertEqual(icon.unread,[(PARENT,'done')])
        self.assertIn(('orphan',''),icon.seen)
        self.assertFalse(icon.notify_complete(dict(session='orphan',turn='')))
        self.assertEqual(json.loads(self.store.read_text(encoding='utf-8'))['unread'],[[PARENT,'done']])
    def test_unavailable_metadata_never_removes_normal_pending_notices(self):
        self.store.write_text(json.dumps(dict(unread=[[PARENT,'done']],seen=[])),encoding='utf-8')
        self.db.execute('DROP TABLE threads');self.db.commit()
        self.assertEqual(self.restore().unread,[(PARENT,'done')])
        missing=self.home/'missing';missing.mkdir()
        self.assertEqual(subagent_sessions(missing,[PARENT]),set())
        self.assertFalse((missing/'state_5.sqlite').exists())


if __name__=='__main__':unittest.main()
