"""Bailong desktop companion with Codex status and account data."""
from theme_registry import color as theme_color
import ctypes
import json
import math
import os
import random
import sys
import threading
import queue
import time
from pathlib import Path

# Companion watcher has no GUI, Qt initialization or animation resources.
if __name__=='__main__' and '--cleanup-storage-migration' in sys.argv:
    from storage_locations import cleanup_main
    raise SystemExit(cleanup_main(sys.argv[sys.argv.index('--cleanup-storage-migration')+1]))
if __name__=='__main__' and '--watch-codex' in sys.argv:
    from codex_startup import main as watch_codex
    raise SystemExit(watch_codex())

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPoint, QRectF, QUrl
from PySide6.QtGui import QIcon, QPainter, QPixmap, QCursor, QFontDatabase, QDesktopServices, QColor, QPen
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QProgressBar, QLabel
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from pet import Pet, Bubble, ROOT, QuotaWorker
from enhanced_core import RolloutTail, motion_step, clean_text, windows_from_limits
from version import VERSION
from reset_watch import LocalResetEvidence, locally_reset, ResetTracker, fetch_feed, schedule_text, account_reset_text, SOURCE_URL, local_time
from token_calendar import TokenUsageIndex
from refresh_flow import RefreshCoordinator, RefreshRuns
from hover_hints import TrayHints

STATE_DIR=Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'BailongEnhanced'
STATE_DIR.mkdir(parents=True,exist_ok=True)
CONFIG=STATE_DIR/'settings.json'

def save_json(path,value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)

