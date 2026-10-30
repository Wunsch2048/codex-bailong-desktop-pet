"""One-shot local paint progress; static labels and axes stay readable."""
from PySide6.QtCore import QObject,QVariantAnimation,QEasingCurve,QPointF,Qt,QRectF
from PySide6.QtGui import QPixmap,QPainter,QColor,QPainterPath,QPicture
from theme_registry import chart_color

def bar_shape(rect):
    """Shared subtle corners, capped for narrow and near-zero columns.

    Called only when a plot rebuilds its cached layer, never on reveal ticks.
    The original value rectangle and baseline remain unchanged.
    """
    path=QPainterPath()
    if rect.width()>0 and rect.height()>0:
        path.addRoundedRect(rect,min(1.5,rect.width()/3),min(1.5,rect.height()/3))
    return path

class RasterChart:
    """Cache labels and full geometry once; animate only the plotted layer.

    Two small DPR-aware rasters per visible plot, never a sequence of frames.
    Geometry/data revisions invalidate them; elapsed animation time does not.
    """
    def invalidate_layers(self):self._layer_key=None
    def ensure_layers(self):
        ratio=self.devicePixelRatioF();key=(self.width(),self.height(),ratio)
        if getattr(self,'_layer_key',None)==key:return
        layers=[]
        for _ in range(2):
            image=QPixmap(max(1,int(self.width()*ratio+.5)),max(1,int(self.height()*ratio+.5)))
            image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent);layers.append(image)
        # Keep bars as a short native display list during entry. Scaling a
        # raster causes source-row selection to jump near the settled height.
        bars=self.chart_mode()=='bars';commands=QPicture() if bars else None
        static=QPainter(layers[0]);dynamic=QPainter(commands if bars else layers[1])
        try:
            for p in (static,dynamic):p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.render_layers(static,dynamic)
        finally:static.end();dynamic.end()
        if bars:
            raster=QPainter(layers[1]);raster.drawPicture(0,0,commands);raster.end()
        self._bar_commands=commands
        self._layers=layers;self._layer_key=key;self.layer_builds=getattr(self,'layer_builds',0)+1
    def reveal_region(self):
        # Independent of cache construction, safe during layout preparation.
        return self.chart_rect().adjusted(-3,-3,3,3).toAlignedRect()
    def paint_layers(self):
        self.ensure_layers();p=QPainter(self);p.drawPixmap(0,0,self._layers[0])
        chart=self.chart_rect();progress=self.reveal.progress
        if self.chart_mode()=='bars':
            if progress>0:
                p.save();p.setClipRect(chart.adjusted(-1,-1,1,1));p.translate(0,chart.bottom()*(1-progress));p.scale(1,progress)
                if progress<1 and self._bar_commands is not None:p.drawPicture(0,0,self._bar_commands)
                else:p.drawPixmap(0,0,self._layers[1])
                p.restore()
        elif self.points:
            curve=getattr(self,'curve',None)
            head=curve.head(progress) if curve is not None else trace_head(self.points,progress)
            p.save();p.setClipRect(QRectF(chart.left()-2,chart.top()-3,max(0,head.x()-chart.left()+2),chart.height()+6))
            p.drawPixmap(0,0,self._layers[1]);p.restore()
            if progress>0:
                p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(chart_color(original=self.trace_color)));p.drawEllipse(head,2,2)

class ChartReveal(QObject):
    def __init__(self,widget,duration=620):
        super().__init__(widget);self.widget=widget;self.progress=1.;self.pending=False
        self.animation=QVariantAnimation(self);self.animation.setDuration(duration)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.);self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._advance)
    def _advance(self,value):
        self.progress=float(value)
        region=self.widget.reveal_region() if hasattr(self.widget,'reveal_region') else self.widget.rect()
        if self.widget.visibleRegion().intersects(region):self.widget.update(region)
    def prepare(self):
        from settings_controls import motion_enabled
        self.animation.stop();self.pending=motion_enabled();self.progress=0. if self.pending else 1.;self.widget.update()
    def start(self):
        from settings_controls import play_animation
        if self.pending and self.widget.isVisible():self.pending=False;play_animation(self.animation)
    def stop(self):self.animation.stop()

def trace_head(points,progress):
    if not points:return None
    target=points[0].x()+(points[-1].x()-points[0].x())*progress
    for a,b in zip(points,points[1:]):
        if b.x()>=target:
            f=(target-a.x())/max(.0001,b.x()-a.x());return QPointF(target,a.y()+(b.y()-a.y())*f)
    return points[-1]
