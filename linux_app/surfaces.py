"""将原面板的逻辑几何映射到 niri 原生窗口，保留原布局及绘制"""
import time

from PySide6.QtCore import QObject, QPoint, QRect, QEvent, QTimer, Qt
from PySide6.QtGui import QRegion, QPainter
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsOpacityEffect


class DragBubble(QWidget):
    """拖动期间以角色为父表面显示原气泡，原生位置随父表面连续更新"""
    def __init__(self, manager):
        flags = Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
        super().__init__(manager.pet, flags)
        self.manager = manager
        self.image = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)

    def refresh(self, update_frame=True):
        """沿用原布局和绘制；移动由父表面完成，内容刷新只在拖动交接期间运行"""
        pet = self.manager.pet
        bubble = pet.bubble
        if pet.closing or not pet.isVisible() or not bubble.isVisible() or pet.settings.get('panel_detached'):
            self.stop()
            return
        from surface_morph import complete_frame
        if update_frame:
            self.image = complete_frame(bubble)
        # 拖动中的附着编辑页使用角色锚点和原边缘翻转规则，不继承入口留下的屏幕位置
        positioned = bubble._editor_positioned
        bubble._editor_positioned = False
        try:
            target = bubble.content_geometry()
        finally:
            bubble._editor_positioned = positioned
        if bubble.panel_page != 'status':
            bubble.move(target.topLeft())
        point = QWidget.mapToGlobal(pet, QPoint()) + target.topLeft() - pet.pos()
        self.setGeometry(QRect(point, target.size()))
        self.update()

    def start(self):
        """先提交原气泡画面，再隐藏真实窗口；create 不提升兄弟控件为原生窗口"""
        self.refresh()
        self.create()
        self.windowHandle().setTransientParent(self.manager.pet.windowHandle())
        self.windowHandle().setMask(QRegion(-1, -1, 1, 1))
        self.show()
        self.repaint()
        self.timer.start()

    def stop(self):
        """交接结束或角色隐藏时释放画布和刷新时钟"""
        self.timer.stop()
        self.hide()
        self.image = None
        self.destroy()

    def paintEvent(self, event):
        """透明像素保持透明，不给气泡增加背景或阴影"""
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        if self.image is not None:
            painter.drawPixmap(0, 0, self.image)


