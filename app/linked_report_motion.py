"""Keep an open report attached to the visible card, never its native canvas."""
from PySide6.QtCore import QObject,QRect,QRectF,QPoint,QTimer,Qt
from PySide6.QtGui import QFontMetrics,QPixmap,QPainter,QRegion
from PySide6.QtWidgets import QWidget,QToolButton,QLabel,QLineEdit,QListWidget,QScrollArea,QStackedWidget
from panel_transition import NativeLanding,present_barrier,settle_visible
from surface_morph import SurfaceMorph,SurfaceState,pixel_size,raster_offset
from spring_motion import container_progress,stage
from card_motion import paint_card

class LinkedReportMotion(QObject):
    def __init__(self,report):
        super().__init__(report);self.report=report;self.active=False;self.committed=False;self.progress=0.
        self.old=None;self.new=None;self.start=None;self.end=None;self.canvas=None
        self.frame=None;self.weighted=None;self.saved_opacity=1.;self.saved_passthrough=False;self.status_tracking=False;self.tracked_rect=None
        self.module_start=None;self.module_morph=None
        self.landing=NativeLanding(report.bubble);self.shield=NativeLanding(report.bubble)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(0);self.timer.timeout.connect(self.release)
    def park(self,surface):
        # NativeLanding seeds its raster before its first show. Empty guards
        # no longer need an idle exposed HWND behind the opening report.
        surface.release()
    def capture(self):
        r=self.report;ratio=r.devicePixelRatioF();size=r.surface.size()
        image=QPixmap(pixel_size(size.width(),ratio),pixel_size(size.height(),ratio));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
        p=QPainter(image);paint_card(p,QRectF(0,0,size.width(),size.height()),None,1.)
        r.surface.render(p,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren);p.end();return image
    def module_state(self,rect,image):
        r=self.report
        root=r.surface
        bounds={};clips={}
        surface_clip=QRectF(root.rect())
        if r.page=='overview' and r.report and not r.calendar:
            viewport=r.scroll.viewport()
            body_clip=QRectF(viewport.rect().translated(viewport.mapTo(root,QPoint()))).intersected(surface_clip)
            bounds,clips=self.overview_parts(surface_clip,body_clip)
        else:
            self.collect_modules(root,surface_clip,bounds,clips)
        return SurfaceState(QRectF(rect),image,QRectF(),QPixmap(),False,[],
                            page='status',expanded=True,shared_bounds=bounds,visible_bounds=clips)
    def collect_modules(self,root,surface_clip,bounds,clips):
        r=self.report
        from data_page_motion import PageFade
        from project_cost_ui import DetailSummary,FeeStrip,MetricLine,SessionButton,TurnRow,dollars,estimated
        from settings_controls import SlidingSegments
        from daily_report import ModelRow
        from report_metrics import ReportMetricPair
        from quota_compare_ui import CyclePlot
        from report_calendar import CalendarCell
        from token_calendar import compact_tokens
        from typography import ui_font

        overlay_names={'explanationOverlay','officialRatesPage','pricingEditor'}
        panels={'quota_current_section':8,'quota_comparison_section':8,'costSection':8,
                'pricingGroup':9,'officialRateModel':8,'reportCalendarGrid':9}

        def add(widget,key,clip,local=None):
            box=(QRectF(widget.rect()) if local is None else local).translated(widget.mapTo(root,QPoint()))
            if box.intersects(clip) and not box.isEmpty():
                bounds[key]=box.intersected(surface_clip);clips[key]=clip

        def slices(widget,key,clip,rect,parts):
            for name,x,y,width,height in parts:
                add(widget,key+'/'+name,clip,QRectF(x,y,width,height).translated(rect.topLeft()))

        def split_row(name,width,right_width,top,height):
            right_width=min(width,right_width)
            return [(f'fixed-left-{name}',0,top,width-right_width,height),
                    (f'fixed-right-{name}',width-right_width,top,right_width,height)]

        def collect(layout,key,clip):
            for index in range(layout.count()):
                item=layout.itemAt(index);part=f'{key}/{index}'
                if item.widget():visit(item.widget(),part,clip)
                elif item.layout():collect(item.layout(),part,clip)

        def front(widget):
            return next((child for child in reversed(widget.children()) if isinstance(child,QWidget)
                         and child.isVisibleTo(root) and (child.objectName() in overlay_names or isinstance(child,PageFade))),None)

        def visit(widget,key,clip):
            if not widget.isVisibleTo(root) or widget.isWindow():return
            rect=QRectF(widget.rect());box=rect.translated(widget.mapTo(root,QPoint()))
            clip=clip.intersected(box)
            if clip.isEmpty():return
            overlay=front(widget)
            if overlay is not None:
                visit(overlay,key+'/overlay',clip);return
            if isinstance(widget,QStackedWidget):
                current=widget.currentWidget()
                if current is not None:visit(current,f'{key}/page{widget.currentIndex()}',clip)
            elif isinstance(widget,QScrollArea):
                viewport=widget.viewport()
                viewport_clip=clip.intersected(QRectF(viewport.rect().translated(viewport.mapTo(root,QPoint()))))
                child=front(viewport) or widget.widget()
                if child is not None:visit(child,key+'/viewport',viewport_clip)
                if widget.verticalScrollBar().isVisibleTo(root):add(widget.verticalScrollBar(),key+'/fixed-right-scrollbar',clip)
            elif isinstance(widget,QListWidget):
                viewport=widget.viewport()
                viewport_clip=clip.intersected(QRectF(viewport.rect().translated(viewport.mapTo(root,QPoint()))))
                row=widget.indexAt(QPoint(1,0)).row()
                for index in range(max(0,row),widget.count()):
                    item=widget.item(index);row_rect=QRectF(widget.visualItemRect(item))
                    if row_rect.top()>=viewport.height():break
                    if row_rect.bottom()<=0:continue
                    row_key=f'{key}/row{index}';width=row_rect.width()
                    data=item.data(Qt.ItemDataRole.UserRole) or {}
                    if '_summary' in data:
                        parent=row_key+'/report-panel10'
                        add(viewport,parent,viewport_clip,row_rect.adjusted(0,0,0,-1))
                        for name,right,y,h in [('currency',72,0,24),('projects',100,48,23),
                                               ('coverage',72,76,23),('sort',94,100,23)]:
                            slices(viewport,parent,viewport_clip,row_rect,split_row(name,width,right,y,h))
                        # The summary separators and amounts occupy separate rows.
                        slices(viewport,parent,viewport_clip,row_rect,[('fixed-left-value',0,24,width,24),('divider',9,73,width-18,1)])
                    else:
                        amount=estimated(data.get('cost'),data.get('tokens',0),data.get('pending_tokens',0))
                        right=QFontMetrics(ui_font(16,True)).horizontalAdvance(amount)+14
                        y=57 if data.get('duplicate') else 39
                        parts=split_row('name',width,right,0,26)
                        if data.get('duplicate'):parts.append(('fixed-left-path',0,26,width,18))
                        parts.extend(split_row('usage',width,70,y-13,22))
                        parts.append(('progress',7,y+9,width-14,3))
                        slices(viewport,row_key,viewport_clip,row_rect,parts)
                if widget.verticalScrollBar().isVisibleTo(root):add(widget.verticalScrollBar(),key+'/fixed-right-scrollbar',clip)
            elif isinstance(widget,CalendarCell):
                if widget.band:add(widget,key+'/band',clip)
                width=min(widget.width(),38 if widget.month_cell else 24)
                add(widget,key+'/fixed-center-date',clip,QRectF((widget.width()-width)/2,0,width,widget.height()))
            elif widget.objectName()=='calendarFooterAction':
                add(widget,key+'/report-panel7',clip)
                width=min(widget.width(),QFontMetrics(ui_font(12)).horizontalAdvance(widget.text())+8)
                add(widget,key+'/fixed-center-label',clip,QRectF((widget.width()-width)/2,0,width,widget.height()))
            elif widget is r.plot:
                chart=widget.chart_rect();w,h=widget.width(),widget.height()
                if isinstance(widget,CyclePlot):
                    left=chart.left()
                    parts=[('fixed-left-value-axis',0,0,left,h),('bars',left,0,w-left,77),
                           ('fixed-left-date',left,77,48,h-77),('fixed-right-date',w-52,77,48,h-77)]
                else:
                    bottom=round(chart.bottom()+3)
                    parts=[('bars',0,0,w,bottom),('fixed-left-date',0,bottom,40,h-bottom),
                           ('fixed-right-date',w-40,bottom,40,h-bottom)]
                slices(widget,key,clip,rect,parts)
            elif isinstance(widget,ReportMetricPair):
                parent=key+'/report-panel';add(widget,parent,clip)
                for name,column in zip(('peak','average'),widget.columns):
                    add(column,parent+'/fixed-left-'+name,clip)
            elif isinstance(widget,(ModelRow,DetailSummary,MetricLine,SessionButton,TurnRow)):
                width,height=widget.width(),widget.height()
                if isinstance(widget,DetailSummary):key+='/report-panel10';add(widget,key,clip)
                elif isinstance(widget,ModelRow) and widget.selected:key+='/report-panel-selection';add(widget,key,clip)
                if isinstance(widget,TurnRow):
                    turn=widget.turn
                    amount=estimated(turn['cost'],turn['tokens'],turn['pending_tokens'])
                    right=QFontMetrics(ui_font(12,True)).horizontalAdvance(amount)+4
                    parts=split_row('title',width,right,0,23)
                    for i,fit in enumerate(('left','center','right')):
                        parts.append((f'fixed-{fit}-tokens',i*width/3,28,width/3,33))
                    parts.append(('divider',2,68,width-4,1))
                elif isinstance(widget,DetailSummary):
                    data=widget.data
                    parts=[('fixed-left-name',6,5,width-12,21)]
                    if widget.session:
                        right=QFontMetrics(ui_font(16,True)).horizontalAdvance(dollars(data['cost']))+9
                        parts.extend(split_row('totals',width,right,30,23))
                    else:
                        parts.append(('fixed-left-price',6,25,width-12,32))
                        parts.extend(split_row('totals',width,86,61,22))
                elif isinstance(widget,ModelRow):
                    total=compact_tokens(widget.item['total'])+f"  {widget.item['total']/max(1,widget.total)*100:.1f}%"
                    right=27+QFontMetrics(ui_font(11,widget.selected)).horizontalAdvance(total)
                    parts=[('fixed-left-title',7,3,max(0,width-right-7),18),
                           ('fixed-right-title',max(7,width-right),3,max(0,right-7),18),
                           ('fixed-left-meta',20,21,max(0,width-29),14)]
                else:
                    height_split=26 if isinstance(widget,SessionButton) else height
                    if isinstance(widget,SessionButton):
                        right=8+min(width//2,QFontMetrics(ui_font(12,True)).horizontalAdvance(dollars(widget.session['cost'])+' ›')+4)
                    else:right=QFontMetrics(ui_font(12,True)).horizontalAdvance(str(widget.value))
                    parts=split_row('title',width,right,0,height_split)
                    if height_split<height:parts.append(('fixed-left-meta',0,height_split,width,height-height_split))
                slices(widget,key,clip,rect,parts)
            elif isinstance(widget,SlidingSegments):
                key+='/report-panel-segments';add(widget,key,clip)
                add(widget,key+'/report-panel-segment-pill',clip,widget.pill)
                for i,button in enumerate(widget.buttons.values()):
                    if not button.isVisibleTo(root):continue
                    metrics=QFontMetrics(button.font());w=metrics.horizontalAdvance(button.text())+4;h=metrics.height()+4
                    label=QRectF((button.width()-w)/2,(button.height()-h)/2,w,h)
                    add(button,f'{key}/fixed-center-label{i}',clip,label)
            elif widget.layout() is not None:
                radius=panels.get(widget.objectName())
                if radius:
                    key+=f'/report-panel{radius}';add(widget,key,clip)
                collect(widget.layout(),key,clip)
            else:
                align=widget.alignment() if isinstance(widget,QLabel) else Qt.AlignmentFlag.AlignLeft
                fit='right' if align&Qt.AlignmentFlag.AlignRight else 'center' if align&Qt.AlignmentFlag.AlignHCenter else 'left'
                if isinstance(widget,FeeStrip):
                    add(widget,key,clip)
                elif isinstance(widget,QLineEdit):
                    slices(widget,key,clip,rect,[('fixed-left-input',0,0,widget.width()-8,widget.height()),
                                                ('fixed-right-edge',widget.width()-8,0,8,widget.height())])
                else:add(widget,key+f'/fixed-{fit}-control',clip)

        if r.calendar and r.calendar.isVisibleTo(root):visit(r.calendar,'calendar',surface_clip)
        else:collect(r.layout,'report',surface_clip)
    def overview_parts(self,surface_clip,body_clip):
        """Capture backgrounds, moving text, and the chart at native size."""
        r=self.report;root=r.surface;bounds={};clips={}
        def add(key,widget,local=None,clip=body_clip):
            if widget is None or not widget.isVisibleTo(root):return
            local=QRectF(widget.rect()) if local is None else local
            box=local.translated(widget.mapTo(root,QPoint()))
            if box.intersects(clip):
                bounds[key]=box.intersected(surface_clip);clips[key]=clip

        header=r.header_title.parentWidget()
        first_action=r.refresh_button.x()
        add('chrome_0/fixed-left-title',header,QRectF(0,0,first_action,header.height()),surface_clip)
        for i in range(3,header.layout().count()):
            widget=header.layout().itemAt(i).widget()
            add(f'chrome_0/fixed-left-action{i}',widget,clip=surface_clip)
        add('chrome_1/fixed-left-tabs',r.nav_panel,clip=surface_clip)

        stats=r.stats;w=stats.width()
        add('body_stats/fixed-left-caption',stats,QRectF(0,0,w,18))
        for i in range(4):
            cell=stats.cell_rect(i);key=f'body_stat{i}/report-panel-stat'
            add(key,stats,cell)
            add(key+'/fixed-left-text',stats,cell.adjusted(5,4,-5,-4))
        add('body_stats/fixed-left-day',stats,QRectF(0,106,w/2,17))
        add('body_stats/fixed-right-messages',stats,QRectF(w/2,106,w/2,17))
        add('body_state/fixed-left-status',r.data_state)

        hourly=r.daily_cost.parentWidget();key='body_hourly/report-panel'
        add(key,hourly)
        cost=r.daily_cost;half=cost.width()//2
        add(key+'/fixed-left-usage',cost,QRectF(0,0,half,cost.height()))
        add(key+'/fixed-left-cost',cost,QRectF(half,0,cost.width()-half,cost.height()))
        plot=r.plot;area=plot.chart_rect();bottom=round(area.bottom()+2)
        add(key+'/fixed-left-legend',plot,QRectF(0,0,plot.width(),16))
        add(key+'/plot',plot,QRectF(0,16,plot.width(),bottom-16))
        for name,x in (('left',area.left()),('center',area.center().x()-15),('right',area.right()-32)):
            add(key+f'/fixed-left-axis-{name}',plot,QRectF(x,bottom,32,plot.height()-bottom))
        add(key+'/fixed-left-rate',r.readout)
        add(key+'/fixed-left-info',hourly.findChild(QToolButton,'report_daily_explanation'))

        analogy=r.analogy.parentWidget();key='body_analogy/report-panel'
        add(key,analogy)
        add(key+'/fixed-left-copy',r.analogy)
        add(key+'/fixed-left-estimate',r.book_estimate)
        add(key+'/fixed-left-book',analogy.findChild(QToolButton,'report_next_book'))
        add('body_footer/fixed-left-note',r.note_label)
        return bounds,clips
    def begin(self):
        r=self.report
        if not r.isVisible() or not r.requested or r._animating:return
        if self.active:self.cancel()
        self.release();self.active=True;self.committed=False;self.progress=0.
        self.status_tracking=False;self.tracked_rect=None
        self.start=QRectF(r.content_geometry());self.old=self.capture()
        self.module_start=self.module_state(self.start,self.old)
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
            if r.page=='overview' and getattr(r,'stats',None):r.stats.set_columns(width-22)
            r._measure_overview();target=r.geometry_for_host(host)
            r.surface.setFixedSize(target.size())
            settle_visible(r.surface);r._sync_scroll_extent();settle_visible(r.surface)
            r.setUpdatesEnabled(enabled)
            self.new=self.capture();r.setUpdatesEnabled(False)
            self.end=QRectF(target)
            if self.start.width()!=self.end.width():
                self.module_morph=SurfaceMorph(self.module_start,self.module_state(self.end,self.new))
            self.canvas=self.start.united(self.end).adjusted(-r.PAD,-r.PAD,r.PAD,r.PAD).toAlignedRect()
            if self.module_morph is not None:
                self.module_morph.prepare_landing(self.canvas,r.devicePixelRatioF())
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
        if self.module_morph is not None and not self.status_tracking:
            self.module_morph.paint(p,self.progress,self.canvas)
            return
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
                r.surface.setFixedSize(end.size())
                settle_visible(r.surface);r._sync_scroll_extent();settle_visible(r.surface)
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
        if not self.active:
            self.old=self.new=self.frame=self.weighted=None
            self.module_start=self.module_morph=None
        if not self.active and r.isVisible() and r.plot:r.plot.start_reveal()
    def cancel(self):
        if self.active and self.committed and self.report.isVisible():self.finish()
        self.report.setWindowOpacity(self.saved_opacity);self.report._input_passthrough(self.saved_passthrough)
        self.active=False;self.committed=False;self.old=self.new=None;self.release()
