"""原生 Wayland 的人物输入区域，不改变 QWidget 视觉裁剪"""
from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QBitmap, QImage, QPainter, QRegion, qRgb
from .input_shape import input_bitmap


def input_region(image):
    """Wayland 输入区域使用逻辑坐标，空画面以窗口外区域表示完全穿透"""
    data = input_bitmap(image)
    bitmap = QImage(data, image.width(), image.height(), (image.width() + 7) // 8,
                    QImage.Format.Format_MonoLSB)
    bitmap.setColorTable([qRgb(255, 255, 255), qRgb(0, 0, 0)])
    region = QRegion(QBitmap.fromImage(bitmap))
    # Qt 的空 mask 表示恢复整个窗口输入，窗口外矩形才能表达无命中像素
    return region if not region.isEmpty() else QRegion(-1, -1, 1, 1)


class InputRegion:
    """随绘制更新原生输入区域，同帧和隐藏状态不重复计算"""
    def __init__(self, pet):
        self.pet = pet
        self.last = None
        self.timer = QTimer(pet)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.update)

    def update(self):
        """仅操作 QWindow mask，拖动时保留松手后 Enter 的接收范围"""
        pet = self.pet
        if not pet.isVisible():
            return
        window = pet.windowHandle()
        if window is None:
            return
        held = bool(getattr(pet, '_niri_drag', False) or getattr(pet, '_pointer_pressed', False))
        transform = pet.frame_transform(QRectF(pet.rect()))
        frame = pet.frames[pet.index].cacheKey() if pet.frames else None
        current = pet.current or {}
        key = (window, int(window.winId()), frame, pet.width(), pet.height(), held,
               pet.settings.get('mouse_through'), transform.m11(), transform.m22(),
               transform.dx(), transform.dy(), current.get('renderScale'),
               tuple(current.get('renderOffset', [])))
        if key == self.last:
            return
        if held and not pet.settings.get('mouse_through'):
            region = QRegion(pet.rect())
        else:
            image = QImage(pet.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            if pet.frames and not pet.settings.get('mouse_through'):
                painter = QPainter(image)
                pet.draw_frame(painter, QRectF(pet.rect()))
                painter.end()
            region = input_region(image)
        window.setMask(region)
        self.last = key
        # 输入区域随下一次 surface commit 生效，静态画面也需提交一次
        pet.update()


def install(stack):
    """只在 niri 后端绑定绘制后的输入区域更新"""
    from .overrides import replace
    from desktop import DesktopPet
    paint = DesktopPet.paintEvent

    def paint_event(pet, event):
        """原绘制完成后合并更新，避免原生窗口重建期间操作旧句柄"""
        paint(pet, event)
        shape = getattr(pet, '_wayland_input', None)
        if shape and not shape.timer.isActive():
            shape.timer.start(0)

    stack.enter_context(replace(DesktopPet, 'paintEvent', paint_event))


def attach(pet):
    """输入区域对象随人物窗口销毁，无常驻轮询计时器"""
    pet._wayland_input = InputRegion(pet)
    pet.update()
