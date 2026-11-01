"""Compact project costs with local search and stable scrolling and local detail navigation."""
from PySide6.QtCore import Qt,Signal,QRectF,QSize,QTimer,QEasingCurve,QAbstractAnimation,QPropertyAnimation,QObject,QEvent,QPointF
from PySide6.QtGui import QPainter,QFontMetrics,QPen,QColor,QWheelEvent
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QLabel,QToolButton,QSizePolicy,QListWidget,QListWidgetItem,QStyledItemDelegate,QStyle,QScrollArea,QStackedWidget,QFrame,QApplication,QAbstractScrollArea
from compact_bubble import font,FONT_CSS
from theme_registry import color
from theme_runtime import set_theme_style
from settings_controls import SlidingSegments,motion_enabled
from data_page_motion import PageFade
from token_calendar import compact_tokens
from project_cost import search_rows,PRICE_SOURCE

def dollars(n):return '—' if n is None else '<$0.01' if 0<n<.01 else f'${n:,.2f}'

def estimated(cost,tokens,pending):return dollars(None if pending and pending>=tokens else cost)

class ExplanationOverlay(QWidget):
    """Local, fixed-size explanation view; never resizes the report window."""
    def __init__(self,parent,title,paragraphs):
        super().__init__(parent);self.setObjectName('explanationOverlay')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        set_theme_style(self,'QWidget#explanationOverlay{background:#fcfafc;}QLabel{'+FONT_CSS+'font-size:12px;color:#706879;background:transparent;}QToolButton{'+FONT_CSS+'font-size:12px;color:#75618d;border:0;background:transparent;text-align:left;}')
        layout=QVBoxLayout(self);layout.setContentsMargins(3,3,3,3);layout.setSpacing(10)
        self.back=QToolButton();self.back.setText('‹ 返回');self.back.setFixedHeight(27);self.back.clicked.connect(self.close);layout.addWidget(self.back)
        area=QScrollArea();area.setWidgetResizable(True)
        from ui_theme import hide_scrollbars
        hide_scrollbars(area);set_theme_style(area,'QScrollArea{border:0;background:transparent;}');body=QWidget();body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True);set_theme_style(body,'background:#fcfafc;');content=QVBoxLayout(body);content.setContentsMargins(3,0,3,0);content.setSpacing(12)
        heading=QLabel(title);set_theme_style(heading,FONT_CSS+'font-size:14px;font-weight:600;color:#393343;background:transparent;');content.addWidget(heading)
        for text in paragraphs:
            label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);label.setMinimumWidth(0);content.addWidget(label)
        content.addStretch();area.setWidget(body);layout.addWidget(area)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);parent.installEventFilter(self);self.setGeometry(parent.rect());self.show();self.raise_();self.setFocus()
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.close();event.accept();return
        super().keyPressEvent(event)
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor(color('#fcfafc')))
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Resize:self.setGeometry(obj.rect())
        elif event.type()==QEvent.Type.Hide:self.close()
        return False

class SearchButton(QToolButton):
    def paintEvent(self,event):
        super().paintEvent(event)
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(color('#75618d' if self.underMouse() else '#706879')),1.5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        cx=self.width()/2;cy=self.height()/2
        p.drawEllipse(QRectF(cx-5,cy-5,7,7));p.drawLine(round(cx+1),round(cy+1),round(cx+5),round(cy+5))

