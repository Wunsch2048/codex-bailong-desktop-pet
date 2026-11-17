"""Budgeted, resumable metadata-only history, using the existing worker/SQLite source."""
import json,time,sqlite3,hashlib
from datetime import datetime,timedelta
from token_rate import RateStore,MetadataCollector
from token_analytics import continuation,stamp_of

MAX_OUTPUT_SAMPLE_GAP=300

def hourly_output(db,start,end):
    """Aggregate verified output deltas over observed session time."""
    previous={};hours={}
    rows=db.execute('''SELECT session,stamp,MAX(output_tokens),MIN(known),COUNT(*)
        FROM usage WHERE stamp>=? AND stamp<=? AND session<>''
        GROUP BY session,stamp ORDER BY stamp''',(start-MAX_OUTPUT_SAMPLE_GAP,end))
    for session,stamp,output,known,count in rows:
        reliable=bool(known and count==1 and output is not None and output>=0)
        prior=previous.get(session)
        previous[session]=(stamp,reliable)
        if not prior or not prior[1] or not reliable:continue
        elapsed=stamp-prior[0]
        if not 0<elapsed<=MAX_OUTPUT_SAMPLE_GAP:continue
        cursor=max(start,prior[0])
        while cursor<stamp:
            local=datetime.fromtimestamp(cursor)
            hour_end=cursor+3600-local.minute*60-local.second-local.microsecond/1e6
            boundary=min(stamp,hour_end)
            seconds=boundary-cursor
            key=local.strftime('%Y-%m-%dT%H')
            total,covered=hours.get(key,(0.,0.))
            hours[key]=(total+output*seconds/elapsed,covered+seconds)
            cursor=boundary
    return {key:dict(rate=total/seconds,sampled_seconds=seconds)
            for key,(total,seconds) in hours.items()}

def migrate(db):
    store=RateStore.using(db)
    db.execute('CREATE TABLE IF NOT EXISTS rate_files(path TEXT PRIMARY KEY,offset INTEGER,state TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS rate_cursor(id INTEGER PRIMARY KEY,position INTEGER)')
    return store

def update(db,files,stop=lambda:False,budget=.15):
    store=migrate(db);source='local';deadline=time.monotonic()+budget;pending=False;scanned=0;errors=0
    # New/recent files first for immediate feedback; cursor rows make history resumable.
    ordered=sorted(files,key=lambda p:str(p),reverse=True)
    saved=db.execute('SELECT position FROM rate_cursor WHERE id=1').fetchone();position=(saved[0] if saved else 0)%max(1,len(ordered))
    next_position=position
    for i in range(position,len(ordered)):
        if stop() or time.monotonic()>=deadline:pending=True;break
        path=ordered[i];next_position=i
        key=str(path);row=db.execute('SELECT offset,state FROM rate_files WHERE path=?',(key,)).fetchone()
        offset,state=row if row else (0,None)
        try:
            if path.stat().st_size<offset:offset,state=0,None
            saved=json.loads(state) if state else None
            if saved and not saved.get('segment_checked'):
                with path.open('rb') as header:
                    try:continued=continuation(json.loads(header.readline(4*1024*1024)))
                    except (ValueError,UnicodeError):continued=False
                if continued:offset,saved=0,None
                else:
                    saved['segment_checked']=True
                    db.execute('UPDATE rate_files SET state=? WHERE path=?',(json.dumps(saved,separators=(',',':')),key))
            if path.stat().st_size==offset:next_position=i+1;continue
            collector=MetadataCollector(store);session=path.stem
            if saved:
                session=saved['session'];s=saved['stream']
                for k in ('water','base'):
                    if s.get(k) is not None:s[k]=tuple(s[k])
                collector.streams[(source,session)]=s
            with path.open('rb') as stream:
                waiting_tail=False
                stream.seek(offset)
                while not stop() and time.monotonic()<deadline:
                    start=stream.tell();line=stream.readline(4*1024*1024)
                    if not line:break
                    if not line.endswith(b'\n'):
                        if len(line)<4*1024*1024:stream.seek(start);waiting_tail=True;break
                        # Oversized records are not parsed or retained; drain in bounded chunks.
                        while line and not line.endswith(b'\n') and not stop() and time.monotonic()<deadline:line=stream.readline(4*1024*1024)
                        if not line.endswith(b'\n'):stream.seek(start);break
                        offset=stream.tell();continue
                    offset=stream.tell();scanned+=len(line)
                    if not any(k in line for k in (b'session_meta',b'token_count',b'task_',b'turn_')):continue
                    try:
                        obj=json.loads(line);payload=obj.get('payload');stamp=stamp_of(obj)
                        if not isinstance(payload,dict) or stamp is None:continue
                        if obj.get('type')=='session_meta':
                            session=str(payload.get('id') or session)[:128]
                            continued=continuation(obj)
                            collector.streams.setdefault((source,session),dict(water=None if continued else (0,0,0),
                                                                               turn=None,base=None,continued=continued))
                        elif obj.get('type')=='event_msg':collector.ingest(source,session,payload,stamp)
                    except (ValueError,TypeError,AttributeError,OverflowError):errors+=1
            saved=dict(session=session,segment_checked=True,stream=collector.streams.get((source,session),dict(water=None,turn=None,base=None)))
            db.execute('INSERT OR REPLACE INTO rate_files VALUES(?,?,?)',(key,offset,json.dumps(saved,separators=(',',':'))))
            if offset<path.stat().st_size and not waiting_tail:pending=True;break
            next_position=i+1
        except (OSError,ValueError,sqlite3.DatabaseError):errors+=1;next_position=i+1
    if next_position>=len(ordered):next_position=0
    db.execute('INSERT OR REPLACE INTO rate_cursor VALUES(1,?)',(next_position,))
    return dict(pending=pending,bytes=scanned,errors=errors)

def snapshot(db,now,progress=None,*,include_output=False):
    store=migrate(db);today=datetime.fromtimestamp(now).replace(hour=0,minute=0,second=0,microsecond=0);yesterday=today-timedelta(days=1)
    first=db.execute('SELECT MIN(stamp) FROM rate_samples WHERE stamp<=?',(now,)).fetchone()[0]
    start=max(first or yesterday.timestamp(),now-86400*3659)
    daily=store.query(start,now+.001)['bins'];hours=store.query(yesterday.timestamp(),now+.001,bucket='hour')['bins']
    def item(g):return dict(rate=g['task_tokens_per_second'],median_rate=g['task_median_tokens_per_second'],first_token_ms=g['first_token_ms'],
                            samples=g['samples'],valid_samples=g['task_samples'],output=g['task_output'],duration_ms=g['task_ms'])
    days={g['key']:item(g) for g in daily};groups={g['key']:item(g) for g in hours}
    output=hourly_output(db,yesterday.timestamp(),now) if include_output else {}
    # RateStore default local timestamps have no zone suffix. Fixed source uses OS local time.
    def hourly(day,values=groups):return [values.get(day.replace(hour=h).strftime('%Y-%m-%dT%H')) for h in range(24)]
    return dict(days=days,today=hourly(today),yesterday=hourly(yesterday),yesterday_mean=days.get(yesterday.strftime('%Y-%m-%d')),
                today_output=hourly(today,output),yesterday_output=hourly(yesterday,output),
                pending=bool((progress or {}).get('pending')),errors=(progress or {}).get('errors',0),metric='task',
                description='输出 Token（含推理）÷ 回合总耗时；含思考、工具和等待时间，不代表纯生成速度')
