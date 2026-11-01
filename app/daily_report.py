"""Manually opened, animated daily report anchored above the status bubble."""
from settings_controls import play_animation
from theme_registry import color as theme_color,chart_color
from theme_runtime import set_theme_style,theme_style_source,set_theme_text
import math,random
from html import escape
from datetime import datetime
from PySide6.QtCore import Qt,QRect,QRectF,QPointF,QPoint,QSize,QEvent,Signal,QVariantAnimation,QEasingCurve,QAbstractAnimation,QTimer
from PySide6.QtGui import QPainter,QPainterPath,QPen,QColor,QFontMetrics,QPixmap,QRegion
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QToolButton,QScrollArea,QApplication,QSizePolicy,QProgressBar,QStackedWidget
from compact_bubble import font,INK,MUTED,FONT_CSS,action_button
from token_calendar import compact_tokens
from token_analytics import model_series,token_analogy
from book_reference import analogy as book_analogy,catalog as book_catalog
from chart_reveal import ChartReveal,RasterChart,bar_shape
from chart_curve import SmoothTrace
from rate_chart import ComboChart,colors as rate_colors,rate_text
from spring_motion import island_response,dismiss_progress,stage,EXPAND_MS,DISMISS_MS
from card_motion import card_geometry,paint_card

from ui_theme import MODEL_COLORS,PANEL,PRIMARY,SELECTED
from settings_controls import SlidingSegments
from quota_compare_ui import QuotaCompareView
from project_cost_ui import ProjectCosts,ProjectSearchBar,DailyCostButton,ExplanationOverlay,SmoothCostScroll
COLORS=MODEL_COLORS

# Radix Colors light: mauve for surfaces/text, purple for the quota accent.
CYCLE_SURFACE='#f5f0f8';CYCLE_INK='#393343';CYCLE_MUTED='#706879'
CYCLE_ACCENT='#8b78a6';CYCLE_TRACK='#e4dfea'

def tab(text,slot,checked=False,checkable=True):
    b=QToolButton();b.setText(text);b.setCheckable(checkable);b.setChecked(checked);b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor);b.setFixedHeight(23)
    set_theme_style(b,'QToolButton{'+FONT_CSS+'font-size:12px;font-weight:500;color:#706879;border:0;border-radius:5px;padding:2px 4px;background:transparent;}QToolButton:checked{color:#514360;background:#eae1f2;}QToolButton:hover{background:#f0e9f6;}')
    b.clicked.connect(slot);return b

class ScopeReadout(QLabel):
    """Keep the Token amount prominent beside the shared period filter."""
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumWidth(0);self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);self.setFixedHeight(27)
    def paintEvent(self,event):
        p=QPainter(self);main=self.text()
        p.setFont(font(11,True));p.setPen(QColor(theme_color(INK)));fm=QFontMetrics(p.font())
        shown=fm.elidedText(main,Qt.TextElideMode.ElideRight,self.width());p.drawText(self.rect(),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,shown)

