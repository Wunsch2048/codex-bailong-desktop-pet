"""Small status island and quota satellite; no per-frame window movement."""
from settings_controls import play_animation
from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
import math,time,re
from PySide6.QtCore import Qt,QRectF,QSize,QTimer,Signal,QPointF,QVariantAnimation,QEasingCurve,QAbstractAnimation
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QFontMetrics,QFontMetricsF
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QToolButton
from typography import ui_font,FONT_CSS
from reset_watch import epoch
from ui_theme import SURFACE,INK,MUTED,ACCENT,TRACK,ISLAND,ON_ISLAND,QUOTA_WEEK,QUOTA_LOW
from chart_reveal import ChartReveal

WIDTH=210
HEIGHT=38
CAPTION_OPTICAL_Y=1.0  # The mathematically centered glyphs looked high; keep the same optical offset during slides.
ICON_OPTICAL_Y=1  # Match the caption's optical center without moving the whole group.

def valid_percent(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<=value<=100

def selected_quota(windows,now=None):
    now=time.time() if now is None else now
    five=next((w for w in windows if w.get('name')=='5小时'),None)
    week=next((w for w in windows if w.get('name')=='一周'),None)
    chosen=five or week or next(iter(windows),dict(name='额度',remaining=None))
    if five:
        reset=epoch(five.get('resetsAt'))
        if not (reset is not None and reset<=now) and valid_percent(five.get('remaining')) and five['remaining']==0 and week:
            chosen=week
    chosen=dict(chosen);reset=epoch(chosen.get('resetsAt'))
    if reset is not None and reset<=now:
        chosen.update(remaining=None,pending=True)
    return chosen

def short_status(icon):
    if getattr(icon,'session_summary',''):return icon.session_summary
    visual=icon.visual()
    if visual=='attention':return '已完成，仍有任务' if icon.is_busy() else '已完成'
    if visual=='complete':return '已确认' if icon.is_busy() else '已完成'
    if visual=='busy':return {'thinking':'思考中','responding':'回复中'}.get(icon.state,'执行中')
    if visual=='waiting':return '待操作'
    if visual=='paused':return '已中断'
    if visual=='warning':return '已中断' if icon.state=='interrupted' else '未连接'
    return '待命'

class IslandCaption(QLabel):
    """One clipped text viewport; semantic text is always the latest status."""
    def __init__(self,parent):
        super().__init__(parent);self.previous='';self.previous_font=ui_font(12,True);self.progress=1.
        self.current_ink=QRectF();self.previous_ink=QRectF()
        self.line_height=QFontMetrics(self.previous_font).height()+4
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    def paintEvent(self,event):
        p=QPainter(self);line=self.line_height
        p.setClipRect(QRectF(0,(self.height()-line)/2,self.width(),line));p.setPen(QColor(theme_color(ON_ISLAND)))
        distance=line;t=self.progress
        if t<1 and self.previous:
            p.setFont(self.previous_font)
            p.drawText(QPointF(1-self.previous_ink.left(),self.height()/2-self.previous_ink.center().y()+CAPTION_OPTICAL_Y-distance*t),self.previous)
        p.setFont(self.font())
        p.drawText(QPointF(1-self.current_ink.left(),self.height()/2-self.current_ink.center().y()+CAPTION_OPTICAL_Y+distance*(1-t)),self.text())

class StatusIsland(QWidget):
    expand=Signal()
    def __init__(self,icon,parent=None):
        super().__init__(parent);self.setObjectName('status_island');self.icon=icon
        self.setFixedSize(124,38);self.setCursor(Qt.CursorShape.PointingHandCursor)
        icon.setParent(self);icon.show()
        self.text=IslandCaption(self);self.text.setFont(ui_font(12,True))
        self._pose=(0.,0.,0.);self._start=self._pose;self._target=self._pose;self._ready=False;self._holds=set()
        self.animation=QVariantAnimation(self);self.animation.setDuration(250)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.valueChanged.connect(self._advance);self.animation.finished.connect(self._settle)
        self.refresh()
    def refresh(self):
        full=short_status(self.icon);budget=self.width()-12-10-16-5-2
        old=self.text.text();old_font=self.text.font();self.text.setFont(ui_font(12,True));text=full
        if QFontMetrics(self.text.font()).horizontalAdvance(text)>budget:
            self.text.setFont(ui_font(11,True))
            for a,b in [('已完成','完成'),('思考中','思考'),('执行中','执行'),('回复中','回复'),('仍有任务','进行中')]:text=text.replace(a,b)
        metrics=QFontMetrics(self.text.font());tail=re.search(r'\s*\+\d+$',text)
        if tail and metrics.horizontalAdvance(text)>budget:
            suffix=tail.group();text=metrics.elidedText(text[:tail.start()],Qt.TextElideMode.ElideRight,max(1,budget-metrics.horizontalAdvance(suffix)))+suffix
        else:text=metrics.elidedText(text,Qt.TextElideMode.ElideRight,budget)
        ink=QFontMetricsF(self.text.font()).tightBoundingRect(text)
        width=max(1,math.ceil(ink.width())+2);group=16+5+width
        left=(self.width()-group)/2;target=(left,left+21,float(width))
        self.setAccessibleName('Codex '+full+'；点击打开正常面板')
        if self._ready and old==text and self._target==target:return
        from settings_controls import motion_enabled
        running=self.animation.state()!=QAbstractAnimation.State.Stopped
        if running:
            if self.text.progress<.5:old=self.text.previous;old_font=self.text.previous_font
            self.animation.stop()
        self.text.previous=old;self.text.previous_font=old_font;self.text.setText(text)
        self.text.current_ink=ink;self.text.previous_ink=QFontMetricsF(old_font).tightBoundingRect(old)
        self.text.line_height=max(metrics.height(),QFontMetrics(old_font).height())+4
        self._start=self._pose;self._target=target
        if self._ready and self.isVisible() and not self._holds and motion_enabled():
            self._advance(0.);play_animation(self.animation)
        else:self._settle()
        self._ready=True
    def _advance(self,fraction):
        self._pose=tuple(a+(b-a)*fraction for a,b in zip(self._start,self._target))
        x,tx,width=self._pose;self.icon.move(round(x),(self.height()-self.icon.height())//2+ICON_OPTICAL_Y)
        # Keep enough text viewport for both strings. Only their clipped
        # drawing and local x position change, never the outer native window.
        viewport=max(width,self._start[2],self._target[2]) if fraction<1 else width
        self.text.setGeometry(round(tx),0,max(1,round(viewport)),self.height())
        self.text.progress=fraction;self.text.update()
    def _settle(self):
        self._advance(1.);self.text.previous=self.text.text();self.text.previous_font=self.text.font()
    def freeze_motion(self,reason='surface'):
        self._holds.add(reason)
        if self.animation.state()==QAbstractAnimation.State.Running:self.animation.pause()
    def resume_motion(self,reason='surface'):
        self._holds.discard(reason)
        if not self._holds and self.isVisible() and self.animation.state()==QAbstractAnimation.State.Paused:self.animation.resume()
    def hideEvent(self,event):
        self.animation.stop();self._settle();super().hideEvent(event)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'text'):self.refresh()
    def mouseReleaseEvent(self,event):
        window=self.window()
        if hasattr(window,'card_pointer_release') and window.card_pointer_release():event.accept();return
        if event.button()==Qt.MouseButton.LeftButton:self.expand.emit();event.accept()
    def paintEvent(self,event):
        p=QPainter(self);self.paint_dial(p)
    def paint_dial(self,p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme_color('#494052')),1));p.setBrush(QColor(theme_color(ISLAND)));p.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),22,22)

