"""Shared two-column metrics card for the model and quota pages."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from theme_runtime import set_theme_style
from typography import FONT_CSS
from ui_theme import INK, MUTED, PANEL


class ReportMetricPair(QWidget):
    def __init__(self, captions, name):
        super().__init__()
        self.captions=captions
        self.setObjectName(name)
        self.setFixedHeight(48)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        set_theme_style(self,f'QWidget#{name}{{background:{PANEL};border-radius:7px;}}')
        row=QHBoxLayout(self)
        row.setContentsMargins(7,3,7,3)
        row.setSpacing(4)
        self.columns=[]
        self.value_labels=[]
        for caption in captions:
            column=QWidget(self)
            column.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
            layout=QVBoxLayout(column)
            layout.setContentsMargins(0,0,0,0)
            layout.setSpacing(0)
            label=QLabel(caption,column)
            value=QLabel('—',column)
            for widget,size,shade,weight in ((label,12,MUTED,400),(value,20,INK,600)):
                widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
                set_theme_style(widget,FONT_CSS+f'font-size:{size}px;color:{shade};font-weight:{weight};background:transparent;')
                layout.addWidget(widget)
            row.addWidget(column,1)
            self.columns.append(column)
            self.value_labels.append(value)

    @property
    def values(self):
        return tuple(label.text() for label in self.value_labels)

    def set_values(self,*values):
        for label,text in zip(self.value_labels,values):
            if label.text()!=text:label.setText(text)
        self.setAccessibleName('，'.join(f'{caption} {value}' for caption,value in zip(self.captions,values)))
