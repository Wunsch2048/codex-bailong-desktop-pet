"""Independent, incremental cost metadata. Never change the existing Token ledger."""
import hashlib,json,re,time,unicodedata,sqlite3
from contextlib import closing
from datetime import datetime,timedelta
from pathlib import PureWindowsPath,Path
from token_calendar import counter

PRICE_VERSION='2026-10-30-standard-short'
PRICE_SOURCE='https://developers.openai.com/api/docs/pricing'
# Current standard short-context USD per million. No generic model fallback.
RATES={'gpt-6-astra':(10,1,50),'gpt-6.1-sol':(2,.1,10),
       'gpt-6.1-terra':(1,.05,5),'gpt-6-luna':(.1,.01,.5),
       'gpt-6-sol':(2,.2,10),'gpt-5.6-luna':(.2,.02,1.2)}
# Legacy models are still used in historical sessions. Verify their own model
# pages, not the four flagship rows shown by default on the pricing page.
RATE_SOURCES={name:'https://developers.openai.com/api/docs/models/'+name
              for name in ('gpt-6-sol','gpt-5.6-luna')}

def rate(model,prices=None):
    name=re.sub(r'-\d{4}-\d{2}-\d{2}$','',model.lower())
    return (RATES if prices is None else prices).get(name)

def pricing_revision(prices=None):
    """Bind each projection to the entire price table, not just its label."""
    return PRICE_VERSION+':'+hashlib.sha256(json.dumps(RATES if prices is None else prices,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]

def migrate(db):
    db.execute('CREATE TABLE IF NOT EXISTS cost_files(path TEXT PRIMARY KEY,offset INTEGER,state TEXT,archived INTEGER)')
    db.execute('''CREATE TABLE IF NOT EXISTS cost_events(id TEXT PRIMARY KEY,stamp REAL,session TEXT,project TEXT,
                model TEXT,tokens INTEGER,input INTEGER,cached INTEGER,output INTEGER,known INTEGER)''')
    db.execute('CREATE INDEX IF NOT EXISTS cost_project_stamp ON cost_events(project,stamp)')
    db.execute('CREATE TABLE IF NOT EXISTS cost_cursor(key TEXT PRIMARY KEY,value TEXT)')

def project_path(value):
    if not isinstance(value,str) or not value.strip():return ''
    value=value.replace('\\','/')
    if value.lower().startswith('//?/unc/'):value='//'+value[8:]
    elif value.startswith('//?/'):value=value[4:]
    # Windows paths are case insensitive; Linux and WSL paths retain case.
    if re.match(r'^[a-zA-Z]:[\\/]',value) or value.startswith('//'):
        return str(PureWindowsPath(value)).replace('\\','/').casefold()
    return value.rstrip('/') or '/'

def parse_line(line,state,path):
    if not any(k in line for k in (b'session_meta',b'turn_context',b'token_count',b'task_started',b'turn_started')):return None
    try:
        obj=json.loads(line);p=obj.get('payload') or {}
        if not isinstance(p,dict):return None
        kind=obj.get('type')
        if kind=='event_msg' and p.get('type') in ('task_started','turn_started'):
            state['turn']=str(p.get('turn_id') or p.get('id') or '')[:128];return None
        if kind=='session_meta':
            if state.get('header_seen'):return None  # later headers may be copied parent history
            state['header_seen']=True
            sid=p.get('id') or p.get('session_id')
            if isinstance(sid,str) and sid:state['session']=sid[:128]
            else:state['limited']=True
            state['project']=project_path(p.get('cwd'))
            state['model']=p.get('model') or ''
            state['fork']=bool(p.get('forked_from_id'))
            state['created']=obj.get('timestamp')
            return None
        if kind=='turn_context':
            state['turn']=str(p.get('turn_id') or p.get('id') or state.get('turn') or '')[:128]
            state['project']=project_path(p.get('cwd')) or state.get('project','')
            state['model']=p.get('model') or state.get('model','')
            return None
        if kind!='event_msg' or p.get('type')!='token_count':return None
        info=p.get('info') or {};u=info.get('total_token_usage') or {}
        a,b,c=(counter(u.get(k)) for k in ('input_tokens','output_tokens','cached_input_tokens'))
        total=counter(u.get('total_tokens'))
        if total is None:total=a+b if a is not None and b is not None else None
        if total is None:
            state['limited']=True;state['unresolved_events']=state.get('unresolved_events',0)+1;return None
        previous=state.get('water');stamp=datetime.fromisoformat(str(obj.get('timestamp')).replace('Z','+00:00')).timestamp()
        state['last_stamp']=max(stamp,state.get('last_stamp',0))
        if state.get('fork') and state.get('created') and stamp<datetime.fromisoformat(state['created'].replace('Z','+00:00')).timestamp():
            state.update(water=total,a=a,b=b,c=c,inherited_baseline=True);return None
        da=a-state.get('a',0) if a is not None and state.get('a',0) is not None else None
        dbb=b-state.get('b',0) if b is not None and state.get('b',0) is not None else None
        dc=c-state.get('c',0) if c is not None and state.get('c',0) is not None else None
        delta=total-(previous or 0)
        state.update(water=total,a=a,b=b,c=c)
        # No parent record match/baseline means inherited and new usage cannot be separated safely.
        if state.get('fork') and previous is None:
            state['limited']=True;state['unresolved_events']=state.get('unresolved_events',0)+1;return None
        if delta<=0:
            if delta<0:state['limited']=True
            return None
        known=all(v is not None and v>=0 for v in (da,dbb,dc)) and da+dbb==delta and dc<=da
        model=p.get('model') or info.get('model') or state.get('model','')
        if not isinstance(model,str):model=''
        sid=state.get('session')
        if not sid:state['limited']=True;return None
        identity='v2:'+hashlib.sha256(json.dumps([sid,obj.get('timestamp'),total,a,b,c,delta,da,dc,dbb,model],separators=(',',':')).encode()).hexdigest()
        return (identity,stamp,sid,state.get('project',''),model,delta,da,dc,dbb,int(known))
    except (ValueError,TypeError,AttributeError,OverflowError):state['limited']=True
    return None


def scan(db,path,stop,deadline):
    from project_cost_store import scan as scan_revision
    return scan_revision(db,path,stop,deadline,parse_line)

def update(db,files,stop=lambda:False,budget=.35):
    from project_cost_store import migrate as migrate_sources
    migrate(db);migrate_sources(db);deadline=time.monotonic()+budget;pending=False;errors=0
    paths=sorted(files);saved=db.execute("SELECT value FROM cost_cursor WHERE key='path'").fetchone()
    cursor=saved[0] if saved else '';cut=next((i for i,p in enumerate(paths) if str(p)>cursor),len(paths))
    paths=paths[cut:]+paths[:cut]
    last=None
    for path in paths:
        if stop() or time.monotonic()>=deadline:pending=True;break
        try:
            unfinished=scan(db,path,stop,deadline);pending=unfinished or pending
            # Finish a budgeted source before rotating. Otherwise large-file
            # hash checkpoints are evicted by the next files before completion.
            if unfinished and (stop() or time.monotonic()>=deadline):break
            last=str(path)
        except (OSError,ValueError):errors+=1
    if last is not None:db.execute("INSERT OR REPLACE INTO cost_cursor VALUES('path',?)",(last,))
    if not stop() and time.monotonic()<deadline:
        from index_maintenance import prune_slice
        prune_slice(db)
    indexed={row[0] for row in db.execute('SELECT path FROM cost_source_active')}
    initial=pending and any(str(Path(path).resolve()) not in indexed for path in files)
    return dict(pending=pending,initial_pending=initial,syncing=pending and not initial,errors=errors)

def snapshot(db,now,progress,files=None,home=None):
    from cost_preferences import prices as saved_prices
    prices=saved_prices();price_revision=pricing_revision(prices)
    statuses={};limited=False;membership_health={};unresolved=0;metadata={}
    db.execute('CREATE TABLE IF NOT EXISTS cost_session_assignment(session TEXT PRIMARY KEY,project TEXT,archived INTEGER)')
    assignments={sid:(project,bool(archived)) for sid,project,archived in db.execute('SELECT * FROM cost_session_assignment')}
    archived_meta={sid:v[1] for sid,v in assignments.items()}
    catalog={};parents={}
    if home is not None:
        from project_membership import read_membership,root_session
        overrides,catalog,parents,metadata,membership_health=read_membership(home,db)
        for sid,m in metadata.items():
            if 'archived' in m:archived_meta[sid]=bool(m['archived'])
            directory=(overrides[sid] or project_path(m.get('cwd'))) if sid in overrides else (assignments.get(sid,('',False))[0] if assignments.get(sid,('',False))[0].startswith('project:') else '') or project_path(m.get('cwd'))
            if directory or sid in overrides:
                archived=archived_meta.get(sid,False)
                changed=assignments.get(sid)!=(directory,archived);assignments[sid]=(directory,archived)
                if changed:db.execute('INSERT OR REPLACE INTO cost_session_assignment VALUES (?,?,?)',(sid,directory,int(archived)))
        for sid,directory in overrides.items():
            directory=directory or project_path(metadata.get(sid,{}).get('cwd'))
            a=archived_meta.get(sid,False)
            if assignments.get(sid)!=(directory,a):db.execute('INSERT OR REPLACE INTO cost_session_assignment VALUES (?,?,?)',(sid,directory,int(a)))
            assignments[sid]=(directory,a)
    present={str(p.resolve()) for p in files} if files is not None else None
    from project_cost_store import file_metadata
    for path,state,archived in file_metadata(db):
        meta=json.loads(state);sid=meta.get('session')
        if sid and sid not in assignments and meta.get('project'):assignments[sid]=(project_path(meta['project']),bool(archived))
        if sid and (present is None or path in present):statuses.setdefault(sid,[]).append(bool(archived))
        limited=limited or bool(meta.get('limited'))
        unresolved+=meta.get('unresolved_events',0)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='cost_source_work'").fetchone():
        for (raw,) in db.execute('SELECT state FROM cost_source_work'):
            stage=json.loads(raw);limited=limited or bool(stage.get('limited'))
    if not membership_health.get('projects',True) and any(p.startswith('project:') for p,a in assignments.values()):limited=True
    parent_conflicts=sum(1 for sid in parents if root_session(sid,parents)==sid)
    limited=limited or bool(parent_conflicts)
    result={}
    current=datetime.fromtimestamp(now);midnight=current.replace(hour=0,minute=0,second=0,microsecond=0)
    from project_cost_store import active_event_stream
    events,conflicts=active_event_stream(db);limited=limited or bool(conflicts)
    revisions={}
    from project_membership import root_session
    from session_read_state import conversation_display_name
    for sid,revision,offset,fp in db.execute('SELECT a.session,a.revision,a.offset,a.fingerprint FROM cost_source_active a JOIN temp.cost_selected_source s ON a.path=s.path AND a.revision=s.revision'):
        revisions.setdefault(root_session(sid,parents),[]).append((sid,offset,json.loads(fp).get('digest','')))
    revisions={sid:hashlib.sha256(json.dumps(sorted(values),separators=(',',':')).encode()).hexdigest()[:20] for sid,values in revisions.items()}
    buckets={}
    for _,stamp,sid,project,model,tokens,a,c,b,known in events:
        if stamp>now:continue
        # Keep incomplete events separate: one bad record must not turn a
        # whole otherwise-priced session/model/day into pending usage.
        key=(project,model,sid,datetime.fromtimestamp(stamp).strftime('%Y-%m-%d'),bool(known))
        sums=buckets.setdefault(key,[0,0,0,0]);sums[0]+=tokens
        for i,value in enumerate((a,c,b),1):
            if value is not None:sums[i]+=value
    # A missing thread and missing rollout leave historical usage, but no
    # current evidence that its old working directory is still its project.
    # Only apply this when both sources were available for comparison.
    check_missing = present is not None and membership_health.get('threads')
    live_roots = {root_session(sid,parents) for sid in metadata.keys() | statuses.keys()} if check_missing else set()
    unassigned='unassigned:'
    projectless=set(membership_health.pop('projectless_ids',()))
    scratch_root=project_path(str(Path.home()/'Documents'/'Codex'))
    grouped=[]
    for (project,model,sid,day,known),values in buckets.items():
        root=root_session(sid,parents)
        path=assignments.get(root,assignments.get(sid,(project_path(project),False)))[0]
        original_path=path
        if check_missing and root not in live_roots:
            path=''
        elif path and not path.startswith('project:'):
            relative=path.removeprefix(scratch_root+'/')
            date_folder,separator,leaf=relative.partition('/')
            scratch=(relative!=path and separator and leaf and
                     len(date_folder)==10 and date_folder[4]==date_folder[7]=='-' and
                     date_folder.replace('-','').isdigit())
            if root in projectless or scratch:
                path=unassigned
        grouped.append((path,model,root,day,*values,known,original_path,(sid,project)))
    project_archives={}
    for path,model,sid,*_ in grouped:
        archived=archived_meta.get(sid,bool(statuses.get(sid)) and all(statuses[sid]))
        project_archives[path]=project_archives.get(path,True) and archived
    yesterday=(midnight-timedelta(days=1)).strftime('%Y-%m-%d')
    for period,days in [('all',None),('30d',30),('7d',7),('yesterday',1)]:
        start=yesterday if period=='yesterday' else (midnight-timedelta(days=days-1)).strftime('%Y-%m-%d') if days else ''
        projects={}
        for path,model,sid,day,tokens,a,c,b,known,original_path,source in grouped:
            if day<start or (period=='yesterday' and day!=yesterday):continue
            display=dict(name='未归属项目',path='') if path==unassigned else catalog.get(path,{})
            name=display.get('name') or (PureWindowsPath(path).name if path else '未识别项目') or path
            p=projects.setdefault(path,dict(id=path,name=name,path=display.get('path',path),tokens=0,cost=0.,parts=[0.,0.,0.],pending_tokens=0,pending_reasons={},sessions=set(),models=set(),archived=True,model_usage={},session_usage={}))
            p['tokens']+=tokens;p['sessions'].add(sid);p['models'].add(model or '未识别模型')
            m=p['model_usage'].setdefault(model or '未识别模型',dict(model=model or '未识别模型',tokens=0,cost=0.,pending_tokens=0,pending_reasons={}))
            m['tokens']+=tokens
            title=' '.join((conversation_display_name(metadata.get(sid,{})) or ('会话 '+sid[-8:])).split())[:240]
            session=p['session_usage'].setdefault(sid,dict(id=sid,name=title,tokens=0,cost=0.,pending_tokens=0,detail_revision=revisions.get(sid,'')))
            if path==unassigned:session['directory']=original_path
            session['tokens']+=tokens
            p['archived']=project_archives[path]
            model_prices=rate(model,prices)
            if not path and original_path:
                p.setdefault('priced_history_sources',set()).add(source)
            if not known or model_prices is None or not original_path:
                # Exclusive reasons keep their sum equal to pending_tokens.
                reason='incomplete_counts' if not known else 'unknown_model' if model_prices is None else 'unknown_project'
                for row in (p,m):
                    row['pending_tokens']+=tokens;row['pending_reasons'][reason]=row['pending_reasons'].get(reason,0)+tokens
                session['pending_tokens']+=tokens
                continue
            parts=[(a-c)*model_prices[0]/1e6,c*model_prices[1]/1e6,b*model_prices[2]/1e6]
            p['parts']=[x+y for x,y in zip(p['parts'],parts)];p['cost']+=sum(parts)
            m['cost']+=sum(parts)
            session['cost']+=sum(parts)
        for p in projects.values():
            for row in [p,*p['model_usage'].values()]:
                row['priced_tokens']=row['tokens']-row['pending_tokens']
                row['price_coverage']=row['priced_tokens']/row['tokens'] if row['tokens'] else None
            p['session_ids']=sorted(p['sessions']);p['sessions']=len(p['sessions']);p['models']=sorted(p['models']);p['cost']=round(p['cost'],6)
            p['model_usage']=sorted(p['model_usage'].values(),key=lambda v:-v['cost'])
            p['session_usage']=sorted(p['session_usage'].values(),key=lambda v:-v['cost'])
        result[period]=sorted(projects.values(),key=lambda p:-p['cost'])
    return dict(ranges=result,yesterday=yesterday,**progress,limited=limited,unresolved_events=unresolved,source_conflicts=conflicts,parent_conflicts=parent_conflicts,membership_health=membership_health,price_version=PRICE_VERSION,price_revision=price_revision,price_table=prices,price_source=PRICE_SOURCE,checked=now)

def search_rows(data,period='all',query='',archive='active'):
    def norm(s):return unicodedata.normalize('NFKC',s).casefold().replace('\\','/')
    words=norm(query).split()
    return [p for p in (data or {}).get('ranges',{}).get(period,[]) if
            (archive=='all' or p['archived']==(archive=='archived')) and
            (not words or all(w in norm(' '.join([p['name'],p['path'],*(s.get('directory','') for s in p.get('session_usage',[]))])) for w in words))]
