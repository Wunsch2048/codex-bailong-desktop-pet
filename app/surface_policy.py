"""One layering and foreground policy for the pet's native surfaces."""
import os

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget


class SurfacePolicy(QObject):
    def __init__(self, pet, api=None):
        super().__init__(pet)
        self.pet=pet;self.applied={};self.queued=False;self.foreground_key=None;self.foreground_codex=False
        self.force_bottom=False
        if api is None and QApplication.platformName()=='windows':
            from video_fullscreen import WindowAPI
            api=WindowAPI()
        self.api=api
        self.timer=QTimer(self);self.timer.setInterval(300);self.timer.timeout.connect(self.poll_focus)
        if self.api is not None:QApplication.instance().installEventFilter(self)

    def owned(self,widget):
        bubble=self.pet.bubble
        while widget is not None:
            if widget is self.pet or widget is bubble:return True
            handle=widget.windowHandle()
            if handle is not None:
                owner=handle.transientParent()
                if owner is not None and owner in (self.pet.windowHandle(),bubble.windowHandle(),
                        bubble.report.windowHandle() if bubble.report else None):return True
            widget=widget.parentWidget()
        return False

    def configure(self):
        self.sync_layer()
        enabled=self.api is not None and self.pet.settings['codex_focus_only']
        if enabled:
            if not self.timer.isActive():self.timer.start()
            self.poll_focus()
        else:
            self.timer.stop();self.foreground_key=None;self.pet.set_focus_hidden(False)

    def sync_layer(self):
        self.queued=False
        pet=self.pet;layer=pet.settings['window_layer']
        force_bottom=self.force_bottom;self.force_bottom=False
        if self.api is None:
            for widget in (pet,pet.bubble):
                update_qt_layer(widget,layer)
            if pet.bubble.report and not pet.bubble.report.isVisible():update_qt_layer(pet.bubble.report,layer)
            return
        if pet._video_yielded or pet._fullscreen_yielded:return
        for widget in (pet,pet.bubble):
            if not widget.isVisible() and not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
                update_qt_layer(widget,layer)
        windows=[w for w in QApplication.topLevelWidgets() if w.isVisible() and
                 w.windowType()!=Qt.WindowType.Popup and w.testAttribute(Qt.WidgetAttribute.WA_WState_Created) and self.owned(w)]
        # Order the two independently owned roots before their transient tools.
        windows.sort(key=lambda w:0 if w is pet else 1 if w is pet.bubble else 2)
        desired={}
        for widget in windows:
            hwnd=int(widget.winId());previous=self.applied.get(hwnd)
            if previous!=layer or self.api.topmost(hwnd)!=(layer=='top') or (layer=='bottom' and force_bottom):
                if not self.api.set_layer(hwnd,layer,previous=='bottom'):continue
            desired[hwnd]=layer
        self.applied=desired
        self.stack_roots()

    def stack_roots(self):
        pet=self.pet;bubble=pet.bubble
        if (self.api is None or pet.settings['window_layer']=='top' or pet._video_yielded or pet._fullscreen_yielded or
                bubble.panel_page!='status' or not pet.isVisible() or not bubble.isVisible()):return
        # Status stays with the character even when independently positioned.
        self.api.stack_with(int(bubble.winId()),int(pet.winId()))
        if bubble.report and bubble.report.isVisible():
            self.api.stack_with(int(bubble.report.winId()),int(bubble.winId()))

    def poll_focus(self):
        hwnd=self.api.foreground() if self.api is not None else 0
        if not hwnd:return
        pid=self.api.window_pid(hwnd)
        if not pid:return
        pet=self.pet
        if pid==os.getpid():
            if pet.editing_while_focus_hidden():
                pet.set_focus_hidden(True);return
            # Clicking the pet from Codex is still part of that interaction.
            if self.foreground_codex and not pet._focus_hidden:return
        key=(hwnd,pid)
        if key!=self.foreground_key:
            from desktop_services import codex_desktop_process
            self.foreground_key=key;self.foreground_codex=codex_desktop_process(pid)
        pet._focus_editor_override=False
        pet.set_focus_hidden(not self.foreground_codex)

    def eventFilter(self,obj,event):
        kind=event.type()
        if (self.api is not None and kind in (QEvent.Type.Show,QEvent.Type.Hide,QEvent.Type.WinIdChange,QEvent.Type.WindowDeactivate)
                and isinstance(obj,QWidget) and obj.isWindow() and self.owned(obj)):
            if kind in (QEvent.Type.Show,QEvent.Type.WindowDeactivate) and self.pet.settings['window_layer']=='bottom':
                self.force_bottom=True
            if not self.queued:self.queued=True;QTimer.singleShot(0,self,self.sync_layer)
        return False

    def shutdown(self):
        self.timer.stop()
        if self.api is not None:QApplication.instance().removeEventFilter(self)


def update_qt_layer(widget,layer):
    top=Qt.WindowType.WindowStaysOnTopHint;bottom=Qt.WindowType.WindowStaysOnBottomHint
    flags=widget.windowFlags();wanted=flags&~(top|bottom)
    if layer=='top':wanted|=top
    elif layer=='bottom':wanted|=bottom
    if wanted!=flags:
        visible=widget.isVisible();widget.setWindowFlags(wanted)
        if visible:widget.show()

def card_layer(bubble):
    owner=bubble.owner_pet() if hasattr(bubble,'owner_pet') else None
    if getattr(owner,'_video_yielded',False):return 'normal'
    if owner and 'window_layer' in getattr(owner,'settings',{}):return owner.settings['window_layer']
    return 'top' if bubble.windowFlags()&Qt.WindowType.WindowStaysOnTopHint else 'normal'