class ActivityThread(QThread):
    event=Signal(object)
    def __init__(self,parent=None,home=None):
        super().__init__(parent)
        self.stop=threading.Event()
        self.tail=RolloutTail(home)
        from live_rate import LiveOutputRate
        self.output_rate=LiveOutputRate();self.tail.rate_observer=self.output_rate.ingest;self.last_output_rate=None
        from codex_connection import is_wsl_source
        from wsl_codex import state_dir
        self.wsl=is_wsl_source(self.tail.home);self.session_dir=state_dir(STATE_DIR,self.tail.home)
        self.token_index=TokenUsageIndex(STATE_DIR/'token-usage.sqlite3',home);self.last_token_scan=0;self.token_wake=threading.Event();self.token_reader=None
        self.week_cycle=None
        self.token_runs=RefreshRuns()
        self.last_presence_scan=0;self.presence_reader=None;self.desktop_open=None;self.last_read_scan=0;self.seed_status_sent=False;self.last_name_scan=-10;self.conversation_names={}
        from session_read_state import ReadAcknowledgements
        self.read_acknowledgements=ReadAcknowledgements()
        self.live_reader=None;self.live_events=queue.SimpleQueue()
        self.last_health_scan=-10
        from activity_targets import ActivityTargets
        self.targets=ActivityTargets();self.context_lock=threading.Lock();self.displayed=();self.visited=();self.last_active_scan=-20
    def run(self):
        from codex_live_status import LiveStatusReader
        if self.wsl:
            from wsl_codex import LogOnlyLiveReader
            LiveStatusReader=LogOnlyLiveReader
        self.live_reader=LiveStatusReader(self.stop,
            lambda sid,on,turn:self.live_events.put(('compacting',sid,on,turn)),
            lambda sid,reason,turn:self.live_events.put(('waiting',sid,reason,turn)),
            lambda sid,on,turn:self.live_events.put(('activity',sid,on,turn)),
            lambda sid,status,turn:self.live_events.put(('terminal',sid,status,turn)))
        self.live_reader.start()
        while not self.stop.is_set():
            if self.wsl:
                from wsl_codex import running,unc_parts
                if not running(unc_parts(self.tail.home)[0]):
                    if time.monotonic()-self.last_health_scan>=10:
                        self.last_health_scan=time.monotonic()
                        self.event.emit(dict(kind='connection_health',capabilities={key:dict(state='unavailable',code='wsl_stopped') for key in ('tasks','completion','tokens','compaction')}))
                    if self.token_wake.is_set() and (self.token_reader is None or not self.token_reader.is_alive()):
                        self.token_wake.clear();self.token_reader=threading.Thread(target=self.read_tokens,name='BailongWslUnavailable',daemon=True);self.token_reader.start()
                    self.stop.wait(1);continue
            if time.monotonic()-self.last_presence_scan>=5:
                self.last_presence_scan=time.monotonic()
                if self.presence_reader is None or not self.presence_reader.is_alive():
                    self.presence_reader=threading.Thread(target=self.read_presence,name='BailongCodexPresence',daemon=True);self.presence_reader.start()
            try:
                from session_read_state import session_id,active_conversations,conversation_names
                from enhanced_core import Session
                try:pending=json.loads((self.session_dir/'task-notifications.json').read_text(encoding='utf-8')).get('unread',[])
                except (OSError,ValueError,AttributeError):pending=[]
                pending=[k for k in pending if isinstance(k,list) and len(k)==2 and all(isinstance(v,str) for v in k)]
                seeds=[]
                if time.monotonic()-self.last_active_scan>=15:
                    self.last_active_scan=time.monotonic();seeds=[] if self.wsl else active_conversations(self.tail.home)
                    existing={session_id(s) for s in self.tail.reducer.sessions}
                    for e in seeds:
                        if session_id(e['session']) not in existing:
                            self.tail.reducer.sessions[e['session']]=Session(title=e['title'],state='working',turn=e['turn'],done=False,updated=time.monotonic())
                with self.context_lock:displayed=self.displayed;visited=self.visited
                self.targets.sync(self.tail.reducer.sessions,pending,displayed,visited)
                self.tail.set_pins(self.targets.pinned());batch=self.tail.poll()
                live_rate=self.output_rate.snapshot()
                for item in live_rate['details']:
                    record=self.tail.reducer.sessions.get(item['session'])
                    item['name']=self.conversation_names.get(session_id(item['session'])) or (record.title if record else '') or '会话 '+session_id(item['session'])[:8]
                if live_rate!=self.last_output_rate:
                    self.last_output_rate=live_rate;self.event.emit(dict(kind='live_output_rate',value=live_rate))
                if not self.seed_status_sent:
                    self.seed_status_sent=True
                    states={session_id(sid):v for sid,v in self.tail.reducer.sessions.items()}
                    batch.extend(e for e in seeds if not states.get(session_id(e['session']),Session()).done)
                self.targets.sync(self.tail.reducer.sessions,pending,displayed,visited)
                self.live_reader.set_targets(self.targets.ipc_targets())
                while not self.live_events.empty():
                    phase,sid,value,turn=self.live_events.get_nowait();target=self.targets.alias(sid)
                    if target in self.tail.reducer.sessions:
                        if phase=='terminal':
                            batch.extend(self.tail.reducer.terminate(target,value,turn));continue
                        if phase=='activity':
                            batch.append(dict(kind='animation_lifecycle',session=target,turn=turn,active=value));continue
                        apply=self.tail.reducer.set_waiting if phase=='waiting' else self.tail.reducer.set_compacting
                        batch.extend(apply(target,value,turn))
                if time.monotonic()-self.last_name_scan>=3:
                    self.last_name_scan=time.monotonic()
                    ids=self.targets.choose('names',128);names={} if self.wsl else conversation_names(self.tail.home,ids)
                    if names:
                        self.conversation_names.update(names)
                        self.conversation_names={sid:name for sid,name in self.conversation_names.items() if sid in self.targets.entries}
                        self.event.emit(dict(kind='conversation_names',names=names))
                from session_read_state import session_id
                for event in batch:
                    name=self.conversation_names.get(session_id(event.get('session','')))
                    if name:event['title']=name;event['conversation_name']=name
                    self.event.emit(event)
                if self.desktop_open is not True:self.read_acknowledgements.first_read.clear()
                if self.desktop_open is True and time.monotonic()-self.last_read_scan>=2:
                    self.last_read_scan=time.monotonic()
                    seen=self.read_acknowledgements.poll(self.tail.home,pending)
                    if seen:self.event.emit(dict(kind='read_receipts',seen=seen))
                if time.monotonic()-self.last_health_scan>=10:
                    self.last_health_scan=time.monotonic()
                    from session_read_state import read_tracking_probe
                    read=read_tracking_probe(self.tail.home)
                    if self.desktop_open is False and read['state']=='available':read.update(state='degraded',code='codex_closed')
                    values=dict(tasks=self.tail.health,completion=dict(self.tail.health),read=read,compaction=self.live_reader.health_snapshot())
                    self.event.emit(dict(kind='connection_health',capabilities=values))
            except Exception:
                self.event.emit({'kind':'monitor_error','text':'状态监听暂时不可用，稍后重试'})
                self.event.emit(dict(kind='connection_health',capabilities={key:dict(state='unavailable',code='logs_unreadable') for key in ('tasks','completion')}))
            due=time.monotonic()-self.last_token_scan>=30 or self.token_wake.is_set()
            if due and not self.stop.is_set() and (self.token_reader is None or not self.token_reader.is_alive()):
                self.last_token_scan=time.monotonic();self.token_wake.clear()
                self.token_runs.reserve()
                self.token_reader=threading.Thread(target=self.read_tokens,name='BailongTokenIndex',daemon=True)
                self.token_reader.start()
            self.stop.wait(1)
        if self.token_reader:self.token_reader.join(4)
        if self.presence_reader:self.presence_reader.join(1)
        if self.live_reader:self.live_reader.join(2)
    def set_context(self,displayed,visited=()):
        with self.context_lock:self.displayed=tuple(displayed);self.visited=tuple(visited)
    def set_week_cycle(self,cycle):
        with self.context_lock:
            if self.week_cycle==cycle:return
            self.week_cycle=cycle
        self.token_wake.set()
    def read_presence(self):
        from desktop_services import codex_desktop_open
        try:value=codex_desktop_open()
        except Exception:value=None
        self.desktop_open=value
        if not self.stop.is_set():self.event.emit(dict(kind='codex_presence',open=value))
    def read_tokens(self):
        run,_=self.token_runs.reserve()
        self.event.emit({'kind':'token_busy','busy':True,'run_id':run})
        terminal=None;health=None;snapshot=None
        try:
            if self.wsl:
                from wsl_codex import running,unc_parts
                if not running(unc_parts(self.tail.home)[0]):raise RuntimeError('WSL source unavailable')
            prepare=getattr(self.token_index,'prepare',None)
            if prepare:
                maintenance=prepare(self.stop.is_set)
                self.event.emit(dict(kind='database_maintenance',value=maintenance))
                if self.stop.is_set():return
                if maintenance.get('pending'):
                    self.last_token_scan=min(self.last_token_scan,time.monotonic()-29)
                    health=dict(kind='connection_health',capabilities={'tokens':dict(state='degraded',code='index_maintenance')})
                    return
            with self.context_lock:cycle=self.week_cycle
            options=dict(stop=self.stop.is_set)
            if cycle:options['cycle']=cycle
            snapshot=self.token_index.poll(**options)
            if (snapshot.get('quota_history') or {}).get('pending'):
                # Bound each import slice and allow the UI/status worker to run.
                # Continue in five seconds without adding a GUI timer or scanner.
                self.last_token_scan=min(self.last_token_scan,time.monotonic()-25)
            if not self.stop.is_set():
                terminal={'kind':'token_usage','snapshot':snapshot,'run_id':run}
                code=('token_schema' if snapshot.get('format_unknown') else 'token_missing') if snapshot.get('unavailable') else 'token_cached' if snapshot.get('readable_files')==0 else 'token_partial' if snapshot.get('partial') else 'ok'
                state='unavailable' if snapshot.get('unavailable') else 'degraded' if code!='ok' else 'available'
                health=dict(kind='connection_health',capabilities={'tokens':dict(state=state,code=code,success_at=snapshot.get('checked') if state!='unavailable' else None)})
        except Exception:
            if not self.stop.is_set():
                terminal={'kind':'token_usage_error','run_id':run}
                health=dict(kind='connection_health',capabilities={'tokens':dict(state='unavailable',code='unavailable')})
        finally:
            # A click from the terminal event handler must reserve a new read,
            # never join the result that handler has already consumed.
            self.token_runs.complete(run)
            if not self.stop.is_set():
                if terminal:self.event.emit(terminal)
                if health:self.event.emit(health)
                self.event.emit({'kind':'token_busy','busy':False,'run_id':run})
        if snapshot and (snapshot.get('rates') or {}).get('pending'):
            # Share the background index worker. Yield frequently and publish at most once/second.
            deadline=time.monotonic()+3;last_publish=0
            try:
                while not self.stop.is_set() and not self.token_wake.is_set() and time.monotonic()<deadline:
                    rates=self.token_index.rate_step(self.stop.is_set)
                    if not rates['pending'] or time.monotonic()-last_publish>=1:
                        self.event.emit(dict(kind='token_rate',rates=rates));last_publish=time.monotonic()
                    if not rates['pending']:break
                    self.stop.wait(.02)
            except Exception:pass  # The next regular poll retries; never discard usage totals.
        if snapshot and (snapshot.get('projects') or {}).get('pending'):
            from project_cost_drain import drain
            try:
                drain(lambda:self.token_index.project_step(self.stop.is_set),
                      lambda progress:self.event.emit(dict(kind='project_cost',projects=self.token_index.project_snapshot(progress))),
                      self.stop.is_set,self.stop.wait,
                      lambda:self.token_wake.is_set() or time.monotonic()-self.last_token_scan>=30)
            except Exception:
                # Retain the last complete snapshot; the regular poll retries.
                pass
    def request_tokens(self):
        if self.stop.is_set():return None
        run,new=self.token_runs.reserve()
        if new:self.token_wake.set()
        return run


