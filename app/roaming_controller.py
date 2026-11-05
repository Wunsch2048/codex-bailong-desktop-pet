"""Own one autonomous route; rendering and natural landing stay in DesktopPet."""
from roaming import plan,legal_bounds
from roaming_window import ForegroundGeometry
import time

POLICY_KEYS=('wander_mode','wander_side','wander_zone','wander_horizontal_only','move_range','move_speed','panel_detached','bubble','scale')

class RoamingController:
    def __init__(self,pet):
        self.pet=pet;self.reader=ForegroundGeometry();self.queue=[];self.last=None;self.context=None;self.window=None;self.checked_at=0;self.rest_pending=False
        self.pending_start=False;self.paused_until=None;self.compact_owned=False
    def cancel(self):
        self.queue.clear();self.context=None;self.rest_pending=False
        self.pending_start=False;self.paused_until=None;self.compact_owned=False
    def prepare_panel(self,now):
        """Collect before planning: the route uses the compact footprint."""
        p=self.pet;b=p.bubble
        if self.paused_until is not None and now<self.paused_until:return False
        if p.settings.get('panel_detached') or not b.enabled or not b.isVisible():return True
        if b.size_transition.running or b.size_transition.preparing:
            self.pending_start=True;return False
        self.compact_owned=True
        if b.is_compact():self.pending_start=False;return True
        b.size_transition.begin();b.auto_compact=True;b._minimal_normal_open=False
        b.expanded=False;b.panel_page='status';b._editor_origin=None
        b._editing_flags(False);b.redraw();b.size_transition.commit()
        self.pending_start=True;return False
    def interrupt(self,now):
        p=self.pet
        if p.settings.get('panel_detached') or not (p.walking or self.pending_start or self.paused_until is not None):return
        if p.walking:
            # next() has already removed this leg; preserve it ahead of the
            # remaining route so opening a card does not discard the journey.
            if p.walk_target:self.queue.insert(0,tuple(p.walk_target[:2]))
            p.stop_walk(land=True,preserve_route=True)
        self.pending_start=False;self.compact_owned=False;self.paused_until=now+5
    def activity(self,now,pressed=False):
        if pressed:self.interrupt(now)
        if self.paused_until is not None:self.paused_until=now+5
    def tick(self,now):
        p=self.pet;b=p.bubble
        if p.walking and self.compact_owned and not b.is_compact():self.interrupt(now)
        if not (self.pending_start or self.paused_until is not None):return
        if self.paused_until is not None and now<self.paused_until:return
        if p.walking or p.locomotion.active or p.dragging or p.throwing:return
        if p.settings.get('no_move') or not p.wandering:self.cancel();return
        p.start_walk()
    def footprint(self):
        p=self.pet;l=t=0;r=p.width();b=p.height();bubble=p.bubble
        if not p.settings.get('panel_detached') and p.settings.get('bubble') and bubble.isVisible():
            rect=bubble.size_transition.visible_geometry();l=min(l,rect.left()-p.x());t=min(t,rect.top()-p.y());r=max(r,rect.right()+1-p.x());b=max(b,rect.bottom()+1-p.y())
        return (l,t,r,b)
    def next(self,screen,area,home,uniform):
        p=self.pet;footprint=self.footprint();rect=(area.x(),area.y(),area.width(),area.height())
        key=(screen.name(),rect,footprint,repr([p.settings.get(k) for k in POLICY_KEYS]))
        if self.context!=key:self.queue.clear();self.rest_pending=False
        self.context=key
        if p.settings.get('wander_mode')=='window':
            current=self.reader.read(p)
            if current!=self.window:self.queue.clear()
            self.window=current
        if not self.queue:
            if p.settings.get('wander_mode')!='window':self.window=None
            self.last=plan((p.x(),p.y()),home,rect,footprint,p.settings,uniform,self.window)
            self.queue=list(self.last.points)
        if not self.queue:return None
        target=self.queue.pop(0)
        # Body remains inside the work area. Attached-card occupancy was used
        # when planning, but never changes the character's actual window size.
        bounds=(area.left(),area.top(),area.right()-p.width()+1,area.bottom()-p.height()+1)
        return target,bounds
    def foreground_changed(self,now):
        if self.pet.settings.get('wander_mode')!='window' or now<self.checked_at:return False
        self.checked_at=now+1
        current=self.reader.read(self.pet)
        changed=current!=self.window
        if changed:self.cancel();self.window=current
        return changed
    def speed(self,x,y,base):
        from roaming import contains
        escape=self.last and (self.last.fast_cross or self.last.mode!='zone') and contains((x,y),self.last.center)
        return min(300,max(180,base*2.5)) if escape else base
    def may_timeout(self,x,y):
        from roaming import contains
        return not (self.last and contains((x,y),self.last.center))
    @property
    def wait_factor(self):return self.last.wait_factor if self.last else 1.


def watch_interaction(pet):
    """One cheap filter, active only during a route or its interaction pause."""
    from PySide6.QtCore import QObject,QEvent
    from PySide6.QtWidgets import QApplication,QWidget
    class InputFilter(QObject):
        def eventFilter(self,obj,event):
            r=pet.roaming
            if not (pet.walking or r.pending_start or r.paused_until is not None):return False
            kind=event.type()
            if kind not in (QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease,
                            QEvent.Type.MouseMove,QEvent.Type.Wheel,QEvent.Type.KeyPress):return False
            if not isinstance(obj,QWidget):return False
            roots=(pet,pet.bubble,pet.bubble.report,pet.settings_dialog,pet.chat_window)
            if any(root is not None and (obj is root or root.isAncestorOf(obj)) for root in roots):
                r.activity(time.monotonic(),kind==QEvent.Type.MouseButtonPress)
            return False
    listener=InputFilter(pet);QApplication.instance().installEventFilter(listener)
    return listener