class Surfaces(QObject):
    """只管理本进程登记的气泡、日报及过渡画布"""
    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.pet = controller.pet
        self.entries = {}
        self.dragging = None
        self.left = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sync)
        self.serial = 0
        self.drag_bubble = None

    def begin_pet_drag(self):
        """仅附着且可见的气泡参与角色拖动，分离卡片保持独立"""
        if self.pet.isVisible() and self.pet.bubble.isVisible() and not self.pet.settings.get('panel_detached'):
            if self.drag_bubble is None:
                self.drag_bubble = DragBubble(self)
            self.drag_bubble.start()

    def finish_pet_drag(self):
        """真实窗口定位完成后撤销拖动画布"""
        if self.drag_bubble is not None:
            self.drag_bubble.stop()

    def bind(self, widget):
        """赋予独立原生窗口唯一标题，子控件不进入合成器定位流程"""
        if not widget.isWindow():
            return
        if widget in self.entries:
            return
        self.serial += 1
        widget.setWindowTitle('白龙 Linux 面板 ' + str(self.serial))
        widget._linux_surfaces = self
        self.entries[widget] = dict(point=QWidget.pos(widget), waiting=None, workspace=None, sent_at=0.)
        widget.installEventFilter(self)
        widget.destroyed.connect(lambda: self.entries.pop(widget, None))

    def window(self, widget):
        """只从 niri 控制器已过滤的本进程窗口中匹配标题"""
        return next((w for w in self.controller.windows.values() if w.get('title') == widget.windowTitle()), None)

    def actual(self, widget):
        """原生拖动读取合成器真实位置，不能累计 Qt 虚拟全局坐标"""
        window = self.window(widget)
        if not window:
            return None
        output = self.controller.workspaces.get(window.get('workspace_id'))
        screen = next((s for s in QApplication.screens() if s.name() == output), None)
        xy = window['layout'].get('tile_pos_in_workspace_view')
        if screen is None or xy is None:
            return None
        offset = window['layout']['window_offset_in_tile']
        return QPoint(round(xy[0] + offset[0]), round(xy[1] + offset[1])) + screen.geometry().topLeft()

    def move(self, widget, point):
        """同步保存布局目标，异步窗口确认不得改变正在计算的动画坐标系"""
        self.bind(widget)
        entry = self.entries[widget]
        entry['point'] = QPoint(point)
        if not self.timer.isActive():
            self.timer.start(0)

    def sync(self):
        """工作区切换和位移分别等待确认，避免重复累计相对增量"""
        if self.pet.closing:
            return
        transition = self.pet.bubble.size_transition
        stage = getattr(transition, '_linux_stage', None)
        parent = getattr(transition.landing, '_linux_popup_parent', None)
        if parent is not None and stage in ('preparing', 'playing', 'landing'):
            point = parent.pos()
            delta = point - transition._linux_parent_origin
            transition._linux_parent_origin = QPoint(point)
            # 手动拖动已有共享收纳控制器平移画布；其余移动也必须在交接前更新同一目标
            if not getattr(getattr(self.pet, 'drag_panel', None), 'active', False) and not delta.isNull():
                if transition.running:
                    transition.translate(delta)
                else:
                    transition.bubble.move(transition.bubble.pos() + delta)
                    transition.landing.move(transition.landing.pos() + delta)
        for widget, entry in tuple(self.entries.items()):
            if (widget is self.dragging or not widget.isVisible()
                    or getattr(widget, '_linux_popup_parent', None) is not None):
                continue
            window = self.window(widget)
            current = self.actual(widget)
            if not window or current is None:
                continue
            target = entry['point']
            screen = QApplication.screenAt(QRect(target, widget.size()).center()) or QApplication.primaryScreen()
            output = self.controller.workspaces.get(window.get('workspace_id'))
            if output != screen.name():
                key = ('monitor', screen.name())
                if entry['workspace'] != key:
                    entry['workspace'] = key
                    self.controller.action('MoveWindowToMonitor', id=window['id'], output=screen.name())
                continue
            # 附着面板与角色保持同一工作区，分离面板保留自己的工作区
            character = self.controller.character()
            detached = self.pet.settings.get('panel_detached') or not self.pet.settings.get('character_visible', True)
            if not detached and character and self.controller.workspaces.get(character.get('workspace_id')) == output and window.get('workspace_id') != character.get('workspace_id'):
                key = ('workspace', character['workspace_id'])
                if entry['workspace'] != key:
                    entry['workspace'] = key
                    self.controller.action('MoveWindowToWorkspace', window_id=window['id'], reference={'Id': character['workspace_id']}, focus=False)
                continue
            entry['workspace'] = None
            waiting = entry['waiting']
            if waiting is not None:
                if (current - waiting).manhattanLength() > 1 and time.monotonic() - entry['sent_at'] < 1.5:
                    self.timer.start(1500)
                    continue
                entry['waiting'] = None
            delta = target - current
            if delta.manhattanLength() <= 1:
                continue
            entry['waiting'] = QPoint(target)
            entry['sent_at'] = time.monotonic()
            self.timer.start(1500)
            self.controller.action('MoveFloatingWindow', id=window['id'], x={'AdjustFixed': delta.x()}, y={'AdjustFixed': delta.y()})

    def eventFilter(self, widget, event):
        """原生移动以离开后重新进入结束，Qt 模拟松手不结束拖动"""
        if self.dragging is widget:
            if event.type() == QEvent.Type.Leave:
                self.left = True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                return True
            elif event.type() == QEvent.Type.Enter and self.left:
                point = self.actual(widget)
                self.dragging = None
                widget._card_press = None
                widget._card_dragged = False
                if point is not None:
                    self.entries[widget]['point'] = point
                    self.pet.remember_card_anchor(QRect(point, widget.size()))
                    self.pet.position_bubble()
                    self.pet.save_settings()
                    if widget.report and widget.report.requested:
                        widget.report.sync_geometry()
            elif event.type() == QEvent.Type.Hide:
                self.dragging = None
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            if widget.windowFlags() & Qt.WindowType.WindowTransparentForInput and widget.windowHandle():
                # Qt 的透明输入标志不能替代 Wayland 输入区域，空 mask 又会恢复整窗命中
                widget.windowHandle().setMask(QRegion(-1, -1, 1, 1))
                widget.update()
            self.entries[widget]['waiting'] = None
            if not self.timer.isActive():
                self.timer.start(0)
        return False


