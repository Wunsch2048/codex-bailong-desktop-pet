"""Native numeric editing with clear, quiet decrement/increment controls."""
from settings_controls import play_animation
from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QPainter,QPen,QColor
from PySide6.QtWidgets import QAbstractButton,QAbstractSpinBox,QSpinBox,QDoubleSpinBox
from typography import FONT_CSS,ui_font
from ui_theme import SURFACE,PANEL,SELECTED,BORDER,INK,PRIMARY
from settings_controls import motion_enabled


class StepButton(QAbstractButton):
    def __init__(self,positive,parent):
        super().__init__(parent);self.positive=positive;self.hover=0.
        self.setFixedSize(26,26);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor);self.setAutoRepeat(True)
        self.setAutoRepeatDelay(400);self.setAutoRepeatInterval(90)
        self.setAccessibleName('增加数值' if positive else '减少数值')
        self.animation=QVariantAnimation(self);self.animation.setDuration(130)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.animation.valueChanged.connect(self.advance)
    def advance(self,value):self.hover=float(value);self.update()
    def fade(self,target):
        self.animation.stop()
        if self.isVisible() and motion_enabled():
            self.animation.setStartValue(self.hover);self.animation.setEndValue(target);play_animation(self.animation)
        else:self.hover=target;self.update()
    def enterEvent(self,event):self.fade(1.);super().enterEvent(event)
    def leaveEvent(self,event):self.fade(0.);super().leaveEvent(event)
    def hideEvent(self,event):self.animation.stop();self.hover=0.;super().hideEvent(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a,b=QColor(theme_color(PANEL)),QColor(theme_color(SELECTED));f=self.hover
        color=QColor.fromRgbF(*(x+(y-x)*f for x,y in zip(a.getRgbF()[:3],b.getRgbF()[:3])))
        if self.isDown():color=QColor(theme_color(BORDER))
        elif self.hasFocus():color=QColor(theme_color(SELECTED))
        if not self.isEnabled():p.setOpacity(.35)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme_color(color));p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),5,5)
        p.setPen(QPen(QColor(theme_color(INK)),1.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(8.5,13),QPointF(17.5,13))
        if self.positive:p.drawLine(QPointF(13,8.5),QPointF(13,17.5))


class _NumberField:
    def __init__(self,parent=None):
        super().__init__(parent);self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setMinimumHeight(34);self.setMinimumWidth(138);self.setFont(ui_font(12))
        set_theme_style(self,'QAbstractSpinBox{'+FONT_CSS+f'font-size:12px;color:{INK};background:{SURFACE};border:1px solid {BORDER};border-radius:8px;padding:4px 66px 4px 10px;}}'
            f'QAbstractSpinBox:focus{{border-color:{PRIMARY};}}QAbstractSpinBox:disabled{{color:{BORDER};}}')
        self.minus=StepButton(False,self);self.plus=StepButton(True,self)
        self.minus.clicked.connect(self.stepDown);self.plus.clicked.connect(self.stepUp)
        self.valueChanged.connect(self.sync_buttons);self.sync_buttons()
    def sync_buttons(self,*args):
        if not hasattr(self,'minus'):return
        active=self.isEnabled() and not self.isReadOnly();flags=self.stepEnabled()
        self.minus.setEnabled(active and bool(flags&QAbstractSpinBox.StepEnabledFlag.StepDownEnabled))
        self.plus.setEnabled(active and bool(flags&QAbstractSpinBox.StepEnabledFlag.StepUpEnabled))
    def setRange(self,*args):super().setRange(*args);self.sync_buttons()
    def setMinimum(self,*args):super().setMinimum(*args);self.sync_buttons()
    def setMaximum(self,*args):super().setMaximum(*args);self.sync_buttons()
    def setReadOnly(self,*args):super().setReadOnly(*args);self.sync_buttons()
    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.Type.EnabledChange:self.sync_buttons()
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'minus'):
            self.minus.move(self.width()-61,(self.height()-26)//2)
            self.plus.move(self.width()-31,(self.height()-26)//2)
    def wheelEvent(self,event):
        if self.hasFocus():super().wheelEvent(event)
        else:event.ignore()


class DecimalField(_NumberField,QDoubleSpinBox):pass
class IntegerField(_NumberField,QSpinBox):pass
