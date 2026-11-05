"""Compact project costs with local search and stable scrolling and local detail navigation."""
from PySide6.QtCore import Qt,Signal,QRectF,QSize,QTimer,QEasingCurve,QAbstractAnimation,QPropertyAnimation,QObject,QEvent,QPointF,QThread
from PySide6.QtGui import QPainter,QFontMetrics,QPen,QColor,QWheelEvent
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QLabel,QToolButton,QSizePolicy,QListWidget,QListWidgetItem,QStyledItemDelegate,QStyle,QScrollArea,QStackedWidget,QFrame,QApplication,QAbstractScrollArea,QMenu,QPushButton,QFileDialog,QMessageBox
from compact_bubble import font,FONT_CSS
from theme_registry import color
from theme_runtime import set_theme_style
from settings_controls import SlidingSegments,motion_enabled
from data_page_motion import PageFade
from token_calendar import compact_tokens
from project_cost import search_rows,PRICE_SOURCE

def dollars(n):
    from cost_preferences import money
    return money(n)

class DetailJob(QThread):
    ready=Signal(object);failed=Signal(str)
    def __init__(self,path,project,period,home=None,price_table=None):
        super().__init__(QApplication.instance());self.path=path;self.project=project;self.period=period;self.home=home
        self.price_table=None if price_table is None else dict(price_table)
        QApplication.instance().aboutToQuit.connect(self.stop_for_exit)
    def stop_for_exit(self):
        self.requestInterruption();self.wait(3000)
    def run(self):
        from cost_details import detail_snapshot
        try:
            result=detail_snapshot(self.path,self.project,self.period,cancel=self.isInterruptionRequested,home=self.home,price_table=self.price_table)
            if result is not None:self.ready.emit(result)
        except Exception as error:self.failed.emit('明细暂未取得，请稍后重试：'+str(error)[:100])

class TurnRow(QWidget):
    def __init__(self,turn):
        super().__init__();self.turn=turn;self.setFixedHeight(69);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.token_parts=[max(0,turn['input']-turn['cached']),turn['cached'],turn['output']] if turn.get('known',True) else [None,None,None]
        self.setAccessibleName('回合用量与费用');self.setAccessibleDescription('非缓存输入、缓存输入和输出用量直接显示')
    def paintEvent(self,event):
        from datetime import datetime
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);w=self.width()
        p.setFont(font(11));p.setPen(QColor(color('#706879')))
        stamp='未识别' if self.turn['unknown'] else datetime.fromtimestamp(self.turn['stamp']).strftime('%H:%M')
        p.drawText(2,16,stamp)
        amount=estimated(self.turn['cost'],self.turn['tokens'],self.turn['pending_tokens']);aw=QFontMetrics(font(12,True)).horizontalAdvance(amount)+4
        p.drawText(QRectF(43,1,max(0,w-aw-48),20),Qt.AlignmentFlag.AlignVCenter,QFontMetrics(p.font()).elidedText(' / '.join(self.turn['models']),Qt.TextElideMode.ElideRight,max(0,w-aw-48)))
        p.setFont(font(12,True));p.setPen(QColor(color('#75618d')));p.drawText(QRectF(w-aw,1,aw,20),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,amount)
        for i,(label,value) in enumerate(zip(('非缓存输入','缓存输入','输出'),self.token_parts)):
            align=Qt.AlignmentFlag.AlignLeft if i==0 else Qt.AlignmentFlag.AlignHCenter if i==1 else Qt.AlignmentFlag.AlignRight
            r=QRectF(i*w/3,28,w/3,16);p.setFont(font(11));p.setPen(QColor(color('#706879')));p.drawText(r,align|Qt.AlignmentFlag.AlignVCenter,label)
            p.setPen(QColor(color('#393343')));p.setFont(font(12));p.drawText(r.translated(0,17),align|Qt.AlignmentFlag.AlignVCenter,'—' if value is None else compact_tokens(value))
        p.setPen(QColor(color('#ded2e7')));p.drawLine(2,68,w-2,68)

class DetailSummary(QWidget):
    def __init__(self,data,session=False):
        super().__init__();self.data=data;self.session=session;self.setFixedHeight(62 if session else 94);self.setMinimumWidth(0)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);w=self.width();d=self.data
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#f5f0f8')));p.drawRoundedRect(QRectF(self.rect()),10,10)
        p.setPen(QColor(color('#393343')));p.setFont(font(12,True));p.drawText(9,20,QFontMetrics(p.font()).elidedText(d['name'],Qt.TextElideMode.ElideRight,w-18))
        if self.session:
            p.setFont(font(16,True));amount=dollars(d['cost']);aw=QFontMetrics(p.font()).horizontalAdvance(amount)
            p.setPen(QColor(color('#75618d')));p.drawText(QRectF(w-aw-9,30,aw,23),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,amount)
            text=(str(len(d['turns']))+' 回合 / ' if 'turns' in d else '')+compact_tokens(d['tokens'])+' Token'
            p.setFont(font(11));p.setPen(QColor(color('#706879')));p.drawText(QRectF(9,30,max(0,w-aw-25),23),Qt.AlignmentFlag.AlignVCenter,QFontMetrics(p.font()).elidedText(text,Qt.TextElideMode.ElideRight,max(0,w-aw-25)))
        else:
            p.setFont(font(22,True));p.drawText(9,50,estimated(d['cost'],d['tokens'],d['pending_tokens']))
            p.setFont(font(11));p.setPen(QColor(color('#706879')));p.drawText(9,77,compact_tokens(d['tokens'])+' Token');p.drawText(QRectF(110,61,w-119,22),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,str(d['sessions'])+' 会话')

