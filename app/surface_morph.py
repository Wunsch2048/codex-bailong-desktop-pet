"""One continuous body, a shared status glyph and separately moving satellites.

Reference: Apple's WWDC23 10194 at 11:12 and 12:43. Captures are prepared
once per navigation; each frame is only a few raster draws on a fixed canvas.
"""
from theme_registry import color as theme_color
from dataclasses import dataclass,field
import math
from PySide6.QtCore import QRectF,QPoint,QPointF,QSizeF,Qt
from PySide6.QtGui import QPixmap,QPainter,QPainterPath,QColor,QPen,QRegion,QFontMetrics
from PySide6.QtWidgets import QWidget,QToolButton
from spring_motion import container_progress,stage
from ui_theme import SURFACE,ISLAND

PANEL_RADIUS=18.


def pixel_size(value,ratio):return math.floor(value*ratio+.5)


def raster_offset(point,canvas,ratio,origin=QPointF()):
    """Difference of native pixel positions, not a rounded logical delta.

    At 150%, round(100*1.5)-round(99*1.5) differs from round(1*1.5).
    Use the screen origin just as Qt's per-monitor geometry conversion does.
    """
    def native(v):return math.floor(v+.5) if v>=0 else math.ceil(v-.5)
    return QPointF((native((point.x()-origin.x())*ratio)-native((canvas.x()-origin.x())*ratio))/ratio,
                   (native((point.y()-origin.y())*ratio)-native((canvas.y()-origin.y())*ratio))/ratio)


def complete_frame(bubble):
    size=bubble.content.size();ratio=bubble.devicePixelRatioF()
    image=QPixmap(pixel_size(size.width(),ratio),pixel_size(size.height(),ratio));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not bubble.is_compact():
        p.setBrush(QColor(theme_color(SURFACE)));p.setPen(QPen(QColor(theme_color('#e0d9e6')),1))
        p.drawRoundedRect(QRectF(0,0,size.width(),size.height()).adjusted(.5,.5,-.5,-.5),PANEL_RADIUS,PANEL_RADIUS)
    bubble.content.render(p,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren);p.end()
    return image


def snapshot(widget,children_only=False,skip=None):
    ratio=widget.devicePixelRatioF();image=QPixmap(pixel_size(widget.width(),ratio),pixel_size(widget.height(),ratio))
    image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
    if children_only:
        painter=QPainter(image)
        for child in widget.findChildren(QWidget,options=Qt.FindChildOption.FindDirectChildrenOnly):
            if child.isVisibleTo(widget) and child is not skip:child.render(painter,child.pos(),QRegion(),QWidget.RenderFlag.DrawChildren)
        painter.end()
    else:widget.render(image,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren)
    return image


