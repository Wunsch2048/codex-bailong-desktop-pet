"""Semantic/UI regressions for estimate versus history-comparison gates."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from quota_compare_ui import QuotaCompareView,cycle_messages
APP=QApplication.instance() or QApplication([])
def row(**changes):
 c=dict(id='now',start=1792300000,end=1792890000,kind='natural',closed=False,remaining=85,used=15000000,estimated_total=100000000,per_percent=1000000,complete=True,fresh=True,drop=15,plan='pro',model='gpt-6.1-sol',model_share=.9,output_share=.2,distinct_readings=3,change=None)
 c.update(changes);return c
class QuotaComparePresentationTests(unittest.TestCase):
 def test_five_points_estimates_and_twenty_points_compare_have_distinct_purposes(self):
  c=row(drop=2,estimated_total=None,per_percent=None);m=cycle_messages(c,{})
  self.assertIn('3 个百分点可估算总量',m['estimate']);self.assertIn('18 个百分点',m['reason']);self.assertIn('总量变化',m['title'])
  m=cycle_messages(row(),{});self.assertIn('5 个百分点',m['reason']);self.assertNotIn('可比较',m['reason']);self.assertTrue(m['show_coverage'])
 def test_coverage_alone_does_not_claim_comparison_is_ready(self):
  m=cycle_messages(row(drop=20,distinct_readings=2),{});self.assertIn('读数不足',m['title'])
  m=cycle_messages(row(drop=20,model_share=.6),{});self.assertIn('分散',m['title'])
 def test_closed_cycle_does_not_tell_user_to_consume_more_past_quota(self):
  m=cycle_messages(row(closed=True),{});self.assertNotIn('再观察',m['reason']);self.assertIn('不能用于历史对比',m['reason'])
 def test_restricted_stale_corrected_and_missing_plan_have_specific_states(self):
  for changes,expected in [({'complete':False},'受限'),({'fresh':False},'最新额度'),({'rise_pending':True,'estimated_total':None},'待确认'),({'corrected':True},'回升'),({'plan':''},'套餐')]:
   m=cycle_messages(row(**changes),{});self.assertIn(expected,m['title']);self.assertFalse(m['show_coverage'])
 def test_real_change_is_labeled_as_estimate_not_official_quota(self):
  m=cycle_messages(row(drop=35,change=-30,baseline_count=2),{})
  self.assertIn('推测容量减少 30.0%',m['title']);self.assertIn('上一周期',m['reason']);self.assertNotIn('前 2 轮',m['reason']);self.assertFalse(m['show_coverage'])
 def test_workload_block_preserves_capacity_and_does_not_show_old_change(self):
  c=row(drop=35,change=-25,comparison_block='使用条件记录不完整，暂不判断涨跌')
  m=cycle_messages(c,{})
  self.assertEqual(m['title'],'使用条件不可比');self.assertIn('仍按本轮用法保留',m['reason']);self.assertIsNotNone(c['estimated_total'])
 def test_disclosure_selection_and_hover_preserve_view_geometry(self):
  v=QuotaCompareView();v.setFixedWidth(246);v.set_snapshot({'quota_history':{'cycles':[row(),row(id='old',closed=True,start=1791695200)]}});v.show();APP.processEvents()
  try:
   self.assertEqual(v.coverage.value(),150);self.assertTrue(v.rules.isHidden());self.assertTrue(v.estimate_hint.isHidden())
   v.rules_button.click();APP.processEvents();self.assertTrue(v.explanation.isVisible());self.assertEqual(v.explanation.geometry(),v.rect());self.assertIn('5 个百分点',v.note.text())
   v.explanation.back.click();APP.processEvents();self.assertTrue(v.rules.isHidden());self.assertFalse(v.rules_button.isChecked())
   before=v.sizeHint();v.show_plot_readout('10/18 已用 15M / 推测 100M');APP.processEvents();self.assertEqual(v.sizeHint(),before)
   v.show_plot_readout('');self.assertEqual(v.readout.text(),'历史周期')
   v.previous.click();self.assertEqual(v.selected_id,'old');self.assertIn('不能用于历史对比',v.comparison_reason.text())
  finally:v.close()
if __name__=='__main__':unittest.main()
