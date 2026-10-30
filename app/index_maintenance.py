"""Owned SQLite repair: retain every record except unreachable cost associations.

Runs in the existing serial index worker. Copy/verification checkpoints are
resumable; the source stays unchanged until a verified compact copy and backup
exist. No external programs, services, registry edits or arbitrary file scans.
"""
import hashlib,json,os,shutil,sqlite3,time,uuid
from contextlib import closing
from pathlib import Path

FORMAT=1
META='cost_index_maintenance'
ROWS=256

def quote(name):return '"'+name.replace('"','""')+'"'

def mark_clean(db):
    db.execute('CREATE TABLE IF NOT EXISTS '+META+'(key TEXT PRIMARY KEY,value TEXT)')
    db.execute('INSERT OR REPLACE INTO '+META+' VALUES(?,?)',('format',str(FORMAT)))
    db.execute('INSERT OR REPLACE INTO '+META+' VALUES(?,?)',('baseline_bytes',str(db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0])))

def prune_slice(db,limit=128):
    """Bounded orphan-link sweep. Actual event/usage/history tables are untouched."""
    db.execute('CREATE TABLE IF NOT EXISTS '+META+'(key TEXT PRIMARY KEY,value TEXT)')
    meta=dict(db.execute('SELECT key,value FROM '+META))
    if float(meta.get('sweep_after',0))>time.time():return 0
    cursor=int(meta.get('sweep_cursor',0))
    rows=db.execute('SELECT rowid,path,revision FROM cost_source_events WHERE rowid>? ORDER BY rowid LIMIT ?',(cursor,limit)).fetchall()
    live=set(db.execute('SELECT path,revision FROM cost_source_active'))|set(db.execute('SELECT path,revision FROM cost_source_work'))
    obsolete=[(rowid,) for rowid,path,rev in rows if (path,rev) not in live]
    db.executemany('DELETE FROM cost_source_events WHERE rowid=? AND NOT EXISTS(SELECT 1 FROM cost_source_active a WHERE a.path=cost_source_events.path AND a.revision=cost_source_events.revision) AND NOT EXISTS(SELECT 1 FROM cost_source_work w WHERE w.path=cost_source_events.path AND w.revision=cost_source_events.revision)',obsolete)
    db.execute('INSERT OR REPLACE INTO '+META+' VALUES(?,?)',('sweep_cursor',str(rows[-1][0] if rows else 0)))
    db.execute('INSERT OR REPLACE INTO '+META+' VALUES(?,?)',('sweep_after',str(0 if rows else time.time()+3600)))
    return len(obsolete)

def identity(path):
    st=path.stat()
    with path.open('rb') as stream:header=stream.read(100)
    wal=path.with_name(path.name+'-wal')
    side=None
    if wal.exists():
        w=wal.stat()
        with wal.open('rb') as stream:
            head=stream.read(32);stream.seek(max(0,w.st_size-32));tail=stream.read(32)
        side=[w.st_size,w.st_mtime_ns,hashlib.sha256(head+tail).hexdigest()]
    return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,hashlib.sha256(header).hexdigest(),side]

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def atomic(path,value):
    temp=path.with_suffix('.json.tmp')
    with temp.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    for attempt in range(5):
        try:os.replace(temp,path);break
        except PermissionError:
            if attempt==4:raise
            time.sleep(.01*(attempt+1))

def plain(path):
    path=Path(path).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (path,*path.parents)):
        raise ValueError('Database maintenance path is a link')
    return path

def encode(row):
    def scalar(v):return {'blob':v.hex()} if isinstance(v,bytes) else v
    return json.dumps([scalar(v) for v in row],ensure_ascii=False,separators=(',',':')).encode()

def schema(db):
    objects=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name").fetchall()
    if any('VIRTUAL TABLE' in r[3].upper() for r in objects):raise ValueError('Unsupported virtual table; original retained')
    tables=[]
    for kind,name,owner,sql in objects:
        if kind!='table':continue
        if name.startswith('sqlite_'):raise ValueError('Unsupported internal table; original retained')
        fields=db.execute('PRAGMA table_xinfo('+quote(name)+')').fetchall()
        if 'WITHOUT ROWID' in sql.upper() or any(r[6] for r in fields):raise ValueError('Unsupported table layout; original retained')
        if any(r[1].lower() in ('rowid','_rowid_','oid') for r in fields):raise ValueError('Shadowed rowid; original retained')
        tables.append(dict(name=name,sql=sql,columns=[r[1] for r in fields]))
    return objects,tables

