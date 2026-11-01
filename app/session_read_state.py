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
                    if owner==parent:inherited_parent=True
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


def conversation_names(home,ids):
    """Fetch only display names for tracked sessions from the desktop store."""
    ids=list(dict.fromkeys(session_id(sid) for sid in ids if sid))
    if not ids:return {}
    try:
        with closing(sqlite3.connect((Path(home)/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            found={}
            for start in range(0,len(ids),128):
                chunk=ids[start:start+128];rows=db.execute('SELECT id,name,title FROM threads WHERE id IN ('+','.join('?' for _ in chunk)+')',chunk)
                found.update({sid:(name or title).strip() for sid,name,title in rows if (name or title or '').strip()})
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

def seen_completed_turns(home,pending):
    if not pending:return []
    home=Path(home);unread=read_unread_sessions(home)
    if unread is None:return []
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
    if fallback:
        try:
            with closing(sqlite3.connect((home/'thread_history_1.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
                terminal=set()
                for start in range(0,len(fallback),128):
                    chunk=fallback[start:start+128];slots=','.join('(?,?)' for _ in chunk)
                    rows=db.execute("WITH pending(thread_id,turn_id) AS (VALUES "+slots+") SELECT a.thread_id,a.turn_id FROM thread_turns a JOIN pending p ON a.thread_id=p.thread_id AND a.turn_id=p.turn_id WHERE a.status IN ('completed','failed','interrupted')",[value for key in chunk for value in key])
                    terminal.update(rows)
            accepted.update(terminal)
        except (OSError,sqlite3.Error,ValueError):pass
    return [key for key in keys if key in accepted]


class ReadAcknowledgements:
    """Wait for stable read evidence; reset on unread, unknown or a new turn."""
    def __init__(self,settle_seconds=4):self.first_read={};self.settle_seconds=settle_seconds
    def poll(self,home,pending,now=None):
        now=time.monotonic() if now is None else now
        candidates=seen_completed_turns(home,pending)
        self.first_read={key:self.first_read.get(key,now) for key in candidates}
        return [key for key in candidates if now-self.first_read[key]>=self.settle_seconds]

def terminal_conversations(home,pairs):
    """Bounded exact-turn repair for a missed log/IPC terminal, read-only."""
    pairs=list(dict.fromkeys((session_id(s),str(t)) for s,t in pairs if s and t))[:128]
    if not pairs:return []
    try:
        with closing(sqlite3.connect((Path(home)/'thread_history_1.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            slots=','.join('(?,?)' for _ in pairs)
            rows=db.execute("WITH wanted(thread_id,turn_id) AS (VALUES "+slots+") SELECT a.thread_id,a.turn_id,a.status FROM thread_turns a JOIN wanted p ON a.thread_id=p.thread_id AND a.turn_id=p.turn_id WHERE a.rollout_ordinal=(SELECT MAX(b.rollout_ordinal) FROM thread_turns b WHERE b.thread_id=a.thread_id AND b.turn_id=a.turn_id) AND a.status IN ('completed','failed','interrupted')",[v for pair in pairs for v in pair])
            return list(rows)
    except (OSError,sqlite3.Error,ValueError):return []


def active_conversations(home):
    home=Path(home)
    try:
        with closing(sqlite3.connect((home/'thread_history_1.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            active=db.execute("SELECT thread_id,turn_id FROM thread_turns a WHERE status='inProgress' AND rollout_ordinal=(SELECT MAX(rollout_ordinal) FROM thread_turns b WHERE b.thread_id=a.thread_id)").fetchall()
        with closing(sqlite3.connect((home/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            eligible={sid:(name or title) for sid,name,title in db.execute("SELECT id,name,title FROM threads WHERE archived=0 AND (agent_path IS NULL OR agent_path='' OR agent_path='/root') AND (COALESCE(name,'')<>'' OR title<>'' OR has_user_event=1)")}
        excluded=subagent_sessions(home,[sid for sid,turn in active])
        eligible={sid:title for sid,title in eligible.items() if sid not in excluded}
        return [dict(kind='status',session=sid,turn=turn,state='working',title=eligible[sid],text='任务正在进行',active=len([x for x,t in active if x in eligible]),historical_snapshot=True) for sid,turn in active if sid in eligible]
    except (OSError,sqlite3.Error,ValueError):return []