class QuotaSatellite(QToolButton):
    resetDue=Signal(float)
    def __init__(self,windows,caption,parent=None):
        super().__init__(parent);self.setObjectName('island_quota');self.windows=windows;self.caption=caption
        self.setFixedSize(38,38);self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.window=selected_quota(windows)
        self.reveal=ChartReveal(self)
        self._reveal_resume_ms=None
        value=self.window.get('remaining')
        exact=f'{value:g}%' if valid_percent(value) else '等待更新' if self.window.get('pending') else '未知'
        self.setAccessibleName(self.window.get('name','额度')+'剩余 '+exact+'；点击展开详情')
        self._prepare_dial()
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self._due)
        five=next((w for w in windows if w.get('name')=='5小时'),None)
        self.reset=epoch((five or self.window).get('resetsAt'))
    def showEvent(self,event):
        super().showEvent(event)
        # Showing a hidden compact surface is a new entry. The bubble owns
        # preparation; never spend the reveal clock under its morph/landing.
        if self.reveal.pending or self._reveal_resume_ms is not None:QTimer.singleShot(0,self,self.start_reveal)
        if self.reset:
            self.timer.start(max(1,min(2147483647,math.ceil((self.reset-time.time())*1000))))
    def begin_reveal(self):self._reveal_resume_ms=None;self.reveal.prepare()
    def start_reveal(self):
        transition=getattr(QWidget.window(self),'size_transition',None)
        if transition and (transition.preparing or transition.running or transition.landing.image is not None):return
        if self._reveal_resume_ms is not None and self.isVisible():
            elapsed=self._reveal_resume_ms;self._reveal_resume_ms=None
            from settings_controls import play_animation
            play_animation(self.reveal.animation);self.reveal.animation.setCurrentTime(elapsed);return
        self.reveal.start()
    def hideEvent(self,event):
        self.timer.stop()
        if self.reveal.animation.state()==self.reveal.animation.State.Running:self._reveal_resume_ms=self.reveal.animation.currentTime()
        self.reveal.stop();super().hideEvent(event)
    def _due(self):self.resetDue.emit(self.reset)
    def value_text(self):
        value=self.window.get('remaining')
        if not valid_percent(value):return '—'
        if 0<value<1:return '<1%'
        return f'{100 if value==100 else min(99,int(value+.5))}%'
    def _prepare_dial(self):
        # The compact preview uses a full circular track with a lighter stroke.
        # Cache all text measurements; reveal frames only change the arc span.
        self._label=self.value_text()
        number=self._label.removesuffix('%');suffix='%' if self._label.endswith('%') else ''
        small=ui_font(11);small.setPixelSize(9)
        for size in (12,11,10):
            main=ui_font(size);main.setPixelSize(size);main.setWeight(QFont.Weight.Medium);main.setStretch(100)
            metrics=QFontMetricsF(main);bounds=metrics.tightBoundingRect(number)
            suffix_x=metrics.horizontalAdvance(number)+.6
            if suffix:bounds=bounds.united(QFontMetricsF(small).tightBoundingRect(suffix).translated(suffix_x,0))
            if bounds.width()**2+bounds.height()**2<=27.6**2:break
        origin=QPointF(20-bounds.center().x(),20-bounds.center().y())
        self._text_runs=[(main,number,origin)]
        if suffix:self._text_runs.append((small,suffix,origin+QPointF(suffix_x,0)))
        self._label_bounds=bounds.translated(origin)
        value=self.window.get('remaining')
        self._fraction=value/100 if valid_percent(value) else 0.
        from theme_registry import palette,quota_ring_color
        colors=palette();self._color=QColor(quota_ring_color(value if valid_percent(value) else None))
        self._arc=QRectF(5,5,30,30)
        self._track_pen=QPen(QColor(theme_color(colors['pillTrack'])),2.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)
        self._value_pen=QPen(self._color,2.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)
    def paintEvent(self,event):
        p=QPainter(self);p.scale(self.width()/40,self.height()/40);self.paint_dial(p)
    def paint_dial(self,p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme_color(ISLAND)))
        p.drawEllipse(QRectF(.5,.5,39,39));p.setBrush(Qt.BrushStyle.NoBrush)
        fraction=self._fraction*self.reveal.progress
        p.setPen(theme_color(self._track_pen));p.drawArc(self._arc,90*16,-360*16)
        if fraction>0:
            p.setPen(theme_color(self._value_pen));p.drawArc(self._arc,90*16,-max(1,round(360*16*fraction)))
        p.setPen(QColor(theme_color(ON_ISLAND)))
        for font,text,origin in self._text_runs:
            p.setFont(font);p.drawText(origin,text)

class MinimalQuota(QuotaSatellite):
    """A single readable quota circle; dragging never expands the panel."""
    def __init__(self,windows,caption,parent=None):
        super().__init__(windows,caption,parent);self.setObjectName('minimal_quota');self.setFixedSize(54,54)
        self.setAccessibleName(self.accessibleName().replace('展开详情','打开正常卡片')+'；可拖动；右键切换模式')
    def paintEvent(self,event):
        p=QPainter(self);p.scale(self.width()/40,self.height()/40);self.paint_dial(p)
    def mousePressEvent(self,event):
        self.parentWidget().window().card_pointer_press(event);super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.parentWidget().window().card_pointer_move(event):self.setDown(False);event.accept();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.parentWidget().window().card_pointer_release():self.setDown(False);event.accept();return
        super().mouseReleaseEvent(event)