def pairs(db):
    result=set(db.execute('SELECT path,revision FROM cost_source_active'))|set(db.execute('SELECT path,revision FROM cost_source_work'))
    if any(not isinstance(v,str) for pair in result for v in pair):raise ValueError('Invalid cost source identity')
    return sorted(result)

def batch(db,table,cursor,live):
    names='rowid,'+','.join(quote(c) for c in table['columns']);name=quote(table['name'])
    if table['name']!='cost_source_events':
        rows=db.execute('SELECT '+names+' FROM '+name+' WHERE rowid>? ORDER BY rowid LIMIT ?',(cursor or 0,ROWS)).fetchall()
        return rows,(rows[-1][0] if rows else cursor),not rows
    index,last=cursor or [0,None]
    while index<len(live):
        path,rev=live[index]
        if last is None and db.execute('SELECT 1 FROM '+name+" WHERE path=? AND revision=? AND (event IS NULL OR typeof(event)!='text') LIMIT 1",(path,rev)).fetchone():raise ValueError('Invalid retained event key')
        clause=' AND event>?' if last is not None else ''
        args=(path,rev,last,ROWS) if last is not None else (path,rev,ROWS)
        rows=db.execute('SELECT '+names+' FROM '+name+' WHERE path=? AND revision=?'+clause+' ORDER BY event LIMIT ?',args).fetchall()
        if rows:return rows,[index,rows[-1][3]],False
        index+=1;last=None
    return [],[index,last],True