class ProjectSearchBar(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumWidth(0);self.setFixedHeight(27)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(1)
        self.edit=QLineEdit();self.edit.setMinimumWidth(0);self.edit.setPlaceholderText('项目或目录');self.edit.setAccessibleName('搜索项目名或目录');self.edit.setClearButtonEnabled(True);self.edit.setFixedHeight(27)
        set_theme_style(self.edit,'QLineEdit{'+FONT_CSS+'font-size:12px;color:#393343;background:#f5f0f8;border:0;border-radius:6px;padding:3px 5px;}QLineEdit:focus{background:#eae1f2;}')
        row.addWidget(self.edit,1);self.button=SearchButton(self);self.button.setFixedSize(25,27);self.button.setAccessibleName('搜索项目');self.button.setProperty('headerActionHint','搜索');self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(self.button,'QToolButton{background:transparent;border:0;border-radius:6px;}QToolButton:hover{background:#eae1f2;}QToolButton:pressed{background:#e0d3eb;}');self.button.hide()

class CostSummary(QLabel):
    def paintEvent(self,event):
        p=QPainter(self);self.draw(p,self.rect(),self.text())
    @staticmethod
    def draw(p,rect,text):
        if not text:return
        title,_,amount=text.split('\n')[0].rpartition('  ')
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#f5f0f8')));p.drawRoundedRect(QRectF(rect),9,9)
        p.setFont(font(12));p.setPen(QColor(color('#706879')));p.drawText(8,18,title+' (USD)')
        p.setFont(font(22,True));p.setPen(QColor(color('#393343')));p.drawText(8,44,amount)
        p.setFont(font(12));p.setPen(QColor(color('#706879')))
        for i,line in enumerate(text.split('\n')[1:]):
            p.drawText(8,64+i*17,QFontMetrics(p.font()).elidedText(line,Qt.TextElideMode.ElideRight,rect.width()-16))

class DailyCostButton(QToolButton):
    def __init__(self,parent=None):
        super().__init__(parent);self.tokens=0;self.amount=None;self.partial=False;self.setFixedHeight(47)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.setAccessibleName('查看昨日项目成本');self.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(self,'QToolButton{border:0;background:transparent;}')
    def set_data(self,report,projects):
        projects=projects or {};rows=projects.get('ranges',{}).get('yesterday',[])
        valid=projects.get('yesterday')==report.get('day') and 'yesterday' in projects.get('ranges',{})
        tokens=sum(p['tokens'] for p in rows);pending=sum(p['pending_tokens'] for p in rows)
        self.tokens=report.get('yesterday_total',0)
        self.partial=bool(pending or projects.get('limited') or projects.get('errors') or projects.get('pending'))
        self.amount=sum(p['cost'] for p in rows) if valid and not (pending and pending>=tokens) and (rows or not self.tokens) else None
        self.setAccessibleName('查看昨日项目成本 '+dollars(self.amount));self.update()
    def paintEvent(self,event):
        p=QPainter(self);half=self.width()/2
        p.setPen(QColor(color('#706879')));p.setFont(font(12));p.drawText(0,14,'Token 用量')
        p.setPen(QColor(color('#75618d')));p.drawText(round(half+5),14,'成本（部分） ›' if self.partial else '成本估算 ›')
        p.setPen(QColor(color('#393343')));p.setFont(font(20,True));p.drawText(0,40,compact_tokens(self.tokens));p.drawText(round(half+5),40,dollars(self.amount))
    def mouseReleaseEvent(self,event):
        if event.position().x()<self.width()/2:self.setDown(False);event.accept();return
        super().mouseReleaseEvent(event)

class FeeStrip(QWidget):
    def __init__(self,parts):
        super().__init__();self.parts=parts;self.setFixedHeight(7)
    def paintEvent(self,event):
        from theme_registry import chart_color
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);x=0.;total=sum(self.parts)
        for i,value in enumerate(self.parts):
            if not total:break
            width=self.width()*value/total
            p.fillRect(QRectF(x,1,max(0,width-2),5),QColor(chart_color(i)));x+=width

class SmoothCostScroll(QObject):
    """Animate mouse-wheel steps only; preserve native touchpad pixel deltas."""
    def __init__(self,area):
        super().__init__(area);self.area=area;self.bar=area.verticalScrollBar()
        self.animation=QPropertyAnimation(self.bar,b'value',self);self.animation.setDuration(160)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.target=0
        area.viewport().installEventFilter(self)
        self.bar.sliderPressed.connect(self.animation.stop)
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Hide:self.animation.stop();return False
        if event.type()!=QEvent.Type.Wheel:return False
        if event.pixelDelta().y():self.animation.stop()
        delta=event.pixelDelta().y() or event.angleDelta().y()
        at_edge=(delta>0 and self.bar.value()<=self.bar.minimum()) or (delta<0 and self.bar.value()>=self.bar.maximum())
        if delta and at_edge and self.animation.state()!=QAbstractAnimation.State.Running:
            # The inner list/detail gets first refusal. Only a reached edge
            # hands the same gesture to the ancestor viewport, exactly once.
            parent=self.area.parentWidget()
            while parent:
                if isinstance(parent,QAbstractScrollArea):
                    target=parent.viewport();local=QPointF(target.mapFromGlobal(event.globalPosition().toPoint()))
                    forwarded=QWheelEvent(local,event.globalPosition(),event.pixelDelta(),event.angleDelta(),event.buttons(),event.modifiers(),event.phase(),event.inverted(),event.source())
                    QApplication.sendEvent(target,forwarded)
                    if forwarded.isAccepted():event.accept();return True
                    break
                parent=parent.parentWidget()
        if event.pixelDelta().y() or not motion_enabled():self.animation.stop();return False
        delta=event.angleDelta().y()
        if not delta:return False
        current=self.bar.value();running=self.animation.state()==QAbstractAnimation.State.Running
        target=max(self.bar.minimum(),min(self.bar.maximum(),(self.target if running else current)-round(delta/120*60)))
        if target==current and not running:return False
        self.animation.stop();self.target=target
        self.animation.setStartValue(current);self.animation.setEndValue(target);self.animation.start()
        event.accept();return True


class CostDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        data=index.data(Qt.ItemDataRole.UserRole) or {}
        return QSize(100,98 if '_summary' in data else 82 if data.get('duplicate') else 64)
    def paint(self,p,option,index):
        item=index.data(Qt.ItemDataRole.UserRole)
        if not item:return
        p.save();p.translate(option.rect.topLeft());r=QRectF(0,0,option.rect.width(),option.rect.height()-4)
        if '_summary' in item:CostSummary.draw(p,r.toRect(),item['_summary']);p.restore();return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state&QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#f5f0f8')));p.drawRoundedRect(r,7,7)
        amount=estimated(item['cost'],item['tokens'],item['pending_tokens'])
        p.setFont(font(14,True));p.setPen(QColor(color('#393343')));aw=QFontMetrics(p.font()).horizontalAdvance(amount)+6
        p.drawText(r.adjusted(7,4,-7,0),Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignRight,amount)
        p.drawText(7,20,QFontMetrics(p.font()).elidedText(item['name'],Qt.TextElideMode.ElideRight,max(8,int(r.width())-aw-21)))
        p.setFont(font(12));p.setPen(QColor(color('#706879')));y=39
        if item.get('duplicate'):
            p.drawText(7,y,QFontMetrics(p.font()).elidedText(item['path'],Qt.TextElideMode.ElideMiddle,int(r.width())-14));y+=18
        p.drawText(7,y,compact_tokens(item['tokens'])+' Token')
        p.drawText(r.adjusted(7,y-14,-7,0),Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignRight,str(item['sessions'])+' 会话')
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#f5f0f8')));p.drawRoundedRect(QRectF(7,y+9,r.width()-14,3),1.5,1.5)
        p.setBrush(QColor(color('#8b78a6')));p.drawRoundedRect(QRectF(7,y+9,(r.width()-14)*item.get('share',0),3),1.5,1.5);p.restore()

