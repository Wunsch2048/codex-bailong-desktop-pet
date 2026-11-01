"""Directly labelled quota bars, independent reset times and daily token total."""
from settings_controls import play_animation
from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
import math,time
from PySide6.QtCore import Qt,QRectF,QSize,QPoint,QPointF,Signal,QTimer,QVariantAnimation,QEasingCurve,QAbstractAnimation
from PySide6.QtGui import QPainter,QPen,QColor,QFontMetrics,QPixmap
from PySide6.QtWidgets import QWidget,QToolButton
from compact_bubble import font,INK,MUTED
from quota_summary_data import quota_items,today_tokens
from reset_watch import local_time
from ui_theme import QUOTA_WEEK,QUOTA_FIVE,QUOTA_LOW

HEIGHT=102

def quota_color(item):
    from theme_registry import week_color
    if item.get('remaining') is not None:
        return QColor(theme_color(week_color(item['remaining'])))
    if item['name']=='一周':
        remaining=item.get('remaining')
        if remaining is None:return QColor(theme_color('#9b93a4'))
        # Colour follows actual quota, never the 0-to-value entry animation.
        stops=((0,'#ac6e85'),(15,'#ac6e85'),(35,'#b18e62'),(65,'#9b86b0'),(100,QUOTA_WEEK))
        for (start,left),(end,right) in zip(stops,stops[1:]):
            if remaining<=end:
                fraction=max(0.,min(1.,(remaining-start)/(end-start)))
                a,b=QColor(theme_color(left)),QColor(theme_color(right))
                return QColor(*(round(x+(y-x)*fraction) for x,y in zip(a.getRgb()[:3],b.getRgb()[:3])))
        return QColor(theme_color(QUOTA_WEEK))
    return QColor(theme_color(QUOTA_LOW if item['low'] else QUOTA_WEEK if item['name']=='一周' else QUOTA_FIVE))