class IndexMaintenance:
    def __init__(self,path,*,workspace=None,preview_only=False):
        self.path=plain(path);self.folder=plain(workspace or (self.path.parent/'index-maintenance'))/self.path.name
        self.journal=self.folder/'state.json';self.done=False;self.state=None
        self.preview_only=preview_only

    def save(self):atomic(self.journal,self.state)

    def restore_failed_swap(self):
        """Keep a failed candidate for diagnosis and restore the exact old file."""
        if not self.state or self.state['phase'] not in ('swapping','installed'):return
        retired=self.file('retired');candidate=self.file('candidate')
        if retired.exists():
            if self.path.exists():
                if candidate.exists():raise ValueError('Ambiguous failed swap; all files retained')
                os.replace(self.path,candidate)
            os.replace(retired,self.path)
        if not self.path.exists():raise ValueError('Original index could not be restored')
        self.state['phase']='failed';self.save()

    def defer(self):
        self.restore_failed_swap()
        if self.state and self.state['phase']!='completed' and self.path.exists():
            self.state['phase']='failed'
            try:self.save()
            except OSError:pass  # original still exists; a later startup retries

    def file(self,key):
        name=self.state[key]
        if Path(name).name!=name or not name.startswith(self.state['job']+'-'):
            raise ValueError('Invalid owned maintenance filename')
        return plain(self.folder/name)

    def begin(self,src):
        objects,tables=schema(src)
        job=uuid.uuid4().hex
        self.folder.mkdir(parents=True,exist_ok=True);plain(self.folder)
        self.state=dict(format=FORMAT,job=job,phase='copy',source=identity(self.path),objects=objects,tables=tables,live=pairs(src),
            candidate=job+'-compact.sqlite3',backup=job+'-statistics-backup.sqlite3',retired=job+'-original.sqlite3',
            table=0,cursor=None,verified={},rows=0,started=time.time())
        with closing(sqlite3.connect(self.file('candidate'))) as dst,dst:
            dst.execute('PRAGMA synchronous=FULL')
            for table in tables:dst.execute(table['sql'])
            for key in ('user_version','application_id'):
                value=src.execute('PRAGMA '+key).fetchone()[0];dst.execute('PRAGMA '+key+'='+str(value))
        self.save()

    def recover(self):
        if not self.journal.exists():return
        self.state=json.loads(self.journal.read_text('utf-8'))
        for key in ('candidate','backup','retired'):self.file(key)
        phase=self.state['phase'];retired=self.file('retired');candidate=self.file('candidate')
        if phase in ('swapping','installed'):
            if not self.path.exists() and retired.exists():
                os.replace(retired,self.path);self.state['phase']='ready';self.save()
            elif self.path.exists() and not candidate.exists() and self.state.get('sha256') and digest(self.path)==self.state['sha256']:
                self.state['phase']='installed';self.save();self.complete()
            elif self.path.exists() and candidate.exists() and not retired.exists():
                self.state['phase']='ready';self.save()
            else:raise ValueError('Ambiguous maintenance recovery; files retained')
        elif phase=='completed':
            if retired.exists() and self.path.exists() and digest(self.file('backup'))==self.state.get('sha256'):
                retired.unlink()
            self.state=None
        elif phase=='failed':self.state=None

    def complete(self):
        # The independent compact backup retains every original statistical
        # record. Only unreachable associations are absent from it.
        backup=self.file('backup')
        if digest(backup)!=self.state['sha256'] or digest(self.path)!=self.state['sha256']:
            raise ValueError('Maintenance backup or installed copy mismatch')
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Installed compact index is invalid')
        self.state['phase']='completed';self.state['ended']=time.time();self.state['afterBytes']=self.path.stat().st_size;self.save()
        retired=self.file('retired')
        if retired.exists():
            try:retired.unlink()  # one exact owned file, after verified recovery backup
            except OSError:
                self.state['cleanupPending']=True;self.save()
        self.done=True

    def swap(self):
        if identity(self.path)!=self.state['source']:raise ValueError('Source changed; original retained')
        if digest(self.file('candidate'))!=self.state['sha256'] or digest(self.file('backup'))!=self.state['sha256']:
            raise ValueError('Verified candidate or recovery copy changed; original retained')
        with closing(sqlite3.connect(self.path,timeout=.1)) as db:
            before=db.execute('PRAGMA data_version').fetchone()[0]
            result=db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if result[0]:return False
            db.execute('BEGIN EXCLUSIVE')
            if db.execute('PRAGMA data_version').fetchone()[0]!=before:raise ValueError('Concurrent source writer')
            self.state['source']=identity(self.path);db.commit()
        # Never transplant a WAL/SHM onto a different main database.
        if any(self.path.with_name(self.path.name+suffix).exists() for suffix in ('-wal','-shm','-journal')):
            self.state['source']=identity(self.path);self.save();return False
        self.state['source']=identity(self.path);self.state['phase']='swapping';self.save()
        try:
            os.replace(self.path,self.file('retired'))
            try:os.replace(self.file('candidate'),self.path)
            except BaseException:
                os.replace(self.file('retired'),self.path);self.state['phase']='ready';self.save();raise
        except OSError:
            self.state['phase']='ready';self.save();return False
        self.state['phase']='installed';self.save();self.complete();return True

    def step(self,stop=lambda:False,budget=.15):
        if self.done:return dict(state='completed',pending=False)
        deadline=time.monotonic()+budget
        if self.state is None:self.recover()
        if self.done:return dict(state='completed',pending=False)
        if stop():return dict(state='paused',pending=True)
        if not self.path.exists():
            if self.state:raise ValueError('Maintenance source missing')
            self.done=True;return dict(state='not_needed',pending=False)
        if self.state and self.state['phase'] in ('copy','verify','backup','ready') and identity(self.path)!=self.state['source']:
            candidate=self.file('candidate')
            if candidate.exists():candidate.unlink()
            self.state=None
        if self.state and self.state['phase']=='installed':self.complete();return dict(state='completed',pending=False)
        if self.state and self.state['phase']=='ready':
            if self.preview_only:
                self.done=True;return dict(state='verified_preview',pending=False,rows=self.state['rows'],tablesVerified=len(self.state['verified']))
            return dict(state='completed' if self.swap() else 'waiting_for_database',pending=not self.done)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=.1)) as src:
            src.set_progress_handler(lambda:bool(stop()),10000)
            src.execute('BEGIN')
            tables={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'cost_source_active','cost_source_work','cost_source_events'}<=tables:
                self.done=True;return dict(state='not_needed',pending=False)
            if self.state is None:
                meta=dict(src.execute('SELECT key,value FROM '+META)) if META in tables else {}
                if meta.get('format')==str(FORMAT) and self.path.stat().st_size<=max(32*1024**2,int(meta.get('baseline_bytes',0))*4):
                    self.done=True;return dict(state='not_needed',pending=False)
                self.begin(src)
            if identity(self.path)!=self.state['source']:
                # Restart a partial copy if an older program or external writer
                # changed the database. Never apply a mixed-time copy.
                candidate=self.file('candidate')
                if candidate.exists():candidate.unlink()
                self.state=None;self.begin(src)
            with closing(sqlite3.connect(self.file('candidate'))) as dst:
                dst.set_progress_handler(lambda:bool(stop()),10000)
                while time.monotonic()<deadline and not stop():
                    phase=self.state['phase'];index=self.state['table'];plan=self.state['tables']
                    if index>=len(plan):
                        if phase=='copy':
                            with dst:
                                for kind,name,owner,sql in self.state['objects']:
                                    if kind!='table':
                                        previous=dst.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()
                                        if previous is None:dst.execute(sql)
                                        elif previous[0]!=sql:raise ValueError('Unexpected compact schema object')
                            self.state.update(phase='verify',table=0,cursor=None);self.save();continue
                        expected=self.state['verified'].get('cost_source_events',{}).get('rows',0)
                        if dst.execute('SELECT COUNT(*) FROM cost_source_events').fetchone()[0]!=expected:raise ValueError('Unexpected compact associations')
                        if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Compact index integrity failure')
                        if dst.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Compact index references invalid')
                        with dst:mark_clean(dst)
                        self.state['phase']='backup';self.save();break
                    table=plan[index];cursor=self.state['cursor'];rows,next_cursor,finished=batch(src,table,cursor,self.state['live'])
                    if phase=='copy':
                        if rows:
                            names='rowid,'+','.join(quote(c) for c in table['columns'])
                            with dst:dst.executemany('INSERT OR REPLACE INTO '+quote(table['name'])+'('+names+') VALUES('+','.join('?' for _ in range(len(rows[0])))+')',rows)
                            self.state['rows']+=len(rows)
                    else:
                        actual,_,actual_finished=batch(dst,table,cursor,self.state['live'])
                        if rows!=actual or finished!=actual_finished:raise ValueError('Statistical records changed in '+table['name'])
                        record=self.state['verified'].setdefault(table['name'],dict(rows=0,sha256='0'*64))
                        for row in rows:record['sha256']=hashlib.sha256(bytes.fromhex(record['sha256'])+encode(row)).hexdigest()
                        record['rows']+=len(rows)
                    self.state['cursor']=next_cursor
                    if finished:self.state.update(table=index+1,cursor=None)
                self.save()
                if identity(self.path)!=self.state['source']:raise ValueError('Source changed during copy')
        if self.state['phase']=='backup' and not stop():
            candidate=self.file('candidate');self.state['sha256']=digest(candidate)
            backup=self.file('backup');shutil.copy2(candidate,backup)
            if digest(backup)!=self.state['sha256']:raise ValueError('Compact recovery backup failed')
            self.state['phase']='ready';self.save()
        return dict(state=self.state['phase'],pending=True,rows=self.state['rows'],tablesVerified=len(self.state['verified']))

def before_backup(path,seconds=120):
    """Installer already owns the deployment lock and has stopped all app writers."""
    job=IndexMaintenance(path);deadline=time.monotonic()+seconds;before=Path(path).stat().st_size
    try:
        while time.monotonic()<deadline:
            result=job.step(lambda:time.monotonic()>=deadline)
            if not result.get('pending'):
                return dict(state=result['state'],beforeBytes=before,afterBytes=Path(path).stat().st_size)
            time.sleep(.01)
        return dict(state='deferred',reason='budget',beforeBytes=before)
    except (OSError,sqlite3.DatabaseError,ValueError,KeyError,TypeError) as error:
        job.defer()
        if not Path(path).is_file():raise
        return dict(state='deferred',reason=type(error).__name__,beforeBytes=before)