class MetricLine(QWidget):
    def __init__(self,title,value):
        super().__init__();self.title=title;self.value=value;self.setFixedHeight(23);self.setMinimumWidth(0)
    def paintEvent(self,event):
        p=QPainter(self);p.setFont(font(12,True));right=str(self.value);width=QFontMetrics(p.font()).horizontalAdvance(right);p.setPen(QColor(color('#393343')))
        p.drawText(QRectF(max(0,self.width()-width),0,width,23),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,right)
        p.setFont(font(11));p.setPen(QColor(color('#706879')));p.drawText(QRectF(0,0,max(0,self.width()-width-10),23),Qt.AlignmentFlag.AlignVCenter,QFontMetrics(p.font()).elidedText(self.title,Qt.TextElideMode.ElideRight,max(0,self.width()-width-10)))

class CostMoreButton(QToolButton):
    def __init__(self,parent=None):
        super().__init__(parent);self.setFixedSize(22,23);self.setAccessibleName('更多成本操作');self.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(self,'QToolButton{background:transparent;border:0;border-radius:6px;}QToolButton:hover{background:#eae1f2;}')
    def paintEvent(self,event):
        super().paintEvent(event);p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#75618d')))
        for x in (6,11,16):p.drawEllipse(QRectF(x-1.4,10,2.8,2.8))

