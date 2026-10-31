"""Compact activity rings with legible icons attached to their moving heads."""
from settings_controls import play_animation
from theme_registry import color as theme_color
import math
import bisect
from functools import lru_cache
from PySide6.QtCore import Qt,QRectF,QPointF,QSize,Signal,QEvent,QTimer,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QPainter,QPen,QColor,QPolygonF,QFontMetrics
from PySide6.QtWidgets import QWidget,QToolTip
from compact_bubble import font,INK,MUTED,PURPLE,GREEN
from ring_metrics import dashboard_metrics

HEIGHT=102
TILT=0
AXIS_X=1
AXIS_Y=1
ARC_START=-110
ARC_SWEEP=220
CENTER_Y=52

@lru_cache(maxsize=1)
def ellipse_lengths():
    start=math.radians(ARC_START)
    total=[0.0];previous=(AXIS_X*math.sin(start),-AXIS_Y*math.cos(start))
    for index in range(1,721):
        a=math.radians(ARC_START+index*ARC_SWEEP/720);point=(AXIS_X*math.sin(a),-AXIS_Y*math.cos(a))
        total.append(total[-1]+math.hypot(point[0]-previous[0],point[1]-previous[1]));previous=point
    return total

def progress_angle(progress):
    """Equal progress means equal arc length, including on a rotated ellipse."""
    progress=max(0,min(1,progress));lengths=ellipse_lengths();target=progress*lengths[-1]
    index=min(720,max(1,bisect.bisect_left(lengths,target)))
    return (index-1+(target-lengths[index-1])/(lengths[index]-lengths[index-1]))*ARC_SWEEP/720

def ellipse_point(radius,progress,cx=0,cy=0):
    angle=math.radians(ARC_START+progress_angle(progress));tilt=math.radians(TILT)
    x=radius*AXIS_X*math.sin(angle);y=-radius*AXIS_Y*math.cos(angle)
    return QPointF(cx+x*math.cos(tilt)-y*math.sin(tilt),cy+x*math.sin(tilt)+y*math.cos(tilt))

def ring_geometry(count):
    """Radii, stroke, badge diameter in logical pixels at the actual pet size."""
    count=max(1,min(6,count))
    if count<=3:return [38-14*i for i in range(count)],12,16
    if count==4:return [38,27,16,5],9,16
    if count==5:return [36,28,20,12,4],6,6
    return [36,30,24,18,12,6],4.5,4.5

@lru_cache(maxsize=128)
def _metric_ink(value,background,ink):
    from theme_registry import contrast,mix
    for _ in range(24):
        if contrast(value,background)>=3:break
        value=mix(value,ink,.08)
    return value

def metric_color(metric,index=0):
    from theme_registry import palette
    if metric.get('low'):value=theme_color('#98566d')
    elif metric['kind']=='time':value=theme_color('#587586')
    elif metric['kind']=='tokens':value=theme_color('#936a83')
    else:value=theme_color('#577c78' if metric.get('label')=='一周' else '#76618f')
    p=palette()
    return QColor(_metric_ink(value,p['panel'],p['ink']))

def metric_name(metric):
    if metric['kind']=='time':return '距重置'
    if metric['kind']=='tokens':return '今日Token'
    return {'5小时':'5h剩余','一周':'周剩余','额度':'额度'}.get(metric['label'],metric['label']+'剩余')

def draw_metric_icon(p,point,kind,badge,color=None):
    p.save();p.translate(point);p.scale(badge/13*1.22,badge/13*1.22)
    ink=QColor(theme_color(color or '#493b5b'));p.setPen(QPen(ink,1.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.setBrush(Qt.BrushStyle.NoBrush)
    if kind=='clock':
        p.drawEllipse(QRectF(-3.6,-3.6,7.2,7.2));p.drawLine(QPointF(0,-2.1),QPointF(0,0));p.drawLine(QPointF(0,0),QPointF(2,1))
    elif kind=='bolt':
        p.setBrush(theme_color(ink));p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(.8,-4.3),QPointF(-3.2,.5),QPointF(-.6,.5),QPointF(-1,4.3),QPointF(3.2,-.6),QPointF(.5,-.6)]))
    elif kind=='tokens':
        p.drawEllipse(QRectF(-4,-4,8,8));p.setFont(font(7,True))
        p.drawText(QRectF(-4,-4.8,8,9),Qt.AlignmentFlag.AlignCenter,'T')
    else:
        p.drawRoundedRect(QRectF(-3.7,-3,7.4,6.7),.7,.7);p.drawLine(QPointF(-3.5,-.8),QPointF(3.5,-.8))
        p.drawLine(QPointF(-1.8,-4.1),QPointF(-1.8,-2));p.drawLine(QPointF(1.8,-4.1),QPointF(1.8,-2))
        p.setFont(font(6,True));p.drawText(QRectF(-3.5,-.8,7,4.7),Qt.AlignmentFlag.AlignCenter,'7')
    p.restore()

