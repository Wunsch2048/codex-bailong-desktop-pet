"""Persistent quota observations and conservative cross-cycle comparisons.

Only counters, timestamps and plan labels are retained. Import is incremental
and bounded; no account credentials or conversation text are stored.
"""
import json
import math
import time
from datetime import datetime

WEEK=604800


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS quota_observations (
        stamp REAL NOT NULL, deadline REAL NOT NULL, remaining REAL NOT NULL,
        source TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '', boundary REAL,
        reset_kind TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(stamp,deadline,remaining))''')
    db.execute('CREATE INDEX IF NOT EXISTS quota_observation_time ON quota_observations(stamp)')
    db.execute('CREATE TABLE IF NOT EXISTS quota_history_files (path TEXT PRIMARY KEY, offset INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS quota_cycle_snapshots (id TEXT PRIMARY KEY, record TEXT NOT NULL)')


def valid_sample(stamp,deadline,remaining):
    return (all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
                for v in (stamp,deadline,remaining)) and stamp>0 and
            stamp<deadline<=stamp+WEEK+300 and 0<=remaining<=100)


def store(db,stamp,deadline,remaining,source='log',plan='',boundary=None,reset_kind=''):
    if not valid_sample(stamp,deadline,remaining):return False
    if boundary is not None and not (isinstance(boundary,(int,float)) and
            math.isfinite(boundary) and deadline-WEEK-300<=boundary<=stamp):boundary=None
    db.execute('''INSERT INTO quota_observations VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(stamp,deadline,remaining) DO UPDATE SET
        source=CASE WHEN excluded.source='live' THEN 'live' ELSE source END,
        plan=CASE WHEN excluded.plan!='' THEN excluded.plan ELSE plan END,
        boundary=COALESCE(excluded.boundary,boundary),
        reset_kind=CASE WHEN excluded.reset_kind!='' THEN excluded.reset_kind ELSE reset_kind END''',
        (stamp,deadline,remaining,source,str(plan or '').lower()[:40],boundary,reset_kind))
    return True


def record_line(db,line):
    if b'"rate_limits"' not in line or b'token_count' not in line:return
    try:
        obj=json.loads(line);p=obj.get('payload') or {}
        if obj.get('type')!='event_msg' or p.get('type')!='token_count':return
        info=p.get('info') or {};limits=p.get('rate_limits') or info.get('rate_limits')
        if not isinstance(limits,dict) or limits.get('limit_id') not in (None,'codex'):return
        from enhanced_core import windows_from_limits
        from token_analytics import stamp_of
        stamp=stamp_of(obj)
        for w in windows_from_limits(limits):
            if w['name']=='一周':store(db,stamp,w.get('resetsAt'),w['remaining'],plan=limits.get('plan_type'))
    except (ValueError,TypeError,AttributeError):return


def import_step(db,files,stop=lambda:False,seconds=.3,max_bytes=64*1024*1024):
    """Resume at per-file byte offsets, including complete zero-usage events."""
    deadline=time.monotonic()+seconds;read=0;pending=False;errors=0
    offsets=dict(db.execute('SELECT path,offset FROM quota_history_files'))
    for path in sorted(files,reverse=True):
        key=str(path.resolve())
        try:size=path.stat().st_size
        except OSError:errors+=1;continue
        offset=offsets.get(key,0)
        if size<offset:offset=0
        if size==offset:continue
        if stop() or time.monotonic()>=deadline or read>=max_bytes:
            pending=True;continue
        try:
            with path.open('rb') as stream:
                stream.seek(offset)
                while not stop() and time.monotonic()<deadline and read<max_bytes:
                    line=stream.readline(4*1024*1024);read+=len(line)
                    if not line:break
                    if not line.endswith(b'\n'):
                        if len(line)<4*1024*1024:break
                        while line and not line.endswith(b'\n') and not stop():
                            line=stream.readline(4*1024*1024);read+=len(line)
                        if not line.endswith(b'\n'):break
                        offset=stream.tell();continue
                    offset=stream.tell();record_line(db,line)
            db.execute('INSERT OR REPLACE INTO quota_history_files VALUES(?,?)',(key,offset))
            if offset<size:pending=True
        except OSError:errors+=1
    return dict(pending=pending,errors=errors,bytes_read=read)


def capacity_doubled(previous,remaining,plan):
    """A rounded Pro denominator change, not proof of an official promotion.

    Require a material rise away from a full refill. Confirmation and unchanged
    deadline are handled by partition; never apply this to a plan change.
    """
    return bool(str(plan or '').lower() in ('pro','prolite','proheavy') and
        remaining-previous>=10 and previous<=80 and remaining<95 and
        abs(2*(100-remaining)-(100-previous))<=3)


def partition(samples):
    """Confirm rises before they affect a cycle; concurrent logs can lag."""
    cycles=[];current=None;last=None
    for sample in samples:
        stamp,deadline,remaining,source,plan,boundary,kind=sample
        if not valid_sample(stamp,deadline,remaining):continue
        if last and stamp<=last[0]:continue
        change='';candidate=None
        if current:
            if deadline<current['deadline']-1800:continue  # An old concurrent log arrived late.
            candidate=current.pop('rise_candidate',None)
            if plan and current['plan'] and plan!=current['plan']:change='changed'
            elif deadline>current['deadline']+1800:
                if stamp>=current['deadline']-120:change='natural'
                elif remaining-last[2]>=10:change='extra'
                else:change='changed'  # A shifted window without a refill is not a proven bonus.
            elif (boundary and boundary>current['start']+300 and boundary>(last[0] if last else 0)
                    and remaining>last[2]+1
                    and not capacity_doubled(last[2],remaining,current['plan'])
                    and not (candidate and capacity_doubled(last[2],candidate[2],current['plan']))):
                # A stale local-reset file can report the first post-restart
                # observation as a refill. Within the same weekly deadline,
                # a boundary hint alone must not split an unchanged/falling
                # balance and discard the already observed quota coverage.
                change=kind or 'extra'
            elif (candidate and 0<stamp-candidate[0]<=1800 and
                    remaining>last[2]+1 and remaining>=candidate[2]-2):
                if capacity_doubled(last[2],candidate[2],current['plan']):
                    # Normalize the older denominator in memory only. Preserve
                    # the cycle identity, Token interval and raw stored samples.
                    current['samples']=[tuple([s[0],s[1],100-(100-s[2])/2,*s[3:]]) for s in current['samples']]
                    current['capacity_factor']=current.get('capacity_factor',1)*2
                    current['capacity_changes']=current.get('capacity_changes',[])+[candidate[0]]
                    current['samples'].append(candidate)
                elif candidate[2]-last[2]>=10:
                    change='extra';boundary=candidate[0]
                else:
                    # A sustained small rise makes the slope unreliable, but
                    # an isolated older snapshot must not poison the whole week.
                    current['corrected']=True
                    current['samples'].append(candidate)
            elif remaining>last[2]+1:
                current['rise_candidate']=sample
                continue
        if current is None or change:
            if current:
                current['end']=min(boundary or stamp,current['deadline']) if change=='natural' else (boundary or stamp)
                current['closed']=True
            start=(boundary if boundary else deadline-WEEK) if not current or change=='natural' else (boundary or stamp)
            start=min(stamp,max(deadline-WEEK,start))
            current=dict(id=f'{int(start)}:{int(deadline)}',start=start,deadline=deadline,
                kind=change or (kind if kind in ('natural','extra') else 'inferred'),plan=plan,
                samples=[],closed=False,end=None)
            cycles.append(current)
            if candidate and boundary==candidate[0]:current['samples'].append(candidate)
        if plan:current['plan']=plan
        current['samples'].append(sample);last=sample
    return cycles


def token_span(db,start,end,models=False):
    if models:
        return list(db.execute('''SELECT model,SUM(tokens),SUM(input_tokens),SUM(output_tokens),MIN(known)
            FROM usage WHERE stamp>? AND stamp<=? GROUP BY model ORDER BY SUM(tokens) DESC''',(start,end)))
    return db.execute('SELECT COALESCE(SUM(tokens),0),COUNT(*) FROM usage WHERE stamp>? AND stamp<=?',(start,end)).fetchone()


def summarize_cycles(db,now=None,complete=True,pending=False):
    from quota_workload import profile
    now=time.time() if now is None else now
    rows=db.execute('''SELECT stamp,deadline,remaining,source,plan,boundary,reset_kind
        FROM quota_observations WHERE stamp<=? ORDER BY stamp,source''',(now,)).fetchall()
    periods=partition(rows);result=[]
    for c in periods:
        samples=c['samples']
        if not samples:continue
        first,last=samples[0],samples[-1]
        closed=c['closed'] or c['deadline']<=now
        end=c['end'] or min(now,c['deadline'])
        used,records=token_span(db,c['start']-.001,end)
        observed,observed_records=token_span(db,first[0],last[0])
        drop=first[2]-last[2]
        fresh=closed or now-last[0]<=900
        rise_pending=bool(c.get('rise_candidate'))
        valid=bool(complete and not pending and fresh and not rise_pending and
            not c.get('corrected') and drop>=5 and observed>0)
        estimate=round(observed*100/drop) if valid else None
        mix=token_span(db,first[0],last[0],True)
        model=mix[0][0] if mix else ''
        share=(mix[0][1]/observed if mix and observed else 0)
        known=bool(mix) and all(x[4] for x in mix)
        output=sum(x[3] or 0 for x in mix)/observed if observed and known else None
        # Wide observation coverage and stable workload are needed to compare.
        eligible=bool(valid and drop>=20 and len({s[2] for s in samples})>=3 and
            model and model!='未识别模型' and share>=.7 and known)
        result.append(dict(id=c['id'],start=c['start'],end=end,through=last[0],reset_at=c['deadline'],
            kind=c['kind'],closed=closed,remaining=last[2],used=used,records=records,
            estimated_total=estimate,per_percent=estimate/100 if estimate else None,
            estimate_low=round(observed*100/(drop+1)) if valid else None,
            estimate_high=round(observed*100/max(1,drop-1)) if valid else None,
            observed_tokens=observed,drop=round(max(0,drop),1),sample_count=len(samples),distinct_readings=len({s[2] for s in samples}),
            complete=bool(complete and not pending),fresh=fresh,corrected=bool(c.get('corrected')),rise_pending=rise_pending,
            capacity_factor=c.get('capacity_factor',1),capacity_changes=c.get('capacity_changes',[]),
            model=model,model_share=share,output_share=output,plan=c['plan'],eligible=eligible,
            workload=profile(db,first[0],last[0]),
            change=None,baseline=None,comparison_scope='previous',comparison_reason='尚无上一周期记录'))
    compare_cycles(result)
    return list(reversed(result))


def compare_cycles(result):
    """Re-evaluate policy even when a closed capacity came from cache."""
    from quota_workload import mismatch
    for i,item in enumerate(result):
        item.update(change=None,baseline=None,comparison_block='',comparison_scope='previous',comparison_version=1)
        item.pop('baseline_count',None);item.pop('baseline_cycle_id',None)
        item['comparison_reason']='尚无上一周期记录'
        if not item['plan']:
            item['comparison_reason']='套餐记录不足，暂不比较';continue
        if not item['eligible']:
            if not item['complete']:reason='历史记录尚未完整，暂不比较'
            elif not item['fresh']:reason='额度记录待刷新，暂不比较'
            elif item['rise_pending']:reason='额度回升待确认，暂不比较'
            elif item['corrected']:reason='额度读数曾回升，本轮暂不比较'
            elif item['drop']<20:reason=f"再记录 {20-item['drop']:g} 个百分点后可比较"
            elif item['distinct_readings']<3:reason='需至少 3 个不同余额读数后比较'
            elif not item['model'] or item['model']=='未识别模型' or item['output_share'] is None:reason='模型或输入输出记录不完整'
            elif item['model_share']<.7:reason='模型混用较多，主模型占比需达到 70%'
            else:reason='有效用量记录不足，暂不比较'
            item['comparison_reason']=reason
            continue
        if not i:continue
        old=result[i-1]
        if old['plan']!=item['plan']:
            item['comparison_reason']='套餐已变更，暂不比较';continue
        if not old['closed'] or not old['eligible']:
            item['comparison_reason']='上一周期记录不足，暂不比较';continue
        if old['model']!=item['model'] or abs(old['model_share']-item['model_share'])>.15:
            item['comparison_reason']='上一周期的主模型或使用比例不同，暂不比较';continue
        if old['output_share'] is None or abs(old['output_share']-item['output_share'])>.1:
            item['comparison_reason']='上一周期的输入输出比例不同，暂不比较';continue
        if (old['kind']=='extra')!=(item['kind']=='extra') or old['kind']=='changed' or item['kind']=='changed':
            item['comparison_reason']='上一周期的重置类型不同，暂不比较';continue
        blocked=mismatch(item,old)
        if blocked:
            item.update(comparison_reason=blocked,comparison_block=blocked);continue
        base=old['estimated_total']
        item.update(change=round((item['estimated_total']/base-1)*100,1),baseline=base,
            comparison_reason='较上一周期',baseline_count=1,baseline_cycle_id=old['id'])


def snapshot(db,cycle,now,complete,progress):
    if cycle:
        store(db,cycle['through'],cycle['reset_at'],cycle['remaining'],'live',plan=cycle.get('plan',''),
            boundary=cycle['start'] if cycle['start_source']=='detected' else None,
            reset_kind=cycle.get('reset_kind',''))
    cycles=summarize_cycles(db,now,complete and not progress['errors'],progress['pending'])
    cached=dict(db.execute('SELECT id,record FROM quota_cycle_snapshots'))
    for i,item in enumerate(cycles):
        if item['closed'] and item['complete']:
            db.execute('INSERT OR REPLACE INTO quota_cycle_snapshots VALUES(?,?)',
                (item['id'],json.dumps(item,separators=(',',':'))))
        elif item['closed'] and item['id'] in cached:
            try:
                cycles[i]=dict(json.loads(cached[item['id']]),cached=True)
                if cycles[i].get('comparison_scope')!='previous':
                    cycles[i].update(change=None,baseline=None,comparison_reason='历史对比口径待刷新')
            except (ValueError,TypeError):pass
    # Old snapshots retain factual capacity, not pre-policy comparison results.
    compare_cycles(list(reversed(cycles)))
    partial=not complete or bool(progress['errors'])
    return dict(cycles=cycles,anomaly=anomaly(cycles,now) if not partial and not progress['pending'] else None,
        pending=progress['pending'],partial=partial)


def anomaly(cycles,now=None,decline_threshold=10,increase_threshold=15):
    """Compare the preceding cycle, with independent change thresholds."""
    now=time.time() if now is None else now
    if len(cycles)<2:return None
    current,previous=cycles[:2]
    if current['closed'] or not previous['closed']:return None
    if not 0<=now-current['through']<=900:return None
    for row in (current,previous):
        if not row['eligible'] or not row['complete'] or row.get('corrected') or not row.get('plan'):return None
    if current['plan']!=previous['plan']:return None
    if current['model']!=previous['model'] or abs(current['model_share']-previous['model_share'])>.15:return None
    if current.get('output_share') is None or previous.get('output_share') is None:return None
    if abs(current['output_share']-previous['output_share'])>.1:return None
    if (current['kind']=='extra')!=(previous['kind']=='extra'):return None
    if current['kind']=='changed' or previous['kind']=='changed':return None
    from quota_workload import mismatch
    if mismatch(current,previous):return None
    estimate=current['estimated_total'];base=previous['estimated_total']
    if not estimate or not base:return None
    change=round((estimate/base-1)*100,6)
    if -decline_threshold<change<increase_threshold:return None
    if current['estimate_low']<=previous['estimate_high'] and previous['estimate_low']<=current['estimate_high']:return None
    return dict(change=round(change,1),current=estimate,previous=base,through=current['through'],
        reset_at=current['reset_at'],plan=current['plan'],cycle=current['id'],remaining=current['remaining'],
        comparison_version=1,text=f"推测容量 {change:+.0f}%",
        description=f"相近使用条件下，本轮推测 Token 容量较上一周期{'少' if change<0 else '多'} {abs(change):.1f}%。两轮均观察至少20个百分点，已检查模型分布、缓存、输入输出及速度和推理档位。\n仍会受任务差异和其他设备使用影响，不是官方额度变动确认。")


def visible_anomaly(snapshot,windows,now=None,decline_threshold=10,increase_threshold=15):
    """Do not display an older-cycle warning while new quota/Token data arrive."""
    now=time.time() if now is None else now
    snapshot=snapshot or {};history=snapshot.get('quota_history') or {};warning=history.get('anomaly')
    if history.get('cycles'):
        warning=anomaly(history['cycles'],now,decline_threshold,increase_threshold)
    if warning and warning.get('comparison_version')!=1:return None
    if not warning or -decline_threshold<warning.get('change',0)<increase_threshold or any(snapshot.get(k) for k in ('partial','unavailable','refresh_failed')):return None
    if history.get('pending') or history.get('partial'):return None
    week=next((w for w in windows if w.get('name')=='一周'),None)
    if not week or week.get('plan')!=warning['plan']:return None
    from reset_watch import epoch
    deadline=epoch(week.get('resetsAt'))
    if not deadline or deadline<=now or abs(deadline-warning['reset_at'])>1800:return None
    remaining=week.get('remaining')
    if remaining is not None and remaining>warning.get('remaining',100)+5:return None
    if not 0<=now-warning['through']<=900:return None
    return warning


def inherit_live_plan(windows,live,observed):
    """Recent logs may omit planType; keep a same-window API plan for 3 minutes."""
    if not live or not 0<=observed-live[1]<=180:return windows
    from reset_watch import epoch
    result=[]
    for item in windows:
        item=dict(item);deadline=epoch(item.get('resetsAt'))
        old=next((w for w in live[0] if w['name']==item['name']),None)
        previous=epoch(old.get('resetsAt')) if old else None
        if not item.get('plan') and old and old.get('plan') and deadline and previous and abs(deadline-previous)<=1800:
            item['plan']=old['plan']
        result.append(item)
    return result
