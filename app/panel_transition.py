"""Fixed native canvas, blended snapshots and queued explicit navigation."""
from settings_controls import play_animation
from theme_registry import color as theme_color
from PySide6.QtCore import QObject,QVariantAnimation,QEasingCurve,QRect,QRectF,QPoint,Qt,QEvent,QTimer
from PySide6.QtGui import QPainter,QPainterPath,QColor,QPen,QPixmap,QRegion
from PySide6.QtWidgets import QWidget,QApplication
from spring_motion import container_progress,dismiss_progress,EXPAND_MS,SHRINK_MS,DISMISS_MS
from surface_morph import SurfaceState,SurfaceMorph,pixel_size,complete_frame
from data_page_motion import paint_pages


def present_barrier():
    """Wait for the Windows compositor, not an assumed number of milliseconds.

    Offscreen Qt tests deliberately do not exercise this presentation boundary.
    """
    if QApplication.platformName() != 'windows':return
    import ctypes
    result=ctypes.windll.dwmapi.DwmFlush()
    return result == 0


def settle_visible(root):
    """Settle this page, not inactive QStackedWidget/settings/report pages.

    isVisibleTo ignores the deliberately hidden root used during preparation,
    while rejecting explicitly hidden descendants and their entire subtrees.
    """
    widgets=[root]+[w for w in root.findChildren(QWidget) if w.isVisibleTo(root)]
    for widget in reversed(widgets):
        widget.ensurePolished()
        if widget.layout():widget.layout().activate()
    for widget in widgets:QApplication.sendPostedEvents(widget,QEvent.Type.LayoutRequest)
    return widgets


class TransitionCover(QWidget):
    def __init__(self,parent):
        super().__init__(parent);self.image=None;self.next_image=None;self.blend=0.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.hide()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source);p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        t=self.parentWidget().size_transition
        if t.canvas_morph:
            t.paint_morph(p);return
        if t.same_size_fade:
            paint_pages(p,self.rect(),self.image,self.next_image,self.blend,t.page_direction);return
        # The captured frame already contains the exact corner/background.
        if self.image is not None:
            if self.next_image is None:p.drawPixmap(self.rect(),self.image,self.image.rect())
            else:
                p.setOpacity(1.-self.blend);p.drawPixmap(self.rect(),self.image,self.image.rect())
                p.setOpacity(self.blend);p.drawPixmap(self.rect(),self.next_image,self.next_image.rect())

class NativeLanding(QWidget):
    """Brief independent surface across a layered window's native shrink.

    A child cover shares its parent's resized backing store. An owned tool
    surface keeps the exact last frame visible while that store is replaced.
    It takes neither focus nor mouse input and is never an interactive panel.
    """
    def __init__(self,bubble):
        flags=Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowTransparentForInput|Qt.WindowType.WindowDoesNotAcceptFocus
        super().__init__(bubble,flags);self.image=None;self.paints=0;self.native_published=False;self.native_error=''
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus);self.hide()
    def prepare(self,rect):
        top=bool(self.parentWidget().windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
        if bool(self.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)!=top:self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,top)
        # Expose an empty, input-transparent surface during the animation.
        # A first show at the final resize may not be paintable synchronously.
        if self.geometry()!=rect:self.setGeometry(rect)
        if not self.isVisible():self.show();self.raise_()
        self.repaint()
        # A just-shown translucent tool is not necessarily exposed to Qt yet.
        # Submit the raster now, before the owner becomes transparent.
        from native_landing import publish
        try:self.native_published=publish(self,self.image);self.native_error=''
        except OSError as error:self.native_published=False;self.native_error=str(error)
    def present(self,image,rect):
        self.image=image;self.paints=0;self.prepare(rect)
    def paintEvent(self,event):
        p=QPainter(self);p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source);p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        if self.image is not None:p.drawPixmap(0,0,self.image)
        if self.image is not None:self.paints+=1
    def release(self):
        # A hidden layered backing store keeps its last pixels. Erase while
        # exposed, before hiding, so the next transparent prewarm cannot flash
        # the previous capsule's final frame on its first native show.
        self.image=None
        if self.isVisible():
            self.repaint()
            from native_landing import publish
            try:publish(self,None)
            except OSError as error:self.native_error=str(error)
        self.native_published=False
        self.hide()


