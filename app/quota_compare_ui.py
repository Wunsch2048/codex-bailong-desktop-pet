"""Quota history, styled like the existing data panel."""
from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
from datetime import datetime
from PySide6.QtCore import Qt,QRectF,QPointF,Signal,QTimer,QAbstractAnimation
from PySide6.QtGui import QPainter,QColor,QPen,QFontMetrics
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QSizePolicy,QToolButton,QProgressBar,QScrollArea
from typography import ui_font as font,FONT_CSS
from ui_theme import INK,MUTED,PRIMARY,ACCENT,PANEL,SELECTED,BORDER
from token_calendar import compact_tokens
from chart_reveal import RasterChart,ChartReveal,bar_shape
from choice_controls import ChoiceCombo
from settings_controls import motion_enabled
from card_motion import AnimatedDisclosure
from project_cost_ui import ExplanationOverlay


def date_text(stamp):
    return datetime.fromtimestamp(stamp).strftime('%m/%d')


def text_label(text='',size=11,primary=False):
    label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText);label.setFont(font(size))
    set_theme_style(label,FONT_CSS+f'font-size:{size}px;font-weight:{600 if primary else 400};color:{INK if primary else MUTED};background:transparent;')
    return label


class CyclePlot(QWidget,RasterChart):
    selected=Signal(str);hoverText=Signal(str)
    def __init__(self):
        super().__init__();self.setFixedHeight(94);self.setMouseTracking(True)
        self.cycles=[];self.selected_id=None;self.hits=[];self.points=[];self._resume_time=None
        self.reveal=ChartReveal(self);self._left=38;self._max=1
    def set_data(self,cycles,selected):
        ordered=list(reversed(cycles));index=next((i for i,c in enumerate(ordered) if c['id']==selected),len(ordered)-1)
        start=max(0,min(index-4,len(ordered)-8));shown=ordered[start:start+8]
        if self.cycles==shown and self.selected_id==selected:return
        self.cycles=shown;self.selected_id=selected
        self._max=max([max(c['used'],c.get('estimated_total') or 0) for c in shown]+[1])
        fm=QFontMetrics(font(11));self._left=max(37,max(fm.horizontalAdvance(compact_tokens(round(self._max*f))) for f in (0,.5,1))+6)
        self.invalidate_layers();self.update()
    def chart_mode(self):return 'bars'
    def chart_rect(self):return QRectF(self._left,10,max(1,self.width()-self._left-4),65)
    def paintEvent(self,event):self.paint_layers()
    def render_layers(self,p,dynamic):
        chart=self.chart_rect();p.setFont(font(11));fm=QFontMetrics(p.font());self.hits=[]
        for f in (0,.5,1):
            y=chart.bottom()-chart.height()*f;p.setPen(QPen(QColor(theme_color(BORDER)),.7));p.drawLine(QPointF(chart.left(),y),QPointF(chart.right(),y))
            p.setPen(QColor(theme_color(MUTED)));value=compact_tokens(round(self._max*f))
            p.drawText(QPointF(chart.left()-5-fm.horizontalAdvance(value),y+(fm.ascent()-fm.descent())/2),value)
        slot=chart.width()/max(1,len(self.cycles))
        for i,c in enumerate(self.cycles):
            x=chart.left()+i*slot+2;width=max(2,slot-4)
            estimate=c.get('estimated_total') or 0
            if estimate:
                height=chart.height()*estimate/self._max
                dynamic.fillPath(bar_shape(QRectF(x,chart.bottom()-height,width,height)),QColor(theme_color(SELECTED)))
            height=chart.height()*c['used']/self._max
            dynamic.fillPath(bar_shape(QRectF(x,chart.bottom()-height,max(2,width*.55),height)),QColor(theme_color(ACCENT)))
            if c['id']==self.selected_id:
                dynamic.setPen(QPen(QColor(theme_color(PRIMARY)),1.2));dynamic.drawLine(QPointF(x,chart.bottom()),QPointF(x+width,chart.bottom()))
            self.hits.append((QRectF(x,chart.top(),width,chart.height()),c))
        p.setPen(QColor(theme_color(MUTED)))
        if self.cycles:
            p.drawText(QRectF(chart.left(),77,48,16),Qt.AlignmentFlag.AlignLeft,date_text(self.cycles[0]['start']))
            p.drawText(QRectF(chart.right()-48,77,48,16),Qt.AlignmentFlag.AlignRight,date_text(self.cycles[-1]['start']))
        else:p.drawText(chart,Qt.AlignmentFlag.AlignCenter,'暂无历史额度记录')
    def mouseMoveEvent(self,event):
        for rect,c in self.hits:
            if rect.contains(event.position()):
                self.hoverText.emit(date_text(c['start'])+' 已用 '+compact_tokens(c['used'])+' / 推测 '+(compact_tokens(c['estimated_total']) if c.get('estimated_total') else '—'));return
        self.hoverText.emit('')
    def leaveEvent(self,event):self.hoverText.emit('');super().leaveEvent(event)
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            for rect,c in self.hits:
                if rect.contains(event.position()):self.selected.emit(c['id']);break
        super().mouseReleaseEvent(event)
    def begin_reveal(self):
        self.ensure_layers();self._resume_time=None
        self.reveal.prepare()
    def freeze_reveal(self):
        self._resume_time=self.reveal.animation.currentTime() if self.reveal.animation.state()==QAbstractAnimation.State.Running else None
        self.reveal.stop()
    def start_reveal(self):
        if not motion_enabled():self._resume_time=None;self.reveal.prepare();return
        if self._resume_time is not None and self.isVisible():
            value=self._resume_time;self._resume_time=None;self.reveal.animation.start();self.reveal.animation.setCurrentTime(value)
        else:self.reveal.start()
    def showEvent(self,event):
        super().showEvent(event)
        if self.reveal.pending or self._resume_time is not None:QTimer.singleShot(0,self,self.start_reveal)
    def hideEvent(self,event):self.reveal.stop();super().hideEvent(event)


