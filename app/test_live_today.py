import hashlib,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from datetime import datetime
from contextlib import closing
from live_today import LiveTodayTotal

def event(total,stamp):
    return dict(timestamp=datetime.fromtimestamp(stamp).astimezone().isoformat(),payload=dict(type='token_count',info=dict(total_token_usage=dict(total_tokens=total,input_tokens=total-10,output_tokens=10))))

class FutureSampleTests(unittest.TestCase):
    def test_future_sample_does_not_raise_counter_baseline(self):
        from unittest.mock import patch
        live=LiveTodayTotal('unused')
        now=1780000000
        with patch('live_today.time.time',return_value=now):
            live.ingest('a',event(100,now-2),historical=True)
            live.ingest('a',event(10000,now+3600))
            live.ingest('a',event(140,now))
        self.assertEqual(live.water['a'],140)
        self.assertEqual(list(live.events.values()),[(now,40)])

class TodayOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'usage.db';self.now=time.time();self.day=datetime.fromtimestamp(self.now).strftime('%Y-%m-%d')
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('CREATE TABLE usage (fingerprint TEXT PRIMARY KEY, stamp REAL)')
        self.live=LiveTodayTotal(self.path);self.live.reconcile(self.base(100,0));self.live.ingest('a',event(100,self.now-3),historical=True)
    def tearDown(self):self.temp.cleanup()
    def base(self,count,rowid):return dict(days={self.day:count},month=self.day[:7],checked=self.now,_usage_rowid=rowid)
    def insert(self,obj):
        u=obj['payload']['info']['total_token_usage'];key=hashlib.sha256(json.dumps([obj['timestamp'],u['total_tokens'],u['input_tokens'],u['output_tokens']],separators=(',',':')).encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('INSERT INTO usage VALUES (?,?)',(key,datetime.fromisoformat(obj['timestamp']).timestamp()))
    def test_later_index_row_does_not_subtract_delta_until_baseline_includes_it(self):
        obj=event(125,self.now-1);self.live.ingest('a',obj);self.assertEqual(self.live.snapshot(self.now)['count'],125)
        self.insert(obj);self.assertEqual(self.live.snapshot(self.now)['count'],125)
        self.live.reconcile(self.base(125,1));self.assertEqual(self.live.snapshot(self.now)['count'],125)
    def test_observer_late_and_copied_log_do_not_double_count(self):
        obj=event(125,self.now-1);self.insert(obj);self.live.reconcile(self.base(125,1));self.live.ingest('a',obj)
        self.live.ingest('copy',event(100,self.now-3),historical=True);self.live.ingest('copy',obj)
        self.assertEqual(self.live.snapshot(self.now)['count'],125)
    def test_unknown_history_and_counter_regression_do_not_spike(self):
        self.live.ingest('unknown',event(999999,self.now-2));self.live.ingest('a',event(20,self.now-2));self.live.ingest('a',event(110,self.now-1))
        self.assertEqual(self.live.snapshot(self.now)['count'],110)
    def test_malformed_events_are_ignored(self):
        for obj in (None,[],dict(payload=[]),dict(payload={'type':'token_count','info':[]}),event(True,self.now),event(-1,self.now)):
            self.live.ingest('a',obj)
        self.assertEqual(self.live.snapshot(self.now)['count'],100)
    def test_missing_database_never_created_and_never_shows_fake_zero(self):
        missing=Path(self.temp.name)/'missing.db';self.live.path=missing;self.live.ingest('a',event(125,self.now-1))
        self.assertIsNone(self.live.snapshot(self.now));self.assertFalse(missing.exists())
    def test_local_day_rollover_drops_old_overlay(self):
        self.live.ingest('a',event(125,self.now-1));tomorrow=datetime.fromtimestamp(self.now).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()+86400
        day=datetime.fromtimestamp(tomorrow).strftime('%Y-%m-%d');self.live.reconcile(dict(days={day:0},month=day[:7],checked=tomorrow,_usage_rowid=0))
        self.assertEqual(self.live.snapshot(tomorrow)['count'],0)
    def test_idle_snapshot_does_not_open_database(self):
        from unittest.mock import patch
        with patch('live_today.sqlite3.connect',side_effect=AssertionError('idle database access')):self.assertEqual(self.live.snapshot(self.now)['count'],100)
    def test_real_index_reconciliation_matches_usage_fingerprints(self):
        from token_calendar import TokenUsageIndex
        home=Path(self.temp.name)/'codex';(home/'sessions').mkdir(parents=True);path=home/'sessions/rollout-test.jsonl';cache=home/'usage.db'
        first=event(100,self.now-3);first['type']='event_msg';path.write_text(json.dumps(first)+'\n',encoding='utf-8')
        index=TokenUsageIndex(cache,home);live=LiveTodayTotal(index.path);live.ingest(str(path),first,historical=True);live.reconcile(index.poll(self.now))
        later=event(125,self.now-1);later['type']='event_msg'
        with path.open('a',encoding='utf-8') as f:f.write(json.dumps(later)+'\n')
        live.ingest(str(path),later);self.assertEqual(live.snapshot(self.now)['count'],125)
        live.reconcile(index.poll(self.now));self.assertEqual(live.snapshot(self.now)['count'],125)