class OverviewStats(QWidget):
    def __init__(self,report,parent=None):
        super().__init__(parent);self.report=report
    def set_columns(self,width):
        self.columns=2;self.setFixedHeight(126)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);r=self.report
        cells=[('会话数',f"{r.get('sessions',0):,}"),('活跃天数',str(r.get('active_days',0))),
               ('Token 总量',compact_tokens(r.get('all_total',0))),('最常用模型',r.get('favorite_model','暂无记录')),
               ('消息数',f"{r.get('messages',0):,}"),('高峰时段',f"{r['peak_hour']:02}:00–{r['peak_hour']+1:02}:00" if r.get('peak_hour') is not None else '暂无用量')]
        width=(self.width()-4)/2
        p.setPen(QColor(theme_color(PRIMARY)));p.setFont(font(11));p.drawText(QRectF(1,0,self.width()-2,16),Qt.AlignmentFlag.AlignVCenter,'累计  本机记录')
        p.drawText(QRectF(1,105,self.width()-2,18),Qt.AlignmentFlag.AlignVCenter,'昨日')
        p.setPen(QColor(theme_color(MUTED)));p.drawText(QRectF(1,105,self.width()-2,18),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,f"{r.get('messages',0):,} 条消息")
        for i,(label,value) in enumerate(cells[:4]):
            rect=QRectF((i%2)*(width+4),18+(i//2)*41+(18 if i>=4 else 0),width,37)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme_color('#f1ecf6')));p.drawRoundedRect(rect,6,6)
            p.setPen(theme_color(MUTED));p.setFont(font(10));p.drawText(rect.adjusted(6,2,-3,-20),Qt.AlignmentFlag.AlignVCenter,label)
            p.setPen(theme_color(INK));p.setFont(font(11 if i in (3,5) else 14,True))
            p.drawText(rect.adjusted(6,17,-5,-2),Qt.AlignmentFlag.AlignVCenter,QFontMetrics(p.font()).elidedText(value,Qt.TextElideMode.ElideRight,round(width-11)))

class ReportPlot(QWidget,RasterChart,ComboChart):
    hoverText=Signal(str)
    def __init__(self,report,mode='line',period='7d',selected=None,parent=None,series=None):
        super().__init__(parent);self.report=report;self.mode=mode;self.series=(series if series is not None else model_series(report,period)) if mode=='bars' else None
        self.selected=selected;self.hits=[];self.points=[];self._hover='';self._resume_time=None;self.setMouseTracking(True);self.setFixedHeight(94)
        self.reveal=ChartReveal(self,420 if mode=='line' else 620);self.init_combo();self._pending_chart_data=False
        self.reveal.animation.finished.connect(self._apply_chart_data)
        self._measure_axes()
    def set_data(self,report,series=None,selected=None):
        self.dismiss_inspection();self.report=report;self.series=series;self.selected=selected
        if self.reveal.animation.state()==QAbstractAnimation.State.Running and getattr(self,'_layer_key',None) is not None:
            # Keep this entry's axes/columns fixed when a background scan
            # delivers another snapshot. Commit the latest data once landed.
            self._pending_chart_data=True;return
        self._pending_chart_data=False;self.hits=[];self._measure_axes();self.invalidate_layers();self._set_hover('');self.update()
    def _apply_chart_data(self):
        if not self._pending_chart_data:return
        self._pending_chart_data=False;self.hits=[];self._measure_axes();self.invalidate_layers();self._set_hover('');self.update()
    def _measure_axes(self):
        values=self.report.get('hours',[0]*24) if self.mode=='line' else [b['values'].get(self.selected,0) if self.selected else b['total'] for b in self.series['bins']]
        top=max(values,default=0);self._axis_font=font(10,True);self._axis_metrics=QFontMetrics(self._axis_font)
        self._axis_labels=[compact_tokens(round(top*f)) for f in (0,.5,1)]
        self._axis_left=3 if self.mode=='line' else max(37,max(self._axis_metrics.horizontalAdvance(t) for t in self._axis_labels)+7)
    def begin_reveal(self):self._apply_chart_data();self.ensure_layers();self._resume_time=None;self.reveal.prepare()
    def freeze_reveal(self):
        self._resume_time=self.reveal.animation.currentTime() if self.reveal.animation.state()==QAbstractAnimation.State.Running else None
        self.reveal.stop()
    def start_reveal(self):
        from settings_controls import motion_enabled
        if not motion_enabled():
            self._resume_time=None;self.reveal.prepare();return
        if self._resume_time is not None and self.isVisible():
            ms=self._resume_time;self._resume_time=None
            self.reveal.animation.start();self.reveal.animation.setCurrentTime(ms)
        else:self.reveal.start()
    def showEvent(self,event):
        super().showEvent(event)
        # Newly inserted scroll-area children are not visible in the click
        # handler. Start after their first layout/show, rather than lose the
        # pending reveal forever. Hidden/replaced plots cannot start a timer.
        if self.reveal.pending or self._resume_time is not None:QTimer.singleShot(0,self,self.start_reveal)
    def hideEvent(self,event):self.dismiss_inspection();self.reveal.stop();super().hideEvent(event)
    def chart_rect(self):
        top=19 if self.mode=='line' else math.ceil(self._axis_metrics.height()/2)+2
        return QRectF(self._axis_left,top,max(1,self.width()-self._axis_left-6),max(1,self.height()-self._axis_metrics.height()-6-top))
    def chart_mode(self):return self.mode
    trace_color=COLORS[0]
    def paintEvent(self,event):self.paint_combo() if self.mode=='line' else self.paint_layers()
    def render_layers(self,p,dynamic):
        if self.mode=='line':return self._render_combo(p,dynamic)
        chart=self.chart_rect();bottom=chart.bottom();self.hits=[]
        if self.mode=='line':values=self.report.get('hours',[0]*24);top=max(values,default=0)
        else:
            bins=self.series['bins'];values=[b['values'].get(self.selected,0) if self.selected else b['total'] for b in bins];top=max(values,default=0)
        p.setFont(self._axis_font)
        for f,text in zip((0,.5,1),self._axis_labels):
            y=bottom-chart.height()*f;p.setPen(QPen(QColor(theme_color('#e9e1ef')),.7));p.drawLine(QPointF(chart.left(),y),QPointF(chart.right(),y))
            p.setPen(theme_color(MUTED))
            baseline=y+(self._axis_metrics.ascent()-self._axis_metrics.descent())/2
            if self.mode!='line':p.drawText(QPointF(chart.left()-6-self._axis_metrics.horizontalAdvance(text),baseline),text)
        slot=chart.width()/max(1,len(values));points=[];self.points=points;self.curve=None;path=QPainterPath();static=p;p=dynamic
        if self.mode=='line':
            for i,value in enumerate(values):
                point=QPointF(chart.left()+(i+.5)*chart.width()/24,bottom-chart.height()*value/max(1,top));points.append(point)
                self.hits.append((QRectF(point.x()-slot/2,chart.top(),slot,chart.height()),f"{i:02}:00–{i+1:02}:00  {value:,} Tokens"))
            self.curve=SmoothTrace(points);path=self.curve.path
            fill=QPainterPath(path);fill.lineTo(points[-1].x(),bottom);fill.lineTo(points[0].x(),bottom);fill.closeSubpath();p.fillPath(fill,QColor(theme_color('#ebe2f2')))
            p.setPen(QPen(QColor(chart_color(original=COLORS[0])),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.drawPath(path)
            labels=[(0,'00'),(.5,'12'),(1,'24时')]
        else:
            model_order=[m['model'] for m in self.series['models']]
            for i,(b,value) in enumerate(zip(bins,values)):
                y=bottom
                total_height=chart.height()*value/max(1,top)
                p.save()
                p.setClipPath(bar_shape(QRectF(chart.left()+i*slot,bottom-total_height,max(.8,slot-1.5),total_height)),Qt.ClipOperation.IntersectClip)
                for j,model in enumerate(model_order):
                    if self.selected and model!=self.selected:continue
                    amount=b['values'].get(model,0);height=chart.height()*amount/max(1,top)
                    if height<=0:continue
                    p.fillRect(QRectF(chart.left()+i*slot,y-height,max(.8,slot-1.5),height),QColor(chart_color(j,original=COLORS[j%len(COLORS)])));y-=height
                p.restore()
                label=b['start'] if b['start']==b['end'] else b['start']+' 至 '+b['end']
                self.hits.append((QRectF(chart.left()+i*slot,chart.top(),slot,chart.height()),label+f'  {value:,} Tokens'))
            labels=[(0,self.series['start'][5:].replace('-','/')),(1,self.series['end'][5:].replace('-','/'))]
        p=static;p.setFont(font(10,True));p.setPen(theme_color(MUTED))
        for f,text in labels:
            x=chart.left()+f*chart.width();rect=QRectF(x-(30 if f==1 else 0 if f==0 else 15),bottom+4,32,self._axis_metrics.height()+2)
            p.drawText(rect,Qt.AlignmentFlag.AlignVCenter| (Qt.AlignmentFlag.AlignRight if f==1 else Qt.AlignmentFlag.AlignLeft),text)
        if not top:p.drawText(chart,Qt.AlignmentFlag.AlignCenter,'暂无 Token 用量')
    def _render_combo(self,p,dynamic):
        values=self.report.get('hours',[0]*24);plot=self.chart_rect()
        bins=[dict(label=f'{i:02}:00–{i+1:02}:00',value=v) for i,v in enumerate(values)]
        items=(self.report.get('rates') or {}).get('yesterday') or []
        self.combo_layers(p,dynamic,bins,items,plot)
        self.hits=[(r['rect'],b['label']+'  '+format(b['value'],',')+' Tokens') for r,b in zip(self._combo_records,bins)]
        self.points=[QPointF(r['rect'].center().x(),plot.bottom()) for r in self._combo_records]
        theme,bar,line=rate_colors();p.setFont(font(10));p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(bar));p.drawRoundedRect(QRectF(3,3,5,7),1,1)
        p.setPen(QColor(theme['muted']));p.drawText(QRectF(12,0,35,16),Qt.AlignmentFlag.AlignVCenter,'用量')
        p.setPen(QPen(QColor(line),1.8));p.drawLine(QPointF(51,7),QPointF(63,7));p.setPen(QColor(theme['muted']));p.drawText(QRectF(68,0,65,16),Qt.AlignmentFlag.AlignVCenter,'回合均速')
        p.setPen(QColor(theme['muted']));p.setFont(font(10))
        for f,label in [(0,'00时'),(.5,'12'),(1,'24时')]:
            p.drawText(QRectF(plot.left()+f*plot.width()-(32 if f==1 else 15 if f==.5 else 0),plot.bottom()+2,32,18),Qt.AlignmentFlag.AlignVCenter|(Qt.AlignmentFlag.AlignRight if f==1 else Qt.AlignmentFlag.AlignLeft),label)
    def keyPressEvent(self,event):
        if self.mode!='line' or not self.combo_key(event):super().keyPressEvent(event)
    def focusOutEvent(self,event):
        if event.reason()!=Qt.FocusReason.ActiveWindowFocusReason:self.dismiss_inspection()
        super().focusOutEvent(event)
    def mouseMoveEvent(self,event):
        if self.mode=='line':self.inspect_at(event.position())
        hovered=''
        for rect,text in self.hits:
            if rect.contains(event.position()):hovered=text;break
        self._set_hover(hovered)
        super().mouseMoveEvent(event)
    def _set_hover(self,text):
        if text!=self._hover:self._hover=text;self.hoverText.emit(text)
    def leaveEvent(self,event):self.dismiss_inspection();self._set_hover('');super().leaveEvent(event)

class ModelRow(QToolButton):
    def __init__(self,item,total,index,selected,slot):
        super().__init__();self.item=item;self.total=total;self.index=index;self.selected=selected
        self.setFixedHeight(38);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(item['model']+f"  {item['total']:,} Tokens")
        self.setCheckable(True);self.setChecked(selected)
        self.clicked.connect(slot)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.selected or self.underMouse():p.fillRect(self.rect(),QColor(theme_color('#f0e9f5')))
        if self.selected:
            p.setPen(QPen(QColor(theme_color(PRIMARY)),2));p.drawLine(0,3,0,self.height()-3)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(chart_color(self.index,original=COLORS[self.index%len(COLORS)])));p.drawRoundedRect(QRectF(1,7,7,7),2,2)
        p.setPen(QColor(theme_color(PRIMARY)));p.setFont(font(11,True));name=QFontMetrics(p.font()).elidedText(self.item['model'],Qt.TextElideMode.ElideRight,max(20,self.width()-120))
        p.drawText(QRectF(13,1,self.width()-122,19),Qt.AlignmentFlag.AlignVCenter,name)
        p.setPen(QColor(theme_color(INK)))
        text=compact_tokens(self.item['total'])+f"  {self.item['total']/max(1,self.total)*100:.1f}%"
        p.drawText(QRectF(self.width()-115,1,114,19),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,text)
        p.setPen(QColor(theme_color('#706879')));p.setFont(font(10))
        detail=compact_tokens(self.item['input'])+' in  '+compact_tokens(self.item['output'])+' out' if self.item['known'] else '输入 / 输出分项记录不完整'
        p.drawText(QRectF(13,18,self.width()-15,17),Qt.AlignmentFlag.AlignVCenter,detail)

class DailyReport(QWidget):
    refreshRequested=Signal()
    GAP=6
    PAD=8
    MIN_WIDTH=268
    def __init__(self,bubble):
        flags=Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint
        if bubble.windowFlags()&Qt.WindowType.WindowStaysOnTopHint:flags|=Qt.WindowType.WindowStaysOnTopHint
        super().__init__(bubble,flags);self.bubble=bubble;self.requested=False;self.page='overview';self.period='all';self.selected_model=None
        self.snapshot={};self.natural_height=412;self._overview_height=412;self.fraction=0.;self._building=False
        self.book_index=0;self._book_opened=False
        self._animating=False;self._frame=None;self._pending_rebuild=False;self._syncing=False;self._series_cache={}
        self.refresh_busy=False;self._body_cache={};self._data_revision=0
        self._host_open_page=None;self._host_prepared_page=None;self._host_return=False;self._host_closing=False
        self.setWindowTitle('白龙数据面板');self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        set_theme_style(self,'QLabel{'+FONT_CSS+'color:#393343;background:transparent;}QScrollArea{border:0;background:transparent;}QScrollBar:vertical{background:#f5f0f8;width:7px;margin:0;border-radius:3px;}QScrollBar::handle:vertical{background:#c7b7d7;min-height:18px;border-radius:3px;}QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}')
        self.surface=QWidget(self);self.layout=QVBoxLayout(self.surface);self.layout.setContentsMargins(10,8,10,8);self.layout.setSpacing(5)
        from data_page_motion import PageFade
        self.page_fade=PageFade(self.surface)
        self.page_fade.animation.finished.connect(self._page_motion_finished)
        self.refresh_button=action_button('refresh','刷新数据面板',parent=self.surface,hit_size=28)
        self.refresh_button.setObjectName('report_refresh');self.refresh_button.clicked.connect(self.request_refresh)
        self.refresh_button.hide()
        self.animation=QVariantAnimation(self);self.animation.setDuration(260);self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.valueChanged.connect(self._advance);self.animation.finished.connect(self._finished)
        from linked_report_motion import LinkedReportMotion
        self.follow=LinkedReportMotion(self);self.animation.finished.connect(bubble._apply_pending_mode)
        bubble.size_transition.animation.finished.connect(self._host_motion_finished)
        bubble.installEventFilter(self);self.hide();self.rebuild()
    def label(self,text,size=11,bold=False):
        size=max(11,size)
        w=QLabel(text);w.setFont(font(size,bold));w.setTextFormat(Qt.TextFormat.PlainText)
        # Bubble's inherited QLabel rule otherwise overrides setFont(…).
        set_theme_style(w,FONT_CSS+f'font-size:{size}px;font-weight:{600 if bold else 400};color:{"#393343" if bold else "#706879"};background:transparent;');return w
    def card(self,name):
        w=QWidget();w.setObjectName(name)
        set_theme_style(w,'QWidget#'+name+'{background:#f5f0f8;border-radius:7px;}')
        layout=QVBoxLayout(w);layout.setContentsMargins(7,5,7,5);layout.setSpacing(0)
        return w,layout
    def secondary(self,label):
        set_theme_style(label,theme_style_source(label)+'color:#62576e;background:transparent;');return label
    def set_snapshot(self,snapshot):
        snapshot=snapshot or {};previous=self.snapshot;self.snapshot=snapshot
        r=snapshot.get('report') or {};old=previous.get('report') or {}
        if r==old and all(snapshot.get(k)==previous.get(k) for k in ('partial','unavailable','week_cycle','quota_history','projects')):return
        self._data_revision+=1
        if r.get('day')!=old.get('day') or r.get('daily_models')!=old.get('daily_models'):self._series_cache.clear()
        if self._animating or self.follow.active:
            self._pending_rebuild=True;return
        if self.requested:
            if r and self.report:
                self.report=r;self.day_label.setText(r['day'][5:].replace('-','/')+' 昨日' if self.page not in ('cycle','projects') else '')
                if self.page=='overview':
                    self.stats.report=r;self.stats.update()
                    self.hour_total.setText(compact_tokens(r.get('yesterday_total',0)));self.daily_cost.set_data(r,self.snapshot.get('projects'))
                    if r.get('hours')!=old.get('hours') or r.get('rates')!=old.get('rates'):self.plot.set_data(r)
                    self.readout.setText(self._daily_readout(r))
                    self._update_analogy(r)
                elif self.page=='models':self._update_models()
                elif self.page=='projects':self.project_view.set_data(snapshot.get('projects'),self.period)
                else:self._update_cycle()
                self.note_label.setText(self._note(r));self.update()
                self._update_data_state()
                if self.page=='overview':self.sync_geometry()
                self._refresh_page_frame()
            else:
                self.rebuild();self.sync_geometry();self.chart_entry()
    def _daily_readout(self,r):
        item=(r.get('rates') or {}).get('yesterday_mean') or {}
        return '昨日均速  '+(rate_text(item) if item.get('rate') is not None else '—')
    def open_yesterday_cost(self):
        self.period='yesterday';self.set_page('projects')
        view=self.project_view
        view.search.clear();view.archive='all'
        blocked=view.archive_control.blockSignals(True);view.archive_control.setCurrentIndex(view.archive_control.findData('all'),False);view.archive_control.blockSignals(blocked)
        view.set_data(self.snapshot.get('projects'),'yesterday');view.reset_navigation()

    def show_cost_explanation(self):
        ExplanationOverlay(self.scroll.viewport(),'金额怎么估算',[
            '按本机 Token 记录折算成 API 等价金额，单位为美元。它不是 Plus 或 Pro 订阅账单。',
            '非缓存输入 × 输入价\n＋ 缓存输入 × 缓存价\n＋ 输出 × 输出价',
            '推理已包含在输出中。未知模型、价格或计数不完整的部分不当作零元。',
            '回合均速为输出 Token（含推理）除以整轮任务耗时，包含思考、工具和等待，不能据此直接断定模型限速。首 Token 等待仅在有可靠记录时显示。',
            '昨日按本地时间 00:00–24:00 统计。点击昨日金额可查看当日全部项目，含已归档项目。'])

    def request_refresh(self):
        if self.refresh_busy:return
        self.set_refresh_busy(True);self.refreshRequested.emit()
    def set_refresh_busy(self,busy):
        self.refresh_busy=bool(busy);self.refresh_button.set_busy(self.refresh_busy)
        self.refresh_button.setToolTip('正在刷新数据…' if busy else '刷新数据')
    def finish_refresh(self,success=True):
        self.refresh_busy=False;self.refresh_button.finish(success)
        self.refresh_button.setToolTip('数据已刷新' if success else '刷新失败，保留上次统计；点击重试')
    def _series(self):
        if self.period not in self._series_cache:self._series_cache[self.period]=model_series(self.report,self.period)
        series=self._series_cache[self.period]
        if self.selected_model and not any(item['model']==self.selected_model for item in series['models']):self.selected_model=None
        return series
    def chart_entry(self):
        if not self._animating and not self.follow.active and self.plot:
            self.plot.begin_reveal()
            if self.page_fade.animation.state()==QAbstractAnimation.State.Running:self._refresh_page_frame()
            else:QTimer.singleShot(0,self.plot,self.plot.start_reveal)
    def _refresh_page_frame(self):
        if self.page_fade.slide and self.page_fade.animation.state()==QAbstractAnimation.State.Running:
            self.page_fade.next_frame=self.page_fade.snapshot(self.scroll)
    def set_page(self,page):
        if self.page==page:
            if page=='projects':self.project_view.select(None)
            self.page_buttons[page].setChecked(True);return
        if page=='models' and self.period=='yesterday':self.period='all'
        from settings_controls import motion_enabled
        frame=None;previous=self.page
        if self.isVisible() and not self._animating and not self.follow.active and motion_enabled():
            if self.plot:self.plot.freeze_reveal()
            frame=self.page_fade.current_frame() if self.page_fade.isVisible() else self.page_fade.snapshot(self.scroll)
        from panel_transition import present_barrier
        guarded=self.isVisible() and not self._animating and not self.follow.active and QApplication.platformName()=='windows'
        opacity=self.windowOpacity()
        if guarded:
            self.follow.shield.present(self.grab(),self.geometry());present_barrier();self.setWindowOpacity(0.)
        enabled=self.updatesEnabled();self.setUpdatesEnabled(False)
        try:
            self.page_fade.clear()
            self.page=page;self.rebuild();self.sync_geometry();self.layout.activate()
            if page=='projects':self.project_view.reset_navigation()
            if frame is not None:self.page_fade.hold(frame,self.scroll.geometry())
            self.setUpdatesEnabled(enabled)
            if frame is not None:
                # Resolve only this report's descendants. A global flush can
                # run unrelated card layout work during native handoff.
                from panel_transition import settle_visible
                settle_visible(self.scroll)
                if self.plot:self.plot.begin_reveal()
                target=self.page_fade.snapshot(self.scroll)
                order=('overview','models','cycle','projects')
                self.page_fade.present(frame,target,self.scroll.geometry(),direction=1 if order.index(page)>order.index(previous) else -1)
                self.scroll.repaint()
            else:self.chart_entry()
        finally:
            self.setUpdatesEnabled(enabled)
            if guarded:
                self.repaint();self.setWindowOpacity(opacity);self.repaint();present_barrier()
                self.follow.park(self.follow.shield)
    def _page_motion_finished(self):
        if self.requested and self.isVisible() and self.plot:self.plot.start_reveal()
    def set_period(self,period):
        if self.period==period:
            if period in self.range_buttons:self.range_buttons[period].setChecked(True)
            return
        self.period=period;self.selected_model=None
        self.ensure_chrome(self.report)
        if self._animating or self.follow.active:self._pending_rebuild=True;return
        self.page_fade.clear()
        if self.page=='models' and self.report:self._update_models();self.chart_entry()
        elif self.page=='projects' and hasattr(self,'project_view'):self.project_view.set_data(self.snapshot.get('projects'),self.period)
    def select_model(self,model):
        self.selected_model=None if self.selected_model==model else model
        if self._animating or self.follow.active:self._pending_rebuild=True;return
        self.page_fade.clear()
        if self.page=='models' and self.report:self._update_models();self.chart_entry()
    def _update_models(self):
        series=self._series()
        shown=next((m['total'] for m in series['models'] if m['model']==self.selected_model),series['total'])
        self.model_total.setText('Token  '+compact_tokens(shown))
        self.plot.set_data(self.report,series,self.selected_model)
        for period,button in self.range_buttons.items():button.setChecked(period==self.period)
        if self.period_control:
            blocked=self.period_control.blockSignals(True)
            self.period_control.setCurrentIndex(self.period_control.findData(self.period));self.period_control.blockSignals(blocked)
        items=series['models']
        # Keep the clicked controls and scroll-area alive. Only changed model
        # membership requires new rows; a filter updates their paint state.
        if [r.item['model'] for r in self.model_rows]!=[item['model'] for item in items]:
            while self.model_layout.count():
                w=self.model_layout.takeAt(0).widget()
                if w:w.hide();w.deleteLater()
            self._add_model_rows(series)
            # A refresh may add many models while the viewport already exists.
            # Resolve the new extent now, instead of waiting for a nested
            # LayoutRequest and showing clipped rows until another UI event.
            self.model_layout.invalidate();self.model_layout.activate();body=self.scroll.widget()
            body.layout().invalidate();body.layout().activate()
            self._sync_scroll_extent();body.updateGeometry()
        else:
            for i,(row,item) in enumerate(zip(self.model_rows,items)):
                row.item=item;row.total=series['total'];row.index=i;row.selected=self.selected_model==item['model']
                row.setChecked(row.selected)
                row.setAccessibleName(item['model']+f"  {item['total']:,} Tokens");row.update()
        self._update_filter_label()
        if 'models' in self._body_cache:self._body_cache['models']['model_state']=(self._data_revision,self.period,self.selected_model)
    def _update_filter_label(self):
        if not hasattr(self,'filter_label'):return
        self.filter_label.setText('筛选：'+self.selected_model if self.selected_model else '范围内全部模型')
        self.clear_filter.setVisible(bool(self.selected_model))
    def _cycle_text(self,text,size=12,strong=False):
        label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText)
        label.setFont(font(size,strong));set_theme_style(label,FONT_CSS+f'font-size:{size}px;font-weight:{600 if strong else 500};'
            f'color:{CYCLE_INK if strong else CYCLE_MUTED};background:transparent;')
        return label
    def _cycle_card(self,title,name):
        card=QWidget();set_theme_style(card,f'background:{CYCLE_SURFACE};border-radius:8px;')
        layout=QVBoxLayout(card);layout.setContentsMargins(9,7,9,7);layout.setSpacing(2)
        layout.addWidget(self._cycle_text(title));value=self._cycle_text('—',18,True)
        value.setObjectName(name);layout.addWidget(value)
        return card,value
    def _update_cycle(self):
        self.cycle_view.set_snapshot(self.snapshot)
        if 'cycle' in self._body_cache:self._body_cache['cycle']['cycle_revision']=self._data_revision
    def clear_model_filter(self):
        if self.selected_model:self.select_model(self.selected_model)
    def _add_model_rows(self,series):
        self.model_rows=[]
        for i,item in enumerate(series['models']):
            row=ModelRow(item,series['total'],i,self.selected_model==item['model'],lambda checked=False,m=item['model']:self.select_model(m))
            self.model_rows.append(row);self.model_layout.addWidget(row);row.show()
        if not self.model_rows:self.model_layout.addWidget(self.label('该时间范围内暂无模型用量',11))
    def _note(self,r):
        if self.page=='cycle':return ''
        if self.snapshot.get('unavailable'):return '当前统计暂不可用；图中保留上次成功的本机记录。'
        if self.snapshot.get('readable_files')==0:return '源日志暂不可读；显示本机历史统计，近期用量可能不完整。'
        if self.page=='overview':
            note='本机记录 / API 等价估算 (USD)'
            return note+('  部分日志受限' if self.snapshot.get('partial') else '')+('  部分模型未识别' if r.get('metadata_incomplete') else '')
        note='仅统计本机可读日志；输入含缓存，输出含推理。'
        return note+(' 部分日志受限。' if self.snapshot.get('partial') else '')+(' 部分历史记录缺少模型信息。' if r.get('metadata_incomplete') else '')
    def _update_data_state(self):
        if not hasattr(self,'data_state'):return
        if self.page in ('cycle','projects'):self.data_state.setVisible(False);return
        unavailable=self.snapshot.get('unavailable');partial=self.snapshot.get('partial')
        self.data_state.setText('当前受限  以下为上次成功统计' if unavailable else '部分日志受限  统计可能不完整')
        self.data_state.setVisible(bool(unavailable or partial) and bool(self.report))
    def _update_analogy(self,r):
        data=book_analogy(r.get('all_total',0),self.book_index)
        set_theme_text(self.analogy,'<span style="font-size:11px;font-weight:500;color:#62576e">累计用量相当于约</span><br><span style="font-size:12px;font-weight:500;color:#514360">'+escape(data['quantity']+' 本《'+data['book']['title']+'》')+'</span>')
        self.analogy.setAccessibleName(data['sentence'])
        self.book_estimate.setText(data['estimate'])
        self.book_estimate.setAccessibleName(data['estimate']+'；Project Gutenberg '+data['book']['source']+'；o200k_base 参考计数，非账单精确值')
    def next_book(self):
        self.book_index=(self.book_index+1)%len(book_catalog()['books'])
        self._update_analogy(self.report)
        self.sync_geometry()
    def ensure_chrome(self,r):
        if not hasattr(self,'header_title'):
            header=QWidget();header.setFixedHeight(28);row=QHBoxLayout(header);row.setContentsMargins(0,0,0,0);row.setSpacing(3)
            self.header_title=self.label('数据面板',12,True);self.day_label=self.secondary(self.label('',11));self.day_label.setFixedWidth(76)
            row.addWidget(self.header_title);row.addWidget(self.day_label);row.addStretch();row.addWidget(self.refresh_button);self.refresh_button.show()
            close=action_button('close','关闭数据面板',hit_size=28);close.clicked.connect(self.dismiss);row.addWidget(close);self.layout.addWidget(header)
            nav=QWidget();self.nav_panel=nav;nav_layout=QVBoxLayout(nav);nav_layout.setContentsMargins(0,0,0,0);nav_layout.setSpacing(2)
            tabs=QWidget();tabs.setFixedHeight(27);row=QHBoxLayout(tabs);row.setContentsMargins(0,0,0,0);row.setSpacing(2);nav_layout.addWidget(tabs)
            self.page_buttons={}
            for page,text in [('overview','日报'),('models','模型'),('cycle','额度'),('projects','成本')]:
                b=tab(text,lambda checked=False,k=page:self.set_page(k),False);b.setObjectName('report_'+page);row.addWidget(b);self.page_buttons[page]=b
            row.addStretch()
            self.scope_row=QWidget();self.scope_row.setFixedHeight(27);scope=QHBoxLayout(self.scope_row);scope.setContentsMargins(0,0,0,0);scope.setSpacing(5)
            self.scope_left=QStackedWidget();self.scope_left.setMinimumWidth(0);self.scope_left.setFixedHeight(27)
            self.scope_model_total=ScopeReadout();self.scope_project_search=ProjectSearchBar()
            self.scope_left.addWidget(self.scope_model_total);self.scope_left.addWidget(self.scope_project_search);scope.addWidget(self.scope_left,1);nav_layout.addWidget(self.scope_row)
            control=SlidingSegments([('全部','all'),('月','30d'),('周','7d')],compact=True)
            control.setObjectName('report_periods');control.setFixedWidth(94);self.period_control=control;self.range_buttons=control.buttons
            for period,b in control.buttons.items():
                b.setObjectName('report_range_'+period);b.setAccessibleName({'all':'全部历史','30d':'近30天','7d':'近7天'}[period])
            control.currentIndexChanged.connect(lambda index:self.set_period(control.currentData()));scope.addWidget(control);self.yesterday_scope=tab('昨日 ×',lambda:self.set_period('all'));self.yesterday_scope.setFixedWidth(94);scope.addWidget(self.yesterday_scope);self.yesterday_scope.hide();self.layout.addWidget(nav)
        self.day_label.setText(r.get('day','--')[5:].replace('-','/')+' 昨日' if self.page not in ('cycle','projects') else '')
        for page,b in self.page_buttons.items():b.setChecked(page==self.page)
        show_period=self.page in ('models','projects')
        self.scope_row.setVisible(show_period);self.nav_panel.setFixedHeight(56 if show_period else 27)
        self.period_control.setVisible(show_period and self.period!='yesterday')
        self.yesterday_scope.setVisible(show_period and self.period=='yesterday')
        self.scope_left.setCurrentWidget(self.scope_project_search if self.page=='projects' else self.scope_model_total)
        for b in self.range_buttons.values():b.setVisible(self.page in ('models','projects'))
        blocked=self.period_control.blockSignals(True);self.period_control.setCurrentIndex(self.period_control.findData(self.period),False);self.period_control.blockSignals(blocked)
    def rebuild(self):
        if self._animating or self.follow.active:
            self._pending_rebuild=True;return
        self._building=True
        for cached_page,item in self._body_cache.items():
            if item['refs']['scroll'] is getattr(self,'scroll',None):
                item['refs'].update({name:getattr(self,name) for name in item['refs']})
        while self.layout.count()>2:
            w=self.layout.takeAt(2).widget()
            if w:
                w.hide()
                if not any(item['refs']['scroll'] is w for item in self._body_cache.values()):w.deleteLater()
        width=self.panel_width();self.surface.setFixedWidth(width);r=self.snapshot.get('report') or {};self.report=r
        self.ensure_chrome(r)
        cached=self._body_cache.get(self.page)
        if cached and cached['ready']==bool(r):
            for name,value in cached['refs'].items():setattr(self,name,value)
            self.layout.addWidget(self.scroll,1);self.scroll.show()
            self._update_cached_body(r,cached);self._building=False;self._measure_overview();return
        if cached:
            cached['refs']['scroll'].deleteLater();del self._body_cache[self.page]
        self.readout=None
        self.scroll=QScrollArea();self.scroll.setMinimumSize(0,0);self.scroll.setWidgetResizable(True);self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Keep the existing fixed report canvas and wheel scrolling. The
        # narrow scrollbar is hidden on every page, not replaced by auto-height.
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll._smooth_scroll=SmoothCostScroll(self.scroll)
        body=QWidget();set_theme_style(body,'background:transparent;');content=QVBoxLayout(body);content.setContentsMargins(0,0,2,0);content.setSpacing(4)
        self.data_state=self.label('',11,True);self.data_state.setWordWrap(True);set_theme_style(self.data_state,theme_style_source(self.data_state)+'color:#89566c;');content.addWidget(self.data_state);self._update_data_state()
        if self.page=='projects':
            self.project_view=ProjectCosts(search_bar=self.scope_project_search);self.project_view.set_data(self.snapshot.get('projects'),self.period)
            self.project_view.changed.connect(self._refresh_page_frame);content.addWidget(self.project_view,1)
            self.plot=None;self.body_height=270
        elif not r and self.page!='cycle':
            content.addWidget(self.label('正在整理本机 Token 记录…' if not self.snapshot.get('unavailable') else '统计暂不可用，请稍后刷新'));self.plot=None
            self.body_height=100
        elif self.page=='cycle':
            self.cycle_view=QuotaCompareView();content.addWidget(self.cycle_view)
            self.plot=self.cycle_view.plot;self._update_cycle();self.body_height=290
        elif self.page=='overview':
            self.stats=OverviewStats(r);self.stats.set_columns(width-22);content.addWidget(self.stats)
            chart,chart_layout=self.card('report_hourly_card')
            title=QHBoxLayout();title.setContentsMargins(0,0,0,0)
            self.hour_total=self.label(compact_tokens(r.get('yesterday_total',0)),14,True);self.hour_total.hide()
            self.daily_cost=DailyCostButton();self.daily_cost.set_data(r,self.snapshot.get('projects'));self.daily_cost.clicked.connect(self.open_yesterday_cost)
            chart_layout.addWidget(self.daily_cost)
            self.plot=ReportPlot(r);chart_layout.addWidget(self.plot)
            self.readout=self.secondary(self.label(self._daily_readout(r),9))
            self.readout.setObjectName('report_hourly_readout');chart_layout.addWidget(self.readout)
            # Inspection is shown in the dedicated two-value hover window.
            content.addWidget(chart)
            hint_row=QHBoxLayout();hint_row.setSpacing(4)
            chart_layout.removeWidget(self.readout);hint_row.addWidget(self.readout,1)
            info=tab('估算说明',self.show_cost_explanation,checkable=False);info.setFixedHeight(20);hint_row.addWidget(info);chart_layout.addLayout(hint_row)
            self.body_height=self.stats.height()+94+18+17+20
        else:
            series=self._series()
            shown=next((m['total'] for m in series['models'] if m['model']==self.selected_model),series['total'])
            self.model_total=self.scope_model_total;self.model_total.setText('Token  '+compact_tokens(shown))
            filter_bar=QWidget();filter_layout=QHBoxLayout(filter_bar);filter_layout.setContentsMargins(0,0,0,0);filter_layout.setSpacing(4)
            self.filter_label=self.secondary(self.label('',11));self.filter_label.setWordWrap(True);filter_layout.addWidget(self.filter_label,1)
            self.clear_filter=tab('清除筛选',self.clear_model_filter);self.clear_filter.setObjectName('report_clear_model_filter');filter_layout.addWidget(self.clear_filter);content.addWidget(filter_bar);self._update_filter_label()
            self.plot=ReportPlot(r,'bars',self.period,self.selected_model,series=series);content.addWidget(self.plot)
            denominator=self.secondary(self.label('模型占比 = 该模型 / 当前时间范围全部模型',10));denominator.setWordWrap(True);content.addWidget(denominator)
            self.readout=self.secondary(self.label('点击模型筛选  再点一次还原',9))
            self.plot.hoverText.connect(lambda text,label=self.readout:label.setText(text or '点击模型筛选  再点一次还原'))
            content.addWidget(self.readout)
            model_group=QWidget();self.model_layout=QVBoxLayout(model_group);self.model_layout.setContentsMargins(0,0,0,0);self.model_layout.setSpacing(4)
            self._add_model_rows(series);content.addWidget(model_group)
            self.body_height=163+min(4,max(1,len(series['models'])))*43
        self.body_height+=30
        if self.readout:
            self.readout.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            self.readout.setFixedHeight(max(16,QFontMetrics(self.readout.font()).height()+2))
        if self.page=='overview' and r:
            comparison,comparison_layout=self.card('report_comparison_card');comparison_layout.setSpacing(2)
            line=QHBoxLayout();line.setContentsMargins(0,0,0,0);line.setSpacing(2)
            analogy=self.label('',9);analogy.setTextFormat(Qt.TextFormat.RichText);analogy.setWordWrap(True)
            analogy.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
            self.analogy=analogy;line.addWidget(analogy,1)
            change=action_button('book','换一本书',hit_size=28);change.setObjectName('report_next_book');change.clicked.connect(self.next_book);line.addWidget(change)
            comparison_layout.addLayout(line)
            self.book_estimate=self.secondary(self.label('',8));self.book_estimate.setWordWrap(True);comparison_layout.addWidget(self.book_estimate)
            self._update_analogy(r)
            content.addWidget(comparison)
            self.body_height+=43
        foot=self._cycle_text(self._note(r),strong=False) if self.page=='cycle' else self.secondary(self.label(self._note(r),8))
        foot.setWordWrap(True);self.note_label=foot
        foot.setVisible(self.page not in ('cycle','projects'))
        content.addWidget(foot)
        if self.page!='projects':content.addStretch()
        # Attach once the complete body exists. Showing the scroll area earlier
        # leaves later cards pending ShowToParent, so their height is omitted.
        self.scroll.setWidget(body);self.layout.addWidget(self.scroll,1);self.scroll.show()
        # Measure the whole overview, including wrapped book/source notes.
        # Models reuse this canvas and scroll only when their rows overflow it.
        self._building=False
        self._measure_overview()
        common=('scroll','plot','readout','data_state','note_label','body_height')
        extra={'overview':('stats','hour_total','daily_cost','analogy','book_estimate'),'models':('model_total','filter_label','clear_filter','model_rows','model_layout'),'cycle':('cycle_view',),'projects':('project_view',)}
        names=common+extra[self.page] if r or self.page in ('cycle','projects') else common
        self._body_cache[self.page]=dict(ready=bool(r),refs={name:getattr(self,name) for name in names})
        if self.page=='models':self._body_cache[self.page]['model_state']=(self._data_revision,self.period,self.selected_model)
        if self.page=='cycle':self._body_cache[self.page]['cycle_revision']=self._data_revision
    def _update_cached_body(self,r,cached):
        if r:
            if self.page=='overview':
                self.stats.report=r;self.stats.update();self.hour_total.setText(compact_tokens(r.get('yesterday_total',0)));self.daily_cost.set_data(r,self.snapshot.get('projects'))
                if self.plot.report!=r:self.plot.set_data(r)
                self._update_analogy(r)
            elif self.page=='models' and cached.get('model_state')!=(self._data_revision,self.period,self.selected_model):
                self._update_models();cached['model_state']=(self._data_revision,self.period,self.selected_model)
        if self.page=='cycle' and cached.get('cycle_revision')!=self._data_revision:
            self._update_cycle();cached['cycle_revision']=self._data_revision
        if self.page=='projects':self.project_view.set_data(self.snapshot.get('projects'),self.period)
        self._update_data_state();self.note_label.setText(self._note(r))
    def _measure_overview(self):
        if self.page=='overview':
            for widget in [self.surface]+self.surface.findChildren(QWidget):widget.ensurePolished()
            body=self.scroll.widget();available=max(1,self.surface.width()-20)
            body.ensurePolished();content=body.layout()
            height=content.totalHeightForWidth(available)
            if height<0:height=content.sizeHint().height()
            margins=self.layout.contentsMargins()
            header=sum(max(self.layout.itemAt(i).widget().minimumHeight(),self.layout.itemAt(i).widget().sizeHint().height()) for i in (0,1))
            self._overview_height=473  # Preserve the approved overview canvas; content is compacted within it.
        self.natural_height=self._overview_height
    def reserved_height(self,host_size=None):
        area=(self.bubble.screen() or QApplication.primaryScreen()).availableGeometry()
        height=self.bubble.height() if host_size is None else host_size.height()
        return min(self.natural_height+self.PAD,max(0,area.height()-height-self.GAP)) if self.requested else 0
    def panel_width(self,host=None):
        host=self.bubble.geometry() if host is None else host
        area=(self.bubble.screen() or QApplication.primaryScreen()).availableGeometry()
        return min(max(self.MIN_WIDTH,round(host.width())),max(1,area.width()-2*self.PAD))
    def geometry_for_host(self,host):
        """Small hosts anchor a readable panel; they do not dictate its width."""
        area=(self.bubble.screen() or QApplication.primaryScreen()).availableGeometry()
        width=self.panel_width(host)
        x=round(host.x()+(host.width()-width)/2)
        x=max(area.left()+self.PAD,min(x,area.right()-self.PAD-width+1))
        height=max(1,min(self.natural_height,round(host.y())-area.top()-self.GAP-self.PAD))
        return QRect(x,round(host.y())-self.GAP-height,width,height)
    def toggle(self):self.dismiss() if self.requested else self.open()
    def _host_motion_finished(self):
        transition=self.bubble.size_transition
        if transition.running or transition.preparing:return
        if not self.bubble.isVisible():
            self._host_open_page=None;self._host_prepared_page=None;self._host_return=False;self.requested=False;return
        if self._host_return:
            self._host_return=False;self._restore_host();return
        page=self._host_open_page
        if page is not None:
            prepared=page==self._host_prepared_page
            self._host_open_page=None;self._host_prepared_page=None
            if self.requested:self.open(page,_prepared=prepared)
    def open(self,page='overview',_prepared=False):
        from panel_transition import present_barrier
        self._host_closing=False
        if self._host_open_page is not None or (not self.isVisible() and self.bubble.size_transition.running):
            self._host_open_page=page;self.requested=True;self._host_return=False;return
        reversing=self._animating
        self.animation.stop()
        page=page if page in ('overview','models','cycle','projects') else 'overview'
        if self.page!=page:
            # Prepare the requested body while the surface is still hidden by
            # the old reveal. Never reopen a stale cached page for one frame.
            self.page_fade.clear();self.page=page;self._animating=False;reversing=False
        self.requested=True
        native_open=not self.isVisible() and QApplication.platformName()=='windows'
        opacity=self.windowOpacity()
        try:
            # A hidden layered HWND can retain its last fully open bitmap.
            # Publish the zero-size reveal before making a cold show visible.
            if native_open:self.setWindowOpacity(0.)
            if not reversing:
                if not _prepared:
                    count=len(book_catalog()['books'])
                    self.book_index=(self.book_index+1+random.randrange(count-1))%count if self._book_opened else random.randrange(count)
                    self._book_opened=True
                top=bool(self.bubble.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
                if bool(self.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)!=top:self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,top)
                # All tabs share the overview's measured height. A direct
                # quota-alert entry must measure it while hidden too, rather
                # than open a short cycle page and jump on the next tab.
                if not _prepared:
                    if self.page!='overview':
                        selected=self.page;self.page='overview';self.rebuild();self.page=selected
                    self.rebuild()
                    if self.page=='projects':self.project_view.reset_navigation()
                owner=self.bubble.owner_pet()
                if owner and getattr(owner,'enhanced_ready',False):
                    owner.stop_walk()
                    from settings_controls import motion_enabled
                    transition=self.bubble.size_transition
                    target=self.bubble.content_geometry()
                    # Reserve room once, then let the existing host transaction
                    # move its cached surface. Do not expose the report early.
                    if (not self.isVisible() and motion_enabled() and self.bubble.isVisible()
                        and not transition.running and not transition.preparing and target!=self.bubble.geometry()):
                        self._host_open_page=page;self._host_prepared_page=page;self._host_return=False
                        transition.begin();transition.commit();return
                    owner.position_bubble()
                self.sync_geometry();self._prepare_frame()
            self.show();self.raise_();self._input_passthrough(True)
            self.follow.prewarm()
            if native_open:self.repaint();present_barrier()
        finally:
            if native_open:self.setWindowOpacity(opacity)
        self._start_animation(1.)
    def dismiss(self):
        if self._host_open_page is not None:
            self._host_open_page=None;self._host_prepared_page=None;self.requested=False;self._host_return=True;return
        if not self.requested and not self.isVisible():return
        if self.follow.active:
            if self.follow.committed:self._dismiss_after_host=True;return
            self.follow.cancel()
        self.animation.stop();self.requested=False;self._host_closing=True
        if not self._animating:
            self.sync_geometry();self._prepare_frame()
        self._input_passthrough(True);self._start_animation(0.)
    def _input_passthrough(self,value):
        # Do not recreate the layered window with QWidget.setWindowFlags.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,value)
        if self.windowHandle():self.windowHandle().setFlag(Qt.WindowType.WindowTransparentForInput,value)
    def _prepare_frame(self):
        self.refresh_button.freeze_motion('surface')
        if self.plot:
            if self.requested:self.plot.begin_reveal()
            else:self.plot.freeze_reveal()
        # Nested cards/scroll content must settle before raster capture, rather
        # than processing their first LayoutRequest after the reveal finishes.
        widgets=[self.surface]+self.surface.findChildren(QWidget)
        for widget in reversed(widgets):
            widget.ensurePolished()
            if widget.layout():widget.layout().activate()
        for widget in widgets:
            if widget.layout():widget.layout().activate()
        # Wrapped labels now have their final metrics; settle the complete
        # target before freezing it, never grow a pixel at native handoff.
        self.sync_geometry()
        ratio=self.devicePixelRatioF();size=self.surface.size()
        frame=QPixmap(round(size.width()*ratio),round(size.height()*ratio));frame.setDevicePixelRatio(ratio)
        frame.fill(QColor(theme_color('#fcfafc')))
        self.surface.render(frame,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren)
        self._frame=frame;self._animating=True;self.page_fade.clear()
        button=self.bubble.findChild(QToolButton,'bubble_report')
        x=button.mapToGlobal(button.rect().center()).x() if button and button.isVisible() else self.bubble.geometry().center().x()
        self._merge_anchor=QPointF(x-self.x(),self.bubble.y()+1-self.y())
        # Native children/scroll areas are absent from the animated presentation.
        # The complete opaque image is ready before changing their visibility.
        self.surface.hide();self.repaint()
    def _start_animation(self,target):
        start=self.fraction
        # Changing duration/range can emit valueChanged using the old current
        # time. Configure atomically so a quick reversal never jumps to 1/0.
        blocked=self.animation.blockSignals(True)
        self._motion_start=start;self._motion_target=target
        # island_response is already exactly settled at .82. Preserve its
        # visible trajectory, omit the motionless tail before chart handoff.
        self.animation.setDuration(max(1,round((DISMISS_MS if target==0. else EXPAND_MS*.82)*min(1.,abs(target-start)))))
        self.animation.setStartValue(0.);self.animation.setEndValue(1.);self.animation.setCurrentTime(0)
        self.animation.blockSignals(blocked);self.fraction=start;play_animation(self.animation)
    def content_geometry(self):
        return QRect(self.x()+self.PAD,self.y()+self.PAD,self.surface.width(),self.surface.height())
    def visual_rect(self):
        bounds=QRectF(self.PAD,self.PAD,self.surface.width(),self.surface.height())
        if self._frame is None:return bounds
        # A true zero-size endpoint joins the main surface instead of leaving
        # a floating 132x32 seed in the six-pixel gap.
        f=max(0.,self.fraction);a=self._merge_anchor
        width=bounds.width()*(math.sqrt(f) if f<=1. else 1.+(f-1.)*.35)
        height=bounds.height()*f
        center=a.x()+(bounds.center().x()-a.x())*f
        bottom=a.y()+(bounds.bottom()-a.y())*f
        return QRectF(center-width/2,bottom-height,width,height)
    def visible_height(self):return 0 if self.fraction<=0. else round(self.visual_rect().height())
    def _advance(self,value):
        progress=dismiss_progress(value) if self._motion_target==0. else island_response(value*.82)
        self.fraction=self._motion_start+(self._motion_target-self._motion_start)*progress
        # One fixed-size native window, one raster draw. No move/resize/layout
        # operations on animation frames, in either direction.
        self.repaint()
    def _finished(self):
        from panel_transition import present_barrier
        guarded=self.requested and self._animating and QApplication.platformName()=='windows'
        opacity=self.windowOpacity()
        if guarded:
            self.follow.shield.present(self.grab(),self.geometry());present_barrier()
            self.setWindowOpacity(0.)
        self._animating=False
        if not self.requested:
            self.fraction=0.;self._frame=None;self.surface.hide()
            self.repaint();self.hide();self._restore_host();return
        enabled=self.updatesEnabled();self.setUpdatesEnabled(False)
        try:
            if self._pending_rebuild:
                self._pending_rebuild=False;self.rebuild()
                if self.plot:self.plot.begin_reveal()
            self.fraction=1.;self.sync_geometry();self.surface.move(self.PAD,self.PAD);self.surface.show()
        finally:self.setUpdatesEnabled(enabled)
        # Keep the prepared raster underneath until the live, possibly long-idle
        # child hierarchy has painted at its final native size. The old order
        # dropped _frame before this first real paint, exposing stale/blank
        # scroll-area backing pixels for one compositor frame on Windows.
        self.surface.repaint()
        if self.scroll and self.scroll.isVisible():self.scroll.repaint()
        self.refresh_button.resume_motion('surface')
        self._frame=None;self._input_passthrough(False)
        self.repaint()
        if guarded:
            present_barrier();self.setWindowOpacity(opacity);self.repaint();present_barrier();self.follow.park(self.follow.shield)
        if self.plot:self.plot.start_reveal()
    def _restore_host(self):
        self._host_closing=False;b=self.bubble
        owner=b.owner_pet()
        if self.requested or not b.isVisible() or not owner or not getattr(owner,'enhanced_ready',False):return
        if getattr(getattr(owner,'drag_panel',None),'active',False):return
        transition=b.size_transition
        if transition.running or transition.preparing:self._host_return=True;return
        if b.content_geometry()!=b.geometry():
            transition.begin();transition.commit(preserve_reveals=True)
    def _sync_scroll_extent(self):
        area=getattr(self,'scroll',None);body=area.widget() if area else None
        if body is None or body.layout() is None:return
        content=body.layout();width=max(1,area.viewport().width())
        content.invalidate();content.activate()
        height=content.totalHeightForWidth(width) if self.page!='projects' else content.minimumSize().height()
        if height<0:height=content.sizeHint().height()
        body.setMinimumHeight(max(0,height));body.updateGeometry()
    def sync_geometry(self):
        if self._building or self._syncing or self.follow.active:return
        b=self.bubble
        # A host's union canvas is a presentation surface, not its visible
        # card. A closing report must never chase that temporary native rect.
        if b.size_transition.running or b.size_transition.preparing:return
        if not b.isVisible():self.hide();return
        if self._animating or self.follow.active:
            # Follow an anchor move without invalidating the backing store.
            # Width/height changes wait until the frozen frame is released.
            if self.requested:
                rect=self.geometry_for_host(b.geometry())
                self.move(rect.x()-self.PAD,b.y()-self.GAP-self.surface.height()-self.PAD)
            return
        self._syncing=True
        try:
            width=self.panel_width()
            if self.surface.width()!=width:
                self.surface.setFixedWidth(width)
                if self.page=='overview' and getattr(self,'stats',None):self.stats.set_columns(width-22)
            self._measure_overview()
            rect=self.geometry_for_host(b.geometry());target=rect.height()
            if self.surface.size()!=QSize(width,target):self.surface.setFixedSize(width,target)
            self.surface.move(self.PAD,self.PAD);self.layout.activate()
            self._sync_scroll_extent()
            self.setGeometry(rect.adjusted(-self.PAD,-self.PAD,self.PAD,self.PAD))
            if self.isVisible():self.repaint()
        finally:self._syncing=False
    def eventFilter(self,obj,event):
        if obj is self.bubble:
            if event.type() in (QEvent.Type.Move,QEvent.Type.Resize):
                if not self.follow.active and (self.requested or self.isVisible()):self.sync_geometry()
            elif event.type()==QEvent.Type.Hide:
                self._host_open_page=None;self._host_prepared_page=None;self._host_return=False;self.requested=False;self.hide()
        return False
    def hideEvent(self,event):
        self.page_fade.clear()
        self.follow.cancel()
        self.animation.stop();self.requested=False;self.fraction=0.;self._animating=False;self._frame=None
        self._host_closing=False
        self._input_passthrough(False);self.surface.hide()
        self.refresh_button.resume_motion('surface')
        super().hideEvent(event)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Explicitly clear the previous reveal region in the same backing store.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.follow.active:return  # Only the independent fixed canvas presents linked motion.
        if not self.requested and not self._animating and self.surface.isHidden():return
        content=stage(self.fraction,.02,.28) if self._animating and not self.requested else None
        paint_card(p,self.visual_rect(),self._frame,self.fraction if self._frame is not None else 1.,content_progress=content)