class ProjectCosts(QWidget):
    changed=Signal()
    def __init__(self,parent=None,search_bar=None):
        super().__init__(parent);self.data={};self.period='all';self.archive='active';self.selected=None;self._detail_key=None
        self.setMinimumWidth(0);self.setMinimumHeight(230)
        body=QVBoxLayout(self);body.setContentsMargins(0,0,0,0);body.setSpacing(5)
        self._external_search=search_bar is not None
        self.search_bar=search_bar if search_bar is not None else ProjectSearchBar(self)
        self.search=self.search_bar.edit;self.search_button=self.search_bar.button
        if search_bar is None:body.addWidget(self.search_bar)
        self.archive_control=SlidingSegments([('未归档','active'),('已归档','archived'),('全部','all')],compact=True);body.addWidget(self.archive_control)
        self.back=QToolButton();self.back.setText('‹ 返回项目');self.back.setFixedHeight(26)
        set_theme_style(self.back,'QToolButton{'+FONT_CSS+'font-size:12px;color:#514360;background:transparent;border:0;text-align:left;}QToolButton:hover{background:#eae1f2;border-radius:5px;}')
        self.back.clicked.connect(lambda:self.select(None));body.addWidget(self.back);self.back.hide()
        self.summary=CostSummary(self);self.summary.hide();self._row_ids=[]
        self.stack=QStackedWidget();body.addWidget(self.stack,1)
        self.info_button=QToolButton();self.info_button.setText('估算说明  ›');self.info_button.setFixedHeight(24)
        set_theme_style(self.info_button,'QToolButton{'+FONT_CSS+'font-size:12px;color:#75618d;border:0;background:transparent;text-align:left;}')
        self.info_button.clicked.connect(self.show_info);body.addWidget(self.info_button)
        self.list=QListWidget();self.list.setMouseTracking(True);self.list.setItemDelegate(CostDelegate(self.list));self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel);self.list.setMinimumSize(0,0);self.stack.addWidget(self.list)
        self.details=QScrollArea();self.details.setWidgetResizable(True);self.details.setMinimumSize(0,0);self.details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn);self.stack.addWidget(self.details)
        self.empty=self.label('');self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty.setWordWrap(True);self.stack.addWidget(self.empty)
        style='QListWidget,QScrollArea{background:transparent;border:0;outline:0;}QListWidget::item{border:0;}QScrollBar:vertical{background:transparent;width:6px;margin:2px 0 2px 1px;border-radius:2px;}QScrollBar::handle:vertical{background:#e4dfea;min-height:30px;border-radius:2px;}QScrollBar::handle:vertical:hover{background:#8b78a6;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}'
        set_theme_style(self.list,style);set_theme_style(self.details,style)
        self.list_scroll=SmoothCostScroll(self.list);self.detail_scroll=SmoothCostScroll(self.details)
        self.search.textChanged.connect(self.filter_changed);self.search.returnPressed.connect(self.filter_changed);self.search_button.clicked.connect(self.filter_changed);self.archive_control.currentIndexChanged.connect(self.archive_changed)
        self.list.itemClicked.connect(lambda item:self.select(item.data(Qt.ItemDataRole.UserRole)) if '_summary' not in item.data(Qt.ItemDataRole.UserRole) else None)
        self.list.itemActivated.connect(lambda item:self.select(item.data(Qt.ItemDataRole.UserRole)) if '_summary' not in item.data(Qt.ItemDataRole.UserRole) else None)
        self.detail_motion=PageFade(self);self._detail_transition=0
        self.refresh()
    def label(self,text,strong=False):
        w=QLabel(text);w.setTextFormat(Qt.TextFormat.PlainText);w.setWordWrap(True);w.setMinimumWidth(0);w.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        set_theme_style(w,FONT_CSS+'font-size:12px;font-weight:'+('600' if strong else '400')+';color:'+('#393343' if strong else '#706879')+';background:transparent;');return w
    def card(self,layout,title):
        w=QFrame();w.setObjectName('costSection');set_theme_style(w,'QFrame#costSection{background:#f5f0f8;border-radius:8px;}')
        box=QVBoxLayout(w);box.setContentsMargins(8,7,8,7);box.setSpacing(6);heading=self.label(title,True);set_theme_style(heading,FONT_CSS+'font-size:12px;font-weight:500;color:#75618d;background:transparent;');box.addWidget(heading);layout.addWidget(w);return box
    def detail_body(self,p):
        body=QWidget();set_theme_style(body,'background:transparent;');layout=QVBoxLayout(body);layout.setContentsMargins(0,0,5,0);layout.setSpacing(7)
        box=QVBoxLayout();layout.addLayout(box);box.addWidget(self.label(p['name'],True));box.addWidget(self.label(p['path'] or '目录未识别'))
        box.addWidget(self.label('API 等价估算 (USD)'))
        value=self.label(estimated(p['cost'],p['tokens'],p['pending_tokens']),True);set_theme_style(value,FONT_CSS+'font-size:22px;font-weight:600;color:#393343;background:transparent;');box.addWidget(value)
        metrics=QHBoxLayout();metrics.setSpacing(12)
        for value,title in ((compact_tokens(p['tokens']),'Token'),(str(p['sessions']),'会话')):
            metrics.addWidget(self.label(value+' '+title),1)
        box.addLayout(metrics)
        box=self.card(layout,'费用构成')
        box.addWidget(FeeStrip(p['parts']))
        for label,value in zip(('非缓存输入','缓存输入','输出（含推理）'),p['parts']):
            row=QHBoxLayout();row.addWidget(self.label(label),1);amount=self.label(dollars(None if p['pending_tokens']>=p['tokens'] and p['pending_tokens'] else value),True);amount.setAlignment(Qt.AlignmentFlag.AlignRight);row.addWidget(amount,1);box.addLayout(row)
        if p['pending_tokens']:box.addWidget(self.label(compact_tokens(p['pending_tokens'])+' Token 待定价'))
        box=self.card(layout,'模型用量')
        models=p.get('model_usage') or [dict(model=m,tokens=None,cost=None,pending_tokens=0) for m in p['models']]
        for item in models:
            model_name=self.label(item['model']);set_theme_style(model_name,FONT_CSS+'font-size:12px;font-weight:500;color:#75618d;background:transparent;');box.addWidget(model_name)
            if item['tokens'] is not None:
                text=compact_tokens(item['tokens'])+' Token  '+(estimated(item['cost'],item['tokens'],item['pending_tokens']))
                box.addWidget(self.label(text,True))
        note='按当前标准短上下文API单价折算，非订阅账单。'
        if self.data.get('pending'):note+=' 历史记录仍在整理。' if self.data.get('initial_pending',True) else ' 正在同步新增记录。'
        layout.addStretch();return body
    def show_info(self):
        if getattr(self,'explanation',None):self.explanation.close()
        self.explanation=ExplanationOverlay(self,'金额怎么估算',[
            '按本机记录的 Token 折算成 API 等价金额，单位为美元。它不是 Plus 或 Pro 订阅账单。',
            '非缓存输入 × 输入价\n＋ 缓存输入 × 缓存价\n＋ 输出 × 输出价',
            '推理已包含在输出中。未知模型、价格或计数不完整的部分标为待定价，不当作零元。',
            '昨日按本地时间 00:00–24:00 统计。项目跟随当前会话归属，迁移不重复累计历史用量。',
            '正在整理历史记录。' if self.data.get('initial_pending') else '正在同步新增记录。' if self.data.get('pending') else '按已读取记录估算，其他设备的用量可能不完整。'])
        self.explanation.destroyed.connect(lambda:setattr(self,'explanation',None))
    def set_data(self,data,period):self.data=data or {};self.period=period;self.refresh()
    def reset_navigation(self):
        """Fresh entry starts at the list's top; in-visit Back keeps its position."""
        self._detail_transition+=1;self.detail_motion.clear()
        self.list_scroll.animation.stop();self.detail_scroll.animation.stop()
        self.list.verticalScrollBar().setValue(0);self.details.verticalScrollBar().setValue(0);self._detail_key=None
        if self.selected is not None:self.selected=None;self.refresh()
    def filter_changed(self):
        self.list_scroll.animation.stop();self.detail_scroll.animation.stop()
        self._detail_transition+=1;self.detail_motion.clear();self.selected=None;self.list.verticalScrollBar().setValue(0);self.refresh()
    def archive_changed(self,index):self.archive=self.archive_control.currentData();self.filter_changed()
    def select(self,item):
        target=item['id'] if item else None
        if target==self.selected:return
        self.list_scroll.animation.stop();self.detail_scroll.animation.stop()
        entering=target is not None;outer=self.window()
        busy=getattr(outer,'_animating',False) or bool(getattr(getattr(outer,'follow',None),'active',False))
        outer_motion=getattr(outer,'page_fade',None)
        busy=busy or bool(outer_motion and outer_motion.animation.state()==QAbstractAnimation.State.Running)
        frame=None
        if self.isVisible() and not busy and motion_enabled():
            frame=self.detail_motion.current_frame() if self.detail_motion.isVisible() else PageFade.snapshot(self)
        self._detail_transition+=1;ticket=self._detail_transition
        if frame is not None:self.detail_motion.hold(frame,self.rect())
        self.selected=target;self.refresh()
        if entering:
            self.details.verticalScrollBar().setValue(0)
            QTimer.singleShot(0,self,lambda:self._reset_detail_entry(ticket,target))
        if frame is not None:QTimer.singleShot(0,self,lambda:self._present_detail(ticket,frame,entering))
        else:self.detail_motion.clear()
    def _reset_detail_entry(self,ticket,target):
        if ticket==self._detail_transition and self.selected==target:
            self.details.verticalScrollBar().setValue(0)
    def _present_detail(self,ticket,frame,entering):
        if ticket!=self._detail_transition:return
        if not self.isVisible() or not self.updatesEnabled() or not motion_enabled():
            self.detail_motion.clear();return
        try:
            # QWidget.render skips descendants while updates are disabled.
            # This is one synchronous callback: settle only the visible target
            # subtree, capture it, and restore the overlay before queued paints.
            # Do not pump events or thaw a parent-owned window transition.
            from panel_transition import settle_visible
            self.detail_motion.hide();settle_visible(self)
            if ticket!=self._detail_transition:
                self.detail_motion.clear();return
            target=PageFade.snapshot(self)
            self.detail_motion.animation.setDuration(250 if entering else 200)
            self.detail_motion.animation.setEasingCurve(QEasingCurve.Type.OutCubic if entering else QEasingCurve.Type.InCubic)
            self.detail_motion.present(frame,target,self.rect(),direction=1 if entering else -1)
        except Exception:
            # A failed snapshot must leave the live target usable, rather than
            # retaining an old cover or leaving the subtree permanently frozen.
            self.detail_motion.clear();raise
    def hideEvent(self,event):
        self._detail_transition+=1;self.detail_motion.clear();super().hideEvent(event)
    def resizeEvent(self,event):
        if hasattr(self,'detail_motion'):
            self._detail_transition+=1;self.detail_motion.clear()
        super().resizeEvent(event)
    def refresh(self):
        rows=search_rows(self.data,self.period,self.search.text(),self.archive)
        selected=next((p for p in rows if p['id']==self.selected),None)
        if self.selected is not None and selected is None:self.selected=None
        if not self._external_search:self.search_bar.setVisible(not selected)
        self.archive_control.setVisible(not selected);self.back.setVisible(bool(selected))
        ids=[p['id'] for p in rows]
        name_counts={}
        for p in rows:name_counts[p['name']]=name_counts.get(p['name'],0)+1
        if self._row_ids!=ids or not self.list.count():
            self.list_scroll.animation.stop()
            position=self.list.verticalScrollBar().value()
            self.list.clear()
            header=QListWidgetItem();header.setData(Qt.ItemDataRole.UserRole,{'_summary':''});header.setFlags(Qt.ItemFlag.NoItemFlags);self.list.addItem(header)
            for p in rows:self.list.addItem(QListWidgetItem())
            self._row_ids=ids;self.list.verticalScrollBar().setValue(position)
        cost=sum(p['cost'] for p in rows);tokens=sum(p['tokens'] for p in rows);unknown=sum(p['pending_tokens'] for p in rows)
        for i,p in enumerate(rows):
            item=dict(p,share=p['cost']/max(1e-12,cost),duplicate=name_counts[p['name']]>1)
            if self.list.item(i+1).data(Qt.ItemDataRole.UserRole)!=item:self.list.item(i+1).setData(Qt.ItemDataRole.UserRole,item)
        if selected:
            cost=selected['cost'];tokens=selected['tokens'];unknown=selected['pending_tokens']
            key=(selected,self.data.get('pending'),self.data.get('initial_pending'))
            if key!=self._detail_key:
                position=self.details.verticalScrollBar().value();old=self.details.takeWidget()
                self.details.setWidget(self.detail_body(selected));self.details.verticalScrollBar().setValue(position if self._detail_key and self._detail_key[0]['id']==selected['id'] else 0)
                if old:old.deleteLater()
                self._detail_key=key
            self.stack.setCurrentWidget(self.details)
        elif rows:self.stack.setCurrentWidget(self.list)
        else:
            self.empty.setText('正在整理项目记录…' if self.data.get('pending') else '部分用量暂不能核对' if self.data.get('limited') or self.data.get('errors') else '没有匹配项目');self.stack.setCurrentWidget(self.empty)
        note=('已定价部分' if unknown else 'API 等价估算')+'  '+estimated(cost,tokens,unknown)+'\n'+compact_tokens(tokens)+' Token'
        if unknown:note+='\n'+compact_tokens(unknown)+' 待定价'
        elif self.data.get('pending'):note+='\n整理中' if self.data.get('initial_pending',True) else '  同步中'
        elif self.data.get('limited') or self.data.get('errors'):note+='  记录不完整'
        self.summary.setText(note if rows else ('记录不完整' if self.data.get('limited') or self.data.get('errors') else ''))
        header={'_summary':self.summary.text()}
        if self.list.item(0).data(Qt.ItemDataRole.UserRole)!=header:self.list.item(0).setData(Qt.ItemDataRole.UserRole,header)
        if self.detail_motion.slide and self.detail_motion.animation.state()==QAbstractAnimation.State.Running:
            enabled=self.updatesEnabled();self.setUpdatesEnabled(False)
            try:
                self.detail_motion.hide();self.detail_motion.next_frame=PageFade.snapshot(self);self.detail_motion.show()
            finally:self.setUpdatesEnabled(enabled)
        self.changed.emit()
