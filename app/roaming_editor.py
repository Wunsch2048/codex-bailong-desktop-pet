"""In-card roaming settings with a cached route diagram; no native popup."""
import math,random
from PySide6.QtCore import Qt,QRectF,QPointF,QTimer,QEvent,Signal
from PySide6.QtGui import QPainter,QPainterPath,QPen,QColor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QToolButton,QPushButton,QScrollArea,QApplication
from settings_controls import SlidingSegments,motion_enabled
from theme_runtime import set_theme_style
from theme_registry import color
from typography import FONT_CSS,ui_font
from ui_theme import hide_scrollbars
from roaming import LABELS,clean_zone,plan,center_rect

DESCRIPTIONS={'edge':'沿边缘活动，绕开中间区域','side':'在同一侧小范围活动，停留更久','zone':'拖动框内移动，拖动四角调整范围','window':'按前台窗口位置绕行，最大化时回到边缘'}

class RouteDiagram(QWidget):
    valueChanged=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumHeight(96);self.setMaximumHeight(122);self.setMinimumWidth(0)
        self.zone=clean_zone(None);self.mode='edge';self.area=(0,0,1600,900);self.points=[];self.frame=0.;self.drag_origin=None;self.drawing=None
        self.drag_kind=None;self.drag_zone=None;self.setMouseTracking(True)
        self.clock=QTimer(self);self.clock.setInterval(40);self.clock.timeout.connect(self.advance)
        self.setAccessibleName('走动路线示意，手动活动区模式可拖动框选')
    def value(self):return list(self.zone)
    def setValue(self,value):self.zone=clean_zone(value);self.update()
    def screen_rect(self):
        rect=QRectF(self.rect()).adjusted(7,7,-7,-7);ratio=self.area[2]/self.area[3]
        if rect.width()/max(1,rect.height())>ratio:rect.setWidth(rect.height()*ratio)
        else:rect.setHeight(rect.width()/ratio)
        rect.moveCenter(QRectF(self.rect()).center());return rect
    def normalized_point(self,point):
        rect=self.screen_rect();return QPointF(max(0,min(1,(point.x()-rect.left())/rect.width())),max(0,min(1,(point.y()-rect.top())/rect.height())))
    def configure(self,settings,pet):
        self.mode=settings.get('wander_mode','edge');screen=pet.screen() or QApplication.primaryScreen();area=screen.availableGeometry()
        w,h=area.width(),area.height();self.area=(0,0,w,h)
        footprint=getattr(getattr(pet,'roaming',None),'preview_footprint',(0,0,pet.width(),pet.height()))
        if settings.get('panel_detached') or not settings.get('bubble'):footprint=(0,0,pet.width(),pet.height())
        self.center_box=center_rect(self.area,footprint);self.reason=''
        self.preview_size=(footprint[2]-footprint[0],footprint[3]-footprint[1]);pos=(max(8,(w-pet.width())*.86),max(8,(h-pet.height())*.72))
        self.points=[pos];rng=random.Random(24)
        window=(w*.24,h*.17,w*.77,h*.74) if self.mode=='window' else None
        for _ in range(3):
            route=plan(pos,pos,self.area,footprint,settings,rng.uniform,window)
            if not route.points:self.reason=route.reason;break
            self.points.extend(route.points);pos=route.points[-1]
        self.frame=0;self.motion_policy_changed();self.update()
    def advance(self):self.frame=(self.frame+.015)%1;self.update()
    def motion_policy_changed(self):
        if self.isVisible() and motion_enabled() and len(self.points)>1:self.clock.start()
        else:self.clock.stop()
    def showEvent(self,event):super().showEvent(event);self.motion_policy_changed()
    def hideEvent(self,event):self.clock.stop();self.drag_origin=None;self.drawing=None;super().hideEvent(event)
    def event(self,event):
        if event.type() in (QEvent.Type.UngrabMouse,QEvent.Type.WindowDeactivate) and self.drag_origin is not None:self.drag_origin=None;self.drawing=None;self.update()
        return super().event(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);rect=self.screen_rect();w,h=self.area[2:]
        def point(q):return QPointF(rect.x()+q[0]/w*rect.width(),rect.y()+q[1]/h*rect.height())
        p.setPen(QPen(QColor(color('#e4dfea')),1));p.setBrush(QColor(color('#fcfafc')));p.drawRoundedRect(rect,8,8)
        if self.mode=='zone':
            z=self.drawing or self.zone;box=QRectF(point((z[0]*w,z[1]*h)),point((z[2]*w,z[3]*h)))
            fill=QColor(color('#8b78a6'));fill.setAlpha(35);p.setBrush(fill);p.setPen(QPen(QColor(color('#75618d')),1.4));p.drawRoundedRect(box,4,4)
            for corner in (box.topLeft(),box.topRight(),box.bottomLeft(),box.bottomRight()):p.drawEllipse(corner,2,2)
        elif self.mode=='window':
            box=QRectF(point((w*.24,h*.17)),point((w*.77,h*.74)));p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#e4dfea')));p.drawRoundedRect(box,5,5)
            p.setBrush(QColor(color('#f5f0f8')));p.drawRoundedRect(box.adjusted(2,9,-2,-2),3,3)
        else:
            box=getattr(self,'center_box',center_rect(self.area));p.setPen(Qt.PenStyle.NoPen);fill=QColor(color('#706879'));fill.setAlpha(16);p.setBrush(fill);p.drawRoundedRect(QRectF(point(box[:2]),point(box[2:])),5,5)
        if self.points:
            path=QPainterPath(point(self.points[0]))
            for q in self.points[1:]:path.lineTo(point(q))
            pen=QPen(QColor(color('#8b78a6')),1.4,Qt.PenStyle.DashLine);p.setPen(pen);p.setBrush(Qt.BrushStyle.NoBrush);p.drawPath(path)
            lengths=[math.dist(a,b) for a,b in zip(self.points,self.points[1:])];remaining=sum(lengths)*self.frame;current=self.points[0]
            for a,b,length in zip(self.points,self.points[1:],lengths):
                if remaining<=length:
                    f=remaining/max(1,length);current=(a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f);break
                remaining-=length
            dot=point(current);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#75618d')));p.drawEllipse(dot,4.2,4.2)
    def mousePressEvent(self,event):
        if self.mode=='zone' and event.button()==Qt.MouseButton.LeftButton and self.screen_rect().contains(event.position()):
            q=self.normalized_point(event.position());z=self.zone;rect=self.screen_rect();self.drag_origin=q;self.drag_zone=list(z)
            corners=[(z[0],z[1],z[2],z[3]),(z[2],z[1],z[0],z[3]),(z[0],z[3],z[2],z[1]),(z[2],z[3],z[0],z[1])]
            hit=next((c for c in corners if math.hypot((q.x()-c[0])*rect.width(),(q.y()-c[1])*rect.height())<=8),None)
            if hit:self.drag_kind='resize';self.drag_origin=QPointF(hit[2],hit[3])
            elif z[0]<=q.x()<=z[2] and z[1]<=q.y()<=z[3]:self.drag_kind='move';self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:self.drag_kind='draw'
            event.accept();return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.drag_origin is not None:
            q=self.normalized_point(event.position());a=self.drag_origin
            if self.drag_kind=='move':
                z=self.drag_zone;dx=max(-z[0],min(1-z[2],q.x()-a.x()));dy=max(-z[1],min(1-z[3],q.y()-a.y()))
                self.drawing=[z[0]+dx,z[1]+dy,z[2]+dx,z[3]+dy]
            else:self.drawing=[min(a.x(),q.x()),min(a.y(),q.y()),max(a.x(),q.x()),max(a.y(),q.y())]
            self.update();event.accept();return
        if self.mode=='zone':
            q=self.normalized_point(event.position());z=self.zone
            self.setCursor(Qt.CursorShape.OpenHandCursor if z[0]<q.x()<z[2] and z[1]<q.y()<z[3] else Qt.CursorShape.CrossCursor)
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.drag_origin is not None:
            if self.drawing and self.drawing[2]-self.drawing[0]>.05 and self.drawing[3]-self.drawing[1]>.05:self.zone=clean_zone(self.drawing);self.valueChanged.emit()
            self.drag_origin=None;self.drawing=None;self.drag_kind=None;self.drag_zone=None;self.unsetCursor();self.update();event.accept();return
        super().mouseReleaseEvent(event)

