"""Native numeric editing with clear, quiet decrement/increment controls."""
from settings_controls import play_animation
from theme_registry import color as theme_color,mix,palette
from theme_runtime import set_theme_style,theme_style_source
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent,QVariantAnimation,QEasingCurve,QSignalBlocker
from PySide6.QtGui import QPainter,QPen,QColor
from PySide6.QtWidgets import QAbstractButton,QAbstractSpinBox,QSpinBox,QDoubleSpinBox,QWidget,QHBoxLayout,QSlider,QStyle,QStyleOptionSlider
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
        # Scrolling the settings page must never edit a numeric preference.
        event.ignore()


class DecimalField(_NumberField,QDoubleSpinBox):pass
class IntegerField(_NumberField,QSpinBox):pass


class SizeSlider(QSlider):
    def __init__(self,orientation):
        super().__init__(orientation)
        self._drag=None
        set_theme_style(self,'QSlider::groove:horizontal{background:transparent;height:4px;border-radius:2px;}'
                        f'QSlider::handle:horizontal{{background:{SURFACE};border:2px solid {PRIMARY};width:11px;margin:-5px 0;border-radius:7px;}}'
                        f'QSlider:focus::handle:horizontal{{background:{SELECTED};}}')

    def handle_rect(self,option):
        return self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,
                                           QStyle.SubControl.SC_SliderHandle,self)

    def track_limits(self,option):
        ends=QStyleOptionSlider(option)
        ends.sliderPosition=ends.sliderValue=self.minimum()
        first=QRectF(self.handle_rect(ends)).center().x()
        ends.sliderPosition=ends.sliderValue=self.maximum()
        last=QRectF(self.handle_rect(ends)).center().x()
        return first,last

    def paintEvent(self,event):
        option=QStyleOptionSlider()
        self.initStyleOption(option)
        handle=QRectF(self.handle_rect(option))
        center=handle.center()
        first,last=self.track_limits(option)
        theme=palette()
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():painter.setOpacity(.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(mix(theme['surface'],theme['ink'],.14)))
        painter.drawRoundedRect(QRectF(min(first,last),center.y()-2,abs(last-first),4),2,2)
        painter.setBrush(QColor(theme['accentText']))
        selected=abs(center.x()-first)
        if selected:
            painter.drawRoundedRect(QRectF(min(center.x(),first),center.y()-2,selected,4),2,2)
        painter.setOpacity(1)
        painter.setPen(QPen(QColor(theme_color(PRIMARY)),2))
        painter.setBrush(QColor(theme_color(SELECTED if self.hasFocus() else SURFACE)))
        painter.drawRoundedRect(handle.adjusted(1,1,-1,-1),7,7)

    def mousePressEvent(self,event):
        option=QStyleOptionSlider()
        self.initStyleOption(option)
        first,last=self.track_limits(option)
        super().mousePressEvent(event)
        if self.isSliderDown() and first!=last:
            # Preview can resize the window containing this rail mid-gesture.
            self._drag=(event.globalPosition().x(),self.sliderPosition(),last-first)

    def mouseMoveEvent(self,event):
        if self.isSliderDown() and self._drag:
            start,value,span=self._drag
            delta=(event.globalPosition().x()-start)*(self.maximum()-self.minimum())/span
            self.setSliderPosition(max(self.minimum(),min(self.maximum(),round(value+delta))))
            event.accept()
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        self._drag=None
        super().mouseReleaseEvent(event)

    def wheelEvent(self,event):
        event.ignore()


class SizeInput(QDoubleSpinBox):
    def wheelEvent(self,event):
        event.ignore()

    def textFromValue(self,value):
        locale=self.locale()
        if value.is_integer():return locale.toString(int(value))
        text=locale.toString(value,'f',self.decimals())
        return text.rstrip(locale.zeroDigit()).rstrip(locale.decimalPoint())


class SizeField(QWidget):
    def __init__(self,title,limits):
        super().__init__()
        lo,hi=(round(value*100) for value in limits)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(8)
        self.slider=SizeSlider(Qt.Orientation.Horizontal)
        self.slider.setAccessibleName(title+'滑块');self.slider.setRange(lo,hi);self.slider.setPageStep(5)
        self.slider.setMinimumWidth(60);self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.slider,1)
        self.input=SizeInput();self.input.setAccessibleName(title+'百分比');self.input.setFont(ui_font(12))
        self.input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.input.setKeyboardTracking(False);self.input.setDecimals(2);self.input.setRange(lo,hi)
        self.input.setSuffix('%');self.input.setFixedWidth(76);self.input.setMinimumHeight(30)
        row.addWidget(self.input)
        self.slider.valueChanged.connect(self.input.setValue)
        self.input.valueChanged.connect(self.sync_slider)

    def sync_slider(self,value):
        with QSignalBlocker(self.slider):self.slider.setValue(round(value))

