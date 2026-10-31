"""Persistent 16px task indicator. Animate only this widget while visible."""
import time
import json
from collections import deque
from pathlib import Path
from desktop_core import atomic_json
from session_read_state import session_id,subagent_sessions
from PySide6.QtCore import Qt,QTimer,Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget
from status_motion import GlyphMotion,busy_ring_centers,BUSY_RING_RADIUS,BUSY_RING_STROKE,BUSY_BREATH_SECONDS,MORPH_SECONDS
from status_paint import paint_liquid_glyph

ACTIVE={'thinking','working','responding'}

class StatusIndicator(QWidget):
    changed=Signal()
    ATTENTION_SECONDS=1.8
    def __init__(self,parent=None,clock=None):
        super().__init__(parent)
        self.setObjectName('codex_status_indicator');self.setFixedSize(16,16)
        self.clock=clock or time.monotonic
        self.state='idle';self.active=0;self.waiting=0;self.completed=False
        self.busy_since=self.clock();self.completed_at=None;self.seen=deque(maxlen=64)
        self.unread=[];self.store=None;self.ledger=None;self.acknowledged_at=None
        self.island=False;self._last_signature=None
        self.completion_times={};self.session_summary=''
        self._hidden_at=self.clock();self._motion_offset=0.;self._motion_holds={'hidden'}
        self.motion=GlyphMotion(self._motion_now())
        self._tick_at=None;self._paint_at=None
        # Retain ~19 seconds at the fast cadence, spanning the 10-second
        # runtime snapshot interval so a periodic pause cannot fall between samples.
        self._tick_gaps=deque(maxlen=1200);self._paint_gaps=deque(maxlen=1200);self._paint_costs=deque(maxlen=300)
        self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(33);self.timer.timeout.connect(self._tick)
        self._sync()

    def is_busy(self):return self.state in ACTIVE or self.active>0

    def set_store(self,path,home=None):
        self.store=Path(path)
        from completion_ledger import CompletionLedger
        self.ledger=CompletionLedger(self.store.with_suffix('.sqlite3'))
        try:
            data=json.loads(self.store.read_text(encoding='utf-8'))
            def keys(value):
                return [(session_id(v[0]),v[1]) for v in value if isinstance(v,list) and len(v)==2 and all(isinstance(s,str) and len(s)<=512 for s in v)] if isinstance(value,list) else []
            if isinstance(data,dict):
                stored_unread=keys(data.get('unread',[]))
                self.unread=[key for key in stored_unread if key[0] and key[1]]
                self.seen=deque(keys(data.get('seen',[])),maxlen=64)
                for key in stored_unread:
                    if key not in self.unread and key not in self.seen:self.seen.append(key)
                # Older builds could persist child completions after reading an
                # inherited parent header. Remove only proven child notices;
                # retain seen keys so stale events cannot resurrect them.
                from codex_connection import data_home
                excluded=subagent_sessions(data_home(home),[sid for sid,turn in self.unread])
                kept=[key for key in self.unread if key[0] not in excluded]
                if kept!=stored_unread:self.unread=kept;self._save()
        except (OSError,ValueError):pass
        self.ledger.remember(list(self.seen)+self.unread)
        self._sync();self.update()

    def _save(self):
        if self.store:
            try:
                atomic_json(self.store,dict(unread=self.unread,seen=list(self.seen)))
                if self.ledger:self.ledger.remember(list(self.seen)+self.unread)
            except OSError:pass

    def acknowledge(self,session=None):
        before=len(self.unread)
        self.unread=[] if session is None else [key for key in self.unread if key[0]!=session_id(session)]
        if len(self.unread)==before:return False
        self.completed=True;self.acknowledged_at=self.clock()
        if not self.unread:self.completed_at=None
        self._save();self._sync();self.update();return True

    def shaking(self,now=None):
        return bool(self.unread) and self.completed_at is not None and self.motion.shaking(self._motion_now(now))
    def acknowledge_seen(self,keys):
        seen={(session_id(s),str(t)) for s,t in keys}
        before=len(self.unread)
        self.unread=[key for key in self.unread if key not in seen or self.clock()-self.completion_times.get(key,-float('inf'))<2]
        if len(self.unread)==before:return False
        self.acknowledged_at=None;self.completed=False
        if not self.unread:self.completed_at=None
        if not self.is_busy() and self.state=='complete':self.state='idle'
        self._save();self._sync();self.update();return True

    def ack_flash(self,now=None):
        now=self.clock() if now is None else now
        return self.acknowledged_at is not None and now-self.acknowledged_at<1.

    def observe(self,event):
        if event.get('user_message') and event.get('session'):self.acknowledge(event['session'])
        was_busy=self.is_busy()
        self.state=event.get('state','idle')
        count=event.get('active',0)
        self.active=max(0,count) if isinstance(count,(int,float)) else 0
        count=event.get('waiting',0)
        self.waiting=max(0,count) if isinstance(count,(int,float)) else 0
        if self.is_busy():
            self.completed=False
            if not was_busy:self.busy_since=self.clock()
        elif self.state in ('offline','interrupted'):
            self.completed=False
        self._sync();self.update()

    def notify_complete(self,event):
        key=(session_id(event.get('session','')),str(event.get('turn','')))
        if not key[0] or not key[1]:return False
        if key in self.seen or key in self.unread or self.ledger and self.ledger.contains(key):return False
        self.seen.append(key)
        if key not in self.unread:self.unread.append(key)
        self.completion_times[key]=self.clock()
        if len(self.completion_times)>128:self.completion_times={k:v for k,v in self.completion_times.items() if k in self.unread}
        self.acknowledged_at=None
        # The monitor emits the aggregate status immediately after completion.
        # Retain other running tasks, then reconcile with that status event.
        self.active=max(0,self.active-1)
        self.state='working' if self.active else 'complete'
        self.completed=True;self.completed_at=self.clock()
        self._save()
        already_attention=self.motion.state=='attention'
        self._sync()
        if already_attention and (self.isVisible() or 'surface' in self._motion_holds):self.motion.notify_again(self._motion_now());self._sync()
        self.update();return True

    def visual(self,now=None):
        now=self.clock() if now is None else now
        if self.unread:return 'attention'
        if self.ack_flash(now):return 'complete'
        if self.state=='waiting' or self.waiting>0:return 'waiting'
        if self.is_busy():return 'busy'
        if self.state=='interrupted':return 'paused'
        if self.state=='offline':return 'warning'
        if self.completed or self.state=='complete':return 'complete'
        return 'idle'

    def _sync(self):
        visual=self.visual()
        self.motion.set_state(visual,self._motion_now(),animate=self.isVisible() or 'surface' in self._motion_holds)
        signature=(visual,self.state,self.active,self.waiting,len(self.unread))
        if signature==self._last_signature:
            self._sync_timer();return
        labels={'attention':'Codex 任务完成 · 点击确认已读，或在对应对话中回复','busy':'Codex 正在执行任务','waiting':'Codex 等待你输入或确认操作','paused':'Codex 任务已中断','warning':'Codex 未连接或监听异常','complete':'Codex 任务已完成 · 已确认','idle':'Codex 待命'}
        text=labels[visual]
        if visual=='attention' and len(self.unread)>1:text+=f'\n{len(self.unread)} 条完成提醒待确认'
        if visual=='attention' and self.is_busy():text+='，还有任务正在执行'
        if self.toolTip()!=text:self.setToolTip(text);self.setAccessibleName(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.unread else Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if self.unread else Qt.FocusPolicy.NoFocus)
        self._sync_timer()
        self._last_signature=signature;self.changed.emit()

    def _sync_timer(self):
        from settings_controls import motion_enabled
        now=self._motion_now()
        morphing=self.motion.started is not None and now-self.motion.started<MORPH_SECONDS
        fast=self.motion.state=='busy' or morphing or self.motion.shaking(now) or self.ack_flash()
        interval=16 if fast else 33
        if self.timer.interval()!=interval:
            self.timer.setInterval(interval)
            self._tick_at=None;self._paint_at=None;self._tick_gaps.clear();self._paint_gaps.clear()
        running=motion_enabled() and self.isVisible() and not self._motion_holds and (self.motion.moving(now) or self.ack_flash())
        if running and not self.timer.isActive():self.timer.start()
        elif not running:
            self.timer.stop();self._tick_at=None;self._paint_at=None

    def set_island(self,value):self.island=value;self.update()

    def motion_policy_changed(self):self._sync_timer();self.update()

    def _motion_now(self,now=None):
        now=self.clock() if now is None else now
        return (self._hidden_at if self._hidden_at is not None else now)-self._motion_offset

    def freeze_motion(self,reason='surface'):
        if not self._motion_holds:self._hidden_at=self.clock()
        self._motion_holds.add(reason);self.timer.stop()
        self._tick_at=None;self._paint_at=None

    def resume_motion(self,reason='surface'):
        self._motion_holds.discard(reason)
        if not self._motion_holds and self._hidden_at is not None:
            self._motion_offset+=self.clock()-self._hidden_at;self._hidden_at=None
        self._sync()

    def _tick(self):
        now=time.perf_counter()
        if self._tick_at is not None:self._tick_gaps.append((now-self._tick_at)*1000)
        self._tick_at=now
        # Only the acknowledgement deadline can change the semantic state
        # without an incoming event. Ordinary frames must not reset UI props.
        if self.motion.state!=self.visual():self._sync()
        else:self._sync_timer()
        if self.updatesEnabled():self.update()

    def timing_snapshot(self):
        def summary(values):
            if not values:return dict(samples=0)
            ordered=sorted(values)
            return dict(samples=len(ordered),p50Ms=round(ordered[len(ordered)//2],3),
                        p95Ms=round(ordered[int(len(ordered)*.95)],3),maxMs=round(ordered[-1],3),
                        over50ms=sum(v>50 for v in ordered))
        return dict(intervalMs=self.timer.interval(),precise=True,timerActive=self.timer.isActive(),
                    callback=summary(self._tick_gaps),paint=summary(self._paint_gaps),paintCpu=summary(self._paint_costs),
                    displayFpsMeasured=False)

    def showEvent(self,event):
        now=self.clock()
        if 'surface' not in self._motion_holds and self.completed_at is not None and now-self.completed_at>=self.ATTENTION_SECONDS:self.motion.settle()
        super().showEvent(event);self.resume_motion('hidden')

    def hideEvent(self,event):
        self.freeze_motion('hidden');super().hideEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            if self.acknowledge():event.accept();return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Space,Qt.Key.Key_Return,Qt.Key.Key_Enter) and self.acknowledge():event.accept();return
        super().keyPressEvent(event)

    def paintEvent(self,event):
        started=time.perf_counter()
        animating=self.timer.isActive() and not self._motion_holds
        if self._paint_at is not None and animating:self._paint_gaps.append((started-self._paint_at)*1000)
        self._paint_at=started if animating else None
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        from settings_controls import motion_enabled
        pose=self.motion.sample(self._motion_now()) if motion_enabled() else self.motion.steady(self.motion.since)
        paint_liquid_glyph(p,pose,self.island)
        p.end();self._paint_costs.append((time.perf_counter()-started)*1000)