class ResetThread(QThread):
    ready=Signal(object,object,bool)
    failed=Signal()
    busy=Signal(bool)
    completed=Signal(int,bool)
    diagnostic=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.stop=threading.Event()
        self.wake=threading.Event()
        self.tracker=ResetTracker(STATE_DIR/'reset-watch.json')
        self.refresh_runs=RefreshRuns()
    def request_refresh(self):
        if self.stop.is_set():return None
        run,new=self.refresh_runs.reserve()
        if new:self.wake.set()
        return run
    def run(self):
        if self.tracker.snapshot:self.ready.emit(self.tracker.snapshot,[],False)
        while not self.stop.is_set():
            run,_=self.refresh_runs.reserve()
            self.wake.clear()
            self.busy.emit(True)
            success=False;phase='fetch';started=time.monotonic()
            try:
                feed=fetch_feed();phase='cache'
                snapshot,alerts=self.tracker.update(feed)
                self.diagnostic.emit(dict(state='available',code='ok',checked=time.time(),seconds=round(time.monotonic()-started,3)))
                if not self.stop.is_set():self.ready.emit(snapshot,alerts,True);success=True
            except Exception as error:
                from reset_watch import ResetCacheError,reset_failure
                if not self.stop.is_set():
                    if isinstance(error,ResetCacheError):self.ready.emit(error.snapshot,error.alerts,True)
                    self.diagnostic.emit(reset_failure(error,phase));self.failed.emit()
            finally:
                self.refresh_runs.complete(run)
                if not self.stop.is_set():self.completed.emit(run,success)
                self.busy.emit(False)
            self.wake.wait(60)

from compact_bubble import CompactBubble as HeadBubble

