"""Manual edge peeking on the existing pet surface; no extra native window."""
from PySide6.QtCore import QObject,QPoint,QRect,QRectF,QTimer,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QTransform,QCursor
from PySide6.QtWidgets import QApplication
from settings_controls import motion_enabled

def candidate(position,size,area,threshold=12):
    left=area.left();right=max(left,area.right()-size.width()+1)
    if abs(position.x()-left)<=threshold:return 'left'
    if abs(position.x()-right)<=threshold:return 'right'
    return None

def pose(canvas,side,amount):
    t=QTransform()
    if not side or amount<=0:return t
    sign=-1 if side=='left' else 1
    c=canvas.center();t.translate(c.x()+sign*canvas.width()*.40*amount,c.y())
    t.rotate(-sign*60*amount);t.translate(-c.x(),-c.y());return t

class EdgeDock(QObject):
    def __init__(self,pet):
        super().__init__(pet);self.pet=pet;self.side=None;self.amount=0.;self.temporary=False;self.drop_latched=False
        self.animation=QVariantAnimation(self);self.animation.setDuration(240)
        self.target_amount=0.
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.animation.valueChanged.connect(self._advance)
        self.hover_timer=QTimer(self);self.hover_timer.setSingleShot(True);self.hover_timer.timeout.connect(self._hover_check)
    @property
    def active(self):return self.side is not None
    def available(self):
        p=self.pet
        return bool(p.settings.get('edge_docking',True) and p.settings.get('character_visible',True) and not p._materials_missing)
    def visible(self):
        p=self.pet
        return p.isVisible() and not p._desktop_hidden and not p._fullscreen_yielded
    def try_dock(self):
        p=self.pet
        if not self.available() or p.settings.get('no_move') or not self.visible():return False
        screen=p.screen() or QApplication.primaryScreen()
        if screen is None:return False
        area=screen.availableGeometry();side=candidate(p.pos(),p.size(),area)
        if not side:return False
        p.stop_walk();p.throwing=False;p.sustained.cancel();p.continuous.clear();p.gate.state='idle'
        self.side=side;self.target_amount=1.;self.temporary=False;self.drop_latched=True;self.reanchor(area)
        p.play(p.manifest['idle'],'idle');p.bubble.set_edge_compact(not p.settings.get('panel_detached',False))
        self._animate(1.);p.position_bubble();return True
    def reanchor(self,area=None):
        p=self.pet
        if not self.active:return
        if area is None:
            screen=p.screen() or QApplication.primaryScreen()
            if screen is None:return
            area=screen.availableGeometry()
        x=area.left() if self.side=='left' else max(area.left(),area.right()-p.width()+1)
        y=max(area.top(),min(p.y(),max(area.top(),area.bottom()-p.height()+1)))
        point=QPoint(x,y)
        if p.pos()!=point:p.move(point)
    def reveal(self,temporary=False):
        if not self.active:return
        if not temporary:self.clear();return
        if self.pet._pointer_pressed:return
        if self.drop_latched:return
        self.temporary=True;self._animate(0.);self.hover_timer.start(650)
    def observe_pointer(self):
        # Use the full canvas: alpha-hit changes during the fold generate
        # synthetic enter/leave events even though the pointer never moved.
        if self.drop_latched and not self.pet.frameGeometry().contains(QCursor.pos()):self.drop_latched=False
    def leave(self):
        if self.drop_latched:self.observe_pointer();return
        if self.active and self.temporary:self.hover_timer.start(250)
    def _hover_check(self):
        if not self.active or not self.visible():self.temporary=False;return
        if self.pet._pointer_pressed or self.pet.frameGeometry().contains(QCursor.pos()):self.hover_timer.start(250);return
        self.temporary=False;self._animate(1.)
    def _animate(self,value,immediate=False):
        self.animation.stop()
        self.target_amount=float(value)
        if immediate or not self.visible() or not motion_enabled():self._advance(value);return
        self.animation.setStartValue(self.amount);self.animation.setEndValue(float(value));self.animation.start()
    def _advance(self,value):self.amount=float(value);self.pet.update();self.pet.position_bubble()
    def clear(self,immediate=False,update_panel=True):
        if not self.active and self.amount==0:return
        self.hover_timer.stop();self.temporary=False;self.drop_latched=False
        # Keep the pose's side until the final frame of its reveal animation.
        if immediate:self.animation.stop();self.amount=0.;self.target_amount=0.;self.side=None;self.pet.update()
        else:
            self._animate(0.)
            # The logical dock state ends now; paint still needs the old side.
            self._revealing_side=self.side;self.side=None
        if update_panel:self.pet.bubble.set_edge_compact(False)
        self.pet.next_chain=__import__('time').monotonic()+self.pet.settings['random_interval']
    def transform(self,canvas):return pose(canvas,self.side or getattr(self,'_revealing_side',None),self.amount)
    def card_geometry(self,size,progress=None):
        p=self.pet;b=p.bubble
        side=self.side or getattr(self,'_revealing_side',None)
        f=self.amount if progress is None else progress
        if not side or f<=0:return b.content_geometry(size,docked=False)
        area=(p.screen() or QApplication.primaryScreen()).availableGeometry()
        head=pose(QRectF(p.rect()),side,1.).mapRect(QRectF(p.width()*.30,p.height()*.10,p.width()*.45,p.height()*.42)).intersected(QRectF(p.rect()))
        head.translate(p.x(),p.y())
        # Keep more breathing room than 1.9.1, scaled with the character.
        x=round(head.center().x()-size.width()/2);y=round(head.top()-size.height()+p.height()*.025)
        if y<area.top():y=round(head.bottom()+10)
        reserve=b.report.reserved_height(size)+6 if b.report and b.report.requested else 0
        reserve=min(reserve,max(0,area.height()-size.height()))
        x=max(area.left(),min(x,area.right()-size.width()+1));y=max(area.top()+reserve,min(y,area.bottom()-size.height()+1))
        base=b.content_geometry(size,docked=False);f=max(0.,min(1.,f))
        return QRect(round(base.x()+(x-base.x())*f),round(base.y()+(y-base.y())*f),size.width(),size.height())
    def reconcile(self):
        if not self.available():self.clear(immediate=True);return
        if not self.active:return
        self.pet.bubble.set_edge_compact(not self.pet.settings.get('panel_detached',False))
        if not self.visible():
            self.animation.stop();self.hover_timer.stop();self.temporary=False;self.amount=1.;return
        self.reanchor()
    def shutdown(self):self.animation.stop();self.hover_timer.stop()