class QuotaSummary(QWidget):
    expand=Signal()
    anomalyRequested=Signal()
    resetDue=Signal(float)
    def __init__(self,windows,caption='',parent=None,progress_cache=None,clock=None,anomaly=None,expanded=False):
        super().__init__(parent);self.setObjectName('quota_summary');self.setFixedHeight(105 if expanded else HEIGHT);self.setMinimumWidth(106)
        self.expanded=expanded
        self.windows=[dict(w) for w in windows];self.caption=caption;self.clock=clock or time.time
        self.items=quota_items(self.windows,self.clock());self.cache=progress_cache if progress_cache is not None else {}
        self.anomaly=anomaly;self.week_index=next((i for i,w in enumerate(self.items) if w['name']=='一周'),None)
        self.alert_height=0
        self.alert_badge=QToolButton(self);self.alert_badge.setObjectName('week_quota_alert')
        badge_text=f"{anomaly.get('change',0):+.0f}%" if anomaly else ''
        self.alert_badge.setText(badge_text);self.alert_badge.setFont(font(10 if expanded else 11,not expanded))
        self.alert_badge.setFixedSize(max(32 if expanded else 38,QFontMetrics(self.alert_badge.font()).horizontalAdvance(badge_text)+(8 if expanded else 10)),15 if expanded else 18)
        self.alert_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        increase=bool(anomaly and anomaly.get('change',0)>0)
        self.alert_badge.setAccessibleName('周额度推测总量'+('上涨' if increase else '下降')+'提醒，查看额度对比')
        self.refresh_theme_colors()
        self.alert_badge.clicked.connect(self.anomalyRequested.emit)
        self.alert_badge.setVisible(bool(anomaly and self.week_index is not None))
        if anomaly:self.alert_badge.setAccessibleDescription(anomaly['description'])
        self.active=None;self.pressed=False;self.values={};self.starts={};self.targets={};self._due_sent=set()
        self._static_key=None;self._revision=0;self.layer_builds=0
        self.setMouseTracking(True);self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.animation=QVariantAnimation(self);self.animation.setDuration(420);self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.animation.valueChanged.connect(self.animate)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self._refresh_time)
        for item in self.items:
            key=item['id'];target=item['progress'] or 0.
            self.targets[key]=target;self.starts[key]=self.cache.get(key,target) if item['progress'] is not None else 0.
            self.values[key]=self.starts[key]
        self._accessible();self.animate(0.)
    def refresh_theme_colors(self):
        from theme_registry import palette,mix
        p=palette();up=bool(self.anomaly and self.anomaly.get('change',0)>0)
        bg=p['successBg' if up else 'dangerBg'];fg=p['successBadge'] if up else p.get('dangerBadge',p['danger'])
        hover=mix(bg,p['ink'],.07);pressed=mix(bg,p['ink'],.14)
        self.alert_badge.setStyleSheet('QToolButton{background:'+bg+';color:'+fg+';border:0;border-radius:'+('4' if self.expanded else '7')+'px;padding:0;}QToolButton:hover{background:'+hover+';}QToolButton:pressed{background:'+pressed+';}')
    def sizeHint(self):return QSize(121,(105 if self.expanded else HEIGHT)+self.alert_height)
    def _accessible(self):
        text='\n'.join(i['description'] for i in self.items)+'\n'+self.caption
        if self.anomaly and self.week_index is not None:text+='\n'+self.anomaly['description']
        self.setAccessibleName('账户剩余额度；点击查看额度详情');self.setAccessibleDescription(text)
    def row_rect(self,index):
        shift=self.row_shift(index)
        return QRectF(3,3+shift,self.width()-6,96) if len(self.items)==1 else QRectF(3,3+index*50+shift,self.width()-6,48)
    def row_shift(self,index):return 0
    def value_rect(self,index):
        single=len(self.items)==1;y=(0 if single else index*50)+self.row_shift(index)
        if self.expanded:return QRectF(9,22,self.width()-18,35) if single else QRectF(self.width()-63,index*49+7,54,20)
        return QRectF(10,26+y,self.width()-20,34) if single else QRectF(10,20+y,48,22)
    def alert_rect(self):
        if self.expanded:
            if len(self.items)>1:return QRectF(9,(self.week_index or 0)*49+34,self.alert_badge.width(),15)
            return QRectF(self.width()-self.alert_badge.width()-9,8,self.alert_badge.width(),15)
        return QRectF(self.width()-self.alert_badge.width()-7,(0 if len(self.items)==1 else (self.week_index or 0)*50-2)+6,self.alert_badge.width(),18)
    def resizeEvent(self,event):
        self.alert_badge.move(self.alert_rect().topLeft().toPoint())
        super().resizeEvent(event)
    def _schedule(self):
        if not self.isVisible():return
        now=self.clock();future=[i['reset_at']-now for i in self.items if i['reset_at'] and i['reset_at']>now]
        # Minute countdowns need one wake on each next minute/reset boundary.
        seconds=min([60-now%60]+future)
        self.timer.start(max(30,math.ceil(seconds*1000)))
    def _refresh_time(self,request=True):
        fresh=quota_items(self.windows,self.clock())
        changed=fresh!=self.items;self.items=fresh
        for item in fresh:
            if item['expired']:
                self.targets[item['id']]=self.starts[item['id']]=self.values[item['id']]=0.
                self.cache[item['id']]=0.
        if changed:self._revision+=1;self._accessible();self.update()
        # One query covers all newly expired windows, including a second
        # deadline reached while the first window still has stale data.
        pending={i['reset_at'] for i in fresh if i['expired']}-self._due_sent
        if request and pending:
            self._due_sent.update(pending);self.resetDue.emit(max(pending))
        self._schedule()
    def animate(self,fraction):
        for key,target in self.targets.items():self.values[key]=self.starts[key]+(target-self.starts[key])*fraction;self.cache[key]=self.values[key]
        region=self.reveal_region()
        if self.visibleRegion().intersects(region):self.update(region)
    def begin_reveal(self):
        from settings_controls import motion_enabled
        self.ensure_static();self.animation.stop();self.starts={k:0. for k in self.targets};self.animate(0. if motion_enabled() else 1.)
    def start_reveal(self):
        if self.animation.state()!=QAbstractAnimation.State.Running and self.isVisible() and any(abs(self.values[k]-v)>.0005 for k,v in self.targets.items()):play_animation(self.animation)
    def showEvent(self,event):
        super().showEvent(event)
        # Refresh synchronously before the first paint after being hidden.
        # Queue the query: emitting here could re-enter the parent's redraw.
        self._refresh_time(request=False)
        transition=getattr(self.window(),'size_transition',None)
        if not transition or not (transition.running or transition.preparing):self.start_reveal()
        if any(i['expired'] for i in self.items):QTimer.singleShot(0,self,self._refresh_time)
    def hideEvent(self,event):
        self.timer.stop();self.animation.stop();self.active=None;self.pressed=False;super().hideEvent(event)
    def mouseMoveEvent(self,event):
        index=next((i for i in range(len(self.items)) if self.row_rect(i).contains(event.position())),None)
        if index!=self.active:self.active=index;self.update()
        super().mouseMoveEvent(event)
    def leaveEvent(self,event):self.active=None;self.update();super().leaveEvent(event)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.pressed=True;self.update();event.accept()
    def mouseReleaseEvent(self,event):
        clicked=self.pressed and event.button()==Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint())
        self.pressed=False;self.update()
        if clicked:self.expand.emit()
    def _track(self,p,rect,item):
        color=quota_color(item);track=QColor(theme_color(color));track.setAlpha(33)
        if self.expanded:
            from theme_registry import palette
            track=QColor(palette()['track'])
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(theme_color(track));p.drawRoundedRect(rect,rect.height()/2,rect.height()/2)
        if item['progress'] is None:
            p.setPen(QPen(QColor(theme_color('#8e819c')),1.3));p.drawLine(rect.center().toPoint()+QPoint(-3,0),rect.center().toPoint()+QPoint(3,0))
    def track_rect(self,index):
        if self.expanded:return QRectF(9,63,self.width()-18,5) if len(self.items)==1 else QRectF(9,index*49+30,self.width()-18,3)
        return QRectF(10,(65 if len(self.items)==1 else index*50+42)+self.row_shift(index),self.width()-20,6)
    def reveal_region(self):
        rect=QRectF()
        for i in range(len(self.items)):rect=rect.united(self.track_rect(i))
        return rect.adjusted(-1,-1,1,1).toAlignedRect()
    def ensure_static(self):
        ratio=self.devicePixelRatioF();key=(self.width(),self.height(),ratio,self._revision,self.active,self.pressed,self.expanded)
        if self._static_key==key:return
        image=QPixmap(max(1,int(self.width()*ratio+.5)),max(1,int(self.height()*ratio+.5)));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
        p=QPainter(image);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme_color('#f5f2f7')));p.drawRoundedRect(QRectF(self.rect()),11 if self.expanded else 10,11 if self.expanded else 10)
        single=len(self.items)==1
        for index,item in enumerate(self.items):
            rect=self.row_rect(index)
            if self.active==index:
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#e6dcec' if self.pressed else '#ede7f2')));p.drawRoundedRect(rect,7,7)
            y=(0 if single else index*50)+self.row_shift(index)
            if not single:
                self._draw_dual_row(p,index,item,y);continue
            p.setFont(font(11,not self.expanded));p.setPen(theme_color(MUTED))
            label='周' if not single and index==self.week_index and self.anomaly else item['label']
            p.drawText(QRectF(9 if self.expanded else 10,y+8 if self.expanded else y+7,self.width()-(18 if self.expanded else 20),14 if self.expanded else 18),Qt.AlignmentFlag.AlignVCenter,label)
            value=item['display'];color=INK if self.expanded else quota_color(item) if item['remaining'] is not None else MUTED
            p.setPen(theme_color(color));p.setFont(font(29 if self.expanded else 28 if single else 18,True))
            value_rect=self.value_rect(index)
            # Very long custom decimal percentages remain legible and contained.
            if QFontMetrics(p.font()).horizontalAdvance(value)>value_rect.width():p.setFont(font(22 if single else 14,True))
            if self.expanded and value.endswith('%'):
                number=value[:-1];metrics=QFontMetrics(p.font());baseline=value_rect.y()+(value_rect.height()+metrics.ascent()-metrics.descent())/2
                p.drawText(QPointF(value_rect.x(),baseline),number);x=value_rect.x()+metrics.horizontalAdvance(number)+2
                p.setFont(font(15));p.drawText(QPointF(x,baseline),'%')
            else:p.drawText(value_rect,Qt.AlignmentFlag.AlignVCenter|(Qt.AlignmentFlag.AlignLeft if single else Qt.AlignmentFlag.AlignRight),value)
            self._track(p,self.track_rect(index),item)
            text=item['reset_text']
            if self.active==index and item['reset_at'] and not item['expired']:text=local_time(item['reset_at'])+' 重置'
            p.setPen(theme_color(QColor(theme_color('#98566d')) if item['expired'] else MUTED));p.setFont(font(10 if single else 9))
            text=QFontMetrics(p.font()).elidedText(text,Qt.TextElideMode.ElideRight,self.width()-20)
            p.drawText(QRectF(9 if self.expanded else 10,74 if self.expanded else 80+y if single else y+36,self.width()-(18 if self.expanded else 20),14 if self.expanded else 15),Qt.AlignmentFlag.AlignVCenter,text)
        p.end();self._static=image;self._static_key=key;self.layer_builds+=1
    def _draw_dual_row(self,p,index,item,y):
        if self.expanded:
            y=index*49
            p.setFont(font(11));p.setPen(theme_color(MUTED))
            p.drawText(QRectF(9,y+7,self.width()-78,20),Qt.AlignmentFlag.AlignVCenter,item['label'])
            p.setFont(font(18,True));p.setPen(theme_color(INK))
            p.drawText(self.value_rect(index),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,item['display'])
            self._track(p,self.track_rect(index),item)
            text=local_time(item['reset_at']) if self.active==index and item['reset_at'] and not item['expired'] else item['reset_text']
            x=9+self.alert_badge.width()+4 if index==self.week_index and self.anomaly else 9
            p.setFont(font(10));p.setPen(theme_color(MUTED))
            text=QFontMetrics(p.font()).elidedText(text,Qt.TextElideMode.ElideRight,self.width()-x-10)
            p.drawText(QRectF(x,y+36,self.width()-x-9,12),Qt.AlignmentFlag.AlignVCenter,text)
            if index:
                from theme_registry import palette
                p.setPen(QColor(palette()['track']));p.drawLine(9,y+3,self.width()-9,y+3)
            return
        # Same 102px card: a heading/badge row, value/countdown row, then track.
        # The weekly change badge never competes with the remaining percentage.
        precise=self.active==index and item['reset_at'] and not item['expired']
        date,clock=local_time(item['reset_at']).split(' ',1) if precise else ('','')
        p.setFont(font(12,True));p.setPen(theme_color(MUTED))
        p.drawText(QRectF(10,y+3,self.width()-20,18),Qt.AlignmentFlag.AlignVCenter,date if precise else item['label'])
        value=item['display'];rect=self.value_rect(index)
        p.setFont(font(18,True))
        if QFontMetrics(p.font()).horizontalAdvance(value)>rect.width():p.setFont(font(14,True))
        p.setPen(theme_color(quota_color(item)) if item['remaining'] is not None else theme_color(MUTED))
        p.drawText(rect,Qt.AlignmentFlag.AlignVCenter,value)
        text=clock if precise else item['reset_text'].removesuffix('后重置')
        p.setFont(font(11));metrics=QFontMetrics(p.font());text=metrics.elidedText(text,Qt.TextElideMode.ElideRight,max(1,self.width()-64))
        tw=metrics.horizontalAdvance(text);tx=self.width()-10-tw
        p.setPen(QColor(theme_color('#98566d')) if item['expired'] else theme_color(MUTED))
        p.drawText(QRectF(tx,y+23,tw,18),Qt.AlignmentFlag.AlignVCenter,text)
        cx=tx-9;cy=y+32
        p.setPen(QPen(theme_color(MUTED),1.15,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(cx-4,cy-4,8,8),45*16,285*16)
        p.drawLine(round(cx+3),round(cy-4),round(cx+3),round(cy-1))
        self._track(p,self.track_rect(index),item)
    def paintEvent(self,event):
        self.ensure_static();p=QPainter(self);p.drawPixmap(0,0,self._static);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
        for index,item in enumerate(self.items):
            progress=self.values[item['id']]
            if item['progress'] is not None and progress>0:
                rect=self.track_rect(index);filled=QRectF(rect.x(),rect.y(),rect.width()*progress,rect.height());radius=min(filled.width()/2,filled.height()/2)
                p.setBrush(theme_color(quota_color(item)));p.drawRoundedRect(filled,radius,radius)

class TodayTokens(QWidget):
    activated=Signal()
    HEIGHT=20
    def __init__(self,snapshot,parent=None,selected=False):
        super().__init__(parent);self.setObjectName('today_tokens');self.setFixedHeight(self.HEIGHT);self.data=today_tokens(snapshot)
        self.hovered=False;self.pressed=False;self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.selected=None;self.set_selected(selected);self.setAccessibleDescription(self.data['description'])
    def set_selected(self,value):
        value=bool(value)
        if value==self.selected:return
        self.selected=value
        self.setAccessibleName('今日 Token '+self.data['display']+'；'+('当前显示今日24小时曲线' if value else '点击查看今日24小时曲线'))
        self.update()
    def enterEvent(self,event):self.hovered=True;self.update();super().enterEvent(event)
    def leaveEvent(self,event):self.hovered=False;self.update();super().leaveEvent(event)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.pressed=True;self.update();event.accept()
    def mouseReleaseEvent(self,event):
        clicked=self.pressed and event.button()==Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint())
        self.pressed=False;self.update()
        if clicked:self.activated.emit()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
        if getattr(self,'expanded',False) and getattr(self,'compact',False):
            from theme_registry import palette
            colors=palette();p.setBrush(QColor(colors['selected' if self.hovered or self.pressed else 'panel']));p.drawRoundedRect(QRectF(self.rect()),6,6)
            p.setFont(font(11));p.setPen(QColor(colors['muted']));p.drawText(QRectF(7,0,25,self.height()),Qt.AlignmentFlag.AlignVCenter,'今日')
            p.setFont(font(10));entry_width=QFontMetrics(p.font()).horizontalAdvance('›');entry_x=self.width()-7-entry_width
            p.drawText(QRectF(entry_x,0,entry_width,self.height()),Qt.AlignmentFlag.AlignVCenter,'›')
            p.setFont(font(11));p.setPen(QColor(colors['ink']));rect=QRectF(35,0,max(0,entry_x-38),self.height())
            value=self.data['display']+(' 部分' if self.data['partial'] else '')
            value=QFontMetrics(p.font()).elidedText(value,Qt.TextElideMode.ElideRight,round(rect.width()))
            p.drawText(rect,Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,value);return
        p.setBrush(QColor(theme_color('#e6dcec' if self.pressed else '#e8def0' if self.selected else '#eee7f3' if self.hovered else '#f5f2f7')));p.drawRoundedRect(QRectF(self.rect()),6,6)
        p.setPen(theme_color(MUTED));p.setFont(font(10));p.drawText(QRectF(8,0,69,self.height()),Qt.AlignmentFlag.AlignVCenter,'今日 Token')
        p.setFont(font(12,True));p.setPen(theme_color(INK))
        value=self.data['display']+(' 部分' if self.data['partial'] else '')
        if getattr(self,'compact',False):
            # Footer half-width: retain today amount and the 24h action, omit duplicate Token label.
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#e6dcec' if self.pressed else '#e8def0' if self.selected else '#eee7f3' if self.hovered else '#f5f2f7')));p.drawRoundedRect(QRectF(self.rect()),6,6)
            p.setFont(font(10));p.setPen(theme_color(MUTED));p.drawText(QRectF(6,0,22,self.height()),Qt.AlignmentFlag.AlignVCenter,'今日')
            entry='›' if getattr(self,'expanded',False) else '24h ›';entry_width=QFontMetrics(p.font()).horizontalAdvance(entry);entry_x=self.width()-6-entry_width
            p.drawText(QRectF(entry_x,0,entry_width,self.height()),Qt.AlignmentFlag.AlignVCenter,entry)
            p.setFont(font(12,True));p.setPen(theme_color(INK));rect=QRectF(32,0,max(0,entry_x-36),self.height())
            if QFontMetrics(p.font()).horizontalAdvance(value)>rect.width():p.setFont(font(10,True))
            value=QFontMetrics(p.font()).elidedText(value,Qt.TextElideMode.ElideRight,round(rect.width()))
            p.drawText(rect,Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,value);return
        p.drawText(QRectF(77,0,self.width()-128,self.height()),Qt.AlignmentFlag.AlignVCenter,value)
        p.setPen(theme_color(QColor(theme_color('#75618d')) if self.selected else MUTED));p.setFont(font(10,self.selected));p.drawText(QRectF(self.width()-45,0,37,self.height()),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,'24h ›')
