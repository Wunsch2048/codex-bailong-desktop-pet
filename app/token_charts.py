"""Small, readable token bars and calendar-day hourly consumption curve."""
from theme_registry import color as theme_color,chart_color
from theme_runtime import set_theme_style,theme_style_source
import time
from datetime import datetime
from PySide6.QtCore import Qt,QRectF,QPointF,QEvent,Signal,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QPainter,QPen,QColor,QPainterPath,QFontMetrics
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QToolButton,QToolTip,QSizePolicy
from compact_bubble import font,INK,MUTED,FONT_CSS
from token_calendar import usage_series,compact_tokens,TOKEN_RANGES
from chart_reveal import ChartReveal,RasterChart,bar_shape
from chart_curve import SmoothTrace
from rate_chart import ComboChart,daily_rates
from settings_controls import play_animation

class TokenPlot(QWidget,RasterChart,ComboChart):
    def __init__(self,snapshot,period,parent=None,now=None):
        super().__init__(parent);self.hits=[];self.points=[];self.reveal=ChartReveal(self,420)
        self.init_combo();self.setMouseTracking(True);self.setMinimumWidth(0);self.set_data(snapshot,period,now)

    def set_data(self,snapshot,period,now=None):
        snapshot=snapshot or {};now=time.time() if now is None else now
        same_period=getattr(self,'period',None)==period
        keys=('unavailable','today','hours','hour_models') if period=='day' else ('unavailable','history_days','days')
        bucket=lambda stamp:datetime.fromtimestamp(stamp).strftime('%Y-%m-%d-%H' if period=='day' else '%Y-%m-%d')
        same_series=(same_period and bool(self.snapshot)==bool(snapshot) and bucket(self.now)==bucket(now)
                     and all(self.snapshot.get(key)==snapshot.get(key) for key in keys))
        if same_series and period=='7d':
            same_series=(self.snapshot.get('report') or {}).get('daily_models')==(snapshot.get('report') or {}).get('daily_models')
        rate_key='today' if period=='day' else 'days'
        same_rates=same_period and (self.snapshot.get('rates') or {}).get(rate_key)==(snapshot.get('rates') or {}).get(rate_key)
        if same_rates and period=='day':
            same_rates=(self.snapshot.get('rates') or {}).get('today_output')==(snapshot.get('rates') or {}).get('today_output')
        held=self.hold_inspection() if same_period and not (same_series and same_rates) else None
        if not (same_series and same_rates) and held is None:self.dismiss_inspection()
        self.period=period
        self.snapshot=snapshot;self.now=now
        if not same_series:self.series=usage_series(snapshot,period,now)
        if not (same_series and same_rates):self.invalidate_layers()
        s=self.series;bucket=s.get('bucket_days',1)
        description=f"{s['title']}，{s['total']:,} Tokens；{s['start']} 至 {s['end']}。"
        description+='每小时消耗，非累计曲线；当天00–24时，当前小时尚未结束。' if s['mode']=='line' else f'每根柱覆盖{bucket}天，悬停查看日期与用量。'
        description+='仅本机可读取日志；输入含缓存，输出含推理，均不重复相加。'
        if self.snapshot.get('checked'):description+='截至'+datetime.fromtimestamp(self.snapshot['checked']).strftime('%m-%d %H:%M')+'。'
        if not s['available']:description+='统计中或暂不可用。'
        if self.snapshot.get('partial'):description+='部分日志暂不可读。'
        self.setAccessibleName('Codex Token '+('小时曲线' if s['mode']=='line' else '用量柱状图'))
        rate_description=' 曲线按小时显示采样期间的输出速率。' if period=='day' else ' 回合均速包含思考、工具和等待时间。'
        self.setAccessibleDescription(description+rate_description);self.setToolTip('')
        if not (same_series and same_rates):self.resume_inspection(held);self.update()

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
            items=daily_rates(bins,rates.get('days') or {})
            left,right=s['start'][5:].replace('-','/'),s['end'][5:].replace('-','/')
        hourly=s['mode']=='line'
        self.combo_layers(p,dynamic,bins,items,plot,s['available'],by_model=hourly or self.period=='7d',
                          output_rates=(rates.get('today_output') or []) if hourly else None)
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

