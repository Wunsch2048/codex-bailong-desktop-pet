import os,json,time,tempfile,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QEvent
from compact_bubble import CompactBubble
from quota_summary import QuotaSummary
from token_charts import TokenPlot
from enhanced_core import RolloutTail
from session_read_state import seen_completed_turns
APP=QApplication.instance() or QApplication([])
def drain():APP.processEvents();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

class StatusCostTests(unittest.TestCase):
 def setUp(self):self.b=CompactBubble();self.b.show();drain()
 def tearDown(self):self.b.close();self.b.deleteLater();drain()
 def test_status_updates_preserve_static_cards_and_running_chart_clock(self):
  self.b.windows=[dict(name='一周',remaining=80,resetsAt=time.time()+3600)];self.b.redraw();drain()
  quota=self.b.findChildren(QuotaSummary)[0];plot=self.b.findChildren(TokenPlot)[0]
  plot.reveal.prepare();plot.reveal.start();plot.reveal.animation.setCurrentTime(120)
  for i in range(12):self.b.message('状态变化 '+str(i))
  self.assertIs(self.b.findChildren(QuotaSummary)[0],quota);self.assertIs(self.b.findChildren(TokenPlot)[0],plot)
  self.assertEqual(plot.reveal.animation.currentTime(),120)
 def test_independent_rows_keep_second_row_and_static_cards(self):
  for sid in ('a','b'):self.b.roster.observe(dict(session=sid,state='working',display='正在编辑文件'))
  self.b.redraw();drain();second=self.b.status_view.rows['b'];quota=self.b.findChildren(QuotaSummary)[0]
  self.b.roster.observe(dict(session='a',state='working',display='运行了命令'));self.b.refresh_status()
  self.assertIs(self.b.status_view.rows['b'],second);self.assertEqual(second.current,'正在编辑文件')
  self.assertIs(self.b.findChildren(QuotaSummary)[0],quota)
 def test_mini_status_does_not_recreate_island_controls(self):
  self.b.set_mode('mini');self.b.size_transition.complete();drain();island=self.b.island
  self.b.status_indicator.observe(dict(state='working',active=1));self.b.refresh_status();drain()
  self.assertIs(self.b.island,island)
 def test_editor_not_rebuilt_by_status_only_changes(self):
  editor=QWidget();self.b.show_page('settings',editor);self.b.size_transition.complete();drain()
  with patch.object(self.b,'_redraw_editor',wraps=self.b._redraw_editor) as rebuild:
   self.b.message('状态变化');self.assertEqual(rebuild.call_count,0)
  self.assertIs(self.b.editor_stack.currentWidget(),editor)

class BackgroundCostTests(unittest.TestCase):
 def test_unchanged_logs_are_not_opened_and_new_append_is_still_live(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);(home/'sessions').mkdir();path=home/'sessions/rollout-one.jsonl';path.write_text('')
   tail=RolloutTail(home);tail.poll();original=Path.open
   with patch.object(Path,'open',autospec=True,side_effect=original) as opened:
    tail.poll();tail.poll();self.assertEqual(opened.call_count,0)
   path.write_text(json.dumps({'type':'event_msg','payload':{'type':'task_started','turn_id':'new'}})+'\n')
   events=tail.poll();self.assertTrue(any(e.get('state')=='thinking' for e in events))
 def test_no_pending_notifications_means_no_codex_read_metadata_access(self):
  with patch('session_read_state.read_unread_sessions',side_effect=AssertionError('unexpected read')):
   self.assertEqual(seen_completed_turns(Path('missing'),[]),[])
 def test_runtime_report_writes_once_without_intermediate_readback(self):
  from desktop import DesktopPet
  import enhanced,desktop
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);patches=[patch(m+'.'+k,root/('settings.json' if k=='CONFIG' else '')) for m in ('enhanced','desktop') for k in ('CONFIG','STATE_DIR')]
   for p in patches:p.start()
   pet=DesktopPet(monitor=False)
   try:
    for timer in (pet.tick,pet.motion_timer,pet.status_timer,pet.diagnostic_timer):timer.stop()
    with patch('enhanced.save_json',wraps=enhanced.save_json) as base,patch('desktop.atomic_json',wraps=desktop.atomic_json) as final:
     pet.record_state();self.assertEqual(base.call_count,0);self.assertEqual(final.call_count,1)
    value=json.loads((root/'runtime.json').read_text(encoding='utf-8'));self.assertIn('status_icon_unread',value);self.assertIn('bubble_bounds',value)
   finally:
    pet.close();drain()
    for p in reversed(patches):p.stop()

if __name__=='__main__':unittest.main()
