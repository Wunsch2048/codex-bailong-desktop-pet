"""Read-only adapter for versioned desktop unread metadata; no UI guessing."""
import json,re,sqlite3,time
from pathlib import Path
from contextlib import closing

def session_id(value):
    text=str(value);match=re.search(r'([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$',text)
    return match.group(1).lower() if match else text

def rollout_alias(path):
    """Map an edited root-turn rollout back to its desktop conversation."""
    path=Path(path)
    uuid=r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
    match=re.search(rf'({uuid})_({uuid})\.jsonl$',Path(path).name)
    if not match or match.group(1).lower()==match.group(2).lower():return path.stem
    parent,branch=(value.lower() for value in match.groups())
    inherited_parent=False
    try:
        with path.open('rb') as stream:
            size=0
            for _ in range(64):
                raw=stream.readline(65536);size+=len(raw)
                if not raw or not raw.endswith(b'\n') or size>1048576:break
                try:obj=json.loads(raw)
                except (ValueError,UnicodeError):continue
                payload=obj.get('payload') or {}
                if not isinstance(payload,dict):continue
                if obj.get('type')=='session_meta':
                    owner=session_id(payload.get('id') or payload.get('session_id') or '')
                    if owner==branch or is_subagent_metadata(payload):return path.stem
                    if owner==parent:
                        base=payload.get('history_base')
                        if isinstance(base,dict) and session_id(base.get('thread_id',''))==parent:
                            return parent
                        inherited_parent=True
                if obj.get('type')=='event_msg' and payload.get('type')=='task_started':
                    attribution=payload.get('turn_attribution') or {}
                    if not isinstance(attribution,dict):return path.stem
                    root_trigger=attribution.get('turn_trigger') in ('edit_user_message','composer','resume_interrupted_task')
                    if inherited_parent and root_trigger and not attribution.get('initiating_agent_path') and not attribution.get('parent_turn_id'):
                        return parent
                    return path.stem
    except OSError:pass
    return path.stem


def is_subagent_metadata(metadata):
    source=metadata.get('source')
    if isinstance(source,str):
        try:source=json.loads(source)
        except (ValueError,TypeError):pass
    agent=metadata.get('agent_path')
    return (isinstance(source,dict) and 'subagent' in source) or source=='subagent' or (isinstance(agent,str) and bool(agent.strip()) and agent.strip()!='/root')


