"""使用 niri 实际布局和原生交互移动，避免 XWayland 虚拟坐标反馈"""
import json
import os
from PySide6.QtCore import QObject, QPoint, QRect, QEvent, QTimer, Qt
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QGraphicsOpacityEffect, QApplication


def bubble_position(x, y, pet_size, bubble_size, placement_height, area, reserve=0):
    """沿用原气泡间距、居中、上下翻转和屏幕边缘约束，坐标均为输出内逻辑像素"""
    width, height = bubble_size
    bx = x + (pet_size[0] - width) // 2
    by = y - height - 8
    if y - placement_height - 8 < area.top():
        by = y + pet_size[1] + 8
    return QPoint(round(max(area.left(), min(bx, area.right() - width + 1))),
                  round(max(area.top() + reserve, min(by, area.bottom() - height + 1))))


class NiriWindows(QObject):
    """订阅实际布局并移动本进程角色与气泡，不修改 niri 配置"""
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        pet.installEventFilter(self)
        self.opacity = QGraphicsOpacityEffect(pet.bubble)
        self.opacity.setOpacity(1)
        pet.bubble.setGraphicsEffect(self.opacity)
        self.reveal = QTimer(self)
        self.reveal.setSingleShot(True)
        self.reveal.timeout.connect(self.reveal_bubble)
        self.windows = {}
        self.workspaces = {}
        self.restored = False
        self.restore_sent = None
        self.pending = set()
        self.last = None
        self.move_target = None
        self.move_waiting = False
        self.move_timer = QTimer(self)
        self.move_timer.setInterval(33)
        self.move_timer.timeout.connect(self.flush_move)
        self.move_timeout = QTimer(self)
        self.move_timeout.setSingleShot(True)
        self.move_timeout.timeout.connect(self.movement_failed)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(300)
        self.save_timer.timeout.connect(self.pet.save_settings)
        self.stream = QLocalSocket(self)
        self.stream.connected.connect(lambda: self.stream.write(b'"EventStream"\n'))
        self.stream.readyRead.connect(self.read)
        self.stream.disconnected.connect(self.disconnected)
        self.stream.connectToServer(os.environ['NIRI_SOCKET'])

    def reveal_bubble(self):
        """主气泡恢复绘制后撤销跟随画布，拖动中不提前交接"""
        if not getattr(self.pet, '_niri_drag', False):
            self.opacity.setOpacity(1)
            self.pet.bubble.repaint()
            self.surfaces.finish_pet_drag()

    def character(self):
        """仅定位本进程已登记的角色窗口"""
        return next((w for w in self.windows.values() if w.get('title') == self.pet.windowTitle()), None)

    def actual_screen(self):
        """使用工作区所属输出，避免跨屏时 Qt 屏幕信号延迟"""
        window = self.character()
        output = self.workspaces.get(window.get('workspace_id')) if window else None
        return next((s for s in QApplication.screens() if s.name() == output), None)

    def restore_position(self):
        """先移动到目标输出，再等待布局确认后恢复输出内位置"""
        if self.restored:
            return
        from .placement import restore_target
        target = restore_target(self.pet.settings.get('screen_position'), self.pet.size(), QApplication.screens())
        window = self.character()
        screen = self.actual_screen()
        current = self.actual_position()
        if not window or not screen or current is None:
            return
        if not window.get('is_floating'):
            if self.restore_sent != 'floating':
                self.restore_sent = 'floating'
                self.action('MoveWindowToFloating', id=window['id'])
            return
        if target is not None:
            destination, point = target
            if screen.name() != destination.name():
                key = ('output', destination.name())
                if self.restore_sent != key:
                    self.restore_sent = key
                    self.opacity.setOpacity(0)
                    self.action('MoveWindowToMonitor', id=window['id'], output=destination.name())
                return
            delta = point - current
            if delta.manhattanLength() > 1:
                key = ('position', point.x(), point.y())
                if self.restore_sent != key:
                    self.restore_sent = key
                    self.opacity.setOpacity(0)
                    self.action('MoveFloatingWindow', id=window['id'],
                                x={'AdjustFixed': delta.x()}, y={'AdjustFixed': delta.y()})
                return
        self.restored = True
        self.pet.remember_wander_home()
        self.pet.save_settings()
        self.reveal.start(700)

    def actual_position(self):
        """将输出内布局坐标转换为 Qt 屏幕逻辑坐标，保留多屏原点"""
        window = self.character()
        if window is None:
            return None
        layout = window['layout']
        xy = layout.get('tile_pos_in_workspace_view')
        if xy is None:
            return None
        offset = layout['window_offset_in_tile']
        screen = self.actual_screen()
        if screen is None:
            return None
        return QPoint(round(xy[0] + offset[0]), round(xy[1] + offset[1])) + screen.geometry().topLeft()

    def request_move(self, point):
        """只保留最新位置，单个未确认请求期间不累计相对位移"""
        if self.pet.closing or self.pet.dragging or self.pet._pointer_pressed or self.pet.settings.get('no_move'):
            return
        if self.actual_position() is None:
            return
        self.move_target = QPoint(point)
        if not self.move_timer.isActive():
            self.move_timer.start()

    def cancel_move(self):
        """取消尚未发送的位移并停止确认计时，防止输入打断后补发旧目标"""
        self.move_target = None
        self.move_timer.stop()
        self.move_timeout.stop()
        self.move_waiting = False

    def movement_failed(self):
        """布局确认超时后停止走动，避免脱离实际窗口位置继续积分"""
        self.cancel_move()
        self.move_waiting = False
        self.pet.stop_walk()
        print('niri 移动未得到布局确认，已暂停本次走动', flush=True)

    def flush_move(self):
        """以最新已确认位置计算增量，限制为每秒最多约三十次请求"""
        pet = self.pet
        if pet.closing or not pet.isVisible() or pet.dragging or pet._pointer_pressed or pet.settings.get('no_move'):
            self.cancel_move()
            return
        if self.move_waiting or self.move_target is None:
            return
        current = self.actual_position()
        if current is None:
            self.cancel_move()
            pet.stop_walk()
            return
        screen = self.actual_screen()
        if screen is None:
            self.cancel_move()
            return
        area = screen.availableGeometry()
        from pet import clamp_position
        target = clamp_position(self.move_target, pet.size(), area)
        delta = target - current
        if delta.isNull():
            self.cancel_move()
            return
        self.move_waiting = True
        self.move_timeout.start(1500)
        self.action('MoveFloatingWindow', id=self.character()['id'],
                    x={'AdjustFixed': delta.x()}, y={'AdjustFixed': delta.y()})

    def eventFilter(self, watched, event):
        """原生交互移动结束后指针重新进入窗口，恢复原松手动画与气泡"""
        if getattr(self.pet, '_niri_drag', False):
            if event.type() == QEvent.Type.Leave:
                self.pet._niri_left = True
            # Qt 6.9 startSystemMove 会发送模拟松手，真正结束以 Leave 后的 Enter 为准
            if event.type() == QEvent.Type.MouseButtonRelease:
                return True
            if event.type() == QEvent.Type.Enter and getattr(self.pet, '_niri_left', False):
                from types import SimpleNamespace
                self.pet._niri_drag = False
                self.pet._niri_reanchor = True
                self.pet.mouseReleaseEvent(SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton))
                self.position()
                # 本机 niri 使用弹簧位移动画，等待其收敛后恢复绘制
                self.reveal.start(700)
                return False
            if event.type() == QEvent.Type.Hide:
                self.pet._niri_drag = False
                self.pet.cancel_pointer()
                self.surfaces.finish_pet_drag()
        return False

    def disconnected(self):
        """连接丢失时废弃旧窗口标识，避免针对已销毁窗口发送移动请求"""
        self.windows.clear()
        self.last = None
        self.cancel_move()
        self.move_timeout.stop()
        self.move_waiting = False
        self.pet.stop_walk()

    def action(self, name, **values):
        """异步发送带明确窗口标识的动作，避免阻塞 GUI 或改变其他应用"""
        channel = QLocalSocket(self)
        self.pending.add(channel)
        channel.connected.connect(lambda: channel.write((json.dumps({'Action': {name: values}}) + '\n').encode()))
        def finish():
            """收到动作回复后释放一次性连接"""
            if channel.state() == QLocalSocket.LocalSocketState.ConnectedState and not channel.canReadLine():
                return
            data = bytes(channel.readAll()).strip()
            if data:
                reply = json.loads(data)
                if 'Err' in reply:
                    print('niri action failed:', name, reply['Err'], flush=True)
            channel.abort()
            self.pending.discard(channel)
            channel.deleteLater()
        channel.readyRead.connect(finish)
        channel.errorOccurred.connect(lambda error: finish())
        channel.connectToServer(os.environ['NIRI_SOCKET'])

    def read(self):
        """布局事件只保留本进程窗口；浮动窗口坐标来自合成器而非 QWidget.pos"""
        while self.stream.canReadLine():
            previous = self.actual_position()
            if previous is not None:
                self.last = QPoint(previous)
            event = json.loads(bytes(self.stream.readLine()))
            if 'WorkspacesChanged' in event:
                self.workspaces = {w['id']: w.get('output') for w in event['WorkspacesChanged']['workspaces']}
            elif 'WindowsChanged' in event:
                self.windows = {w['id']: w for w in event['WindowsChanged']['windows'] if w.get('pid') == os.getpid()}
            elif 'WindowOpenedOrChanged' in event:
                window = event['WindowOpenedOrChanged']['window']
                if window.get('pid') == os.getpid():
                    self.windows[window['id']] = window
            elif 'WindowClosed' in event:
                self.windows.pop(event['WindowClosed']['id'], None)
            elif 'WindowLayoutsChanged' in event:
                for identifier, layout in event['WindowLayoutsChanged']['changes']:
                    if identifier in self.windows:
                        self.windows[identifier]['layout'] = layout
            self.restore_position()
            actual = self.actual_position()
            if actual is not None:
                self.last = QPoint(actual)
            if actual is not None and actual != previous:
                self.move_waiting = False
                self.move_timeout.stop()
            if actual is not None and getattr(self.pet, '_niri_reanchor', False):
                self.pet._niri_reanchor = False
                self.pet.remember_wander_home()
                self.save_timer.start()
            elif (actual is not None and actual != previous and self.restored and not self.pet.walking
                  and not getattr(self.pet, '_niri_drag', False)):
                self.save_timer.start()
            self.position()

    def position(self):
        """原布局负责所有页面锚点，表面桥接负责合成器位置提交"""
        if not getattr(self.pet, 'enhanced_ready', False) or self.pet.closing:
            return
        if hasattr(self, 'surfaces'):
            if self.restored or not self.pet.settings.get('character_visible', True):
                if self.surfaces.dragging is not self.pet.bubble:
                    self.pet.position_bubble()
            self.surfaces.sync()
            if self.surfaces.drag_bubble is not None and self.surfaces.drag_bubble.isVisible():
                self.surfaces.drag_bubble.refresh(update_frame=False)



