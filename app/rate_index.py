"""Budgeted, resumable metadata-only history, using the existing worker/SQLite source."""
import json,time,sqlite3,hashlib
from datetime import datetime,timedelta
from token_rate import RateStore,MetadataCollector
from token_analytics import stamp_of

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
            if path.stat().st_size==offset:next_position=i+1;continue
            collector=MetadataCollector(store);session=path.stem
            if state:
                saved=json.loads(state);session=saved['session'];s=saved['stream']
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
                    if not any(k in line for k in (b'session_meta',b'token_count',b'task_started',b'turn_started',b'task_complete')):continue
                    try:
                        obj=json.loads(line);payload=obj.get('payload');stamp=stamp_of(obj)
                        if not isinstance(payload,dict) or stamp is None:continue
                        if obj.get('type')=='session_meta':
                            session=str(payload.get('id') or session)[:128]
                            collector.streams.setdefault((source,session),dict(water=(0,0,0),turn=None,base=None))
                        elif obj.get('type')=='event_msg':collector.ingest(source,session,payload,stamp)
                    except (ValueError,TypeError,AttributeError,OverflowError):errors+=1
            saved=dict(session=session,stream=collector.streams.get((source,session),dict(water=None,turn=None,base=None)))
            db.execute('INSERT OR REPLACE INTO rate_files VALUES(?,?,?)',(key,offset,json.dumps(saved,separators=(',',':'))))
            if offset<path.stat().st_size and not waiting_tail:pending=True;break
            next_position=i+1
        except (OSError,ValueError,sqlite3.DatabaseError):errors+=1;next_position=i+1
    if next_position>=len(ordered):next_position=0
    db.execute('INSERT OR REPLACE INTO rate_cursor VALUES(1,?)',(next_position,))
    return dict(pending=pending,bytes=scanned,errors=errors)

def snapshot(db,now,progress=None):
    store=migrate(db);today=datetime.fromtimestamp(now).replace(hour=0,minute=0,second=0,microsecond=0);yesterday=today-timedelta(days=1)
    first=db.execute('SELECT MIN(stamp) FROM rate_samples WHERE stamp<=?',(now,)).fetchone()[0]
    start=max(first or yesterday.timestamp(),now-86400*3659)
    daily=store.query(start,now+.001)['bins'];hours=store.query(yesterday.timestamp(),now+.001,bucket='hour')['bins']
    def item(g):return dict(rate=g['task_tokens_per_second'],median_rate=g['task_median_tokens_per_second'],first_token_ms=g['first_token_ms'],samples=g['samples'],valid_samples=g['task_samples'])
    days={g['key']:item(g) for g in daily};groups={g['key']:item(g) for g in hours}
    # RateStore default local timestamps have no zone suffix. Fixed source uses OS local time.
    def hourly(day):return [groups.get(day.replace(hour=h).strftime('%Y-%m-%dT%H')) for h in range(24)]
    return dict(days=days,today=hourly(today),yesterday=hourly(yesterday),yesterday_mean=days.get(yesterday.strftime('%Y-%m-%d')),
                pending=bool((progress or {}).get('pending')),errors=(progress or {}).get('errors',0),metric='task',
                description='输出 Token（含推理）÷ 回合总耗时；含思考、工具和等待时间，不代表纯生成速度')
