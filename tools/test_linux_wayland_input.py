"""验证原生 Wayland 输入区域与视觉绘制、拖动状态相互独立"""
from types import SimpleNamespace
import unittest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QWidget
from linux_app.wayland_input import input_region, InputRegion


class InputTests(unittest.TestCase):
    """输入阈值、逻辑坐标和拖动交接契约"""
    @classmethod
    def setUpClass(cls):
        """测试使用独立 Qt 应用，不连接真实账户"""
        cls.app = QApplication.instance() or QApplication([])

    def test_threshold_and_empty_frame(self):
        """逐一检查全部 alpha 和非字节对齐行，空帧不能恢复整窗输入"""
        image = QImage(257, 2, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        for alpha in range(256):
            image.setPixelColor(alpha, 0, QColor(255, 255, 255, alpha))
        before = bytes(image.constBits())
        region = input_region(image)
        for alpha in range(256):
            self.assertEqual(region.contains(QPoint(alpha, 0)), alpha >= 12)
            self.assertFalse(region.contains(QPoint(alpha, 1)))
        self.assertEqual(bytes(image.constBits()), before)
        image.fill(0)
        region = input_region(image)
        self.assertFalse(region.isEmpty())
        self.assertFalse(region.intersects(image.rect()))

    def test_input_only_drag_scaling_flip_and_restore(self):
        """窗口 mask 不裁剪 QWidget，按住时保留输入且松开后恢复人物轮廓"""
        widget = QWidget()
        widget.resize(16, 8)
        widget.show()
        image = QImage(8, 4, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setPixelColor(1, 1, QColor(255, 255, 255, 12))
        transform = QTransform()
        def draw(painter, rect):
            """模拟原人物的缩放与翻转绘制"""
            painter.setTransform(transform, True)
            painter.drawImage(rect, image)
        pet = SimpleNamespace(isVisible=widget.isVisible, windowHandle=widget.windowHandle,
            update=widget.update, rect=widget.rect, size=widget.size, width=widget.width, height=widget.height,
            frame_transform=lambda _: transform, frames=[QPixmap.fromImage(image)], index=0,
            current={}, settings={}, draw_frame=draw, _niri_drag=False, _pointer_pressed=False)
        shape = InputRegion.__new__(InputRegion)
        shape.pet, shape.last = pet, None
        try:
            shape.update()
            window = widget.windowHandle()
            self.assertTrue(window.mask().contains(QPoint(2, 2)))
            self.assertFalse(window.mask().contains(QPoint(0, 0)))
            self.assertTrue(widget.mask().isEmpty())
            pet._niri_drag = True
            shape.update()
            self.assertTrue(window.mask().contains(QPoint(0, 0)))
            pet._niri_drag = False
            shape.update()
            self.assertFalse(window.mask().contains(QPoint(0, 0)))
            transform.translate(16, 0)
            transform.scale(-1, 1)
            shape.update()
            self.assertTrue(window.mask().contains(QPoint(13, 2)))
            self.assertFalse(window.mask().contains(QPoint(2, 2)))
            pet.settings['mouse_through'] = True
            shape.update()
            self.assertFalse(window.mask().intersects(widget.rect()))
            pet.settings['mouse_through'] = False
            shape.update()
            self.assertTrue(window.mask().contains(QPoint(13, 2)))
            key = shape.last
            widget.hide()
            pet.frames = []
            shape.update()
            self.assertEqual(shape.last, key)
        finally:
            widget.close()