class EnhancedPet(Pet):
    def __init__(self,monitor=True):
        try:self.settings=json.loads(CONFIG.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.settings={}
        self.enhanced_ready=False
        super().__init__()
        self.setWindowTitle('白龙桌宠增强版')
        self.bubble.close()
        self.bubble.deleteLater()
        self.bubble=HeadBubble(self)
        from codex_connection import session_state_dir
        self.session_dir=session_state_dir(STATE_DIR)
        self.bubble.status_indicator.set_store(self.session_dir/'task-notifications.json')
        self.bubble.quotaRefreshRequested.connect(lambda:self.refresh_quota(manual=True))
        self.bubble.resetRefreshRequested.connect(self.refresh_reset_feed)
        self.bubble.tokenRefreshRequested.connect(self.refresh_tokens)
        self.bubble.refreshAllRequested.connect(self.refresh_all)
        self.bubble.token_range=self.settings.get('token_chart_range','all')
        self.bubble.tokenRangeChanged.connect(self.set_token_range)
        self.bubble.enabled=self.settings.get('bubble',True)
        self.bubble.show_quota=self.settings.get('quota_visible',True)
        self.wandering=self.settings.get('wandering',True)
        self.random_actions=self.settings.get('random_actions',True)
        self.commentary=self.settings.get('commentary',True)
        self.sound=self.settings.get('sound',True)
        self._interaction_sound=False
        self.silent_notifier=None
        self.local_reset_evidence=LocalResetEvidence(self.session_dir/'local-reset-evidence.json')
        self.quota_windows=[]
        self.quota_observed=0
        self.quota_source=''
        self.low_notified=set()
        self.last_activity={'state':'idle','text':'已连接本地 Codex，等待新消息','active':0}
        self.last_status=time.monotonic()
        self.status_hold=0
        self.pending_activity=None
        self.walking=False
        self.walk_direction=1
        self.walk_target=None
        self.motion_clock=time.monotonic()
        self.next_walk=self.motion_clock+random.uniform(12,22)
        self.next_action=self.motion_clock+random.uniform(18,30)
        self._fx,self._fy=float(self.x()),float(self.y())
        self.gesture_until=0
        self.closing=False
        self.activity=None
        self.reset_worker=None
        self.reset_checked=0
        self.refresh_flow=RefreshCoordinator(self._refresh_finished)
        self.quota_runs=RefreshRuns()
        self.refresh_timeout=QTimer(self)
        self.refresh_timeout.setInterval(1000)
        self.refresh_timeout.timeout.connect(self._refresh_expire)
        self.last_reset_display=''
        self.notify_history=[]
        self.enhanced_ready=True
        # The tray icon is also the quota entry point.  Keep the last rendered
        # key so a 120-second refresh cannot cause unnecessary icon repaints.
        self._tray_base_icon=QIcon(str(ROOT/'app/branding/bailong.ico'))
        self._tray_icon_key=None
        self._tray_update_hint=''
        self._tray_quota_hint='额度：等待更新'
        self.motion_timer=QTimer(self)
        self.motion_timer.setInterval(33)
        self.motion_timer.timeout.connect(self.motion_tick)
        self.motion_timer.start()
        self.status_timer=QTimer(self)
        self.status_timer.setInterval(700)
        self.status_timer.timeout.connect(self.flush_status)
        self.status_timer.start()
        self.quota_timer=QTimer(self)
        self.quota_timer.setInterval(120000)
        self.quota_timer.timeout.connect(self.refresh_quota)
        self.quota_timer.start()
        self.diagnostic_timer=QTimer(self)
        self.diagnostic_timer.setInterval(10000)
        self.diagnostic_timer.timeout.connect(self.record_state)
        self.diagnostic_timer.start()
        if monitor and sys.platform=='win32' and getattr(sys,'frozen',False) and os.environ.get('BAILONG_ISOLATED')!='1':
            from stable_tray import StableTray
            self.tray=StableTray(self._tray_base_icon,self)
            self.tray.changed.connect(lambda:QTimer.singleShot(0,self.record_state))
            self.tray.changed.connect(lambda:self._maintain_tray_history() if self.tray.ready else None)
        else:self.tray=QSystemTrayIcon(self._tray_base_icon,self)
        self.tray.setToolTip('')
        tray_menu=QMenu()
        tray_menu.addAction('显示 / 隐藏气泡',self.toggle_bubble)
        tray_menu.addAction('立即查询额度',self.quota)
        tray_menu.addAction('随机播放动作',self.single_click)
        tray_menu.addSeparator()
        tray_menu.addAction('退出',self.close)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(lambda reason:self.toggle_bubble() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray_hover=TrayHints(self.tray,self)
        self._tray_shell_enabled=monitor and os.environ.get('BAILONG_ISOLATED')!='1'
        if self._tray_shell_enabled:self.tray.show()
        self._refresh_tray_icon()
        if self._tray_shell_enabled and sys.platform=='win32' and not hasattr(self.tray,'native_hover'):QTimer.singleShot(3500,self._maintain_tray_history)
        pos=self.settings.get('position')
        if isinstance(pos,list) and len(pos)==2:
            self.move(self.constrained_position(QPoint(int(pos[0]),int(pos[1]))))
        if monitor:
            self.activity=ActivityThread(self)
            self.activity.event.connect(self.on_activity)
            self.activity.start()
            self.reset_worker=ResetThread(self)
            self.reset_worker.ready.connect(self.on_reset_feed)
            self.reset_worker.failed.connect(self.on_reset_feed_error)
            self.reset_worker.diagnostic.connect(self.on_reset_diagnostic)
            self.reset_worker.busy.connect(self._reset_busy_changed)
            self.reset_worker.completed.connect(self._reset_refresh_finished)
            self.reset_worker.start()
            QTimer.singleShot(1800,self.refresh_quota)
        self.position_bubble()

    def save_settings(self):
        self.settings.update(wandering=self.wandering,random_actions=self.random_actions,
                             commentary=self.commentary,sound=self.sound,bubble=self.bubble.enabled,
                             quota_visible=self.bubble.show_quota,position=[self.x(),self.y()])
        save_json(CONFIG,self.settings)

    def say(self,text,ms=4000):
        if not self.enhanced_ready:
            return super().say(text,ms)
        self.bubble_timer.stop()
        self.status_hold=time.monotonic()+max(2,ms/1000 if ms else 3)
        self.bubble.message(text,speech=0<getattr(self,'message_priority',0)<10)
        self.position_bubble()

    def dismiss_bubble(self):
        if not self.enhanced_ready:return super().dismiss_bubble()
        self.status_hold=0
        self.restore_status()

    def position_bubble(self):
        if not self.enhanced_ready:return super().position_bubble()
        screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        area=screen.availableGeometry()
        x=self.x()+(self.width()-self.bubble.width())//2
        y=self.y()-self.bubble.height()-8
        if self.y()-self.bubble.placement_height()-8<area.top():y=self.y()+self.height()+8
        x=max(area.left(),min(x,area.right()-self.bubble.width()+1))
        reserve=self.bubble.report.reserved_height(self.bubble.size())+6 if self.bubble.report and self.bubble.report.requested else 0
        reserve=min(reserve,max(0,area.height()-self.bubble.height()))
        y=max(area.top()+reserve,min(y,area.bottom()-self.bubble.height()+1))
        self.bubble.move(x,y)
        if self.bubble.enabled and self.isVisible() and self.windowFlags()&Qt.WindowType.WindowStaysOnTopHint and self.can_raise_bubble():
            self.bubble.raise_()

    def can_raise_bubble(self):
        return True

    def stop_walk(self):
        self.walking=False
        self.walk_target=None
        self.next_walk=time.monotonic()+random.uniform(15,28)
        if self.mode=='walk':self.idle()

    def start_walk(self):
        if self.dragging or self.mode not in ('idle','walk'):return
        screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        area=screen.availableGeometry()
        left,right=area.left()+8,max(area.left()+8,area.right()-self.width()-8)
        # Reserve headroom for the status bubble and stay in the lower desktop band.
        top=max(area.top()+self.bubble.height()+15, area.top()+int(area.height()*0.55))
        bottom=max(top,area.bottom()-self.height()-8)
        target_x=random.uniform(left,right)
        target_y=random.uniform(top,bottom)
        self._fx,self._fy=float(self.x()),float(self.y())
        self.walk_direction=1 if target_x>=self.x() else -1
        self.walk_target=(target_x,target_y,(left,top,right,bottom))
        self.walking=True
        self.play(self.manifest['dragAnimation'],'walk')
        self.gesture_until=time.monotonic()+20

    def motion_tick(self):
        now=time.monotonic()
        dt=now-self.motion_clock
        self.motion_clock=now
        if self.walking and self.walk_target and not self.dragging:
            tx,ty,bounds=self.walk_target
            self._fx,self._fy,done=motion_step(self._fx,self._fy,tx,ty,42,dt,bounds)
            self.move(self.constrained_position(QPoint(round(self._fx),round(self._fy+math.sin(now*4)*3))))
            self.position_bubble()
            if done or now>self.gesture_until:
                self.move(self.constrained_position(QPoint(round(self._fx),round(self._fy))))
                self.stop_walk()
                self.save_settings()
        elif self.wandering and now>=self.next_walk and self.mode=='idle' and not self.dragging and now>=self.status_hold:
            self.start_walk()
        if self.random_actions and not self.walking and not self.dragging and now>=self.next_action and self.mode=='idle' and now>=self.status_hold:
            self.next_action=now+random.uniform(20,40)
            self.choose(random.choice(self.variants))

    def animate(self):
        if getattr(self,'walking',False) and self.mode=='walk':
            elapsed=time.monotonic()-self.started
            self.index=int(elapsed*24)%len(self.frames)
            self.update_frame()
            return
        super().animate()

    def draw_frame(self,painter,canvas):
        if self.mode=='walk' and getattr(self,'walk_direction',1)<0:
            painter.save()
            painter.translate(canvas.x()*2+canvas.width(),0)
            painter.scale(-1,1)
            super().draw_frame(painter,canvas)
            painter.restore()
        else:super().draw_frame(painter,canvas)

    def choose(self,item,interactive=False):
        if self.enhanced_ready:self.stop_walk()
        self._interaction_sound=interactive
        try:super().choose(item)
        finally:self._interaction_sound=False

    def single_click(self):
        self.last_click=None
        if self.variants:self.choose(random.choice(self.variants),interactive=True)

    def play_click_sound(self):
        if self.enhanced_ready and self.sound and self._interaction_sound:
            super().play_click_sound()

    def refresh_quota(self,manual=False):
        if self.closing:return None
        run,_=self.quota_runs.reserve()
        if self.quota_inflight:return run
        self.quota_generation=self.generation
        self.quota_inflight=True
        self.bubble.set_quota_busy(True)
        try:
            self.worker=QuotaWorker(self,manual=manual)
            self.worker.ready.connect(self.quota_ready)
            self.worker.failed.connect(self.quota_failed)
            self.worker.finished.connect(self.worker.deleteLater)
            self.worker.start()
        except (OSError,RuntimeError):
            self.quota_inflight=False;self.quota_runs.complete(run)
            self.bubble.set_quota_busy(False);self.worker=None
            return None
        return run

    def quota(self):
        self._interaction_sound=True
        try:self.play_click_sound()
        finally:self._interaction_sound=False
        self.stop_walk()
        self.click_timer.stop()
        self.last_click=None
        self.play(self.manifest['quotaAnimation'],'quota')
        self.bubble.show_quota=True
        self.bubble.enabled=True
        self.say('正在读取 Codex 剩余额度…',3000)
        self.refresh_quota(manual=True)

    def quota_ready(self,windows):
        run=self.quota_runs.active
        self.quota_inflight=False
        self.bubble.set_quota_busy(False)
        self.worker=None
        known=any(isinstance(w.get('remaining'),(int,float)) for w in windows)
        if not known and self.quota_windows:
            self.render_quota('接口未提供额度数值 · 下方为上次记录')
        else:self.update_quota(windows,time.time(),'live')
        self.quota_runs.complete(run)
        self.refresh_flow.result('quota',run,known)

    def quota_failed(self,error):
        run=self.quota_runs.active
        self.quota_inflight=False
        self.bubble.set_quota_busy(False)
        self.worker=None
        from cli_launch_health import STARTUP_ERRORS
        startup=getattr(error,'code',None) in STARTUP_ERRORS
        if self.quota_windows:
            self.render_quota('Codex启动失败，点击刷新重试' if startup else '接口暂不可用，下方为上次记录')
        else:
            self.bubble.quota_caption='Codex启动失败，点击刷新重试' if startup else '额度暂不可用，双击可重试'
            self.bubble.redraw()
            self.position_bubble()
            self._refresh_tray_icon()
        self.quota_runs.complete(run)
        self.refresh_flow.result('quota',run,False)

    def update_quota(self,windows,observed,source):
        if source=='session' and observed<self.quota_observed:return
        if source=='live':self._recent_live_quota=([dict(w) for w in windows],observed)
        elif source=='session':
            from quota_history import inherit_live_plan
            windows=inherit_live_plan(windows,getattr(self,'_recent_live_quota',None),observed)
        self.local_reset_evidence.observe(windows,observed,source,self.bubble.reset_snapshot)
        if source=='live' and self.activity:
            from week_cycle import context
            cycle=context(windows,self.local_reset_evidence.state,observed,source)
            self.activity.set_week_cycle(cycle)
        self.bubble.reset_snapshot=self.local_reset_evidence.decorate(self.bubble.reset_snapshot)
        self.quota_windows=windows
        self.quota_observed=observed
        self.quota_source=source
        self.render_quota()
        for window in windows:
            key=(window['name'],window.get('resetsAt'))
            value=window.get('remaining')
            if value is not None and value<=15 and key not in self.low_notified:
                self.low_notified.add(key)
                self.notify('Codex 额度提醒',f"{window['name']}额度仅剩 {value:g}%")

    def render_quota(self,caption=None):
        age=max(0,time.time()-self.quota_observed)
        expired=any(w.get('resetsAt') and w['resetsAt']<time.time() for w in self.quota_windows)
        source='接口' if self.quota_source=='live' else '会话记录'
        when=time.strftime('%H:%M',time.localtime(self.quota_observed))
        self.bubble.quota_caption=caption or f'额度 · {source} {when}'+(' · 待刷新' if age>180 or expired else '')
        self.bubble.windows=self.quota_windows
        self.bubble.redraw()
        self.position_bubble()
        self._refresh_tray_icon()

    def _tray_window(self):
        """Return the same priority window used by the capsule quota ring."""
        from island_widgets import selected_quota, valid_percent
        window=selected_quota(self.quota_windows or [])
        value=window.get('remaining')
        valid=valid_percent(value)
        rounded=round(float(value),1) if valid else None
        return window,rounded,valid

    def _tray_quota_text(self,window,value,valid):
        name=str(window.get('name') or '额度')
        if valid:
            amount=f'{value:g}%'
        elif window.get('pending'):
            amount='待刷新'
        else:
            amount='未知'
        reset=account_reset_text(window.get('resetsAt')).replace(' · ','，')
        return f'{name} {amount}\n{reset}'

    def _tray_quota_icon(self,window,value,valid):
        """Draw the circular, number-free quota ring used by the tray preview."""
        from ui_theme import TRAY_FIVE, TRAY_LOW, TRAY_WEEK, TRAY_TRACK, ISLAND
        from theme_registry import tray_palette
        colors=tray_palette()
        pixmap=QPixmap(64,64);pixmap.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring_width=10
        background=QColor(colors['surface']);background.setAlpha(235)
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(theme_color(background))
        painter.drawEllipse(QRectF(1,1,62,62))
        painter.setPen(QPen(QColor(colors['track']),ring_width,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        arc=QRectF(7,7,50,50);painter.drawEllipse(arc)
        if valid:
            name=str(window.get('name') or '')
            if value<=15:color=QColor(colors['low'])
            elif name=='一周':color=QColor(colors['week'])
            else:color=QColor(colors['five'])
            painter.setPen(QPen(color,ring_width,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            remaining=max(0,min(100,value))
            if remaining>0:painter.drawArc(arc,90*16,-round(360*16*remaining/100))
        painter.end();return QIcon(pixmap)

    def _refresh_tray_icon(self):
        if not hasattr(self,'tray'):return
        window,value,valid=self._tray_window()
        key=(str(window.get('name') or '额度'),value,bool(window.get('pending')))
        if key!=self._tray_icon_key:
            self.tray.setIcon(self._tray_quota_icon(window,value,valid))
            self._tray_icon_key=key
        self._tray_quota_hint=self._tray_quota_text(window,value,valid)
        if self.tray.toolTip():self.tray.setToolTip('')
        if hasattr(self,'tray_hover'):
            name={'一周':'周','5小时':'5小时'}.get(window.get('name'),'')
            amount=f'{value:g}%' if valid else ('待刷新' if window.get('pending') else '未知')
            title=f'{name}额度 {amount}'
            reset=local_time(window.get('resetsAt'))
            self.tray_hover.set_text(title,'下次重置 '+reset if reset else '重置时间未知')
            self.tray_hover.ensure_hook()

    def _maintain_tray_history(self):
        def maintain():
            try:
                if hasattr(self.tray,'native_hover'):
                    from tray_history import reconcile_fixed
                    reconcile_fixed(STATE_DIR,self.tray.host);return
                from tray_history import reconcile
                reconcile(STATE_DIR)
            except (OSError,ValueError,KeyError,TypeError) as error:
                # Shell history maintenance must not break the running tray or
                # introduce a periodic registry scan/retry loop.
                try:save_json(STATE_DIR/'tray-history-error.json',dict(error=str(error)[:300],at=time.time()))
                except OSError:pass
        threading.Thread(target=maintain,name='BailongTrayHistory',daemon=True).start()

    def on_activity(self,event):
        kind=event.get('kind')
        if kind=='token_busy':
            active=self.activity.token_runs.active if self.activity else None
            if event['busy'] or active is None or active==event.get('run_id'):
                self.bubble.set_token_busy(event['busy'])
        elif kind=='database_maintenance':
            self.database_maintenance=event['value']
        elif kind=='live_output_rate':
            self.bubble.live_output_rate=event['value']
            card=getattr(self.bubble,'live_rate_card',None)
            if card is not None:
                from shiboken6 import isValid
                if isValid(card):card.set_data(event['value'])
        elif kind=='token_usage':
            snapshot=event['snapshot']
            if snapshot.get('unavailable') and self.bubble.token_snapshot:
                snapshot=dict(self.bubble.token_snapshot,partial=True,refresh_failed=True)
            self.bubble.token_snapshot=snapshot;self.bubble.redraw();self.position_bubble()
            if self.bubble.report:self.bubble.report.set_snapshot(self.bubble.token_snapshot)
            self.refresh_flow.result('token',event.get('run_id'),not any(event['snapshot'].get(key) for key in ('unavailable','partial')))
        elif kind=='token_rate':
            if self.bubble.token_snapshot:
                previous=self.bubble.token_snapshot
                self.bubble.token_snapshot=dict(previous,rates=event['rates'],report=dict(previous.get('report') or {},rates=event['rates']))
                from token_charts import TokenPlot
                for plot in self.bubble.findChildren(TokenPlot):
                    plot.set_data(self.bubble.token_snapshot,plot.period)
                if self.bubble.report:self.bubble.report.set_snapshot(self.bubble.token_snapshot)
        elif kind=='project_cost':
            if self.bubble.token_snapshot:
                self.bubble.token_snapshot=dict(self.bubble.token_snapshot,projects=event['projects'])
                if self.bubble.report:self.bubble.report.set_snapshot(self.bubble.token_snapshot)
        elif kind=='token_usage_error':
            if self.bubble.token_snapshot:self.bubble.token_snapshot=dict(self.bubble.token_snapshot,partial=True,refresh_failed=True)
            else:self.bubble.token_snapshot=dict(month=time.strftime('%Y-%m'),days={},total=0,partial=True,unavailable=True)
            self.bubble.redraw()
            if self.bubble.report:self.bubble.report.set_snapshot(self.bubble.token_snapshot)
            self.refresh_flow.result('token',event.get('run_id'),False)
        elif kind=='quota':self.update_quota(event['windows'],event['observed'],'session')
        elif kind=='status':
            self.bubble.status_indicator.observe(event)
            self.last_activity=event
            self.last_status=time.monotonic()
            self.pending_activity=event
        elif kind=='complete':
            self.bubble.status_indicator.notify_complete(event)
            self.stop_walk()
            item=next((v for v in self.variants if v['id']=='18'),self.idles[0])
            self.play(item,'variant')
            title=clean_text(event.get('title','Codex 任务'),70)
            self.say('Codex 任务完成啦！\n'+title,14000)
            self.notify('Codex 任务已完成',title)
            self.refresh_quota()
        elif kind=='monitor_error':
            self.last_activity={'state':'offline','text':event['text'],'active':0}
            self.bubble.status_indicator.observe(self.last_activity)

    def restore_status(self):
        event=self.last_activity
        labels={'idle':'待命','thinking':'思考中','working':'处理中','responding':'正在回复','waiting':'待操作','complete':'已完成','interrupted':'已中断','offline':'监听异常'}
        self.bubble.heading='Codex · '+labels.get(event.get('state'),'处理中')
        active=event.get('active',0)
        if active>1:self.bubble.heading+=f' · {active} 个任务'
        text=event.get('display') or event.get('text','等待 Codex 新消息')
        if not self.commentary and event.get('state') in ('working','responding'):
            text='正在处理任务：'+event.get('title','Codex 对话')
        self.bubble.set_activity_text(text)
        self.position_bubble()

    def flush_status(self):
        # Native DPI/layout resize can arrive after text changes; keep the anchor current.
        if self.bubble.isVisible():self.position_bubble()
        reset_display=schedule_text(self.bubble.reset_snapshot)
        if reset_display!=self.last_reset_display:
            self.last_reset_display=reset_display
            self.bubble.redraw()
            self.position_bubble()
        if time.monotonic()<self.status_hold:return
        if self.pending_activity:
            self.pending_activity=None
            self.restore_status()
        elif self.status_hold:
            self.status_hold=0
            self.restore_status()
        if self.quota_observed and time.time()-self.quota_observed>180 and '待刷新' not in self.bubble.quota_caption:
            self.render_quota()

    def on_reset_feed(self,snapshot,alerts,fresh):
        snapshot=self.local_reset_evidence.decorate(snapshot)
        if locally_reset(snapshot):alerts=[a for a in alerts if a.get('kind')!='scheduled']
        self.bubble.reset_snapshot=snapshot
        if fresh:self.bubble.reset_feed_error=False
        self.reset_checked=snapshot.get('checked',0)
        self.last_reset_display=schedule_text(snapshot)
        self.bubble.redraw()
        self.position_bubble()
        if alerts:
            # One visual alert for a batch; all IDs have already been persisted.
            alert=alerts[0]
            self.say(alert['title']+'\n'+alert['text'],18000)
            self.notify(alert['title'],alert['text'])
            if any(a['kind']=='confirmed' for a in alerts):self.refresh_quota()

    def on_reset_feed_error(self):
        self.bubble.reset_feed_error=True
        self.bubble.redraw()
        self.position_bubble()

    def on_reset_diagnostic(self,record):
        self.reset_diagnostic=dict(record)
        self.bubble.reset_error_details=record if record.get('state')!='available' else None
        try:
            from desktop_core import atomic_json
            atomic_json(STATE_DIR/'reset-connection.json',record)
        except OSError:pass

    def refresh_reset_feed(self):
        if self.reset_worker and not self.closing:
            run=self.reset_worker.request_refresh()
            if run is None:return None
            self.bubble.set_reset_busy(True)
            return run
        return None

    def set_token_range(self,period):
        self.settings['token_chart_range']=period;self.save_settings()
    def refresh_tokens(self):
        if self.activity and not self.closing:
            run=self.activity.request_tokens()
            if run is None:return None
            self.bubble.set_token_busy(True)
            return run
        return None

    def refresh_all(self):
        if self.closing or self.refresh_flow.active('bubble'):return
        self.bubble.set_refresh_busy(True)
        sources=dict(quota=self.refresh_quota(manual=True),token=self.refresh_tokens(),reset=self.refresh_reset_feed())
        self._requested_refresh_sources=set(sources)
        self.refresh_flow.begin('bubble',sources)
        if self.refresh_flow.batches:self.refresh_timeout.start()

    def refresh_report(self):
        if self.closing or self.refresh_flow.active('report'):return
        if self.bubble.report:self.bubble.report.set_refresh_busy(True)
        self.refresh_flow.begin('report',dict(token=self.refresh_tokens()))
        if self.refresh_flow.batches:self.refresh_timeout.start()

    def _reset_refresh_finished(self,run,success):
        self.refresh_flow.result('reset',run,success)

    def _reset_busy_changed(self,busy):
        # An old False can be queued just before a click reserves the next read.
        pending=self.reset_worker and self.reset_worker.refresh_runs.active is not None
        self.bubble.set_reset_busy(bool(busy or pending))

    def _refresh_expire(self):
        self.refresh_flow.expire()
        if not self.refresh_flow.batches:self.refresh_timeout.stop()

    def _refresh_finished(self,scope,success,failed):
        target=self.bubble if scope=='bubble' else self.bubble.report
        partial=scope=='bubble' and failed==['reset'] and getattr(self,'_requested_refresh_sources',set())=={'quota','token','reset'}
        self.last_refresh_result=dict(scope=scope,result='partial' if partial else 'success' if success else 'failed',failed=list(failed),checked=time.time())
        if target:target.finish_refresh('partial' if partial else success)
        if not self.refresh_flow.batches:self.refresh_timeout.stop()

    def notify(self,title,text):
        self.notify_history.append({'title':title,'at':time.time()})
        if not getattr(self,'_tray_shell_enabled',False):return
        if sys.platform=='win32':
            # Qt's showMessage has no silent option. Never fall back to an audible alert.
            try:
                if getattr(type(self.tray),'silentMessage',None):
                    self.tray.silentMessage(title,clean_text(text,120));return
                from silent_notify import SilentNotifier
                if not self.silent_notifier:self.silent_notifier=SilentNotifier()
                self.silent_notifier.show(title,clean_text(text,120))
            except (OSError,ValueError):
                pass  # the head bubble remains the guaranteed visible reminder
        else:self.tray.showMessage(title,clean_text(text,120),QSystemTrayIcon.MessageIcon.Information,10000)

    def toggle_bubble(self):
        self.bubble.enabled=not self.bubble.enabled
        self.bubble.redraw()
        self.position_bubble()
        self.save_settings()

    def context_menu(self,point):
        self.stop_walk()
        menu=QMenu(self)
        menu.addAction('立即刷新额度',self.quota)
        menu.addAction('刷新重置消息',self.refresh_reset_feed)
        menu.addAction('查看重置公告来源',lambda:QDesktopServices.openUrl(QUrl(SOURCE_URL)))
        for label,attr in [('桌面自由移动','wandering'),('随机播放动作','random_actions'),('气泡展示 Codex 回复摘要','commentary'),('主动点击音效','sound')]:
            action=menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(getattr(self,attr))
            action.triggered.connect(lambda checked,a=attr:self.set_option(a,checked))
        action=menu.addAction('显示头顶状态气泡')
        action.setCheckable(True)
        action.setChecked(self.bubble.enabled)
        action.triggered.connect(self.toggle_bubble)
        action=menu.addAction('显示额度进度环')
        action.setCheckable(True)
        action.setChecked(self.bubble.show_quota)
        action.triggered.connect(self.toggle_quota)
        menu.addAction('试播移动动画',self.start_walk)
        menu.addAction('测试完成提醒',lambda:self.on_activity({'kind':'complete','title':'这是一条测试提醒'}))
        submenu=menu.addMenu('手动播放动作')
        for item in self.variants:
            submenu.addAction(item['name'],lambda v=item:self.choose(v,interactive=True))
        menu.addSeparator()
        menu.addAction('退出桌宠',self.close)
        menu.exec(point)

    def toggle_quota(self,checked):
        self.bubble.show_quota=checked
        self.bubble.redraw()
        self.position_bubble()
        self.save_settings()

    def set_option(self,attr,value):
        setattr(self,attr,value)
        if attr=='wandering' and not value:self.stop_walk()
        self.save_settings()

    def mousePressEvent(self,event):
        self.stop_walk()
        if event.button()==Qt.MouseButton.RightButton:
            self.click_timer.stop()
            self.last_click=None
            self.context_menu(event.globalPosition().toPoint())
        else:super().mousePressEvent(event)

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        self.bubble.redraw()
        self.position_bubble()
        self.save_settings()

    def runtime_state(self):
        # Diagnostics deliberately omit conversation text, titles and account identity.
        value={'ui_revision':5,'pid':os.getpid(),'windowId':int(self.winId()),'visible':self.isVisible(),
               'position':[self.x(),self.y()],'mode':self.mode,'wandering':self.wandering,
               'random_actions':self.random_actions,'bubble_visible':self.bubble.isVisible(),
               'activity':self.last_activity.get('state'),'quota_windows':len(self.quota_windows),
               'quota_source':self.quota_source,'quota_observed':self.quota_observed,
               'notifications':len(self.notify_history),'at':time.time(),
               'bubble_bounds':[self.bubble.x(),self.bubble.y(),self.bubble.width(),self.bubble.height()],
               'bubble_owned':self.bubble.parentWidget() is self,'automatic_sound':False,
               'reset_feed_checked':self.reset_checked,'reset_feed_error':self.bubble.reset_feed_error,
               'reset_connection':getattr(self,'reset_diagnostic',None),'last_refresh_result':getattr(self,'last_refresh_result',None),
               'scheduled_reset':(self.bubble.reset_snapshot or {}).get('scheduled'),
               'dashboard_card':self.bubble.dashboard_page,'token_month':(self.bubble.token_snapshot or {}).get('month'),
               'ring_types':['quota'] if self.bubble.is_island() else [],
               'ring_shape':'mini_circle' if self.bubble.is_island() else 'none',
               'ring_sweep':360 if self.bubble.is_island() else 0,'ring_tilt':0,
               'token_month_total':(self.bubble.token_snapshot or {}).get('total')}
        value['database_maintenance']=getattr(self,'database_maintenance',None)
        value['hover_hints']=dict(header_custom=True,tray_custom=True,
            tray_hook_ready=bool(getattr(self.tray,'ready',False) or self.tray_hover.hook.hwnd),tray_hook_error=getattr(self.tray,'error','') or self.tray_hover.hook.error,
            tray_watch_active=self.tray_hover.watch.isActive(),tray_native_text_empty=not bool(self.tray.toolTip()))
        return value
    def record_state(self):
        save_json(STATE_DIR/'runtime.json',self.runtime_state())

    def closeEvent(self,event):
        self.closing=True
        self.save_settings()
        for timer in (self.motion_timer,self.status_timer,self.quota_timer,self.diagnostic_timer,self.refresh_timeout,self.tick):timer.stop()
        if self.activity:
            self.activity.stop.set()
            self.activity.wait(5000)
        if self.reset_worker:
            self.reset_worker.stop.set()
            self.reset_worker.wake.set()
            self.reset_worker.wait(12000)
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.worker.wait(4000)
        self.tray_hover.close();self.tray.hide()
        if self.silent_notifier:self.silent_notifier.close()
        self.bubble.close()
        event.accept()
        QApplication.quit()


def main():
    from process_launch import configure_frozen_qt
    configure_frozen_qt()
    if '--chat-probe' in sys.argv:
        from chat_probe import run
        return run(sys.argv[sys.argv.index('--chat-probe')+1])
    if '--reset-diagnostics' in sys.argv:
        from reset_watch import reset_failure
        started=time.monotonic()
        try:
            if '--tls-only' in sys.argv:
                import ssl
                context=ssl.create_default_context()
                result=dict(state='available',code='ok',contextReady=True,certificateVerification=context.verify_mode==ssl.CERT_REQUIRED,hostnameVerification=context.check_hostname,readOnly=True,offline=True)
            else:
                feed=fetch_feed();result=dict(state='available',code='ok',events=len(feed['events']),scheduled=feed['scheduled'],seconds=round(time.monotonic()-started,3),readOnly=True)
        except Exception as error:result=reset_failure(error)
        index=sys.argv.index('--reset-diagnostics')
        if index+1<len(sys.argv):
            from desktop_core import atomic_json
            atomic_json(Path(sys.argv[index+1]),result)
        return 0 if result['state']=='available' else 1
    if '--apply-program-update' in sys.argv:
        from program_update_apply import main as apply_program
        return apply_program()
    if '--startup-probe' in sys.argv:
        from startup_probe import run
        previous=sys.argv[sys.argv.index('--previous-runtime')+1] if '--previous-runtime' in sys.argv else None
        return run(sys.argv[sys.argv.index('--startup-probe')+1],previous,'--startup-probe-child' in sys.argv)
    if '--material-probe' in sys.argv:
        from material_probe import run
        return run(sys.argv[sys.argv.index('--material-probe')+1])
    if '--card-surface-probe' in sys.argv:
        from card_surface_probe import run
        return run(sys.argv[sys.argv.index('--card-surface-probe')+1])
    if '--sustained-probe' in sys.argv:
        from sustained_probe import run
        return run(sys.argv[sys.argv.index('--sustained-probe')+1])
    if '--interaction-probe' in sys.argv:
        from interaction_probe import run
        output=Path(sys.argv[sys.argv.index('--interaction-probe')+1])
        try:return run(str(output))
        except Exception as error:
            # A failed unattended check must fail the build promptly, rather
            # than leave PyInstaller's modal error dialog waiting for a user.
            import traceback
            from desktop_core import atomic_json
            atomic_json(output,dict(passed=False,error=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
            return 1
    if '--smoke-video-probe' in sys.argv:
        from video_yield import smoke_probe
        return smoke_probe(sys.argv[sys.argv.index('--smoke-video-probe')+1])
    if '--manage' in sys.argv or Path(sys.executable).name=='白龙安装管理.exe':
        from installer import maintenance_main
        return maintenance_main()
    if '--check-connection' in sys.argv:
        from codex_connection import check_connection
        report=check_connection();save_json(STATE_DIR/'codex-connection-check.json',report)
        if '--connection-output' in sys.argv:
            index=sys.argv.index('--connection-output')
            if index+1<len(sys.argv):
                destination=Path(sys.argv[index+1]);destination.parent.mkdir(parents=True,exist_ok=True);save_json(destination,report)
        return 0
    app=QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ROOT/'app/branding/bailong.ico')))
    from typography import install_ui_font
    install_ui_font(app)
    app.setQuitOnLastWindowClosed(False)
    server_name='bailong-enhanced-local-v1'
    if '--smoke-test' in sys.argv:server_name+='-smoke-'+str(os.getpid())
    socket=QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(300):
        socket.write(b'quit' if '--quit' in sys.argv else b'settings' if '--settings' in sys.argv else b'ping' if '--from-codex' in sys.argv else b'show')
        socket.flush();socket.waitForBytesWritten(300);return 0
    if '--quit' in sys.argv:return 0
    QLocalServer.removeServer(server_name)
    server=QLocalServer()
    if not server.listen(server_name):return 1
    from desktop import DesktopPet
    pet=DesktopPet(monitor=not any(arg in sys.argv for arg in ('--preview','--smoke-test')))
    connections=[]
    def incoming():
        peer=server.nextPendingConnection();connections.append(peer)
        def receive():
            command=bytes(peer.readAll())
            if command==b'quit':pet.close()
            elif command==b'settings':pet.open_settings()
            elif command==b'ping':pass
            else:pet.recover()
            peer.disconnectFromServer()
            if peer in connections:connections.remove(peer)
        peer.readyRead.connect(receive)
        if peer.bytesAvailable():receive()
        peer.disconnected.connect(peer.deleteLater)
    server.newConnection.connect(incoming)
    if hasattr(pet,'apply_surface_visibility'):pet.apply_surface_visibility()
    else:pet.show()
    if sys.platform=='win32' and pet.isVisible():ctypes.windll.user32.ShowWindow(int(pet.winId()),4)
    pet.bubble.redraw()
    pet.position_bubble()
    from deployment_state import write_ready_receipt
    QTimer.singleShot(250,lambda:write_ready_receipt(pet,server))
    if not any(arg in sys.argv for arg in ('--preview','--smoke-test')):
        from codex_startup import ensure_watcher
        QTimer.singleShot(1600,ensure_watcher)
    if '--settings' in sys.argv:pet.open_settings()
    if '--smoke-test' in sys.argv:
        if '--smoke-report' in sys.argv:pet.open_report()
        QTimer.singleShot(4000,pet.record_state)
        QTimer.singleShot(4500,pet.close)
    if '--preview' in sys.argv:
        pet.update_quota([{'name':'5小时','remaining':68,'resetsAt':None},{'name':'一周','remaining':82,'resetsAt':None}],time.time(),'live')
        pet.bubble.quota_caption='界面演示数据 · 非真实额度'
        pet.bubble.status='正在检查代码并运行测试…'
        pet.bubble.redraw()
        def capture():
            pet.grab().save(str(ROOT/'pet-preview.png'))
            pet.bubble.grab().save(str(ROOT/'bubble-preview.png'))
            pet.close()
        QTimer.singleShot(1500,capture)
    return app.exec()

if __name__=='__main__':
    import traceback
    error_file=open(STATE_DIR/'error.log','a',encoding='utf-8',buffering=1)
    sys.stderr=error_file
    def report_error(typ,value,tb):
        traceback.print_exception(typ,value,tb,file=error_file)
    sys.excepthook=report_error
    try:sys.exit(main())
    except Exception:
        traceback.print_exc(file=error_file)
        raise
