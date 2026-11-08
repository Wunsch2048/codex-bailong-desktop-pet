"""UI-independent, metadata-only rate records and weighted daily/hourly queries.

Task duration is NOT generation duration. Never upgrade inferred timings to a
measured generation rate; reasoning output is already included in output_tokens.
"""
import math,sqlite3
from datetime import datetime,timedelta

def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def sample(*,source,session,turn,stamp,input_tokens,output_tokens,reasoning_tokens=0,
           generation_ms=None,task_ms=None,first_token_ms=None,timing_source=''):
    if not all(isinstance(v,str) and 0<len(v)<=256 for v in (source,session,turn)):
        raise ValueError('速率记录缺少稳定来源或回合标识')
    if not number(stamp) or stamp<=0:raise ValueError('速率时间无效')
    for value in (input_tokens,output_tokens,reasoning_tokens):
        if type(value) is not int or not 0<=value<2**53:raise ValueError('Token计数无效')
    if reasoning_tokens>output_tokens:raise ValueError('推理Token不能超过输出Token')
    for value in (generation_ms,task_ms,first_token_ms):
        if value is not None and (not number(value) or value<0):raise ValueError('速率时长无效')
    # Explicit provider duration only; lifecycle/TTFT subtraction is insufficient.
    measured=generation_ms is not None and generation_ms>0 and timing_source=='generation_duration'
    return dict(source=source,session=session,turn=turn,stamp=stamp,input_tokens=input_tokens,
        output_tokens=output_tokens,reasoning_tokens=reasoning_tokens,
        generation_ms=generation_ms if measured else None,task_ms=task_ms,
        first_token_ms=first_token_ms,quality='measured' if measured else 'timing_unavailable')

def completion(payload,usage,*,source,session,stamp):
    """Extract allowlisted fields only. No title, text, command or credentials."""
    if payload.get('type')!='task_complete':return None
    if not isinstance(usage,dict) or type(usage.get('output_tokens')) is not int:return None
    return sample(source=source,session=session,turn=payload.get('turn_id',''),stamp=stamp,
        input_tokens=usage.get('input_tokens'),output_tokens=usage['output_tokens'],
        reasoning_tokens=usage.get('reasoning_output_tokens',0),task_ms=payload.get('duration_ms'),
        first_token_ms=payload.get('time_to_first_token_ms'))

