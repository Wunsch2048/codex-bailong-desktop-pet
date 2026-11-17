"""Shared pillar/curve drawing and a non-activating, preview-style inspection bubble."""
from datetime import datetime,timedelta
from functools import lru_cache
from bisect import bisect_left,bisect_right
from PySide6.QtCore import Qt,QRectF,QPointF,QPoint,QRect,QTimer,QEvent
from PySide6.QtGui import QPainter,QColor,QPen,QPainterPath,QFontMetrics,QPicture
from PySide6.QtWidgets import QWidget,QToolTip
from chart_curve import SmoothTrace
from chart_reveal import bar_shape
from typography import ui_font
from theme_registry import current,palette,readable,mix
from token_calendar import compact_tokens
from hover_hints import HintBubble

MODEL_SWATCHES=('#d45717','#205de0','#008470','#ad297e','#673ab7','#427c19')
THEME_MODEL_SWATCHES={
    'bailong':('#754ac0','#c65224','#007d77','#a73167','#255dab','#547a15'),
    'mist':('#24559b','#c35b17','#007f6a','#ad327a','#754aba','#617b21'),
    'jade':('#008066','#bc4d25','#4356b6','#a52f76','#946c00','#336ca3'),
    'amber':('#ff6269','#43ccea','#f5c34d','#b59aff','#6ddd93','#fa9552'),
    'night':('#bf94ff','#ffaf58','#4cdbcf','#ff76a7','#76adff','#c2d66c'),
    'cyber':('#ffe629','#46cfee','#ff6c88','#b99aff','#77d991','#fc9251'),
    'starfield':('#ce512b','#325bb7','#008377','#a62d78','#6d4caa','#757214'),
    'division':('#ff8d28','#5ac6f4','#9bd158','#ea81c0','#a89cfa','#edc85b'),
}
THEME_RATE_STROKES={
    'bailong':'#453754',
    'mist':'#424f61',
    'jade':'#344a45',
    'amber':'#e1eef3',
    'night':'#f2d9e8',
    'cyber':'#f0ead0',
    'starfield':'#374b65',
    'division':'#e0e8ee',
}

@lru_cache(maxsize=256)
def _model_color(index,key,panel,surface,ink):
    swatches=THEME_MODEL_SWATCHES.get(key,MODEL_SWATCHES)
    shade=swatches[index] if index<len(swatches) else QColor.fromHsv((index*137)%360,160,220).name()
    return readable(shade,(panel,surface),ink,3)

def model_swatch(index):
    theme=palette()
    return _model_color(index,current(),theme['panel'],theme['surface'],theme['ink'])

def model_segments(values,order):
    ranked=sorted(((model,value) for model,value in values.items() if value>0),
                  key=lambda entry:(-entry[1],entry[0]))
    shown=sorted(ranked[:4],key=lambda entry:order[entry[0]])
    rows=[(model,value,model_swatch(order[model])) for model,value in shown]
    if len(ranked)>4:rows.append(('其他模型',sum(value for _,value in ranked[4:]),palette()['muted']))
    return rows

def colors():
    p=palette()
    bar=readable(mix(p['chart'],p['panel'],.35),(p['panel'],),p['chart'],3)
    line=readable(THEME_RATE_STROKES.get(current(),p['secondary']),(p['panel'],p['surface']),p['ink'],4.5)
    return p,bar,line

def rate_text(item):
    value=(item or {}).get('rate')
    return f'{value:.1f} tok/s' if value is not None else '无有效采样'

def combined_rate(items):
    valid=[item for item in items if item and item.get('rate') is not None]
    if len(valid)==1:return valid[0]
    measured=[item for item in valid if item.get('duration_ms',0)>0 and item.get('output') is not None]
    if not measured or len(measured)!=len(valid):return None
    elapsed=sum(item['duration_ms'] for item in measured)
    output=sum(item['output'] for item in measured)
    return dict(rate=1000*output/elapsed,output=output,duration_ms=elapsed,
                valid_samples=sum(item.get('valid_samples',0) for item in measured))

