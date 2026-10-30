"""Shared pillar/curve drawing and a non-activating, preview-style inspection bubble."""
from datetime import datetime,timedelta
from PySide6.QtCore import Qt,QRectF,QPointF,QPoint,QRect,QTimer,QEvent
from PySide6.QtGui import QPainter,QColor,QPen,QPainterPath,QFontMetrics,QPicture
from PySide6.QtWidgets import QWidget,QToolTip
from chart_curve import SmoothTrace
from chart_reveal import bar_shape
from typography import ui_font
from theme_registry import palette,readable,mix
from token_calendar import compact_tokens
from hover_hints import HintBubble

def colors():
    p=palette();return p,readable(mix(p['chart'],p['panel'],.35),(p['panel'],),p['chart'],3),readable(p['secondary'],(p['panel'],p['surface']),p['ink'],4.5)

def rate_text(item):
    value=(item or {}).get('rate')
    return f'{value:.1f} tok/s' if value is not None else '无有效采样'

def inspection_notes(record):
    if record.get('future'):return '尚未到来','当前时段之后暂无记录'
    if record.get('available') is False:return '暂不可用','等待用量数据更新'
    item=record.get('rate_item') or {}
    if item.get('rate') is None:return '没有可计算的已完成回合','虚线连接，不表示零速率'
    count=item.get('valid_samples',item.get('samples'))
    return (f'{count} 个已完成回合' if count is not None else '已完成回合均速'),'含思考、工具和等待'

def missing_rate_pen(line):
    weak=QColor(line);weak.setAlphaF(.60)
    pen=QPen(weak,1.3,Qt.PenStyle.CustomDashLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)
    pen.setDashPattern([2.,2.])  # Qt lengths are pen-width units: 2.6px dash/gap.
    return pen

def rate_paths(points,known):
    """Full, floor-connected geometry; preserve unknown semantics outside painting."""
    all_path=SmoothTrace(points).path;solid=QPainterPath();missing=QPainterPath()
    for i in range(max(0,len(points)-1)):
        target=solid if known[i] and known[i+1] else missing
        target.moveTo(points[i]);a,b,c=(all_path.elementAt(1+3*i+j) for j in range(3))
        target.cubicTo(QPointF(a.x,a.y),QPointF(b.x,b.y),QPointF(c.x,c.y))
    return solid,missing

