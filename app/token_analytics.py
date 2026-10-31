"""Incremental analytics metadata; store identifiers and counters, never prose."""
import hashlib,json,math
from datetime import date,datetime,timedelta
from token_calendar import counter

UNKNOWN='未识别模型'

def migrate(db):
    from quota_workload import migrate as workload_migrate
    workload_migrate(db)
    if db.execute('PRAGMA user_version').fetchone()[0]>=2:return
    existing={r[1] for r in db.execute('PRAGMA table_info(usage)')}
    for name,kind in [('session','TEXT DEFAULT ""'),('model',f'TEXT DEFAULT "{UNKNOWN}"'),('input_tokens','INTEGER'),('output_tokens','INTEGER'),('known','INTEGER DEFAULT 0')]:
        if name not in existing:db.execute(f'ALTER TABLE usage ADD COLUMN {name} {kind}')
    existing={r[1] for r in db.execute('PRAGMA table_info(files)')}
    for name,kind in [('session','TEXT DEFAULT ""'),('model',f'TEXT DEFAULT "{UNKNOWN}"'),('turn','TEXT DEFAULT ""'),('input_water','INTEGER DEFAULT 0'),('output_water','INTEGER DEFAULT 0')]:
        if name not in existing:db.execute(f'ALTER TABLE files ADD COLUMN {name} {kind}')
    db.execute('CREATE TABLE IF NOT EXISTS messages (fingerprint TEXT PRIMARY KEY, stamp REAL, session TEXT, role TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS messages_stamp ON messages(stamp)')
    db.execute('CREATE INDEX IF NOT EXISTS usage_model_stamp ON usage(model,stamp)')
    db.execute('UPDATE files SET offset=0,highwater=0')
    db.execute('PRAGMA user_version=2');db.commit()

def stamp_of(obj):
    try:
        value=datetime.fromisoformat(str(obj.get('timestamp')).replace('Z','+00:00')).timestamp()
        return value if math.isfinite(value) and value>0 else None
    except (ValueError,TypeError,OverflowError):return None

def model_name(value):
    return value[:128] if isinstance(value,str) and value.strip() else None

def message_text(content):
    if isinstance(content,str):return content
    if isinstance(content,list):return '\n'.join(v.get('text','') for v in content if isinstance(v,dict) and isinstance(v.get('text'),str))
    return ''