def daily_rates(bins,days):
    keys=sorted(days)
    return [combined_rate(days[key] for key in keys[bisect_left(keys,b['start']):bisect_right(keys,b['end'])]) for b in bins]

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
        if self.record and 'rows' in self.record:
            groups=self.groups()
            return 254,69+sum(23*len(rows)+8 for rows in groups)
        first=((self.record or {}).get('rate_item') or {}).get('first_token_ms')
        return 254,178 if first is not None else 161
    def groups(self):
        rows=self.record['rows'][1:]
        count=self.record.get('model_count',0)
        return [group for group in (rows[:count],rows[count:]) if group]
    def inspect(self,record,anchor,host):
        self.record=record;owner=host.window()
        placement=(anchor,host.screen().availableGeometry(),self.hint_size(),owner,bool(owner.windowFlags()&Qt.WindowType.WindowStaysOnTopHint))
        if not self.isVisible() or placement!=getattr(self,'_placement',None):
            self.present(record['label'],record.get('subtitle','用量与回合均速'),anchor,host.screen(),owner=owner,
                         topmost=placement[-1],initial_level=1.)
            self._placement=placement
        else:
            self.title=record['label'];self.subtitle=record.get('subtitle','用量与回合均速')
        self.update()
        if 'rows' in record:
            self.setAccessibleDescription('；'.join(f'{name} {value}' for name,value,_ in record['rows']))
            return
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
        p=QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setOpacity(self.level)
        theme,bar,line=colors()
        body=QRectF(1,1,self.width()-2,self.height()-2)
        p.setPen(QPen(QColor(theme['border']),1));p.setBrush(QColor(theme['surface']))
        p.drawRoundedRect(body,9,9)
        p.setFont(ui_font(12,True));p.setPen(QColor(theme['ink']))
        p.drawText(QRectF(11,5,self.width()-22,19),Qt.AlignmentFlag.AlignVCenter,self.record['label'])
        def paint_row(label,value,swatch,y,primary=False):
            if primary:
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(theme['panel']))
                p.drawRoundedRect(QRectF(8,y,self.width()-16,30),6,6)
            height=30 if primary else 23
            if swatch and not primary:
                p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(swatch))
                p.drawRoundedRect(QRectF(13,y+8,6,7),2,2)
            p.setFont(ui_font(17 if primary else 12,True))
            p.setPen(QColor(theme['accentText'] if primary else theme['ink']))
            metrics=p.fontMetrics()
            value=metrics.elidedText(value,Qt.TextElideMode.ElideMiddle,max(0,self.width()-85))
            value_width=metrics.horizontalAdvance(value)
            right=self.width()-13
            p.drawText(QPointF(right-value_width,y+(height+metrics.ascent()-metrics.descent())/2),value)
            p.setFont(ui_font(12 if primary else 11,primary));p.setPen(QColor(theme['ink'] if primary else theme['muted']))
            left=23 if swatch and not primary else 13
            metrics=p.fontMetrics()
            width=max(0,right-value_width-left-8)
            p.drawText(QPointF(left,y+(height+metrics.ascent()-metrics.descent())/2),
                       metrics.elidedText(label,Qt.TextElideMode.ElideRight,width))
        if 'rows' in self.record:
            paint_row(*self.record['rows'][0],28,True)
            y=65
            for rows in self.groups():
                if y>65:
                    p.setPen(QColor(theme['border']));p.drawLine(QPointF(12,y-4),QPointF(self.width()-12,y-4))
                for label,value,swatch in rows:
                    paint_row(label,value,swatch,y);y+=23
                y+=8
            return

        paint_row('Token 用量',self.record['amount'],bar,28,True)
        paint_row('回合均速',self.rate_value(),line,62)
        paint_row('回合中位速率',self.median_value(),None,85)
        p.setPen(QColor(theme['border']));p.drawLine(QPointF(12,111),QPointF(self.width()-12,111))
        p.setFont(ui_font(11));p.setPen(QColor(theme['muted']))
        notes=list(inspection_notes(self.record))
        first=(self.record.get('rate_item') or {}).get('first_token_ms')
        if first is not None:notes.append(f'首 Token 等待 {first/1000:.1f} 秒')
        for i,note in enumerate(notes):
            p.drawText(QRectF(12,116+i*17,self.width()-24,17),Qt.AlignmentFlag.AlignVCenter,note)

