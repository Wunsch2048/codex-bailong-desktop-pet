import json
import tempfile
import unittest
from pathlib import Path
from enhanced_core import ActivityReducer, RolloutTail, clean_text, motion_step, windows_from_limits

def event(typ, **fields):
    return {'type':'event_msg','timestamp':'2026-10-18T10:00:00Z','payload':{'type':typ,**fields}}

class CoreTests(unittest.TestCase):
    def test_complete_only_explicit_once_and_no_tool_failure_complete(self):
        r=ActivityReducer()
        r.apply('a',event('task_started',turn_id='1'))
        r.apply('a',event('item_completed',item={'type':'CommandExecution','status':'failed'}))
        self.assertFalse(r.sessions['a'].done)
        result=r.apply('a',event('task_complete'))
        self.assertEqual(sum(e['kind']=='complete' for e in result),1)
        self.assertEqual(r.apply('a',event('task_complete')),[])
        r.apply('a',event('task_started',turn_id='2'))
        self.assertEqual(sum(e['kind']=='complete' for e in r.apply('a',event('task_complete'))),1)

    def test_ipc_terminal_turn_rejects_late_log_and_compaction(self):
        r=ActivityReducer();r.apply('s',event('task_started',turn_id='old'))
        self.assertEqual(r.terminate('s','interrupted','old')[-1]['state'],'interrupted')
        self.assertEqual(r.apply('s',{'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'text':'late'}]}}),[])
        self.assertEqual(r.apply('s',event('task_complete')),[])
        self.assertEqual(r.set_compacting('s',True,'old'),[])
        self.assertEqual(r.sessions['s'].state,'interrupted')
        self.assertEqual(r.apply('s',event('task_started',turn_id='old')),[])
        self.assertEqual(r.apply('s',event('task_started',turn_id='new'))[-1]['state'],'thinking')
        self.assertEqual(r.sessions['s'].closed_turn,'')

    def test_final_message_does_not_falsely_claim_task_complete(self):
        r=ActivityReducer()
        r.apply('s',event('task_started'))
        result=r.apply('s',event('item_completed',item={'type':'AgentMessage','phase':'final_answer','content':[{'text':'完成回复'}]}))
        self.assertFalse(any(e['kind']=='complete' for e in result))

    def test_historical_completions_are_silent_and_live_append_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'sessions';folder.mkdir()
            file=folder/'rollout-test.jsonl'
            file.write_text('\n'.join(json.dumps(e) for e in [event('task_started'),event('task_complete')])+'\n')
            tail=RolloutTail(tmp)
            self.assertFalse(any(e['kind']=='complete' for e in tail.poll()))
            with file.open('a') as f:
                f.write(json.dumps(event('task_started',turn_id='new'))+'\n')
                f.write(json.dumps(event('task_complete'))+'\n')
            self.assertEqual(sum(e['kind']=='complete' for e in tail.poll()),1)
            self.assertFalse(any(e['kind']=='complete' for e in tail.poll()))

    def test_partial_json_waits_for_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'sessions';folder.mkdir()
            file=folder/'rollout-test.jsonl';file.write_text('')
            tail=RolloutTail(tmp);tail.poll()
            line=json.dumps(event('task_started',turn_id='x'))
            file.write_text(line[:15]);self.assertEqual(tail.poll(),[])
            with file.open('a') as f:f.write(line[15:]+'\n')
            self.assertTrue(any(e.get('state')=='thinking' for e in tail.poll()))

    def test_parallel_sessions_and_interruption(self):
        r=ActivityReducer()
        r.apply('a',event('task_started'));r.apply('b',event('task_started'))
        last=r.apply('a',event('task_complete'))[-1]
        self.assertEqual(last['active'],1)
        self.assertFalse(any(e['kind']=='complete' for e in r.apply('b',event('turn_aborted'))))

    def test_acknowledgement_marks_only_actual_live_user_messages(self):
        r=ActivityReducer()
        self.assertFalse(r.apply('a',event('task_started',turn_id='1'))[-1]['user_message'])
        self.assertTrue(r.apply('a',event('user_message',message='继续'))[-1]['user_message'])
        self.assertTrue(r.apply('a',event('item_completed',item={'type':'UserMessage','content':[{'text':'回复'}]}))[-1]['user_message'])
        self.assertTrue(r.apply('a',{'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':'回复'}]}})[-1]['user_message'])
        self.assertFalse(r.apply('a',event('item_completed',item={'type':'AgentMessage','content':[{'text':'用户已回复'}]}))[-1]['user_message'])
        self.assertEqual(r.apply('a',event('user_message',message='历史'),historical=True),[])

    def test_quota_spellings_and_invalid_values(self):
        a=windows_from_limits({'primary':{'used_percent':23,'window_minutes':300}})
        b=windows_from_limits({'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':23,'windowDurationMins':300}}}})
        self.assertEqual(a,b);self.assertEqual(a[0]['remaining'],77)
        self.assertEqual(windows_from_limits({'primary':{'usedPercent':float('nan'),'windowDurationMins':300}}),[])
        self.assertEqual(windows_from_limits({'primary':{'usedPercent':120,'windowDurationMins':300}}),[])

    def test_motion_clamped_and_smooth(self):
        x,y,done=motion_step(50,50,1000,-50,40,20,(0,0,100,100))
        self.assertLessEqual(((x-50)**2+(y-50)**2)**.5,4.001)
        for _ in range(100):x,y,done=motion_step(x,y,1000,-50,40,.1,(0,0,100,100))
        self.assertEqual((x,y,done),(100,0,True))

    def test_no_hidden_reasoning_and_basic_credential_mask(self):
        r=ActivityReducer();r.apply('a',event('task_started'))
        result=r.apply('a',{'type':'response_item','payload':{'type':'reasoning','summary':'DO NOT DISPLAY'}})
        self.assertNotIn('DO NOT DISPLAY',str(result))
        self.assertNotIn('sk-1234567890123456',clean_text('key sk-1234567890123456'))

if __name__=='__main__':unittest.main()
