"""Read portable desktop membership by session ID; paths are never membership lists."""
import json,sqlite3
from pathlib import Path
from contextlib import closing

def parent_of(source):
    if isinstance(source,str):
        try:source=json.loads(source)
        except (ValueError,TypeError):return None
    if not isinstance(source,dict):return None
    child=source.get('subagent')
    if not isinstance(child,dict):return None
    spawn=child.get('thread_spawn') or child.get('threadSpawn') or child
    if isinstance(spawn,dict):return spawn.get('parent_thread_id') or spawn.get('parentThreadId')

def read_membership(home,ledger):
    from project_cost import project_path
    ledger.execute('CREATE TABLE IF NOT EXISTS cost_project_catalog(id TEXT PRIMARY KEY,name TEXT,path TEXT)')
    ledger.execute('CREATE TABLE IF NOT EXISTS cost_parent(session TEXT PRIMARY KEY,parent TEXT)')
    catalog={key:dict(name=name,path=path) for key,name,path in ledger.execute('SELECT * FROM cost_project_catalog')}
    parents=dict(ledger.execute('SELECT * FROM cost_parent'));overrides={};metadata={};health=dict(projects=False,threads=False)
    home=Path(home)
    try:
        state=json.loads((home/'.codex-global-state.json').read_text(encoding='utf-8'))
        projects=state.get('local-projects')
        assignments=state.get('thread-project-assignments')
        if not isinstance(projects,dict) or not isinstance(assignments,dict):raise ValueError('Unsupported membership format')
        health['projects']=True
        for key,p in projects.items():
            if not isinstance(p,dict):continue
            roots=p.get('rootPaths') or [];root=next((r for r in roots if isinstance(r,str) and r.strip()),'')
            item=dict(name=str(p.get('name') or root or key),path=project_path(root))
            identity='project:'+key
            if catalog.get(identity)!=item:
                catalog[identity]=item;ledger.execute('INSERT OR REPLACE INTO cost_project_catalog VALUES (?,?,?)',(identity,item['name'],item['path']))
        for sid,a in assignments.items():
            key=a.get('projectId') if isinstance(a,dict) else a if isinstance(a,str) else None
            if key and key in projects and 'project:'+key in catalog:overrides[sid]='project:'+key
            elif a is None or (isinstance(a,dict) and 'projectId' in a and a['projectId'] is None):overrides[sid]=None
        # A successfully read complete map can revoke a previously explicit assignment.
        if ledger.execute("SELECT 1 FROM sqlite_master WHERE name='cost_session_assignment'").fetchone():
            for sid,project in ledger.execute('SELECT session,project FROM cost_session_assignment'):
                if project.startswith('project:') and sid not in assignments:overrides[sid]=None
    except (OSError,ValueError,TypeError,AttributeError):pass
    try:
        with closing(sqlite3.connect((home/'state_5.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            cols={r[1] for r in db.execute('PRAGMA table_info(threads)')}
            fields=[k for k in ('id','cwd','archived','source','agent_path','attached_thread_parent_id','project_id') if k in cols]
            if 'id' in fields:
                health['threads']=True
                from session_read_state import is_subagent_metadata
                for row in db.execute('SELECT '+','.join(fields)+' FROM threads'):
                    m=dict(zip(fields,row));sid=m['id'];metadata[sid]=m
                    pid=m.get('project_id')
                    if sid not in overrides and pid:
                        key='project:'+pid
                        if key not in catalog:
                            path=project_path(m.get('cwd'));catalog[key]=dict(name=Path(path).name or pid,path=path)
                        overrides[sid]=key
                    if is_subagent_metadata(m):
                        parent=parent_of(m.get('source')) or m.get('attached_thread_parent_id')
                        if isinstance(parent,str) and parent!=sid and parents.get(sid)!=parent:
                            parents[sid]=parent;ledger.execute('INSERT OR REPLACE INTO cost_parent VALUES (?,?)',(sid,parent))
    except (OSError,sqlite3.Error,ValueError):pass
    return overrides,catalog,parents,metadata,health

def root_session(sid,parents):
    seen=set();current=sid
    while current in parents:
        if current in seen:return sid
        seen.add(current);current=parents[current]
    return current
