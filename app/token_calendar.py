"""Incremental local token accounting. Persist counters, never conversation content."""
import calendar
import hashlib
import json
import math
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime,timedelta
from pathlib import Path

def counter(value):
    if isinstance(value,int) and not isinstance(value,bool) and 0<=value<2**62:return value
    return None

def compact_tokens(value):
    if value>=1_000_000_000:return f'{value/1_000_000_000:.2f}B'
    if value>=1_000_000:return f'{value/1_000_000:.2f}M'
    if value>=1000:return f'{value/1000:.1f}K'
    return str(value)

def month_bounds(now=None):
    current=datetime.fromtimestamp(time.time() if now is None else now)
    start=current.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
    return start,end

class TokenUsageIndex:
    def __init__(self,path,home=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.legacy_path=self.path
        self.home=__import__('codex_connection').data_home(home)
        # Each selected source has an independent index; retain the old database
        # untouched rather than guessing which mixed historical rows belong here.
        import hashlib,os
        source=__import__('codex_connection').source_identity(self.home)
        key=hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]
        self.path=self.path.with_name(self.path.stem+'-source-'+key+self.path.suffix)
        self.format_known={}
        self.legacy_import_pending=False
        from log_catalog import LogCatalog
        self.catalog=LogCatalog(self.home)
        self._maintenance=None;self._maintenance_result=None

    def prepare(self,stop=lambda:False):
        """Called by the one index worker before it opens a writable connection."""
        from index_maintenance import IndexMaintenance
        if self._maintenance_result is not None:return self._maintenance_result
        if self._maintenance is None:self._maintenance=IndexMaintenance(self.path)
        try:
            result=self._maintenance.step(stop)
        except (OSError,sqlite3.DatabaseError,ValueError,KeyError,TypeError) as error:
            self._maintenance.defer()
            # Never create a new empty index if a file swap needs recovery.
            if not self.path.is_file() or (self._maintenance.state or {}).get('phase') in ('swapping','installed'):
                raise RuntimeError('统计数据库整理尚需恢复，原文件已保留') from error
            result=dict(state='deferred',pending=False,error=type(error).__name__)
        if not result.get('pending'):self._maintenance_result=result
        return result

    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, offset INTEGER, highwater INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS usage (fingerprint TEXT PRIMARY KEY, stamp REAL, tokens INTEGER)')
        db.execute('CREATE INDEX IF NOT EXISTS usage_stamp ON usage(stamp)')
        from token_analytics import migrate
        migrate(db)
        from quota_history import migrate as migrate_quota_history
        migrate_quota_history(db)
        db.execute('CREATE TABLE IF NOT EXISTS source_identity (home TEXT PRIMARY KEY)')
        self.legacy_import_pending=False
        if not db.execute('SELECT 1 FROM source_identity').fetchone():
            if self.import_legacy(db):
                db.execute('INSERT INTO source_identity VALUES(?)',(str(self.home),));db.commit()
            else:self.legacy_import_pending=True
        return db

    def import_legacy(self,db):
        """Attribute retained history using file/session metadata; never move the old DB."""
        if __import__('codex_connection').is_wsl_source(self.home):return True
        if not self.legacy_path.is_file():return True
        savepoint=False
        try:
            with closing(sqlite3.connect(self.legacy_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=0.5)) as old:
                columns=[r[1] for r in old.execute('PRAGMA table_info(files)')]
                if not {'path','session'}<=set(columns):return True
                db.execute('SAVEPOINT legacy_copy');savepoint=True
                owned=set()
                for row in old.execute('SELECT * FROM files'):
                    record=dict(zip(columns,row))
                    if not Path(record['path']).resolve().is_relative_to(self.home):continue
                    if record['session']:owned.add(record['session'])
                    names=[c for c in ('path','offset','highwater','session','model','turn','input_water','output_water') if c in record]
                    db.execute('INSERT OR IGNORE INTO files ('+','.join(names)+') VALUES ('+','.join('?' for _ in names)+')',tuple(record[c] for c in names))
                for table in ('usage','messages'):
                    columns=[r[1] for r in old.execute('PRAGMA table_info('+table+')')]
                    if 'session' not in columns:continue
                    allowed={r[1] for r in db.execute('PRAGMA table_info('+table+')')};names=[c for c in columns if c in allowed]
                    query='INSERT OR IGNORE INTO '+table+' ('+','.join(names)+') VALUES ('+','.join('?' for _ in names)+')'
                    for row in old.execute('SELECT '+','.join(names)+' FROM '+table):
                        if row[names.index('session')] in owned:db.execute(query,row)
                db.execute('RELEASE legacy_copy');savepoint=False
            return True
        except (sqlite3.DatabaseError,OSError,ValueError,TypeError):
            if savepoint:db.execute('ROLLBACK TO legacy_copy');db.execute('RELEASE legacy_copy')
            # A busy or unreadable legacy index must be retried on the next poll.
            return False

    def scan_file(self,db,path,stop):
        from token_analytics import scan_file
        return scan_file(self,db,path,stop)

    def poll(self,now=None,stop=lambda:False,cycle=None):
        from performance_metrics import METRICS
        files=self.catalog.discover(check=True);errors=self.catalog.errors;readable=0;schema_errors=0
        self.project_files=tuple(files)
        with closing(self.connect()) as db, db:
            for path in sorted(files):
                if stop():break
                try:
                    with METRICS.span('token_scan_file'):known=self.scan_file(db,path,stop)
                    if known is False:errors+=1;schema_errors+=1
                    else:readable+=1
                except OSError:errors+=1
            result=self.snapshot(db,now,errors);result.update(log_files=len(files),readable_files=readable,format_unknown=bool(schema_errors))
            if self.legacy_import_pending:
                result['partial']=True
                result['legacy_migration_pending']=True
                result['legacy_migration_reason']='旧 Token 记录暂不可读，下次刷新重试'
            if not readable:
                result['partial']=True
                if not result.get('history_days'):result['unavailable']=True;result['report']={}
            if cycle:
                from week_cycle import summarize,usage
                used,records=usage(db,cycle)
                result['week_cycle']=summarize(cycle,used,records,
                    readable>0 and not result['partial'] and not result.get('unavailable'),now)
            from quota_history import import_step,snapshot as quota_history_snapshot
            progress=import_step(db,files,stop)
            result['quota_history']=quota_history_snapshot(db,cycle,now,
                readable>0 and not result['partial'] and not result.get('unavailable'),progress)
            from project_cost import update as update_projects,snapshot as project_snapshot
            project_progress=update_projects(db,files,stop)
            result['projects']=project_snapshot(db,time.time() if now is None else now,project_progress,files,self.home)
            from rate_index import update as rate_update,snapshot as rate_snapshot
            rate_progress=rate_update(db,files,stop)
            result['rates']=rate_snapshot(db,time.time() if now is None else now,rate_progress)
            if result['report']:result['report']['rates']=result['rates']
            return result

    def rate_step(self,stop=lambda:False):
        from rate_index import update,snapshot
        with closing(sqlite3.connect(self.path,timeout=.5)) as db,db:
            progress=update(db,self.project_files,stop)
            return snapshot(db,time.time(),progress)

    def project_step(self,stop=lambda:False):
        """Continue only the cost index; leave Token/quota history scans alone."""
        from project_cost import update
        with closing(sqlite3.connect(self.path,timeout=.5)) as db, db:
            return update(db,self.project_files,stop,budget=.15)

    def project_snapshot(self,progress):
        from project_cost import snapshot
        with closing(sqlite3.connect(self.path,timeout=.5)) as db, db:
            return snapshot(db,time.time(),progress,self.project_files,self.home)

    def snapshot(self,db,now=None,errors=0):
        now=time.time() if now is None else now;start,end=month_bounds(now)
        days={f'{start:%Y-%m}-{day:02}':0 for day in range(1,calendar.monthrange(start.year,start.month)[1]+1)}
        history=dict(db.execute("SELECT date(stamp,'unixepoch','localtime'),SUM(tokens) FROM usage WHERE stamp<=? GROUP BY date(stamp,'unixepoch','localtime')",(now,)))
        for day,value in history.items():
            if day in days:days[day]=value
        current=datetime.fromtimestamp(now);midnight=current.replace(hour=0,minute=0,second=0,microsecond=0)
        hours=[0]*24
        for hour,value in db.execute("SELECT strftime('%H',stamp,'unixepoch','localtime'),SUM(tokens) FROM usage WHERE stamp>=? AND stamp<=? GROUP BY strftime('%H',stamp,'unixepoch','localtime')",(midnight.timestamp(),now)):
            hours[int(hour)]=value
        from token_analytics import report_snapshot
        return {'report':report_snapshot(db,now),'month':start.strftime('%Y-%m'),'days':days,'total':sum(days.values()),
                'history_days':history,'history_start':min(history,default=None),'all_total':sum(history.values()),
                'today':current.strftime('%Y-%m-%d'),'hours':hours,
                'checked':now,'partial':bool(errors),'source':'本机 Codex 日志'}


