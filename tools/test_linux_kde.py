"""Verify input-only alpha masks without altering the rendered character."""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QWidget
from linux_app.kde import InputShape, input_bitmap, install


class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_transparent_pixels_only_affect_mouse_shape(self):
        widget = QWidget()
        widget.resize(35, 10)  # Deliberately exercise QImage's padded bitmap rows.
        widget.show()
        source = QImage(35, 10, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(Qt.GlobalColor.transparent)
        painter = QPainter(source)
        painter.fillRect(9, 3, 8, 4, Qt.GlobalColor.white)
        painter.end()
        shape = InputShape.__new__(InputShape)
        shape.display, shape.last = 1, None
        shape.x11 = Mock()
        shape.x11.XCreateBitmapFromData.return_value = 42
        shape.xext = Mock()
        pet = SimpleNamespace(isVisible=widget.isVisible, windowHandle=widget.windowHandle, rect=widget.rect,
                              winId=Mock(side_effect=AssertionError('QWidget native ID may be stale')),
                              devicePixelRatioF=lambda: 1., size=widget.size, width=widget.width, height=widget.height,
                              frame_transform=lambda rect: QTransform(), frames=[QPixmap.fromImage(source)], settings={},
                              draw_frame=lambda p, rect: p.drawImage(0, 0, source))
        try:
            shape.update(pet)
            args = shape.x11.XCreateBitmapFromData.call_args.args
            bits = args[2]
            self.assertEqual((args[3], args[4]), (35, 10))
            self.assertEqual(len(bits), 5 * 10)
            hit = lambda x, y: bool(bits[y * 5 + x // 8] & (1 << (x % 8)))
            self.assertTrue(hit(12, 4))
            self.assertFalse(hit(0, 0))
            self.assertFalse(hit(20, 4))
            shape.xext.XShapeCombineMask.assert_called_once_with(1, int(widget.winId()), 2, 0, 0, 42, 0)
            self.assertTrue(widget.mask().isEmpty())  # Visual alpha was never clipped.
            shape.update(pet)
            self.assertEqual(shape.x11.XCreateBitmapFromData.call_count, 1)
            pet.settings['mouse_through'] = True
            shape.update(pet)
            self.assertFalse(any(shape.x11.XCreateBitmapFromData.call_args.args[2]))
            # Pin/through flags can recreate QWindow while QWidget keeps an old ID.
            pet.windowHandle = lambda: SimpleNamespace(winId=lambda: 54321)
            shape.update(pet)
            self.assertEqual(shape.xext.XShapeCombineMask.call_args.args[1], 54321)
            self.assertEqual(shape.x11.XCreateBitmapFromData.call_count, 3)
        finally:
            widget.close()

    def test_kde_does_not_install_niri_geometry_or_drag_overrides(self):
        from desktop import DesktopPet
        original = (DesktopPet.move, DesktopPet.mouseMoveEvent, DesktopPet.paintEvent)
        with ExitStack() as stack:
            install(stack)
            self.assertIs(DesktopPet.move, original[0])
            self.assertIs(DesktopPet.mouseMoveEvent, original[1])
            self.assertIsNot(DesktopPet.paintEvent, original[2])
        self.assertIs(DesktopPet.paintEvent, original[2])

    def test_all_alpha_values_use_the_windows_threshold(self):
        image = QImage(257, 2, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        for alpha in range(256):
            image.setPixelColor(alpha, 0, QColor(255, 255, 255, alpha))
        before = bytes(image.constBits())
        bits = input_bitmap(image)
        stride = (image.width() + 7) // 8
        self.assertEqual(len(bits), stride * 2)
        for alpha in range(256):
            with self.subTest(alpha=alpha):
                self.assertEqual(bool(bits[alpha // 8] & (1 << (alpha % 8))), alpha >= 12)
        self.assertFalse(any(bits[stride:]))
        self.assertEqual(bytes(image.constBits()), before)

    def test_half_transparent_edges_match_hit_test_after_scaling_and_mirroring(self):
        from desktop import DesktopPet
        for ratio in (1., 1.25, 1.5, 2.):
            for mirrored in (False, True):
                with self.subTest(ratio=ratio, mirrored=mirrored):
                    widget = QWidget()
                    widget.resize(8, 2)
                    widget.show()
                    image = QImage(8, 2, QImage.Format.Format_ARGB32_Premultiplied)
                    alphas = (11, 12, 127, 128)
                    for x in range(8):
                        for y in range(2):
                            image.setPixelColor(x, y, QColor(255, 255, 255, alphas[x // 2]))
                    transform = QTransform()
                    if mirrored:
                        transform.translate(8, 0)
                        transform.scale(-1, 1)
                    def draw(painter, rect):
                        painter.setTransform(transform, True)
                        painter.drawImage(rect, image)
                    pet = SimpleNamespace(isVisible=widget.isVisible, windowHandle=widget.windowHandle,
                        devicePixelRatioF=lambda: ratio, rect=widget.rect, size=widget.size,
                        width=widget.width, height=widget.height, frames=[QPixmap.fromImage(image)],
                        settings={}, frame_transform=lambda rect: transform, draw_frame=draw,
                        current={'id': 'synthetic'}, index=0, _hit_image=image, frame_target=lambda rect: rect)
                    shape = InputShape.__new__(InputShape)
                    shape.display, shape.last = 1, None
                    shape.x11, shape.xext = Mock(), Mock()
                    shape.x11.XCreateBitmapFromData.return_value = 42
                    try:
                        shape.update(pet)
                        _, _, bits, width, height = shape.x11.XCreateBitmapFromData.call_args.args
                        self.assertEqual((width, height), (round(8 * ratio), round(2 * ratio)))
                        stride = (width + 7) // 8
                        for logical_x in (1., 3., 5., 7.):
                            px, py = int(logical_x * ratio), int(.5 * ratio)
                            point = QPointF((px + .5) / ratio, (py + .5) / ratio)
                            hit = bool(bits[py * stride + px // 8] & (1 << (px % 8)))
                            self.assertEqual(hit, DesktopPet.alpha_hit(pet, point.x(), point.y()))
                        self.assertTrue(widget.mask().isEmpty())
                    finally:
                        widget.close()
