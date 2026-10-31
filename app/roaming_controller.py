"""Own one autonomous route; rendering and natural landing stay in DesktopPet."""
from roaming import plan,legal_bounds
from roaming_window import ForegroundGeometry

POLICY_KEYS=('wander_mode','wander_side','wander_zone','wander_horizontal_only','move_range','move_speed','panel_detached','bubble','scale')

class RoamingController:
    def __init__(self,pet):
        self.pet=pet;self.reader=ForegroundGeometry();self.queue=[];self.last=None;self.context=None;self.window=None;self.checked_at=0;self.rest_pending=False
    def cancel(self):self.queue.clear();self.context=None;self.rest_pending=False
    def footprint(self):
        p=self.pet;l=t=0;r=p.width();b=p.height();bubble=p.bubble
        if not p.settings.get('panel_detached') and p.settings.get('bubble') and bubble.isVisible():
            rect=bubble.size_transition.visible_geometry();l=min(l,rect.left()-p.x());t=min(t,rect.top()-p.y());r=max(r,rect.right()+1-p.x());b=max(b,rect.bottom()+1-p.y())
        return (l,t,r,b)
    def next(self,screen,area,home,uniform):
        p=self.pet;footprint=self.footprint();rect=(area.x(),area.y(),area.width(),area.height())
        key=(screen.name(),rect,footprint,repr([p.settings.get(k) for k in POLICY_KEYS]))
        if self.context!=key:self.cancel()
        self.context=key
        if not self.queue:
            self.window=self.reader.read(p) if p.settings.get('wander_mode')=='window' else None
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
        return min(300,max(180,base*2.5)) if self.last and self.last.fast_cross and contains((x,y),self.last.center) else base
    def may_timeout(self,x,y):
        from roaming import contains
        return not (self.last and self.last.fast_cross and contains((x,y),self.last.center))
    @property
    def wait_factor(self):return self.last.wait_factor if self.last else 1.
