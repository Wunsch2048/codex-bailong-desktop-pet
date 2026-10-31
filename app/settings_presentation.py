"""Compact settings presentation; persistence stays with SettingsDialog."""
from PySide6.QtCore import Qt,QRectF,QSize,QPointF
from PySide6.QtGui import QPainter,QColor,QFontMetrics,QPen,QPainterPath
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QToolButton,QPushButton,QStyleOptionToolButton,QStyle
from settings_controls import SwitchRow
from theme_controls import ThemeChoices,ThemeDot,ORDER
from theme_registry import palette,values
from typography import ui_font
from theme_runtime import set_theme_style


class SettingsSwitchRow(SwitchRow):
    """Whole-row toggle with the same input semantics and a quieter 31px row."""
    def __init__(self,title,parent=None):
        super().__init__(title,parent);self.setFont(ui_font(11))
    def heightForWidth(self,width):
        bounds=QFontMetrics(self.font()).boundingRect(0,0,max(20,width-43),1000,int(Qt.TextFlag.TextWordWrap),self.text())
        return max(31,bounds.height()+12)
    def sizeHint(self):return QSize(220,self.heightForWidth(max(180,self.width())))
    def minimumSizeHint(self):return QSize(140,31)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);colors=palette()
        if self.property('separated'):
            p.setPen(QPen(QColor(colors['track']),1));p.drawLine(QPointF(0,.5),QPointF(self.width(),.5))
        if self.hasFocus():
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(colors['panel']));p.drawRoundedRect(QRectF(self.rect()),5,5)
        p.setFont(self.font());p.setPen(QColor(colors['ink'] if self.isEnabled() else colors['muted']))
        p.drawText(QRectF(0,5,self.width()-41,self.height()-10),int(Qt.AlignmentFlag.AlignVCenter|Qt.TextFlag.TextWordWrap),self.text())
        track=QRectF(self.width()-28,(self.height()-17)/2,28,17);t=self.position
        off=QColor(colors['track']);on=QColor(colors['accent'])
        fill=QColor.fromRgbF(off.redF()+(on.redF()-off.redF())*t,off.greenF()+(on.greenF()-off.greenF())*t,off.blueF()+(on.blueF()-off.blueF())*t)
        if not self.isEnabled():p.setOpacity(.45)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(fill);p.drawRoundedRect(track,8.5,8.5)
        a=QColor(colors['switchOffKnob']);z=QColor(colors['switchOnKnob'])
        knob=QColor.fromRgbF(a.redF()+(z.redF()-a.redF())*t,a.greenF()+(z.greenF()-a.greenF())*t,a.blueF()+(z.blueF()-a.blueF())*t)
        knob.setAlphaF(.55+.45*t)
        p.setBrush(knob);p.drawEllipse(QRectF(track.x()+2+11*t,track.y()+2,13,13));p.end()


class CompactThemeDot(ThemeDot):
    def __init__(self,key,parent):super().__init__(key,parent);self.setFixedSize(27,30)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:colors=values(self.key,getattr(self.parentWidget(),'custom_colors',None))
        except ValueError:colors=palette()
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(colors['accent']));p.drawEllipse(QRectF(7,7,13,13))
        roles=('signalBlue','signalGold','signalOrange','signalRed') if self.key=='starfield' else ('accent','secondary','tertiary','chart')
        for i,key in enumerate(roles):
            p.setPen(QPen(QColor(colors[key]),3));p.drawArc(QRectF(5.5,5.5,16,16),(i*90+2)*16,86*16)
        if self.isChecked() or self.underMouse() or self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(palette()['muted'] if self.isChecked() else palette()['border']),1));p.drawEllipse(QRectF(2.5,2.5,22,22))
        p.end()


class SettingsThemeChoices(ThemeChoices):
    def __init__(self,parent=None):
        QWidget.__init__(self,parent);self.index=0;self.custom_colors=None;self.buttons=[]
        self.setFixedHeight(30);row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(1)
        for i,key in enumerate(ORDER):
            button=CompactThemeDot(key,self);button.clicked.connect(lambda checked=False,i=i:self.setCurrentIndex(i));row.addWidget(button);self.buttons.append(button)
        row.addStretch();self.buttons[0].setChecked(True);self.buttons[-1].hide()


class SettingsStatusLabel(QLabel):
    """Empty feedback must not reserve a line above the fixed footer."""
    def setText(self,text):super().setText(text);self.setVisible(bool(text))
    def clear(self):self.setText('')


class SettingsResetButton(QToolButton):
    """Small vector reset action; independent of symbol-font availability."""
    def paintEvent(self,event):
        option=QStyleOptionToolButton();self.initStyleOption(option)
        p=QPainter(self);self.style().drawComplexControl(QStyle.ComplexControl.CC_ToolButton,option,p,self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.translate(self.width()/2-8,self.height()/2-8)
        p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(palette()['accentText'] if self.isEnabled() else palette()['muted']),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        path=QPainterPath(QPointF(3,5));path.cubicTo(8,-.5,14.7,3.6,13.5,9.4);path.cubicTo(12.2,15.6,3.8,16,2,11)
        p.drawPath(path);path=QPainterPath(QPointF(3,1));path.lineTo(3,5);path.lineTo(7,5);p.drawPath(path);p.end()


class SettingsDisclosureButton(QPushButton):
    def paintEvent(self,event):
        super().paintEvent(event)
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.translate(self.width()-13,self.height()/2)
        p.setPen(QPen(QColor(palette()['accentText']),1.25,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        direction=-1 if self.isChecked() else 1
        p.drawLine(QPointF(-3,-1.5*direction),QPointF(0,1.5*direction));p.drawLine(QPointF(0,1.5*direction),QPointF(3,-1.5*direction));p.end()


class SettingsFooterButton(QPushButton):
    def __init__(self,text,primary=False):
        super().__init__(text);self.primary=primary;self.setFont(ui_font(11));self.setFixedWidth(50 if primary else 40)
        set_theme_style(self,'QPushButton{min-height:30px;max-height:30px;padding:0;border:0;background:transparent;}')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    def paintEvent(self,event):
        colors=palette();p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():p.setOpacity(.42)
        background=colors['accent'] if self.primary else colors['panel']
        if self.isEnabled() and (self.underMouse() or self.isDown()):background=colors['primaryPressed'] if self.primary else colors['selected']
        p.setPen(QPen(QColor(colors['accent'] if self.primary or self.hasFocus() else colors['border']),1));p.setBrush(QColor(background))
        p.drawRoundedRect(QRectF(.5,.5,self.width()-1,self.height()-1),6,6)
        p.setFont(self.font());p.setPen(QColor(colors['accentOn'] if self.primary else colors['accentText']));p.drawText(self.rect(),int(Qt.AlignmentFlag.AlignCenter),self.text());p.end()