class SessionButton(QToolButton):
    def __init__(self,session):
        super().__init__();self.session=session;self.title=' '.join(str(session['name']).split());self.setAccessibleName(self.title);self.setAccessibleDescription('查看会话回合明细');self.setFixedHeight(71 if session.get('directory') else 57);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed);self.setMinimumWidth(0);self.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(self,'QToolButton{background:transparent;border:0;border-radius:7px;}QToolButton:hover{background:#f5f0f8;}')
    def paintEvent(self,event):
        super().paintEvent(event);p=QPainter(self);p.setFont(font(12,True));p.setPen(QColor(color('#393343')));amount=dollars(self.session['cost'])+' ›';aw=min(self.width()//2,QFontMetrics(p.font()).horizontalAdvance(amount)+4)
        self.title_rect=QRectF(8,5,max(8,self.width()-aw-23),21)
        p.drawText(self.title_rect,Qt.AlignmentFlag.AlignVCenter,QFontMetrics(p.font()).elidedText(self.title,Qt.TextElideMode.ElideRight,round(self.title_rect.width())))
        p.drawText(QRectF(self.width()-aw-8,5,aw,21),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,amount)
        p.setFont(font(11));p.setPen(QColor(color('#706879')));p.drawText(8,45,compact_tokens(self.session['tokens'])+' Token')
        directory=self.session.get('directory')
        if directory:p.drawText(8,61,QFontMetrics(p.font()).elidedText(directory,Qt.TextElideMode.ElideMiddle,max(0,self.width()-16)))

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
    def draw(p,rect,text,meta=None):
        if not text:return
        meta=meta or {};title,_,amount=text.split('\n')[0].rpartition('  ')
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#f5f0f8')));p.drawRoundedRect(QRectF(0,0,rect.width(),rect.height()+3),10,10)
        from cost_preferences import current
        p.setFont(font(11));p.setPen(QColor(color('#706879')));p.drawText(9,18,'API 等价估算');p.drawText(QRectF(100,3,rect.width()-109,20),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,current()['currency'])
        p.setFont(font(22,True));p.setPen(QColor(color('#393343')));p.drawText(9,44,amount)
        if meta.get('pending'):
            x=9+QFontMetrics(p.font()).horizontalAdvance(amount)+5;p.setFont(font(11));p.setPen(QColor(color('#706879')));p.drawText(x,43,'部分')
        p.setFont(font(11));p.setPen(QColor(color('#706879')));p.drawText(9,65,text.split('\n')[1] if len(text.split('\n'))>1 else '')
        p.drawText(QRectF(130,49,rect.width()-139,20),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,str(meta.get('projects',''))+' 个项目')
        def button(bounds,value):
            p.setPen(QPen(QColor(color('#ded2e7'))));p.setBrush(QColor(color('#fcfafc')))
            p.drawRoundedRect(bounds,5,5)
            p.setPen(QColor(color('#514360')));p.setFont(font(11,True))
            p.drawText(bounds,Qt.AlignmentFlag.AlignCenter,value)
        if meta.get('tokens'):
            p.setPen(QColor(color('#ded2e7')));p.drawLine(9,73,rect.width()-9,73)
            p.setPen(QColor(color('#393343')));p.setFont(font(11,True));p.drawText(9,92,'计价覆盖率')
            coverage=1-meta.get('pending',0)/meta['tokens']
            if meta.get('pending'):coverage=min(.999,coverage)
            button(QRectF(rect.width()-67,77,58,20),f'{coverage:.1%}  ›')
        p.setFont(font(12,True));p.setPen(QColor(color('#393343')));p.drawText(9,117,'项目')
        button(QRectF(rect.width()-93,101,84,20),'按名称  ↓' if meta.get('sort_name') else '成本降序  ↓')

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
        return QSize(100,124 if '_summary' in data else 82 if data.get('duplicate') else 64)
    def paint(self,p,option,index):
        item=index.data(Qt.ItemDataRole.UserRole)
        if not item:return
        p.save();p.translate(option.rect.topLeft());r=QRectF(0,0,option.rect.width(),option.rect.height()-4)
        if '_summary' in item:CostSummary.draw(p,r.toRect(),item['_summary'],item);p.restore();return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state&QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(color('#f5f0f8')));p.drawRoundedRect(r,7,7)
        amount=estimated(item['cost'],item['tokens'],item['pending_tokens'])
        p.setFont(font(16,True));p.setPen(QColor(color('#75618d')));aw=QFontMetrics(p.font()).horizontalAdvance(amount)+6
        p.drawText(r.adjusted(7,4,-7,0),Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignRight,amount)
        p.setFont(font(12,True));p.setPen(QColor(color('#393343')));p.drawText(7,20,QFontMetrics(p.font()).elidedText(item['name'],Qt.TextElideMode.ElideRight,max(8,int(r.width())-aw-21)))
        p.setFont(font(11));p.setPen(QColor(color('#706879')));y=39
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
        self.session_rows=None;self.session=None;self.detail_job=None;self.detail_ticket=0;self._sessions_key=None;self.session_order='time';self.session_position=0
        self.turn_error=''
        from turn_detail_cache import shared
        self.turn_cache=shared();self.turn_cache.changed.connect(self.turn_cache_changed);self._turn_request_key=None
        self.setMinimumWidth(0);self.setMinimumHeight(230)
        body=QVBoxLayout(self);body.setContentsMargins(0,0,0,0);body.setSpacing(5)
        self._external_search=search_bar is not None
        self.search_bar=search_bar if search_bar is not None else ProjectSearchBar(self)
        self.search=self.search_bar.edit;self.search_button=self.search_bar.button
        if search_bar is None:body.addWidget(self.search_bar)
        self.archive_control=SlidingSegments([('未归档','active'),('已归档','archived'),('全部','all')],compact=True);body.addWidget(self.archive_control)
        self.back=QToolButton();self.back.setText('‹ 项目');self.back.setFixedHeight(26)
        set_theme_style(self.back,'QToolButton{'+FONT_CSS+'font-size:12px;color:#514360;background:transparent;border:0;text-align:left;}QToolButton:hover{background:#eae1f2;border-radius:5px;}')
        self.back.clicked.connect(self.go_back);body.addWidget(self.back);self.back.hide()
        self.summary=CostSummary(self);self.summary.hide();self._row_ids=[]
        self.stack=QStackedWidget();body.addWidget(self.stack,1)
        if self._external_search:
            body.removeWidget(self.back)
            self.search_bar.layout().addWidget(self.back,0,Qt.AlignmentFlag.AlignLeft)
        self.info_button=CostMoreButton()
        set_theme_style(self.info_button,'QToolButton{'+FONT_CSS+'font-size:12px;color:#75618d;border:0;background:transparent;text-align:left;}')
        self.info_button.clicked.connect(self.more)
        if not self._external_search:
            toolbar=QHBoxLayout();toolbar.addStretch();toolbar.addWidget(self.info_button);body.insertLayout(0,toolbar)
        else:self.info_button.hide()
        self.list=QListWidget();self.list.setMouseTracking(True);self.list.setItemDelegate(CostDelegate(self.list));self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel);self.list.setMinimumSize(0,0);self.stack.addWidget(self.list)
        self.details=QScrollArea();self.details.setWidgetResizable(True);self.details.setMinimumSize(0,0);self.details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn);self.stack.addWidget(self.details)
        self.empty=self.label('');self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty.setWordWrap(True);self.stack.addWidget(self.empty)
        style='QListWidget,QScrollArea{background:transparent;border:0;outline:0;}QListWidget::item{border:0;}QScrollBar:vertical{background:transparent;width:3px;margin:2px 0 2px 0;border-radius:2px;}QScrollBar::handle:vertical{background:#e4dfea;min-height:30px;border-radius:2px;}QScrollBar::handle:vertical:hover{background:#8b78a6;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}'
        set_theme_style(self.list,style);set_theme_style(self.details,style)
        self.list_scroll=SmoothCostScroll(self.list);self.detail_scroll=SmoothCostScroll(self.details)
        self.search.textChanged.connect(self.filter_changed);self.search.returnPressed.connect(self.filter_changed);self.search_button.clicked.connect(self.filter_changed);self.archive_control.currentIndexChanged.connect(self.archive_changed)
        self.list.itemClicked.connect(self.activate_row)
        self.list.itemActivated.connect(lambda item:self.select(item.data(Qt.ItemDataRole.UserRole)) if '_summary' not in item.data(Qt.ItemDataRole.UserRole) else None)
        self.detail_motion=PageFade(self);self._detail_transition=0
        from pricing_ui import events
        events().changed.connect(self.prices_changed)
        self.refresh()
    def activate_row(self,item):
        value=item.data(Qt.ItemDataRole.UserRole)
        if '_summary' not in value:self.select(value);return
        from PySide6.QtGui import QCursor
        local=self.list.viewport().mapFromGlobal(QCursor.pos())-self.list.visualItemRect(item).topLeft()
        width=self.list.visualItemRect(item).width()
        if QRectF(width-93,101,84,20).contains(QPointF(local)):
            self.sort_name=not getattr(self,'sort_name',False);self.refresh()
        elif value.get('tokens') and QRectF(width-67,77,58,20).contains(QPointF(local)):
            if value.get('pending'):self.show_coverage(dict(name='筛选项目',pending_tokens=value['pending'],pending_reasons={}))
            else:ExplanationOverlay(self,'计价覆盖率',['当前筛选范围内的 Token 用量均已计价。'])
    def prices_changed(self):
        self._sessions_key=None;self._detail_key=None;self.refresh()
    def owner_pet(self):
        bubble=getattr(self.window(),'bubble',None)
        return bubble.owner_pet() if bubble is not None else None
    def more(self):
        menu=QMenu(self);set_theme_style(menu,'QMenu{'+FONT_CSS+'font-size:12px;color:#393343;background:#fcfafc;border:1px solid #e4dfea;border-radius:8px;padding:5px;}QMenu::item{padding:7px 12px;border-radius:5px;}QMenu::item:selected{background:#eae1f2;}')
        menu.addAction('导出统计',self.show_export);menu.addAction('计价设置',self.show_pricing);menu.addAction('估算说明',self.show_info);menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        anchor=getattr(self,'more_anchor',self.info_button);menu.ensurePolished();menu.popup(anchor.mapToGlobal(__import__('PySide6.QtCore',fromlist=['QPoint']).QPoint(anchor.width()-menu.sizeHint().width(),anchor.height()+3)))
    def show_pricing(self):
        from pricing_ui import open_editor
        models={m['model'] for p in self.data.get('ranges',{}).get('all',[]) for m in p['model_usage']}
        pet=self.owner_pet();open_editor(self,models,getattr(pet,'refresh_tokens',None))
    def show_export(self):
        from cost_details import export_rows,encode_export
        rows=list(export_rows(self.data,self.period,self.search.text(),self.archive))
        overlay=ExplanationOverlay(self,'导出统计',['当前项目、时间和归档筛选。','项目、范围、模型、Token、美元估算金额及待定价用量。','不包含聊天正文、账号或完整项目路径。'])
        formats=SlidingSegments([('CSV','CSV'),('JSON','JSON')],compact=True);overlay.layout().addWidget(formats)
        button=QPushButton('导出文件');overlay.layout().addWidget(button)
        set_theme_style(button,FONT_CSS+'font-size:12px;background:#eae1f2;color:#514360;border:0;border-radius:6px;padding:7px;')
        def write():
            from pathlib import Path
            kind=formats.currentData();path,_=QFileDialog.getSaveFileName(self,'导出成本统计','白龙成本统计.'+kind.lower(),kind+' (*.'+kind.lower()+')')
            if not path:return
            try:
                import os,tempfile
                target=Path(path);fd,name=tempfile.mkstemp(prefix='.bailong-export-',dir=target.parent)
                try:
                    with os.fdopen(fd,'wb') as stream:stream.write(encode_export(rows,kind))
                    os.replace(name,target)
                finally:
                    if Path(name).exists():Path(name).unlink()
            except OSError as error:QMessageBox.warning(overlay,'未能导出',str(error));return
            QMessageBox.information(overlay,'导出完成','文件已保存到：\n'+path)
        button.clicked.connect(write)
    def request_sessions(self,project):
        if 'session_usage' in project:
            self.session_rows=project['session_usage'];return
        key=(project['id'],self.period,self.data.get('checked'),self.data.get('price_revision'))
        # A refresh may reuse already rendered details, without restarting a
        # long history read for every incoming quota/status update.
        key=(project['id'],self.period,self.data.get('price_revision'),project['tokens'],tuple(project.get('session_ids',[])))
        if key==self._sessions_key:return
        base=(key[0],key[1],key[2],key[4])
        if self.detail_job is not None and base==getattr(self,'_request_base',None):return
        keep=self.session_rows is not None and base==getattr(self,'_request_base',None)
        self._request_base=base
        self._sessions_key=key;self.detail_ticket+=1;ticket=self.detail_ticket
        if self.detail_job:self.detail_job.requestInterruption()
        pet=self.owner_pet();index=getattr(getattr(pet,'activity',None),'token_index',None)
        path=getattr(self,'detail_index_path',None) or getattr(index,'path',None)
        if not path:self.session_rows=[];return
        if not keep:self.session_rows=None
        self.session_error='';job=DetailJob(path,dict(project),self.period,getattr(index,'home',None));self.detail_job=job
        job.ready.connect(lambda rows:self.sessions_ready(ticket,rows));job.failed.connect(lambda text:self.sessions_failed(ticket,text));job.finished.connect(job.deleteLater);job.start()
    def sessions_ready(self,ticket,rows):
        from shiboken6 import isValid
        if not isValid(self):return
        if ticket!=self.detail_ticket:return
        self.detail_job=None;self.session_rows=rows
        if self.session:self.session=next((s for s in rows if s['id']==self.session['id']),None)
        self._detail_key=None;self.refresh()
    def sessions_failed(self,ticket,text):
        from shiboken6 import isValid
        if not isValid(self):return
        if ticket!=self.detail_ticket:return
        self.detail_job=None;self.session_rows=[];self.session_error=text;self._detail_key=None;self.refresh()
    def action(self,box,text,slot):
        button=QPushButton(text);button.setMinimumWidth(0);button.setCursor(Qt.CursorShape.PointingHandCursor)
        set_theme_style(button,'QPushButton{'+FONT_CSS+'font-size:12px;color:#393343;background:#f5f0f8;border:0;border-radius:7px;padding:8px;text-align:left;}QPushButton:hover{background:#eae1f2;}');button.clicked.connect(slot);box.addWidget(button);return button
    def go_back(self):
        if self.session is not None:
            self.open_session(None);return
        self.select(None)
    def open_session(self,session):
        position=self.details.verticalScrollBar().value()
        if session:self.session_position=position
        frame=PageFade.snapshot(self) if self.isVisible() and motion_enabled() else None
        if session is None and self.detail_job and self._turn_request_key is None:
            self.detail_job.requestInterruption();self.detail_job=None;self.detail_ticket+=1
        self.session=dict(session) if session else None
        if session and 'turns' not in session:self.load_turns(session)
        self._detail_key=None;self.refresh();self.details.verticalScrollBar().setValue(0 if session else self.session_position)
        self._detail_transition+=1;ticket=self._detail_transition
        if frame is not None:self.detail_motion.hold(frame,self.rect());QTimer.singleShot(0,self,lambda:self._present_detail(ticket,frame,session is not None))
    def load_turns(self,session):
        pet=self.owner_pet();index=getattr(getattr(pet,'activity',None),'token_index',None);path=getattr(self,'detail_index_path',None) or getattr(index,'path',None)
        key=(str(path),session['id'],self.period,self.data.get('price_revision'),session['tokens'],session.get('detail_revision'))
        self.turn_error='';self._turn_request_key=key
        turns,exact=self.turn_cache.lookup(key)
        if turns is not None:self.session=dict(session,turns=turns,syncing=not exact)
        if exact:self.detail_job=None;return
        if not path:self.turn_error='暂无可读取明细';return
        project=next(p for p in self.data['ranges'][self.period] if p['id']==self.selected)
        self.detail_job=self.turn_cache.request(key,lambda p=path,scope=dict(project,session_ids=[session['id']]),period=self.period,home=getattr(index,'home',None),prices=self.data.get('price_table'):DetailJob(p,scope,period,home,prices))
    def turn_cache_changed(self,key,result):
        wanted=self._turn_request_key
        if wanted is None or key[:4]!=wanted[:4]:return
        self.detail_job=None
        if not self.session or self.session['id']!=key[1]:return
        if 'error' in result:self.turn_error=result['error']
        else:self.session=dict(self.session,turns=result['turns'],syncing=key!=wanted)
        if not self.isVisible():self._detail_key=None;return
        if key!=wanted and self.isVisible():self.load_turns(self.session)
        self._detail_key=None;self.refresh()
    def session_body(self,session):
        from datetime import datetime
        body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(0,0,2,0);layout.setSpacing(3)
        layout.addWidget(DetailSummary(session,True))
        if session.get('syncing') or self.turn_error:
            status=QHBoxLayout();status.addWidget(self.label(self.turn_error or '正在更新明细…'),1)
            if self.turn_error:
                retry=QPushButton('重试');retry.clicked.connect(lambda:self.load_turns(session));status.addWidget(retry)
            layout.addLayout(status)
        if 'turns' not in session:
            layout.addWidget(self.label(self.turn_error or '首次读取回合明细…'));layout.addStretch();return body
        head=QHBoxLayout();head.addWidget(self.label('回合明细',True),1)
        order=QToolButton();order.setText('最新优先 ↓' if self.session_order=='time' else '成本优先 ↓');order.setAccessibleName('回合排序');set_theme_style(order,FONT_CSS+'font-size:11px;color:#706879;background:transparent;border:0;');head.addWidget(order)
        def sorting():
            menu=QMenu(order)
            for title,key in (('最新优先','time'),('成本优先','cost')):menu.addAction(title,lambda k=key:self.set_session_order(k))
            menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);menu.popup(order.mapToGlobal(__import__('PySide6.QtCore',fromlist=['QPoint']).QPoint(0,order.height())))
        order.clicked.connect(sorting);layout.addLayout(head)
        turns=sorted(session['turns'],key=(lambda t:-t['cost']) if self.session_order=='cost' else (lambda t:-t['stamp']));day=None
        for turn in turns[:getattr(self,'turn_limit',60)]:
            date='回合未识别' if turn['unknown'] else datetime.fromtimestamp(turn['stamp']).strftime('%m月%d日')
            if self.session_order=='time' and date!=day:layout.addWidget(self.label(date));day=date
            layout.addWidget(TurnRow(turn))
        if len(turns)>getattr(self,'turn_limit',60):self.action(layout,'继续显示',self.more_turns)
        if not turns:layout.addWidget(self.label('这个范围还没有回合'))
        layout.addStretch();return body

    def more_turns(self):self.turn_limit=getattr(self,'turn_limit',60)+60;self._detail_key=None;self.refresh()
    def set_session_order(self,value):self.session_order=value;self._detail_key=None;self.refresh();self.details.verticalScrollBar().setValue(0)
    def label(self,text,strong=False):
        w=QLabel(text);w.setTextFormat(Qt.TextFormat.PlainText);w.setWordWrap(True);w.setMinimumWidth(0);w.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);w.setFixedHeight(20 if '\n' not in str(text) else 20*len(str(text).splitlines()))
        if len(str(text))<16:w.setMinimumWidth(QFontMetrics(font(12,strong)).horizontalAdvance(str(text))+2)
        set_theme_style(w,FONT_CSS+'font-size:12px;font-weight:'+('600' if strong else '400')+';color:'+('#393343' if strong else '#706879')+';background:transparent;');return w
    def card(self,layout,title):
        w=QFrame();w.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Maximum);w.setObjectName('costSection');set_theme_style(w,'QFrame#costSection{background:#f5f0f8;border-radius:8px;}')
        box=QVBoxLayout(w);box.setContentsMargins(8,7,8,7);box.setSpacing(6);heading=self.label(title,True);set_theme_style(heading,FONT_CSS+'font-size:12px;font-weight:500;color:#75618d;background:transparent;');
        if title:box.addWidget(heading)
        layout.addWidget(w);return box
    def detail_body(self,p):
        body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(0,0,2,0);layout.setSpacing(6)
        layout.addWidget(DetailSummary(p))
        tabs=SlidingSegments([('会话 '+str(p['sessions']),'sessions'),('费用构成','composition')],compact=True);tabs.setCurrentIndex(tabs.findData(getattr(self,'project_part','sessions')),False);layout.addWidget(tabs)
        tabs.currentIndexChanged.connect(lambda:self.set_project_part(tabs.currentData()))
        if getattr(self,'project_part','sessions')=='sessions':
            head=QHBoxLayout();head.addWidget(self.label('会话名称'),1);head.addWidget(self.label('估算成本'));layout.addLayout(head)
            if self.session_rows is None:layout.addWidget(self.label('正在读取会话明细…'))
            elif not self.session_rows:layout.addWidget(self.label(getattr(self,'session_error','暂无可读取明细')))
            else:
                for session in self.session_rows:
                    button=SessionButton(session);button.clicked.connect(lambda checked=False,s=session:self.open_session(s));layout.addWidget(button)
        else:
            layout.addWidget(self.label('费用分布',True));layout.addWidget(FeeStrip(p['parts']))
            for title,value in zip(('非缓存输入','缓存输入','输出（含推理）'),p['parts']):
                layout.addWidget(MetricLine(title,estimated(value,p['tokens'],p['pending_tokens'])))
            layout.addWidget(self.label('模型用量',True))
            for item in p.get('model_usage',[]):
                layout.addWidget(MetricLine(item['model'],estimated(item['cost'],item['tokens'],item['pending_tokens'])));layout.addWidget(self.label(compact_tokens(item['tokens'])+' Token'))
        if p['pending_tokens']:self.action(layout,compact_tokens(p['pending_tokens'])+' Token 待定价  ›',lambda:self.show_coverage(p))
        layout.addStretch();return body
    def show_coverage(self,p):
        reasons={'unknown_model':'模型暂无单价','incomplete_counts':'输入 / 输出记录不完整','unknown_project':'项目归属未识别'}
        text=[p['name']+' / '+compact_tokens(p['pending_tokens'])+' Token 待定价','已知价格的部分已计入金额。']
        text.extend(reasons.get(k,'暂未核算')+' / '+compact_tokens(n)+' Token' for k,n in p.get('pending_reasons',{}).items())
        overlay=ExplanationOverlay(self,'未计价用量',text)
        button=QPushButton('补充模型单价');button.clicked.connect(self.show_pricing);overlay.layout().addWidget(button)

    def show_info(self):
        if getattr(self,'explanation',None):self.explanation.close()
        self.explanation=ExplanationOverlay(self,'金额怎么估算',[
            '按本机记录的 Token 折算成 API 等价金额，单位为美元。它不是 Plus 或 Pro 订阅账单。',
            '非缓存输入 × 输入价\n＋ 缓存输入 × 缓存价\n＋ 输出 × 输出价',
            '推理已包含在输出中。未知模型、价格或计数不完整的部分标为待定价，不当作零元。',
            '昨日按本地时间 00:00–24:00 统计。项目跟随当前会话归属，迁移不重复累计历史用量。',
            '正在整理历史记录。' if self.data.get('initial_pending') else '正在同步新增记录。' if self.data.get('pending') else '按已读取记录估算，其他设备的用量可能不完整。'])
        self.explanation.destroyed.connect(lambda:setattr(self,'explanation',None))
    def set_data(self,data,period):
        if period!=self.period:self.session=None;self.turn_limit=60
        self.data=data or {};self.period=period;self.refresh()
    def reset_navigation(self):
        """Fresh entry starts at the list's top; in-visit Back keeps its position."""
        self._detail_transition+=1;self.detail_motion.clear();self.session=None;self.turn_limit=60
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
        if target is None and self.detail_job and self._turn_request_key is None:
            self.detail_job.requestInterruption();self.detail_job=None;self.detail_ticket+=1;self._sessions_key=None
        self.list_scroll.animation.stop();self.detail_scroll.animation.stop()
        entering=target is not None
        ticket,frame=self._hold_detail_frame()
        self.selected=target;self.session=None;self.project_part='sessions';self.turn_limit=60;self.refresh()
        if entering:
            self.details.verticalScrollBar().setValue(0)
            QTimer.singleShot(0,self,lambda:self._reset_detail_entry(ticket,target))
        if frame is not None:QTimer.singleShot(0,self,lambda:self._present_detail(ticket,frame,entering))
        else:self.detail_motion.clear()
    def set_project_part(self,part):
        if self.selected is None or self.session or self.project_part==part:return
        self.detail_scroll.animation.stop()
        ticket,frame=self._hold_detail_frame()
        self.project_part=part;self._detail_key=None
        self.refresh()
        self.details.verticalScrollBar().setValue(0)
        target=self.selected
        QTimer.singleShot(0,self,lambda:self._reset_detail_entry(ticket,target))
        if frame is not None:
            QTimer.singleShot(0,self,lambda:self._present_detail(ticket,frame,part=='composition'))
        else:self.detail_motion.clear()

    def _hold_detail_frame(self):
        outer=self.window()
        busy=getattr(outer,'_animating',False) or bool(getattr(getattr(outer,'follow',None),'active',False))
        outer_motion=getattr(outer,'page_fade',None)
        busy=busy or bool(outer_motion and outer_motion.animation.state()==QAbstractAnimation.State.Running)
        frame=None
        if self.isVisible() and not busy and motion_enabled():
            frame=self.detail_motion.current_frame() if self.detail_motion.isVisible() else PageFade.snapshot(self)
        self._detail_transition+=1;ticket=self._detail_transition
        if frame is not None:self.detail_motion.hold(frame,self.rect())
        return ticket,frame

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
            self.detail_motion.animation.setDuration(220)
            self.detail_motion.animation.setEasingCurve(QEasingCurve.Type.OutCubic if entering else QEasingCurve.Type.InCubic)
            self.detail_motion.present(frame,target,self.rect(),direction=1 if entering else -1)
        except Exception:
            # A failed snapshot must leave the live target usable, rather than
            # retaining an old cover or leaving the subtree permanently frozen.
            self.detail_motion.clear();raise
    def hideEvent(self,event):
        if self.detail_job and self._turn_request_key is None:
            self.detail_job.requestInterruption();self.detail_job=None;self.detail_ticket+=1;self._sessions_key=None
        self._detail_transition+=1;self.detail_motion.clear();super().hideEvent(event)
    def resizeEvent(self,event):
        if hasattr(self,'detail_motion'):
            self._detail_transition+=1;self.detail_motion.clear()
        super().resizeEvent(event)
    def refresh(self):
        rows=search_rows(self.data,self.period,self.search.text(),self.archive)
        rows=sorted(rows,key=(lambda p:p['name']) if getattr(self,'sort_name',False) else (lambda p:-p['cost']))
        selected=next((p for p in rows if p['id']==self.selected),None)
        if self.selected is not None and selected is None:self.selected=None
        if not self._external_search:self.search_bar.setVisible(not selected)
        else:self.search.setVisible(not selected)
        self.archive_control.setVisible(not selected);self.back.setVisible(bool(selected))
        ids=[p['id'] for p in rows]
        name_counts={}
        for p in rows:name_counts[p['name']]=name_counts.get(p['name'],0)+1
        if self._row_ids!=ids or not self.list.count():
            self.list_scroll.animation.stop()
            position=self.list.verticalScrollBar().value()
            self.list.clear()
            header=QListWidgetItem();header.setData(Qt.ItemDataRole.UserRole,{'_summary':''});header.setFlags(Qt.ItemFlag.ItemIsEnabled);self.list.addItem(header)
            for p in rows:self.list.addItem(QListWidgetItem())
            self._row_ids=ids;self.list.verticalScrollBar().setValue(position)
        cost=sum(p['cost'] for p in rows);tokens=sum(p['tokens'] for p in rows);unknown=sum(p['pending_tokens'] for p in rows)
        for i,p in enumerate(rows):
            item=dict(p,share=p['cost']/max(1e-12,cost),duplicate=name_counts[p['name']]>1)
            if self.list.item(i+1).data(Qt.ItemDataRole.UserRole)!=item:self.list.item(i+1).setData(Qt.ItemDataRole.UserRole,item)
        if selected:
            self.request_sessions(selected)
            if self.session:
                summary=next((s for s in (self.session_rows or []) if s['id']==self.session['id']),None)
                if summary:self.session=dict(self.session,name=summary['name'])
            cost=selected['cost'];tokens=selected['tokens'];unknown=selected['pending_tokens']
            key=(selected,self.data.get('pending'),self.data.get('initial_pending'),self.data.get('price_revision'),self.session['id'] if self.session else None,id(self.session.get('turns')) if self.session else None,self.turn_error,self.session_order,getattr(self,'turn_limit',60))
            if key!=self._detail_key:
                position=self.details.verticalScrollBar().value();old=self.details.takeWidget()
                self.details.setWidget(self.session_body(self.session) if self.session else self.detail_body(selected));self.details.verticalScrollBar().setValue(position if self._detail_key and self._detail_key[0]['id']==selected['id'] else 0)
                if old:old.deleteLater()
                self._detail_key=key
            self.back.setText('‹ 项目' if not self.session else '‹ '+selected['name'])
            self.stack.setCurrentWidget(self.details)
        elif rows:self.stack.setCurrentWidget(self.list)
        else:
            self.empty.setText('正在整理项目记录…' if self.data.get('pending') else '部分用量暂不能核对' if self.data.get('limited') or self.data.get('errors') else '没有匹配项目');self.stack.setCurrentWidget(self.empty)
        note=('已定价部分' if unknown else 'API 等价估算')+'  '+estimated(cost,tokens,unknown)+'\n'+compact_tokens(tokens)+' Token'
        if unknown:note+='\n'+compact_tokens(unknown)+' 待定价'
        elif self.data.get('pending'):note+='\n整理中' if self.data.get('initial_pending',True) else '  同步中'
        elif self.data.get('limited') or self.data.get('errors'):note+='  记录不完整'
        self.summary.setText(note if rows else ('记录不完整' if self.data.get('limited') or self.data.get('errors') else ''))
        header={'_summary':self.summary.text(),'sort_name':getattr(self,'sort_name',False),'projects':len(rows),'tokens':sum(p['tokens'] for p in rows),'pending':sum(p['pending_tokens'] for p in rows)}
        if self.list.item(0).data(Qt.ItemDataRole.UserRole)!=header:self.list.item(0).setData(Qt.ItemDataRole.UserRole,header)
        if self.updatesEnabled() and self.detail_motion.slide and self.detail_motion.animation.state()==QAbstractAnimation.State.Running:
            # A worker may finish inside the entry animation. QWidget.render
            # drops child text while updates are disabled; capture a settled
            # live subtree synchronously, without thawing a parent handoff.
            try:
                from panel_transition import settle_visible
                self.detail_motion.hide();settle_visible(self);self.detail_motion.next_frame=PageFade.snapshot(self)
            finally:self.detail_motion.show();self.detail_motion.raise_()
        self.changed.emit()