class ChartBubble(HintBubble):
    def __init__(self):super().__init__();self.record=None
    def hint_size(self):
        return 230,161 if ((self.record or {}).get('rate_item') or {}).get('first_token_ms') is not None else 143
    def inspect(self,record,anchor,host):
        self.record=record;p=palette();owner=host.window()
        self.present(record['label'],'用量与回合均速',anchor,host.screen(),owner=owner,
                     topmost=bool(owner.windowFlags()&Qt.WindowType.WindowStaysOnTopHint))
        self.update()
        notes=inspection_notes(record)
        self.setAccessibleName(record['label']);self.setAccessibleDescription(f"用量 {record['amount']}；回合均速 {self.rate_value()}；回合中位速率 {self.median_value()}；{notes[0]}；{notes[1]}")
    def rate_value(self):
        record=self.record or {}
        return '—' if record.get('future') or record.get('available') is False else rate_text(record.get('rate_item'))
    def median_value(self):
        record=self.record or {};value=(record.get('rate_item') or {}).get('median_rate')
        return '—' if record.get('future') or record.get('available') is False or value is None else f'{value:.1f} tok/s'
    def paintEvent(self,event):
        if self.record is None:return
        p=QPainter(self);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source);p.fillRect(self.rect(),Qt.GlobalColor.transparent);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setOpacity(self.level)
        theme,bar,line=colors();body=QRectF(1,5 if self.below else 1,self.width()-2,self.height()-6)
        p.setPen(QPen(QColor(theme['border']),1));p.setBrush(QColor(theme['surface']));p.drawRoundedRect(body,9,9)
        p.setFont(ui_font(10));p.setPen(QColor(theme['muted']));p.drawText(body.adjusted(10,5,-10,-body.height()+23),Qt.AlignmentFlag.AlignVCenter,self.record['label'])
        rows=[('Token 用量',self.record['amount'],bar),('回合均速',self.rate_value(),line),('回合中位速率',self.median_value(),None)]
        for i,(label,value,color) in enumerate(rows):
            y=body.top()+26+i*21;p.setPen(Qt.PenStyle.NoPen)
            if color is not None:p.setBrush(QColor(color))
            if i==0:p.drawRoundedRect(QRectF(11,y+5,5,7),1,1)
            elif i==1:
                missing=(self.record.get('rate_item') or {}).get('rate') is None
                p.setPen(missing_rate_pen(color) if missing else QPen(QColor(color),1.5));p.drawLine(QPointF(10,y+9),QPointF(19,y+9))
            p.setFont(ui_font(10));p.setPen(QColor(theme['muted']));p.drawText(QRectF(23,y,70,18),Qt.AlignmentFlag.AlignVCenter,label)
            p.setFont(ui_font(11,True));p.setPen(QColor(theme['ink']));p.drawText(QRectF(87,y,self.width()-98,18),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,value)
        p.setPen(QPen(QColor(theme['border']),1));p.drawLine(QPointF(11,body.top()+91),QPointF(self.width()-11,body.top()+91))
        p.setFont(ui_font(10));p.setPen(QColor(theme['muted']))
        for i,note in enumerate(inspection_notes(self.record)):
            p.drawText(QRectF(11,body.top()+95+i*17,self.width()-22,17),Qt.AlignmentFlag.AlignVCenter,note)
        first=(self.record.get('rate_item') or {}).get('first_token_ms')
        if first is not None:
            p.drawText(QRectF(11,body.top()+129,self.width()-22,18),Qt.AlignmentFlag.AlignVCenter,f'首 Token 等待 {first/1000:.1f} 秒')