@dataclass
class SurfaceState:
    rect:QRectF
    content:QPixmap
    icon_rect:QRectF
    icon:QPixmap
    island:bool
    satellites:list
    frame:QPixmap=None
    frame_origin:QPointF=None
    screen_origin:QPointF=None
    radius:float=PANEL_RADIUS
    page:str=''
    expanded:bool=False
    shared_bounds:dict=field(default_factory=dict)

    @classmethod
    def capture(cls,bubble,origin=None,frame=None,content=None):
        origin=bubble.pos() if origin is None else origin;island=bubble.is_island()
        minimal=bubble.is_minimal()
        root=bubble.island if island else bubble.minimal_quota if minimal else bubble.content
        offset=root.mapTo(bubble.content,QPoint())
        rect=QRectF(QPointF(origin+offset),QSizeF(root.size()))
        icon=bubble.status_indicator;icon_pos=icon.mapTo(root,QPoint()) if not minimal else QPoint()
        # Only the normal/detail root can reuse a complete content raster.
        # Keep an unmodified endpoint before clearing the shared glyph below.
        cached=content if root is bubble.content else None
        image=cached.copy() if cached is not None else snapshot(root,children_only=island,skip=icon)
        # Extract the shared glyph so it follows one path instead of appearing
        # twice in two fading, differently positioned screenshots.
        clear=QPainter(image);clear.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        clear.fillRect(QRectF(QPointF(icon_pos),QSizeF(icon.size())),Qt.GlobalColor.transparent);clear.end()
        glyph=snapshot(icon) if not minimal else QPixmap();glyph_rect=QRectF(QPointF(origin+offset+icon_pos),QSizeF(icon.size())) if not minimal else QRectF(rect.center(),QSizeF(0,0))
        if minimal:image=snapshot(root)
        satellites=[]
        if island:
            for name in ('island_shortcut','island_quota'):
                widget=next((w for w in bubble.findChildren(QToolButton,name) if w.isVisibleTo(bubble.content)),None)
                if widget:
                    pos=widget.mapTo(bubble.content,QPoint());satellites.append((QRectF(QPointF(origin+pos),QSizeF(widget.size())),snapshot(widget)))
        screen=bubble.screen()
        shared={}
        if not island and not minimal and bubble.panel_page=='status':
            heading=getattr(bubble,'_status_title',None)
            candidates={'heading':heading.parentWidget() if heading is not None else None,
                        'conversations':bubble.status_view,'quota':getattr(bubble,'quota_summary_card',None),
                        'statistics':bubble.deck,'today_tokens':bubble.today_tokens_card,
                        'live_rate':getattr(bubble,'live_rate_card',None)}
            candidates.update({'action_'+str(i):widget for i,widget in enumerate(getattr(bubble,'_header_actions',[]))})
            for key,widget in candidates.items():
                if widget is not None and widget.isVisibleTo(root) and widget.width()>0 and widget.height()>0:
                    shared[key]=QRectF(QPointF(widget.mapTo(root,QPoint())),QSizeF(widget.size()))
            for sid,row in bubble.status_view.rows.items():
                if not row.isVisibleTo(root):continue
                point=QPointF(row.mapTo(root,QPoint()));left=row.text_left()
                if left:
                    shared['conversation_title_'+sid]=QRectF(point.x(),point.y(),max(1,left-6),row.height())
                    shared['conversation_divider_'+sid]=QRectF(point.x()+left-6,point.y(),6,row.height())
                shared['conversation_detail_'+sid]=QRectF(point.x()+left,point.y(),max(1,row.width()-left),row.height())
            if bubble.status_view.overflow.isVisibleTo(root):
                more=bubble.status_view.overflow;shared['conversation_counter']=QRectF(QPointF(more.mapTo(root,QPoint())),QSizeF(more.size()))
            quota=getattr(bubble,'quota_summary_card',None)
            if quota is not None and 'quota' in shared:
                offset=QPointF(quota.mapTo(root,QPoint()))
                for index in range(len(quota.items)):
                    shared['quota_track_'+str(index)]=quota.track_rect(index).adjusted(-1,-1,1,1).translated(offset)
                    if len(quota.items)>1:shared['quota_value_'+str(index)]=quota.value_rect(index).translated(offset)
                if quota.alert_badge.isVisibleTo(root):
                    shared['quota_alert']=QRectF(QPointF(quota.alert_badge.mapTo(root,QPoint())),QSizeF(quota.alert_badge.size()))
            if 'today_tokens' in shared:
                footer=shared['today_tokens'];daily=bubble.today_tokens_card
                if getattr(daily,'compact',False):
                    from typography import ui_font
                    link=QFontMetrics(ui_font(10)).horizontalAdvance('24h ›')+10
                    shared['today_tokens_link']=QRectF(footer.right()-link,footer.y(),link,footer.height())
                    shared['today_tokens_amount']=QRectF(footer.x()+30,footer.y(),max(1,footer.width()-link-30),footer.height())
                else:shared['today_tokens_link']=QRectF(footer.right()-45,footer.y(),45,footer.height())
            if 'live_rate' in shared:
                footer=shared['live_rate']
                shared['live_rate_value']=QRectF(footer.x()+30,footer.y(),max(1,footer.width()-30),footer.height())
            deck=bubble.deck
            if deck is not None and 'statistics' in shared:
                controls={'statistics_tab_'+key:widget for key,widget in deck.tabs.buttons.items()}
                controls.update({'statistics_range_'+key:widget for key,widget in getattr(deck.content,'range_buttons',{}).items()})
                for key,widget in controls.items():
                    shared[key]=QRectF(QPointF(widget.mapTo(root,QPoint())),QSizeF(widget.size()))
                plot=getattr(deck.content,'plot',None)
                if plot is not None:
                    from typography import ui_font
                    point=QPointF(plot.mapTo(root,QPoint()));w,h=plot.width(),plot.height()
                    shared['statistics_plot']=QRectF(point,QSizeF(plot.size()))
                    if plot.chart_mode()!='combo':
                        title_height=max(16,QFontMetrics(ui_font(11,True)).height())
                        shared['statistics_plot_title']=QRectF(point.x(),point.y(),w,title_height)
                    label_height=QFontMetrics(ui_font(11)).height()+2;label_y=point.y()+h-label_height
                    hourly=plot.series['mode']=='line'
                    edge_width=30 if hourly else w/2
                    shared['statistics_plot_left']=QRectF(point.x(),label_y,edge_width,label_height)
                    shared['statistics_plot_right']=QRectF(point.x()+w-edge_width,label_y,edge_width,label_height)
                    if hourly:shared['statistics_plot_middle']=QRectF(point.x()+w/2-14,label_y,28,label_height)
                    if plot.series['available'] and not max((v['value'] for v in plot.series['bins'] if not v['future']),default=0):
                        metrics=QFontMetrics(ui_font(10,True));size=QSizeF(metrics.horizontalAdvance('暂无用量')+4,metrics.height()+4)
                        center=plot.chart_rect().center()+point
                        shared['statistics_plot_empty']=QRectF(center-QPointF(size.width()/2,size.height()/2),size)
                else:
                    shared['statistics_reset']=QRectF(QPointF(deck.content.mapTo(root,QPoint())),QSizeF(deck.content.size()))
                    source=getattr(deck.content,'source_button',None)
                    if source is not None and source.isVisibleTo(root):
                        shared['statistics_reset_source']=QRectF(QPointF(source.mapTo(root,QPoint())),QSizeF(source.size()))
        return cls(rect,image,glyph_rect,glyph,island,satellites,frame if frame is not None else complete_frame(bubble),QPointF(origin),QPointF(screen.geometry().topLeft()) if screen else QPointF(),root.height()/2 if island or minimal else PANEL_RADIUS,
                   bubble.panel_page,bool(bubble.expanded),shared)


