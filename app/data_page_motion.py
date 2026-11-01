"""Short body-only crossfade; headers and the native window never disappear."""
from settings_controls import play_animation
from theme_registry import color as theme_color
from PySide6.QtCore import Qt,QVariantAnimation,QEasingCurve,QPoint,QRect
from PySide6.QtGui import QPainter,QPixmap,QColor,QRegion
from PySide6.QtWidgets import QWidget
from ui_theme import SURFACE

def paint_pages(p,rect,first,second,progress,direction=1):
    """Opaque, clipped page travel: text never blends with unrelated text."""
    p.save();p.setClipRect(rect);p.fillRect(rect,QColor(theme_color(SURFACE)))
    offset=round(rect.width()*max(0.,min(1.,progress))*direction)
    for image,x in ((first,-offset),(second,rect.width()*direction-offset)):
        if image is not None:
            target=rect.translated(round(x),0)
            p.drawPixmap(target,image,image.rect())
    p.restore()

class PageFade(QWidget):
    @staticmethod
    def snapshot(widget):
        ratio=widget.devicePixelRatioF()
        image=QPixmap(round(widget.width()*ratio),round(widget.height()*ratio));image.setDevicePixelRatio(ratio)
        # A transparent scroll viewport has no standalone backing background.
        # Seed the actual card colour, otherwise Windows can capture black.
        image.fill(QColor(theme_color(SURFACE)));widget.render(image,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren)
        return image
    @staticmethod
    def snapshot_region(widget,rect):
        """Capture a parent region including overlays and the live child below."""
        rect=QRect(rect);ratio=widget.devicePixelRatioF()
        image=QPixmap(round(rect.width()*ratio),round(rect.height()*ratio));image.setDevicePixelRatio(ratio)
        image.fill(QColor(theme_color(SURFACE)))
        widget.render(image,QPoint(-rect.x(),-rect.y()),QRegion(rect),QWidget.RenderFlag.DrawChildren)
        return image
    def __init__(self,parent):
        super().__init__(parent);self.frame=None;self.next_frame=None;self.progress=0.;self.fade_out=False
        self.direction=1;self.slide=False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);self.hide()
        self.animation=QVariantAnimation(self);self.animation.setDuration(160)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.advance);self.animation.finished.connect(self.clear)
    def present(self,frame,next_frame,rect,fade_out=False,direction=None):
        self.animation.stop();self.frame=frame;self.next_frame=next_frame;self.progress=0.;self.fade_out=bool(fade_out)
        self.slide=direction is not None;self.direction=1 if direction is None or direction>=0 else -1;self.setGeometry(rect)
        self.show();self.raise_();play_animation(self.animation)
    def hold(self,frame,rect):
        self.animation.stop();self.frame=frame;self.next_frame=None;self.progress=0.;self.fade_out=False;self.slide=False
        self.setGeometry(rect);self.show();self.raise_()
    def current_frame(self):
        """Return the pixels currently on screen when a second switch interrupts us."""
        if self.frame is None:return None
        if self.next_frame is None or not self.isVisible():return self.frame
        ratio=self.devicePixelRatioF()
        image=QPixmap(round(self.width()*ratio),round(self.height()*ratio));image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        p=QPainter(image);self._paint(p);p.end()
        return image
    def advance(self,value):
        self.progress=float(value)
        # This short, cached raster is cheap. Paint the animation tick now;
        # queued updates can coalesce while other native surfaces are active.
        self.repaint()
    def clear(self):
        self.animation.stop();self.hide();self.frame=None;self.next_frame=None;self.progress=0.;self.fade_out=False;self.slide=False
    def paintEvent(self,event):
        if self.frame is None:return
        p=QPainter(self);self._paint(p)
    def _paint(self,p):
        if self.slide:
            paint_pages(p,self.rect(),self.frame,self.next_frame,self.progress,self.direction);return
        if self.fade_out:
            p.setOpacity(1.-self.progress);p.drawPixmap(self.rect(),self.frame,self.frame.rect())
        elif self.next_frame is None:p.drawPixmap(self.rect(),self.frame,self.frame.rect())
        else:
            p.drawPixmap(self.rect(),self.next_frame,self.next_frame.rect())
            p.setOpacity(1.-self.progress);p.drawPixmap(self.rect(),self.frame,self.frame.rect())
