"""Compact date picker inside the report's existing surface."""
from calendar import monthrange
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QLabel, QGridLayout, QHBoxLayout, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from choice_controls import ChoiceCombo
from report_dates import DAY, MONTH, WEEK, date_bounds, period_text, quota_days, quota_span, quota_text
from theme_registry import mix, palette
from theme_runtime import set_theme_style
from typography import FONT_CSS, ui_font
from ui_theme import hide_scrollbars


class DateButton(QToolButton):
    """Inline date with a compact, theme-coloured downward triangle."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(ui_font(12))

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text())+17,24)

    def paintEvent(self, event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme=palette()
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(theme['accent']),1))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),4,4)
        p.setFont(self.font());p.setPen(QColor(theme['ink']))
        p.drawText(self.rect().adjusted(1,0,-14,0),Qt.AlignmentFlag.AlignVCenter,self.text())
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme['accentText']))
        x=self.width()-10;y=self.height()/2
        p.drawPolygon(QPolygonF([QPointF(x-3.5,y-2),QPointF(x+3.5,y-2),QPointF(x,y+2.5)]))


def caption(text='',size=11,strong=False):
    label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText)
    set_theme_style(label,FONT_CSS+f'font-size:{size}px;font-weight:{600 if strong else 500};color:{"#393343" if strong else "#706879"};background:transparent;')
    return label


def control(text, action, primary=False):
    button=QToolButton();button.setText(text);button.clicked.connect(action)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
    button.setFixedHeight(29)
    bg,ink=('#8b78a6','#ffffff') if primary else ('#f5f0f8','#393343')
    set_theme_style(button,'QToolButton{'+FONT_CSS+f'font-size:12px;color:{ink};background:{bg};border:1px solid transparent;border-radius:7px;}}'+
        'QToolButton:focus{border:1px solid #8b78a6;}QToolButton:disabled{color:#9e96a7;background:transparent;}')
    return button


class CalendarCell(QToolButton):
    def __init__(self, parent, value, text, *, marker=False, selected=False, band=False,
                 first=False, last=False, circle=False, future=False, alternate=False, shared=False):
        super().__init__(parent)
        self.month_cell=text.endswith('月')
        self.setText(text);self.setCheckable(True)
        self.setFixedHeight(64 if self.month_cell else 29)
        self.setMinimumWidth(0);self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_appearance(value,marker,selected,band=band,first=first,last=last,circle=circle,
                            future=future,alternate=alternate,shared=shared)

    def set_appearance(self,value,marker,selected,*,band=False,first=False,last=False,circle=False,
                       future=False,alternate=False,shared=False):
        next_state=(value,marker,selected,band,first,last,circle,future,alternate,shared)
        self.setChecked(selected)
        if next_state==getattr(self,'_appearance',None):return
        self._appearance=next_state
        self.value=value;self.marker=marker;self.selected=selected;self.band=band
        self.first=first;self.last=last;self.circle=circle;self.future=future
        self.alternate=alternate;self.shared=shared
        self.setAccessibleName(value.isoformat()+(' 两个周期相接' if shared else ''))
        self.update()

    def set_surface_scale(self,pixels):
        self.setFixedHeight(pixels(64 if self.month_cell else 29))

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme=palette();center=QRectF(self.rect()).center()
        diameter=36 if self.month_cell else 22
        if self.band:
            height=22 if self.selected else 20
            left=center.x()-diameter/2 if self.first and self.circle else 0
            right=center.x()+diameter/2 if self.last and self.circle else self.width()
            rect=QRectF(left,center.y()-height/2,max(0,right-left),height)
            radius=height/2;path=QPainterPath();path.setFillRule(Qt.FillRule.WindingFill);path.addRoundedRect(rect,radius,radius)
            if not self.first:path.addRect(QRectF(left,rect.y(),min(radius,rect.width()),height))
            if not self.last:path.addRect(QRectF(max(left,right-radius),rect.y(),min(radius,rect.width()),height))
            shade=mix(theme['panel'],theme['accent'],.14 if self.future else .25) if self.selected else mix(theme['panel'],theme['ink'],.10 if self.alternate else .055)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(shade));p.drawPath(path)
        if self.circle:
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme['accent']));p.drawEllipse(center,diameter/2,diameter/2)
        ink=theme['accentOn'] if self.circle else theme['ink'] if self.isEnabled() and not self.future else theme['muted']
        p.setPen(QColor(ink));p.setFont(ui_font(14 if self.month_cell else 13))
        p.drawText(QRectF(self.rect()).translated(0,-2 if self.marker else 0),Qt.AlignmentFlag.AlignCenter,self.text())
        if self.marker:
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme['accentOn'] if self.circle else theme['accentText']))
            y=center.y()+(13 if self.month_cell else 7)
            for x in (-2,2) if self.shared else (0,):p.drawEllipse(QPointF(center.x()+x,y),1.5,1.5)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(theme['accent']),1))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),5,5)


class ReportCalendar(QWidget):
    accepted=Signal(object)
    cancelled=Signal()

    def __init__(self, parent, kind, period, selected, cutoff, available=(), cycles=(), chronological_start=None):
        super().__init__(parent)
        self.setObjectName('reportCalendarPage')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.kind=kind;self.period=period;self.selected=selected;self.cutoff=cutoff
        self.available=frozenset(available);self.cycles={c['id']:c for c in cycles}
        self.available_periods={date_bounds(period,day)[0] for day in self.available}
        self.coverage={key:quota_days(c) for key,c in self.cycles.items()}
        self.reset_days={moment.date() for c in cycles for moment in quota_span(c)}
        self.cycle_order={key:index for index,key in enumerate(self.cycles)}
        self.shared=()
        self.natural=kind=='quota'
        self.year_grid=period==MONTH and not self.natural
        self.current=(next((key for key,c in self.cycles.items() if not c.get('closed')),next(iter(self.cycles),None)) if self.natural else
                      max(self.available_periods,default=date_bounds(period,cutoff)[0]) if kind=='models' else date_bounds(period,cutoff)[0])
        self.earliest=(min((first for first,_ in self.coverage.values()),default=cutoff) if self.natural else
                       (chronological_start or min(self.available,default=cutoff)))
        self.latest=max((last for _,last in self.coverage.values()),default=cutoff) if self.natural else cutoff
        self.pixels=round;self.scale_value=10000
        self.cursor=self.anchor(selected).replace(day=1)
        self._grid_key=None;self.buttons={}
        set_theme_style(self,'QWidget#reportCalendarPage{background:#fcfafc;border-radius:17px;}')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        base=QVBoxLayout(self);base.setContentsMargins(0,0,0,0);base.setSpacing(0)
        scroll=hide_scrollbars(QScrollArea(self));scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setObjectName('reportCalendarScroll')
        scroll.setStyleSheet('QScrollArea#reportCalendarScroll{background:transparent;border:0;}')
        scroll.viewport().setAutoFillBackground(False)
        base.addWidget(scroll)
        body=QWidget();column=self.column=QVBoxLayout(body);column.setContentsMargins(13,8,13,10);column.setSpacing(5)
        self._compact_height=False
        header=control('‹ '+{'quota':'额度','models':'模型','projects':'成本'}[kind],self.cancelled.emit)
        header.setFixedWidth(48);header.setAccessibleName('返回');header.setObjectName('report_calendar_back')
        title='额度周期' if self.natural else {MONTH:'选择月份',WEEK:'选择一周',DAY:'选择日期'}[period]
        top=QHBoxLayout();top.addWidget(header);top.addStretch()
        self.compact_title=caption(title,12,True);self.compact_title.setAccessibleName(title)
        self.compact_title.hide();top.addWidget(self.compact_title)
        column.addLayout(top)
        self.page_title=caption(title,20,True);column.addWidget(self.page_title)
        self.range=caption('',14,True);self.range.setFixedHeight(24);column.addWidget(self.range)
        self.switch=ChoiceCombo();self.switch.setFixedHeight(24);self.switch.setMinimumHeight(24);self.switch.setAccessibleName('选择重置日的额度周期')
        self.switch.currentIndexChanged.connect(self._switch);column.addWidget(self.switch)
        self.note=caption();self.note.setFixedHeight(16);column.addWidget(self.note)
        nav=QHBoxLayout();nav.setSpacing(4)
        self.previous=control('‹',lambda:self.browse(-1));self.next=control('›',lambda:self.browse(1))
        self.previous.setAccessibleName('上一年' if self.year_grid else '上个月');self.next.setAccessibleName('下一年' if self.year_grid else '下个月')
        self.previous.setFixedWidth(28);self.next.setFixedWidth(28)
        self.heading=caption('',15,True);self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self.previous);nav.addWidget(self.heading,1);nav.addWidget(self.next);column.addLayout(nav)
        self.grid=QWidget();self.grid.setObjectName('reportCalendarGrid');self.grid.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        set_theme_style(self.grid,'QWidget#reportCalendarGrid{background:#f5f0f8;border-radius:9px;}')
        self.cells=QGridLayout(self.grid);self.cells.setContentsMargins(4,4,4,4);self.cells.setSpacing(0)
        for n in range(4 if self.year_grid else 7):self.cells.setColumnStretch(n,1)
        column.addWidget(self.grid)
        legend=QHBoxLayout();legend.setSpacing(4)
        dot=QWidget();dot.setFixedSize(6,6)
        set_theme_style(dot,'background:#8b78a6;border-radius:3px;')
        legend.addWidget(dot);legend.addWidget(caption('重置日' if self.natural else '有用量'))
        if self.natural:
            legend.addSpacing(6)
            band=QWidget();band.setFixedSize(12,5)
            set_theme_style(band,'background:#dacbe8;border-radius:2px;')
            legend.addWidget(band);legend.addWidget(caption('周期'))
        legend.addStretch(1);column.addLayout(legend)
        column.addStretch(1)
        footer=QWidget(self)
        actions=QHBoxLayout(footer);actions.setContentsMargins(13,5,13,9);actions.setSpacing(6)
        self.jump=control('本轮' if self.natural else {MONTH:'本月',WEEK:'本周',DAY:'昨日'}[period],self.jump_current)
        self.apply=control('查看周期' if self.natural else '应用筛选',lambda:self.accepted.emit(self.selected),True)
        self.jump.setObjectName('calendarFooterAction');self.apply.setObjectName('calendarFooterAction')
        actions.addWidget(self.jump,1);actions.addWidget(self.apply,2)
        base.addWidget(footer)
        scroll.setWidget(body)
        # QScrollArea enables auto-fill on the inserted widget. Its Window
        # palette would replace the themed calendar surface with system gray.
        body.setAutoFillBackground(False)
        self.build()

    def anchor(self,value):
        return self.coverage[value][0] if self.natural else value

    def browse(self,step):
        month=self.cursor.year*12+self.cursor.month-1+step*(12 if self.year_grid else 1)
        self.cursor=date(month//12,month%12+1,1);self.shared=();self.build()

    def jump_current(self):
        if self.current is None:return
        self.selected=self.current;self.cursor=self.anchor(self.selected).replace(day=1);self.shared=();self.build()

    def _switch(self,index):
        if index<0:return
        self.selected=self.switch.itemData(index);self.build()

    def choose(self,day):
        if self.natural:
            self.shared=tuple(key for key,(first,last) in self.coverage.items() if first<=day<=last)
            if self.selected not in self.shared:self.selected=self.shared[0]
        else:self.selected=date_bounds(self.period,day)[0]
        self.build()
        if len(self.shared)>1:self.switch.setFocus()
        elif day in self.buttons:self.buttons[day].setFocus()

    def build(self):
        cursor=self.cursor
        key=(lambda day:day.year) if self.year_grid else (lambda day:(day.year,day.month))
        self.previous.setEnabled(key(cursor)>key(self.earliest));self.next.setEnabled(key(cursor)<key(self.latest))
        self.heading.setText(f'{cursor.year} 年'+('' if self.year_grid else f' {cursor.month} 月'))
        overlap=len(self.shared)>1
        self.switch.blockSignals(True);self.switch.clear()
        for key_ in self.shared:self.switch.addItem(quota_text(self.cycles[key_]),key_)
        self.switch.setCurrentIndex(self.switch.findData(self.selected));self.switch.blockSignals(False)
        self.switch.setVisible(overlap)
        if self.natural:
            cycle=self.cycles[self.selected]
            self.range.setText(quota_text(cycle))
            state='已结束' if cycle.get('closed') else '进行中，结束时间为预计重置' if (cycle.get('reset_at') or 0)>cycle['start'] else '进行中，尚无重置时间'
            self.note.setText('重置日有两轮，请选择时间' if overlap else state)
        else:
            bounds=date_bounds(self.period,self.selected)
            self.range.setText(period_text(self.period,bounds,cost=self.kind=='projects',full=True))
            self.note.setText(f'统计至 {self.cutoff.month}/{self.cutoff.day}' if bounds[-1]>self.cutoff else '')
            self.jump.setText('最近有用量' if self.kind=='models' and self.current!=date_bounds(self.period,self.cutoff)[0] else {MONTH:'本月',WEEK:'本周',DAY:'昨日'}[self.period])
        self.note.setVisible(bool(self.note.text()))
        self.range.setVisible(not overlap and not self._compact_height)
        self.compact_title.setText(self.page_title.text() if overlap else self.range.text())
        grid_key=key(cursor);rebuild=grid_key!=self._grid_key
        if rebuild:
            self._grid_key=grid_key
            while self.cells.count():
                widget=self.cells.takeAt(0).widget()
                if widget:widget.hide();widget.deleteLater()
            self.buttons.clear()
        if self.year_grid:
            for month in range(1,13):
                day=date(cursor.year,month,1)
                marked=day in self.available_periods
                selected=day==self.selected
                self.add_cell(day,f'{month}月',(month-1)//4,(month-1)%4,marked,selected,enabled=marked,circle=selected)
            self.cells.activate()
            return
        if rebuild:
            for i,day in enumerate('一二三四五六日'):
                label=caption(day);label.setFixedHeight(19);label.setAlignment(Qt.AlignmentFlag.AlignCenter);self.cells.addWidget(label,0,i);label.show()
        last_day=monthrange(cursor.year,cursor.month)[1];offset=cursor.weekday()
        month_end=cursor.replace(day=last_day)
        for i in range(42):
            daynum=i-offset+1
            row,col=1+i//7,i%7
            if not 1<=daynum<=last_day:
                if rebuild:
                    space=QWidget();space.setFixedHeight(self.pixels(29));self.cells.addWidget(space,row,col);space.show()
                continue
            day=cursor.replace(day=daynum)
            if self.natural:
                keys=[key_ for key_,(first,last) in self.coverage.items() if first<=day<=last]
                selected=self.selected in keys;active=self.selected if selected else (keys[0] if keys else None)
                first,last=self.coverage.get(active,(day,day))
                marker=day in self.reset_days
                self.add_cell(day,str(daynum),row,col,marker,selected,enabled=bool(keys),band=bool(active),
                              first=col==0 or day in (first,cursor),last=col==6 or day in (last,month_end),
                              circle=selected and marker,future=day>self.cutoff,alternate=bool(keys and self.cycle_order[active]%2),shared=len(keys)>1)
            else:
                start,_=date_bounds(self.period,day);selected=self.selected==start
                enabled=start in self.available_periods
                self.add_cell(day,str(daynum),row,col,day in self.available,selected,enabled=enabled,
                              band=selected and self.period==WEEK,first=col==0 or day==cursor,
                              last=col==6 or day==month_end,circle=selected and self.period==DAY,future=day>self.cutoff)
        self.cells.activate()

    def add_cell(self,day,text,row,column,marker,selected,enabled,**appearance):
        existing=self.buttons.get(day)
        if existing is not None:
            existing.set_appearance(day,marker,selected,**appearance)
            existing.setEnabled(enabled)
            return
        cell=CalendarCell(self.grid,day,text,marker=marker,selected=selected,**appearance)
        cell.set_surface_scale(self.pixels)
        cell.setEnabled(enabled);cell.clicked.connect(lambda checked=False,value=day:self.choose(value))
        self.buttons[day]=cell;self.cells.addWidget(cell,row,column);cell.show()

    def set_surface_scale(self,pixels):
        value=pixels(10000)
        if self.scale_value==value:return
        self.pixels=pixels;self.scale_value=value
        for i in range(self.cells.count()):
            widget=self.cells.itemAt(i).widget()
            if isinstance(widget,CalendarCell):widget.set_surface_scale(pixels)
            elif not isinstance(widget,QLabel):widget.setFixedHeight(pixels(29))
        self.cells.activate()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.cancelled.emit();event.accept();return
        super().keyPressEvent(event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        compact=event.size().height()<220
        if compact==self._compact_height:return
        self._compact_height=compact
        self.page_title.setVisible(not compact)
        self.compact_title.setVisible(compact)
        self.range.setVisible(not compact and len(self.shared)<=1)
        self.column.setSpacing(3 if compact else 5)
        self.column.removeWidget(self.note)
        self.column.insertWidget(self.column.count()-1 if compact else 4,self.note)
