import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QAbstractAnimation
from compact_bubble import StatusScroller
from enhanced_core import ActivityReducer
from conversation_roster import ConversationRoster,title_keywords
from session_read_state import conversation_names
import tempfile,sqlite3
from pathlib import Path
APP=QApplication.instance() or QApplication([])
RUNNING=QAbstractAnimation.State.Running

def response(typ,**fields):return {'type':'response_item','payload':{'type':typ,**fields}}

class IndependentRowsTests(unittest.TestCase):
    def setUp(self):
        self.v=StatusScroller(248);self.v.show();APP.processEvents()
        self.v.set_conversations([('a','正在运行命令'),('b','正在编辑文件')])
    def tearDown(self):self.v.close();self.v.deleteLater();APP.processEvents()
    def test_only_changed_session_scrolls_and_bursts_coalesce_per_row(self):
        v=self.v;a,b=v.rows['a'],v.rows['b']
        v.set_conversations([('a','运行了命令'),('b','正在编辑文件')])
        self.assertEqual(a.animation.state(),RUNNING);self.assertNotEqual(b.animation.state(),RUNNING)
        a.animation.setCurrentTime(120)
        v.set_conversations([('a','正在查找资料'),('b','正在编辑文件')])
        self.assertEqual(a.animation.currentTime(),120);self.assertEqual(a.pending,'正在查找资料')
        self.assertEqual(b.current,'正在编辑文件');self.assertIsNone(b.pending)
        v.set_conversations([('a','正在查找资料'),('b','编辑了文件')])
        self.assertEqual(a.animation.currentTime(),120);self.assertEqual(b.animation.state(),RUNNING)
        a.animation.setCurrentTime(300);APP.processEvents()
        self.assertEqual(a.incoming,'正在查找资料');self.assertEqual(b.incoming,'编辑了文件')
    def test_removing_first_session_moves_second_without_replaying_its_text(self):
        v=self.v;b=v.rows['b'];self.assertEqual(b.y(),v.line_height)
        v.set_conversations([('b','正在编辑文件')])
        self.assertEqual(v.animation.state(),RUNNING);self.assertNotEqual(b.animation.state(),RUNNING)
        v.animation.setCurrentTime(150)
        self.assertTrue(0<b.y()<v.line_height);self.assertTrue(v.line_height<v.height()<v.line_height*2)
        v.animation.setCurrentTime(300);self.assertEqual(b.y(),0);self.assertEqual(v.height(),v.line_height)
    def test_reordering_uses_session_identity_not_slot(self):
        v=self.v;a,b=v.rows['a'],v.rows['b']
        v.set_conversations([('b','正在编辑文件'),('a','正在运行命令')],extra=3)
        v.animation.setCurrentTime(300)
        self.assertIs(v.rows['a'],a);self.assertIs(v.rows['b'],b)
        self.assertEqual(b.y(),0);self.assertEqual(a.y(),v.line_height)
        self.assertNotEqual(a.animation.state(),RUNNING);self.assertNotEqual(b.animation.state(),RUNNING)
        self.assertEqual(a.width(),218)

