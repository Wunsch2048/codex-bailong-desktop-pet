import os,sys,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from codex_connection import data_home,find_executable
from session_read_state import seen_completed_turns,read_unread_sessions,session_id
from conversation_roster import ConversationRoster

class DiscoveryTests(unittest.TestCase):
    def test_new_user_without_path_uses_own_codex_cache(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'LOCALAPPDATA':folder,'BAILONG_CODEX':''}),patch('codex_connection.shutil.which',return_value=None):
            exe=Path(folder)/'OpenAI/Codex/bin/new-version/codex.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'test')
            self.assertEqual(Path(find_executable()),exe)
    def test_fresh_store_install_finds_native_resource_not_gui(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'LOCALAPPDATA':folder,'APPDATA':folder,'BAILONG_CODEX':''}),patch('codex_connection.shutil.which',return_value=None):
            root=Path(folder)/'store/app';(root/'resources').mkdir(parents=True)
            (root/'Codex.exe').write_bytes(b'gui');native=root/'resources/codex.exe';native.write_bytes(b'cli')
            with patch('codex_connection.packaged_roots',return_value={root}):self.assertEqual(Path(find_executable()),native)
    def test_custom_home_expands_and_all_adapters_share_it(self):
        from enhanced_core import RolloutTail
        from token_calendar import TokenUsageIndex
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'CODEX_HOME':folder,'BAILONG_CODEX_HOME':''}):
            self.assertEqual(data_home(),Path(folder).resolve());self.assertEqual(RolloutTail().home,data_home());self.assertEqual(TokenUsageIndex(Path(folder)/'index.sqlite').home,data_home())
    def test_missing_override_is_actionable_and_does_not_silently_use_another_cli(self):
        with patch.dict(os.environ,{'BAILONG_CODEX':'Z:/missing/bailong-test-cli.exe'}),patch('codex_connection.shutil.which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'BAILONG_CODEX'):find_executable()
    def test_empty_new_home_is_not_reported_connected(self):
        from enhanced_core import RolloutTail
        with tempfile.TemporaryDirectory() as folder:
            events=RolloutTail(folder).poll();self.assertEqual(events[-1]['state'],'offline');self.assertIn('尚未找到',events[-1]['text'])

class ReadReceiptTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def state(self,ids):
        p=self.home/'.codex-global-state.json';p.write_text(json.dumps({'electron-thread-read-state-v1':dict(version=1,unreadByIdentity={'account':{'local:host':ids,'remote:other':['b']}})}),encoding='utf-8');return p
    def database(self):
        with sqlite3.connect(self.home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE thread_read_receipts(thread_id TEXT,last_published_turn TEXT)');db.executemany('INSERT INTO thread_read_receipts VALUES(?,?)',[('a','turn-a'),('b','turn-b')])
        db.close()
    def test_only_viewed_exact_completed_turn_is_acknowledged_without_writes(self):
        state=self.state(['b']);self.database();before=state.read_bytes();database=(self.home/'state_5.sqlite').read_bytes()
        self.assertEqual(seen_completed_turns(self.home,[('a','turn-a'),('b','turn-b')]),[('a','turn-a')])
        self.assertEqual(state.read_bytes(),before);self.assertEqual((self.home/'state_5.sqlite').read_bytes(),database)
        self.assertFalse(seen_completed_turns(self.home,[('a','new-unpublished-turn')]))
    def test_missing_or_changed_metadata_never_means_all_read(self):
        self.assertIsNone(read_unread_sessions(self.home));self.assertFalse(seen_completed_turns(self.home,[('a','turn')]))
        self.state([]);p=self.home/'.codex-global-state.json';p.write_text('{broken',encoding='utf-8');self.assertIsNone(read_unread_sessions(self.home))
    def test_rollout_file_names_map_to_desktop_thread_identity(self):
        sid='01a143e6-20e5-7843-8da6-ed8bc6ce277b';self.assertEqual(session_id('rollout-2026-10-16T12-00-00-'+sid),sid)
    def test_paginated_desktop_history_restores_named_active_thread_with_legacy_flag_zero(self):
        from session_read_state import active_conversations
        with sqlite3.connect(self.home/'thread_history_1.sqlite') as db:
            db.execute('CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,status TEXT,rollout_ordinal INTEGER)')
            db.executemany('INSERT INTO thread_turns VALUES(?,?,?,?)',[('a','a1','inProgress',1),('b','b1','completed',1),('internal','i1','inProgress',1)])
        db.close()
        with sqlite3.connect(self.home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads(id TEXT,name TEXT,title TEXT,has_user_event INTEGER,archived INTEGER,agent_path TEXT)')
            db.executemany('INSERT INTO threads VALUES(?,?,?,?,?,?)',[('a','会话 A','初始请求',0,0,None),('b','会话 B','',0,0,None),('internal','','',0,0,None)])
        db.close();active=active_conversations(self.home);self.assertEqual([x['session'] for x in active],['a']);self.assertEqual(active[0]['active'],1)

class RosterTests(unittest.TestCase):
    def test_unread_completion_and_running_conversation_take_one_slot_each(self):
        r=ConversationRoster()
        for sid,state in [('a','complete'),('b','working'),('c','thinking')]:r.observe(dict(session=sid,state=state,title=sid))
        chosen,extra=r.selection([('a','turn')]);self.assertEqual([v['session'] for v in chosen],['a','b']);self.assertEqual(extra,1)
        r.observe(dict(session='c',state='working',text='many frequent updates'))
        chosen,_=r.selection([('a','turn')]);self.assertEqual([v['session'] for v in chosen],['a','b'])
        chosen,extra=r.selection([]);self.assertEqual({v['session'] for v in chosen},{'b','c'});self.assertEqual(extra,0)
    def test_overflow_can_cycle_but_never_renders_more_than_two(self):
        r=ConversationRoster()
        for i in range(5):r.observe(dict(session=str(i),state='working'))
        initial,_=r.selection([]);r.cycle();next_page,extra=r.selection([])
        self.assertEqual(len(next_page),2);self.assertEqual(extra,3);self.assertNotEqual([v['session'] for v in initial],[v['session'] for v in next_page])

if __name__=='__main__':unittest.main()
