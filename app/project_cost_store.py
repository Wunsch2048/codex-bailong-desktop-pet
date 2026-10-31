"""Revisioned project-cost index. Original usage and legacy cost rows remain intact."""
import hashlib,json,time,uuid
from pathlib import Path
from collections import OrderedDict

_HASHES={}
_STATES=OrderedDict()
AUDIT_SECONDS=300

def remember(path,token,offset,hasher):
    key=(str(path),token);_STATES[key]=(offset,hasher.copy());_STATES.move_to_end(key)
    while len(_STATES)>8:_STATES.popitem(last=False)

def seed(path,offset,deadline,token,expected=None,force=False):
    value=_STATES.get((str(path),token))
    if not force and value and value[0]==offset and (expected is None or value[1].hexdigest()==expected):
        _STATES.move_to_end((str(path),token));return value[1].copy()
    if offset==0:return hashlib.sha256()
    if digest(path,offset,deadline,token) is None:return None
    return _STATES[(str(path),token)][1].copy()


def migrate(db):
    fresh=not db.execute("SELECT 1 FROM sqlite_master WHERE name='cost_source_events'").fetchone()
    db.execute('''CREATE TABLE IF NOT EXISTS cost_revision_events(id TEXT PRIMARY KEY,stamp REAL,session TEXT,project TEXT,
                model TEXT,tokens INTEGER,input INTEGER,cached INTEGER,output INTEGER,known INTEGER)''')
    db.execute('CREATE TABLE IF NOT EXISTS cost_source_active(path TEXT PRIMARY KEY,revision TEXT,session TEXT,offset INTEGER,state TEXT,fingerprint TEXT,archived INTEGER,checked REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS cost_source_work(path TEXT PRIMARY KEY,revision TEXT,offset INTEGER,state TEXT,fingerprint TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS cost_source_events(path TEXT,revision TEXT,event TEXT,PRIMARY KEY(path,revision,event))')
    db.execute('CREATE INDEX IF NOT EXISTS cost_source_event ON cost_source_events(event)')
    if fresh:
        from index_maintenance import mark_clean
        mark_clean(db)

def fingerprint(path,offset=None):
    with path.open('rb') as f:
        st=path.stat();end=st.st_size if offset is None else min(offset,st.st_size)
        head_len=min(end,4096);head=f.read(head_len);f.seek(max(0,end-4096));tail=f.read(min(end,4096))
    return dict(size=st.st_size,mtime=st.st_mtime_ns,file=[st.st_dev,st.st_ino],head=hashlib.sha256(head).hexdigest(),head_len=head_len,tail=hashlib.sha256(tail).hexdigest(),boundary=end)

def same_boundary(path,old):
    current=fingerprint(path,old['boundary'])
    # Head length must be compared at the original boundary, not the new EOF.
    return current['file']==old['file'] and current['size']>=old['boundary'] and current['head']==old['head'] and current['tail']==old['tail']

def digest(path,limit,deadline,token):
    """Budgeted full-prefix verification; at most eight small hash states, no idle timer."""
    key=(str(path),limit,token)
    if key not in _HASHES:
        if len(_HASHES)>=8:_HASHES.pop(next(iter(_HASHES)))
        _HASHES[key]=[0,hashlib.sha256()]
    progress=_HASHES[key]
    with path.open('rb') as stream:
        stream.seek(progress[0])
        while progress[0]<limit and time.monotonic()<deadline:
            raw=stream.read(min(262144,limit-progress[0]))
            if not raw:_HASHES.pop(key,None);raise OSError('Cost source changed during verification')
            progress[1].update(raw);progress[0]+=len(raw)
    if progress[0]<limit:return None
    remember(path,token,limit,progress[1]);_HASHES.pop(key,None);return progress[1].hexdigest()

