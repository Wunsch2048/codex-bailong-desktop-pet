"""One short clock for either independent digit slots or a whole numeric value."""
import math
import re
from PySide6.QtCore import QObject,QVariantAnimation,QAbstractAnimation,QEasingCurve,Qt,QPointF,QRectF,QTimer
from PySide6.QtGui import QFontMetricsF
from settings_controls import motion_enabled,play_animation

DIGIT_EASING=QEasingCurve(QEasingCurve.Type.BezierSpline)
DIGIT_EASING.addCubicBezierSegment(QPointF(.42,0),QPointF(.58,1),QPointF(1,1))

class NumberRoll(QObject):
    def __init__(self,widget,digits=False,allow_decrease=False):
        super().__init__(widget);self.widget=widget;self.digits=digits;self.current='';self.target='';self.value=None;self.target_value=None
        self.progress=1.;self.direction=1;self.pending=None;self.digit_tracks={};self.allow_decrease=allow_decrease
        self._clock_progress=1.
        self._font_key=None;self._slots_key=None;self._slots=();self._old_slots=();self._paint_rect=None;self.rebuilding=False;self._rebuild_ticket=0
        self.animation=QVariantAnimation(self);self.animation.setDuration(180);self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.animation.valueChanged.connect(self.advance);self.animation.finished.connect(self.finish)
    @staticmethod
    def numeric(value):
        try:return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
        except OverflowError:return False
    def set(self,text,value,animate=True):
        text=str(text)
        if (not animate and not self.rebuilding) or not motion_enabled() or not self.current or not self.numeric(value) or not self.numeric(self.target_value):
            self.snap(text,value);return
        if self.animation.state()==QAbstractAnimation.State.Running:
            self.pending=(text,value) if text!=self.target else None;self.target_value=value if text==self.target else self.target_value;return
        if text==self.current:self.value=self.target_value=value;return
        # Day rollovers/corrections and unit switches are not growing digits.
        suffix=lambda s:''.join(c for c in s if c.isalpha())
        if self.digits and ((value<self.value and not self.allow_decrease) or suffix(text)!=suffix(self.current)):
            self.snap(text,value);return
        self.digit_tracks,steps=self.tracks(self.current,text) if self.digits else ({},0)
        self.animation.setDuration(min(420,220+steps*10) if steps>1 else 180)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear if self.digits else QEasingCurve.Type.OutCubic)
        self._clock_progress=0.
        self.target=text;self.target_value=value;self.direction=1 if value>=self.value else -1;self.progress=0.;play_animation(self.animation)
    @staticmethod
    def tracks(before,after):
        pattern=r'(\d+)(\.\d+)?(.*)'
        old=re.fullmatch(pattern,before);new=re.fullmatch(pattern,after)
        if not old or not new or old.groups()[2]!=new.groups()[2] or len(old[2] or '')!=len(new[2] or ''):
            return {},0
        first=int(old[1]+(old[2] or '').replace('.',''))
        last=int(new[1]+(new[2] or '').replace('.',''))
        steps=abs(last-first)
        if steps<=1:return {},steps
        direction=1 if last>first else -1
        tracks={};place=1
        whole=max((old[1],new[1]),key=len)
        for index,char in enumerate(reversed(whole+(new[2] or '')+new[3])):
            if index<len(new[3]) or char=='.':continue
            start,end=first//place,last//place
            if end!=start:
                carry=place-first%place if direction>0 else first%place+1
                delay=0. if place==1 else min(.68,.65*carry/steps)
                blank=place>=10**(min(len(old[1]),len(new[1]))+len((new[2] or '').replace('.','')))
                tracks[index]=(start,abs(end-start),delay,blank)
            place*=10
        return tracks,steps
    def snap(self,text=None,value=None):
        self.animation.stop()
        if text is None:text,value=self.pending or (self.target,self.target_value)
        self.current=self.target=str(text);self.value=self.target_value=value;self.pending=None;self.digit_tracks={};self.progress=1.;self.redraw()
    def redraw(self):
        if self._paint_rect is None:self.widget.update()
        else:self.widget.update(self._paint_rect.toAlignedRect())
    def advance(self,value):
        self._clock_progress=float(value)
        self.progress=DIGIT_EASING.valueForProgress(value) if self.digits else value
        self.redraw()
    def finish(self):
        self.current=self.target;self.value=self.target_value;self.progress=1.;pending=self.pending;self.pending=None;self.redraw()
        if pending:self.set(*pending,animate=self.widget.isVisible())
    def begin_rebuild(self,preserve):
        self._rebuild_ticket+=1;ticket=self._rebuild_ticket;self.rebuilding=bool(preserve)
        if not preserve:self.snap()
        QTimer.singleShot(0,self,lambda:self.end_rebuild(ticket))
    def end_rebuild(self,ticket):
        if ticket!=self._rebuild_ticket:return
        self.rebuilding=False
        if not self.widget.isVisible():self.snap()
    def metrics(self,font,device=None):
        device=self.widget if device is None else device
        key=(font.toString(),device.logicalDpiX(),device.logicalDpiY())
        if key!=self._font_key:
            self._font_key=key;self._metrics=QFontMetricsF(font,device)
            self._digit=max(self._metrics.horizontalAdvance(str(n)) for n in range(10));self._slots_key=None
        return self._metrics,self._digit
    def paint(self,p,rect):
        rect=QRectF(rect);self._paint_rect=rect;running=self.animation.state()==QAbstractAnimation.State.Running
        if not running and not self.digits:p.drawText(rect,Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,self.current);return
        p.save();p.setClipRect(rect)
        distance=rect.height();offset=self.progress*distance*self.direction
        if not self.digits:
            p.drawText(rect.translated(0,-offset),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,self.current)
            p.drawText(rect.translated(0,self.direction*distance-offset),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,self.target)
        else:
            fm,digit=self.metrics(p.font(),p.device() if hasattr(p,'device') else None)
            ink=fm.tightBoundingRect('0123456789')
            baseline=rect.center().y()+(fm.ascent()-fm.descent())/2
            digit_clip=rect.intersected(QRectF(rect.left(),baseline+ink.top()-1,rect.width(),ink.height()+2))
            distance=digit_clip.height()
            offset=self.progress*distance*self.direction
            target=self.target if running else self.current
            key=(self._font_key,self.current,target,rect.x(),rect.y(),rect.width(),rect.height())
            if key!=self._slots_key:
                def fitted(text):
                    measure=fm.horizontalAdvance
                    if measure(text)<=rect.width():return text
                    while text and measure(text+'…')>rect.width():text=text[:-1]
                    return text+'…' if fm.horizontalAdvance('…')<=rect.width() else ''
                def layout(text):
                    start=rect.right()-fm.horizontalAdvance(text)
                    return list(reversed([(c,QRectF(start+fm.horizontalAdvance(text[:i+1])-fm.horizontalAdvance(c),rect.y(),fm.horizontalAdvance(c),rect.height())) for i,c in enumerate(text)]))
                old=layout(fitted(self.current));new=layout(fitted(target));slots=[];old_slots=[]
                for index in range(max(len(old),len(new))):
                    a,old_slot=old[index] if index<len(old) else ('',new[index][1])
                    b,new_slot=new[index] if index<len(new) else ('',old[index][1])
                    slots.append((a,b,new_slot));old_slots.append(old_slot)
                self._slots=tuple(slots);self._old_slots=tuple(old_slots);self._slots_key=key
            tracks=self.digit_tracks if running and fm.horizontalAdvance(self.current)<=rect.width() and fm.horizontalAdvance(target)<=rect.width() else {}
            for index,((a,b,slot),old_slot) in enumerate(zip(self._slots,self._old_slots)):
                right=old_slot.right()+(slot.right()-old_slot.right())*(self.progress if running else 1.)
                aw=old_slot.width() if a else 0.;bw=slot.width() if b else 0.
                before=QRectF(right-aw,rect.y(),aw,rect.height())
                after=QRectF(right-bw,rect.y(),bw,rect.height())
                flags=Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter
                if index in tracks:
                    start,count,delay,blank=tracks[index]
                    local_progress=max(0.,(self._clock_progress-delay)/(1-delay))
                    phase=count*DIGIT_EASING.valueForProgress(local_progress)
                    step=min(count,int(phase));fraction=phase-step
                    p.save();p.setClipRect(digit_clip)
                    for shift in range(1 if step==count else 2):
                        digit_value=start+(step+shift)*self.direction
                        if blank and digit_value==0:continue
                        digit_text=str(digit_value%10)
                        width=fm.horizontalAdvance(digit_text)
                        p.drawText(QRectF(right-width,rect.y()+(shift-fraction)*distance*self.direction,width,rect.height()),flags,digit_text)
                    p.restore()
                elif a==b:p.drawText(after,flags,b)
                else:
                    p.save();p.setClipRect(digit_clip)
                    p.drawText(before.translated(0,-offset),flags,a);p.drawText(after.translated(0,self.direction*distance-offset),flags,b)
                    p.restore()
        p.restore()
    def width(self,font,text=None):
        fm,digit=self.metrics(font);text=self.target if text is None else text
        return fm.horizontalAdvance(text)
