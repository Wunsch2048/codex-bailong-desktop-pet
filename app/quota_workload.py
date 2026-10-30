"""Quota comparability metadata collected by the existing Token scanner.

No prices/assumed subscription weights, extra log scans or historical rewrites.
Unknown context stays unknown; the raw capacity estimate remains available.
"""
import json
import math

VERSION=1
SPEEDS=('standard','default','priority','fast','ultrafast','flex')
EFFORTS=('none','minimal','low','medium','high','xhigh','max','ultra')


def migrate(db):
    db.execute('CREATE TABLE IF NOT EXISTS quota_workload_files(path TEXT PRIMARY KEY,offset INTEGER,state TEXT)')
    db.execute('''CREATE TABLE IF NOT EXISTS quota_workload_events(
        fingerprint TEXT PRIMARY KEY,model TEXT,tokens INTEGER,cached INTEGER,speed TEXT,effort TEXT)''')


def resume(db,path,offset,input_water):
    row=db.execute('SELECT offset,state FROM quota_workload_files WHERE path=?',(path,)).fetchone()
    if row and row[0]==offset:
        try:return json.loads(row[1])
        except (ValueError,TypeError):pass
    return dict(cached=0 if offset==0 and input_water==0 else None,speed='',effort='')


def label(value,allowed):
    return value if isinstance(value,str) and value in allowed else ''


def context(state,p):
    # A new turn can change either setting. Never carry the last turn's tier
    # across a missing field, or infer current/historical speed from config.toml.
    state['speed']=label(p.get('service_tier'),SPEEDS)
    state['effort']=label(p.get('effort') or p.get('reasoning_effort'),EFFORTS)
    state['model']=p.get('model') if isinstance(p.get('model'),str) else ''


def event_context(state,model,p,info):
    if state.get('model')!=model:
        state.update(model=model,speed='',effort='')
    for source in (info,p):
        if 'service_tier' in source:state['speed']=label(source['service_tier'],SPEEDS)
        if 'effort' in source or 'reasoning_effort' in source:
            state['effort']=label(source.get('effort') or source.get('reasoning_effort'),EFFORTS)


def observe(state,usage,input_delta,known):
    value=usage.get('cached_input_tokens');previous=state.get('cached')
    valid=isinstance(value,int) and not isinstance(value,bool) and value>=0
    state['cached']=value if valid else None
    delta=value-previous if valid and isinstance(previous,int) else None
    return delta if known and delta is not None and 0<=delta<=input_delta else None


def store(db,key,model,tokens,cached,state):
    value=(model,tokens,cached,state.get('speed',''),state.get('effort',''))
    old=db.execute('SELECT model,tokens,cached,speed,effort FROM quota_workload_events WHERE fingerprint=?',(key,)).fetchone()
    if old:
        if old[1]<0:return  # A conflicting duplicate cannot regain confidence.
        if old[:2]!=value[:2] or any(a not in (None,'') and b not in (None,'') and a!=b for a,b in zip(old[2:],value[2:])):
            value=(model,-1,None,'','')
        else:value=old[:2]+tuple(a if a not in (None,'') else b for a,b in zip(old[2:],value[2:]))
    db.execute('INSERT OR REPLACE INTO quota_workload_events VALUES(?,?,?,?,?,?)',(key,*value))


def save(db,path,offset,state):
    db.execute('INSERT OR REPLACE INTO quota_workload_files VALUES(?,?,?)',(path,offset,json.dumps(state,separators=(',',':'))))