def mix_rect(a,z,f):
    return QRectF(a.x()+(z.x()-a.x())*f,a.y()+(z.y()-a.y())*f,a.width()+(z.width()-a.width())*f,a.height()+(z.height()-a.height())*f)


class SharedPart:
    """Prepared endpoint rasters and bounded reusable blend buffers."""
    def __init__(self,start,end,key):
        self.frames=[];self.rects=[];self.pixel_rects=[];self.buffers=None;self.buffer_builds=0
        self.fit=('left' if key in ('quota','conversations','today_tokens','live_rate','statistics_plot_left','statistics_reset') or key.startswith(('conversation_title_','conversation_detail_')) else
                  'right' if key.startswith('quota_value_') or key in ('today_tokens_link','today_tokens_amount','live_rate_value','statistics_plot_right') else
                  'center' if key.startswith(('statistics_tab_','statistics_range_')) or key in ('statistics_plot_title','statistics_plot_middle','statistics_plot_empty','conversation_counter') else 'stretch')
        self.backgrounds=[];self.corner=10 if key=='quota' else 6 if key in ('today_tokens','live_rate') else 0
        self.single=key.startswith('quota_track_') or key=='statistics_plot';self.background_painter=None
        for state in (start,end):
            local=state.shared_bounds[key];ratio=state.content.devicePixelRatioF()
            left,top=pixel_size(local.x(),ratio),pixel_size(local.y(),ratio)
            right,bottom=pixel_size(local.right(),ratio),pixel_size(local.bottom(),ratio)
            from PySide6.QtCore import QRect
            crop=QRect(left,top,max(1,right-left),max(1,bottom-top))
            image=state.content.copy(crop);image.setDevicePixelRatio(ratio)
            if self.fit!='stretch' and not key.startswith('conversation_'):
                self.backgrounds.append(image.toImage().pixelColor(min(image.width()-1,max(0,round(3*ratio))) if self.corner else 0,image.height()//2 if self.corner else 0))
            children=[]
            for child_key,child in state.shared_bounds.items():
                if child_key!=key and local.contains(child) and child.width()*child.height()<local.width()*local.height():
                    children.append(QRectF(child.x()-left/ratio,child.y()-top/ratio,child.width(),child.height()))
            if children:
                q=QPainter(image);q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                for child in children:q.fillRect(child,Qt.GlobalColor.transparent)
                q.end()
            self.frames.append(image);self.pixel_rects.append(crop)
            self.rects.append(QRectF(state.rect.topLeft()+QPointF(left/ratio,top/ratio),image.deviceIndependentSize()))
        self.same=self.frames[0].toImage()==self.frames[1].toImage()
        if key=='statistics':
            from dashboard_cards import paint_deck_surface
            self.background_painter=paint_deck_surface;self.frames=[];return
        if not self.same and self.backgrounds and self.backgrounds[0]==self.backgrounds[1]:
            # Identical text can have differently sized padding. Normalize it
            # once, so playback can draw one natural-size raster instead of
            # blending two copies of the same glyphs on every frame.
            ratio=max(image.devicePixelRatioF() for image in self.frames)
            width=max(r.width() for r in self.rects);height=max(r.height() for r in self.rects)
            normalized=[]
            for image in self.frames:
                out=QPixmap(pixel_size(width,ratio),pixel_size(height,ratio));out.setDevicePixelRatio(ratio);out.fill(self.backgrounds[0])
                q=QPainter(out);self._draw(q,image,QRectF(0,0,width,height));q.end();normalized.append(out)
            self.same=normalized[0].toImage()==normalized[1].toImage()
    def prepare(self,ratio):
        if self.same or self.background_painter:return
        size=(max(pixel_size(r.width(),ratio) for r in self.rects),max(pixel_size(r.height(),ratio) for r in self.rects))
        if self.buffers is not None and self.buffers[0]==(ratio,size):return
        images=[]
        for _ in range(2):
            image=QPixmap(*size);image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent);images.append(image)
        self.buffers=((ratio,size),images);self.buffer_builds+=1
    def geometry(self,f):return mix_rect(self.rects[0],self.rects[1],f)
    def _draw(self,p,image,rect):
        if self.fit=='stretch':p.drawPixmap(rect,image,QRectF(image.rect()));return
        width=image.deviceIndependentSize().width()
        x=rect.x() if self.fit=='left' else rect.right()-width if self.fit=='right' else rect.center().x()-width/2
        p.drawPixmap(QPointF(x,rect.y()),image)
    def paint(self,p,f,canvas):
        target=self.geometry(f).translated(-canvas.x(),-canvas.y())
        p.save();p.setOpacity(1.);p.setClipRect(target,Qt.ClipOperation.IntersectClip)
        if self.background_painter:
            self.background_painter(p,target);p.restore();return
        source=QRectF(self.frames[0].rect())
        if self.backgrounds:
            color=QColor(*[round(a+(z-a)*f) for a,z in zip(self.backgrounds[0].getRgb(),self.backgrounds[1].getRgb())])
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(theme_color(color))
            if self.corner:
                path=QPainterPath();path.addRoundedRect(target,self.corner,self.corner);p.setClipPath(path,Qt.ClipOperation.IntersectClip);p.drawPath(path)
            else:p.fillRect(target,color)
        if (self.single and f<=.7) or self.same or f<=0:
            self._draw(p,self.frames[0],target);p.restore();return
        if f>=1:
            self._draw(p,self.frames[1],target);p.restore();return
        self.prepare(p.device().devicePixelRatioF());mixed,weighted=self.buffers[1]
        local=QRectF(0,0,target.width(),target.height());weight=round((stage(f,.7,1.) if self.single else f)*255)
        weighted.fill(Qt.GlobalColor.transparent);q=QPainter(weighted);q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        q.setOpacity((weight+1)/256);self._draw(q,self.frames[1],local);q.end()
        mixed.fill(Qt.GlobalColor.transparent);q=QPainter(mixed);q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        q.setOpacity((256-weight)/256);self._draw(q,self.frames[0],local)
        q.setOpacity(1.);q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus);q.drawPixmap(0,0,weighted);q.end()
        p.drawPixmap(target.topLeft(),mixed);p.restore()