class RateStore:
    """Caller-owned background connection. Does not open existing usage databases."""
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS rate_samples(
            source TEXT,session TEXT,turn TEXT,stamp REAL,input_tokens INTEGER,
            output_tokens INTEGER,reasoning_tokens INTEGER,generation_ms REAL,
            task_ms REAL,first_token_ms REAL,quality TEXT,
            PRIMARY KEY(source,session,turn))''')
        self.db.execute('CREATE INDEX IF NOT EXISTS rate_stamp ON rate_samples(stamp)')
        self.db.commit()
    def close(self):self.db.close()
    @classmethod
    def using(cls,db):
        obj=cls.__new__(cls);obj.db=db;obj.transaction_owned=True
        db.execute('''CREATE TABLE IF NOT EXISTS rate_samples(
            source TEXT,session TEXT,turn TEXT,stamp REAL,input_tokens INTEGER,
            output_tokens INTEGER,reasoning_tokens INTEGER,generation_ms REAL,
            task_ms REAL,first_token_ms REAL,quality TEXT,
            PRIMARY KEY(source,session,turn))''')
        db.execute('CREATE INDEX IF NOT EXISTS rate_stamp ON rate_samples(stamp)')
        return obj
    def put(self,record,inherited=None):
        # Retry/restart duplicate does not count twice. Conflicting counts are
        # rejected, never silently overwrite a previously accepted measurement.
        row=self.db.execute('SELECT input_tokens,output_tokens,reasoning_tokens,generation_ms,task_ms,first_token_ms,quality FROM rate_samples WHERE source=? AND session=? AND turn=?',tuple(record[k] for k in ('source','session','turn'))).fetchone()
        values=tuple(record[k] for k in ('input_tokens','output_tokens','reasoning_tokens','generation_ms','task_ms','first_token_ms','quality'))
        if row is not None:
            if row==values:return False
            if inherited is not None and row[:3]==inherited and row[3:]==values[3:]:
                # Only replace the old, provably zero-based sample from this turn.
                self.db.execute('''UPDATE rate_samples SET input_tokens=?,output_tokens=?,reasoning_tokens=?
                    WHERE source=? AND session=? AND turn=? AND stamp=?''',
                    (*values[:3],record['source'],record['session'],record['turn'],record['stamp']))
                if not getattr(self,'transaction_owned',False):self.db.commit()
                return True
            raise ValueError('同一回合速率记录冲突，保留旧记录')
        self.db.execute('INSERT INTO rate_samples VALUES(?,?,?,?,?,?,?,?,?,?,?)',tuple(record[k] for k in ('source','session','turn','stamp','input_tokens','output_tokens','reasoning_tokens','generation_ms','task_ms','first_token_ms','quality')))
        if not getattr(self,'transaction_owned',False):self.db.commit()
        return True
    def discard_inherited(self,source,session,turn,stamp,counts):
        self.db.execute('''DELETE FROM rate_samples WHERE source=? AND session=? AND turn=? AND stamp=?
            AND input_tokens=? AND output_tokens=? AND reasoning_tokens=?''',(source,session,turn,stamp,*counts))
        if not getattr(self,'transaction_owned',False):self.db.commit()

    def query(self,start,end,*,bucket='day',tz=None):
        if bucket not in ('day','hour') or not number(start) or not number(end) or start>=end:raise ValueError('速率查询范围无效')
        if (end-start)>86400*3660:raise ValueError('速率查询范围过大')
        rows=self.db.execute('SELECT stamp,input_tokens,output_tokens,reasoning_tokens,generation_ms,task_ms,first_token_ms FROM rate_samples WHERE stamp>=? AND stamp<? ORDER BY stamp',(start,end))
        groups={}
        for stamp,inp,out,reason,duration,task,first in rows:
            local=datetime.fromtimestamp(stamp,tz)
            key=local.strftime('%Y-%m-%d' if bucket=='day' else '%Y-%m-%dT%H%z')
            g=groups.setdefault(key,dict(key=key,input_tokens=0,output_tokens=0,reasoning_tokens=0,measured_output=0,generation_ms=0.,task_output=0,task_ms=0.,task_samples=0,first_ms=0.,first_samples=0,samples=0,measured_samples=0,_task_rates=[]))
            g['input_tokens']+=inp;g['output_tokens']+=out;g['reasoning_tokens']+=reason;g['samples']+=1
            if duration is not None and duration>0:
                g['measured_output']+=out;g['generation_ms']+=duration;g['measured_samples']+=1
            if task is not None and task>0:
                g['task_output']+=out;g['task_ms']+=task;g['task_samples']+=1
                g['_task_rates'].append(1000*out/task)
            if first is not None:g['first_ms']+=first;g['first_samples']+=1
        for g in groups.values():
            g['tokens_per_second']=1000*g['measured_output']/g['generation_ms'] if g['generation_ms'] else None
            g['task_tokens_per_second']=1000*g['task_output']/g['task_ms'] if g['task_ms'] else None
            # Each valid completed turn has one vote. Sort the temporary
            # metadata in place; do not persist another table or alter means.
            rates=g.pop('_task_rates');rates.sort();n=len(rates)
            g['task_median_tokens_per_second']=(rates[n//2] if n%2 else (rates[n//2-1]+rates[n//2])/2) if n else None
            g['coverage']=g['measured_samples']/g['samples']
            g['first_token_ms']=g['first_ms']/g['first_samples'] if g['first_samples'] else None
        return dict(bucket=bucket,start=start,end=end,bins=list(groups.values()),
            average_method='sum_output / sum_generation_seconds',task_median_method='median_of_valid_completed_turn_output_per_task_second',assignment='completion_time',
            empty='missing bins mean unknown, not zero',reasoning_included_in_output=True)

def capabilities(*,connected,last_event,now):
    """Local collector liveness, not Internet speed or server reachability."""
    if not all(number(v) for v in (last_event,now)) or now<last_event:status='unknown'
    elif not connected:status='disconnected'
    else:status='observed' if now-last_event<=30 else 'stale'
    return dict(local_stream=status,network='not_measured',generation_timing='requires_explicit_duration',
        historical_backfill=False)

class MetadataCollector:
    """Feed already-decoded metadata from a background monitor, never poll UI.

    A completion needs counters known BEFORE turn start. Attaching midway or a
    counter reset leaves that turn unknown instead of charging all history to it.
    """
    def __init__(self,store):self.store=store;self.streams={}
    def ingest(self,source,session,payload,stamp):
        key=(source,session)
        if key not in self.streams and len(self.streams)>=128:self.streams.pop(next(iter(self.streams)))
        state=self.streams.setdefault(key,dict(water=None,turn=None,base=None))
        kind=payload.get('type')
        if kind=='token_count':
            # Some clients attach a turn ID to usage. Never apply a delayed
            # response from another turn to the active turn's baseline.
            if payload.get('turn_id') and state['turn'] is not None and payload['turn_id']!=state['turn']:
                return dict(recorded=False,reason='mismatched_usage_turn')
            info=payload.get('info') or {}
            usage=info.get('total_token_usage') or {}
            keys=('input_tokens','output_tokens','reasoning_output_tokens')
            values=tuple(usage.get(k) for k in keys)
            if all(type(v) is int and 0<=v<2**53 for v in values) and values[2]<=values[1]:
                old=state['water']
                if old and any(v<prior for v,prior in zip(values,old)):state['base']=None
                if old is None and state.get('continued') and state['turn'] is not None:
                    state['inherited_baseline']=True
                    last=info.get('last_token_usage')
                    recent=tuple(last.get(k) for k in keys) if isinstance(last,dict) else ()
                    if recent and all(type(v) is int and 0<=v<=total for v,total in zip(recent,values)) and recent[2]<=recent[1]:
                        state['base']=tuple(total-v for total,v in zip(values,recent))
                state['water']=values
            else:
                state['base']=None
        elif kind in ('task_started','turn_started'):
            turn=payload.get('turn_id')
            if turn and turn!=state['turn']:state.update(turn=turn,base=state['water'],inherited_baseline=False)
        elif kind in ('task_aborted','turn_aborted','task_failed','turn_failed','task_cancelled','turn_cancelled','task_canceled','turn_canceled'):
            if not payload.get('turn_id') or payload['turn_id']==state['turn']:
                state.update(turn=None,base=None)
            return dict(recorded=False,reason='turn_terminated')
        elif kind=='task_complete':
            if payload.get('turn_id')!=state['turn'] or state['base'] is None or state['water'] is None:
                if payload.get('turn_id')==state['turn']:
                    if state.pop('inherited_baseline',False) and state['water'] is not None and state['turn']:
                        self.store.discard_inherited(source,session,state['turn'],stamp,state['water'])
                    state.update(turn=None,base=None)
                return dict(recorded=False,reason='missing_turn_baseline')
            counts=tuple(a-b for a,b in zip(state['water'],state['base']))
            usage=dict(zip(('input_tokens','output_tokens','reasoning_output_tokens'),counts))
            # Retire before parsing/storing: a duplicate completion arriving
            # after another usage event must not attempt to rewrite this turn.
            inherited=state['water'] if state.pop('inherited_baseline',False) else None
            state.update(turn=None,base=None)
            record=completion(payload,usage,source=source,session=session,stamp=stamp)
            if record is None:return dict(recorded=False,reason='missing_usage')
            inserted=self.store.put(record,inherited) if inherited is not None else self.store.put(record)
            return dict(recorded=inserted,generation_rate_available=False,reason='task_duration_only')
        return dict(recorded=False,reason='awaiting_completion')
