"""Linux 位置持久化仅使用合成器确认的布局，不写入 Wayland 占位坐标"""
import math
from PySide6.QtCore import QPoint


def restore_target(saved, size, screens):
    """按显示器名称恢复相对位置，显示器缺失时回退首个可用屏幕"""
    if not screens or not isinstance(saved, dict):
        return None
    try:
        ratios = [float(saved[key]) for key in ('rx', 'ry')]
        if not all(math.isfinite(value) for value in ratios):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    screen = next((s for s in screens if s.name() == saved.get('screen')), screens[0])
    area = screen.availableGeometry()
    point = QPoint(round(area.x() + max(0, area.width() - size.width()) * max(0, min(1, ratios[0]))),
                   round(area.y() + max(0, area.height() - size.height()) * max(0, min(1, ratios[1]))))
    return screen, point


def install(stack):
    """替换 Linux 保存与恢复入口，其他偏好仍按原字段保存"""
    from .overrides import replace
    from desktop import DesktopPet, CONFIG
    from desktop_core import atomic_json, relative_position

    def save(pet):
        """初始化、原生拖动及恢复期间保留上一次有效位置"""
        if not pet.enhanced_ready:
            return
        pet.settings.update(wandering=pet.wandering, random_actions=pet.random_actions,
                            commentary=pet.commentary, sound=pet.sound, bubble=pet.bubble.enabled,
                            quota_visible=pet.bubble.show_quota, facing=pet.walk_direction)
        controller = getattr(pet, '_niri_windows', None)
        if controller and controller.restored and not getattr(pet, '_niri_drag', False):
            point = controller.actual_position()
            screen = controller.actual_screen()
            if point is not None and screen is not None:
                area = screen.availableGeometry()
                pet.settings['position'] = [point.x(), point.y()]
                pet.settings['screen_position'] = relative_position(point.x(), point.y(), pet.width(), pet.height(),
                    (area.x(), area.y(), area.width(), area.height()), screen.name())
        atomic_json(CONFIG, pet.settings)

    def restore(pet):
        """窗口尚未建立时不调用 QWidget.move，布局事件负责完成恢复"""
        controller = getattr(pet, '_niri_windows', None)
        if controller:
            controller.restored = False
            controller.restore_sent = None
            controller.restore_position()

    stack.enter_context(replace(DesktopPet, 'save_settings', save))
    stack.enter_context(replace(DesktopPet, 'restore_saved_position', restore))