def install(stack):
    """仅供 Linux 原生 Wayland 入口安装，Windows 类与入口保持原样"""
    from .overrides import replace
    from . import placement
    placement.install(stack)
    from . import wayland_input
    wayland_input.install(stack)
    from . import surfaces
    surfaces.install(stack)
    from desktop import DesktopPet
    from enhanced import EnhancedPet
    press = DesktopPet.mousePressEvent
    move = DesktopPet.mouseMoveEvent
    position = EnhancedPet.position_bubble
    cancel = DesktopPet.cancel_pointer
    original_pos = DesktopPet.pos
    original_move = DesktopPet.move
    original_frame = DesktopPet.frameGeometry
    original_walk = DesktopPet.start_walk
    original_stop = DesktopPet.stop_walk
    original_apply = DesktopPet.apply_settings

    def actual_pos(pet):
        """Python 业务逻辑读取合成器实际位置，初始化时保留 Qt 默认值"""
        controller = getattr(pet, '_niri_windows', None)
        actual = controller.actual_position() if controller else None
        # 交互拖动会暂时撤下布局坐标，Qt 虚拟原点不能作为顶部翻转依据
        if actual is None and controller is not None:
            actual = controller.last
        return actual if actual is not None else original_pos(pet)

    def frame_geometry(pet):
        """角色无窗口装饰，实际位置与固定画布组成屏幕矩形"""
        if not hasattr(pet, '_niri_windows'):
            return original_frame(pet)
        return QRect(actual_pos(pet), pet.size())

    def move_window(pet, *args):
        """仅 Linux 角色的程序化移动经 niri 提交，初始化仍交给 Qt"""
        controller = getattr(pet, '_niri_windows', None)
        if controller is None:
            return original_move(pet, *args)
        point = args[0] if len(args) == 1 else QPoint(*args)
        controller.request_move(point)

    def start_walk(pet):
        """实际位置不可用时不生成走动目标，避免使用 Wayland 占位坐标"""
        controller = getattr(pet, '_niri_windows', None)
        if controller is None or not controller.restored or controller.actual_position() is None:
            return
        original_walk(pet)

    def stop_walk(pet, land=False):
        """拖动或设置中断清掉排队位移，正常到达时保留最后一步"""
        controller = getattr(pet, '_niri_windows', None)
        if controller is not None and not land:
            controller.cancel_move()
        original_stop(pet, land)


    def apply_settings(pet, values, save=True):
        """缩放位移独立于走动队列，保持脚底锚点并允许锁定状态下调整尺寸"""
        controller = getattr(pet, '_niri_windows', None)
        before = QRect(pet.geometry()) if controller else None
        original_apply(pet, values, save)
        if controller and before is not None and before.size() != pet.size():
            from pet import clamp_position
            screen = controller.actual_screen()
            current = controller.actual_position()
            if screen is not None and current is not None:
                controller.cancel_move()
                target = clamp_position(QPoint(before.center().x() - pet.width() // 2,
                                                before.bottom() + 1 - pet.height()), pet.size(), screen.availableGeometry())
                delta = target - current
                controller.action('MoveFloatingWindow', id=controller.character()['id'],
                                  x={'AdjustFixed': delta.x()}, y={'AdjustFixed': delta.y()})

    def mouse_press(pet, event):
        """保存窗口内抓取点，普通单击和双击仍走原逻辑"""
        pet._niri_press = event.position().toPoint()
        press(pet, event)

    def mouse_move(pet, event):
        """超过原拖动阈值后交由 Wayland 合成器移动，禁止累计虚拟全局坐标"""
        if not hasattr(pet, '_niri_windows'):
            return move(pet, event)
        if pet.settings.get('no_move') or not pet._pointer_pressed:
            return
        if event.buttons() & Qt.MouseButton.LeftButton and (event.position().toPoint() - pet._niri_press).manhattanLength() > 8:
            if pet.windowHandle().startSystemMove():
                pet.click_timer.stop()
                pet.last_click = None
                pet.drag_samples.clear()
                pet._niri_drag = True
                pet._niri_windows.save_timer.stop()
                pet._niri_left = False
                pet._pointer_pressed = False
                pet.dragging = True
                pet.generation += 1
                pet.gate.state = 'idle'
                pet.bubble_timer.stop()
                if not pet.settings.get('panel_detached'):
                    pet.bubble.size_transition.cancel()
                    pet._niri_windows.reveal.stop()
                    pet._niri_windows.surfaces.begin_pet_drag()
                    pet._niri_windows.opacity.setOpacity(0)
                pet.play(pet.manifest.get('dragAnimation') or pet.idles[0], 'drag')
                pet.gate.state = 'drag'
                event.accept()

    def cancel_pointer(pet):
        """合成器接管鼠标不等于用户取消拖动；结束事件负责清理"""
        if not getattr(pet, '_niri_drag', False):
            cancel(pet)

    def position_bubble(pet):
        """复用原气泡目标几何，设置和聊天页共享同一定位入口"""
        controller = getattr(pet, '_niri_windows', None)
        if controller is None or not hasattr(controller, 'surfaces'):
            return position(pet)
        pet.bubble.move(pet.bubble.content_geometry().topLeft())
        report = pet.bubble.report
        if report and report.requested:
            report.sync_geometry()

    stack.enter_context(replace(DesktopPet, 'apply_settings', apply_settings))
    stack.enter_context(replace(DesktopPet, 'pos', actual_pos))
    stack.enter_context(replace(DesktopPet, 'x', lambda pet: actual_pos(pet).x()))
    stack.enter_context(replace(DesktopPet, 'y', lambda pet: actual_pos(pet).y()))
    stack.enter_context(replace(DesktopPet, 'frameGeometry', frame_geometry))
    stack.enter_context(replace(DesktopPet, 'geometry', frame_geometry))
    stack.enter_context(replace(DesktopPet, 'move', move_window))
    stack.enter_context(replace(DesktopPet, 'start_walk', start_walk))
    stack.enter_context(replace(DesktopPet, 'stop_walk', stop_walk))
    stack.enter_context(replace(DesktopPet, 'cancel_pointer', cancel_pointer))
    stack.enter_context(replace(DesktopPet, 'mousePressEvent', mouse_press))
    stack.enter_context(replace(DesktopPet, 'mouseMoveEvent', mouse_move))
    stack.enter_context(replace(EnhancedPet, 'position_bubble', position_bubble))


def attach(pet):
    """在标题设置完毕后绑定本进程原生窗口"""
    pet._niri_windows = NiriWindows(pet)
    from .wayland_input import attach
    attach(pet)
    from .surfaces import Surfaces
    pet._niri_windows.surfaces = Surfaces(pet._niri_windows)
    pet._niri_windows.surfaces.bind(pet.bubble)
    pet._niri_windows.surfaces.bind(pet.bubble.size_transition.landing)