class ComboChart:
    def init_combo(self):
        self._inspection=-1;self._combo_records=[];self._rate_points=[];self._popup=ChartBubble();self.destroyed.connect(self._popup.deleteLater)
        self._inspect_delay=QTimer(self);self._inspect_delay.setSingleShot(True);self._inspect_delay.setInterval(350);self._inspect_delay.timeout.connect(self.show_inspection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def combo_layers(self,p,dynamic,bins,rate_items,plot,available=True,by_model=False,output_rates=None,model_order=None,rate_label='回合均速'):
        theme,bar,line=colors();bottom=plot.bottom();n=max(1,len(bins));slot=plot.width()/n
        trace_items=rate_items if output_rates is None else output_rates
        totals={}
        if by_model and available:
            for bucket in bins:
                if bucket.get('future'):continue
                for model,value in bucket.get('models',{}).items():
                    if value>0:totals[model]=totals.get(model,0)+value
        ranked=sorted(totals,key=lambda model:(-totals[model],model))
        order={model:i for i,model in enumerate(ranked)} if model_order is None else model_order
        p.setPen(QPen(QColor(theme['border']),.6))
        for y in (plot.top()+plot.height()/2,bottom):p.drawLine(QPointF(plot.left(),y),QPointF(plot.right(),y))
        top=max((b['value'] for b in bins if not b.get('future')),default=0)
        maximum=max((r['rate'] for r in trace_items if r and r.get('rate') is not None),default=1)*1.1
        maximum=max(.001,maximum);self._rate_points=[];self._combo_records=[];floor_points=[];known=[];self._rate_curves=[];bars=[]
        for i,b in enumerate(bins):
            rect=QRectF(plot.left()+i*slot,plot.top(),slot,plot.height());item=rate_items[i] if available and i<len(rate_items) else None
            trace_item=trace_items[i] if available and i<len(trace_items) else None
            amount='尚未到来' if b.get('future') else compact_tokens(b['value'])+' Token' if available else '暂不可用'
            record=dict(label=b['label'],amount=amount,rate_item=item,rect=rect,future=bool(b.get('future')),available=available)
            segments=model_segments(b.get('models',{}),order) if by_model and available and not b.get('future') else []
            if segments and sum(value for _,value,_ in segments)!=b['value']:segments=[]
            if by_model:
                rows=[('Token 用量',amount,None)]
                if available and not b.get('future'):
                    rows.extend((model,compact_tokens(value),swatch) for model,value,swatch in segments)
                    if output_rates is not None:
                        rows.append(('小时输出速率',rate_text(trace_item),line))
                    if item and item.get('rate') is not None:rows.append((rate_label,rate_text(item),None))
                    if item and item.get('median_rate') is not None:
                        rows.append(('回合中位速率',f"{item['median_rate']:.1f} tok/s",None))
                record.update(rows=rows,model_count=len(segments),subtitle='')
            self._combo_records.append(record)
            x=rect.center().x()
            if not b.get('future') and available:
                height=plot.height()*b['value']/max(1,top)
                column=QRectF(rect.left()+slot*.17,bottom-height,max(.25,slot*.66),height)
                bars.append((column,segments))
            value=(trace_item or {}).get('rate') if not b.get('future') else None
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
            columns.setPen(Qt.PenStyle.NoPen)
            for column,segments in bars:
                shape=bar_shape(column)
                if not segments:
                    columns.fillPath(shape,QColor(bar));continue
                columns.save();columns.setClipPath(shape,Qt.ClipOperation.IntersectClip)
                y=column.bottom()
                for i,(_,value,swatch) in enumerate(segments):
                    height=plot.height()*value/max(1,top)
                    columns.fillRect(QRectF(column.left(),y-height,column.width(),height),QColor(swatch));y-=height
                    if i+1<len(segments) and min(height,plot.height()*segments[i+1][1]/max(1,top))>=3:
                        columns.fillRect(QRectF(column.left(),y-.4,column.width(),.8),QColor(theme['panel']))
                columns.restore()
        finally:columns.end()
        self._combo_trace=QPicture();trace=QPainter(self._combo_trace)
        try:
            trace.setRenderHint(QPainter.RenderHint.Antialiasing)
            trace.setPen(missing_rate_pen(line));trace.setBrush(Qt.BrushStyle.NoBrush);trace.drawPath(missing)
            if by_model:
                trace.setPen(QPen(QColor(theme['panel']),3.2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
                trace.drawPath(solid)
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
    def hold_inspection(self):
        if not 0<=self._inspection<len(self._combo_records):return None
        return (self._combo_records[self._inspection]['label'],self._popup.isVisible(),self._inspect_delay.isActive())
    def resume_inspection(self,state):
        if state is None:return
        self.ensure_layers()
        self._inspection=next((i for i,r in enumerate(self._combo_records) if r['label']==state[0]),-1)
        if self._inspection<0:self.dismiss_inspection();return
        if state[1]:self.show_inspection()
        elif state[2] and not self._inspect_delay.isActive() and self.isVisible():self._inspect_delay.start(1)
        self.update()
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
