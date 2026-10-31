from theme_registry import color as theme_color
from theme_runtime import set_theme_style,theme_style_source
import json, random, sys, time, threading, gzip, os
from pathlib import Path
from collections import OrderedDict
from datetime import datetime
from PIL import Image
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QRegion, QCursor
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QProgressBar, QMenu, QMessageBox, QProgressDialog
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from quota import read_quota, quota_windows
from version import VERSION
from typography import FONT_CSS

ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
ASSETS=ROOT/'outputs/白龙桌宠素材'
FLAGS=Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.Tool

def clamp_position(position,size,area):
    """Keep the full pet window inside one monitor's usable rectangle."""
    max_x=max(area.left(),area.right()-size.width()+1)
    max_y=max(area.top(),area.bottom()-size.height()+1)
    return QPoint(max(area.left(),min(position.x(),max_x)),
                  max(area.top(),min(position.y(),max_y)))

class QuotaWorker(QThread):
    ready=Signal(object)
    failed=Signal(object)
    def __init__(self,parent=None,manual=False):
        super().__init__(parent);self.cancel=threading.Event();self.manual=manual
    def run(self):
        try: self.ready.emit(quota_windows(read_quota(cancel=self.cancel,manual=self.manual)))
        except Exception as error: self.failed.emit(error)

class Bubble(QWidget):
    def __init__(self):
        super().__init__(None, FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.layout=QVBoxLayout(self); self.layout.setContentsMargins(13,10,13,10);self.layout.setSpacing(5)
        self.setFixedWidth(256)
        set_theme_style(self,'QLabel {'+FONT_CSS+'color:#332644;font-size:12px;} QProgressBar {background:#eee8f5;border:1px solid #c8b5dc;border-radius:7px;height:14px;} QProgressBar::chunk {background:#a47bc9;border-radius:6px;}')
    def paintEvent(self,event):
        from performance_metrics import METRICS
        METRICS.add('paint')
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.GlobalColor.white);painter.setPen(Qt.GlobalColor.transparent)
        painter.drawRoundedRect(self.rect(),16,16)
    def clear(self):
        while self.layout.count():
            widget=self.layout.takeAt(0).widget();widget.deleteLater()
    def label(self,text):
        label=QLabel(text);label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText);self.layout.addWidget(label)
    def message(self,text):
        self.is_quota_result=False
        self.clear();self.label(text);self.adjustSize();self.show()
    def quota(self,windows):
        self.is_quota_result=True
        self.clear();self.label('Codex 剩余额度')
        for window in windows:
            value=window['remaining']
            self.label(window['name']+' · '+(f'剩余 {value:g}%' if value is not None else '暂未提供'))
            bar=QProgressBar();bar.setRange(0,100)
            bar.setValue(round(value) if value is not None else 0);bar.setTextVisible(False);self.layout.addWidget(bar)
            if window['resetsAt']:
                self.label('重置：'+datetime.fromtimestamp(window['resetsAt']).strftime('%m月%d日 %H:%M'))
        self.adjustSize();self.show()