class TokenRangeTabs(QWidget):
    """Move one highlight while keeping the chart's compact controls fixed."""
    changed=Signal(str)

    def __init__(self,period,parent=None):
        super().__init__(parent);self.setFixedHeight(18);self.buttons={};self.period=period
        self.pill=QRectF();self.source=QRectF();self.target=QRectF()
        self.animation=QVariantAnimation(self);self.animation.setDuration(170)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic);self.animation.valueChanged.connect(self.advance)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(1)
        for key,text,tip in [('all','全部','全部本机记录；较长时间自动合并日期分组'),('30d','30天','最近30天，每天一根柱'),('7d','7天','最近7天，每天一根柱')]:
            button=QToolButton();button.setObjectName('token_range_'+key);button.setText(text);button.setToolTip(tip)
            button.setAccessibleName(tip);button.setCheckable(True);button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus);button.setCursor(Qt.CursorShape.PointingHandCursor);button.setFixedHeight(18)
            set_theme_style(button,'QToolButton{'+FONT_CSS+'font-size:11px;font-weight:500;color:#76638c;border:0;padding:0;background:transparent;border-radius:4px;}QToolButton:checked{color:#514360;}QToolButton:hover:!checked{background:#eee7f5;}')
            button.clicked.connect(lambda checked=False,k=key:self.changed.emit(k));row.addWidget(button,1);self.buttons[key]=button
        self.select(period,False)

    def select(self,period,animate=True):
        changed=period!=self.period
        self.period=period
        for key,button in self.buttons.items():button.setChecked(key==period)
        if animate and not changed:return
        self.layout().activate()
        button=self.buttons.get(period)
        self.animation.stop();self.source=QRectF(self.pill)
        self.target=QRectF(button.geometry()) if button else QRectF(self.source.center().x(),0,0,self.height())
        if self.source.isEmpty() and button:
            self.source=QRectF(self.target.center().x(),self.target.y(),0,self.target.height())
        if animate and self.isVisible():play_animation(self.animation)
        else:self.advance(1.)

    def advance(self,progress):
        a,z=self.source,self.target;old=self.pill
        self.pill=QRectF(a.x()+(z.x()-a.x())*progress,z.y(),a.width()+(z.width()-a.width())*progress,z.height())
        self.update(old.united(self.pill).adjusted(-1,-1,1,1).toAlignedRect())

    def resizeEvent(self,event):
        super().resizeEvent(event);self.select(self.period,False)

    def hideEvent(self,event):
        self.select(self.period,False);super().hideEvent(event)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(theme_color('#e8def0'));p.drawRoundedRect(self.pill,4,4)


class TokenChartCard(QWidget):
    rangeChanged=Signal(str)
    def __init__(self,snapshot=None,parent=None,period='all',now=None,expanded=False):
        super().__init__(parent);self.setMinimumWidth(0)
        self.period=period if period in TOKEN_RANGES else 'all';self.range_buttons={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        tabs=TokenRangeTabs(self.period);self.range_tabs=tabs;self.range_buttons=tabs.buttons
        tabs.changed.connect(self.rangeChanged.emit)
        layout.addWidget(tabs);self.plot=TokenPlot(snapshot,self.period,self,now);layout.addWidget(self.plot,1)
        if expanded:tabs.hide();self.plot.expanded=True;self.plot.invalidate_layers()
        self.setAccessibleName(self.plot.accessibleName());self.setAccessibleDescription(self.plot.accessibleDescription())

    def set_period(self,period):
        self.period=period
        self.range_tabs.select(period)
        self.plot.set_data(self.plot.snapshot,period);self.plot.begin_reveal();self.plot.start_reveal()
