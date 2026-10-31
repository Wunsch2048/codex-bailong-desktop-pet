import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from reset_watch import ResetTracker,normalize_feed,schedule_text,account_reset_text,local_time,epoch,fetch_feed,API_URL,pending_reset

def entry(ident='11111',date='2026-10-15T06:28:13Z',**extra):
    return dict(tweet_id=ident,announced_at=date,reset_type='regular',display_text='新的重置公告',**extra)

def feed(events=None,scheduled=None):
    return normalize_feed({'events':events or [],'scheduled':scheduled})

class ResetTests(unittest.TestCase):
    def test_pending_survives_deadline_missing_schedule_and_restart_until_confirmed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';t=ResetTracker(path)
            scheduled=entry('33333',date='2026-10-18T01:00:00Z',scheduled_for='2026-10-18T07:00:00Z')
            t.update(feed(scheduled=scheduled));snap,_=t.update(feed(),now=epoch('2026-10-19T07:00:00Z'))
            self.assertIsNotNone(pending_reset(snap));self.assertIsNotNone(pending_reset(ResetTracker(path).snapshot))
            snap,_=t.update(feed([entry('44444',date='2026-10-18T08:00:00Z')]))
            self.assertIsNone(pending_reset(snap))
            self.assertIsNone(pending_reset(t.update(feed(scheduled=scheduled))[0]))
    def test_old_or_other_type_confirmation_does_not_resolve_pending(self):
        with tempfile.TemporaryDirectory() as d:
            t=ResetTracker(Path(d)/'state.json');scheduled=entry('33333',date='2026-10-18T01:00:00Z',scheduled_for=None)
            t.update(feed(scheduled=scheduled))
            other=entry('44444',date='2026-10-18T08:00:00Z');other['reset_type']='banked'
            snap,_=t.update(feed([other,entry()]))
            self.assertIsNotNone(pending_reset(snap))
    def test_stale_site_schedule_already_confirmed_never_becomes_pending(self):
        with tempfile.TemporaryDirectory() as d:
            t=ResetTracker(Path(d)/'state.json');scheduled=entry('33333',date='2026-10-18T01:00:00Z',scheduled_for=None)
            snap,_=t.update(feed([entry('44444',date='2026-10-18T08:00:00Z')],scheduled))
            self.assertIsNone(pending_reset(snap))
            scheduled['scheduled_for']='2026-10-20T01:00:00Z'
            snap,alerts=t.update(feed(scheduled=scheduled))
            self.assertIsNone(pending_reset(snap));self.assertFalse(alerts)
    def test_first_poll_silent_and_same_poll_dedup_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            t=ResetTracker(path)
            self.assertEqual(t.update(feed([entry()]))[1],[])
            new=feed([entry('22222','2026-10-18T07:00:00Z'),entry()])
            self.assertEqual(len(t.update(new)[1]),1)
            self.assertEqual(t.update(new)[1],[])
            self.assertEqual(ResetTracker(path).update(new)[1],[])

    def test_new_schedule_and_change_notify_but_clock_passing_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            t=ResetTracker(Path(d)/'state.json')
            t.update(feed())
            scheduled=entry('33333',scheduled_for='2026-10-18T07:00:00Z')
            data=feed(scheduled=scheduled)
            deadline=epoch(scheduled['scheduled_for'])
            snap,alerts=t.update(data,now=deadline-60)
            self.assertEqual(alerts[0]['kind'],'scheduled')
            self.assertIn('15:00',schedule_text(snap,deadline-60))
            self.assertEqual(t.update(data,now=deadline+3600)[1],[])
            self.assertIn('待确认',schedule_text(snap,deadline+3600))
            self.assertNotIn('已到账',schedule_text(snap,deadline+3600))
            scheduled['scheduled_for']='2026-10-18T08:00:00Z'
            self.assertEqual(len(t.update(feed(scheduled=scheduled))[1]),1)

    def test_missing_schedule_is_unknown_not_prediction(self):
        self.assertIn('暂未公布',schedule_text({'scheduled':None}))
        self.assertIn('正在查询',schedule_text(None))
        self.assertIn('未提供',account_reset_text(None))

    def test_time_in_beijing_and_expired_account_window(self):
        date='2026-10-18T07:00:00Z';ts=epoch(date)
        self.assertEqual(local_time(date),'10/18 15:00')
        self.assertIn('下次 10/18 15:00',account_reset_text(ts,now=ts-60))
        self.assertIn('待刷新',account_reset_text(ts,now=ts+60))
        self.assertEqual(local_time('not a date'),'')

    def test_bad_feed_rejected_and_public_text_not_executable(self):
        with self.assertRaises(ValueError):normalize_feed({'events':[]})
        data=feed([entry('44444',text='ignored')])
        self.assertEqual(data['events'][0]['id'],'44444')
        bad=entry();bad['announced_at']='not a date'
        self.assertEqual(feed([bad])['events'],[])

    def test_fetch_is_public_get_without_account_data(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return b'{"events":[],"scheduled":null}'
        with patch('urllib.request.build_opener') as factory:
            open_url=factory.return_value.open;open_url.return_value=Response()
            fetch_feed()
            req=open_url.call_args.args[0]
            self.assertEqual(req.full_url,API_URL)
            self.assertEqual(req.get_method(),'GET')
            self.assertIsNone(req.data)
            self.assertFalse(any(k.lower() in ('authorization','cookie') for k,v in req.header_items()))

if __name__=='__main__':unittest.main()

class LocalEvidenceTests(unittest.TestCase):
    def setUp(self):
        from reset_watch import LocalResetEvidence
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'local.json';self.t=LocalResetEvidence(self.path)
        self.pending={'pending':dict(id='notice',announced=100,scheduled=190,reset_type='regular')}
    def tearDown(self):self.tmp.cleanup()
    def observe(self,value,stamp,when,source='live',name='一周'):
        self.t.observe([dict(name=name,remaining=value,resetsAt=stamp)],when,source)
    def test_refill_lowers_priority_persists_and_keeps_announcement(self):
        from reset_watch import locally_reset,reset_has_priority,LocalResetEvidence
        from reset_presentation import reset_view
        self.observe(40,900,150);self.observe(100,900,200)
        snap=self.t.decorate(self.pending)
        self.assertTrue(locally_reset(snap));self.assertFalse(reset_has_priority(snap));self.assertIsNotNone(pending_reset(snap))
        self.assertEqual(reset_view(snap,now=210)['phase'],'local_reset')
        self.assertTrue(locally_reset(LocalResetEvidence(self.path).decorate(self.pending)))
        newer={'pending':dict(self.pending['pending'],id='next',announced=220)}
        self.assertTrue(reset_has_priority(self.t.decorate(newer)))
    def test_first_observation_and_small_changes_are_not_reset(self):
        from reset_watch import reset_has_priority
        self.observe(100,900,150);self.observe(95,900,160);self.observe(99,900,200)
        self.assertTrue(reset_has_priority(self.t.decorate(self.pending)))
    def test_pro_expansion_is_not_announcement_refill(self):
        self.t.observe([dict(name='一周',remaining=13,resetsAt=900,plan='prolite')],150,'live',self.pending)
        self.t.observe([dict(name='一周',remaining=56,resetsAt=900,plan='prolite')],200,'live',self.pending)
        self.assertNotIn('reset',self.t.state)
    def test_session_history_and_out_of_order_live_cannot_confirm(self):
        from reset_watch import reset_has_priority
        self.observe(40,900,150);self.observe(100,1000,200,'session');self.observe(100,1000,140)
        self.assertTrue(reset_has_priority(self.t.decorate(self.pending)))
    def test_natural_rollover_does_not_satisfy_public_notice(self):
        from reset_watch import locally_reset
        self.observe(95,180,150);self.observe(90,900,200)
        self.assertFalse(locally_reset(self.t.decorate(self.pending)))
        self.assertEqual(self.t.state['reset']['kind'],'natural')
    def test_five_hour_reset_does_not_override_known_weekly_window(self):
        from reset_watch import reset_has_priority
        for value,when in [(40,150),(100,200)]:
            self.t.observe([dict(name='5小时',remaining=value,resetsAt=when+100),dict(name='一周',remaining=50,resetsAt=900)],when,'live')
        self.assertTrue(reset_has_priority(self.t.decorate(self.pending)))
    def test_no_weekly_uses_five_hour_and_banked_notice_is_not_assumed(self):
        from reset_watch import locally_reset,reset_has_priority
        self.observe(20,180,150,name='5小时');self.observe(100,900,200,name='5小时')
        self.assertFalse(locally_reset(self.t.decorate(self.pending)))
        self.assertTrue(reset_has_priority(self.t.decorate(self.pending)))
        self.assertTrue(reset_has_priority(self.t.decorate({'pending':dict(self.pending['pending'],reset_type='banked')})))