def subagent_sessions(home,ids):
    """Identify only proven child threads; missing metadata never hides a chat."""
    from codex_connection import is_wsl_source
    if is_wsl_source(home):return set()
    ids=list(dict.fromkeys(session_id(sid) for sid in ids if sid))
    if not ids:return set()
    try:
        with closing(sqlite3.connect((Path(home)/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            columns={row[1] for row in db.execute('PRAGMA table_info(threads)')}
            fields=[key for key in ('id','source','agent_path') if key in columns]
            if 'id' not in fields or len(fields)<2:return set()
            found=set()
            for start in range(0,len(ids),128):
                chunk=ids[start:start+128];rows=db.execute('SELECT '+','.join(fields)+' FROM threads WHERE id IN ('+','.join('?' for _ in chunk)+')',chunk)
                found.update(row[0] for row in rows if is_subagent_metadata(dict(zip(fields,row))))
            return found
    except (OSError,sqlite3.Error,ValueError):return set()


def attached_conversations(home,ids):
    """Resolve only explicit desktop attachments, never names or ordinary forks.

    A missing parent, unknown schema or cycle is not evidence to hide a chat.
    Read bounded metadata batches; do not read conversation messages.
    """
    ids={session_id(s) for s in ids if s}
    if not ids:return {}
    try:
        with closing(sqlite3.connect((Path(home)/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            columns={r[1] for r in db.execute('PRAGMA table_info(threads)')}
            if not {'id','attached_thread_parent_id'}<=columns:return {}
            graph={};wanted=set(ids)
            for _ in range(16):
                missing=sorted(wanted-set(graph))
                if not missing:break
                previous_size=len(graph)
                for start in range(0,len(missing),128):
                    chunk=missing[start:start+128]
                    rows=db.execute('SELECT id,attached_thread_parent_id FROM threads WHERE id IN ('+','.join('?' for _ in chunk)+')',chunk)
                    graph.update((session_id(s),session_id(p) if isinstance(p,str) and p.strip() else '') for s,p in rows)
                if len(graph)==previous_size:break
                wanted={p for p in graph.values() if p and p not in graph}
                if not wanted:break
            result={}
            for sid in ids:
                current=sid;seen=set()
                while current in graph and current not in seen:
                    seen.add(current);parent=graph[current]
                    if not parent:
                        if current!=sid:result[sid]=current
                        break
                    current=parent
            return result
    except (OSError,sqlite3.Error,ValueError):return {}


def non_user_sessions(home,ids):
    ids=list(ids)
    return subagent_sessions(home,ids)|set(attached_conversations(home,ids))


def conversation_display_name(metadata):
    for key in ('name','title'):
        value=metadata.get(key)
        if isinstance(value,str) and value.strip():return value.strip()
    return ''

def conversation_names(home,ids):
    """Fetch only display names for tracked sessions from the desktop store."""
    ids=list(dict.fromkeys(session_id(sid) for sid in ids if sid))
    if not ids:return {}
    try:
        with closing(sqlite3.connect((Path(home)/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            found={};columns={row[1] for row in db.execute('PRAGMA table_info(threads)')};fields=[k for k in ('id','name','title') if k in columns]
            if 'id' not in fields:return {}
            for start in range(0,len(ids),128):
                chunk=ids[start:start+128];rows=db.execute('SELECT '+','.join(fields)+' FROM threads WHERE id IN ('+','.join('?' for _ in chunk)+')',chunk)
                for row in rows:
                    metadata=dict(zip(fields,row));name=conversation_display_name(metadata)
                    if name:found[metadata['id']]=name
            return found
    except (OSError,sqlite3.Error,ValueError):return {}

def read_unread_sessions(home):
    try:
        root=json.loads((Path(home)/'.codex-global-state.json').read_text(encoding='utf-8'))
        data=root.get('electron-thread-read-state-v1') if isinstance(root,dict) else None
        if not isinstance(data,dict) or data.get('version')!=1:return None
        groups=data.get('unreadByIdentity')
        if not isinstance(groups,dict):return None
        found=False;unread=set()
        for hosts in groups.values():
            if not isinstance(hosts,dict):return None
            for host,ids in hosts.items():
                if not host.startswith('local:'):continue
                if not isinstance(ids,list) or not all(isinstance(x,str) for x in ids):return None
                found=True;unread.update(session_id(x) for x in ids)
        return unread if found else None
    except (OSError,ValueError,UnicodeError):return None

def read_tracking_probe(home):
    """Verify current marker shape and an actual read-only publication query."""
    from connection_health import sample
    from codex_connection import is_wsl_source
    if is_wsl_source(home):return sample('degraded','wsl_logs_only')
    home=Path(home)
    if read_unread_sessions(home) is None:
        return sample('unavailable','read_schema' if (home/'.codex-global-state.json').exists() else 'read_missing')
    busy=False
    for filename,table,columns in [('state_5.sqlite','thread_read_receipts',('thread_id','last_published_turn')),
                                   ('thread_history_1.sqlite','thread_turns',('thread_id','turn_id','status','rollout_ordinal'))]:
        if not (home/filename).is_file():continue
        try:
            with closing(sqlite3.connect((home/filename).as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
                db.execute('SELECT '+','.join(columns)+' FROM '+table+' LIMIT 1').fetchone()
            return sample('available','ok',time.time())
        except sqlite3.OperationalError as error:busy=busy or 'locked' in str(error).lower() or 'busy' in str(error).lower()
        except (OSError,sqlite3.Error):pass
    return sample('degraded' if busy else 'unavailable','database_busy' if busy else 'read_schema')

def seen_completed_turns(home,pending,continuations=None):
    if not pending:return []
    home=Path(home);unread=read_unread_sessions(home)
    if unread is None:return []
    aliases=continuations or {}
    unread=unread|{aliases[s] for s in unread if s in aliases}
    keys=[(session_id(s),str(t)) for s,t in pending if session_id(s) not in unread and t]
    if not keys:return []
    published={}
    try:
        with closing(sqlite3.connect((home/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            for start in range(0,len(keys),128):
                chunk=keys[start:start+128];slots=','.join('?' for _ in chunk)
                published.update(db.execute('SELECT thread_id,last_published_turn FROM thread_read_receipts WHERE thread_id IN ('+slots+')',[s for s,t in chunk]))
    except (OSError,sqlite3.Error,ValueError):pass
    accepted={(s,t) for s,t in keys if published.get(s)==t}
    # Paginated desktop history can omit or leave stale thread_read_receipts.
    # Verify the exact pending turn, not just the latest turn: a new task can
    # already be running, or a formerly announced completion can settle as
    # failed/interrupted. Stable thread-level read evidence acknowledges those
    # old terminal notices too. Missing/unfinished/unknown turns stay pending.
    fallback=[(s,t) for s,t in keys if (s,t) not in accepted]
    parents=set(aliases.values())
    continued=[key for key in fallback if key[0] in parents]
    if continued:
        accepted.update((s,t) for s,t,_ in terminal_conversations(home,continued,aliases))
        fallback=[key for key in fallback if key[0] not in parents]
    if fallback:
        try:
            with closing(sqlite3.connect((home/'thread_history_1.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
                for start in range(0,len(fallback),128):
                    chunk=fallback[start:start+128];slots=','.join('(?,?)' for _ in chunk)
                    accepted.update(db.execute("WITH pending(thread_id,turn_id) AS (VALUES "+slots+") SELECT a.thread_id,a.turn_id FROM thread_turns a JOIN pending p ON a.thread_id=p.thread_id AND a.turn_id=p.turn_id WHERE a.status IN ('completed','failed','interrupted')",[value for key in chunk for value in key]))
        except (OSError,sqlite3.Error,ValueError):pass
    return [key for key in keys if key in accepted]


class ReadAcknowledgements:
    """Wait for stable read evidence; reset on unread, unknown or a new turn."""
    def __init__(self,settle_seconds=4):self.first_read={};self.settle_seconds=settle_seconds
    def poll(self,home,pending,now=None,continuations=None):
        now=time.monotonic() if now is None else now
        candidates=seen_completed_turns(home,pending,continuations)
        self.first_read={key:self.first_read.get(key,now) for key in candidates}
        return [key for key in candidates if now-self.first_read[key]>=self.settle_seconds]

def terminal_conversations(home,pairs,continuations=None):
    """Bounded exact-turn repair for a missed log/IPC terminal, read-only."""
    pairs=list(dict.fromkeys((session_id(s),str(t)) for s,t in pairs if s and t))[:128]
    if not pairs:return []
    aliases=continuations or {}
    wanted=set(pairs)
    sources=[(branch,turn) for branch,parent in aliases.items() for sid,turn in pairs if sid==parent]
    lookups=pairs+sources
    latest={}
    try:
        with closing(sqlite3.connect((Path(home)/'thread_history_1.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            for start in range(0,len(lookups),128):
                batch=lookups[start:start+128];slots=','.join('(?,?)' for _ in batch)
                rows=db.execute("WITH wanted(thread_id,turn_id) AS (VALUES "+slots+") SELECT a.thread_id,a.turn_id,a.status,a.rollout_ordinal FROM thread_turns a JOIN wanted p ON a.thread_id=p.thread_id AND a.turn_id=p.turn_id WHERE a.rollout_ordinal=(SELECT MAX(b.rollout_ordinal) FROM thread_turns b WHERE b.thread_id=a.thread_id AND b.turn_id=a.turn_id)",[v for pair in batch for v in pair])
                for source,turn,status,ordinal in rows:
                    sid=aliases.get(source,source)
                    if (sid,turn) not in wanted:continue
                    rank=(ordinal,source!=sid,source)
                    if (sid,turn) not in latest or rank>latest[sid,turn][0]:latest[sid,turn]=(rank,status)
        return [(sid,turn,status) for (sid,turn),(_,status) in latest.items() if status in ('completed','failed','interrupted')]
    except (OSError,sqlite3.Error,ValueError):return []


def active_conversations(home,continuations=None):
    home=Path(home)
    aliases=continuations or {}
    try:
        with closing(sqlite3.connect((home/'thread_history_1.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            rows=db.execute("SELECT thread_id,turn_id,status,rollout_ordinal FROM thread_turns a WHERE rollout_ordinal=(SELECT MAX(rollout_ordinal) FROM thread_turns b WHERE b.thread_id=a.thread_id)"+("" if aliases else " AND status='inProgress'")).fetchall()
        with closing(sqlite3.connect((home/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            eligible={sid:(name or title) for sid,name,title in db.execute("SELECT id,name,title FROM threads WHERE archived=0 AND (agent_path IS NULL OR agent_path='' OR agent_path='/root') AND (COALESCE(name,'')<>'' OR title<>'' OR has_user_event=1)")}
        candidates=[(source,aliases.get(source,source),turn,status,ordinal) for source,turn,status,ordinal in rows if aliases.get(source,source) in eligible]
        excluded=non_user_sessions(home,{sid for source,root,*_ in candidates for sid in (source,root)})
        latest={}
        for source,sid,turn,status,ordinal in candidates:
            if source in excluded or sid in excluded:continue
            rank=(ordinal,source!=sid,source)
            if sid not in latest or rank>latest[sid][0]:latest[sid]=(rank,turn,status)
        active=[(sid,turn) for sid,(_,turn,status) in latest.items() if status=='inProgress']
        return [dict(kind='status',session=sid,turn=turn,state='working',title=eligible[sid],text='任务正在进行',active=len(active),historical_snapshot=True) for sid,turn in active]
    except (OSError,sqlite3.Error,ValueError):return []