class RoamingEditor(QWidget):
    def __init__(self,settings,parent):
        super().__init__(parent);self.settings=settings;self.setObjectName('roamingEditor');self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        set_theme_style(self,'QWidget#roamingEditor{background:#f5f2f7;}QLabel{'+FONT_CSS+'font-size:12px;color:#706879;}QToolButton{'+FONT_CSS+'font-size:12px;color:#75618d;border:0;border-radius:6px;background:#e8dff0;padding:4px 8px;text-align:left;}QToolButton:hover{background:#ded2e7;}')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);outer=QVBoxLayout(self);outer.setContentsMargins(5,3,5,4);outer.setSpacing(7)
        back=QToolButton();back.setText('‹ 走动设置');back.setFixedHeight(26);back.clicked.connect(self.close_page);outer.addWidget(back)
        scroll=hide_scrollbars(QScrollArea());scroll.setWidgetResizable(True);set_theme_style(scroll,'QScrollArea{border:0;background:transparent;}')
        scroll.viewport().setObjectName('roamingViewport');scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True);set_theme_style(scroll.viewport(),'QWidget#roamingViewport{background:#f5f2f7;}')
        body=QWidget();body.setObjectName('roamingBody');body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True);set_theme_style(body,'QWidget#roamingBody{background:#f5f2f7;}')
        row=QVBoxLayout(body);row.setContentsMargins(2,0,2,0);row.setSpacing(7)
        self.mode=SlidingSegments([(LABELS[k],k) for k in ('edge','side','zone','window')]);row.addWidget(self.mode)
        diagram_row=QHBoxLayout();self.diagram=RouteDiagram();diagram_row.addWidget(self.diagram,1)
        from settings_presentation import SettingsResetButton
        self.reset_zone=SettingsResetButton();self.reset_zone.setFixedSize(26,26);self.reset_zone.setAccessibleName('重置活动区');self.reset_zone.setToolTip('重置');self.reset_zone.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(self.reset_zone,'QToolButton{font-size:18px;color:#75618d;background:#e8dff0;border:0;border-radius:13px;}QToolButton:hover{background:#ded2e7;}QToolButton:pressed{background:#d6c5ed;}')
        self.reset_zone.clicked.connect(self.reset_activity_zone);diagram_row.addWidget(self.reset_zone);row.addLayout(diagram_row);self.caption=QLabel();self.caption.setWordWrap(True);row.addWidget(self.caption)
        form=QFormLayout();form.setContentsMargins(0,0,0,0);form.setVerticalSpacing(7);row.addLayout(form)
        old=settings._building_index;settings._building_index=1
        settings.fields['wander_mode']=self.mode;settings.field_tabs['wander_mode']=1;settings.field_titles['wander_mode']='走动模式'
        self.side=SlidingSegments([('当前侧','auto'),('左侧','left'),('右侧','right')]);form.addRow('停留侧',self.side)
        settings.fields['wander_side']=self.side;settings.field_tabs['wander_side']=1;settings.field_titles['wander_side']='停留侧'
        settings.fields['wander_zone']=self.diagram;settings.field_tabs['wander_zone']=1;settings.field_titles['wander_zone']='活动区'
        settings.check(form,'wander_horizontal_only','仅水平移动');settings.number(form,'move_range','活动范围',.1,1,.1,factor=100,suffix='%');settings.number(form,'move_speed','基础速度',10,300,5,suffix=' px/s')
        settings._building_index=old
        self.horizontal_hint=QLabel('快速通过，不在中心停留');self.horizontal_hint.setWordWrap(True);row.addWidget(self.horizontal_hint);row.addStretch();scroll.setWidget(body);outer.addWidget(scroll,1)
        self.scroll=scroll;footer=QHBoxLayout();self.discard=QPushButton('放弃修改');self.discard.setAutoDefault(False);self.discard.clicked.connect(settings.reload);footer.addWidget(self.discard)
        self.save=QPushButton('保存并返回');self.save.setAutoDefault(False);self.save.setProperty('role','primary');self.save.clicked.connect(self.commit);footer.addWidget(self.save);outer.addLayout(footer)
        self.mode.currentIndexChanged.connect(lambda:self.edited('wander_mode'));self.side.currentIndexChanged.connect(lambda:self.edited('wander_side'));self.diagram.valueChanged.connect(lambda:self.edited('wander_zone'))
        for key in ('wander_horizontal_only','move_range','move_speed'):
            widget=settings.fields[key];signal=getattr(widget,'toggled',None) or widget.valueChanged;signal.connect(self.refresh)
        self.form=form;parent.installEventFilter(self);self.hide()
        settings.tabs.currentChanged.connect(lambda index:self.hide() if index!=1 else None)
    def edited(self,key):self.settings.edited(key);self.refresh()
    def reset_activity_zone(self):
        self.diagram.setValue(None);self.diagram.valueChanged.emit()
    def refresh(self,*unused):
        if not self.settings.draft:return
        values=self.settings.draft.values;mode=values.get('wander_mode','edge');self.form.setRowVisible(self.side,mode=='side');self.caption.setText(DESCRIPTIONS[mode]);self.horizontal_hint.setVisible(values.get('wander_horizontal_only',True));self.diagram.configure(values,self.settings.pet)
        self.reset_zone.setVisible(mode=='zone')
        if len(self.diagram.points)==1 and mode=='zone' and self.diagram.reason:
            self.caption.setText('请让活动区覆盖人物当前高度' if '高度' in self.diagram.reason else '活动区太小，请扩大框选范围')
    def open(self):
        from data_page_motion import PageFade
        parent=self.parentWidget();motion=getattr(self,'page_motion',None)
        if motion is None:self.page_motion=motion=PageFade(parent)
        frame=motion.current_frame() if motion.isVisible() else None
        motion.clear()
        if frame is None:frame=PageFade.snapshot(parent)
        self.setGeometry(parent.rect());self.refresh();self.scroll.verticalScrollBar().setValue(0);self.show();self.raise_();self.layout().activate();self.setFocus()
        motion.present(frame,PageFade.snapshot(self),self.geometry(),direction=1)
    def close_page(self):
        from data_page_motion import PageFade
        parent=self.parentWidget();motion=getattr(self,'page_motion',None)
        if motion is None:self.hide();return
        frame=motion.current_frame() if motion.isVisible() else PageFade.snapshot(self)
        motion.clear();self.hide()
        motion.present(frame,PageFade.snapshot(parent),parent.rect(),direction=-1)
    def commit(self):
        self.settings.apply()
        if not self.settings.draft.dirty:self.close_page()
        else:self.caption.setText(self.settings.status.text())
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Resize:self.setGeometry(obj.rect())
        elif event.type()==QEvent.Type.Hide:self.hide()
        return False
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.close_page();event.accept();return
        super().keyPressEvent(event)
    def paintEvent(self,event):p=QPainter(self);p.fillRect(self.rect(),QColor(color('#f5f2f7')))
