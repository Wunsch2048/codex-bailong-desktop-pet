"""Small native controls using the companion's existing typography and palette."""
from theme_registry import color as theme_color,palette
from theme_runtime import set_theme_style,theme_style_source
import os
from functools import lru_cache
from PySide6.QtCore import Qt,QRectF,QSize,Signal,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QPainter,QColor,QPen,QFontMetrics
from PySide6.QtWidgets import QWidget,QHBoxLayout,QToolButton,QCheckBox,QSizePolicy
from typography import FONT_CSS,ui_font
from ui_theme import INK,MUTED,PRIMARY,SELECTED,PANEL,BORDER,SURFACE,DISABLED


_motion_mode='quality'

@lru_cache(maxsize=1)
def _system_motion_enabled():
    if os.environ.get('BAILONG_REDUCED_MOTION')=='1':return False
    if os.name=='nt':
        try:
            import ctypes
            enabled=ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042,0,ctypes.byref(enabled),0):return bool(enabled.value)
        except (OSError,AttributeError):pass
    return True

def motion_enabled():
    return _motion_mode=='quality' and _system_motion_enabled()

def set_motion_mode(mode):
    """Process-local presentation policy; persistence belongs to saved settings."""
    global _motion_mode
    _motion_mode='performance' if mode=='performance' else 'quality'

def play_animation(animation):
    """Keep normal finish/landing callbacks even when spatial motion is reduced."""
    animation.start()
    if not motion_enabled():animation.setCurrentTime(animation.duration())