def install(stack):
    """限定原生面板和提示的几何入口，子控件和 Windows 实现不受影响"""
    from .overrides import replace
    from compact_bubble import CompactBubble
    from daily_report import DailyReport
    from panel_transition import NativeLanding, PanelTransition, TransitionCover
    from hover_hints import HintBubble

    def bridge(widget):
        """沿父对象找到已绑定气泡，兼容延迟创建的日报与过渡画布"""
        current = widget
        while current is not None:
            value = getattr(current, '_linux_surfaces', None)
            if value:
                value.bind(widget)
                return value
            current = current.parentWidget()
        return None

    def pos(widget):
        """向布局返回已提交目标，原生拖动期间返回实际坐标"""
        manager = bridge(widget)
        if manager:
            actual = manager.actual(widget) if manager.dragging is widget else None
            return actual if actual is not None else QPoint(manager.entries[widget]['point'])
        return QWidget.pos(widget)

    def geometry(widget):
        """逻辑原点与 Qt 实际画布尺寸组成布局矩形"""
        return QRect(pos(widget), widget.size())

    def move(widget, *args):
        """程序化定位交给合成器，窗口尺寸仍由原 Qt 布局管理"""
        manager = bridge(widget)
        if not manager:
            return QWidget.move(widget, *args)
        manager.move(widget, args[0] if len(args) == 1 else QPoint(*args))

    def set_geometry(widget, *args):
        """先登记新原点再调整画布，resizeEvent 始终看到一致的逻辑几何"""
        manager = bridge(widget)
        if not manager:
            return QWidget.setGeometry(widget, *args)
        rect = QRect(args[0]) if len(args) == 1 else QRect(*args)
        if isinstance(widget, CompactBubble) and getattr(widget.size_transition, "_linux_stage", None) == "building":
            return
        manager.move(widget, rect.topLeft())
        parent = getattr(widget, '_linux_popup_parent', None)
        if parent is not None:
            # xdg_popup 的锚点属于父表面，Qt 全局坐标与 niri 布局原点并不一致
            local = QWidget.mapToGlobal(parent, QPoint()) + rect.topLeft() - parent.pos()
            QWidget.setGeometry(widget, QRect(local, rect.size()))
        else:
            QWidget.resize(widget, rect.size())

    def screen(widget):
        """跨屏动画的边界计算使用目标屏幕，不依赖滞后的 Qt 屏幕信号"""
        if bridge(widget):
            return QApplication.screenAt(geometry(widget).center()) or QApplication.primaryScreen()
        return QWidget.screen(widget)

    for cls in (CompactBubble, DailyReport, NativeLanding, HintBubble):
        for name, method in dict(pos=pos, x=lambda w: pos(w).x(), y=lambda w: pos(w).y(), geometry=geometry,
                                 frameGeometry=geometry, move=move, setGeometry=set_geometry, screen=screen).items():
            stack.enter_context(replace(cls, name, method))

    present = HintBubble.present

    def present_hint(widget, title, subtitle, anchor, screen, *, card_top=None, topmost=True, owner=None):
        """穿透提示作为附着 popup 定位，按钮间切换无需等待浮动窗口移动确认"""
        manager = bridge(owner) if owner is not None else None
        if manager:
            manager.bind(widget)
            if widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                if getattr(widget, '_linux_popup_parent', None) is not owner:
                    # popup 的父表面在创建时确定，日报开关导致换宿主时需重新映射
                    widget.hide()
                    widget.destroy()
                    widget._linux_popup_parent = owner
                if widget.windowType() != Qt.WindowType.ToolTip:
                    widget.setWindowFlags((widget.windowFlags() & ~Qt.WindowType.WindowType_Mask) | Qt.WindowType.ToolTip)
            bubble = manager.pet.bubble
            delta = bubble.pos() - QWidget.mapToGlobal(bubble, QPoint())
            anchor = anchor.translated(delta)
            if card_top is not None:
                card_top += delta.y()
            screen = bubble.screen()
        return present(widget, title, subtitle, anchor, screen, card_top=card_top, topmost=topmost, owner=owner)

    stack.enter_context(replace(HintBubble, 'present', present_hint))

    begin = PanelTransition.begin
    commit = PanelTransition.commit
    finish = PanelTransition.finish
    cancel = PanelTransition.cancel
    release_landing = PanelTransition.release_landing
    prepare_surface = NativeLanding.prepare
    present_surface = NativeLanding.present
    paint_surface = NativeLanding.paintEvent
    paint_cover = TransitionCover.paintEvent
    advance = PanelTransition.advance
    release_surface = NativeLanding.release

    def prepare_card_surface(widget, rect):
        """构建目标布局时保留原窗口，临时画布稍后只定位一次"""
        transition = widget.parentWidget().size_transition
        if getattr(transition, '_linux_stage', None) == 'building':
            return
        parent = getattr(widget, '_linux_popup_parent', None)
        kind = Qt.WindowType.ToolTip if parent is not None else Qt.WindowType.Tool
        flags = (widget.windowFlags() & ~Qt.WindowType.WindowType_Mask) | kind
        flags = (flags & ~Qt.WindowType.WindowStaysOnTopHint) | (transition.bubble.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if widget.windowFlags() != flags:
            widget.setWindowFlags(flags)
        if parent is not None:
            parent.winId()
            # winId 会强制兄弟控件原生化，内容和遮罩必须留在气泡的绘制树内
            widget.create()
            widget.windowHandle().setTransientParent(parent.windowHandle())
        prepare_surface(widget, rect)

    def release_card_surface(widget):
        """popup 隐藏后释放原生 backing store，避免多轮重映射保留帧缓冲"""
        release_surface(widget)
        if getattr(widget, '_linux_popup_parent', None) is not None:
            widget.destroy()

    def present_card_surface(widget, image, rect):
        """末帧留在固定画布内，不让可见交接窗口再做原生移动"""
        transition = widget.parentWidget().size_transition
        if getattr(transition, '_linux_stage', None) != 'landing':
            present_surface(widget, image, rect)

    def paint_card_surface(widget, event):
        """复用上游形变绘制，交接期间只有这一张画布呈现动画"""
        transition = widget.parentWidget().size_transition
        stage = getattr(transition, '_linux_stage', None)
        if stage not in ('preparing', 'playing', 'landing'):
            return paint_surface(widget, event)
        painter = QPainter(widget)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(widget.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        parent = getattr(widget, '_linux_popup_parent', None)
        if parent is not None:
            # 合成器可把 popup 推回屏幕内，绘制原点仍需与原动画的全局画布一致
            native_origin = QWidget.mapToGlobal(widget, QPoint()) - QWidget.mapToGlobal(parent, QPoint()) + parent.pos()
            painter.translate(widget.pos() - native_origin)
        if stage == 'playing':
            transition.paint_morph(painter)
        elif stage == 'landing':
            painter.drawPixmap(transition._linux_frame_offset, widget.image)

    def paint_source_cover(widget, event):
        """等待临时画布定位时，原窗口保持原截图和原尺寸"""
        transition = widget.parentWidget().size_transition
        if getattr(transition, '_linux_stage', None) != 'preparing':
            return paint_cover(widget, event)
        painter = QPainter(widget)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(widget.rect(), Qt.GlobalColor.transparent)
        painter.drawPixmap(0, 0, transition.before)

    def begin_transition(transition):
        """拖动交接中从控件内容取起始帧，避开主窗口用于隐藏的透明度"""
        bubble = transition.bubble
        manager = bridge(bubble)
        frame = None
        if manager and bubble.isVisible() and manager.controller.opacity.opacity() == 0:
            from surface_morph import complete_frame
            frame = complete_frame(bubble)
        begin(transition)
        if frame is not None:
            transition.before = frame
            transition.old_surface.frame = frame
            transition.cover.image = frame

    def commit_transition(transition, preserve_reveals=False):
        """先构建原形变，再定位空画布，避免两张胶囊分别移动"""
        manager = bridge(transition.bubble)
        if not manager:
            return commit(transition, preserve_reveals=preserve_reveals)
        transition._linux_stage = 'building'
        commit(transition, preserve_reveals=preserve_reveals)
        if not (transition.running and transition.canvas_morph and not transition.closing):
            transition._linux_stage = None
            return
        transition.animation.pause()
        transition._linux_stage = 'preparing'
        transition.cover.setGeometry(transition.bubble.rect())
        transition.cover.repaint()
        pet = manager.pet
        parent = pet if pet.isVisible() and pet.screen() == transition.bubble.screen() else None
        transition._linux_parent_origin = QPoint(pet.pos()) if parent is not None else None
        transition.landing._linux_popup_parent = parent
        transition.landing.prepare(transition.canvas_rect)
        transition.landing_timer.start(0 if parent is not None else 700)

    def advance_transition(transition, value):
        """沿用原动画时钟和日报联动，只把绘制送到固定交接画布"""
        advance(transition, value)
        if getattr(transition, '_linux_stage', None) == 'playing':
            transition.landing.update()

    def finish_transition(transition):
        """原窗口在不可见期间落到目标，临时画布原地保留末帧"""
        stage = getattr(transition, '_linux_stage', None)
        if stage not in ('preparing', 'playing') or not transition.morph:
            return finish(transition)
        if stage == 'preparing':
            release_transition(transition)
        transition._linux_stage = 'landing'
        transition._linux_frame_offset = transition.target_rect.topLeft() - transition.canvas_rect.topLeft()
        transition.landing.image = transition.morph.end.frame
        transition.landing.repaint()
        finish(transition)
        transition.landing_timer.start(0 if getattr(transition.landing, '_linux_popup_parent', None) is not None else 700)

    def release_transition(transition):
        """准备完成时交给单一动画画布，收尾时恢复真实控件并撤销临时窗口"""
        stage = getattr(transition, '_linux_stage', None)
        manager = bridge(transition.bubble)
        if stage == 'preparing':
            transition.landing_timer.stop()
            popup = getattr(transition.landing, '_linux_popup_parent', None) is not None
            handle = transition.landing.windowHandle()
            if popup and not handle.isExposed() and transition.animation.state() == transition.animation.State.Paused:
                transition.landing_timer.start(8)
                return
            actual = manager.actual(transition.landing)
            if (transition.animation.state() == transition.animation.State.Paused and actual is not None
                    and (actual - transition.canvas_rect.topLeft()).manhattanLength() > 1):
                transition.landing_timer.start(100)
                return
            transition._linux_stage = 'playing'
            manager.controller.reveal.stop()
            manager.finish_pet_drag()
            # 接过拖动或启动的交接后，落地应显示面板，不能恢复上一阶段隐藏时的透明度
            transition._linux_handoff_opacity = 1.
            manager.controller.opacity.setOpacity(0)
            transition.landing.image = transition.before
            transition.landing.repaint()
            if popup:
                # 目标窗口在原动画播放期间完成原生定位，收尾不串行等待第二段移动
                transition.bubble.setGeometry(transition.target_rect)
                manager.sync()
            if transition.animation.state() == transition.animation.State.Paused:
                transition.animation.resume()
            return
        transition._linux_stage = None
        opacity = getattr(transition, '_linux_handoff_opacity', None)
        if opacity is not None:
            transition._linux_handoff_opacity = None
            if not getattr(manager.pet, '_niri_drag', False):
                manager.controller.opacity.setOpacity(opacity)
        release_landing(transition)
        if manager and getattr(manager.pet, '_niri_drag', False) and not transition.running:
            manager.begin_pet_drag()
            manager.controller.opacity.setOpacity(0)

    def cancel_transition(transition):
        """关闭或快速导航时同步结束交接，不遗留透明控件及额外窗口"""
        cancel(transition)
        release_transition(transition)

    stack.enter_context(replace(NativeLanding, 'release', release_card_surface))
    stack.enter_context(replace(NativeLanding, 'prepare', prepare_card_surface))
    stack.enter_context(replace(NativeLanding, 'present', present_card_surface))
    stack.enter_context(replace(NativeLanding, 'paintEvent', paint_card_surface))
    stack.enter_context(replace(TransitionCover, 'paintEvent', paint_source_cover))
    stack.enter_context(replace(PanelTransition, 'begin', begin_transition))
    stack.enter_context(replace(PanelTransition, 'advance', advance_transition))
    stack.enter_context(replace(PanelTransition, 'commit', commit_transition))
    stack.enter_context(replace(PanelTransition, 'finish', finish_transition))
    stack.enter_context(replace(PanelTransition, 'release_landing', release_transition))
    stack.enter_context(replace(PanelTransition, 'cancel', cancel_transition))

    press = CompactBubble.card_pointer_press
    release = CompactBubble.card_pointer_release

    def pointer_press(bubble, event):
        """保留可拖动区域判定，仅使用窗口内坐标判断阈值"""
        result = press(bubble, event)
        if result:
            bubble._linux_card_press = event.position().toPoint()
        return result

    def pointer_move(bubble, event):
        """分离面板交给 Wayland 原生移动，避免全局坐标反馈"""
        manager = bridge(bubble)
        if not manager or not bubble._card_press or not event.buttons() & Qt.MouseButton.LeftButton:
            return False
        if manager.dragging is bubble:
            return True
        if (event.position().toPoint() - bubble._linux_card_press).manhattanLength() <= 5:
            return False
        manager.dragging = bubble
        manager.left = False
        if bubble.windowHandle().startSystemMove():
            manager.entries[bubble]['waiting'] = None
            bubble._card_dragged = True
            return True
        manager.dragging = None
        return False

    def pointer_release(bubble):
        """合成器接管后不把模拟松手误认成用户释放"""
        manager = bridge(bubble)
        if manager and manager.dragging is bubble:
            return True
        return release(bubble)

    stack.enter_context(replace(CompactBubble, 'card_pointer_press', pointer_press))
    stack.enter_context(replace(CompactBubble, 'card_pointer_move', pointer_move))
    stack.enter_context(replace(CompactBubble, 'card_pointer_release', pointer_release))

    def set_opacity(widget, opacity):
        """Wayland 用绘制透明度隐藏日报，保持动画交接时原生窗口存在"""
        if not hasattr(widget, '_linux_opacity'):
            widget._linux_opacity = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(widget._linux_opacity)
        widget._linux_opacity.setOpacity(opacity)

    def opacity(widget):
        """向原联动动画返回同一绘制透明度，保持取消与恢复语义"""
        return widget._linux_opacity.opacity() if hasattr(widget, '_linux_opacity') else 1.

    stack.enter_context(replace(DailyReport, 'setWindowOpacity', set_opacity))
    stack.enter_context(replace(DailyReport, 'windowOpacity', opacity))