class PanelTransition(QObject):
    def __init__(self,bubble):
        super().__init__(bubble);self.bubble=bubble;self.cover=TransitionCover(bubble)
        self.start_rect=None;self.target_rect=None;self.before=None;self.deferred=False;self.active=False;self.preparing=False;self.frozen=[]
        self.canvas_morph=False;self.same_size_fade=False;self.start_island=False;self.canvas_rect=None;self.progress=0.;self.raw_progress=0.;self.shrinking=False;self.closing=False
        self.old_surface=None;self.morph=None
        self.landing=NativeLanding(bubble);self.landing_timer=QTimer(self);self.landing_timer.setSingleShot(True)
        self.landing_timer.setInterval(0);self.landing_timer.timeout.connect(self.release_landing)
        self._preparation_updates=None;self.status_deferred=False;self.post_handoff=None;self.start_page_state=None
        self._native_preparation_opacity=None
        self.page_direction=1
        self.animation=QVariantAnimation(self);self.animation.setDuration(280)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.valueChanged.connect(self.advance);self.animation.finished.connect(self.finish)
    @property
    def running(self):return self.active
    def _hold_icon(self,hold):
        for name in ('status_indicator','refresh_button','island'):
            icon=getattr(self.bubble,name,None)
            if icon:
                if hold:icon.freeze_motion()
                else:icon.resume_motion()
    def _page_state(self):
        b=self.bubble
        return (b.panel_page,b.expanded,b.bubble_mode,b.auto_compact,b._minimal_normal_open,b.detail_tab)
    def begin(self):
        b=self.bubble
        self.release_landing()
        self._hold_icon(True)
        self.start_island=b.is_island();self.canvas_morph=False;self.same_size_fade=False;self.closing=False;self.canvas_rect=None
        self.start_page_state=self._page_state()
        self.cover.next_image=None;self.cover.blend=0.
        self.old_surface=None;self.morph=None
        if b.isVisible():
            self.before=b.grab();self.start_rect=QRect(b.geometry());self.old_surface=SurfaceState.capture(b,frame=self.before)
        else:self.before=None;self.start_rect=None
        if self.before is not None and QApplication.platformName()=='windows':
            # Guard BEFORE hiding children or rendering a replacement layout.
            # QWidget.render can flush a translucent HWND's backing store even
            # while updates are disabled; guarding only SetWindowPos is late.
            self.landing.present(self.before,self.start_rect);present_barrier()
            self._native_preparation_opacity=b.windowOpacity();b.setWindowOpacity(0.);present_barrier()
        self.animation.stop();self.active=False;self.preparing=True;self.target_rect=None
        self.thaw()
        if self._preparation_updates is None:self._preparation_updates=b.updatesEnabled()
        b.setUpdatesEnabled(False)
        if self.before is not None:
            self.cover.image=self.before;self.cover.setGeometry(b.rect());self.cover.show();self.cover.raise_()
        # All target widgets are built under a hidden ancestor. Offscreen
        # render may flush native updates even without an event-loop turn.
        b.content.hide()
        if b.report and b.report.requested and not b.report._animating:b.report.follow.begin()
    def commit(self,preserve_reveals=False):
        # Redrawing a disabled status view may already have started its close.
        # Do not overwrite that target with a second navigation animation.
        if self.closing:return
        b=self.bubble;target=b.content_geometry()
        if self.start_rect is None or target==self.start_rect:
            if target==self.start_rect and self.before is not None and b.isVisible() and self._page_state()!=self.start_page_state:
                # Equal-sized editor pages used to swap live widgets directly.
                # On a long-idle backing store the first new paint could arrive
                # one compositor frame later, exposing a blank or stale page.
                widgets=settle_visible(b.content)
                b.setUpdatesEnabled(bool(self._preparation_updates))
                image=complete_frame(b)
                if image is not None and not image.isNull():
                    b.setUpdatesEnabled(False)
                    b.setFixedSize(target.size());b.move(target.topLeft())
                    # Header/navigation remain live and stationary. Only the
                    # opaque body changes page; whole-window fading produced
                    # two displaced toolbars and translucent text in videos.
                    top=b.layout.itemAt(1).widget().geometry().bottom()+1+b.layout.spacing()
                    margins=b.layout.contentsMargins()
                    body=QRect(margins.left(),top,b.width()-margins.left()-margins.right(),max(1,b.height()-top-margins.bottom()))
                    ratio=image.devicePixelRatioF()
                    source=QRect(pixel_size(body.x(),ratio),pixel_size(body.y(),ratio),pixel_size(body.width(),ratio),pixel_size(body.height(),ratio))
                    self.cover.image=self.before.copy(source);self.cover.next_image=image.copy(source);self.cover.blend=0.
                    order=('status','chat','settings')
                    self.page_direction=1 if order.index(b.panel_page)>order.index(self.start_page_state[0]) else -1
                    self.cover.setGeometry(body);self.cover.show();self.cover.raise_()
                    b.content.show()
                    if b.panel_page!='status':b._editor_positioned=True
                    if b.report:b.report.follow.finish(target)
                    self.before=None;self.start_rect=None;self.old_surface=None;self.deferred=False;self.preparing=False
                    self.active=True;self.same_size_fade=True;self.target_rect=target
                    self.progress=0.;self.raw_progress=0.
                    blocked=self.animation.blockSignals(True)
                    self.animation.stop();self.animation.setDuration(160)
                    self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                    self.animation.setStartValue(0.);self.animation.setEndValue(1.)
                    self.animation.setCurrentTime(0);self.animation.blockSignals(blocked)
                    from settings_controls import motion_enabled
                    if not motion_enabled():
                        self.cover.blend=1.;self._end_preparation();self.finish();return
                    play_animation(self.animation);self._end_preparation();b.content.repaint();self.cover.repaint();return
            b.setFixedSize(target.size());b.move(target.topLeft());b.content.setVisible(b.isVisible());self.cover.hide()
            self.cover.image=None;self.cover.next_image=None;self.cover.blend=0.
            if b.report:b.report.follow.finish(target)
            self.before=None;self.start_rect=None;self.old_surface=None;self.start_page_state=None;self.deferred=False;self.preparing=False;self._end_preparation();self._hold_icon(False);return
        self.target_rect=target;b.layout.activate()
        self.shrinking=target.width()*target.height()<self.start_rect.width()*self.start_rect.height()
        self.animation.setDuration(SHRINK_MS if self.shrinking else EXPAND_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        widgets=settle_visible(b.content)
        # QWidget.render skips update-disabled descendants. Restore them only
        # for synchronous offscreen captures, after all posted layout work.
        # No event-loop turn or native paint is dispatched in this interval.
        b.setUpdatesEnabled(bool(self._preparation_updates))
        shared_status=(self.old_surface is not None and self.old_surface.page==b.panel_page=='status' and
                       self.old_surface.expanded!=bool(b.expanded) and self.old_surface.shared_bounds and not b.is_compact())
        for widget in widgets:
            if not preserve_reveals and not self.shrinking and not shared_status and widget.isVisibleTo(b.content) and hasattr(widget,'begin_reveal'):widget.begin_reveal()
        ratio=b.devicePixelRatioF();size=b.content.size()
        # Render directly over the final paper once. Rendering text against a
        # transparent raster and then compositing it changes Qt font AA.
        image=complete_frame(b)
        self.cover.image=image
        self.cover.next_image=None;self.cover.blend=0.
        self.morph=SurfaceMorph(self.old_surface,SurfaceState.capture(b,target.topLeft(),frame=image,content=image))
        b.layout.setEnabled(False)
        self.frozen=[(b.layout.itemAt(i).widget(),b.layout.itemAt(i).widget().updatesEnabled()) for i in range(b.layout.count()) if b.layout.itemAt(i).widget()]
        for widget,enabled in self.frozen:widget.setUpdatesEnabled(False)
        self.active=True
        if b.panel_page!='status':b._editor_positioned=True
        self.canvas_morph=True
        # One full native canvas for the entire morph. Only in-memory
        # snapshots and the bottom-anchored clip change on each frame.
        self.progress=0.;self.raw_progress=0.;self.canvas_rect=self.start_rect.united(target).united(self.morph.bounds())
        self.morph.prepare_landing(self.canvas_rect,ratio)
        if b.report:b.report.follow.commit(target)
        native_canvas=QApplication.platformName()=='windows'
        if not native_canvas and self.shrinking:self.landing.prepare(target)
        enabled=b.updatesEnabled();b.setUpdatesEnabled(False)
        try:
            b.content.hide();b.setMinimumSize(0,0);b.setMaximumSize(16777215,16777215)
            self.cover.setGeometry(QRect(QPoint(),self.canvas_rect.size()))
            b.setGeometry(self.canvas_rect);self.cover.show();self.cover.raise_()
        finally:
            self.preparing=False;b.setUpdatesEnabled(enabled);self._end_preparation()
        self.cover.repaint()
        if native_canvas:self.landing.prepare(target)
        play_animation(self.animation)
    def dismiss(self):
        b=self.bubble
        if self.running or not b.isVisible():return
        if not self.preparing:self.begin()
        self.preparing=False;self.closing=True;self.active=True;self.canvas_morph=True
        self.canvas_rect=QRect(self.start_rect);self.progress=0.;self.raw_progress=0.
        self.target_rect=QRect(self.start_rect.center().x(),self.start_rect.bottom(),1,1)
        b.layout.setEnabled(False);b.content.hide();self.cover.image=self.before
        self.cover.setGeometry(b.rect());self.cover.show();self.cover.raise_()
        b.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
        if b.windowHandle():b.windowHandle().setFlag(Qt.WindowType.WindowTransparentForInput,True)
        if b.report:b.report.dismiss()
        self._end_preparation()
        self.animation.setDuration(DISMISS_MS);self.animation.setEasingCurve(QEasingCurve.Type.Linear);self.cover.repaint();play_animation(self.animation)
    def advance(self,value):
        if self.target_rect is None:return
        self.raw_progress=float(value)
        self.progress=max(0.,dismiss_progress(value)) if self.closing else max(0.,min(1.,float(value))) if self.same_size_fade else container_progress(value)
        if self.same_size_fade:self.cover.blend=self.progress
        self.cover.repaint()
        if self.bubble.report:self.bubble.report.follow.advance(self.raw_progress)
    def visible_geometry(self):
        if not self.running or self.target_rect is None:return QRect(self.bubble.geometry())
        if self.same_size_fade:return QRect(self.target_rect)
        if self.morph and not self.closing:return self.morph.geometry(self.raw_progress).toAlignedRect()
        a,z=self.start_rect,self.target_rect;f=self.progress
        return QRect(*[round(x+(y-x)*f) for x,y in zip((a.x(),a.y(),a.width(),a.height()),(z.x(),z.y(),z.width(),z.height()))])
    def paint_morph(self,p):
        if self.morph and not self.closing:
            self.morph.paint(p,self.raw_progress,self.canvas_rect);return
        f=self.progress;a=self.start_rect;z=self.target_rect;c=self.canvas_rect
        blend=max(0.,min(1.,f))
        values=[x+(y-x)*f for x,y in zip((a.x(),a.y(),a.width(),a.height()),(z.x(),z.y(),z.width(),z.height()))]
        rect=QRectF(values[0]-c.x(),values[1]-c.y(),values[2],values[3])
        if self.closing:
            path=QPainterPath();path.addRoundedRect(rect,min(22,rect.height()/2),min(22,rect.height()/2));p.setClipPath(path)
            p.setOpacity(min(1.,(1-f)/.08));p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(rect,self.before,QRectF(self.before.rect()));return
        radius=(22 if self.start_island else 14)+((22 if self.bubble.is_island() else 14)-(22 if self.start_island else 14))*blend
        path=QPainterPath();path.addRoundedRect(rect,radius,radius);p.setClipPath(path)
        normal=(blend if self.start_island else 1-blend) if self.start_island or self.bubble.is_island() else 1.
        p.setOpacity(normal);p.fillRect(rect,QColor(theme_color('#fcfafc')))
        for image,island,opacity in ((self.before,self.start_island,1-blend),(self.cover.image,self.bubble.is_island(),blend)):
            p.setOpacity(opacity);size=image.deviceIndependentSize()
            if f>1. and image is self.cover.image:
                # A slight squeeze, not cropped text/buttons at the rebound.
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.drawPixmap(rect,image,QRectF(image.rect()));continue
            x=rect.center().x()-size.width()/2;y=rect.center().y()-size.height()/2 if island else rect.bottom()-size.height()
            p.drawPixmap(round(x),round(y),image)
        p.setClipping(False);p.setOpacity(normal);p.setPen(QPen(QColor(theme_color('#e0d9e6')),1));p.setBrush(Qt.BrushStyle.NoBrush);p.drawRoundedRect(rect.adjusted(.5,.5,-.5,-.5),radius,radius)
    def finish(self):
        b=self.bubble;closing=self.closing;same_size_fade=self.same_size_fade;self.closing=False
        guarded=bool(not closing and (self.shrinking or QApplication.platformName()=='windows') and b.isVisible() and self.morph and self.morph.end.frame is not None)
        if guarded:
            # Publish on another native backing store BEFORE touching the
            # bubble's native geometry; disabling QWidget updates alone does
            # not cover the Windows compositor during a layered-window resize.
            self.landing.present(self.morph.end.frame,self.target_rect)
            present_barrier()
        native_opacity=b.windowOpacity() if guarded and QApplication.platformName()=='windows' else None
        if native_opacity is not None:b.setWindowOpacity(0.)
        enabled=b.updatesEnabled();b.setUpdatesEnabled(False)
        try:
            if closing:
                deferred=self.deferred;self.active=False
                b.hide();self.target_rect=QRect(self.start_rect);self.deferred=deferred
                b._editing_flags(b.panel_page!='status')
            if self.target_rect is not None:
                # Preserve the global snapshot origin during native events.
                if self.canvas_morph and self.canvas_rect:self.cover.move(self.canvas_rect.topLeft()-self.target_rect.topLeft())
                b.setMinimumSize(0,0);b.setMaximumSize(16777215,16777215)
                b.setGeometry(self.target_rect);b.setFixedSize(self.target_rect.size())
            self.thaw();self.canvas_morph=False
            b.content.setVisible(not closing and b.isVisible());b.layout.activate()
            if not same_size_fade:self.cover.hide();self.cover.image=None
        finally:b.setUpdatesEnabled(enabled)
        if same_size_fade:
            # Keep the finished raster above the newly shown page until its
            # live widgets have synchronously painted at the final geometry.
            b.content.repaint()
            if QApplication.platformName()=='windows':present_barrier()
            self.cover.hide();self.cover.image=None
        if native_opacity is not None:
            b.repaint();present_barrier()
            b.setWindowOpacity(native_opacity);b.repaint();present_barrier()
        else:b.repaint()
        if b.report:b.report.follow.finish(self.target_rect)
        self.active=False;self.before=None;self.old_surface=None;self.morph=None;self.same_size_fade=False;self.start_page_state=None;self.cover.image=None;self.cover.next_image=None;self.cover.blend=0.;self.start_rect=self.target_rect=None;self.canvas_rect=None
        if guarded:self.landing_timer.start()
        else:self._hold_icon(False);self.start_reveals()
        deferred=self.deferred;self.deferred=False
        status_deferred=self.status_deferred;self.status_deferred=False
        if deferred or status_deferred:
            refresh=self.bubble.redraw if deferred else self.bubble.refresh_status
            if guarded:self.post_handoff=refresh
            else:refresh()
    def start_reveals(self):
        for widget in self.bubble.content.findChildren(QWidget):
            if widget.isVisible() and hasattr(widget,'start_reveal'):widget.start_reveal()
    def release_landing(self):
        self.landing_timer.stop()
        if self.landing.image is None:
            self.landing.release();self._hold_icon(False);self._run_post_handoff();return
        # The native window is already at its final size. Flush its complete
        # live children before retiring the independent presentation surface.
        if self.bubble.isVisible():
            self.bubble.repaint()
            present_barrier()
        self.landing.release()
        self._hold_icon(False)
        if not self.running and self.bubble.isVisible():self.start_reveals()
        self._run_post_handoff()
    def _run_post_handoff(self):
        callback=self.post_handoff;self.post_handoff=None
        if callback and self.bubble.isVisible():QTimer.singleShot(0,self.bubble,callback)
    def complete(self):
        if self.running:self.animation.setCurrentTime(self.animation.duration())
    def translate(self,delta):
        """An attached drag moves the whole prepared canvas, never relayouts."""
        if not self.running or delta.isNull():return
        for name in ('start_rect','target_rect','canvas_rect'):
            rect=getattr(self,name)
            if rect is not None:rect.translate(delta)
        if self.morph:self.morph.translate(delta)
        self.bubble.move(self.bubble.pos()+delta)
        if self.landing.isVisible():self.landing.move(self.landing.pos()+delta)
    def thaw(self):
        for widget,enabled in self.frozen:widget.setUpdatesEnabled(enabled)
        self.frozen=[];self.bubble.layout.setEnabled(True)
    def _end_preparation(self):
        if self._preparation_updates is not None:
            enabled=self._preparation_updates;self._preparation_updates=None
            self.bubble.setUpdatesEnabled(enabled)
        if self._native_preparation_opacity is not None:
            opacity=self._native_preparation_opacity;self._native_preparation_opacity=None
            self.cover.repaint();self.bubble.repaint();present_barrier()
            self.bubble.setWindowOpacity(opacity);self.bubble.repaint();present_barrier()
            self.landing.release()
    def cancel(self):
        if self.bubble.report:self.bubble.report.follow.cancel()
        self.landing_timer.stop();self.landing.release()
        self.animation.stop();self.deferred=False;self.status_deferred=False;self.preparing=False
        if self.active:self.finish()
        else:
            self.cover.hide();self.cover.image=None;self.before=None;self.old_surface=None
            if self.bubble.isVisible():self.bubble.content.show()
        self._end_preparation()
        if self.landing.image is None:self._hold_icon(False)
