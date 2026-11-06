"""On-demand metadata-only drill-down and private-by-default exports."""
import csv,io,json,sqlite3,time,threading,copy
from collections import OrderedDict
from contextlib import closing
from datetime import datetime,timedelta
from pathlib import Path
from project_cost import parse_line,rate
from cost_preferences import prices
_turn_cache=OrderedDict();_checkpoints=OrderedDict();_cache_lock=threading.Lock()

def detail_snapshot(db_path,project,period='all',now=None,cancel=lambda:False,home=None,price_table=None,price_history=None):
    from project_membership import root_session
    from project_cost_store import active_event_stream
    now=time.time() if now is None else now;today=datetime.fromtimestamp(now).replace(hour=0,minute=0,second=0,microsecond=0)
    start=0 if period=='all' else (today-timedelta(days=29 if period=='30d' else 6 if period=='7d' else 1)).timestamp()
    end=today.timestamp() if period=='yesterday' else now
    with closing(sqlite3.connect(Path(db_path).as_uri()+'?mode=ro',uri=True,timeout=.5)) as db:
        db.execute('BEGIN')
        parents=dict(db.execute('SELECT * FROM cost_parent')) if db.execute("SELECT 1 FROM sqlite_master WHERE name='cost_parent'").fetchone() else {}
        roots=set(project.get('session_ids',[]));rows=[];metadata={}
        events,_=active_event_stream(db,prepare=False)
        for row in events:
            if cancel():return None
            if root_session(row[2],parents) in roots and start<=row[1]<=end:rows.append(row)
        ids={r[0] for r in rows};sources=list(db.execute('SELECT a.path,a.offset,a.state,a.revision FROM cost_source_active a JOIN temp.cost_selected_source s ON a.path=s.path AND a.revision=s.revision'))
        # Release the read snapshot before any large log IO, so the existing
        # writer can continue its bounded indexing slices.
        db.rollback()
        # Old installations have no turn metadata. Derive it only for the
        # selected sources, in this cancellable worker, without rewriting history.
        for path,offset,saved,revision in sources:
            if cancel():return None
            if root_session(json.loads(saved).get('session',''),parents) not in roots:continue
            source_ids={r[0] for r in rows if r[2]==json.loads(saved).get('session','')}
            with _cache_lock:
                for ident in source_ids:
                    key=(path,revision,ident)
                    if key in _turn_cache:metadata[ident]=_turn_cache[key];_turn_cache.move_to_end(key)
                checkpoint=copy.deepcopy(_checkpoints.get((path,revision)))
            if source_ids<=metadata.keys():continue
            state={};read=0
            missing=[r for r in rows if r[0] in source_ids and r[0] not in metadata]
            if checkpoint and checkpoint[0]<=offset and missing and min(r[1] for r in missing)>checkpoint[1].get('last_stamp',0):read,state=checkpoint
            try:
                with open(path,'rb') as stream:
                    stream.seek(read)
                    while read<offset and not cancel():
                        line=stream.readline(min(4*1024*1024,offset-read));read+=len(line)
                        if not line:break
                        event=parse_line(line,state,Path(path))
                        if event and event[0] in source_ids:
                            metadata[event[0]]=state.get('turn','')
                            with _cache_lock:
                                _turn_cache[(path,revision,event[0])]=metadata[event[0]]
                                while len(_turn_cache)>20000:_turn_cache.popitem(last=False)
                with _cache_lock:
                    _checkpoints[(path,revision)]=(read,copy.deepcopy(state));_checkpoints.move_to_end((path,revision))
                    while len(_checkpoints)>8:_checkpoints.popitem(last=False)
            except OSError:pass
        session_rows={};price=prices() if price_table is None else price_table
        if price_history is None and price_table is None:
            from cost_preferences import price_history as saved_history
            price_history=saved_history()
        from official_api_prices import PriceBook
        price_book=PriceBook(price_history) if price_history is not None else None
        priced_history_sources={tuple(source) for source in project.get('priced_history_sources',())}
        for ident,stamp,sid,path,model,tokens,a,c,b,known in rows:
            root=root_session(sid,parents);s=session_rows.setdefault(root,dict(id=root,name='会话 '+root[-8:],tokens=0,cost=0.,pending_tokens=0,turns={}))
            # Never invent turn boundaries where the log has no turn identity.
            turn=metadata.get(ident);key=(sid,turn) if turn else (sid,'unattributed')
            t=s['turns'].setdefault(key,dict(id=turn or '',stamp=stamp,models=set(),tokens=0,input=0,cached=0,output=0,cost=0.,pending_tokens=0,unknown=not bool(turn),known=True))
            t['known']=t['known'] and bool(known)
            t['stamp']=min(t['stamp'],stamp);t['models'].add(model or '未识别模型');t['tokens']+=tokens;s['tokens']+=tokens
            model_prices=price_book.rate(model,stamp) if price_book else rate(model,price)
            for field,value in zip(('input','cached','output'),(a,c,b)):t[field]+=value or 0
            if known and model_prices is not None and (project['id'] or (sid,path) in priced_history_sources):
                cost=((a-c)*model_prices[0]+c*model_prices[1]+b*model_prices[2])/1e6;t['cost']+=cost;s['cost']+=cost
            else:t['pending_tokens']+=tokens;s['pending_tokens']+=tokens
        for s in session_rows.values():
            s['turns']=sorted(s['turns'].values(),key=lambda t:-t['stamp'])
            for t in s['turns']:t['models']=sorted(t['models'])
        if home is not None:
            from session_read_state import conversation_names
            for sid,name in conversation_names(home,session_rows).items():session_rows[sid]['name']=' '.join(name.split())[:240]
        return sorted(session_rows.values(),key=lambda s:-s['cost'])

def export_rows(data,period,query,archive):
    from project_cost import search_rows
    checked=datetime.fromtimestamp(data.get('checked') or time.time());end=checked.strftime('%Y-%m-%d');start='' if period=='all' else (checked-timedelta(days=29 if period=='30d' else 6 if period=='7d' else 1)).strftime('%Y-%m-%d')
    if period=='yesterday':end=start
    for project in search_rows(data,period,query,archive):
        for m in project['model_usage']:
            yield dict(project=project['name'],period=period,range_start=start,range_end=end,model=m['model'],tokens=m['tokens'],usd_cost=round(m['cost'],6),unpriced_tokens=m['pending_tokens'])

def encode_export(rows,kind):
    rows=list(rows)
    if kind=='JSON':return json.dumps(dict(currency='USD',rows=rows),ensure_ascii=False,indent=2).encode('utf-8')
    out=io.StringIO(newline='');fields=['project','period','range_start','range_end','model','tokens','usd_cost','unpriced_tokens'];writer=csv.DictWriter(out,fieldnames=fields,lineterminator='\r\n');writer.writeheader()
    for row in rows:
        # A user-chosen project/model name must remain data in spreadsheets.
        writer.writerow({k:('\''+str(v) if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in row.items()})
    return out.getvalue().encode('utf-8-sig')
