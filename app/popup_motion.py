"""Paint popup motion within its final geometry, including native menus."""
from PySide6.QtCore import Qt,QPoint,QPointF,QRectF,QSize,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QCursor,QPainter,QPainterPath
from PySide6.QtWidgets import QApplication,QGraphicsEffect,QMenu
from settings_controls import motion_enabled

POPUP_OPEN_MS=335
POPUP_FULL_SIZE_MS=228
POPUP_CLOSE_MS=172

# Approximate silhouette and fade from repeated visible video frames.
# Each key is time, width, height, travel from the trigger, trailing inset,
# opacity and softness. Coordinates are relative to the fully open popup.
POPUP_OPEN=(
    (0,    .72,.19,.079,.038,0.,0.),
    (16,   .73,.19,.098,.035,.88,0.),
    (42,   .82,.49,.143,.050,1.,0.),
    (84,   .90,.72,.118,.040,1.,0.),
    (126,  .95,.92,.066,.023,1.,0.),
    (168,  .98,.97,.025,.008,1.,0.),
    (210,  .99,.99,.006,.002,1.,0.),
    (POPUP_FULL_SIZE_MS, 1., 1., 0., 0., 1.,0.),
    (248, 1., 1.,-.009,0.,  1.,0.),
    (276, 1., 1., .004,0.,  1.,0.),
    (308, 1., 1., 0.,  0.,  1.,0.),
    (335, 1., 1., 0.,  0.,  1.,0.),
)
POPUP_CLOSE=(
    (0,   1., 1., 0.,  0.,  1.,0.),
    (32,  .96,.94,.030,.013,.95,.12),
    (74,  .83,.49,.120,.037,.84,.88),
    (116, .71,.22,.119,.061,.36,1.),
    (150, .54,.17,.102,.076,.09,1.),
    (172, .48,.15,.088,.079,0.,1.),
)

def popup_sample(keys,ms):
    for before,after in zip(keys,keys[1:]):
        if ms<=after[0]:
            portion=max(0.,(ms-before[0])/(after[0]-before[0]))
            return tuple(a+(b-a)*portion for a,b in zip(before[1:],after[1:]))
    return keys[-1][1:]

def anchored_start(start,extent,revealed,anchor,inset):
    """Keep the trigger at the same proportional point along the reveal."""
    fraction=max(0.,min(1.,(anchor-start)/max(1.,extent)))
    remaining=max(0.,extent-revealed)
    margin=min(remaining/2,extent*inset)
    return start+margin+(remaining-2*margin)*fraction


