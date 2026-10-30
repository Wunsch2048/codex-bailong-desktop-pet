"""In-card choice sheets; QComboBox data/signals remain compatible."""
from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
from PySide6.QtCore import Qt,QPoint,QRect,QEvent,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QPainter,QColor,QPen,QFontMetrics
from PySide6.QtWidgets import QComboBox,QFrame,QVBoxLayout,QLineEdit,QListWidget,QListWidgetItem,QApplication,QGraphicsOpacityEffect
from typography import FONT_CSS,ui_font
from ui_theme import SURFACE,PANEL,INK,MUTED,PRIMARY,BORDER,SELECTED,hide_scrollbars
from settings_controls import motion_enabled


class ChoiceCombo(QComboBox):
    def __init__(self,parent=None):
        super().__init__(parent);self._panel=None;self.setMinimumHeight(30);self.setFont(ui_font(12))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(7)
        self.model().modelReset.connect(self.hidePopup);self.model().rowsRemoved.connect(lambda *args:self.hidePopup())
    def showPopup(self):
        if self._panel:self.hidePopup();return
        if self.count() and self.isEnabled():self._panel=ChoiceSheet(self);self._panel.present()
    def hidePopup(self):
        if self._panel:
            panel=self._panel;self._panel=None;panel.dismiss()
    def hideEvent(self,event):self.hidePopup();super().hideEvent(event)
    def wheelEvent(self,event):
        # Scrolling a settings page must never edit the value under the cursor,
        # including when a previous click left this choice focused.
        event.ignore()
    def display_text(self):return self.currentText()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(theme_color(PANEL if self.hasFocus() or self._panel else SURFACE)));p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect().adjusted(1,1,-1,-1),7,7)
        p.setFont(ui_font(12));p.setPen(QColor(theme_color(INK if self.isEnabled() else MUTED)))
        value=QFontMetrics(p.font()).elidedText(self.display_text(),Qt.TextElideMode.ElideRight,max(0,self.width()-34))
        p.drawText(self.rect().adjusted(9,0,-26,0),Qt.AlignmentFlag.AlignVCenter,value)
        p.setPen(QPen(QColor(theme_color(MUTED)),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        x=self.width()-15;y=self.height()/2
        p.drawLine(QPoint(x-3,int(y-3)),QPoint(x,int(y-6)));p.drawLine(QPoint(x,int(y-6)),QPoint(x+3,int(y-3)))
        p.drawLine(QPoint(x-3,int(y+3)),QPoint(x,int(y+6)));p.drawLine(QPoint(x,int(y+6)),QPoint(x+3,int(y+3)))


class ChoiceSheet(QFrame):
    def __init__(self,owner):
        super().__init__(owner.window());self.owner=owner;self.closing=False
        self.setObjectName('choice_sheet');set_theme_style(self,f'QFrame#choice_sheet{{background:{SURFACE};border:1px solid {BORDER};border-radius:10px;}}'
            'QListWidget{'+FONT_CSS+f'font-size:12px;color:{INK};background:transparent;border:0;outline:0;}}'
            f'QListWidget::item{{padding:7px 8px;border-radius:6px;}}QListWidget::item:selected{{background:{SELECTED};color:{INK};}}'
            f'QListWidget::item:hover{{background:{PANEL};}}QLineEdit{{'+FONT_CSS+f'font-size:12px;color:{INK};background:{PANEL};border:0;border-radius:6px;padding:6px;}}')
        layout=QVBoxLayout(self);layout.setContentsMargins(6,6,6,6);layout.setSpacing(4)
        self.search=QLineEdit();self.search.setPlaceholderText('搜索');self.search.setClearButtonEnabled(True)
        self.search.setVisible(owner.count()>7);layout.addWidget(self.search)
        self.list=hide_scrollbars(QListWidget())
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel);layout.addWidget(self.list)
        for i in range(owner.count()):
            item=QListWidgetItem(('✓  ' if i==owner.currentIndex() else '    ')+owner.itemText(i))
            item.setData(Qt.ItemDataRole.UserRole,i);self.list.addItem(item)
        self.list.setCurrentRow(owner.currentIndex());self.list.itemClicked.connect(self.choose)
        self.list.itemActivated.connect(self.choose);self.search.textChanged.connect(self.filter)
        self.search.installEventFilter(self);self.list.installEventFilter(self)
        self.effect=QGraphicsOpacityEffect(self);self.setGraphicsEffect(self.effect)
        self.animation=QVariantAnimation(self);self.animation.setDuration(140);self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.effect.setOpacity);self.animation.finished.connect(self.finished)
    def present(self):
        host=self.parentWidget();origin=self.owner.mapTo(host,QPoint(0,0))
        width=min(max(200,self.owner.width()),host.width()-16)
        height=min(12+min(8,self.owner.count())*33+(34 if self.owner.count()>7 else 0),host.height()-16)
        x=max(8,min(origin.x(),host.width()-width-8));y=origin.y()+self.owner.height()+4
        if y+height>host.height()-8:y=max(8,origin.y()-height-4)
        y=max(8,min(y,host.height()-height-8))
        self.setGeometry(x,y,width,height);self.show();self.raise_()
        QApplication.instance().installEventFilter(self)
        (self.search if self.search.isVisible() else self.list).setFocus()
        self.list.scrollToItem(self.list.currentItem())
        self.effect.setOpacity(0 if motion_enabled() else 1)
        if motion_enabled():self.animation.setStartValue(0.);self.animation.setEndValue(1.);self.animation.start()
    def filter(self,text):
        for i in range(self.list.count()):self.list.item(i).setHidden(text.casefold() not in self.list.item(i).text().casefold())
    def choose(self,item):
        if self.closing:return
        self.owner.setCurrentIndex(item.data(Qt.ItemDataRole.UserRole));self.owner.hidePopup()
    def dismiss(self):
        if self.closing:return
        self.closing=True;QApplication.instance().removeEventFilter(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.animation.stop()
        if self.isVisible() and self.owner.isVisible() and motion_enabled():
            self.animation.setStartValue(self.effect.opacity());self.animation.setEndValue(0.);self.animation.start()
        else:self.finished()
    def finished(self):
        if self.closing:self.hide();self.deleteLater()
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Wheel:
            if not self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint())):self.owner.hidePopup()
        if event.type()==QEvent.Type.KeyPress:
            if event.key()==Qt.Key.Key_Escape:self.owner.hidePopup();self.owner.setFocus();return True
            if obj is self.search and event.key()==Qt.Key.Key_Down:self.list.setFocus();return True
        if event.type()==QEvent.Type.MouseButtonPress:
            point=event.globalPosition().toPoint()
            if not self.rect().contains(self.mapFromGlobal(point)):
                self.owner.hidePopup()
                return self.owner.rect().contains(self.owner.mapFromGlobal(point))
        if obj is self.owner and event.type() in (QEvent.Type.Hide,QEvent.Type.Close):self.owner.hidePopup()
        return super().eventFilter(obj,event)