class CycleChoice(ChoiceCombo):
    title='选择额度周期'
    def display_text(self):return self.title


def cycle_messages(c,history):
    """Presentation only: keep estimate readiness separate from comparison readiness."""
    if c is None:
        return dict(estimate='等待周额度记录',title='暂无可对比周期',reason='记录额度与 Token 后，才能估算可用总量。',coverage=0,show_coverage=False)
    drop=c.get('drop',0);estimate=c.get('estimated_total')
    if history.get('pending'):estimate_note='正在补齐历史记录'
    elif not c.get('complete'):estimate_note='记录受限，暂不估算'
    elif not c.get('fresh'):estimate_note='刷新额度后再估算'
    elif c.get('rise_pending'):estimate_note='额度回升待确认'
    elif c.get('corrected'):estimate_note='额度读数曾回升，暂停估算'
    elif estimate:estimate_note='每 1% ≈ '+compact_tokens(round(c['per_percent']))+' Token' if c.get('per_percent') else '基于本机额度与 Token 记录估算'
    elif drop<5:
        estimate_note=(f'再观察 {5-drop:g} 个百分点可估算总量' if not c['closed'] else f'仅观察 {drop:g} 个百分点，未达估算门槛')
    else:estimate_note='缺少有效 Token 记录，暂不估算'
    # This is a second, stricter gate. Passing it alone does not prove a match.
    show_coverage=False
    if history.get('pending'):title='历史记录整理中';reason='整理完成后再比较总量。'
    elif not c.get('complete'):title='记录受限，暂不能比较';reason='补齐本机记录后再判断总量变化。'
    elif not c.get('fresh'):title='等待最新额度';reason='刷新后再比较总量。'
    elif c.get('rise_pending'):title='额度回升待确认';reason='等待后续读数确认，再继续估算与比较。'
    elif c.get('corrected'):title='额度读数回升，暂停比较';reason='多次读数确认回升，这轮暂不用于总量比较。'
    elif not c.get('plan'):title='缺少套餐记录';reason='需要确认同一套餐，避免把套餐差异当作缩水。'
    elif drop<20:
        title='尚不能判断总量变化';show_coverage=True
        reason=(f'再观察 {20-drop:g} 个百分点，才达对比门槛。' if not c['closed'] else '此周期未达到 20 个百分点，不能用于历史对比。')
    elif c.get('distinct_readings',3)<3:title='额度读数不足';reason='需要至少 3 个不同的剩余额度读数。'
    elif not c.get('model') or c.get('model')=='未识别模型' or c.get('output_share') is None:title='模型记录不完整';reason='需要主模型及输入输出记录，才能筛选相近周期。'
    elif c.get('model_share',0)<.7:title='模型使用较分散';reason='主模型用量占比达到 70% 后，再比较总量。'
    elif c.get('comparison_block'):
        title='使用条件不可比';reason=c['comparison_block']+'。预计容量仍按本轮用法保留。'
    elif c.get('change') is not None:
        change=c['change'];title=('推测容量减少 ' if change<0 else '推测容量增加 ' if change>0 else '推测容量基本持平')+(f'{abs(change):.1f}%' if change else '')
        reason='相近使用条件下对照上一周期，不代表官方额度变动。'
    elif not estimate:title='有效用量不足';reason='缺少与额度读数对应的 Token，暂不能比较。'
    elif '套餐已变更' in c.get('comparison_reason',''):title='套餐变化，不直接比较';reason='改用当前套餐重新积累可比周期。'
    else:title='上一周期暂不能用于比较';reason=c.get('comparison_reason') or '等待上一周期的有效记录。'
    if c.get('capacity_factor',1)>1:
        reason='本周期疑似扩容，已换算此前的额度读数。'+reason
    return dict(estimate=estimate_note,title=title,reason=reason,coverage=drop,show_coverage=show_coverage)


