"""A personal refill must not masquerade as the pending public announcement."""
import unittest
from pathlib import Path
from unittest.mock import patch
from reset_watch import LocalResetEvidence,ResetTracker,locally_reset,reset_has_priority,schedule_key
from reset_presentation import reset_view
from week_cycle import context
NOW=1_800_000_000
class ResetAssociationTests(unittest.TestCase):
 def pending(self,scheduled=NOW+3600):return dict(pending=dict(id='n',announced=NOW-86400,scheduled=scheduled,reset_type='regular',text='公告待确认'))
 def evidence(self,when=NOW,kind='extra',window='一周'):
  e=LocalResetEvidence.__new__(LocalResetEvidence);e.state=dict(reset=dict(observed=when,kind=kind,window=window));e.path=Path('unused-evidence.json');return e
 def test_card_before_public_deadline_keeps_countdown_even_one_second_early(self):
  for due in (NOW+1,NOW+3600,NOW+12*3600):
   e=self.evidence();snap=e.decorate(self.pending(due))
   self.assertTrue(reset_has_priority(snap));self.assertFalse(locally_reset(snap))
   self.assertEqual(reset_view(snap,now=NOW)['phase'],'scheduled')
 def test_natural_and_five_hour_resets_do_not_satisfy_weekly_public_notice(self):
  for kind,window in [('natural','一周'),('extra','5小时')]:
   snap=self.evidence(kind=kind,window=window).decorate(self.pending(NOW-60))
   self.assertTrue(reset_has_priority(snap));self.assertNotEqual(reset_view(snap,now=NOW)['phase'],'local_reset')
 def test_no_announced_deadline_and_next_announcement_cannot_reuse_a_refill(self):
  for change in [dict(scheduled=None),dict(announced=NOW+1,scheduled=NOW-60)]:
   snap=self.pending(NOW-60);snap['pending'].update(change)
   self.assertTrue(reset_has_priority(self.evidence().decorate(snap)))
 def test_late_week_refill_can_demote_local_display_without_claiming_public_cause(self):
  snap=self.evidence().decorate(self.pending(NOW-60));view=reset_view(snap,now=NOW)
  self.assertTrue(locally_reset(snap));self.assertFalse(reset_has_priority(snap))
  self.assertEqual(view['value'],'已补充');self.assertEqual(view['note'],'来源未确认')
  self.assertIn('不能据此认定公告已落实',view['description']);self.assertIsNotNone(snap['pending'])
 def test_old_unscoped_cache_is_not_trusted_and_stale_marker_is_removed(self):
  snap=self.pending();snap['local_reset']=dict(self.evidence().state['reset'],schedule=schedule_key(snap['pending']))
  self.assertFalse(locally_reset(snap));self.assertNotIn('local_reset',self.evidence().decorate(snap))
  self.assertFalse(locally_reset(dict(pending=None,local_reset=dict(scope='account_only'))))
 def test_personal_card_still_starts_real_local_usage_cycle(self):
  e=self.evidence();deadline=NOW+6*86400;e.state={'window':dict(name='一周',remaining=40,reset=deadline,observed=NOW-300)}
  windows=[dict(name='一周',remaining=100,resetsAt=deadline)]
  with patch('desktop_core.atomic_json'):e.observe(windows,NOW,'live',self.pending())
  self.assertEqual(e.state['reset']['kind'],'extra')
  self.assertTrue(reset_has_priority(e.decorate(self.pending())))
  c=context(windows,e.state,NOW,'live');self.assertEqual(c['start_source'],'detected');self.assertEqual(c['start'],NOW)
 def test_public_confirmation_still_clears_notice_independently(self):
  t=ResetTracker.__new__(ResetTracker);t.path=Path('unused-reset-feed.json');t.state={'initialized':False,'seen':[],'schedules':[]}
  pending=self.pending()['pending']
  with patch('desktop_core.atomic_json'):
   t.update(dict(events=[],scheduled=pending),NOW)
   self.assertTrue(reset_has_priority(self.evidence().decorate(t.snapshot)))
   snap,alerts=t.update(dict(events=[dict(pending,announced=NOW+4000)],scheduled=None),NOW+4000)
  self.assertIsNone(snap['pending']);self.assertIsNotNone(snap['latest'])

if __name__=='__main__':unittest.main()