class AnchoredPopupEffect(QGraphicsEffect):
    def __init__(self,parent):
        super().__init__(parent);self.level=0.;self.pivot=QPointF()
        self.closing=False;self.interrupted=None;self.soft=None

    def animate(self,animation,target):
        previous=self.sample() if 0.<self.level<1. else None
        animation.stop()
        self.closing=not target
        self.interrupted=(self.level,previous) if previous is not None else None
        self.soft=None
        animation.setDuration(POPUP_OPEN_MS if target else POPUP_CLOSE_MS)
        animation.setEasingCurve(QEasingCurve.Type.Linear)
        animation.setStartValue(self.level);animation.setEndValue(target);animation.start()

    def sample(self):
        if self.interrupted is None:
            if self.closing:return popup_sample(POPUP_CLOSE,(1.-self.level)*POPUP_CLOSE_MS)
            return popup_sample(POPUP_OPEN,self.level*POPUP_OPEN_MS)
        start,frame=self.interrupted
        target=0. if self.closing else 1.
        f=min(1.,abs(self.level-start)/max(.001,abs(target-start)))
        finish=(*frame[:4],0.,frame[-1]) if self.closing else POPUP_OPEN[-1][1:]
        return tuple(a+(b-a)*f for a,b in zip(frame,finish))

    def reveal_rect(self,area,sample):
        width,height,travel,inset,_,_=sample
        w=area.width()*width;h=area.height()*height
        dx=max(-.9,travel*area.height())
        x=anchored_start(area.left(),area.width(),w,self.pivot.x(),inset)
        y=area.top()+dx if self.pivot.y()<area.center().y() else area.bottom()-h-dx
        return QRectF(x,y,w,h)

    def draw(self,painter):
        if self.level<=0.:return
        if self.level>=1.:
            self.drawSource(painter);return
        area=self.sourceBoundingRect(Qt.CoordinateSystem.LogicalCoordinates)
        offset=QPoint()
        source=self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates,offset,self.PixmapPadMode.NoPad)
        if source.isNull():return
        sample=self.sample();rect=self.reveal_rect(area,sample)
        _,_,_,_,alpha,blur=sample
        settling=not self.closing and self.interrupted is None and self.level>=POPUP_FULL_SIZE_MS/POPUP_OPEN_MS
        shift=rect.topLeft()-area.topLeft()
        if settling:
            if shift.isNull():self.drawSource(painter);return
            interior=area.adjusted(3,3,-3,-3)
            rim=QPainterPath();rim.setFillRule(Qt.FillRule.OddEvenFill)
            rim.addRect(area);rim.addRect(interior)
            painter.save();painter.setClipRect(interior,Qt.ClipOperation.IntersectClip)
            painter.drawPixmap(offset,source);painter.restore()
            painter.save();painter.setClipPath(rim,Qt.ClipOperation.IntersectClip)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(QPointF(offset)+shift,source);painter.restore()
            return
        contour=QPainterPath();contour.addRoundedRect(rect,7,7)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(contour,Qt.ClipOperation.IntersectClip)
        painter.translate(0.,shift.y())
        opacity=painter.opacity()
        if blur>0. and self.soft is None:
            size=QSize(max(1,round(source.width()/5)),max(1,round(source.height()/5)))
            soft=source.scaled(size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self.soft=soft.scaled(source.size(),Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
            self.soft.setDevicePixelRatio(source.devicePixelRatioF())
        painter.setOpacity(opacity*alpha*(1.-blur if self.soft is not None else 1.))
        painter.drawPixmap(offset,source)
        if self.soft is not None and blur>0.:
            painter.setOpacity(opacity*alpha*blur);painter.drawPixmap(offset,self.soft)
        painter.restore()


class AnimatedContextMenu(QMenu):
    """Keep Qt's native mouse grab, action routing, and outside-click handling."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.motion=AnchoredPopupEffect(self)
        self.animation=QVariantAnimation(self)
        self.animation.valueChanged.connect(self._advance)
        self.animation.finished.connect(self._finish_motion)
        self._anchor=None;self._closing=False

    def popup(self,pos,at=None):
        self._anchor=pos
        if at is None:super().popup(pos)
        else:super().popup(pos,at)

    def exec(self,pos,at=None):
        self._anchor=pos
        if at is None:return super().exec(pos)
        return super().exec(pos,at)

    def _advance(self,value):
        self.motion.level=float(value)
        if not self.isVisible() or QApplication.platformName()=='windows':return
        # Native Windows QMenu and its shadow share Qt's popup paint path.
        # Keep its geometry/mask intact throughout the nested exec loop.
        if not self.motion.closing and self.motion.level>=POPUP_FULL_SIZE_MS/POPUP_OPEN_MS:
            self.setWindowOpacity(1.);return
        self.setWindowOpacity(self.motion.sample()[4])

    def _animate(self,target):
        self.motion.animate(self.animation,target)

    def showEvent(self,event):
        # Keep the native QMenu shadow and paint lifecycle under Qt ownership.
        # A window mask reveals the menu without replacing its graphics effect.
        anchor=self.mapFromGlobal(self._anchor or QCursor.pos())
        self.motion.pivot=QPointF(max(0,min(self.width(),anchor.x())),max(0,min(self.height(),anchor.y())))
        self._closing=False
        animated=motion_enabled() and QApplication.platformName()!='windows'
        self._advance(0. if animated else 1.)
        super().showEvent(event)
        if animated:self._animate(1.)

    def hideEvent(self,event):
        self.animation.stop()
        if QApplication.platformName()!='windows':self.setWindowOpacity(1.)
        self.motion.level=0.;self.motion.interrupted=None;self.motion.soft=None
        self._anchor=None;self._closing=False
        super().hideEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape and motion_enabled() and QApplication.platformName()!='windows':
            if not self._closing:
                self._closing=True;self._animate(0.)
            event.accept();return
        super().keyPressEvent(event)

    def _finish_motion(self):
        self.motion.soft=None;self.motion.interrupted=None
        if self._closing:self.hide()


def ContextMenu(parent=None):
    # QMenu.exec on Windows 11 must retain the platform menu implementation.
    if QApplication.platformName()=='windows':return QMenu(parent)
    return AnimatedContextMenu(parent)
