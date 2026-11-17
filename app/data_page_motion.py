"""Body-only page transitions that leave the native window in place."""
from settings_controls import motion_enabled,play_animation
from theme_registry import color as theme_color
from PySide6.QtCore import Qt,QVariantAnimation,QEasingCurve,QPoint,QRect,QEvent,QTimer
from PySide6.QtGui import QPainter,QPixmap,QColor,QRegion
from PySide6.QtWidgets import QWidget
from ui_theme import SURFACE

def paint_pages(p,rect,first,second,progress,direction=1,axis='horizontal'):
    """Opaque, clipped page travel: text never blends with unrelated text."""
    p.save();p.setClipRect(rect);p.fillRect(rect,QColor(theme_color(SURFACE)))
    vertical=axis=='vertical';extent=rect.height() if vertical else rect.width()
    offset=round(extent*max(0.,min(1.,progress))*direction)
    for image,x in ((first,-offset),(second,extent*direction-offset)):
        if image is not None:
            target=rect.translated(0,round(x)) if vertical else rect.translated(round(x),0)
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
        self.direction=1;self.slide=False;self.axis='horizontal'
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);self.hide()
        self.animation=QVariantAnimation(self);self.animation.setDuration(160)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.advance);self.animation.finished.connect(self.clear)
    def present(self,frame,next_frame,rect,fade_out=False,direction=None,axis='horizontal'):
        self.animation.stop();self.frame=frame;self.next_frame=next_frame;self.progress=0.;self.fade_out=bool(fade_out)
        self.axis=axis
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
            paint_pages(p,self.rect(),self.frame,self.next_frame,self.progress,self.direction,self.axis);return
        if self.fade_out:
            p.setOpacity(1.-self.progress);p.drawPixmap(self.rect(),self.frame,self.frame.rect())
        elif self.next_frame is None:p.drawPixmap(self.rect(),self.frame,self.frame.rect())
        else:
            p.drawPixmap(self.rect(),self.next_frame,self.next_frame.rect())
            p.setOpacity(1.-self.progress);p.drawPixmap(self.rect(),self.frame,self.frame.rect())


class ReportSubpage(QWidget):
    """Slide a child page over a fixed report viewport and restore it on Back."""

    def __init__(self,parent):
        super().__init__(parent)
        self.hide()
        self._motion_ticket=0
        self._returning=False
        self._capturing_return=False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.page_motion=PageFade(self)
        self.page_motion.animation.finished.connect(self.motion_finished)
        parent.installEventFilter(self)

    def show_page(self,entry_frame=None):
        parent=self.parentWidget()
        entry=entry_frame
        if entry is None and parent.isVisible() and parent.updatesEnabled() and motion_enabled():
            entry=PageFade.snapshot(parent)
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        if entry is not None:
            self._motion_ticket+=1
            ticket=self._motion_ticket
            self.page_motion.hold(entry,self.rect())
            QTimer.singleShot(0,self,lambda:self.present_entry(ticket,entry))
    def present_entry(self,ticket,frame):
        if ticket!=self._motion_ticket:return
        if not self.isVisible() or not self.updatesEnabled() or not motion_enabled():self.page_motion.clear();return
        try:
            from panel_transition import settle_visible
            self.page_motion.hide();settle_visible(self)
            target=PageFade.snapshot(self)
            self.page_motion.animation.setDuration(220);self.page_motion.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.page_motion.present(frame,target,self.rect(),direction=1)
        except Exception:self.page_motion.clear();raise
    def go_back(self):
        if self._returning:return
        parent=self.parentWidget()
        if not self.isVisible() or not self.updatesEnabled() or not parent.isVisible() or not motion_enabled():self.close();return
        self._motion_ticket+=1
        frame=self.page_motion.current_frame() if self.page_motion.isVisible() else PageFade.snapshot(self)
        self.page_motion.clear()
        try:
            self._capturing_return=True;self.hide()
            from panel_transition import settle_visible
            settle_visible(parent);target=PageFade.snapshot(parent)
            self.show();self.raise_();self._capturing_return=False;self._returning=True
            self.page_motion.animation.setDuration(220);self.page_motion.animation.setEasingCurve(QEasingCurve.Type.InCubic)
            self.page_motion.present(frame,target,self.rect(),direction=-1)
        except Exception:
            self._capturing_return=False;self.close();raise
    def motion_finished(self):
        if self._returning:self.close()
    def cancel_motion(self):
        self._motion_ticket+=1;self._returning=False;self.page_motion.clear()
    def closeEvent(self,event):
        self.cancel_motion();super().closeEvent(event)
    def hideEvent(self,event):
        if hasattr(self,'page_motion') and not self._capturing_return:self.cancel_motion()
        super().hideEvent(event)
    def resizeEvent(self,event):
        if hasattr(self,'page_motion'):
            returning=self._returning;self.cancel_motion()
            if returning:self.close()
        super().resizeEvent(event)
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Resize:self.setGeometry(obj.rect())
        elif event.type()==QEvent.Type.Hide:self.close()
        return False
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.go_back();event.accept();return
        super().keyPressEvent(event)
