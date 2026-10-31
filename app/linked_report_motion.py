"""Keep an open report attached to the visible card, never its native canvas."""
from PySide6.QtCore import QObject,QRect,QRectF,QPoint,QTimer,Qt
from PySide6.QtGui import QPixmap,QPainter,QRegion
from PySide6.QtWidgets import QWidget
from panel_transition import NativeLanding,present_barrier
from surface_morph import pixel_size,raster_offset
from spring_motion import container_progress,stage
from card_motion import paint_card

class LinkedReportMotion(QObject):
    def __init__(self,report):
        super().__init__(report);self.report=report;self.active=False;self.committed=False;self.progress=0.
        self.old=None;self.new=None;self.start=None;self.end=None;self.canvas=None
        self.frame=None;self.weighted=None;self.saved_opacity=1.;self.saved_passthrough=False;self.status_tracking=False;self.tracked_rect=None
        self.landing=NativeLanding(report.bubble);self.shield=NativeLanding(report.bubble)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(0);self.timer.timeout.connect(self.release)
    def park(self,surface):
        surface.image=None
        if surface.isVisible():surface.repaint()
        if self.report.isVisible() and self.report.requested:
            # A newly shown layered HWND is not exposed synchronously. Keep
            # these empty/input-transparent stores exposed while the report
            # is open, so its first host resize has a paintable guard too.
            if not surface.isVisible():surface.prepare(self.report.geometry())
        else:surface.hide()
    def prewarm(self):
        if not self.active:
            self.park(self.landing);self.park(self.shield)
    def capture(self):
        r=self.report;ratio=r.devicePixelRatioF();size=r.surface.size()
        image=QPixmap(pixel_size(size.width(),ratio),pixel_size(size.height(),ratio));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
        p=QPainter(image);paint_card(p,QRectF(0,0,size.width(),size.height()),None,1.)
        r.surface.render(p,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren);p.end();return image
    def begin(self):
        r=self.report
        if not r.isVisible() or not r.requested or r._animating:return
        if self.active:self.cancel()
        self.release();self.active=True;self.committed=False;self.progress=0.
        self.status_tracking=False;self.tracked_rect=None
        self.start=QRectF(r.content_geometry());self.old=self.capture()
        if hasattr(r,'page_fade'):r.page_fade.clear()
        r.refresh_button.freeze_motion('host')
        if r.plot:r.plot.freeze_reveal()
        # Present the original pixels on an independent native surface before
        # touching the live report. A hidden child does not suppress its
        # parent's translucent backing-store paints during QWidget.render.
        native=QRect(r.geometry());ratio=r.devicePixelRatioF()
        frame=QPixmap(pixel_size(native.width(),ratio),pixel_size(native.height(),ratio));frame.setDevicePixelRatio(ratio);frame.fill(Qt.GlobalColor.transparent)
        p=QPainter(frame);p.drawPixmap(r.PAD,r.PAD,self.old);p.end();self.shield.present(frame,native);present_barrier()
        self.saved_opacity=r.windowOpacity();self.saved_passthrough=r.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        r.setWindowOpacity(0.);r._input_passthrough(True)
    def commit(self,host):
        if not self.active:return
        r=self.report;enabled=r.updatesEnabled();r.setUpdatesEnabled(False)
        try:
            width=r.panel_width(host)
            r.surface.hide();r.surface.setFixedWidth(width)
            if r.page=='overview' and getattr(r,'stats',None):r.stats.set_columns(width-22)
            r._measure_overview();target=r.geometry_for_host(host)
            height=target.height()
            r.surface.setFixedHeight(height);r.layout.activate()
            for widget in [r.surface]+r.surface.findChildren(QWidget):
                if widget.layout():widget.layout().activate()
            r.setUpdatesEnabled(enabled)
            self.new=self.capture();r.setUpdatesEnabled(False)
            self.end=QRectF(target)
            self.canvas=self.start.united(self.end).adjusted(-r.PAD,-r.PAD,r.PAD,r.PAD).toAlignedRect()
            self.committed=True
            ratio=r.devicePixelRatioF();self.frame=QPixmap(pixel_size(self.canvas.width(),ratio),pixel_size(self.canvas.height(),ratio));self.frame.setDevicePixelRatio(ratio);self.weighted=QPixmap(self.frame.size());self.weighted.setDevicePixelRatio(ratio)
        finally:r.setUpdatesEnabled(enabled)
        self.render_frame();self.landing.present(self.frame,self.canvas);self.park(self.shield)
    def geometry(self,time=None):
        if not self.committed:return self.start
        if self.tracked_rect is not None:return self.tracked_rect
        time=self.progress if time is None else time;f=container_progress(time);a,z=self.start,self.end
        return QRectF(a.x()+(z.x()-a.x())*f,a.y()+(z.y()-a.y())*f,a.width()+(z.width()-a.width())*f,a.height()+(z.height()-a.height())*f)
    def advance(self,time):
        if self.active and self.committed:self.progress=time;self.render_frame();self.landing.repaint()
    def begin_status(self,target):
        self.begin()
        if self.active:self.commit(target);self.status_tracking=True
    def track_status(self,host,progress):
        if not self.active or not self.status_tracking:return
        r=self.report;self.tracked_rect=QRectF(r.geometry_for_host(host))
        self.advance(min(.999999,float(progress)))
    def finish_status(self):
        if self.active and self.status_tracking:self.finish()
    def render_frame(self):
        if self.frame is None:return
        self.frame.fill(Qt.GlobalColor.transparent);p=QPainter(self.frame);self.paint(p);p.end()
    def paint(self,p):
        if self.progress<=0. or self.progress>=1.:
            rect,image=(self.start,self.old) if self.progress<=0. else (self.end,self.new)
            screen=self.report.screen();origin=screen.geometry().topLeft() if screen else QPoint()
            p.drawPixmap(raster_offset(rect.topLeft(),self.canvas.topLeft(),p.device().devicePixelRatioF(),origin),image);return
        rect=self.geometry().translated(-self.canvas.x(),-self.canvas.y())
        p.save()
        from PySide6.QtGui import QPainterPath
        path=QPainterPath();path.addRoundedRect(rect,18,18);p.setClipPath(path);p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        weight=round(stage(self.progress,.12,.86)*255)
        p.setOpacity((256-weight)/256);p.drawPixmap(rect,self.old,QRectF(self.old.rect()))
        self.weighted.fill(Qt.GlobalColor.transparent);q=QPainter(self.weighted);q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform);q.setClipPath(path)
        q.setOpacity((weight+1)/256);q.drawPixmap(rect,self.new,QRectF(self.new.rect()));q.end()
        p.setOpacity(1.);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus);p.drawPixmap(0,0,self.weighted)
        p.restore()
    def finish(self,host=None):
        if not self.active:return
        r=self.report
        if not self.committed:
            self.active=False;r.setWindowOpacity(self.saved_opacity);r._input_passthrough(self.saved_passthrough);self.release();return
        tracking=self.status_tracking
        if tracking and self.tracked_rect is not None:self.end=QRectF(self.tracked_rect)
        self.status_tracking=False;self.tracked_rect=None
        end=self.end.toRect();native=end.adjusted(-r.PAD,-r.PAD,r.PAD,r.PAD)
        if r._pending_rebuild or tracking:
            enabled=r.updatesEnabled();r.setUpdatesEnabled(False)
            resume=r.plot._resume_time if r.plot else None
            try:
                if r._pending_rebuild:
                    self.active=False;r._pending_rebuild=False;r.rebuild();self.active=True
                r.surface.setFixedSize(end.size());r.layout.activate()
                for widget in [r.surface]+r.surface.findChildren(QWidget):
                    if widget.layout():widget.layout().activate()
                r.setUpdatesEnabled(enabled);self.new=self.capture()
                if r.plot:r.plot._resume_time=resume
            finally:self.active=True;r.setUpdatesEnabled(enabled)
        self.progress=1.;self.render_frame();self.landing.repaint()
        enabled=r.updatesEnabled();r.setUpdatesEnabled(False)
        try:
            # Ignore the host's native resize events until this atomic handoff.
            r.setGeometry(native);r.surface.move(r.PAD,r.PAD);r.surface.show();self.active=False;self.committed=False
            r.fraction=1.
        finally:r.setUpdatesEnabled(enabled)
        r.repaint();r.setWindowOpacity(self.saved_opacity);r._input_passthrough(self.saved_passthrough);r.repaint();self.timer.start()
        if getattr(r,'_dismiss_after_host',False):
            r._dismiss_after_host=False;self.release();r.dismiss()
    def release(self):
        self.timer.stop();r=self.report
        if self.landing.image is not None and r.isVisible():
            r.repaint();present_barrier()
        self.park(self.landing);self.park(self.shield);r.refresh_button.resume_motion('host')
        if not self.active:self.old=self.new=self.frame=self.weighted=None
        if not self.active and r.isVisible() and r.plot:r.plot.start_reveal()
    def cancel(self):
        if self.active and self.committed and self.report.isVisible():self.finish()
        self.report.setWindowOpacity(self.saved_opacity);self.report._input_passthrough(self.saved_passthrough)
        self.active=False;self.committed=False;self.old=self.new=None;self.release()
