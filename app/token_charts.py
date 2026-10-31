"""Small, readable token bars and calendar-day hourly consumption curve."""
from theme_registry import color as theme_color,chart_color
from theme_runtime import set_theme_style,theme_style_source
import time
from datetime import datetime
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent,Signal
from PySide6.QtGui import QPainter,QPen,QColor,QPainterPath,QFontMetrics
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QToolButton,QToolTip,QSizePolicy
from compact_bubble import font,INK,MUTED,FONT_CSS
from token_calendar import usage_series,compact_tokens,TOKEN_RANGES
from chart_reveal import ChartReveal,RasterChart,bar_shape
from chart_curve import SmoothTrace
from rate_chart import ComboChart

class TokenPlot(QWidget,RasterChart,ComboChart):
    def __init__(self,snapshot,period,parent=None,now=None):
        super().__init__(parent);self.hits=[];self.points=[];self.reveal=ChartReveal(self,420)
        self.init_combo();self.setMouseTracking(True);self.setMinimumWidth(0);self.set_data(snapshot,period,now)

    def set_data(self,snapshot,period,now=None):
        self.dismiss_inspection();self.period=period
        self.snapshot=snapshot or {};self.now=time.time() if now is None else now
        self.series=usage_series(snapshot,period,self.now);self.invalidate_layers()
        if period=='all' and self.series.get('bucket_days',1)>1:
            # Keep daily rate observations daily even when long-history usage used grouped columns.
            from datetime import timedelta
            first=datetime.fromisoformat(self.series['start']).date();last=datetime.fromisoformat(self.series['end']).date()
            history=self.snapshot.get('history_days',self.snapshot.get('days',{})) or {}
            self.series['bins']=[dict(start=str(first+timedelta(days=i)),end=str(first+timedelta(days=i)),label=str(first+timedelta(days=i)),value=history.get(str(first+timedelta(days=i)),0),current=first+timedelta(days=i)==last,future=False) for i in range((last-first).days+1)]
            self.series['bucket_days']=1
        s=self.series;bucket=s.get('bucket_days',1)
        description=f"{s['title']}，{s['total']:,} Tokens；{s['start']} 至 {s['end']}。"
        description+='每小时消耗，非累计曲线；当天00–24时，当前小时尚未结束。' if s['mode']=='line' else f'每根柱覆盖{bucket}天，悬停查看日期与用量。'
        description+='仅本机可读取日志；输入含缓存，输出含推理，均不重复相加。'
        if self.snapshot.get('checked'):description+='截至'+datetime.fromtimestamp(self.snapshot['checked']).strftime('%m-%d %H:%M')+'。'
        if not s['available']:description+='统计中或暂不可用。'
        if self.snapshot.get('partial'):description+='部分日志暂不可读。'
        self.setAccessibleName('Codex Token '+('小时曲线' if s['mode']=='line' else '用量柱状图'))
        self.setAccessibleDescription(description+' 回合均速包含思考、工具和等待时间。');self.setToolTip('');self.update()

    def chart_rect(self):
        # Both the title and the mixed Chinese/numeric axis use the shared
        # small-text font. Reserve its actual height instead of a 12px strip.
        expanded=getattr(self,'expanded',False);line_height=QFontMetrics(font(10 if expanded else 11)).height()
        top=3 if expanded else 4;bottom=13 if expanded else line_height+3
        return QRectF(2,top,max(1,self.width()-4),max(5,self.height()-top-bottom))
    def chart_mode(self):return 'combo'
    trace_color='#8d76ab'
    def paintEvent(self,event):self.paint_combo()
    def render_layers(self,p,dynamic):
        return self._render_combo(p,dynamic)
    def _render_combo(self,p,dynamic):
        s=self.series;plot=self.chart_rect();bins=s['bins'];rates=self.snapshot.get('rates') or {}
        if s['mode']=='line':items=rates.get('today') or [];left,right='00时','24时'
        else:
            items=[(rates.get('days') or {}).get(b['start']) for b in bins]
            left,right=s['start'][5:].replace('-','/'),s['end'][5:].replace('-','/')
        self.combo_layers(p,dynamic,bins,items,plot,s['available'])
        self.hits=[(record['rect'],b) for record,b in zip(self._combo_records,bins)]
        self.points=[QPointF(record['rect'].center().x(),plot.bottom()) for record,b in zip(self._combo_records,bins) if not b.get('future') and s['available']]
        p.setFont(font(10 if getattr(self,'expanded',False) else 11));p.setPen(theme_color(MUTED));top=self.height()-QFontMetrics(p.font()).height()-2
        for x,label,align in [(0,left,Qt.AlignmentFlag.AlignLeft),(self.width()/2,right,Qt.AlignmentFlag.AlignRight)]:
            p.drawText(QRectF(x,top,self.width()/2,QFontMetrics(p.font()).height()+2),align|Qt.AlignmentFlag.AlignVCenter,label)
        if s['mode']=='line':p.drawText(QRectF(self.width()/2-14,top,28,QFontMetrics(p.font()).height()+2),Qt.AlignmentFlag.AlignCenter,'12')
        if not s['available']:p.drawText(plot,Qt.AlignmentFlag.AlignCenter,'暂不可用' if self.snapshot.get('unavailable') else '统计中…')
    def detail(self,b):
        if b['future']:value='尚未到来'
        elif not self.series['available']:value='统计暂不可用' if self.snapshot.get('unavailable') else '正在统计…'
        else:value=f"{b['value']:,} Tokens"
        text=b['label']+' · '+value
        if b['current']:text+='\n当前小时尚未结束' if self.series['mode']=='line' else '\n含今天，今日用量仍在更新'
        return text+'\n本机 Codex 日志 · 输入（含缓存）+ 输出（含推理）'
    def begin_reveal(self):self.ensure_layers();self.reveal.prepare()
    def start_reveal(self):self.reveal.start()
    def hideEvent(self,event):self.dismiss_inspection();self.reveal.stop();super().hideEvent(event)
    def leaveEvent(self,event):self.dismiss_inspection();super().leaveEvent(event)
    def mouseMoveEvent(self,event):self.inspect_at(event.position());super().mouseMoveEvent(event)
    def keyPressEvent(self,event):
        if not self.combo_key(event):super().keyPressEvent(event)
    def focusOutEvent(self,event):
        if event.reason()!=Qt.FocusReason.ActiveWindowFocusReason:self.dismiss_inspection()
        super().focusOutEvent(event)

    def event(self,event):
        if event.type()==QEvent.Type.ToolTip:
            QToolTip.hideText();self.inspect_at(QPointF(event.pos()));self.show_inspection();event.accept();return True
        if event.type() in (QEvent.Type.Move,QEvent.Type.Resize) and hasattr(self,'_popup'):self.dismiss_inspection()
        return super().event(event)