def profile(db,start,end):
    result=dict(version=VERSION,complete=False,models={},settings={},tokens=0)
    columns={r[1] for r in db.execute('PRAGMA table_info(usage)')}
    if 'fingerprint' not in columns or not db.execute("SELECT 1 FROM sqlite_master WHERE name='quota_workload_events'").fetchone():return result
    # Aggregate in SQLite; no event arrays are sent to the GUI or kept per frame.
    rows=db.execute('''SELECT u.model,w.speed,w.effort,SUM(u.tokens),SUM(u.input_tokens),SUM(u.output_tokens),SUM(w.cached),
        MIN(CASE WHEN u.known=1 AND w.model=u.model AND w.tokens=u.tokens AND w.cached>=0 AND w.cached<=u.input_tokens
          AND u.input_tokens+u.output_tokens=u.tokens THEN 1 ELSE 0 END)
        FROM usage u LEFT JOIN quota_workload_events w ON w.fingerprint=u.fingerprint
        WHERE u.stamp>? AND u.stamp<=? GROUP BY u.model,w.speed,w.effort''',(start,end)).fetchall()
    if not rows:return result
    complete=True;missing=set()
    for model,speed,effort,tokens,inputs,outputs,cached,known in rows:
        result['tokens']+=tokens;complete &= bool(known and speed and effort)
        if not known:missing.add('计数条件')
        if not speed:missing.add('速度档位')
        if not effort:missing.add('推理档位')
        m=result['models'].setdefault(model,dict(tokens=0,input=0,output=0,cached=0))
        for key,value in [('tokens',tokens),('input',inputs),('output',outputs),('cached',cached)]:m[key]+=value or 0
        result['settings'][json.dumps([model,speed,effort],separators=(',',':'))]=tokens
    result['complete']=bool(complete and result['tokens']>0)
    result['missing']=sorted(missing)
    return result


def mismatch(current,previous):
    """Conservative similarity gate, never a claim of official quota changes."""
    a=current.get('workload') or {};b=previous.get('workload') or {}
    if not isinstance(a,dict):a={}
    if not isinstance(b,dict):b={}
    def valid(p):
        try:
            if p.get('version')!=VERSION or not p.get('complete') or p.get('tokens',0)<=0:return False
            models=p['models'];settings=p['settings']
            if not models or not settings or sum(v['tokens'] for v in models.values())!=p['tokens'] or sum(settings.values())!=p['tokens']:return False
            for model,v in models.items():
                if not isinstance(model,str) or not model:return False
                if any(not isinstance(v[k],(int,float)) or isinstance(v[k],bool) or not math.isfinite(v[k]) or v[k]<0 for k in ('tokens','input','output','cached')):return False
                if v['input']+v['output']!=v['tokens'] or v['cached']>v['input']:return False
            for key,n in settings.items():
                parts=json.loads(key)
                if not isinstance(parts,list) or len(parts)!=3 or parts[0] not in models or not label(parts[1],SPEEDS) or not label(parts[2],EFFORTS) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<=0:return False
            return True
        except (TypeError,ValueError,KeyError,AttributeError):return False
    if not all(valid(p) for p in (a,b)):
        missing=set(a.get('missing',[]))|set(b.get('missing',[]))
        if len(missing)==1:return '缺少'+next(iter(missing))+'记录，暂不判断涨跌'
        return '使用条件记录不完整，暂不判断涨跌'
    def distance(x,y):
        return sum(abs(x.get(k,0)-y.get(k,0)) for k in set(x)|set(y))/2
    def fractions(p):return {k:v['tokens']/p['tokens'] for k,v in p['models'].items()}
    x,y=fractions(a),fractions(b)
    if set(x)!=set(y) or distance(x,y)>.03+1e-9:
        return '模型使用结构不同，暂不判断涨跌'
    for model in x:
        ma,mb=a['models'][model],b['models'][model]
        for numerator,denominator in [('output','tokens'),('cached','input')]:
            va=ma[numerator]/ma[denominator] if ma[denominator] else 0
            vb=mb[numerator]/mb[denominator] if mb[denominator] else 0
            if not math.isfinite(va+vb) or abs(va-vb)>.02+1e-9:
                return '缓存或输入输出结构不同，暂不判断涨跌'
    sa={k:v/a['tokens'] for k,v in a['settings'].items()};sb={k:v/b['tokens'] for k,v in b['settings'].items()}
    if set(sa)!=set(sb) or distance(sa,sb)>.03+1e-9:
        return '速度或推理档位不同，暂不判断涨跌'
    return ''