TOKEN_RANGES=('all','30d','7d','day')

def usage_series(snapshot,period='30d',now=None):
    """Bounded daily bars or hourly consumption, with honest future/empty slots."""
    snapshot=snapshot or {};now=time.time() if now is None else now
    current=datetime.fromtimestamp(now);today=current.date();period=period if period in TOKEN_RANGES else '30d'
    bins=[];available=bool(snapshot) and not snapshot.get('unavailable')
    if period=='day':
        values=snapshot.get('hours') or [];available=available and snapshot.get('today')==today.isoformat() and len(values)==24
        for hour in range(24):
            value=counter(values[hour]) if available else 0
            bins.append(dict(label=f'{hour:02}:00–{hour+1:02}:00',value=value or 0,
                             future=hour>current.hour,current=hour==current.hour,start=hour,end=hour))
        return dict(mode='line',period=period,title='今日',bins=bins,total=sum(b['value'] for b in bins if not b['future']),
                    available=available,start=today.isoformat(),end=today.isoformat())
    history=snapshot.get('history_days',snapshot.get('days',{})) or {};clean={}
    for key,value in history.items():
        try:day=datetime.strptime(key,'%Y-%m-%d').date()
        except (ValueError,TypeError):continue
        if day<=today and counter(value) is not None:clean[day]=value
    start=min(clean,default=today) if period=='all' else today-timedelta(days=29 if period=='30d' else 6)
    span=(today-start).days+1;step=max(1,math.ceil(span/24)) if period=='all' else 1
    cursor=start
    while cursor<=today:
        last=min(today,cursor+timedelta(days=step-1))
        value=sum(clean.get(cursor+timedelta(days=i),0) for i in range((last-cursor).days+1))
        label=str(cursor) if cursor==last else f'{cursor} 至 {last}'
        bins.append(dict(start=cursor.isoformat(),end=last.isoformat(),label=label,value=value,current=last==today,future=False))
        cursor=last+timedelta(days=1)
    return dict(mode='bars',period=period,title={'all':'全部','30d':'30天','7d':'7天'}[period],bins=bins,
                total=sum(b['value'] for b in bins),available=available,start=start.isoformat(),end=today.isoformat(),bucket_days=step)
