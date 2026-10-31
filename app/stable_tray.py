"""Qt-facing adapter for the one fixed-path Windows tray owner."""
import base64,hashlib,json,os,secrets,shutil,subprocess,sys
from pathlib import Path
from PySide6.QtCore import Qt,QObject,Signal,QRect,QPoint,QBuffer,QIODevice,QTimer
from PySide6.QtGui import QCursor,QGuiApplication,QIcon
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QSystemTrayIcon

HOST_NAME='BailongTray.exe'
TRAY_GUID='6baea166-d3d9-4ffb-88c4-39a669a20e69'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def prepare_host(source,installation):
    source=Path(source).resolve();target=Path(installation).resolve()/'tray'/HOST_NAME
    if not source.is_file():raise OSError('缺少固定托盘宿主')
    if target.parent.is_symlink() or target.parent.is_junction():raise OSError('托盘目录不能为链接')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and sha(source)==sha(target):return target
    # Never terminate an unrelated process with a similar filename.
    import psutil
    for process in psutil.process_iter(['exe']):
        try:
            if process.info['exe'] and Path(process.info['exe']).resolve()==target.resolve():
                process.terminate();process.wait(2)
        except psutil.NoSuchProcess:pass
    stage=target.with_suffix('.pending')
    shutil.copyfile(source,stage)
    if sha(stage)!=sha(source):raise OSError('托盘宿主复制校验失败')
    if target.exists():shutil.copyfile(target,target.with_suffix('.previous'))
    os.replace(stage,target)
    return target

class StableTray(QObject):
    activated=Signal(object)
    native_hover=Signal()
    changed=Signal()
    def __init__(self,icon,parent=None):
        super().__init__(parent);self._icon=QIcon(icon);self._menu=None;self._visible=False;self._rect=QRect()
        self.ready=False;self.error='';self.process=None;self.socket=None;self._buffer=b'';self._attempts=0
        self.server=QLocalServer(self);self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connect)
        self.nonce=secrets.token_hex(24);self.pipe='BailongTray-'+str(os.getpid())+'-'+self.nonce[:12]
    def setToolTip(self,text):pass  # custom HintBubble owns text, never a native tooltip
    def toolTip(self):return ''
    def setContextMenu(self,menu):
        self._menu=menu
        if menu:menu.aboutToHide.connect(self._menu_closed)
    def contextMenu(self):return self._menu
    def _menu_closed(self):
        self._send(dict(kind='focus'))
        if sys.platform=='win32' and self._menu is not None:
            import ctypes
            from ctypes import wintypes
            user=ctypes.WinDLL('user32',use_last_error=True)
            user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
            user.PostMessageW(int(self._menu.winId()),0,0,0)
    def isVisible(self):return self._visible and self.ready
    def geometry(self):return QRect(self._rect)
    def icon(self):return QIcon(self._icon)
    def setIcon(self,icon):self._icon=QIcon(icon);self._publish_icon()
    def show(self):
        if self._visible:return
        self._visible=True
        try:
            from storage_locations import install_root
            source=Path(sys.executable).resolve().parent/'tray'/HOST_NAME
            self.host=prepare_host(source,install_root())
            if not self.server.listen(self.pipe):raise OSError(self.server.errorString())
            self.process=subprocess.Popen([str(self.host),self.pipe,self.nonce,str(os.getpid())],creationflags=0x08000000)
        except (OSError,ValueError) as e:
            self.error=str(e);self._visible=False;self.changed.emit()
    def _connect(self):
        candidate=self.server.nextPendingConnection()
        if self.socket is not None:candidate.disconnectFromServer();candidate.deleteLater();return
        self.socket=candidate;candidate.readyRead.connect(self._read)
        candidate.disconnected.connect(self._disconnected)
        if candidate.bytesAvailable():self._read()
    def _disconnected(self):self.ready=False;self.error='托盘连接已结束';self.changed.emit()
    def _send(self,value):
        if self.socket is not None:self.socket.write((json.dumps(value,ensure_ascii=False)+'\n').encode('utf-8'));self.socket.flush()
    def _publish_icon(self):
        if self.socket is None:return
        image=self._icon.pixmap(32,32);buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
        self._send(dict(kind='icon',png=base64.b64encode(bytes(buffer.data())).decode('ascii')))
    def _read(self):
        self._buffer+=bytes(self.socket.readAll())
        if len(self._buffer)>262144:self.socket.disconnectFromServer();return
        while b'\n' in self._buffer:
            line,self._buffer=self._buffer.split(b'\n',1)
            try:event=json.loads(line)
            except (ValueError,UnicodeError):continue
            kind=event.get('kind')
            if kind in ('connected','ready'):
                if event.get('secret')!=self.nonce:self.socket.disconnectFromServer();return
                if kind=='connected':self._publish_icon()
                else:
                    self.ready=bool(event.get('ok'));self.error='' if self.ready else 'Shell拒绝托盘注册：'+str(event.get('error'))
                    if not self.ready and self._attempts<4:
                        self._attempts+=1;QTimer.singleShot(250*self._attempts,self,self._publish_icon)
                    self.changed.emit()
                continue
            if kind=='error':self.error=str(event.get('error',''));self.changed.emit();continue
            point=QCursor.pos();screen=QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen();scale=screen.devicePixelRatio()
            if event.get('geometryValid'):
                name=str(event.get('monitor','')).split('\\')[-1].casefold()
                screen=next((s for s in QGuiApplication.screens() if s.name().split('\\')[-1].casefold()==name),screen)
                scale=screen.devicePixelRatio();origin=screen.geometry().topLeft()
                self._rect=QRect(round(origin.x()+(event['left']-event.get('monitorLeft',0))/scale),round(origin.y()+(event['top']-event.get('monitorTop',0))/scale),round(event['width']/scale),round(event['height']/scale))
            if kind=='hover':self.native_hover.emit()
            elif kind in ('click','doubleClick'):
                self.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick if kind=='doubleClick' else QSystemTrayIcon.ActivationReason.Trigger)
            elif kind=='context' and self._menu:self._show_context(point)
    def _show_context(self,point):
        menu=self._menu
        if menu is None:return
        menu.ensurePolished();handle=int(menu.winId())
        if sys.platform=='win32':
            import ctypes
            from ctypes import wintypes
            user=ctypes.WinDLL('user32',use_last_error=True)
            user.SetForegroundWindow.argtypes=[wintypes.HWND];user.SetForegroundWindow.restype=wintypes.BOOL
            # The host granted foreground rights before forwarding the event.
            user.SetForegroundWindow(handle)
        menu.popup(point)
        if sys.platform=='win32':user.SetForegroundWindow(handle)
        menu.activateWindow();menu.setFocus(Qt.FocusReason.PopupFocusReason)
    def silentMessage(self,title,text):self._send(dict(kind='message',title=title[:63],text=text[:255]))
    def hide(self):
        self._visible=False;self.ready=False;self._send(dict(kind='close'))
        if self.socket:self.socket.disconnectFromServer()
        self.server.close()
    def diagnostics(self):return dict(backend='fixed-host',ready=self.ready,error=self.error,guid=TRAY_GUID,path=str(getattr(self,'host','')),pid=self.process.pid if self.process else None)