def settle_motion():
    """One sweep on a mode change, never a background poll or decoder change."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QAbstractAnimation
    app=QApplication.instance()
    if app is None:return
    if not motion_enabled():
        for animation in app.findChildren(QAbstractAnimation):
            if animation.state()==QAbstractAnimation.State.Running and animation.loopCount()==1:
                animation.setCurrentTime(animation.duration())
        # Top-level widgets are not necessarily QApplication children.
        for widget in app.allWidgets():
            for animation in widget.findChildren(QAbstractAnimation,options=Qt.FindChildOption.FindDirectChildrenOnly):
                if animation.state()==QAbstractAnimation.State.Running and animation.loopCount()==1:
                    animation.setCurrentTime(animation.duration())
    for widget in app.allWidgets():
        callback=getattr(widget,'motion_policy_changed',None)
        if callback:callback()


class SlidingSegments(QWidget):
    currentIndexChanged=Signal(int)
    def __init__(self,items,parent=None,compact=False):
        super().__init__(parent);self.items=list(items);self.buttons={};self._index=0;self.pill=QRectF()
        self.setFixedHeight(27 if compact else 32)
        row=QHBoxLayout(self);row.setContentsMargins(3,3,3,3);row.setSpacing(0)
        for i,(label,key) in enumerate(self.items):
            b=QToolButton(self);b.setText(label);b.setCheckable(True);b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor);b.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
            set_theme_style(b,'QToolButton{'+FONT_CSS+f'font-size:12px;color:{MUTED};background:transparent;border:0;padding:0 {2 if compact else 4}px;}}'
                f'QToolButton:checked{{color:{INK};}}QToolButton:focus{{border:0;outline:0;color:{PRIMARY};}}')
            b.clicked.connect(lambda checked=False,index=i:self.setCurrentIndex(index));row.addWidget(b,1);self.buttons[key]=b
        self.animation=QVariantAnimation(self);self.animation.setDuration(170)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.animation.valueChanged.connect(self._advance)
        self.setMinimumWidth(94 if compact else 174);self.setCurrentIndex(0,animate=False)
    def currentData(self):return self.items[self._index][1]
    def currentIndex(self):return self._index
    def findData(self,key):return next((i for i,(_,k) in enumerate(self.items) if k==key),-1)
    def setCurrentIndex(self,index,animate=True):
        if not 0<=index<len(self.items):return
        if index==self._index and animate and not self.pill.isEmpty():
            for key,b in self.buttons.items():b.setChecked(key==self.currentData())
            return
        changed=index!=self._index;self._index=index;self.layout().activate()
        target=QRectF(self.buttons[self.currentData()].geometry());self.animation.stop()
        if animate and changed and self.isVisible() and not self.pill.isEmpty() and motion_enabled():
            self.animation.setStartValue(QRectF(self.pill));self.animation.setEndValue(target);self.animation.start()
        else:self.pill=target;self.update()
        for key,b in self.buttons.items():b.setChecked(key==self.currentData())
        if changed:self.currentIndexChanged.emit(index)
    def _advance(self,value):self.pill=QRectF(value);self.update()
    def resizeEvent(self,event):
        super().resizeEvent(event);self.setCurrentIndex(self._index,False)
    def showEvent(self,event):
        super().showEvent(event);self.setCurrentIndex(self._index,False)
    def hideEvent(self,event):
        self.animation.stop();super().hideEvent(event)
    def paintEvent(self,event):
        # Hidden layout changes do not deliver resize/show events before a
        # transition snapshot. Paint the settled target, not the old pill rect.
        if self.animation.state()!=self.animation.State.Running:
            self.pill=QRectF(self.buttons[self.currentData()].geometry())
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        preview=bool(self.property('largeCardPalette'))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color(PANEL if preview else SELECTED)));p.drawRoundedRect(QRectF(self.rect()),8,8)
        p.setBrush(QColor(theme_color(SELECTED if preview else SURFACE)));p.drawRoundedRect(self.pill,5,5)


class SwitchRow(QCheckBox):
    """Keyboard/accessibility-compatible checkbox with a full-row hit target."""
    def __init__(self,title,parent=None):
        super().__init__(title,parent);self.position=0.;self.setFont(ui_font(12));self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        set_theme_style(self,'QCheckBox{border:0;padding:0;background:transparent;}')
        self.animation=QVariantAnimation(self);self.animation.setDuration(160)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.animation.valueChanged.connect(self._advance)
        self.toggled.connect(self._toggle)
    def hasHeightForWidth(self):return True
    def heightForWidth(self,width):
        bounds=QFontMetrics(self.font()).boundingRect(0,0,max(20,width-69),1000,int(Qt.TextFlag.TextWordWrap),self.text())
        return max(42,bounds.height()+18)
    def sizeHint(self):return QSize(300,self.heightForWidth(max(220,self.width())))
    def minimumSizeHint(self):return QSize(160,42)
    def hitButton(self,point):return self.rect().contains(point)
    def _toggle(self,checked):
        self.animation.stop();target=float(checked)
        if self.isVisible() and motion_enabled():
            self.animation.setStartValue(self.position);self.animation.setEndValue(target);self.animation.start()
        else:self.position=target;self.update()
    def _advance(self,value):self.position=float(value);self.update()
    def showEvent(self,event):
        self.animation.stop();self.position=float(self.isChecked());super().showEvent(event)
    def hideEvent(self,event):self.animation.stop();super().hideEvent(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color(PANEL if self.hasFocus() else SURFACE)));p.drawRoundedRect(QRectF(self.rect()),8,8)
        p.setFont(self.font());p.setPen(QColor(theme_color(INK if self.isEnabled() else DISABLED)))
        p.drawText(QRectF(9,7,self.width()-68,self.height()-14),int(Qt.AlignmentFlag.AlignVCenter|Qt.TextFlag.TextWordWrap),self.text())
        track=QRectF(self.width()-47,(self.height()-22)/2,38,22)
        off=QColor(theme_color(BORDER));on=QColor(theme_color(PRIMARY));t=self.position
        mix=QColor.fromRgbF(off.redF()+(on.redF()-off.redF())*t,off.greenF()+(on.greenF()-off.greenF())*t,off.blueF()+(on.blueF()-off.blueF())*t)
        if not self.isEnabled():p.setOpacity(.45)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(theme_color(mix));p.drawRoundedRect(track,11,11)
        colors=palette();a=QColor(colors['switchOffKnob']);z=QColor(colors['switchOnKnob'])
        knob=QColor.fromRgbF(a.redF()+(z.redF()-a.redF())*t,a.greenF()+(z.greenF()-a.greenF())*t,a.blueF()+(z.blueF()-a.blueF())*t)
        p.setBrush(knob);p.drawEllipse(QRectF(track.x()+2+16*t,track.y()+2,18,18))
        p.setOpacity(1)