class QuotaRings(QWidget):
    expand=Signal()
    metricHovered=Signal(int)
    def __init__(self,windows,caption='',parent=None,token_snapshot=None,progress_cache=None,metrics=None):
        super().__init__(parent);self.setFixedHeight(HEIGHT);self.setMinimumWidth(106);self.setMouseTracking(True)
        self.windows=sorted([dict(w) for w in windows],key=lambda w:0 if w.get('name')=='5小时' else 1 if w.get('name')=='一周' else 2)
        self.caption=caption;self.tokens=token_snapshot;self.demo=metrics is not None
        self.metrics=metrics if self.demo else dashboard_metrics(self.windows,token_snapshot)
        self.cache=progress_cache if progress_cache is not None else {};self.values={};self.starts={};self.targets={};self.active=None;self._badge_cache=None
        for metric in self.metrics:
            key=metric['id'];target=metric['progress'] if metric['progress'] is not None else 0
            self.targets[key]=target;self.starts[key]=self.cache.get(key,target) if metric['progress'] is not None else target;self.values[key]=self.starts[key]
        self.animation=QVariantAnimation(self);self.animation.setDuration(420);self.animation.setStartValue(0.0);self.animation.setEndValue(1.0);self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.animate)
        if any(abs(self.starts[k]-v)>.0005 for k,v in self.targets.items()):play_animation(self.animation)
        else:self.animate(1.0)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.update_time)
        self.setToolTip('\n\n'.join(m['description'] for m in self.metrics)+'\n'+caption+'\n点击展开全部信息')
        self.setAccessibleName('额度、重置倒计时与今日 Token 活动环');self.setAccessibleDescription(self.toolTip());self.setCursor(Qt.CursorShape.PointingHandCursor)
    def sizeHint(self):return QSize(121,HEIGHT)
    def begin_reveal(self):
        from settings_controls import motion_enabled
        self.animation.stop();self.starts={k:0. for k in self.targets};self.animate(0. if motion_enabled() else 1.)
    def start_reveal(self):
        if self.isVisible() and any(abs(self.values[k]-v)>.0005 for k,v in self.targets.items()):play_animation(self.animation)
    def animate(self,fraction):
        for key,target in self.targets.items():self.values[key]=self.starts[key]+(target-self.starts[key])*fraction;self.cache[key]=self.values[key]
        self.update()
    def update_time(self):
        if self.demo:return
        fresh=next(m for m in dashboard_metrics(self.windows,self.tokens) if m['kind']=='time')
        for i,metric in enumerate(self.metrics):
            if metric['kind']=='time':
                self.metrics[i]=fresh;self.values[fresh['id']]=fresh['progress'] or 0;self.cache[fresh['id']]=self.values[fresh['id']];self.update();break
    def showEvent(self,event):
        super().showEvent(event)
        if any(abs(self.values[k]-v)>.0005 for k,v in self.targets.items()):
            self.starts=dict(self.values);play_animation(self.animation)
        if not self.demo:self.timer.start()
    def hideEvent(self,event):
        self.animation.stop();self.timer.stop();super().hideEvent(event)
    def head_point(self,index,progress=None):
        radii,_,_=ring_geometry(len(self.metrics));metric=self.metrics[index]
        progress=self.values[metric['id']] if progress is None else progress
        return ellipse_point(radii[index],progress,self.width()/2,CENTER_Y)
    def badge_points(self):
        """Keep enlarged badges clear of each other and the caption opening.

        The true endpoints stay on the arcs. Only crowded badges move a few
        pixels, with a short leader to their endpoint; geometry is cached.
        """
        anchors=[self.head_point(i) for i in range(len(self.metrics))]
        key=(self.width(),tuple((round(p.x(),2),round(p.y(),2)) for p in anchors))
        if self._badge_cache and self._badge_cache[0]==key:return self._badge_cache[1]
        badge=ring_geometry(len(self.metrics))[2];half=badge/2;points=[]
        caption=QRectF(self.width()/2-30,CENTER_Y+8,60,39)
        for anchor in anchors:
            candidates=[]
            for dx,dy in badge_offsets():
                point=QPointF(anchor.x()+dx,anchor.y()+dy)
                if not (half+1<=point.x()<=self.width()-half-1 and half+1<=point.y()<=HEIGHT-half-1):continue
                rect=QRectF(point.x()-half,point.y()-half,badge,badge)
                overlap=sum(max(0,badge+1-math.hypot(point.x()-q.x(),point.y()-q.y()))**2 for q in points)
                intrusion=rect.intersected(caption)
                score=dx*dx+dy*dy+overlap*200+intrusion.width()*intrusion.height()*200
                candidates.append((score,point))
                if not overlap and intrusion.isEmpty():break
            points.append(min(candidates,key=lambda pair:pair[0])[1] if candidates else anchor)
        self._badge_cache=(key,points);return points
    def set_active(self,index):
        if index==self.active:return
        self.active=index;self.metricHovered.emit(-1 if index is None else index);self.update()
    def nearest(self,point):
        radii,stroke,badge=ring_geometry(len(self.metrics));heads=self.badge_points()
        for i,head in enumerate(heads):
            if math.hypot(point.x()-head.x(),point.y()-head.y())<=badge/2+2:return i
        angle=math.radians(-TILT);x=point.x()-self.width()/2;y=point.y()-CENTER_Y
        x,y=(x*math.cos(angle)-y*math.sin(angle))/AXIS_X,(x*math.sin(angle)+y*math.cos(angle))/AXIS_Y
        bearing=math.degrees(math.atan2(x,-y))
        if not ARC_START<=bearing<=ARC_START+ARC_SWEEP:return None
        distance=math.hypot(x,y)
        return next((i for i,r in enumerate(radii) if abs(distance-r)<stroke/2+2),None)
    def mouseMoveEvent(self,event):
        active=self.nearest(event.position())
        self.set_active(active)
        super().mouseMoveEvent(event)
    def leaveEvent(self,event):self.set_active(None);super().leaveEvent(event)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.expand.emit()
    def event(self,event):
        if event.type()==QEvent.Type.ToolTip:
            index=self.nearest(event.pos())
            if index is not None:
                metric=self.metrics[index];extra='\n'+self.caption if metric['kind']=='quota' else ''
                QToolTip.showText(event.globalPos(),metric['description']+extra+'\n点击展开全部信息',self);return True
        return super().event(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#f5f2f7')));p.drawRoundedRect(QRectF(self.rect()),11,11)
        radii,stroke,badge=ring_geometry(len(self.metrics));cx=self.width()/2;cy=CENTER_Y
        for index,metric in enumerate(self.metrics):
            radius=radii[index]
            # Continuous, substantial tracks with a quiet tinted remainder.
            # The lower opening holds the text; three 12px bands keep 2px gaps.
            color=metric_color(metric,index);track=QColor(theme_color(color));track.setAlpha(35)
            p.setPen(QPen(track,stroke,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.setBrush(Qt.BrushStyle.NoBrush)
            p.save();p.translate(cx,cy);p.rotate(TILT)
            p.drawArc(QRectF(-radius*AXIS_X,-radius*AXIS_Y,radius*2*AXIS_X,radius*2*AXIS_Y),round((90-ARC_START)*16),-round(ARC_SWEEP*16));p.restore()
            progress=self.values[metric['id']]
            if metric['progress'] is not None and progress>0:
                p.setPen(QPen(metric_color(metric,index),stroke,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
                p.save();p.translate(cx,cy);p.rotate(TILT)
                p.drawArc(QRectF(-radius*AXIS_X,-radius*AXIS_Y,radius*2*AXIS_X,radius*2*AXIS_Y),round((90-ARC_START)*16),-round(progress_angle(progress)*16));p.restore()
        for index,(metric,point) in enumerate(zip(self.metrics,self.badge_points())):
            anchor=self.head_point(index);color=metric_color(metric,index)
            if math.hypot(point.x()-anchor.x(),point.y()-anchor.y())>2:
                p.setPen(QPen(color,1.2));p.drawLine(anchor,point)
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(theme_color(color));p.drawEllipse(anchor,2,2)
            p.setPen(QPen(INK if self.active==index else color,1.6 if self.active==index else 1.25));p.setBrush(QColor(theme_color('#fffdff')));p.drawEllipse(point,badge/2,badge/2)
            draw_metric_icon(p,point,metric['icon'],badge)
        selected=self.metrics[self.active if self.active is not None else 0]
        label=metric_name(selected)
        value=selected['display']
        quotas=[m for m in self.metrics if m['kind']=='quota']
        if self.active is None and len(quotas)>1:
            label='额度剩余'
            value=' / '.join(m['display'] for m in quotas)
        # Nest the caption in the bottom opening, just below the inner endcaps.
        p.setFont(font(11,True));p.setPen(theme_color(MUTED));p.drawText(QRectF(2,CENTER_Y+8,self.width()-4,15),Qt.AlignmentFlag.AlignCenter,label)
        value_font=font(14,True);p.setFont(value_font)
        if p.fontMetrics().horizontalAdvance(value)>self.width()-8:p.setFont(font(12,True))
        p.setPen(theme_color(INK));p.drawText(QRectF(2,CENTER_Y+22,self.width()-4,21),Qt.AlignmentFlag.AlignCenter,value)

@lru_cache(maxsize=1)
def badge_offsets():
    return sorted(((x,y) for x in range(-20,21,2) for y in range(-20,21,2)),key=lambda v:(v[0]**2+v[1]**2,abs(v[0]),v[1]))

class RingLegend(QWidget):
    HEIGHT=20
    def __init__(self,rings,parent=None):
        super().__init__(parent);self.rings=rings;self.active=None;self.hits=[]
        self.setFixedHeight(self.HEIGHT);self.setMouseTracking(True);self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('圆环图例：'+'；'.join(metric_name(m) for m in rings.metrics))
        rings.metricHovered.connect(self._highlight)
    def _highlight(self,index):
        self.active=None if index<0 else index;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size=11 if len(self.rings.metrics)>3 and self.width()<280 else 12
        p.setFont(font(size,True));fm=QFontMetrics(p.font())
        widths=[20+fm.horizontalAdvance(metric_name(m)) for m in self.rings.metrics]
        available=max(1,self.width()-max(0,len(widths)-1)*2)
        if sum(widths)>available:widths=[w*available/sum(widths) for w in widths]
        gap=max(1,(self.width()-sum(widths))/max(1,len(widths)-1));x=max(0,(self.width()-sum(widths)-gap*(len(widths)-1))/2);self.hits=[]
        for i,(metric,width) in enumerate(zip(self.rings.metrics,widths)):
            rect=QRectF(x,0,width,self.height());self.hits.append(rect)
            if self.active==i:p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#ece6f2')));p.drawRoundedRect(rect,5,5)
            point=QPointF(x+8,10);color=metric_color(metric,i)
            p.setPen(QPen(color,1));p.setBrush(QColor(theme_color('#fffdff')));p.drawEllipse(point,8,8);draw_metric_icon(p,point,metric['icon'],16)
            p.setFont(font(size,True));p.setPen(theme_color(INK));p.drawText(QRectF(x+17,0,width-17,self.height()),Qt.AlignmentFlag.AlignVCenter,fm.elidedText(metric_name(metric),Qt.TextElideMode.ElideRight,max(1,round(width-17))));x+=width+gap
    def mouseMoveEvent(self,event):
        self.rings.set_active(next((i for i,rect in enumerate(self.hits) if rect.contains(event.position())),None));super().mouseMoveEvent(event)
    def leaveEvent(self,event):self.rings.set_active(None);super().leaveEvent(event)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.rings.expand.emit()