def scan(db,path,stop,deadline,parse_line):
    migrate(db);path=Path(path);key=str(path.resolve());archived=int('archived_sessions' in path.parts)
    active=db.execute('SELECT revision,session,offset,state,fingerprint,checked FROM cost_source_active WHERE path=?',(key,)).fetchone()
    work=db.execute('SELECT revision,offset,state,fingerprint FROM cost_source_work WHERE path=?',(key,)).fetchone()
    stat=path.stat();now=time.time();hasher=None
    if work:
        revision,offset,state,old=work[0],work[1],json.loads(work[2]),json.loads(work[3])
        base=state.get('_cost_append_base')
        base_valid=not base or (active is not None and base==[active[0],active[2]])
        if not base_valid or not old.get('digest') or not same_boundary(path,old) or (stat.st_size==old['size'] and stat.st_mtime_ns!=old['mtime']):work=None
        else:
            hasher=seed(path,offset,deadline,revision,old['digest'])
            if hasher is None:return True
            if hasher.hexdigest()!=old['digest']:work=None
    if not work:
        append=False;verified_at=now
        if active:
            old=json.loads(active[4]);unchanged=stat.st_size==old['size'] and stat.st_mtime_ns==old['mtime'] and [stat.st_dev,stat.st_ino]==old['file']
            due=now-active[5]>=AUDIT_SECONDS
            if unchanged and not due:
                db.execute('UPDATE cost_source_active SET archived=? WHERE path=?',(archived,key));return False
            valid=stat.st_size>=active[2] and same_boundary(path,old)
            if valid:
                # Cached SHA state extends append-only prefixes. Restart, cache
                # eviction, an in-place edit or periodic audit verifies them anew.
                token=active[0] if not due else active[0]+':audit:'+str(active[5])
                cached=_STATES.get((str(path),token))
                reuse=not due and stat.st_size>active[2] and cached is not None
                hasher=seed(path,active[2],deadline,token,old.get('digest'),force=not reuse)
                if hasher is None:return True
                valid=hasher.hexdigest()==old.get('digest') and same_boundary(path,old)
                verified_at=active[5] if reuse else now
            if valid and stat.st_size==active[2]:
                # Rebuild the active fingerprint too; a harmless metadata touch
                # must not cause another full read on the next ordinary poll.
                current=fingerprint(path,active[2]);current['digest']=hasher.hexdigest()
                remember(path,active[0],active[2],hasher)
                db.execute('UPDATE cost_source_active SET checked=?,fingerprint=?,archived=? WHERE path=?',(verified_at,json.dumps(current),archived,key));return False
            append=valid and stat.st_size>active[2]
        revision=uuid.uuid4().hex
        offset,state=(active[2],json.loads(active[3])) if append else (0,{'parser_revision':2})
        state['_cost_full_checked']=verified_at
        # Work holds only the appended delta. The confirmed revision stays
        # readable until the new complete-line prefix has passed verification.
        if append:state['_cost_append_base']=[active[0],active[2]]
        else:hasher=hashlib.sha256()
    before=fingerprint(path);initial_size=before['size'];partial=False
    with path.open('rb') as stream:
        stream.seek(offset)
        while offset<initial_size and not stop() and time.monotonic()<deadline:
            pos=stream.tell();line=stream.readline(min(4*1024*1024,initial_size-pos))
            if not line:break
            if not line.endswith(b'\n'):
                if len(line)<4*1024*1024:partial=True;break
                state['limited']=True;state['oversized_record']=True;offset=stream.tell();hasher.update(line);continue
            offset=stream.tell();hasher.update(line);event=parse_line(line,state,path)
            if event:
                db.execute('INSERT OR IGNORE INTO cost_revision_events VALUES (?,?,?,?,?,?,?,?,?,?)',event)
                db.execute('INSERT OR IGNORE INTO cost_source_events VALUES (?,?,?)',(key,revision,event[0]))
    current=fingerprint(path,offset)
    if not same_boundary(path,before) or (current['size']==before['size'] and current['mtime']!=before['mtime']):return True
    current['digest']=hasher.hexdigest()
    remember(path,revision,offset,hasher)
    db.execute('INSERT OR REPLACE INTO cost_source_work VALUES (?,?,?,?,?)',(key,revision,offset,json.dumps(state),json.dumps(current)))
    if stop() or (offset<initial_size and not partial):return True
    if not state.get('session'):
        state['limited']=True
        db.execute('UPDATE cost_source_work SET state=? WHERE path=?',(json.dumps(state),key))
        return False
    # Publish the verified complete-line prefix even if a writer appended after
    # it. Incomplete/new tail bytes are left for the following bounded slice.
    end=path.stat()
    if not same_boundary(path,current) or (end.st_size==current['size'] and end.st_mtime_ns!=current['mtime']):return True
    current['digest']=hasher.hexdigest()
    session=state['session']
    base=state.pop('_cost_append_base',None)
    if base:
        confirmed=db.execute('SELECT revision,offset FROM cost_source_active WHERE path=?',(key,)).fetchone()
        if confirmed!=tuple(base):return True
        db.execute('INSERT OR IGNORE INTO cost_source_events SELECT path,?,event FROM cost_source_events WHERE path=? AND revision=?',(base[0],key,revision))
        db.execute('DELETE FROM cost_source_events WHERE path=? AND revision=?',(key,revision))
        revision=base[0]
        remember(path,revision,offset,hasher)
    db.execute('INSERT OR REPLACE INTO cost_source_active VALUES (?,?,?,?,?,?,?,?)',(key,revision,session,offset,json.dumps(state),json.dumps(current),archived,state.get('_cost_full_checked',now)))
    db.execute('DELETE FROM cost_source_work WHERE path=?',(key,))
    return partial or path.stat().st_size>offset


def active_events(db):
    """Choose one canonical complete source per session, then deduplicate events."""
    migrate(db);sources=list(db.execute('SELECT path,revision,session,state,fingerprint FROM cost_source_active'))
    candidates={};conflicts=0
    for path,revision,sid,state,fp in sources:
        state=json.loads(state);fp=json.loads(fp)
        rank=(state.get('last_stamp',0),fp['mtime'],path)
        candidates.setdefault(sid,[]).append((rank,path,revision))
    ids=set();covered=set(candidates)
    for sid,items in candidates.items():
        items.sort(reverse=True);_,path,rev=items[0]
        chosen={r[0] for r in db.execute('SELECT event FROM cost_source_events WHERE path=? AND revision=?',(path,rev))}
        for _,other,version in items[1:]:
            other_ids={r[0] for r in db.execute('SELECT event FROM cost_source_events WHERE path=? AND revision=?',(other,version))}
            if not other_ids<=chosen:conflicts+=1
        ids.update(chosen)
    # Legacy rows are a fallback until that session has a verified new-parser source.
    rows=[row for row in db.execute('SELECT * FROM cost_revision_events') if row[0] in ids]
    rows.extend(row for row in db.execute('SELECT * FROM cost_events') if row[2] not in covered)
    return rows,conflicts


def file_metadata(db):
    migrate(db)
    current=list(db.execute('SELECT path,state,archived FROM cost_source_active'))
    covered={json.loads(state).get('session') for path,state,a in current}
    paths={path for path,state,a in current}
    yield from current
    for path,state,archived in db.execute('SELECT path,state,archived FROM cost_files'):
        if path not in paths and json.loads(state).get('session') not in covered:yield path,state,archived
