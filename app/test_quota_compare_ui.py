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
 def test_history_chart_is_above_capacity_comparison_and_visible_at_open(self):
  from PySide6.QtWidgets import QScrollArea,QWidget
  from PySide6.QtCore import QPoint
  area=QScrollArea();area.setWidgetResizable(True);area.resize(246,360)
  v=QuotaCompareView();area.setWidget(v);v.set_snapshot({'quota_history':{'cycles':[
   row(drop=69,comparison_block='使用条件记录不完整，暂不判断涨跌'),
   row(id='old',closed=True,estimated_total=120000000),
  ]}});area.show();APP.processEvents()
  try:
   metrics=v.findChild(QWidget,'quota_current_section');comparison=v.findChild(QWidget,'quota_comparison_section')
   plot_top=v.plot.mapTo(v,QPoint(0,0)).y()
   self.assertGreater(plot_top,metrics.geometry().bottom())
   self.assertLess(v.plot.mapTo(v,QPoint(0,v.plot.height())).y(),comparison.y())
   self.assertLessEqual(v.plot.mapTo(area.viewport(),QPoint(0,v.plot.height())).y(),area.viewport().height())
   self.assertEqual(area.verticalScrollBar().value(),0)
  finally:area.close();area.deleteLater();APP.processEvents()
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
  self.assertEqual(m['title'],'同条件涨跌暂不能判断');self.assertIn('记录不完整',m['reason']);self.assertIsNotNone(c['estimated_total'])
 def test_mixed_workload_shows_reference_without_claiming_same_conditions(self):
  v=QuotaCompareView()
  v.set_snapshot({'quota_history':{'cycles':[
   row(drop=35,comparison_block='模型使用结构不同，暂不判断涨跌'),
   row(id='old',closed=True,estimated_total=120000000,start=1791695200),
   row(id='older',closed=True,estimated_total=140000000,start=1791090400),
  ]}})
  self.assertEqual(v.current_capacity.text(),'100.00M')
  self.assertEqual(v.previous_capacity.text(),'120.00M')
  self.assertEqual(v.comparison.text(),'同条件涨跌暂不能判断')
  self.assertIn('-16.7%',v.reference.text());self.assertIn('按各自用法',v.reference.text())
  self.assertFalse(v.reference.isHidden())
  v.previous.click()
  self.assertEqual(v.current_capacity.text(),'120.00M')
  self.assertEqual(v.previous_capacity.text(),'140.00M')
  self.assertIn('-14.3%',v.reference.text())
  v.previous.click()
  self.assertTrue(v.capacity_pair.isHidden())
  self.assertTrue(v.reference.isHidden())
  v.close()
 def test_missing_fields_are_explained_without_promising_future_calibration(self):
  c=row(drop=69,comparison_block='使用条件记录不完整，暂不判断涨跌',workload=dict(missing=['速度档位','计数条件']))
  previous=row(workload=dict(missing=['推理档位']))
  m=cycle_messages(c,{},previous)
  for field in ('速度档位','推理档位','缓存用量'):self.assertIn(field,m['reason'])
  self.assertNotIn('待校准',m['title']);self.assertNotIn('等待',m['reason'])
 def test_reference_does_not_leak_across_pending_invalid_or_strict_views(self):
  v=QuotaCompareView()
  try:
   cycles=[row(drop=69),row(id='old',closed=True,estimated_total=120000000)]
   v.set_snapshot(dict(quota_history=dict(cycles=cycles)))
   self.assertFalse(v.reference.isHidden())
   v.set_snapshot(dict(quota_history=dict(cycles=cycles,pending=True)))
   self.assertTrue(v.reference.isHidden())
   cycles[0]=row(drop=69,change=-16.7)
   v.set_snapshot(dict(quota_history=dict(cycles=cycles)))
   self.assertTrue(v.reference.isHidden());self.assertIn('推测容量减少',v.comparison.text())
   cycles[0]=row(drop=69,estimated_total=None)
   v.set_snapshot(dict(quota_history=dict(cycles=cycles)))
   self.assertTrue(v.reference.isHidden());self.assertEqual(v.current_capacity.text(),'—')
  finally:v.close()
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