def scan_file(index,db,path,stop):
    key=str(path.resolve());size=path.stat().st_size
    row=db.execute('SELECT offset,highwater,session,model,turn,input_water,output_water FROM files WHERE path=?',(key,)).fetchone()
    offset,previous,sid,model,turn,pi,po=row or (0,0,path.stem,UNKNOWN,'',0,0)
    if size<offset:offset,previous,sid,model,turn,pi,po=0,0,path.stem,UNKNOWN,'',0,0;index.format_known.pop(key,None)
    import quota_workload as workload
    condition=workload.resume(db,key,offset,pi)
    # The saved offset survives a restart; the in-memory format cache does not.
    # A newly appended tail may contain only progress/completion events that
    # the token scanner deliberately skips. Validate the header independently
    # of whether the file grew, and retry a previous negative after it settles.
    if not index.format_known.get(key):
        try:
            with path.open('rb') as header:meta=json.loads(header.readline(4*1024*1024))
            index.format_known[key]=isinstance(meta,dict) and meta.get('type') in ('session_meta','event_msg','response_item','turn_context')
        except (ValueError,UnicodeError):index.format_known[key]=False
    if size==offset and row:
        return index.format_known[key]
    recognized=index.format_known.get(key,False)
    if not sid:sid=path.stem
    with path.open('rb') as stream:
        stream.seek(offset)
        while not stop():
            line=stream.readline(4*1024*1024)
            from performance_metrics import METRICS
            METRICS.add('token_bytes',bytes_read=len(line))
            if not line:break
            if not line.endswith(b'\n'):
                if len(line)<4*1024*1024:break
                while line and not line.endswith(b'\n') and not stop():line=stream.readline(4*1024*1024)
                if not line.endswith(b'\n'):break
                offset=stream.tell();continue
            offset=stream.tell()
            if not any(k in line for k in (b'token_count',b'turn_context',b'session_meta',b'task_started',b'turn_started',b'user_message',b'agent_message',b'"message"',b'item_completed')):continue
            try:obj=json.loads(line);p=obj.get('payload') or {};kind=obj.get('type');typ=p.get('type')
            except (ValueError,TypeError,AttributeError):continue
            if not isinstance(p,dict):continue
            if kind in ('session_meta','event_msg','response_item','turn_context'):recognized=True
            if kind=='session_meta':
                if isinstance(p.get('id'),str):sid=p['id'][:128]
                model=model_name(p.get('model')) or model
            elif kind=='turn_context':
                model=model_name(p.get('model')) or model
                workload.context(condition,p)
            elif kind=='event_msg' and typ in ('task_started','turn_started'):turn=str(p.get('turn_id') or obj.get('timestamp',''))[:128]
            stamp=stamp_of(obj)
            if stamp is None:continue
            role=text=None
            if kind=='event_msg' and typ in ('user_message','agent_message'):
                role='user' if typ=='user_message' else 'assistant';text=message_text(p.get('message'))
            elif kind=='response_item' and typ=='message' and p.get('role')=='assistant':
                role=p['role'];text=message_text(p.get('content'))
            elif kind=='event_msg' and typ=='item_completed':
                item=p.get('item') or {}
                if isinstance(item,dict) and item.get('type') in ('UserMessage','AgentMessage'):
                    role='user' if item['type']=='UserMessage' else 'assistant';text=message_text(item.get('content'))
            if role and text:
                digest=hashlib.sha256(text.strip().encode()).hexdigest()
                # Same logical message is often emitted as an event and an item.
                identity=json.dumps([turn or obj.get('timestamp'),role,digest],separators=(',',':'))
                fingerprint=hashlib.sha256(identity.encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?)',(fingerprint,stamp,sid,role))
            if kind!='event_msg' or typ!='token_count':continue
            try:
                info=p.get('info') or {};usage=info.get('total_token_usage') or {}
                total=counter(usage.get('total_tokens'));a=counter(usage.get('input_tokens'));b=counter(usage.get('output_tokens'))
                if total is None:
                    if a is None or b is None:continue
                    total=a+b
                model=model_name(p.get('model')) or model_name(info.get('model')) or model
            except (TypeError,AttributeError):continue
            workload.event_context(condition,model,p,info)
            delta=max(0,total-previous);previous=max(previous,total)
            di=max(0,a-pi) if a is not None else None;do=max(0,b-po) if b is not None else None
            if a is not None:pi=max(pi,a)
            if b is not None:po=max(po,b)
            known=di is not None and do is not None and di+do==delta
            cached=workload.observe(condition,usage,di,known)
            if not delta:continue
            identity=json.dumps([obj.get('timestamp'),total,usage.get('input_tokens'),usage.get('output_tokens')],separators=(',',':'))
            fingerprint=hashlib.sha256(identity.encode()).hexdigest()
            db.execute('''INSERT INTO usage (fingerprint,stamp,tokens,session,model,input_tokens,output_tokens,known) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET session=CASE WHEN usage.session='' THEN excluded.session ELSE usage.session END,
                model=CASE WHEN usage.model=? THEN excluded.model ELSE usage.model END,
                input_tokens=CASE WHEN usage.known=0 AND usage.tokens=excluded.tokens THEN excluded.input_tokens ELSE usage.input_tokens END,
                output_tokens=CASE WHEN usage.known=0 AND usage.tokens=excluded.tokens THEN excluded.output_tokens ELSE usage.output_tokens END,
                known=CASE WHEN usage.tokens=excluded.tokens THEN MAX(usage.known,excluded.known) ELSE usage.known END''',
                (fingerprint,stamp,delta,sid,model,di if known else None,do if known else None,int(known),UNKNOWN))
            workload.store(db,fingerprint,model,delta,cached,condition)
    db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?)',(key,offset,previous,sid,model,turn,pi,po))
    workload.save(db,key,offset,condition)
    index.format_known[key]=recognized
    return recognized

