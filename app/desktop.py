"""Full desktop controls on top of the existing Codex/quota integration."""
import copy
import ctypes
import json
import math
import os
import random
import shutil
import sys
import time
import threading
from collections import deque
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QPoint,QPointF,QRect,QRectF,QUrl,QEvent,Signal
from PySide6.QtGui import QPainter,QCursor,QDesktopServices,QTransform
from PySide6.QtWidgets import QApplication,QMenu,QSystemTrayIcon,QFileDialog,QMessageBox
from enhanced import EnhancedPet,STATE_DIR,CONFIG
from pet import ROOT,ASSETS,clamp_position
from enhanced_core import motion_step,clean_text
from performance_metrics import measured
from desktop_core import (VERSION,DEFAULTS,normalized,atomic_json,ActionGate,physics_step,
    relative_position,restore_position,local_roam_bounds,local_roam_target)
from desktop_services import all_items,validate_character,open_codex,autostart_enabled,set_autostart
from stream_player import StreamPlayer
from status_reactions import StatusReactions
from continuous_work import ContinuousWork
from sustained_player import SustainedPlayback
from sustained_assets import profile_paths,seam_items
from locomotion import Locomotion,selection as movement_selection,profile as movement_profile,travel_speed as movement_speed

class DesktopPet(EnhancedPet):
    LAZY=True
    settingsChanged=Signal(dict)
    codexPresence=Signal(object)
    connectionHealthChanged=Signal(dict)
    def __init__(self,monitor=True):
        self._video_yielded=False;self._fullscreen_yielded=False;self.video_yield=None
        self._desktop_hidden=False;self._card_anchor=None;self._visibility_ready=False
        self.settings_revision=0
        from codex_connection import data_home,saved_paths
        from connection_health import CapabilityHealth
        saved_paths()
        try:previous=json.loads((STATE_DIR/'runtime.json').read_text(encoding='utf-8')).get('connection_health')
        except (OSError,ValueError):previous=None
        self.connection_health=CapabilityHealth(data_home(),previous)
        from material_store import MaterialStore
        self.material_store=MaterialStore(ROOT,STATE_DIR);self._pending_material=None
        self._materials_missing=self.material_store.current is None
        self.player=None;self.gate=ActionGate();self.asset_root=self.material_store.root
        self._landing_seed=None;self._landing_preparing=None
        self.animation_wakeups=0;self.movement_wakeups=0
        self.sustained=SustainedPlayback();self.continuous=ContinuousWork();self.locomotion=Locomotion();self._resume_idle=False
        from roaming_controller import RoamingController
        self.roaming=RoamingController(self)
        self._interactive_action=False;self._manual_action=False;self._priority=0
        self._hit_image=None;self.throwing=False;self.velocity=(0.,0.)
        self._pointer_pressed=False;self._pointer_epoch=0
        self.drag_samples=deque(maxlen=12);self.press_feedback=0;self.buffer_until=0
        self.pending_completion=None;self.settings_dialog=None;self.chat_window=None
        self.reactions=StatusReactions(time.monotonic());self.last_reaction=None
        self.character_dir=STATE_DIR/'characters';self.character_dir.mkdir(exist_ok=True)
        self.created_at=time.monotonic();self.decode_error=None
        super().__init__(monitor)
        # A hidden Qt/native owner can also suppress its tool windows. Keep a
        # logical owner for data/placement, with an independent native card.
        self.bubble.setParent(None,self.bubble.windowFlags())
        self.bubble._owner=self
        from codex_navigation import CodexNavigation
        self.codex_navigation=CodexNavigation(lambda session:open_codex(session),self)
        self.codex_navigation.error.connect(lambda text:self.say(text,6000))
        from update_controller import UpdateController
        self.updates=UpdateController(VERSION,STATE_DIR/'updates',self,allow_auto=monitor)
        self.updates.installerReady.connect(self.install_app_update)
        self.updates.animationReady.connect(self.queue_animation_update)
        self.updates.changed.connect(self.app_update_state)
        self._update_exit_pending=False
        from material_controller import MaterialController
        self.materials=MaterialController(self.material_store,self)
        self.materials.ready.connect(self.queue_material)
        self.materials.removeRequested.connect(self.remove_materials)
        self.materials.rollbackRequested.connect(self.rollback_animation_update)
        self._material_exit_pending=False
        self.reactions.set_actions(item['id'] for item in all_items(self.manifest))
        self.bubble.reportRequested.connect(self.open_report)
        self.bubble.quotaCompareRequested.connect(self.open_quota_comparison)
        self.bubble.settingsRequested.connect(self.open_settings)
        self.bubble.chatRequested.connect(self.open_chat)
        self.bubble.shortcutRequested.connect(self.open_shortcut)
        self.bubble.codexRequested.connect(self.open_assistant)
        self.bubble.conversationRequested.connect(self.open_conversation)
        self.bubble.optionRequested.connect(self.set_option)
        self.bubble.modeChanged.connect(self.save_bubble_mode)
        if self.settings.get('schema')!=2 and CONFIG.exists():
            shutil.copy2(CONFIG,STATE_DIR/'settings-before-0.5.0.json')
        self.settings=normalized(self.settings)
        from settings_controls import set_motion_mode,settle_motion
        set_motion_mode(self.settings['ui_animation_mode']);settle_motion()
        self._theme_preview=None;self._theme_preview_pending=False
        from edge_dock import EdgeDock
        self.edge_dock=EdgeDock(self)
        self.bubble.size_transition.animation.finished.connect(self._flush_theme_preview)
        self._visibility_ready=True
        self._card_anchor=self.settings.get('card_anchor')
        self.walk_direction=self.settings['facing']
        self.apply_settings({},save=False)
        chosen=self.settings.get('character','builtin')
        if chosen!='builtin':
            try:self.switch_character(chosen)
            except (OSError,ValueError,KeyError):
                self.settings['character']='builtin';self.say('角色包不可用，已恢复白龙默认素材。',6000)
        self.restore_saved_position()
        if self.settings['wander_home'] is None:self.remember_wander_home()
        self.next_chain=time.monotonic()+self.settings['random_interval']
        self.next_talk=time.monotonic()+random.uniform(self.settings['talk_min'],self.settings['talk_max'])
        self.motion_clock=time.perf_counter()
        self.motion_timer.setTimerType(Qt.TimerType.PreciseTimer)
        from codex_startup import ExitGate
        self._codex_exit_gate=ExitGate();self._codex_polling=False;self._codex_closing=False
        self.codexPresence.connect(self.observe_codex_presence)
        self.codex_timer=QTimer(self);self.codex_timer.setInterval(2000);self.codex_timer.timeout.connect(self.poll_codex_presence)
        if monitor:self.codex_timer.start()
        self._tray_update_hint=''
        self._refresh_tray_icon()
        self.tray.activated.disconnect()
        self.tray.activated.connect(lambda reason:self.recover() if reason in (QSystemTrayIcon.ActivationReason.Trigger,QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray_menu=QMenu();self.tray_menu.aboutToShow.connect(self.populate_tray);self.tray.setContextMenu(self.tray_menu)
        if monitor and sys.platform=='win32':
            from video_yield import VideoYield
            self.video_yield=VideoYield(self)
        self.save_settings()
        self.schedule_animation()

    def poll_codex_presence(self):
        from codex_connection import is_wsl_source
        if is_wsl_source():return
        if not self.settings.get('codex_exit') or self._codex_polling or self._codex_closing:return
        self._codex_polling=True
        def read():
            from codex_startup import desktop_sessions
            try:value=desktop_sessions()
            except Exception:value=None
            try:self.codexPresence.emit(value)
            except RuntimeError:pass
        threading.Thread(target=read,name='BailongCodexPresence',daemon=True).start()
    def observe_codex_presence(self,value):
        self._codex_polling=False
        if self._codex_closing or not self.settings.get('codex_exit'):return
        if self._codex_exit_gate.observe(value):self.close()

    def asset_path(self,item):
        name=item.get('playbackFile') or item['file'].replace('.webm','.webp')
        from material_store import checked
        return checked(self.asset_root,name)

    def play(self,item,mode):
        if self._materials_missing:return False
        if self._visibility_ready and (self._desktop_hidden or not self.settings.get('character_visible',True)):return False
        if self._interactive_action and mode=='variant':mode='click'
        if not self.gate.request(mode,item,force=self._interactive_action or self._manual_action):return False
        self.sustained.cancel()
        self.locomotion.cancel()
        # Every playback/cache key must use the current physical display size.
        # An earlier temporary native size must not survive into new actions.
        self.frame_size=self.desired_decode_size()
        if self.player is None:self.player=StreamPlayer()
        try:
            path=self.asset_path(item)
            seed=None
            if mode=='landing' and self._landing_seed:
                key=(str(path),self.frame_size,path.stat().st_mtime_ns)
                if self._landing_seed[0]==key:seed=self._landing_seed[1]
            if mode=='walk' and movement_profile(item):frame=self.locomotion.begin(self.player,path,self.frame_size,item,self.asset_root)
            else:frame=self.player.start(path,self.frame_size,item.get('durationMs',4000)/1000,cache_loop=mode=='idle',seed=seed)
        except (OSError,ValueError,KeyError) as error:
            self.decode_error=type(error).__name__;self.gate.state='idle'
            if self.current and self.current is not item:
                fallback=self.idles[0]
                if item is not fallback:self.play(fallback,'idle')
                return False
            raise
        self.frames=[frame];self._hit_image=frame.toImage();self.current=item;self.mode=mode;self.index=0
        self.started=time.monotonic();self.transition=None;self.update_frame()
        self.schedule_animation()
        return True

    def idle(self):
        self.gate.state='idle'
        if self._materials_missing:
            from PySide6.QtGui import QPixmap
            image=QPixmap(1,1);image.fill(Qt.GlobalColor.transparent);self.frames=[image];self.current=self.manifest['idle']
            return
        self.play(self.manifest['idle'] if getattr(self,'edge_dock',None) and self.edge_dock.active else random.choice(self.idles),'idle')

    @measured('pet_animation_event')
    def animate(self):
        self.animation_wakeups+=1
        try:self._animate_frame()
        finally:self.schedule_animation()

    def schedule_movement(self):
        if not hasattr(self,'motion_timer') or not self.motion_timer.isActive():return
        active=self.walking or self.throwing
        interval=16 if active else 1000
        if not active and self.settings.get('self_talk') and self.settings.get('character_visible',True) and not getattr(self,'_desktop_hidden',False):
            interval=max(1,min(1000,math.ceil((self.next_talk-time.monotonic())*1000)))
        if self.motion_timer.interval()!=interval:
            if active:self.motion_clock=time.perf_counter()
            self.motion_timer.setInterval(interval)

    def schedule_animation(self):
        self.schedule_movement()
        if not hasattr(self,'tick') or not self.tick.isActive() or not self.player:return
        speed=self.settings.get('playback_speed',1)*self.sustained.speed_factor(self.player)
        interval=self.player.next_delay_ms(speed)
        if self.locomotion.active and self.player.ended:interval=16
        if self.press_feedback and time.monotonic()-self.press_feedback<.5:interval=min(16,interval)
        self.tick.setInterval(interval)

    def _animate_frame(self):
        if self.player is None or not self.current:return
        if getattr(self,'_visibility_ready',False) and (self._desktop_hidden or not self.settings.get('character_visible',True)):return
        now=time.monotonic()
        desired=self.continuous.target(self.reactions,now,self.status_animation_allowed())
        was_sustained=self.sustained.active
        if was_sustained:
            owner=self.sustained.owner
            same_turn=bool(desired and (desired.session,desired.turn)==(owner.session,owner.turn))
            hard=bool(self._pending_material or not same_turn)
            self.sustained.request(bool(not hard and desired.action_id==owner.action_id),hard=hard)
        frame,ended=self.player.advance(self.frame_size,getattr(self,'settings',{}).get('playback_speed',1)*self.sustained.speed_factor(self.player))
        if self.locomotion.active:
            return_frame=self.locomotion.poll_stop(self.player,self.frame_size)
            if return_frame is not None:frame=return_frame;ended=False
        if frame is not None:
            self.frames=[frame];self.index=0;self._hit_image=frame.toImage();self.update_frame()
        if self.press_feedback and time.monotonic()-self.press_feedback<.5:self.update()
        if self.locomotion.active and (ended or self.player.ended):
            frame,finished=self.locomotion.boundary(self.player,self.frame_size)
            if frame is not None:
                self.frames=[frame];self.index=0;self._hit_image=frame.toImage();self.update_frame()
            if not finished:return
            self.walking=False;self.walk_target=None;ended=True
            if self.locomotion.error:self.decode_error=self.locomotion.error;self.roaming.cancel()
        if ended:
            if was_sustained:
                frame,finished=self.sustained.boundary(self.player,self.frame_size)
                if not finished:
                    self.frames=[frame];self.index=0;self._hit_image=frame.toImage();self.update_frame();return
            if self.player.error:
                self.roaming.cancel()
                self.decode_error=self.player.error
                if self.enhanced_ready:self.say('这段素材读取失败，已回到待机。',5000)
            if self.mode in ('drag','throw') or (self.mode=='walk' and self.walking):
                mode=self.mode;self.gate.state=mode;self.play(self.current,mode);return
            previous=self.mode;self.gate.finish();now=time.monotonic()
            if previous!='idle':
                dedicated=previous=='reaction' and str(self.current.get('id','')).startswith('work')
                self.reactions.finished(now,0 if was_sustained else max(2 if dedicated else 8,self.settings.get('action_gap',2)))
                self.buffer_until=now+max(.8,self.settings.get('action_gap',2))
            if previous in ('click','landing','task','quota','reaction'):self.next_chain=self.buffer_until+self.settings.get('random_interval',25)
            if previous in ('walk','landing') and self.roaming.rest_pending:
                self.next_chain=max(self.next_chain,self.buffer_until+self.settings.get('random_interval',25)*self.roaming.wait_factor)
                self.roaming.rest_pending=False
            if self._pending_material:self.apply_material()
            if self.play_status_reaction(now):return
            if previous in ('walk','landing') and self.roaming.queue:
                self.start_walk()
                if self.walking:return
            if previous=='idle' and self.autonomous_boundary(now):return
            self.idle()

    def status_animation_allowed(self):
        return self.isVisible() and not (getattr(self,'edge_dock',None) and self.edge_dock.active) and self.settings.get('status_actions',True) and not (self.dragging or self.throwing or self.walking or self.locomotion.active)

    def play_status_reaction(self,now):
        if self.gate.state!='idle' or not self.status_animation_allowed() or not self.player or not self.player.ended:return False
        selected=self.reactions.take_completion(now) or self.reactions.take_opening(now)
        desired=self.continuous.target(self.reactions,now)
        items={item['id']:item for item in all_items(self.manifest)}
        if selected is None and desired and now>=self.reactions.earliest:
            item=items.get(desired.action_id)
            try:profile=profile_paths(self.asset_root,item) if item else None
            except (OSError,ValueError,KeyError):profile=None;self.decode_error='invalid_sustained_profile'
            if profile:
                if not self.gate.request('reaction',item):return False
                try:frame=self.sustained.begin(self.player,profile,desired,self.frame_size)
                except (OSError,ValueError):
                    self.sustained.cancel();self.gate.state='idle';self.decode_error='sustained_start_failed';return False
                self.current=item;self.mode='reaction';self.frames=[frame];self.index=0;self._hit_image=frame.toImage()
                self.started=now;self.transition=None;self.update_frame()
                self.continuous.commit(desired,now);self.last_reaction=desired;self.reactions.record(desired,now)
                return True
            selected=self.reactions.take_current(desired,now)
        # Paused feedback remains a one-shot, independent of active-state loops.
        if selected is None and self.reactions.latest and self.reactions.latest.get('state')=='interrupted':
            selected=self.reactions.poll(now,boundary=True)
        if selected is None:return False
        item=items.get(selected.action_id)
        # Imported characters need an actual corresponding action. Do not
        # substitute an unrelated random animation when a mapping is absent.
        if item is None:return False
        if selected.kind=='complete':self.pending_completion=None
        mode='task' if selected.kind=='complete' else 'reaction'
        if not self.play(item,mode):return False
        if selected.kind not in ('complete','received'):self.continuous.commit(selected,now)
        self.last_reaction=selected
        return True

    def autonomous_boundary(self,now):
        if not self.isVisible() or self.dragging or self.throwing or self.walking or (getattr(self,'edge_dock',None) and self.edge_dock.active):return False
        if now<max(self.next_chain,self.buffer_until,self.status_hold):return False
        if self.settings.get('status_actions',True) and (self.reactions.busy(now) or self.bubble.status_indicator.is_busy()):return False
        if self.roaming.queue:self.start_walk();return self.walking
        self.next_chain=now+self.settings['random_interval']+self.settings['action_gap']
        choices=['idle'];weights=[30]
        if self.random_actions:choices+=['turn','variant'];weights+=[10,40]
        if self.wandering and not self.settings['no_move']:choices+=['walk'];weights+=[20]
        selected=random.choices(choices,weights)[0]
        if selected=='walk':self.start_walk();return self.walking
        if selected=='turn':
            self.walk_direction*=-1;self.settings['facing']=self.walk_direction
            return self.play(random.choice(self.manifest.get('turnAnimations') or self.idles),'turn')
        if selected=='variant' and self.variants:self.choose(random.choice(self.variants));return True
        return False

    def frame_transform(self,canvas):
        transform=QTransform()
        elapsed=time.monotonic()-self.press_feedback if self.press_feedback else 99
        if elapsed<.5:
            squash=math.sin(elapsed/.5*math.pi*2)*.075*math.exp(-elapsed*5)
            transform.translate(canvas.center().x(),canvas.bottom())
            transform.scale(1+squash,1-squash);transform.translate(-canvas.center().x(),-canvas.bottom())
        if getattr(self,'walk_direction',1)<0:
            transform.translate(canvas.x()*2+canvas.width(),0);transform.scale(-1,1)
        if getattr(self,'edge_dock',None):transform=transform*self.edge_dock.transform(canvas)
        return transform

    def draw_frame(self,painter,canvas):
        painter.save();painter.setTransform(self.frame_transform(canvas),True)
        # The base EnhancedPet mirrors only during walking; call Pet directly.
        from pet import Pet
        Pet.draw_frame(self,painter,canvas);painter.restore()

    def nativeEvent(self,event_type,message):
        if sys.platform=='win32' and self.enhanced_ready and not self.dragging:
            from ctypes import wintypes
            msg=wintypes.MSG.from_address(int(message))
            if msg.message==0x84: # WM_NCHITTEST. Preserve soft alpha in the layered window.
                from native_coordinates import client_position,message_position
                pos=client_position(msg.hWnd,*message_position(msg.lParam),self.width(),self.height())
                # Conversion failure delegates to Qt instead of making the pet unclickable.
                if pos is not None and not self.alpha_hit(*pos):return True,-1
        return super().nativeEvent(event_type,message)

    def alpha_hit(self,x,y):
        if self.settings.get('mouse_through'):return False
        if not self.frames or not self.current:return False
        if not (0<=x<self.width() and 0<=y<self.height()):return False
        canvas=QRectF(self.rect());inverse,valid=self.frame_transform(canvas).inverted()
        if not valid:return False
        point=inverse.map(QPointF(x,y));target=self.frame_target(canvas)
        if target.isEmpty() or not target.contains(point):return False
        image=self._hit_image or self.frames[self.index].toImage()
        fx=math.floor((point.x()-target.x())/target.width()*image.width())
        fy=math.floor((point.y()-target.y())/target.height()*image.height())
        return 0<=fx<image.width() and 0<=fy<image.height() and image.pixelColor(fx,fy).alpha()>=12

    def choose(self,item,interactive=False,manual=False):
        if (interactive or manual) and getattr(self,'edge_dock',None):self.edge_dock.clear(immediate=True)
        if self._visibility_ready and (self._desktop_hidden or not self.settings.get('character_visible',True)):return
        if not interactive and not manual and self.gate.state not in ('idle','turn','walk','variant'):return
        if interactive and self.gate.state=='task':return
        self.stop_walk();self.throwing=False
        self._interactive_action=interactive;self._manual_action=manual
        old=self._priority;self._priority=5 if interactive or manual else 1
        try:super().choose(item,interactive)
        finally:self._interactive_action=False;self._manual_action=False;self._priority=old

    def single_click(self):
        self.last_click=None;self.press_feedback=time.monotonic()
        pool=self.manifest.get('clickAnimations') or [v for v in self.variants if v['id'] in ('01','08','09','10','11','17','20','26') ] or self.variants or self.idles
        self.choose(random.choice(pool),interactive=True)

    def say(self,text,ms=4000):
        if self.enhanced_ready:
            now=time.monotonic();priority=self._priority or 3
            if now<self.status_hold and priority<getattr(self,'message_priority',0):return
            # Automatic action lines never obscure an active Codex task.
            if priority<=1 and not getattr(self,'_allow_talk_busy',False) and (self.last_activity.get('active',0)>0 or self.last_activity.get('state') in ('working','thinking','responding')):return
            self.message_priority=priority
        super().say(text,ms)

    def stop_walk(self,land=False,preserve_route=False):
        if not preserve_route:self.roaming.cancel()
        self.walking=False;self.walk_target=None
        if land and self.locomotion.active:
            self.locomotion.request_stop();return
        self.locomotion.cancel()
        if self.mode=='walk':
            self.gate.state='idle'
            landing=self.manifest.get('landingAnimation') if land else None
            if not landing or not self.play(landing,'landing'):self.idle()

    def prepare_landing(self):
        landing=self.manifest.get('landingAnimation')
        if not landing:return
        try:
            path=self.asset_path(landing)
            key=(str(path),self.frame_size,path.stat().st_mtime_ns)
        except (OSError,ValueError,KeyError):return
        if self._landing_preparing==key or (self._landing_seed and self._landing_seed[0]==key):return
        self._landing_preparing=key
        def decode():
            from PIL import Image
            import zlib
            from decode_runtime import STATS,opened
            try:
                opened(path)
                with Image.open(path) as source:
                    source.seek(0);source.load()
                    raw=source.convert('RGBA').resize((key[1],key[1]),Image.Resampling.LANCZOS).tobytes()
                    delay=max(.015,float(source.info.get('duration',landing.get('durationMs',2333)/max(1,source.n_frames)))/1000)
                STATS.add('decoded_frames')
                seed=(zlib.compress(raw,1),delay)
                if self._landing_preparing==key:self._landing_seed=(key,seed)
            except (OSError,ValueError,KeyError):pass
            finally:
                if self._landing_preparing==key:self._landing_preparing=None
        from decode_runtime import STATS
        STATS.start(decode,'pet-landing-prefetch')

    def remember_wander_home(self):
        screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        area=screen.availableGeometry()
        self.settings['wander_home']=relative_position(self.x(),self.y(),self.width(),self.height(),
            (area.x(),area.y(),area.width(),area.height()),screen.name())

    def start_walk(self):
        if self._materials_missing or not self.settings.get('character_visible',True):return
        if self.settings.get('status_actions',True) and (self.reactions.busy(time.monotonic()) or self.bubble.status_indicator.is_busy()):return
        if getattr(self,'edge_dock',None) and self.edge_dock.active:return
        if self.settings_dialog and self.settings_dialog.isVisible():return
        if self.bubble.underMouse() or self.underMouse() or self.bubble.size_transition.running or self.bubble.size_transition.preparing:return
        if (not self.settings.get('panel_detached') and ((self.bubble.report and self.bubble.report.requested) or self.bubble.panel_page!='status')) or self.settings.get('no_move') or self.dragging or self.throwing or self.gate.state not in ('idle','walk'):return
        screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen();area=screen.availableGeometry()
        home=self.settings.get('wander_home')
        if not isinstance(home,dict) or home.get('screen')!=screen.name():
            self.remember_wander_home();home=self.settings['wander_home']
        anchor=restore_position(home,self.width(),self.height(),(area.x(),area.y(),area.width(),area.height()))
        horizontal=self.settings['wander_horizontal_only']
        leg=self.roaming.next(screen,area,anchor,random.uniform)
        if leg is None:return
        target,bounds=leg
        tx,ty=target
        distance=math.hypot(tx-self.x(),ty-self.y())
        self.walk_direction=1 if tx>=self.x() else -1;self.settings['facing']=self.walk_direction
        self._fx,self._fy=float(self.x()),float(self.y());self.walk_target=(tx,ty,bounds)
        pool=self.manifest.get('moveAnimations') or [self.manifest.get('dragAnimation') or self.idles[0]]
        # Keep the small, calm walk as the default. A long horizontal journey
        # may occasionally use the valid run, mirrored for either direction.
        selected=movement_selection(pool,tx-self.x(),ty-self.y(),prefer_run=horizontal and distance>=450 and random.random()<.18) or random.choice(pool)
        self.walk_speed=movement_speed(selected,self.settings['move_speed'])
        self.walking=True;self.gate.state='idle'
        if not self.play(selected,'walk'):self.stop_walk();return
        self.prepare_landing()
        intro=self.locomotion.p['moveStart']/self.locomotion.p['fps']/self.settings.get('playback_speed',1) if self.locomotion.active else 0
        self.gesture_until=time.monotonic()+max(15,intro+distance/max(10,self.walk_speed)+5)

    def motion_tick(self):
        self.movement_wakeups+=1
        try:self._move_frame()
        finally:self.schedule_movement()

    def _move_frame(self):
        if not self.enhanced_ready:return
        now=time.monotonic();motion_now=time.perf_counter();dt=motion_now-self.motion_clock;self.motion_clock=motion_now
        if not self.isVisible():return
        self.edge_dock.observe_pointer()
        if self.throwing:
            a=(QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()).availableGeometry()
            bounds=(a.left(),a.top(),max(a.left(),a.right()-self.width()+1),max(a.top(),a.bottom()-self.height()+1))
            self._fx,self._fy,vx,vy,done=physics_step(self._fx,self._fy,*self.velocity,dt,bounds);self.velocity=(vx,vy)
            self.move(round(self._fx),round(self._fy));self.position_bubble()
            if done:self.throwing=False;self.gate.state='idle';self.play(self.manifest.get('landingAnimation') or self.idles[0],'landing');self.remember_wander_home();self.save_settings()
            return
        if self.walking and self.walk_target and not self.dragging:
            if self.settings_dialog and self.settings_dialog.isVisible():self.stop_walk(land=True);return
            if not self.settings.get('panel_detached') and (self.bubble.panel_page!='status' or self.bubble.report and self.bubble.report.requested):self.stop_walk(land=True);return
            if self.roaming.foreground_changed(now):self.stop_walk(land=True);return
            if self.locomotion.active and not self.locomotion.moving(self.player):return
            tx,ty,bounds=self.walk_target
            self._fx,self._fy,done=motion_step(self._fx,self._fy,tx,ty,self.roaming.speed(self._fx,self._fy,self.walk_speed),dt,bounds)
            self.move(round(self._fx),round(self._fy));self.position_bubble()
            # A delayed timer must not park a cross-screen walk in the middle.
            # The target is always in an edge band for horizontal roaming.
            timed_out=now>self.gesture_until and self.roaming.may_timeout(self._fx,self._fy) and (
                not self.settings['wander_horizontal_only'] or abs(tx-self._fx)<140)
            if done or timed_out:
                continuing=bool(done and self.roaming.queue)
                self.stop_walk(land=True,preserve_route=continuing);self.roaming.rest_pending=not continuing;self.buffer_until=now+self.settings['action_gap'];self.next_chain=now+(self.settings['action_gap'] if continuing else self.settings['random_interval']*self.roaming.wait_factor);self.save_settings()
        # Automatic gestures are dispatched in animate(), only after the
        # current clip has ended. This timer only moves the desktop window.
        if now>=self.next_talk:
            self.next_talk=now+random.uniform(self.settings['talk_min'],self.settings['talk_max'])
            busy=self.last_activity.get('active',0)>0 or self.last_activity.get('state') in ('working','thinking','responding')
            if self.settings['self_talk'] and self.settings['talk_lines'] and now>=self.status_hold and (not self.settings['talk_quiet'] or not busy):
                self._priority=1
                self._allow_talk_busy=not self.settings['talk_quiet']
                try:self.say(random.choice(self.settings['talk_lines']),5000)
                finally:self._priority=0;self._allow_talk_busy=False

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.roaming.cancel()
            self._pointer_epoch+=1;self._pointer_pressed=True
        self.throwing=False
        if self.mode=='throw':self.gate.state='idle';self.idle()
        self.press_feedback=time.monotonic();self.drag_samples.clear();self.drag_samples.append((time.perf_counter(),self.x(),self.y()))
        super().mousePressEvent(event)
        self.schedule_animation()
    def mouseMoveEvent(self,event):
        if self.settings.get('no_move'):return
        if not self._pointer_pressed and not self.dragging:return
        # User dragging is the highest priority; it can interrupt a task gesture.
        if event.buttons()&Qt.MouseButton.LeftButton and not self.dragging and hasattr(self,'press_pos'):
            if (event.globalPosition().toPoint()-self.press_pos).manhattanLength()>8:
                self.begin_drag_panel()
                self.gate.state='idle'
        super().mouseMoveEvent(event)
        if self.dragging:self.gate.state='drag';self.drag_samples.append((time.perf_counter(),self.x(),self.y()))
    def begin_drag_panel(self):
        from drag_panel import DragPanel
        if not hasattr(self,'drag_panel'):self.drag_panel=DragPanel(self)
        self.drag_panel.begin()
        # Independent/hidden panels do not enter DragPanel's transaction.
        if self.edge_dock.active or self.edge_dock.amount>0:self.edge_dock.clear(immediate=True)
    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        had_press=self._pointer_pressed or self.dragging
        self._pointer_pressed=False;self._pointer_epoch+=1
        if not had_press:return
        if self.dragging:
            self.dragging=False;self.last_click=None;self.click_timer.stop();self.gate.state='idle'
            if self.edge_dock.try_dock():
                if hasattr(self,'drag_panel'):self.drag_panel.finish(docked=True)
                self.remember_wander_home();self.bubble.refresh_status();self.position_bubble();self.save_settings();return
            if hasattr(self,'drag_panel'):self.drag_panel.finish()
            self.remember_wander_home()
            samples=[s for s in self.drag_samples if time.perf_counter()-s[0]<.15]
            vx=vy=0
            if len(samples)>1:
                a,b=samples[0],samples[-1];dt=max(.01,b[0]-a[0]);vx=(b[1]-a[1])/dt;vy=(b[2]-a[2])/dt
            length=math.hypot(vx,vy)
            if self.settings['drag_physics'] and length>120 and not self.settings['no_move']:
                factor=min(1,1800/max(1,length));self.velocity=(vx*factor,vy*factor)
                self._fx,self._fy=float(self.x()),float(self.y());self.throwing=True
                self.play(self.manifest.get('dragAnimation') or self.idles[0],'throw')
            else:self.play(self.manifest.get('landingAnimation') or self.idles[0],'landing')
            self.bubble.refresh_status();self.position_bubble();self.save_settings();return
        if self.edge_dock.active:
            self.click_timer.stop();self.last_click=time.monotonic();self.edge_dock.clear();self.position_bubble();return
        super().mouseReleaseEvent(event)

    def enterEvent(self,event):
        if getattr(self,'edge_dock',None):self.edge_dock.reveal(temporary=True)
        super().enterEvent(event)
    def leaveEvent(self,event):
        if getattr(self,'edge_dock',None):self.edge_dock.leave()
        super().leaveEvent(event)

    def cancel_pointer(self):
        """A lost grab has no release event; finish safely without a click or throw."""
        if not (self._pointer_pressed or self.dragging):return
        was_dragging=self.dragging
        self._pointer_pressed=False;self._pointer_epoch+=1;self.dragging=False
        self.drag_samples.clear();self.last_click=None;self.click_timer.stop()
        if hasattr(self,'drag_panel'):self.drag_panel.finish()
        if self.mode=='drag':self.gate.state='idle';self.idle()
        if was_dragging:self.remember_wander_home();self.save_settings()
        if self.enhanced_ready:self.bubble.refresh_status();self.position_bubble()

    def cancel_lost_grab(self,epoch):
        if epoch==self._pointer_epoch:self.cancel_pointer()

    @measured('ui_activity')
    def on_activity(self,event):
        if event.get('kind')=='animation_lifecycle':
            self.reactions.confirm(event.get('session',''),event.get('turn',''),event.get('active',False),time.monotonic());return
        if event.get('kind')=='connection_health':
            self.update_connection_health(event.get('capabilities',{}));return
        if event.get('kind')=='conversation_names':
            if self.bubble.roster.update_names(event.get('names',{})):self.bubble.refresh_status()
            return
        if event.get('kind')=='read_receipts':
            if self.bubble.status_indicator.acknowledge_seen(event.get('seen',[])):self.bubble.refresh_status()
            return
        if event.get('kind')=='complete' and not self.bubble.status_indicator.notify_complete(event):return
        if event.get('kind') in ('status','complete'):
            self.bubble.roster.observe(event)
        if event.get('kind') in ('status','complete'):self.bubble.task_updated(event)
        elif event.get('kind')=='codex_presence':
            self.reactions.present=event.get('open')
            self.bubble.codex_open=event.get('open');self.bubble.evaluate_mode();return
        if event.get('kind')=='complete':
            title=clean_text(event.get('title','Codex 任务'),70)
            self._priority=10
            try:self.say('Codex 任务完成啦！\n'+title,14000)
            finally:self._priority=0
            self.notify('Codex 任务已完成',title);self.refresh_quota()
            self.complete_animation(event)
        else:
            if event.get('kind')=='status':
                self.reactions.observe(event,time.monotonic())
                if self.reactions.completion is None:self.pending_completion=None
            elif event.get('kind')=='monitor_error':
                self.reactions.observe(dict(state='offline',text='监听异常',active=0),time.monotonic())
            super().on_activity(event)
            if event.get('kind')=='status' and self.settings.get('status_actions',True) and self.bubble.status_indicator.is_busy() and self.walking and not (self.dragging or self.throwing):
                self.stop_walk(land=True)
    def complete_animation(self,event):
        if self.reactions.queue_completion(event,time.monotonic()):self.pending_completion=event
    def update_connection_health(self,values):
        self.connection_health.update(values);self.connectionHealthChanged.emit(self.connection_health.snapshot())
    def quota_ready(self,windows):
        super().quota_ready(windows)
        known=any(isinstance(w.get('remaining'),(int,float)) for w in windows)
        self.update_connection_health({'quota':dict(state='available' if known else 'degraded',code='ok' if known else 'quota_unknown' if windows else 'no_windows',success_at=time.time())})
    def quota_failed(self,error):
        super().quota_failed(error)
        from quota import classify_error
        code=getattr(error,'code',None) or classify_error(str(error)).code
        if str(error) in ('服务器暂未提供额度窗口。','当前账户没有可读取的 Codex 额度。'):code='no_windows'
        self.update_connection_health({'quota':dict(state='degraded' if code=='no_windows' else 'unavailable',code=code)})
    def on_reset_feed(self,snapshot,alerts,fresh):
        self._priority=10
        try:super().on_reset_feed(snapshot,alerts,fresh)
        finally:self._priority=0

    def preview_theme(self,values=None,within_transition=False):
        """A display-only draft. Never put it in settings or a save callback."""
        from theme_registry import THEME_KEYS,values as theme_values,current,palette
        from theme_runtime import apply_theme
        target=dict(self.settings)
        if values is not None:target.update({k:values[k] for k in THEME_KEYS if k in values})
        proposed=theme_values(target.get('theme','bailong'),target)
        self._theme_preview=None if values is None else {k:target[k] for k in THEME_KEYS}
        transition=self.bubble.size_transition
        if (transition.running or transition.preparing) and not within_transition:
            self._theme_preview_pending=True
            if transition.preparing:QTimer.singleShot(0,self,self._flush_theme_preview)
            return
        self._theme_preview_pending=False
        if current()==target['theme'] and palette()==proposed:return
        guarded=not within_transition
        if guarded:transition.begin()
        try:
            apply_theme(target['theme'],target,roots=(self,self.bubble,self.settings_dialog,self.chat_window,self.bubble.report))
            self._tray_icon_key=None;self._refresh_tray_icon()
        finally:
            if guarded:transition.commit()

    def _flush_theme_preview(self):
        if self._theme_preview_pending and not self.bubble.size_transition.running and not self.bubble.size_transition.preparing:
            self.preview_theme(self._theme_preview)

    def apply_settings(self,values,save=True):
        from theme_registry import values as theme_values,current,palette
        from theme_registry import THEME_KEYS
        from theme_runtime import apply_theme
        candidate=dict(self.settings,**values)
        theme_values(candidate.get('theme','bailong'),candidate)
        changing_theme=any(key in values for key in THEME_KEYS)
        effective=(getattr(self,'_theme_preview',None) if not changing_theme else None) or candidate
        proposed=theme_values(effective.get('theme','bailong'),effective)
        recolor=current()!=effective.get('theme','bailong') or palette()!=proposed
        guarded=recolor or (changing_theme and getattr(self,'_theme_preview',None) is not None)
        from quick_actions import website_url
        if values.get('capsule_action',self.settings.get('capsule_action'))=='website':
            website_url(values.get('capsule_website',self.settings.get('capsule_website','')))
        if guarded:self.bubble.size_transition.begin()
        previous=copy.deepcopy(self.settings)
        if (previous.get('character_visible',True) and values.get('character_visible') is False) or (not previous.get('panel_detached') and values.get('panel_detached') is True):
            self.remember_card_anchor(self.bubble.content_geometry())
        if 'codex_exit' in values and values['codex_exit']!=previous.get('codex_exit'):
            self._codex_exit_gate.reset()
        old_size=self.height();foot=self.geometry().bottom()+1;center=self.geometry().center().x()
        self.settings.update(values);self.settings=normalized(self.settings)
        from settings_controls import set_motion_mode,settle_motion
        set_motion_mode(self.settings['ui_animation_mode'])
        if self.settings['ui_animation_mode']!=previous.get('ui_animation_mode','quality'):settle_motion()
        if recolor:
            apply_theme(effective['theme'],effective,roots=(self,self.bubble,self.settings_dialog,self.chat_window,self.bubble.report))
            self._tray_icon_key=None;self._refresh_tray_icon()
        if 'card_anchor' in values:self._card_anchor=copy.deepcopy(self.settings.get('card_anchor'))
        if (self.settings['no_move'] or self.settings['mouse_through'] or
            self.settings['scale']!=previous.get('scale') or self.settings['on_top']!=previous.get('on_top')):
            self.cancel_pointer()
        self.reactions.configure(self.settings['status_action_interval'],time.monotonic())
        if hasattr(self,'updates'):self.updates.configure(self.settings['update_checks'])
        for attr in ('wandering','random_actions','commentary','sound'):setattr(self,attr,self.settings[attr])
        self.bubble.enabled=self.settings['bubble'];self.bubble.show_quota=self.settings['quota_visible']
        self.bubble.bubble_mode=self.settings['bubble_mode']
        if 'bubble_mode' in values:self.bubble._minimal_normal_open=False;self.bubble.auto_compact=False
        self.bubble.capsule_action=self.settings['capsule_action']
        if 'bubble_mode' in values and self.bubble._editor_origin is not None:
            self.bubble._editor_origin.update(bubble_mode=self.settings['bubble_mode'],expanded=False,
                                               auto_compact=False,minimal_normal_open=False)
        self.bubble.token_range=self.settings['token_chart_range']
        self.bubble.pinned=self.settings['on_top'];self.bubble.wandering=self.settings['wandering'];self.bubble.movement_locked=self.settings['no_move']
        size=round(256*self.settings['scale']);self.setFixedSize(size,size)
        if size!=old_size:self.move(self.constrained_position(QPoint(center-size//2,foot-size)))
        # All states use one physical-pixel decode policy. Refresh the current
        # frame immediately rather than changing clarity on the next action.
        self.sync_decode_size()
        from roaming_controller import POLICY_KEYS
        if (self.settings['no_move'] or not self.wandering or
            any(self.settings.get(k)!=previous.get(k) for k in POLICY_KEYS)):self.stop_walk()
        if self.settings['no_move']:self.throwing=False
        for widget in (self,self.bubble):
            visible=widget.isVisible()
            widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,self.settings['on_top'])
            if widget is self:widget.setWindowFlag(Qt.WindowType.WindowTransparentForInput,self.settings['mouse_through'])
            if visible:widget.show()
        self.sync_panel_flags()
        if values.get('bubble') is False:
            self.bubble.size_transition.cancel();self.bubble.panel_page='status';self.bubble.expanded=False
            self.bubble._editor_origin=None;self.bubble._editor_positioned=False;self.bubble._editing_flags(False)
        self.bubble.redraw();self.position_bubble()
        if guarded:self.bubble.size_transition.commit()
        if getattr(self,'edge_dock',None):self.edge_dock.reconcile()
        if self._visibility_ready:self.apply_surface_visibility()
        if values.get("bubble") is False:self.bubble.hide()
        if self.video_yield:self.video_yield.reconcile()
        self.next_chain=time.monotonic()+self.settings['random_interval'];self.next_talk=time.monotonic()+self.settings['talk_min']
        self.schedule_animation()
        if save:
            try:self.save_settings()
            except (OSError,ValueError):
                self.settings=previous;self._card_anchor=copy.deepcopy(previous.get('card_anchor'));self.apply_settings({},save=False);raise
        if changing_theme:self._theme_preview=None;self._theme_preview_pending=False
        changed={key:copy.deepcopy(value) for key,value in self.settings.items() if previous.get(key)!=value}
        if changed:
            self.settings_revision+=1;self.settingsChanged.emit(changed)

    def save_bubble_mode(self,mode):
        self.settings['bubble_mode']=mode;self.save_settings()

    def flush_status(self):
        super().flush_status();self.bubble.evaluate_mode()

    def desired_decode_size(self):
        from decode_runtime import display_decode_size
        return display_decode_size(getattr(self,'settings',{}).get('scale',1),self.devicePixelRatioF())

    def request_decode_sync(self):
        if getattr(self,'_decode_sync_pending',False):return
        self._decode_sync_pending=True
        def sync():
            self._decode_sync_pending=False
            # Read DPI after Qt has applied the screen/resize event, rather
            # than rejecting a request while the old metrics are still live.
            expected=self.desired_decode_size()
            if self.frame_size!=expected or self.player is not None and getattr(self.player,'size',expected)!=expected:self.sync_decode_size()
        QTimer.singleShot(0,self,sync)

    def watch_screen(self,screen):
        super().watch_screen(screen)
        def changed(*unused):
            if getattr(self,'enhanced_ready',False):self.request_decode_sync()
        screen.geometryChanged.connect(changed)
        screen.logicalDotsPerInchChanged.connect(changed)
        screen.physicalDotsPerInchChanged.connect(changed)

    def ensure_on_screen(self):
        super().ensure_on_screen()
        if getattr(self,'edge_dock',None):self.edge_dock.reconcile()
        if getattr(self,'enhanced_ready',False):self.request_decode_sync()

    def sync_decode_size(self):
        self.frame_size=self.desired_decode_size()
        if self.player is not None:
            frame=self.player.resize(self.frame_size)
            if frame is not None:
                self.frames=[frame];self.index=0;self._hit_image=frame.toImage();self.update_frame()
                if self.sustained.active:self.sustained.prewarm(self.player,self.frame_size)

    def pause_hidden_animation(self):
        if not self.isVisible() and self.player:
            self.locomotion.cancel();self.walking=False;self.walk_target=None
            self.sustained.cancel();self.player.close();self.continuous.clear();self.gate.state='idle';self._resume_idle=True

    def event(self,event):
        if getattr(self,'enhanced_ready',False):
            if event.type()==QEvent.Type.UngrabMouse:
                # Qt can release its implicit grab just before delivering mouseRelease.
                epoch=self._pointer_epoch
                QTimer.singleShot(0,self,lambda:self.cancel_lost_grab(epoch))
            elif event.type()==QEvent.Type.Hide:
                self.click_timer.stop();self.last_click=None
                self.cancel_pointer();QTimer.singleShot(0,self,self.pause_hidden_animation)
            elif event.type()==QEvent.Type.Show and self._resume_idle:
                self._resume_idle=False;self.idle()
        result=super().event(event)
        if event.type() in (QEvent.Type.DevicePixelRatioChange,QEvent.Type.Show,QEvent.Type.Resize) and getattr(self,'enhanced_ready',False):
            self.request_decode_sync()
        return result

    def save_settings(self):
        if not self.enhanced_ready:return
        super().save_settings()
        self.settings['facing']=self.walk_direction
        screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen();a=screen.availableGeometry()
        self.settings['screen_position']=relative_position(self.x(),self.y(),self.width(),self.height(),(a.x(),a.y(),a.width(),a.height()),screen.name())
        atomic_json(CONFIG,self.settings)
    def restore_saved_position(self):
        saved=self.settings.get('screen_position')
        if isinstance(saved,dict):
            screen=next((s for s in QApplication.screens() if s.name()==saved.get('screen')),QApplication.primaryScreen());a=screen.availableGeometry()
            try:x,y=restore_position(saved,self.width(),self.height(),(a.x(),a.y(),a.width(),a.height()));self.move(x,y)
            except (ValueError,TypeError):self.ensure_on_screen()
        self.position_bubble()
    def reset_position(self):
        self.edge_dock.clear(immediate=True)
        self.stop_walk();self.throwing=False
        screen=QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen();a=screen.availableGeometry()
        self.move(clamp_position(QPoint(a.right()-self.width()-20,a.bottom()-self.height()-20),self.size(),a));self.remember_wander_home();self.position_bubble();self.save_settings()
    def recover(self):
        self.edge_dock.clear(immediate=True)
        self._desktop_hidden=False;values={'mouse_through':False}
        # Recovery from the tray must be useful even when both surfaces were
        # hidden.  Do not leave the user with a visible pet and no way to see
        # the card they clicked the tray icon for.
        if not self.settings.get('character_visible',True) or not self.bubble.enabled:values['bubble']=True
        self.apply_settings(values);self.apply_surface_visibility();self.bubble.redraw();self.position_bubble()
    def toggle_pet(self):
        self._desktop_hidden=not self._desktop_hidden;self.apply_surface_visibility()
    def set_fullscreen_yield(self,hidden):
        """Hide the desktop surfaces for the general full-screen policy.

        This is intentionally separate from video z-order yielding: a video
        completion can reclaim topmost, while the all-window policy leaves only
        the tray ring visible until the full-screen window exits.
        """
        hidden=bool(hidden)
        if hidden==self._fullscreen_yielded:return
        self._fullscreen_yielded=hidden
        self.edge_dock.reconcile()
        if hidden:
            self.stop_walk();self.throwing=False;self.cancel_pointer();self.hide();self.bubble.hide();self.tick.stop();self.pause_hidden_animation()
        else:self.apply_surface_visibility()
    def card_surface_visible(self):
        return not self._desktop_hidden and not self._fullscreen_yielded and (self.isVisible() or self._materials_missing or not self.settings.get('character_visible',True))
    def apply_surface_visibility(self):
        if not self._visibility_ready:return
        self.edge_dock.reconcile()
        if self._fullscreen_yielded:
            self.hide();self.bubble.hide();self.tick.stop();self.pause_hidden_animation();return
        character=not self._materials_missing and self.settings.get('character_visible',True) and not self._desktop_hidden
        if character:
            if not self.isVisible():self.show();self.tick.start()
        else:
            self.stop_walk();self.throwing=False;self.cancel_pointer();self.hide();self.tick.stop();self.pause_hidden_animation()
            if self._pending_material:self.apply_material()
        if not self._desktop_hidden and (self.bubble.enabled or self.bubble.panel_page!='status'):
            self.bubble.show();self.position_bubble()
        else:self.bubble.hide()
    def remember_card_anchor(self,rect):
        screen=QApplication.screenAt(rect.center()) or QApplication.primaryScreen();a=screen.availableGeometry()
        # QRect.center() truncates the half-pixel center of even-width cards.
        # Restoring with width/2 then drifts one pixel on repeated placement.
        self._card_anchor=dict(screen=screen.name(),rx=(rect.x()+rect.width()/2-a.left())/max(1,a.width()),bottom=(rect.bottom()+1-a.top())/max(1,a.height()))
        self.settings['card_anchor']=dict(self._card_anchor)
    def card_geometry(self,size):
        anchor=self._card_anchor
        if not isinstance(anchor,dict):
            rect=QRect(self.bubble.pos(),size);self.remember_card_anchor(rect);anchor=self._card_anchor
        screen=next((s for s in QApplication.screens() if s.name()==anchor.get('screen')),QApplication.primaryScreen());a=screen.availableGeometry()
        try:cx=a.left()+a.width()*max(0,min(1,float(anchor.get('rx',.8))));bottom=a.top()+a.height()*max(0,min(1,float(anchor.get('bottom',.8))))
        except (TypeError,ValueError):cx=a.right()-80;bottom=a.bottom()-40
        x=round(cx-size.width()/2);y=round(bottom-size.height())
        reserve=self.bubble.report.reserved_height(size)+6 if self.bubble.report and self.bubble.report.requested else 0
        x=max(a.left(),min(x,a.right()-size.width()+1));y=max(a.top()+min(reserve,max(0,a.height()-size.height())),min(y,a.bottom()-size.height()+1))
        return QRect(x,y,size.width(),size.height())
    def move_card(self,point):
        rect=QRect(point,self.bubble.size());self.remember_card_anchor(rect);self.bubble.move(self.card_geometry(rect.size()).topLeft());self.remember_card_anchor(self.bubble.geometry())
    def position_bubble(self):
        # EnhancedPet calls this virtual method before DesktopPet has restored
        # the saved independent-card anchor. Initial placement must not create
        # and persist a replacement anchor from the temporary startup geometry.
        if not getattr(self,'_visibility_ready',False):return super().position_bubble()
        if hasattr(self,'drag_panel'):self.drag_panel.follow()
        report=getattr(self.bubble,'report',None)
        if report and getattr(report,'_host_closing',False) and not getattr(getattr(self,'drag_panel',None),'active',False):return
        if self.enhanced_ready and (self.bubble.size_transition.running or self.bubble.size_transition.preparing or self.bubble.size_transition.landing.image is not None):return
        if self.enhanced_ready and (self.settings.get('panel_detached') or self._materials_missing or not self.settings.get('character_visible',True)):
            self.bubble.move(self.card_geometry(self.bubble.content.size()).topLeft())
            if self._desktop_hidden:self.bubble.hide()
            return
        edge=getattr(self,'edge_dock',None)
        if self.enhanced_ready and edge and (edge.active or edge.amount>0) and self.bubble.is_minimal():
            self.bubble.move(edge.card_geometry(self.bubble.content.size()).topLeft())
            return
        if self.enhanced_ready and self.bubble.panel_page!='status' and self.bubble._editor_positioned:
            if not self.card_surface_visible():self.bubble.hide()
            return
        super().position_bubble()
        if self.enhanced_ready and self.bubble.panel_page!='status':self.bubble._editor_positioned=True
        if self.enhanced_ready and not self.card_surface_visible():self.bubble.hide()
    def can_raise_bubble(self):
        if self._video_yielded or self._fullscreen_yielded or self.dragging or self.throwing or self.walking:return False
        # Owned panels stay above the pet. Periodic bubble updates must not
        # reorder its sibling windows over an open settings/chat panel.
        if QApplication.activePopupWidget() is not None or self.bubble.panel_page!='status':return False
        return not any(panel and panel.isVisible() and not panel.isMinimized()
                       for panel in (self.settings_dialog,self.chat_window))
    def sync_panel_flags(self):
        self.bubble._editing_flags(self.bubble.panel_page!='status')
        for panel in (self.settings_dialog,self.chat_window):
            if panel is None or not panel.isWindow():continue
            target=self.settings['on_top']
            if bool(panel.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)!=target:
                visible=panel.isVisible();state=panel.windowState();active=panel.isActiveWindow()
                panel.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,target)
                if visible:
                    panel.setWindowState(state);panel.show()
                    if active:panel.raise_();panel.activateWindow()
    def show_panel(self,panel):
        if not panel.isWindow():
            if not self.bubble.enabled:self.set_option('bubble',True)
            self.stop_walk();self.throwing=False;self._desktop_hidden=False;self.apply_surface_visibility()
            # First activation can synchronously polish the native editor and
            # take a full frame. Do it before the snapshot animation starts so
            # the visible morph has an uninterrupted clock.
            self.bubble.raise_();self.bubble.activateWindow()
            if self.bubble.windowHandle():self.bubble.windowHandle().requestActivate()
            QApplication.setActiveWindow(self.bubble)
            self.bubble.show_page('settings' if panel is self.settings_dialog else 'chat',panel)
            if panel is self.chat_window and panel.pages.currentWidget() is panel.chat_body:panel.input.setFocus()
            elif panel is self.settings_dialog:panel.tabs.tabBar().setFocus()
            return
        self.sync_panel_flags();panel.showNormal();panel.raise_();panel.activateWindow()
    def set_option(self,attr,value):
        try:self.apply_settings({attr:value})
        except (OSError,ValueError) as error:
            message='设置保存失败，已恢复原值：'+str(error)
            if self.settings_dialog:self.settings_dialog.status.setText(message)
            previous=self._priority;self._priority=10
            try:self.say(message,6500)
            finally:self._priority=previous
    def toggle_bubble(self):self.set_option('bubble',not self.bubble.enabled)
    def toggle_quota(self,value):self.set_option('quota_visible',value)
    def quota(self):
        self.refresh_quota(manual=True)

    def action_groups(self):
        return {'待机':self.idles,'转向':self.manifest.get('turnAnimations',[]),'移动':self.manifest.get('moveAnimations',[]),
            '点击回应':self.manifest.get('clickAnimations') or [v for v in self.variants if v['id'] in ('01','08','09','10','11')],
            '互动动作':self.variants,'工作动作':[v for v in self.manifest.get('workAnimations',[]) if v], '额度回应（不刷新数据）':[self.manifest['quotaAnimation']] if self.manifest.get('quotaAnimation') else [],
            '拖拽':[self.manifest['dragAnimation']] if self.manifest.get('dragAnimation') else [],
            '落地':[self.manifest['landingAnimation']] if self.manifest.get('landingAnimation') else []}
    def populate_tray(self):self.build_menu(self.tray_menu,tray=True)
    def execute_command(self,command,checked=False):
        if command.startswith('mode_'):self.bubble.set_mode(command[5:]);return
        toggles={'character':'character_visible','pin':'on_top','lock':'no_move','through':'mouse_through','bubble':'bubble','detach':'panel_detached'}
        if command in toggles:self.set_option(toggles[command],checked);return
        if command=='status' and not self.settings['bubble']:self.set_option('bubble',True)
        commands={'status':self.open_status,'settings':self.open_settings,'chat':self.open_chat,
            'visible':self.toggle_pet,'recover':self.recover,'position':self.reset_position,
            'walk':lambda:self.set_option('wandering',not self.settings['wandering']),'quit':self.close}
        commands[command]()
    def menu_command(self,menu,command):
        labels={'status':'查看状态','settings':'桌宠设置…','chat':'和白龙聊天…',
            'visible':'显示桌面组件' if self._desktop_hidden else '隐藏全部组件','recover':'找回组件并关闭穿透','character':'显示人物',
            'mode_auto':'自动 / 正常卡片','mode_mini':'胶囊模式','mode_minimal':'极简：额度百分比',
            'position':'回到当前屏幕右下角','pin':'始终置顶','lock':'锁定人物位置（含拖动）',
            'through':'鼠标穿透（从托盘恢复）','bubble':'显示面板','detach':'面板位置独立于人物','quit':'退出桌宠',
            'walk':('自主走动（位置已锁定）' if self.settings['no_move'] else '暂停自主走动' if self.settings['wandering'] else '恢复自主走动')}
        action=menu.addAction(labels[command]);action.setObjectName('command_'+command)
        key={'character':'character_visible','pin':'on_top','lock':'no_move','through':'mouse_through','bubble':'bubble','detach':'panel_detached'}.get(command)
        if key:action.setCheckable(True);action.setChecked(self.settings[key])
        if command.startswith('mode_'):action.setCheckable(True);action.setChecked(self.bubble.bubble_mode==command[5:])
        if command=='walk':action.setEnabled(not self.settings['no_move'])
        action.triggered.connect(lambda value=False,c=command:QTimer.singleShot(0,self,lambda:self.execute_command(c,value)))
        return action
    def build_menu(self,menu,tray=False):
        menu.clear()
        if tray:
            for command in ('recover','visible','status','settings'):self.menu_command(menu,command)
            display=menu.addMenu('显示方式');self.menu_command(display,'character');self.menu_command(display,'bubble');self.menu_command(display,'detach')
            for mode in ('auto','mini','minimal'):self.menu_command(display,'mode_'+mode)
            menu.addSeparator();self.menu_command(menu,'quit');return
        for command in ('bubble','status','chat','walk'):self.menu_command(menu,command)
        desktop=menu.addMenu('桌面操作')
        for command in ('character','pin','lock','through','detach'):self.menu_command(desktop,command)
        display=desktop.addMenu('卡片模式')
        for mode in ('auto','mini','minimal'):self.menu_command(display,'mode_'+mode)
        desktop.addSeparator()
        for command in ('recover','position'):self.menu_command(desktop,command)
        groups=menu.addMenu('手动动作')
        for group,items in self.action_groups().items():
            sub=groups.addMenu(group)
            if not items:sub.addAction('专用素材待制作，暂用现有动作').setEnabled(False)
            for item in items:sub.addAction(item.get('name',item['id']),lambda v=item:self.choose(v,interactive=True,manual=True))
        menu.addSeparator()
        for command in ('settings','visible','quit'):self.menu_command(menu,command)
    def context_menu(self,point):
        self.stop_walk();menu=QMenu(self);self.build_menu(menu);menu.exec(point)
    def toggle_startup(self,value):
        try:set_autostart(value)
        except OSError:self.say('启动设置保存失败，请打开设置检查。',5000)
        if self.settings_dialog:self.settings_dialog.sync_from_pet(read_startup=True)
    def open_report(self):
        self.throwing=False
        if self.bubble.report is not None and self.bubble.report.requested:
            self.bubble.report.dismiss();return
        if self.bubble.report is None:
            from daily_report import DailyReport
            self.bubble.report=DailyReport(self.bubble)
            self.bubble.report.refreshRequested.connect(self.refresh_report)
        self.bubble.report.set_snapshot(self.bubble.token_snapshot)
        self.bubble.report.open()

    def open_quota_comparison(self):
        if self.bubble.report is not None and self.bubble.report.requested and self.bubble.report.page=='cycle':
            self.bubble.report.dismiss();return
        if self.bubble.report is None:
            from daily_report import DailyReport
            self.bubble.report=DailyReport(self.bubble)
            self.bubble.report.refreshRequested.connect(self.refresh_report)
        report=self.bubble.report;report.set_snapshot(self.bubble.token_snapshot)
        report.set_page('cycle')
        if not report.requested:report.open(page='cycle')

    def open_settings(self):
        if self.bubble.panel_page=='status':self.roaming.preview_footprint=self.roaming.footprint()
        if not self.settings_dialog:
            from desktop_settings import SettingsDialog
            self.settings_dialog=SettingsDialog(self,embedded=True,lazy=True)
        self.settings_dialog.sync_from_pet(read_startup=True)
        self.show_panel(self.settings_dialog)
    def open_status(self):
        self.show()
        if not self.bubble.enabled:self.set_option('bubble',True)
        if self.bubble.bubble_mode=='minimal':self.bubble.open_normal_from_minimal()
        else:self.bubble.set_mode('auto')
    def open_chat(self):
        if not self.chat_window:
            from chat_window import ChatWindow
            self.chat_window=ChatWindow(self,STATE_DIR,embedded=True)
        self.show_panel(self.chat_window)
    def open_chat_service(self):
        self.open_chat();self.chat_window.provider()
    def open_shortcut(self):
        from quick_actions import action_info,website_url
        action=action_info(self.settings.get('capsule_action'))[0]
        if action in ('chatgpt','website'):
            try:
                url='https://chatgpt.com/' if action=='chatgpt' else website_url(self.settings.get('capsule_website'))
                if not QDesktopServices.openUrl(QUrl(url)):raise OSError('未能打开默认浏览器，请检查系统的浏览器设置。')
            except (ValueError,OSError) as error:self.say(str(error),6000)
        elif action=='codex':self.open_assistant()
        elif action=='chat':self.open_chat()
        elif action=='settings':self.open_settings()
        elif action=='report':self.open_report()
        elif action=='refresh':self.bubble.request_refresh_all()
    def open_assistant(self):
        try:self.codex_navigation.open()
        except OSError as error:self.say(str(error),6000)
    def open_conversation(self,session):
        self.recently_visited=getattr(self,'recently_visited',{});self.recently_visited[session]=time.monotonic()
        try:self.codex_navigation.open(session)
        except OSError as error:self.say(str(error),6000)
    def open_data(self):QDesktopServices.openUrl(QUrl.fromLocalFile(str(STATE_DIR)))
    def open_install_manager(self):
        try:
            from installer import checked_version,read_manifest
            from storage_locations import install_root
            root=install_root();m=read_manifest(root)
            exe=checked_version(root,m.get('current',''))/'白龙安装管理.exe'
            if not exe.is_file():raise OSError('当前没有已安装的维护程序，请使用安装器选择程序位置')
            from process_launch import launch_own
            launch_own([str(exe),'--manage'],cwd=exe.parent,creationflags=0x08000000)
        except (OSError,ValueError) as exc:QMessageBox.warning(self.settings_dialog,'安装管理',str(exc))
    def app_update_state(self,state):
        self._tray_update_hint=('有更新 '+str(state.get('latest','')) if state.get('phase')=='available' else '')
        self._refresh_tray_icon()
    def install_app_update(self,path):
        import subprocess
        from process_launch import launch_own
        from app_updates import cache_paths,UpdateError
        try:
            release=self.updates.release
            if release is None:raise OSError('更新信息已失效，请重新检查')
            if release.kind=='program':
                from program_updates import program_paths,verify_ready
                expected=program_paths(self.updates.cache,release.version)['source']
                if Path(path).resolve()!=expected.resolve():raise OSError('程序更新尚未就绪，请重新下载')
                exe=verify_ready(expected,self.updates.cache,release.version,release.sha256,full=False)
                launch_own([str(exe),'--apply-program-update'],cwd=str(expected),creationflags=0x08000000 if sys.platform=='win32' else 0)
                self.updates.installing();return
            expected=cache_paths(self.updates.cache,release.version)['installer']
            if Path(path).resolve()!=expected.resolve() or not expected.is_file():raise OSError('安装程序尚未就绪，请重新下载')
            launch_own([str(expected),'--quick'],cwd=str(expected.parent),creationflags=0x08000000 if sys.platform=='win32' else 0)
            self.updates.installing()
        except (OSError,ValueError,UpdateError) as error:self.updates.install_failed(str(error))
    def character_choices(self):
        choices=[('builtin','白龙娘 · 内置')]
        for folder in sorted(self.character_dir.iterdir()):
            if not folder.is_dir() or folder.name.startswith('import-'):continue
            try:
                m=json.loads((folder/'素材清单.json').read_text(encoding='utf-8'));choices.append((folder.name,m.get('character',folder.name)))
            except (ValueError,OSError):pass
        return choices
    def switch_character(self,key):
        if not key:return
        if self._pending_material:raise ValueError('画质切换正在等待动作结束，请稍后切换角色')
        if key=='builtin':
            if self.material_store.current is None:raise ValueError('请先在素材设置中下载并启用动画')
            root=self.material_store.root
        else:
            root=(self.character_dir/key).resolve()
            if root.parent!=self.character_dir.resolve():raise ValueError('角色目录无效')
        # Import performs full decoding. Switching checks structure and first frame only.
        m=json.loads((root/'素材清单.json').read_text(encoding='utf-8'))
        if not isinstance(m,dict) or not isinstance(m.get('idle'),dict) or not isinstance(m.get('variants',[]),list):raise ValueError('角色清单结构无效')
        for item in all_items(m)+seam_items(m):
            path=(root/(item.get('playbackFile') or item['file'])).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('角色包缺少素材或路径无效')
        old=(self.asset_root,self.manifest,self.idles,self.variants,self.settings.get('character','builtin'))
        old_missing=self._materials_missing
        preference_keys=('scale','playback_speed','talk_lines')
        self.settings['character_preferences'][old[4]]={k:copy.deepcopy(self.settings[k]) for k in preference_keys}
        self.stop_walk();self.throwing=False;self.gate.state='idle'
        self.sustained.cancel();self.continuous.clear()
        try:
            self.asset_root=root;self.manifest=m;self.idles=[m['idle']]+m.get('additionalIdleAnimations',[]);self.variants=m.get('variants',[])
            self._materials_missing=False
            self.reactions.set_actions(item['id'] for item in all_items(m))
            self.idle()
        except Exception:
            self.asset_root,self.manifest,self.idles,self.variants,_=old
            self._materials_missing=old_missing
            self.reactions.set_actions(item['id'] for item in all_items(self.manifest))
            self.gate.state='idle';self.idle();raise
        self.settings['character']=key
        self.apply_settings(self.settings['character_preferences'].get(key,{}))
        if self.bubble.report:self.bubble.report.animation.stop();self.bubble.report.hide()
        if self.chat_window:self.chat_window.shutdown();self.chat_window.deleteLater();self.chat_window=None

    def queue_material(self,tier,root):
        if self.settings.get('character','builtin')!='builtin':
            self.materials.failed('请先切回内置白龙，再切换内置素材画质');return
        self._pending_material=(tier,Path(root))
        if self._materials_missing or self._desktop_hidden or not self.settings.get('character_visible',True):self.apply_material()

    def queue_animation_update(self,ready):
        if self.materials.job or self._pending_material:
            self.updates.install_failed('素材操作正在进行，请完成后重试动画补丁');return
        if ready['root'] is None or self.settings.get('character','builtin')!='builtin':
            try:
                from animation_updates import commit
                if ready['root'] is not None:ready['store'].activate(ready['tier'],ready['root'])
                commit(ready);self.material_store=ready['store'];self.materials.store=self.material_store
                self.updates.animation_applied(ready);self.materials.changed.emit(self.materials.snapshot())
            except (OSError,ValueError) as error:self.updates.install_failed(str(error))
            return
        self._pending_animation=ready
        self.queue_material(ready['tier'],ready['root'])

    def rollback_animation_update(self):
        if self.materials.job or self._pending_material:return
        self.updates.rollback_animation(self.material_store.patch_previous)

    def apply_material(self):
        if not self._pending_material:return False
        tier,root=self._pending_material;self._pending_material=None
        animation=getattr(self,'_pending_animation',None);self._pending_animation=None
        store=animation['store'] if animation else self.material_store
        old=(self.asset_root,self.manifest,self.idles,self.variants)
        try:
            m=json.loads((root/'素材清单.json').read_text(encoding='utf-8'))
            # Fully verified in the worker. Probe the entry frame before committing preference.
            from PIL import Image
            with Image.open(root/(m['idle'].get('playbackFile') or m['idle']['file'])) as im:im.load()
            store.activate(tier,root)
            self.sustained.cancel()
            if self.player:self.player.close()
            self.player=StreamPlayer();self.player.ended=True
            self.cache.clear();self.pinned_frames.clear()
            self.asset_root=root;self.manifest=m;self.idles=[m['idle']]+m.get('additionalIdleAnimations',[]);self.variants=m.get('variants',[])
            self.current=m['idle'];self.gate.state='idle'
            self.reactions.set_actions(item['id'] for item in all_items(m))
            missing=self._materials_missing;self._materials_missing=False
            if missing:
                self.apply_settings(dict(character_visible=True,bubble=True));self.idle()
            if animation:
                from animation_updates import commit
                commit(animation);self.material_store=store;self.materials.store=store
                self.updates.animation_applied(animation)
            self.materials.applied();return True
        except (OSError,ValueError,KeyError) as error:
            self.asset_root,self.manifest,self.idles,self.variants=old
            if animation:self.updates.install_failed('动画补丁切换失败：'+str(error))
            self.materials.failed('画质切换失败：'+str(error));return False
    def remove_materials(self):
        from material_removal import removal_plan
        if self.updates.job or self.updates.state['phase']=='pending':
            self.materials.failed('请先完成当前更新');return
        if self.materials.job or self._pending_material:return
        try:plan=removal_plan(self.material_store)
        except (OSError,ValueError) as exc:self.materials.failed(str(exc));return
        size=sum(item['bytes'] for item in plan)/1048576
        text=f'移除当前程序及素材缓存中的 {len(plan)} 个动画文件（约 {size:.0f} MB），仅保留卡片。\n之后可在这里重新下载。自定义角色不删除。\n旧回退版本保留，可能仍占用部分共享空间。'
        if QMessageBox.question(self.settings_dialog,'移除动画资源',text)!=QMessageBox.StandardButton.Yes:return
        # Stop all readers before the worker unlinks any verified managed file.
        self.apply_settings(dict(character_visible=False,bubble=True));self.stop_walk();self.sustained.cancel()
        if self.player:self.player.close();self.player=None
        self.cache.clear();self.pinned_frames.clear();self._materials_missing=True
        self.settings['character']='builtin';self.save_settings();self.idle()
        self.materials.remove(plan)
    def export_diagnostics(self):
        self.record_state();path=ROOT/('白龙诊断-'+time.strftime('%Y%m%d-%H%M%S')+'.json')
        value=json.loads((STATE_DIR/'runtime.json').read_text(encoding='utf-8'))
        value['asset_count']=len(all_items(self.manifest));value['decode_error']=self.decode_error
        value.update(wander_mode=self.settings.get('wander_mode','edge'),wander_route_pending=len(self.roaming.queue),wander_window_geometry_interval=1,wander_fast_center_pass=True)
        value['work_animation_count']=len([v for v in self.manifest.get('workAnimations',[]) if v]);value['semantic_work_actions']=True;value['explicit_task_arrival_animation']=True
        atomic_json(path,value);self.say('诊断已保存：'+path.name,6000)
    def cleanup_installations(self):
        from installer import ROOT as install_root,DATA
        from installation_cleanup import cleanup_plan,CleanupJob
        if getattr(self,'_cleanup_job',None):self.say('历史版本清理正在进行。',3000);return
        try:
            plan=cleanup_plan(install_root)
            if not plan['versions'] and not plan['backups']:
                QMessageBox.information(self.settings_dialog,'清理历史版本','没有可清理的历史版本和备份。');return
            text=f"将清理 {len(plan['versions'])} 个历史版本、{len(plan['backups'])} 份旧部署备份。\n保留当前版本、最近两个回退版本、运行中的版本及相关备份。\n设置、聊天记录和当前素材保留。是否继续？"
            if QMessageBox.question(self.settings_dialog,'清理预览',text)!=QMessageBox.StandardButton.Yes:return
            self._cleanup_job=CleanupJob(install_root,DATA,plan,self)
            self._cleanup_job.done.connect(self.cleanup_done)
            self._cleanup_job.failed.connect(lambda message:QMessageBox.warning(self.settings_dialog,'清理未完成',message))
            self._cleanup_job.finished.connect(self.cleanup_finished);self._cleanup_job.start()
        except (OSError,ValueError) as error:QMessageBox.warning(self.settings_dialog,'清理未完成',str(error))
    def cleanup_done(self,result):
        if not getattr(self,'_cleanup_exit_pending',False):QMessageBox.information(self.settings_dialog,'清理完成',f"已清理 {result['versions']} 个版本、{result['backups']} 份备份。")
    def cleanup_finished(self):
        job=self._cleanup_job;self._cleanup_job=None;job.deleteLater()
        if getattr(self,'_cleanup_exit_pending',False):self.close()

    def backup_settings(self):
        path=STATE_DIR/('settings-backup-'+time.strftime('%Y%m%d-%H%M%S')+'.json');self.save_settings();shutil.copy2(CONFIG,path)
        self.say('设置备份已保存到配置目录。',5000)
    def restore_settings(self):
        path,_=QFileDialog.getOpenFileName(self.settings_dialog,'选择设置备份',str(STATE_DIR),'JSON (*.json)')
        if not path:return
        try:
            raw=json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(raw,dict):raise ValueError('设置备份格式无效')
            desired=normalized(raw);previous=copy.deepcopy(self.settings);self.backup_settings()
            try:
                if desired['character']!=self.settings['character']:self.switch_character(desired['character'])
                self.apply_settings(desired);self.restore_saved_position();self.position_bubble()
            except (OSError,ValueError):
                if self.settings['character']!=previous['character']:self.switch_character(previous['character'])
                self.apply_settings(previous);self.restore_saved_position();raise
            if self.settings_dialog:self.settings_dialog.reload()
        except (OSError,ValueError) as error:QMessageBox.warning(self.settings_dialog,'恢复失败',str(error))
    def record_state(self):
        path=STATE_DIR/'runtime.json';value=super().runtime_state()
        now=time.monotonic()
        value['activity_projection']=dict(display_busy=self.bubble.status_indicator.is_busy(),animation_busy=self.reactions.busy(now),
            known_animation_sessions=len(self.reactions.sessions),
            recent_active_leases=sum(active and now-stamp<=35 for turn,active,stamp in self.reactions.leases.values()),
            recent_idle_leases=sum(not active and now-stamp<=35 for turn,active,stamp in self.reactions.leases.values()))
        value['status_icon_timing']=self.bubble.status_indicator.timing_snapshot()
        value['material_status_cached']=True
        from decode_runtime import STATS
        value.update(shared_body_tail_decode=True,nonblocking_decoder_cancel=True,adaptive_animation_clock=True,high_resolution_frame_clock=True,frame_clock_resolution=time.get_clock_info('perf_counter').resolution,idle_movement_timer_ms=1000,
            decode_runtime=STATS.snapshot(),animation_wakeups=self.animation_wakeups,movement_wakeups=self.movement_wakeups,decode_error=self.decode_error)
        value.update(material_tiers=True,material_default='light',material_current=self.material_store.current,
            program_only_updates=True,animation_only_updates=True,animation_patch_rollback=True,report_page_stable_height=True,wsl_integration=True,wsl_source=bool(getattr(self.activity,'wsl',False)),program_update_material_verification=True,program_update_full_fallback=True,
            material_resolution=(720 if self.material_store.current=='hd' else 512) if self.material_store.current else None,material_hd_cached=self.material_store.known_available('hd'),
            material_content_id=self.material_store.catalog['tiers'][self.material_store.current]['id'] if self.material_store.catalog and self.material_store.current else None,
            material_switch_pending=bool(self._pending_material))
        value.update(native_client_hit_testing=True,shared_paint_hit_transform=True,lost_mouse_grab_recovery=True,character_switch_keeps_navigation=True,
            independent_card_surface=True,character_visible=self.settings['character_visible'],minimal_quota_mode=True,hidden_character_decoder_paused=not self.settings['character_visible'] and not self.tick.isActive(),
            isolated_transition_preparation=True,cleared_native_landing=True,linked_report_motion=True,
            continuous_state_playback=True,sustained_animation_phase=self.sustained.phase,sustained_animation_cycles=self.sustained.cycles,
            natural_sustained_variants=False,semantic_sustained_loops=True,isolated_report_presentation=True,sustained_animation_variant=self.sustained.variant_index,
            sustained_supported_actions=[i['id'] for i in self.manifest.get('workAnimations',[]) if i.get('sustained')],status_stability_seconds=self.continuous.stable_seconds,
            asset_count=len(all_items(self.manifest)),work_animation_count=len([v for v in self.manifest.get('workAnimations',[]) if v]),
            upstream_animation_version=self.manifest.get('upstreamAnimationVersion'),segmented_movement=True,
            movement_phase=self.locomotion.phase,movement_cycles=self.locomotion.cycles,
            semantic_work_actions=True,explicit_task_arrival_animation=True,current_animation=self.current.get('id') if self.current else None,
            sustained_work_response=True,status_action_interval=self.reactions.interval,animation_lifecycle_leases=len(self.reactions.leases),
            smoothed_token_curves=True,conversation_hover_contrast=True,asynchronous_codex_navigation=True,
            in_app_updates=True,update_phase=self.updates.state['phase'] if hasattr(self,'updates') else 'idle',update_checks_enabled=self.settings.get('update_checks',True),
            last_reaction_kind=self.last_reaction.kind if self.last_reaction else None,
            pending_task_greetings=len(self.reactions.openings),animation_decoder_queue=self.player.frames.qsize() if self.player else 0)
        import psutil
        process=psutil.Process();mem=process.memory_info()
        snapshot=self.bubble.token_snapshot or {}
        idle_cache=self.player.loop_cache.stats() if self.player else dict(bytes=0,hits=0,limit=24*1048576)
        from typography import LATIN_FAMILY,CHINESE_FAMILY,register_font
        report=self.bubble.report
        report_data=snapshot.get('report') or {}
        value.update(ui_revision=87,wander_horizontal_only=self.settings['wander_horizontal_only'],wander_corridor='screen_strategy',chinese_font=CHINESE_FAMILY,typography_style="noto_chakra_medium",chat_config_safe_commit=True,chat_response_formats="sse_json",chat_actionable_errors=True,panel_detached=self.settings.get("panel_detached",False),codex_exit_enabled=self.settings.get("codex_exit",False),glide_interval_ms=16,update_download_channel_fallback=True,reset_countdown_format='hours_minutes',read_terminal_turn_acknowledgement=True,reset_countdown_priority=True,customizable_capsule_shortcut=True,capsule_shortcut=self.settings['capsule_action'],codex_startup_supported=True,hourly_token_entry='today_tokens',unified_refresh=True,icon_only_header_actions=True,refresh_icon_style='single_arc',icon_motion_speed=1.2,busy_icon_style='alternating_liquid',idle_icon_style='slow_liquid_orbit',liquid_status_family=True,status_icon_morph=True,status_waiting_live_flags=True,island_quota_segmented=False,island_quota_style='open_arc',island_quota_numeric_only=True,native_shrink_landing=True,shrink_preserves_chart_progress=True,native_landing_hold_ms=0,cached_chart_layers=True,stable_report_scrollbar=True,animated_deck_tabs=True,incremental_deck_switch=True,prewarmed_transition_landing=True,monotone_container_motion=True,status_updates_preserve_surface=True,capsule_pixel_handoff=True,atomic_transition_handoff=True,clean_report_dismiss=True,stable_disclosure_gutter=True,unified_card_motion=True,report_continuous_shape=True,animated_disclosures=True,week_quota_palette=True,continuous_surface_morph=True,shared_status_glyph=True,apple_island_reference=True,panel_shrink_spring=True,panel_dismiss_spring=True,panel_shrink_ms=440,panel_dismiss_ms=360,lossless_asset_pack=self.material_store.current=='hd',lossless_asset_encoding=True,lightweight_resampling=self.material_store.current=='light',lightweight_maintenance=True,optional_webm_converter=True,shared_version_assets=True,fair_activity_targets=True,persistent_completion_ledger=True,cached_log_discovery=True,chat_incremental_stream=True,installation_ready_receipt=True,semantic_controls=True,labeled_header_actions=False,editor_keyboard_save=True,capability_health=True,connection_path_picker=True,report_scope_groups=True,report_model_filter_explicit=True,settings_draft_merge=True,settings_dirty_fields_only=True,context_menu_root_items=8,tray_recovery_menu=True,editor_returns_to_origin=True,chat_destructive_confirmation=True,quota_query_silent=True,subagent_completion_filter=True,ring_persistent_legend=False,quota_display_layout='labeled_bars',quota_reset_per_window=True,today_tokens_direct_value=True,book_reference_count=27,island_click_opens_normal=True,conversation_name_pointer_feedback=True,context_compaction_tracking=True,conversation_name_navigation=True,codex_live_status_connected=bool(self.activity and self.activity.live_reader and self.activity.live_reader.connected),daily_report_incremental_updates=True,daily_report_chart_start_after_show=True,quota_source_header_visible=False,incremental_status_refresh=True,skip_unchanged_log_reads=True,single_runtime_write=True,read_acknowledgement_history=True,read_acknowledgement_settle_seconds=4,conversation_names_visible=True,completed_conversation_background=True,independent_conversation_scroll=True,operation_status_summary=True,session_read_tracking=True,conversation_status_limit=2,codex_connection_diagnostics=True,portable_codex_discovery=True,island_bubble=True,island_quota_priority=True,bubble_mode=self.bubble.bubble_mode,bubble_auto_compact=self.bubble.auto_compact,island_visible=self.bubble.is_island(),panel_transition_stable_canvas=True,panel_transition_content_blend=True,chart_entry_animation=True,daily_report=True,daily_report_stable_surface=True,token_scan_background=True,token_models=len({r['model'] for r in report_data.get('daily_models',[])}),token_report_hours=len(report_data.get('hours',[])),daily_report_visible=bool(report and report.isVisible()),daily_report_aligned=not report or not report.isVisible() or (report.content_geometry().width()==self.bubble.width() and report.content_geometry().x()==self.bubble.x() and report.content_geometry().bottom()+1==self.bubble.y()-6),ring_center_y=None,daily_report_open=bool(self.bubble.report and self.bubble.report.requested),inline_explanations_only=True,version=VERSION,status_icon_animated=True,status_icon_unread=len(self.bubble.status_indicator.unread),status_icon_acknowledgement=True,status_icon_state=self.bubble.status_indicator.visual(),status_icon_timer=self.bubble.status_indicator.timer.isActive(),panel_transition_no_fade=True,panel_transition_staged_layout=True,panel_transition_ms=480,idle_cache_mb=round(idle_cache['bytes']/1048576,2),idle_cache_limit_mb=idle_cache['limit']/1048576,idle_cache_hits=idle_cache['hits'],integrated_panels=True,panel_page=self.bubble.panel_page,separate_panel_windows=sum(bool(p and p.isWindow()) for p in (self.settings_dialog,self.chat_window)),expanded_details_grouped=True,latin_font=LATIN_FAMILY,latin_font_loaded=register_font(),status_height_transition_ms=300,status_transition_synchronized=True,token_chart_range=self.bubble.token_range,
            token_history_days=len(snapshot.get('history_days',{})),token_hour_slots=len(snapshot.get('hours',[])),
            mode=self.mode,action_state=self.gate.state,mouse_through=self.settings['mouse_through'],scale=self.settings['scale'],
            facing=self.walk_direction,decoder_queue=self.player.frames.qsize() if self.player else 0,first_frame_cache=len(self.player.first) if self.player else 0,
            decode_size=self.frame_size,decode_expected_size=self.desired_decode_size(),character_logical_size=[self.width(),self.height()],character_device_pixel_ratio=self.devicePixelRatioF(),frame_pixel_size=[self.frames[self.index].width(),self.frames[self.index].height()] if self.frames else None,source_frame=self.player.frame_index if self.player else 0,quality_revision=self.manifest.get('qualityRevision',0),
            status_reactions=self.settings['status_actions'],reaction_samples=self.reactions.sample_count,
            reaction_kind=self.last_reaction.kind if self.last_reaction else None,reaction_action=self.last_reaction.action_id if self.last_reaction else None,
            completion_animation_pending=self.reactions.completion is not None,
            rss_mb=round(mem.rss/1048576,1),uptime=round(time.monotonic()-self.created_at,1),throwing=self.throwing)
        if self.connection_health.records['quota']['state']=='available' and any(w.get('resetsAt') and w['resetsAt']<=time.time() for w in self.quota_windows):
            self.connection_health.record('quota',dict(state='degraded',code='quota_expired'))
        value['ui_revision']=89
        value['edge_docked']=self.edge_dock.active;value['edge_side']=self.edge_dock.side;value['edge_pose']=self.edge_dock.amount
        value['distinct_theme_palettes']=True
        value['preview_header_icons']=True
        value['island_centered_status']=True
        value['island_status_transition_ms']=250
        value['single_native_tray_identity']=True
        if hasattr(self.tray,'diagnostics'):value['tray_identity']=self.tray.diagnostics()
        value['isolated_shell_registration_disabled']=not getattr(self,'_tray_shell_enabled',False)
        value['report_minimum_width']=report.MIN_WIDTH if report else 268
        if report and report.isVisible() and not report.follow.active and not report._animating:
            value['daily_report_aligned']=report.content_geometry()==report.geometry_for_host(self.bubble.geometry())
        value['video_fullscreen_yield_enabled']=self.settings['fullscreen_yield_mode'] in ('video','game_video')
        value['fullscreen_yield_mode']=self.settings.get('fullscreen_yield_mode','video')
        value['fullscreen_window_yielding']=self._fullscreen_yielded
        value['video_fullscreen_yielding']=self._video_yielded
        value['video_detector_running']=bool(self.video_yield and self.video_yield.worker and self.video_yield.worker.is_alive())
        value['video_detection_reason']=self.video_yield.reason if self.video_yield else 'disabled'
        value['video_detection_sample']=self.video_yield.last_sample if self.video_yield else {}
        value['video_native_yield_applied']=bool(self.video_yield and self.video_yield.native_applied)
        value['video_completion_priority']=value['fullscreen_yield_mode']=='video'
        value['video_firefox_backend']='ia2_video_tag'
        value['video_completion_override']=bool(self.video_yield and self.video_yield.attention_override)
        value['connection_health']=self.connection_health.snapshot()
        from performance_metrics import METRICS
        if METRICS.enabled:value['performance']=METRICS.snapshot()
        if self.activity:
            self.recently_visited={sid:t for sid,t in getattr(self,'recently_visited',{}).items() if time.monotonic()-t<120}
            self.activity.set_context(self.bubble.roster.pinned,self.recently_visited)
        if self.settings_dialog and self.settings_dialog.isVisible():self.connectionHealthChanged.emit(value['connection_health'])
        atomic_json(path,value)
    def closeEvent(self,event):
        if getattr(self,'_cleanup_job',None):
            self._cleanup_exit_pending=True;event.ignore();return
        if hasattr(self,'materials') and not self.materials.shutdown():
            if not self._material_exit_pending:self._material_exit_pending=True;self.materials.idle.connect(self.close)
            event.ignore();return
        if self.settings_dialog and self.settings_dialog.path_job and self.settings_dialog.path_job.isRunning():
            if not getattr(self,'_path_exit_pending',False):
                self._path_exit_pending=True;self.settings_dialog.path_job.finished.connect(self.close)
            event.ignore();return
        if self.settings_dialog and self.settings_dialog.connection_job and self.settings_dialog.connection_job.isRunning():
            self.settings_dialog.connection_job.cancel.set()
            if not getattr(self,'_connection_exit_pending',False):
                self._connection_exit_pending=True;self.settings_dialog.connection_job.finished.connect(self.close)
            event.ignore();return
        if self.settings_dialog and self.settings_dialog.job and self.settings_dialog.job.isRunning():
            self.say('素材导入仍在进行，请完成后退出。',5000);event.ignore();return
        if hasattr(self,'updates') and not self.updates.shutdown():
            if not self._update_exit_pending:self._update_exit_pending=True;self.updates.idle.connect(self.close)
            event.ignore();return
        self._codex_closing=True;self.codex_timer.stop();self.click_timer.stop();self.last_click=None
        self.edge_dock.shutdown();self.cancel_pointer();self.sustained.cancel();self.locomotion.cancel();self.codex_navigation.close()
        if self.bubble.report:self.bubble.report.animation.stop();self.bubble.report.hide()
        if self.chat_window:self.chat_window.shutdown()
        if self.settings_dialog:self.settings_dialog.hide()
        if self.player:self.player.close()
        if self.video_yield:self.video_yield.shutdown()
        super().closeEvent(event)