class Pet(QWidget):
    def __init__(self):
        super().__init__(None,FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('白龙桌宠');self.setFixedSize(256,256)
        self.manifest=({'idle':{'id':'unavailable','file':'unavailable.webp','durationMs':1000},'variants':[]} if getattr(self,'_materials_missing',False)
            else json.loads((getattr(self,'asset_root',ASSETS)/'素材清单.json').read_text(encoding='utf-8')))
        self.variants=[v for v in self.manifest['variants'] if self.asset_path(v).is_file()]
        self.idles=[self.manifest['idle']]+self.manifest.get('additionalIdleAnimations',[])[:1]
        self.cache=OrderedDict();self.pinned_frames={};self.frames=[];self.current=None;self.mode='idle';self.index=0
        self.frame_size=min(512,max(256,round(256*max(s.devicePixelRatio() for s in QApplication.screens()))))
        self.transition=None
        self.bubble=Bubble();self.generation=0;self.worker=None;self.quota_inflight=False;self.dragging=False;self.last_click=None
        self.click_timer=QTimer(self);self.click_timer.setTimerType(Qt.TimerType.PreciseTimer);self.click_timer.setSingleShot(True);self.click_timer.setInterval(250);self.click_timer.timeout.connect(self.single_click)
        self.bubble_timer=QTimer(self);self.bubble_timer.setSingleShot(True);self.bubble_timer.timeout.connect(self.dismiss_bubble)
        self.tick=QTimer(self);self.tick.setTimerType(Qt.TimerType.PreciseTimer);self.tick.setInterval(16);self.tick.timeout.connect(self.animate)
        area=QApplication.primaryScreen().availableGeometry()
        self.move(self.constrained_position(QPoint(area.right()-360,area.bottom()-340)))
        for screen in QApplication.screens():self.watch_screen(screen)
        QApplication.instance().screenAdded.connect(self.watch_screen)
        QApplication.instance().screenRemoved.connect(lambda screen:QTimer.singleShot(0,self.ensure_on_screen))
        self.idle()
        # Prepare every animation once: neither clicking nor returning to idle
        # should perform disk IO, WebP decoding or cache eviction.
        items=self.idles+self.variants+[self.manifest[name] for name in ('dragAnimation','landingAnimation','quotaAnimation') if self.manifest.get(name)]
        progress=None
        if QApplication.platformName()!='offscreen' and not getattr(self,'LAZY',False):
            progress=QProgressDialog('白龙正在准备动作，请稍等…','',0,len(items))
            progress.setCancelButton(None);progress.setWindowTitle('白龙桌宠');progress.setMinimumDuration(0);progress.show()
        for i,item in enumerate([] if getattr(self,'LAZY',False) else items):
            key=str(self.asset_path(item));self.pinned_frames[key]=self.load(item);self.cache.pop(key,None)
            if progress:progress.setValue(i+1);QApplication.processEvents()
        if progress:progress.close()
        self.transition=None
        self.started=time.monotonic();self.tick.start()
    def constrained_position(self,position,pointer=None):
        screens=QApplication.screens()
        # Allow crossing monitors, but never use their bounding union: it can
        # contain empty gaps or permit half the pet to hang off a monitor.
        screen=QApplication.screenAt(pointer) if pointer is not None else None
        if screen:return clamp_position(position,self.size(),screen.availableGeometry())
        candidates=[clamp_position(position,self.size(),s.availableGeometry()) for s in screens]
        return min(candidates,key=lambda p:(p.x()-position.x())**2+(p.y()-position.y())**2) if candidates else position
    def watch_screen(self,screen):
        screen.availableGeometryChanged.connect(lambda area:self.ensure_on_screen())
        QTimer.singleShot(0,self.ensure_on_screen)
    def ensure_on_screen(self):
        position=self.constrained_position(self.pos())
        if position!=self.pos():
            self.move(position)
            if self.dragging:self.origin=self.pos();self.press_pos=QCursor.pos()
        if self.bubble.isVisible():self.position_bubble()
    def asset_path(self,item):
        # Optional playbackFile allows future formats without changing the manifest's video source.
        return ASSETS/(item.get('playbackFile') or item['file'].replace('.webm','.webp'))
    def load(self,item):
        path=self.asset_path(item);key=str(path)
        if key in self.pinned_frames:return self.pinned_frames[key]
        if key in self.cache: self.cache.move_to_end(key);return self.cache[key]
        frames=[]
        packed=ROOT/'app/cache'/f'{item["id"]}-hq.rgba.gz';metadata=packed.with_suffix('.json')
        if packed.is_file() and metadata.is_file():
            meta=json.loads(metadata.read_text(encoding='utf-8'));stat=path.stat()
            if meta['sourceSize']==stat.st_size and meta['sourceMtime']==stat.st_mtime_ns:
                raw=gzip.decompress(packed.read_bytes());stride=512*512*4
                if len(raw)==meta['frames']*stride:
                    for offset in range(0,len(raw),stride):
                        pixmap=QPixmap.fromImage(QImage(raw[offset:offset+stride],512,512,2048,QImage.Format.Format_RGBA8888).copy())
                        frames.append(pixmap.scaled(self.frame_size,self.frame_size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation) if self.frame_size!=512 else pixmap)
        if frames:
            self.cache[key]=frames
            while len(self.cache)>2:self.cache.popitem(last=False)
            return frames
        with Image.open(path) as source:
            for i in range(source.n_frames):
                source.seek(i);im=source.convert('RGBA').resize((self.frame_size,self.frame_size),Image.Resampling.LANCZOS)
                raw=im.tobytes();qimage=QImage(raw,self.frame_size,self.frame_size,self.frame_size*4,QImage.Format.Format_RGBA8888).copy()
                frames.append(QPixmap.fromImage(qimage))
        if not frames: raise RuntimeError('动画没有可播放帧：'+str(path))
        self.cache[key]=frames
        while len(self.cache)>2:self.cache.popitem(last=False)
        return frames
    def play(self,item,mode):
        self.frames=self.load(item);self.current=item;self.mode=mode;self.index=0;self.started=time.monotonic();self.update_frame()
        self.transition=None
    def idle(self):
        item=random.choices(self.idles,weights=[4,1][:len(self.idles)])[0]
        self.play(item,'idle')
    def update_frame(self):
        # Windows layered windows use per-pixel alpha. A binary mask would
        # dither the soft character edges and damage transparent rendering.
        self.update()
    def animate(self):
        duration=self.current.get('durationMs',4000)/1000
        elapsed=time.monotonic()-self.started
        if elapsed>=duration:
            if self.mode=='drag':self.play(self.manifest.get('dragAnimation') or self.idles[0],'drag')
            else:self.idle()
            return
        index=min(len(self.frames)-1,int(elapsed/duration*len(self.frames)))
        if self.transition:self.update()
        if index!=self.index:self.index=index;self.update_frame()
    def paintEvent(self,event):
        from performance_metrics import METRICS
        METRICS.add('paint')
        if self.frames:
            painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            # Clear the complete translucent backing area before painting a new
            # silhouette; soft alpha must never accumulate old frame contents.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.rect(),Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self.draw_frame(painter,QRectF(self.rect()))
    def frame_target(self,canvas):
        scale=self.current.get('renderScale',1.0);offset=self.current.get('renderOffset',[0,0])
        width,height=canvas.width()*scale,canvas.height()*scale
        return QRectF(canvas.x()+(canvas.width()-width)/2+canvas.width()*offset[0],canvas.y()+canvas.height()-height+canvas.height()*offset[1],width,height)
    def draw_frame(self,painter,canvas):
        target=self.frame_target(canvas)
        frame=self.frames[self.index];painter.drawPixmap(target,frame,QRectF(frame.rect()))
    def snapshot_frame(self):
        pixmap=QPixmap(self.frame_size,self.frame_size);pixmap.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pixmap);self.draw_frame(painter,QRectF(pixmap.rect()));painter.end();return pixmap
    def position_bubble(self):
        screen=QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        area=screen.availableGeometry();pet=self.frameGeometry()
        width,height=self.bubble.width(),self.bubble.height();gap=12
        if not getattr(self.bubble,'is_quota_result',False):
            x=max(area.left(),min(pet.center().x()-width//2,area.right()-width+1))
            y=pet.top()-height-gap
            if y<area.top():y=pet.bottom()+gap+1
            y=max(area.top(),min(y,area.bottom()-height+1))
            self.bubble.move(x,y);return
        # Prefer the sides; choose a screen-safe position with no character overlap.
        candidates=[(pet.right()+gap+1,pet.center().y()-height//2),
                    (pet.left()-width-gap,pet.center().y()-height//2),
                    (pet.center().x()-width//2,pet.top()-height-gap),
                    (pet.center().x()-width//2,pet.bottom()+gap+1)]
        positions=[]
        for x,y in candidates:
            x=max(area.left(),min(x,area.right()-width+1))
            y=max(area.top(),min(y,area.bottom()-height+1))
            overlap=pet.intersected(QRect(x,y,width,height))
            score=max(0,overlap.width())*max(0,overlap.height())
            positions.append((score,x,y))
        _,x,y=min(positions,key=lambda item:item[0]);self.bubble.move(x,y)
    def say(self,text,ms=4000):
        self.bubble_timer.stop();self.bubble.message(text);self.position_bubble()
        if ms:self.bubble_timer.start(ms)
    def dismiss_bubble(self):
        self.bubble.hide()
        if self.mode=='quota':self.idle()
    def play_click_sound(self):
        # Synthetic clicks in isolated/native probes must never reach speakers.
        if os.environ.get('BAILONG_ISOLATED')=='1' or QApplication.platformName()=='offscreen':return
        if sys.platform=='win32':
            import winsound
            sound=ROOT/'app/sounds/click.wav'
            if sound.is_file():
                try:winsound.PlaySound(str(sound),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
                except RuntimeError:pass
    def choose(self,item):
        self.click_timer.stop();self.last_click=None;self.generation+=1
        try:self.play_click_sound();self.play(item,'variant');self.say(item.get('line',''),4000)
        except Exception as error:self.idle();self.say('这段动画暂时无法播放：'+str(error))
    def single_click(self):
        self.last_click=None
        if self.variants:self.choose(random.choice(self.variants))
    def quota(self):
        self.click_timer.stop();self.last_click=None;self.generation+=1;token=self.generation
        self.play_click_sound()
        self.play(self.manifest.get('quotaAnimation') or self.idles[0],'quota')
        self.say('让我看看额度还有多少。。。。。。',0)
        if self.quota_inflight:
            # Repeated requests share the in-flight read; delivery uses the newest generation.
            self.quota_generation=token;return
        self.quota_generation=token;self.quota_inflight=True;self.worker=QuotaWorker(self,manual=True)
        self.worker.ready.connect(self.quota_ready);self.worker.failed.connect(self.quota_failed);self.worker.start()
    def quota_ready(self,windows):
        self.quota_inflight=False
        if self.quota_generation!=self.generation:return
        self.bubble.quota(windows);self.position_bubble();self.bubble_timer.start(12000)
    def quota_failed(self,error):
        self.quota_inflight=False
        if self.quota_generation==self.generation:self.say('暂时查不到额度：'+str(error),8000)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.RightButton:
            self.click_timer.stop();self.last_click=None
            menu=QMenu(self)
            for item in self.variants:
                action=menu.addAction(item['id']+' · '+item['name']);action.triggered.connect(lambda checked=False,v=item:self.choose(v))
            menu.addSeparator();menu.addAction('退出桌宠',self.close);menu.exec(event.globalPosition().toPoint());return
        if event.button()==Qt.MouseButton.LeftButton:
            self.press_pos=event.globalPosition().toPoint();self.origin=self.pos();self.dragging=False
    def mouseDoubleClickEvent(self,event):
        # Qt may emit this before mousePressEvent for the second physical press.
        self.mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if event.buttons()&Qt.MouseButton.LeftButton and hasattr(self,'press_pos'):
            delta=event.globalPosition().toPoint()-self.press_pos
            if delta.manhattanLength()>8 and not self.dragging:
                self.dragging=True;self.click_timer.stop();self.last_click=None;self.generation+=1
                self.bubble_timer.stop()
                if hasattr(self,'begin_drag_panel'):self.begin_drag_panel()
                elif not getattr(self,'settings',{}).get('panel_detached'):self.bubble.hide()
                self.play(self.manifest.get('dragAnimation') or self.idles[0],'drag')
            if self.dragging:
                self.move(self.constrained_position(self.origin+delta,event.globalPosition().toPoint()))
                self.position_bubble()
    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        if self.dragging:
            self.dragging=False;self.last_click=None;self.click_timer.stop()
            landing=self.manifest.get('landingAnimation')
            if landing:self.play(landing,'landing')
            else:self.idle()
            return
        now=time.monotonic()
        if self.last_click is not None and now-self.last_click<=.25:self.quota()
        else:self.last_click=now;self.click_timer.start()
    def closeEvent(self,event):
        self.tick.stop();self.bubble.close()
        if self.worker and self.worker.isRunning():self.worker.cancel.set();self.worker.wait(3000)
        QApplication.quit();event.accept()

def main():
    if '--autostart' in sys.argv:
        from autostart import main as monitor
        return monitor()
    if '--self-test' in sys.argv:
        from selftest import run
        return run(ROOT)
    app=QApplication(sys.argv)
    if '--enable-autostart' in sys.argv or '--disable-autostart' in sys.argv:
        from autostart import enable_autostart,disable_autostart
        try:
            if '--enable-autostart' in sys.argv:
                enable_autostart();message='已开启：以后登录Windows时，助手会自动运行；打开GPT后启动桌宠。\n如要移动桌宠文件夹，请先关闭自动启动，移好后再开启。'
            else:disable_autostart();message='已关闭桌宠自动启动。'
            QMessageBox.information(None,'白龙桌宠',message);return 0
        except Exception as error:QMessageBox.critical(None,'设置失败',str(error));return 1
    socket=QLocalSocket();socket.connectToServer('bailong-desktop-pet-v1')
    if socket.waitForConnected(150):return 0
    QLocalServer.removeServer('bailong-desktop-pet-v1');server=QLocalServer();server.listen('bailong-desktop-pet-v1')
    try:
        pet=Pet();pet.show()
        def record_startup():
            # pythonw can inherit a hidden startup state from a launcher.
            # Explicitly show this app's own window without stealing focus.
            native_visible=pet.isVisible()
            if sys.platform=='win32':
                import ctypes
                handle=int(pet.winId())
                ctypes.windll.user32.ShowWindow(handle,4)
                native_visible=bool(ctypes.windll.user32.IsWindowVisible(handle))
            (ROOT/'app').mkdir(exist_ok=True)
            (ROOT/'app/运行状态.json').write_text(json.dumps({'version':VERSION,'pid':os.getpid(),'visible':pet.isVisible(),'nativeVisible':native_visible,'windowId':int(pet.winId()),'variants':len(pet.variants),'position':[pet.x(),pet.y()],'displaySize':[pet.width(),pet.height()],'frameSize':[self_size for self_size in (pet.frames[0].width(),pet.frames[0].height())]},ensure_ascii=False),encoding='utf-8')
        QTimer.singleShot(1000,record_startup)
        if '--preview' in sys.argv:
            QTimer.singleShot(500,lambda:pet.grab().save(str(ROOT/'app/桌宠窗口预览.png')))
            QTimer.singleShot(900,app.quit)
    except Exception as error:QMessageBox.critical(None,'白龙桌宠启动失败',str(error));return 1
    return app.exec()

if __name__=='__main__':sys.exit(main())