class TokenChartCard(QWidget):
    rangeChanged=Signal(str)
    def __init__(self,snapshot=None,parent=None,period='all',now=None,expanded=False):
        super().__init__(parent);self.setMinimumWidth(0)
        self.period=period if period in TOKEN_RANGES else 'all';self.range_buttons={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        tabs=QWidget();tabs.setFixedHeight(18);row=QHBoxLayout(tabs);row.setContentsMargins(0,0,0,0);row.setSpacing(1)
        for key,text,tip in [('all','全部','全部本机记录；较长时间自动合并日期分组'),('30d','30天','最近30天，每天一根柱'),('7d','7天','最近7天，每天一根柱')]:
            button=QToolButton();button.setObjectName('token_range_'+key);button.setText(text);button.setToolTip(tip)
            button.setAccessibleName(tip);button.setCheckable(True);button.setChecked(self.period==key);button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus);button.setCursor(Qt.CursorShape.PointingHandCursor);button.setFixedHeight(18)
            set_theme_style(button,'QToolButton{'+FONT_CSS+'font-size:11px;font-weight:500;color:#76638c;border:0;padding:0;background:transparent;border-radius:4px;}QToolButton:checked{background:#e8def0;color:#514360;}QToolButton:hover{background:#eee7f5;}')
            button.clicked.connect(lambda checked=False,k=key:self.rangeChanged.emit(k));row.addWidget(button,1);self.range_buttons[key]=button
        layout.addWidget(tabs);self.plot=TokenPlot(snapshot,self.period,self,now);layout.addWidget(self.plot,1)
        if expanded:tabs.hide();self.plot.expanded=True;self.plot.invalidate_layers()
        self.setAccessibleName(self.plot.accessibleName());self.setAccessibleDescription(self.plot.accessibleDescription())

    def set_period(self,period):
        self.period=period
        for key,button in self.range_buttons.items():button.setChecked(key==period)
        self.plot.set_data(self.plot.snapshot,period);self.plot.begin_reveal();self.plot.start_reveal()