class ComboChart:
    def init_combo(self):
        self._inspection=-1;self._combo_records=[];self._rate_points=[];self._popup=ChartBubble();self.destroyed.connect(self._popup.deleteLater)
        self._inspect_delay=QTimer(self);self._inspect_delay.setSingleShot(True);self._inspect_delay.setInterval(350);self._inspect_delay.timeout.connect(self.show_inspection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def combo_layers(self,p,dynamic,bins,rate_items,plot,available=True):
        theme,bar,line=colors();bottom=plot.bottom();n=max(1,len(bins));slot=plot.width()/n
        p.setPen(QPen(QColor(theme['border']),.6))
        for y in (plot.top()+plot.height()/2,bottom):p.drawLine(QPointF(plot.left(),y),QPointF(plot.right(),y))
        top=max((b['value'] for b in bins if not b.get('future')),default=0)
        maximum=max((r['rate'] for r in rate_items if r and r.get('rate') is not None),default=1)*1.1
        maximum=max(.001,maximum);self._rate_points=[];self._combo_records=[];floor_points=[];known=[];self._rate_curves=[];bars=[]
        for i,b in enumerate(bins):
            rect=QRectF(plot.left()+i*slot,plot.top(),slot,plot.height());item=rate_items[i] if available and i<len(rate_items) else None
            amount='尚未到来' if b.get('future') else compact_tokens(b['value'])+' Token' if available else '暂不可用'
            self._combo_records.append(dict(label=b['label'],amount=amount,rate_item=item,rect=rect,future=bool(b.get('future')),available=available))
            x=rect.center().x()
            if not b.get('future') and available:
                height=plot.height()*b['value']/max(1,top)
                bars.append(bar_shape(QRectF(rect.left()+slot*.17,bottom-height,max(.25,slot*.66),height)))
            value=(item or {}).get('rate') if not b.get('future') else None
            if available and not b.get('future'):
                floor_points.append(QPointF(x,bottom-plot.height()*(value if value is not None else 0)/maximum));known.append(value is not None)
            if value is not None:
                point=QPointF(x,bottom-plot.height()*value/maximum);self._rate_points.append((i,point))
        solid,missing=rate_paths(floor_points,known);self._missing_path=missing;self._solid_rate_path=solid
        # Keep independent display lists, built only with data/geometry. A
        # horizontal wipe of the combined bitmap exposes each column at full
        # height and pauses visually in gaps, rather than growing the bars.
        self._combo_bars=QPicture();columns=QPainter(self._combo_bars)
        try:
            columns.setRenderHint(QPainter.RenderHint.Antialiasing)
            columns.setPen(Qt.PenStyle.NoPen);columns.setBrush(QColor(bar))
            for path in bars:columns.drawPath(path)
        finally:columns.end()
        self._combo_trace=QPicture();trace=QPainter(self._combo_trace)
        try:
            trace.setRenderHint(QPainter.RenderHint.Antialiasing)
            trace.setPen(missing_rate_pen(line));trace.setBrush(Qt.BrushStyle.NoBrush);trace.drawPath(missing)
            trace.setPen(QPen(QColor(line),1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));trace.drawPath(solid)
            # Isolated samples do not turn their unknown neighbours into data.
            for i,point in self._rate_points:
                if (i==0 or not known[i-1]) and (i+1>=len(known) or not known[i+1]):trace.drawEllipse(point,1.1,1.1)
        finally:trace.end()
        dynamic.drawPicture(0,0,self._combo_bars);dynamic.drawPicture(0,0,self._combo_trace)
    def paint_combo(self):
        self.ensure_layers();p=QPainter(self);p.drawPixmap(0,0,self._layers[0]);plot=self.chart_rect()
        progress=max(0.,min(1.,self.reveal.progress))
        if progress>=1.:p.drawPixmap(0,0,self._layers[1])
        elif progress>0.:
            p.save();p.setClipRect(plot.adjusted(-2,-3,2,3))
            p.translate(0,plot.bottom()*(1-progress));p.scale(1,progress)
            p.drawPicture(0,0,self._combo_bars);p.restore()
            p.save();p.setClipRect(QRectF(plot.left()-2,plot.top()-3,(plot.width()+4)*progress,plot.height()+6))
            p.drawPicture(0,0,self._combo_trace);p.restore()
        if 0<=self._inspection<len(self._combo_records) and self.reveal.progress>=.99:
            record=self._combo_records[self._inspection];x=record['rect'].center().x();theme,bar,line=colors();p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(theme['muted']),.7));p.drawLine(QPointF(x,plot.top()),QPointF(x,plot.bottom()))
            for i,point in self._rate_points:
                if i==self._inspection:
                    p.setPen(QPen(QColor(line),1.2));p.setBrush(QColor(theme['panel']));p.drawEllipse(point,2.1,2.1)
    def inspect_at(self,position):
        index=next((i for i,r in enumerate(self._combo_records) if r['rect'].contains(position)),-1)
        if index==self._inspection:return
        self._inspection=index;self.update()
        if index<0:self.dismiss_inspection();return
        if self._popup.isVisible():self.show_inspection()
        else:self._inspect_delay.start()
    def show_inspection(self):
        if not self.isVisible() or self.reveal.progress<.99 or not 0<=self._inspection<len(self._combo_records):return
        rect=self._combo_records[self._inspection]['rect'].toAlignedRect();anchor=QRect(self.mapToGlobal(rect.topLeft()),rect.size())
        self._popup.inspect(self._combo_records[self._inspection],anchor,self)
    def dismiss_inspection(self):
        from shiboken6 import isValid
        if isValid(self._inspect_delay):self._inspect_delay.stop()
        self._inspection=-1
        if isValid(self._popup) and isValid(self._popup.animation):self._popup.dismiss(True)
        self.update()
    def combo_key(self,event):
        if event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Right) and self._combo_records:
            self._inspection=max(0,min(len(self._combo_records)-1,self._inspection+(1 if event.key()==Qt.Key.Key_Right else -1)));self.show_inspection();self.update();return True
        if event.key()==Qt.Key.Key_Escape:self.dismiss_inspection();return True
        return False