class QuotaCompareView(QWidget):
    def __init__(self):
        super().__init__();self.cycles=[];self.selected_id=None;self.history={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(5)
        navigation=QWidget();nav=QHBoxLayout(navigation);nav.setContentsMargins(0,0,0,0);nav.setSpacing(4)
        self.previous=QToolButton();self.next=QToolButton()
        for button,text,title in [(self.previous,'‹','查看更早一轮额度'),(self.next,'›','查看更新一轮额度')]:
            button.setText(text);button.setAccessibleName(title);button.setFixedSize(28,28);button.setCursor(Qt.CursorShape.PointingHandCursor)
            set_theme_style(button,'QToolButton{'+FONT_CSS+f'font-size:16px;color:{PRIMARY};border:0;background:{PANEL};border-radius:7px;}}'
                f'QToolButton:hover{{background:{SELECTED};}}QToolButton:pressed{{background:{BORDER};}}QToolButton:disabled{{color:{BORDER};}}')
        self.choice=CycleChoice();self.choice.setObjectName('quota_cycle_choice');self.choice.setAccessibleName('选择哪一轮额度')
        nav.addWidget(self.previous);nav.addWidget(self.choice,1);nav.addWidget(self.next);layout.addWidget(navigation)
        self.period_line=text_label();self.period_line.setWordWrap(True);layout.addWidget(self.period_line)
        self.previous.clicked.connect(lambda:self.choice.setCurrentIndex(self.choice.currentIndex()+1))
        self.next.clicked.connect(lambda:self.choice.setCurrentIndex(self.choice.currentIndex()-1))
        self.choice.currentIndexChanged.connect(self.select_current)
        metrics,box=self.section('quota_current_section')
        row=QHBoxLayout();row.setSpacing(8)
        for title,name in [('本机已用 Token','used'),('当前用法推测','estimate')]:
            column=QVBoxLayout();column.setSpacing(1);column.addWidget(text_label(title))
            value=text_label('—',16,True);value.setObjectName('quota_cycle_'+name);setattr(self,name,value);column.addWidget(value);row.addLayout(column,1)
        box.addLayout(row)
        self.detail=text_label('',11,True);box.addWidget(self.detail)
        self.estimate_hint=text_label();self.estimate_hint.setWordWrap(True);box.addWidget(self.estimate_hint);layout.addWidget(metrics)
        comparison,box=self.section('quota_comparison_section')
        heading=text_label('与上一周期比较总量',12);set_theme_style(heading,FONT_CSS+f'font-size:12px;font-weight:500;color:{PRIMARY};background:transparent;');box.addWidget(heading)
        self.comparison=text_label('',12,True);self.comparison.setWordWrap(True);box.addWidget(self.comparison)
        self.comparison_reason=text_label();self.comparison_reason.setWordWrap(True);box.addWidget(self.comparison_reason)
        self.coverage_text=text_label();box.addWidget(self.coverage_text)
        self.coverage=QProgressBar();self.coverage.setRange(0,200);self.coverage.setFixedHeight(4);self.coverage.setTextVisible(False)
        set_theme_style(self.coverage,f'QProgressBar{{border:0;border-radius:2px;background:{BORDER};}}QProgressBar::chunk{{border-radius:2px;background:{ACCENT};}}');box.addWidget(self.coverage)
        layout.addWidget(comparison)
        chart,box=self.section('quota_history_section',False)
        line=QHBoxLayout();line.setSpacing(5)
        self.readout=text_label('历史周期',12,True);self.readout.setFixedHeight(18);self.readout.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);line.addWidget(self.readout,1)
        self.legend=QWidget();legend=QHBoxLayout(self.legend);legend.setContentsMargins(0,0,0,0);legend.setSpacing(4)
        for title,color in [('已用',ACCENT),('推测',SELECTED)]:
            swatch=QWidget();swatch.setFixedSize(7,7);set_theme_style(swatch,f'background:{color};border-radius:2px;');legend.addWidget(swatch);legend.addWidget(text_label(title))
        line.addWidget(self.legend);box.addLayout(line)
        self.plot=CyclePlot();self.plot.selected.connect(self.select_id);box.addWidget(self.plot);layout.addWidget(chart)
        self.plot.hoverText.connect(self.show_plot_readout)
        self.rules_button=QToolButton();self.rules_button.setText('估算与对比条件  ›');self.rules_button.setCheckable(True);self.rules_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rules_button.setAccessibleName('展开估算与历史对比条件');set_theme_style(self.rules_button,'QToolButton{'+FONT_CSS+f'border:0;border-radius:6px;padding:4px 2px;color:{PRIMARY};font-size:11px;}}QToolButton:hover{{background:{PANEL};}}QToolButton:pressed{{background:{SELECTED};}}');layout.addWidget(self.rules_button,0,Qt.AlignmentFlag.AlignLeft)
        rules=QWidget();box=QVBoxLayout(rules);box.setContentsMargins(0,0,0,0);box.setSpacing(6)
        self.note=text_label('估算总量：已记录的额度下降达到 5 个百分点，且对应 Token 记录完整、额度新鲜、读数连续。');self.note.setWordWrap(True);box.addWidget(self.note)
        conditions=text_label('仅对比上一周期：两轮均观察至少 20 个百分点、至少 3 个不同余额读数；同套餐与重置类型，且模型分布、缓存、输入输出、速度和推理档位接近。');conditions.setWordWrap(True);box.addWidget(conditions)
        caveat=text_label('推测容量随使用方式变化，不是固定 Token 池。条件缺失或不同仍保留估算，但不提示涨跌；不能据此确认官方额度缩水。');caveat.setWordWrap(True);box.addWidget(caveat)
        self.conditions=conditions;self.caveat=caveat
        self.quality=text_label();self.quality.setWordWrap(True);box.addWidget(self.quality)
        self.rules=AnimatedDisclosure(rules,background=PANEL);layout.addWidget(self.rules)
        self.rules_button.toggled.connect(self.toggle_rules)
    def show_plot_readout(self,value):
        self.legend.setVisible(not value);self.readout.setText(value or '历史周期');self.plot.setAccessibleDescription(value)
    def section(self,name,filled=True):
        card=QWidget();card.setObjectName(name);set_theme_style(card,f'QWidget#{name}{{background:{PANEL if filled else "transparent"};border-radius:8px;}}')
        box=QVBoxLayout(card);box.setContentsMargins(8 if filled else 0,6 if filled else 0,8 if filled else 0,6 if filled else 0);box.setSpacing(3)
        return card,box
    def toggle_rules(self,value):
        self.rules_button.setText('估算与对比条件  ⌄' if value else '估算与对比条件  ›')
        if not value:return
        self.rules_button.setChecked(False)
        host=self
        ancestor=self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor,QScrollArea):host=ancestor.viewport();break
            ancestor=ancestor.parentWidget()
        self.explanation=ExplanationOverlay(host,'估算与对比条件',[
            self.note.text(),
            self.conditions.text(),self.caveat.text(),
            self.quality.text()])
    def set_snapshot(self,snapshot):
        self.history=snapshot.get('quota_history') or {};self.cycles=self.history.get('cycles') or []
        if self.selected_id not in {c['id'] for c in self.cycles}:self.selected_id=self.cycles[0]['id'] if self.cycles else None
        labels=[(self.caption(c),c['id']) for c in self.cycles]
        if labels!=[(self.choice.itemText(i),self.choice.itemData(i)) for i in range(self.choice.count())]:
            blocked=self.choice.blockSignals(True);self.choice.clear()
            for title,key in labels:self.choice.addItem(title,key)
            self.choice.setCurrentIndex(self.choice.findData(self.selected_id));self.choice.blockSignals(blocked)
        self.update_selected()
    def caption(self,c):
        return self.cycle_title(c)+'  '+datetime.fromtimestamp(c['start']).strftime('%m/%d %H:%M')
    def cycle_title(self,c):
        if not c['closed']:return '本轮额度'
        index=next((i for i,x in enumerate(self.cycles) if x['id']==c['id']),0)
        rank=index+(1 if self.cycles and self.cycles[0]['closed'] else 0)
        return '上一轮额度' if rank<=1 else f'前{rank}轮额度'
    def select_current(self,*args):
        self.selected_id=self.choice.currentData();self.update_selected()
    def select_id(self,key):self.choice.setCurrentIndex(self.choice.findData(key))
    def update_selected(self):
        c=next((c for c in self.cycles if c['id']==self.selected_id),None)
        self.choice.setEnabled(bool(self.cycles));self.plot.set_data(self.cycles,self.selected_id)
        index=self.choice.currentIndex();self.previous.setEnabled(index>=0 and index<len(self.cycles)-1);self.next.setEnabled(index>0)
        presentation=cycle_messages(c,self.history)
        self.estimate_hint.setText(presentation['estimate']);self.estimate_hint.setVisible(not c or not c.get('estimated_total'));self.comparison.setText(presentation['title']);self.comparison_reason.setText(presentation['reason'])
        self.coverage.setVisible(presentation['show_coverage']);self.coverage_text.setVisible(presentation['show_coverage'])
        self.coverage.setValue(round(min(20,presentation['coverage'])*10));self.coverage_text.setText(f"已观察 {presentation['coverage']:g} / 20 个百分点")
        if not c:
            self.choice.title='暂无额度周期';self.choice.update();self.period_line.setText('重置后开始记录新一轮')
            self.used.setText('—');self.estimate.setText('—');self.detail.setText('');self.quality.setText('缺少额度记录，无法只靠 Token 还原总量。');return
        self.choice.title=self.cycle_title(c);self.choice.update()
        begin=datetime.fromtimestamp(c['start']).strftime('%m/%d %H:%M')
        end=datetime.fromtimestamp(c['end']).strftime('%m/%d %H:%M') if c['closed'] else '至今'
        kind={'natural':'自然重置','extra':'额外补充','inferred':'起点推定','changed':'套餐或窗口变化'}.get(c['kind'],'起点推定')
        self.period_line.setText(begin+' — '+end+'  '+kind)
        self.used.setText(compact_tokens(c['used']));self.estimate.setText(compact_tokens(c['estimated_total']) if c['estimated_total'] else '—')
        self.detail.setText(f"剩余 {c['remaining']:g}%"+('  '+str(c['plan']).upper() if c.get('plan') else ''))
        parts=[]
        if self.history.get('pending'):parts.append('正在补齐历史记录')
        elif not c['complete']:parts.append('部分记录受限')
        elif c.get('cached'):parts.append('保留上次完整统计')
        elif not c['fresh']:parts.append('额度待刷新')
        elif c.get('rise_pending'):parts.append('额度回升待确认')
        elif c.get('corrected'):parts.append('额度读数曾回升，本轮不推测')
        else:parts.append(f"已记录额度下降 {c['drop']:g} 个百分点")
        if c.get('per_percent'):parts.append('每 1% ≈ '+compact_tokens(round(c['per_percent']))+' Token')
        if c.get('model'):parts.append('主模型 '+c['model']+f"（{c.get('model_share',0):.0%}）")
        self.quality.setText('\n'.join(parts))
        if self.rules.expanded:self.rules.refresh_content()