class ConversationIdentityTests(unittest.TestCase):
    def test_actual_name_wins_over_new_prompt_and_refreshes_on_rename(self):
        r=ConversationRoster();self.assertTrue(r.update_names({'a':'白龙桌宠状态栏'}));self.assertFalse(r.update_names({'a':'白龙桌宠状态栏'}))
        r.observe(dict(session='a',state='working',title='请运行测试',display='运行了命令'))
        self.assertEqual(r.items['a']['title'],'白龙桌宠状态栏')
        self.assertTrue(r.update_names({'a':'白龙桌宠 UI'}))
        self.assertEqual(r.items['a']['title'],'白龙桌宠 UI')
    def test_names_use_desktop_name_then_title_without_creating_missing_store(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d)
            self.assertEqual(conversation_names(home,['a']),{});self.assertFalse((home/'state_5.sqlite').exists())
            db=sqlite3.connect(home/'state_5.sqlite');db.execute('CREATE TABLE threads(id TEXT,name TEXT,title TEXT)')
            db.executemany('INSERT INTO threads VALUES(?,?,?)',[('a','实际对话名','首次提示词'),('b',None,'已有标题'),('c','无关对话','无关')]);db.commit();db.close()
            self.assertEqual(conversation_names(home,['a','b']),{'a':'实际对话名','b':'已有标题'})
    def test_title_stays_fixed_and_completion_has_its_own_background(self):
        v=StatusScroller(248);v.show();APP.processEvents()
        meta={'a':dict(title='白龙桌宠',state='working'),'b':dict(title='额度统计',state='complete')}
        v.set_conversations([('a','正在编辑文件'),('b','已完成')],metadata=meta)
        a,b=v.rows['a'],v.rows['b'];title=a.short_title
        self.assertEqual(title,'白龙桌宠');self.assertTrue(b.completed);self.assertFalse(a.completed)
        v.set_conversations([('a','运行了命令'),('b','已完成')],metadata=meta)
        self.assertEqual(a.short_title,title);self.assertEqual(a.animation.state(),RUNNING);self.assertNotEqual(b.animation.state(),RUNNING)
        self.assertTrue(a.text_left()>0);self.assertIn('白龙桌宠',v.accessibleName())
        v.close();v.deleteLater();APP.processEvents()
    def test_keyword_collision_remains_distinguishable(self):
        self.assertEqual(title_keywords('帮我优化一下白龙气泡，处理一下'),'白龙气泡')
        v=StatusScroller(248);v.show();APP.processEvents()
        meta={'one':dict(title='白龙气泡，调整名称'),'two':dict(title='白龙气泡，修复更新')}
        v.set_conversations([('one','执行中'),('two','执行中')],extra=4,metadata=meta)
        self.assertNotEqual(v.rows['one'].short_title,v.rows['two'].short_title)
        for row in v.rows.values():self.assertLessEqual(row.title_width,round(row.width()*.42))
        v.close();v.deleteLater();APP.processEvents()

class OperationSummaryTests(unittest.TestCase):
    def setUp(self):
        self.r=ActivityReducer();self.r.apply('s',{'type':'event_msg','payload':{'type':'task_started'}})
    def test_real_batched_operations_and_public_commentary(self):
        event=self.r.apply('s',response('custom_tool_call',name='functions.exec',call_id='1',input="await tools.apply_patch('private');await tools.exec_command({cmd:'secret'})"))[-1]
        self.assertEqual(event['display'],'正在编辑文件 · 正在运行命令')
        event=self.r.apply('s',response('custom_tool_call_output',call_id='1',output='result'))[-1]
        self.assertEqual(event['display'],'编辑了文件 · 运行了命令')
        event=self.r.apply('s',response('message',role='assistant',content=[{'text':'很长的进度说明'*50}]))[-1]
        self.assertEqual(event['display'],'编辑了文件 · 运行了命令')
        self.assertNotIn('secret',event['display'])
        final=self.r.apply('s',response('message',role='assistant',phase='final_answer',content=[{'text':'完成'}]))[-1]
        self.assertEqual(final['display'],'正在整理回复')
    def test_unmatched_output_does_not_invent_operation(self):
        self.assertEqual(self.r.apply('s',response('function_call_output',call_id='unknown',output='done')),[])
    def test_failed_item_does_not_claim_success_and_sessions_are_separate(self):
        event=self.r.apply('s',{'type':'event_msg','payload':{'type':'item_completed','item':{'type':'FileChange','status':'failed'}}})[-1]
        self.assertEqual(event['display'],'编辑了文件 · 未成功')
        self.r.apply('other',response('function_call',name='web.search_query',call_id='2'))
        self.assertEqual(self.r.sessions['s'].display,event['display'])

if __name__=='__main__':unittest.main()
