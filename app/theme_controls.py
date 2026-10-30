"""Theme swatches: only color, selection and a short delayed hover name."""
from PySide6.QtCore import Qt,Signal,QRectF
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QWidget,QHBoxLayout,QAbstractButton
from theme_registry import NAMES,values,palette

ORDER=('bailong','mist','jade','amber','night','cyber','starfield','division','custom')

class ThemeDot(QAbstractButton):
    def __init__(self,key,parent):
        super().__init__(parent);self.key=key;self.setFixedSize(30,34);self.setCheckable(True)
        self.setObjectName('theme_dot_'+key);self.setAccessibleName(NAMES[key]);self.setProperty('headerActionHint',NAMES[key])
        self.setToolTip('');self.setCursor(Qt.CursorShape.PointingHandCursor)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:colors=values(self.key,getattr(self.parentWidget(),'custom_colors',None))
        except ValueError:colors=palette()
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(colors['accent']));p.drawEllipse(QRectF(7,9,16,16))
        roles=('signalBlue','signalGold','signalOrange','signalRed') if self.key=='starfield' else ('accent','secondary','tertiary','chart')
        for i,key in enumerate(roles):
            p.setPen(QPen(QColor(colors[key]),3));p.drawArc(QRectF(4.5,6.5,21,21),(i*90+2)*16,86*16)
        if self.isChecked():
            p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(palette()['accentText']),1.6));p.drawEllipse(QRectF(1,3,28,28))
            p.setPen(QPen(QColor(colors['accentOn']),1.7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            p.drawLine(11,17,14,20);p.drawLine(14,20,19,14)
        elif self.underMouse() or self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(palette()['border']),1.4));p.drawEllipse(QRectF(1,3,28,28))

class ThemeChoices(QWidget):
    currentIndexChanged=Signal(int)
    def __init__(self,parent=None):
        super().__init__(parent);self.index=0;self.custom_colors=None;row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(3);self.buttons=[]
        for i,key in enumerate(ORDER):
            button=ThemeDot(key,self);button.clicked.connect(lambda checked=False,i=i:self.setCurrentIndex(i));row.addWidget(button);self.buttons.append(button)
        row.addStretch();self.buttons[0].setChecked(True)
    def currentData(self):return ORDER[self.index]
    def setCustomColors(self,colors):
        self.custom_colors=dict(colors);self.buttons[-1].update()
    def findData(self,key):return ORDER.index(key) if key in ORDER else 0
    def setCurrentIndex(self,index):
        index=max(0,min(len(ORDER)-1,index));changed=self.index!=index;self.index=index
        for i,button in enumerate(self.buttons):button.setChecked(i==index);button.update()
        if changed:self.currentIndexChanged.emit(index)