class SurfaceMorph:
    def translate(self,delta):
        """Move prepared geometry only; reuse every raster and blend buffer."""
        for state in (self.start,self.end):
            state.rect.translate(delta);state.icon_rect.translate(delta)
            if state.frame_origin is not None:state.frame_origin+=delta
            state.satellites=[(rect.translated(delta),image) for rect,image in state.satellites]
        for part in self.shared_parts.values():part.rects=[rect.translated(delta) for rect in part.rects]
        if self._landing:
            key,*rest=self._landing;self._landing=((key[0]+delta.x(),key[1]+delta.y(),*key[2:]),*rest)
    def __init__(self,start,end):
        self.start=start;self.end=end;self._landing=None
        self.shrinking=end.rect.width()*end.rect.height()<start.rect.width()*start.rect.height()
        self.shared_parts={};self.body_frames=(start.content,end.content)
        if start.page==end.page=='status' and start.expanded!=end.expanded and not start.island and not end.island and start.radius==end.radius==PANEL_RADIUS:
            keys=start.shared_bounds.keys()&end.shared_bounds.keys()
            # Composite containers before their text/controls. Alphabetical
            # order put `conversations` after `conversation_detail_*`, so the
            # container's opaque background erased both moving session rows.
            def layer_size(key):
                return max(state.shared_bounds[key].width()*state.shared_bounds[key].height() for state in (start,end))
            self.shared_parts={key:SharedPart(start,end,key) for key in sorted(keys,key=lambda key:(-layer_size(key),key))}
            if self.shared_parts:
                images=[]
                for index,state in enumerate((start,end)):
                    image=state.content.copy();q=QPainter(image);q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                    for part in self.shared_parts.values():
                        rect=part.pixel_rects[index];ratio=image.devicePixelRatioF()
                        q.fillRect(QRectF(rect.x()/ratio,rect.y()/ratio,rect.width()/ratio,rect.height()/ratio),Qt.GlobalColor.transparent)
                    q.end();images.append(image)
                self.body_frames=tuple(images)
    def content_opacities(self,time):
        if not self.start.island and not self.end.island and self.start.radius==PANEL_RADIUS and self.end.radius==PANEL_RADIUS:
            # Normal/detail cards share a surface. Do not fade both contents
            # to zero midway: that exposes a blank white card as a flash.
            incoming=stage(time,.10,.72)
            return 1.-incoming,incoming
        if self.shrinking:
            incoming=stage(time,.08,.42)
            return 1.-incoming,incoming
        return 1.-stage(time,0.,.18),stage(time,.24,.62)
    def geometry(self,time):
        a,z=self.start.rect,self.end.rect;f=container_progress(time)
        # One progress for every edge; staggered spring axes can visibly twist
        # the small capsule when it becomes a tall editor.
        width=a.width()+(z.width()-a.width())*f;height=a.height()+(z.height()-a.height())*f
        center=a.center().x()+(z.center().x()-a.center().x())*f
        bottom=a.bottom()+(z.bottom()-a.bottom())*f
        return QRectF(center-width/2,bottom-height,width,height)
    def bounds(self):
        rect=self.start.rect.united(self.end.rect)
        for i in range(101):rect=rect.united(self.geometry(i/100))
        for state in (self.start,self.end):
            for satellite,image in state.satellites:rect=rect.united(satellite)
        return rect.adjusted(-1,-1,1,1).toAlignedRect()
    def prepare_landing(self,canvas,ratio):
        for part in self.shared_parts.values():part.prepare(ratio)
        if self.end.frame is None:return
        key=(canvas.x(),canvas.y(),canvas.width(),canvas.height(),ratio)
        if self._landing is not None and self._landing[0]==key:return
        frames=[]
        for native in (False,True):
            image=QPixmap(pixel_size(canvas.width(),ratio),pixel_size(canvas.height(),ratio));image.setDevicePixelRatio(ratio);image.fill(Qt.GlobalColor.transparent)
            q=QPainter(image)
            if native:
                z=self.end;q.drawPixmap(raster_offset(z.frame_origin,canvas.topLeft(),ratio,z.screen_origin),z.frame)
            else:self._paint_body(q,1.,canvas)
            q.end();frames.append(image)
        self._landing=(key,frames,frames[0].copy(),frames[0].copy())
    def paint(self,p,time,canvas):
        if time<=0 and self.start.frame is not None:
            a=self.start;p.drawPixmap(raster_offset(a.frame_origin,canvas.topLeft(),p.device().devicePixelRatioF(),a.screen_origin),a.frame);return
        if time>=.9 and self.end.frame is not None:
            self.prepare_landing(canvas,p.device().devicePixelRatioF())
            f=stage(time,.9,1.);a,z=self._landing[1]
            # Premultiplied interpolation preserves alpha at translucent edges.
            # QWidget backing stores do not support every composition mode;
            # perform Plus on a raster pixmap, then submit one opaque frame.
            # Weight the source first: Plus with constant painter opacity falls
            # back to SourceOver on Qt raster paths. Complementary 8-bit alpha
            # weights keep an opaque center exactly opaque through the blend.
            weight=round(f*255);weighted=self._landing[3];weighted.fill(Qt.GlobalColor.transparent)
            q=QPainter(weighted);q.setOpacity((weight+1)/256);q.drawPixmap(0,0,z);q.end()
            mixed=self._landing[2];mixed.fill(Qt.GlobalColor.transparent);q=QPainter(mixed)
            q.setOpacity((256-weight)/256);q.drawPixmap(0,0,a)
            q.setOpacity(1.);q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus);q.drawPixmap(0,0,weighted);q.end()
            p.drawPixmap(0,0,mixed);return
        self._paint_body(p,time,canvas)
    def _paint_body(self,p,time,canvas):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a,z=self.start,self.end;rect=self.geometry(time).translated(-canvas.x(),-canvas.y())
        f=container_progress(time);blend=stage(time,0.,.42)
        ca=QColor(theme_color(ISLAND if a.island else SURFACE));cz=QColor(theme_color(ISLAND if z.island else SURFACE))
        color=QColor(*[round(x+(y-x)*blend) for x,y in zip(ca.getRgb(),cz.getRgb())])
        radius=a.radius+(z.radius-a.radius)*f
        # Match the live widget's inset fill/stroke, including antialiased alpha.
        # Filling the entire uninset rect left a brighter edge at handoff.
        inset=rect.adjusted(.5,.5,-.5,-.5)
        border_a=QColor(theme_color('#494052' if a.island else '#e0d9e6'));border_z=QColor(theme_color('#494052' if z.island else '#e0d9e6'))
        border=QColor(*[round(x+(y-x)*blend) for x,y in zip(border_a.getRgb(),border_z.getRgb())])
        path=QPainterPath();path.addRoundedRect(inset,radius,radius)
        p.save();p.setPen(QPen(border,1));p.setBrush(theme_color(color));p.drawRoundedRect(inset,radius,radius);p.setClipPath(path)
        outgoing,incoming=self.content_opacities(time)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for state,image,opacity,scale in ((a,self.body_frames[0],outgoing,1.-.025*stage(time,0.,.18)),(z,self.body_frames[1],incoming,.975+.025*incoming)):
            if opacity<=0:continue
            size=state.content.deviceIndependentSize();w=size.width()*scale;h=size.height()*scale
            target=QRectF(rect.center().x()-w/2,rect.center().y()-h/2,w,h)
            p.setOpacity(opacity);p.drawPixmap(target,image,QRectF(image.rect()))
        for part in self.shared_parts.values():part.paint(p,f,canvas)
        # Same semantic icon, moving once between the corresponding positions.
        start_icon=a.icon_rect.translated(-a.rect.x(),-a.rect.y());end_icon=z.icon_rect.translated(-z.rect.x(),-z.rect.y())
        nx=start_icon.center().x()/a.rect.width()+(end_icon.center().x()/z.rect.width()-start_icon.center().x()/a.rect.width())*f
        ny=start_icon.center().y()/a.rect.height()+(end_icon.center().y()/z.rect.height()-start_icon.center().y()/a.rect.height())*f
        icon=mix_rect(start_icon,end_icon,f);icon.moveCenter(QPointF(rect.x()+rect.width()*nx,rect.y()+rect.height()*ny))
        if self.shared_parts:icon=mix_rect(a.icon_rect,z.icon_rect,f).translated(-canvas.x(),-canvas.y())
        for image,opacity in ((a.icon,1.-blend),(z.icon,blend)):
            if opacity>0:p.setOpacity(opacity);p.drawPixmap(icon,image,QRectF(image.rect()))
        p.restore();p.setOpacity(1.)
        for state,entering in ((a,False),(z,True)):
            motion=stage(time,.32,.82) if entering else stage(time,0.,.4)
            opacity=stage(time,.42,.8) if entering else 1.-stage(time,0.,.2)
            if opacity<=0:continue
            for satellite,image in state.satellites:
                source=satellite.center()+(state.rect.center()-satellite.center())*.10 if entering else satellite.center()
                target=satellite.center() if entering else satellite.center()+(state.rect.center()-satellite.center())*.10
                center=source+(target-source)*motion-QPointF(canvas.x(),canvas.y())
                scale=.88+.12*motion if entering else 1.-.12*motion
                r=QRectF(center.x()-satellite.width()*scale/2,center.y()-satellite.height()*scale/2,satellite.width()*scale,satellite.height()*scale)
                p.setOpacity(opacity);p.drawPixmap(r,image,QRectF(image.rect()))
        p.setOpacity(1.)
