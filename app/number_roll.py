"""One short clock for either independent digit slots or a whole numeric value."""
import math
import re
from PySide6.QtCore import QObject,QVariantAnimation,QAbstractAnimation,QEasingCurve,Qt,QRectF,QTimer
from PySide6.QtGui import QFontMetricsF
from settings_controls import motion_enabled,play_animation

DIGIT_EASING=QEasingCurve(QEasingCurve.Type.InOutSine)
DIGIT_DURATION_MS=320
MAX_DIGIT_DURATION_MS=420

class NumberRoll(QObject):
    def __init__(self,widget,digits=False,allow_decrease=False):
        super().__init__(widget);self.widget=widget;self.digits=digits;self.current='';self.target='';self.value=None;self.target_value=None
        self.progress=1.;self.direction=1;self.pending=None;self.allow_decrease=allow_decrease;self.digit_tracks={}
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
        # Day resets, corrections and unit changes use the settled layout.
        suffix=lambda s:''.join(c for c in s if c.isalpha())
        if self.digits and ((value<self.value and not self.allow_decrease) or suffix(text)!=suffix(self.current)):
            self.snap(text,value);return
        self.digit_tracks=self.tracks(self.current,text) if self.digits else {}
        longest=max(self.digit_tracks.values(),default=1)
        duration=min(MAX_DIGIT_DURATION_MS,DIGIT_DURATION_MS+(longest-1)*12)
        self.animation.setDuration(duration if self.digits else 180)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear if self.digits else QEasingCurve.Type.OutCubic)
        self.target=text;self.target_value=value;self.direction=1 if value>=self.value else -1;self.progress=0.;play_animation(self.animation)
    @staticmethod
    def tracks(before,after):
        pattern=r'([0-9]+(?:,[0-9]{3})*)(\.[0-9]+)?(.*)'
        old=re.fullmatch(pattern,before)
        new=re.fullmatch(pattern,after)
        if not old or not new or old[3]!=new[3] or len(old[2] or '')!=len(new[2] or ''):
            return {}
        def integer(match):
            return int((match[1]+(match[2] or '')).replace('.','').replace(',',''))
        first,last=integer(old),integer(new)
        layout=max((before,after),key=len)
        amount=layout[:len(layout)-len(new[3])]
        tracks={}
        place=1
        for index,char in enumerate(reversed(amount),start=len(new[3])):
            if not char.isdigit():continue
            count=abs(last//place-first//place)
            if count%10==0:count=0
            if count>10:
                # Keep the correct landing digit and enough visible travel.
                remainder=count%10
                count=remainder+10 if remainder<=3 else remainder
            if count>1:tracks[index]=count
            place*=10
        return tracks

    def snap(self,text=None,value=None):
        self.animation.stop()
        if text is None:text,value=self.pending or (self.target,self.target_value)
        self.current=self.target=str(text);self.value=self.target_value=value;self.pending=None;self.digit_tracks={};self.progress=1.;self.redraw()
    def redraw(self):
        if self._paint_rect is None:self.widget.update()
        else:self.widget.update(self._paint_rect.toAlignedRect())
    def advance(self,value):
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
            progress=self.progress if running else 1.
            # The sine easing's speed is continuous across digit boundaries.
            speed=2.*math.sqrt(max(0.,progress*(1.-progress)))
            softness=min(1.25,distance*.09)*speed
            opacity=p.opacity()
            tracks=self.digit_tracks if running and fm.horizontalAdvance(self.current)<=rect.width() and fm.horizontalAdvance(target)<=rect.width() else {}
            for index,((a,b,slot),old_slot) in enumerate(zip(self._slots,self._old_slots)):
                right=old_slot.right()+(slot.right()-old_slot.right())*(self.progress if running else 1.)
                aw=old_slot.width() if a else 0.;bw=slot.width() if b else 0.
                before=QRectF(right-aw,rect.y(),aw,rect.height())
                after=QRectF(right-bw,rect.y(),bw,rect.height())
                flags=Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter
                count=tracks.get(index,1)
                if a==b and count==1:
                    p.drawText(after,flags,b)
                    continue
                p.save()
                p.setClipRect(digit_clip,Qt.ClipOperation.IntersectClip)
                phase=progress*count
                step=min(count-1,int(phase))
                fraction=phase-step
                if count>1:
                    start=int(a or '0')
                    if step:
                        a=str((start+step*self.direction)%10)
                        width=fm.horizontalAdvance(a)
                        before=QRectF(right-width,rect.y(),width,rect.height())
                    if step+1<count:
                        b=str((start+(step+1)*self.direction)%10)
                        width=fm.horizontalAdvance(b)
                        after=QRectF(right-width,rect.y(),width,rect.height())
                offset=fraction*distance*self.direction
                for text,box,shift,alpha in (
                    (a,before,-offset if a.isdigit() else 0.,1.-fraction),
                    (b,after,self.direction*distance-offset if b.isdigit() else 0.,fraction),
                ):
                    if not text:continue
                    if text.isdigit():
                        # Glyphs remain readable while the clip hides their outer edges.
                        alpha=.55+.45*alpha
                    elif alpha<=0.:continue
                    box.translate(0,shift)
                    if text.isdigit() and softness>.08:
                        # Two faint samples soften only the glyph in motion.
                        p.setOpacity(opacity*alpha*.22*speed)
                        p.drawText(box.translated(0,-softness),flags,text)
                        p.drawText(box.translated(0,softness),flags,text)
                        alpha*=1.-.18*speed
                    p.setOpacity(opacity*alpha)
                    p.drawText(box,flags,text)
                p.restore()
        p.restore()
    def width(self,font,text=None):
        fm,digit=self.metrics(font);text=self.target if text is None else text
        return fm.horizontalAdvance(text)