def report_snapshot(db,now):
    current=datetime.fromtimestamp(now);end=current.replace(hour=0,minute=0,second=0,microsecond=0);start=end-timedelta(days=1)
    rows=list(db.execute("SELECT date(stamp,'unixepoch','localtime'),model,SUM(tokens),SUM(input_tokens),SUM(output_tokens),MIN(known) FROM usage WHERE stamp<=? GROUP BY 1,2 ORDER BY 1,2",(now,)))
    daily=[dict(day=d,model=m or UNKNOWN,total=t,input=i,output=o,known=bool(k)) for d,m,t,i,o,k in rows]
    model_totals={}
    for r in daily:model_totals[r['model']]=model_totals.get(r['model'],0)+r['total']
    sessions=db.execute("SELECT COUNT(DISTINCT session) FROM usage WHERE stamp<=? AND session!=''",(now,)).fetchone()[0]
    messages=db.execute('SELECT COUNT(*) FROM messages WHERE stamp>=? AND stamp<?',(start.timestamp(),end.timestamp())).fetchone()[0]
    hours=[0]*24
    for h,t in db.execute("SELECT strftime('%H',stamp,'unixepoch','localtime'),SUM(tokens) FROM usage WHERE stamp>=? AND stamp<? GROUP BY 1",(start.timestamp(),end.timestamp())):hours[int(h)]=t
    total=sum(r['total'] for r in daily)
    return dict(day=start.strftime('%Y-%m-%d'),hours=hours,daily_models=daily,
                sessions=sessions,active_days=len({r['day'] for r in daily}),all_total=total,
                favorite_model=max(model_totals,key=model_totals.get) if model_totals else '暂无记录',
                messages=messages,yesterday_total=sum(hours),peak_hour=max(range(24),key=lambda h:hours[h]) if any(hours) else None,
                metadata_incomplete=bool(db.execute("SELECT 1 FROM usage WHERE stamp<=? AND (session='' OR model=?) LIMIT 1",(now,UNKNOWN)).fetchone()))

def model_series(report,period='7d'):
    report=report or {};end=report.get('day',datetime.now().strftime('%Y-%m-%d'))
    last=datetime.strptime(end,'%Y-%m-%d').date();rows=[r for r in report.get('daily_models',[]) if r['day']<=end]
    first=min((r['day'] for r in rows),default=end) if period=='all' else (last-timedelta(days=29 if period=='30d' else 6)).isoformat()
    rows=[r for r in rows if r['day']>=first];totals={}
    first_day=datetime.strptime(first,'%Y-%m-%d').date()
    span=(last-first_day).days+1;step=max(1,math.ceil(span/24)) if period=='all' else 1
    bins=[];cursor=first_day
    while cursor<=last:
        end_day=min(last,cursor+timedelta(days=step-1))
        bins.append(dict(start=cursor.isoformat(),end=end_day.isoformat(),values={},total=0))
        cursor=end_day+timedelta(days=1)
    # Assign each row once. The previous nested scan reformatted two dates for
    # every row in every bin, blocking the GUI on large local histories.
    day_bins={}
    for r in rows:
        m=totals.setdefault(r['model'],dict(model=r['model'],total=0,input=0,output=0,known=True))
        m['total']+=r['total'];m['input']+=r['input'] or 0;m['output']+=r['output'] or 0;m['known']&=r['known']
        day=r['day']
        if day not in day_bins:day_bins[day]=(date.fromisoformat(day)-first_day).days//step
        bucket=bins[day_bins[day]];values=bucket['values']
        values[r['model']]=values.get(r['model'],0)+r['total'];bucket['total']+=r['total']
    models=sorted(totals.values(),key=lambda m:(-m['total'],m['model']));total=sum(m['total'] for m in models)
    return dict(models=models,bins=bins,total=total,start=first,end=end)

def token_analogy(total,index=0):
    from book_reference import analogy
    return analogy(total,index)['sentence']
