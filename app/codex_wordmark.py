"""Vector outlines traced from the approved Codex reference crop."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QToolButton

from theme_registry import color


def _outline():
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    # C
    path.moveTo(12.1, 4.7)
    path.cubicTo(11.5, 1.9, 9.5, 0.4, 6.65, 0.4)
    path.cubicTo(2.95, 0.4, 0.85, 3.13, 0.85, 6.84)
    path.cubicTo(0.85, 10.65, 2.98, 13.21, 6.65, 13.21)
    path.cubicTo(9.58, 13.21, 11.5, 11.56, 12.06, 9.03)
    path.lineTo(9.61, 9.03)
    path.cubicTo(9.19, 10.37, 8.14, 11.13, 6.67, 11.13)
    path.cubicTo(4.54, 11.13, 3.19, 9.48, 3.19, 6.83)
    path.cubicTo(3.19, 4.22, 4.52, 2.49, 6.66, 2.49)
    path.cubicTo(8.16, 2.49, 9.22, 3.29, 9.63, 4.7)
    path.closeSubpath()

    # o
    path.addEllipse(13.7, 3.91, 9.94, 9.29)
    path.addEllipse(16.03, 5.88, 5.27, 5.34)

    # d
    path.moveTo(31.07, 0.45)
    path.lineTo(33.34, 0.45)
    path.lineTo(33.34, 12.96)
    path.lineTo(31.07, 12.96)
    path.lineTo(31.07, 11.92)
    path.cubicTo(30.38, 12.81, 29.48, 13.21, 28.35, 13.21)
    path.cubicTo(25.88, 13.21, 24.25, 11.32, 24.25, 8.55)
    path.cubicTo(24.25, 5.78, 25.9, 3.91, 28.36, 3.91)
    path.cubicTo(29.51, 3.91, 30.41, 4.31, 31.07, 5.13)
    path.closeSubpath()
    path.addEllipse(26.54, 5.88, 4.65, 5.34)

    # e
    path.moveTo(44.22, 9.04)
    path.lineTo(37.11, 9.04)
    path.cubicTo(37.31, 10.54, 38.2, 11.3, 39.52, 11.3)
    path.cubicTo(40.59, 11.3, 41.37, 10.85, 41.77, 10.13)
    path.lineTo(44.0, 10.56)
    path.cubicTo(43.21, 12.19, 41.69, 13.21, 39.5, 13.21)
    path.cubicTo(36.64, 13.21, 34.87, 11.31, 34.87, 8.56)
    path.cubicTo(34.87, 5.79, 36.75, 3.91, 39.5, 3.91)
    path.cubicTo(42.25, 3.91, 44.22, 5.86, 44.22, 8.49)
    path.closeSubpath()
    path.moveTo(37.18, 7.34)
    path.lineTo(41.86, 7.34)
    path.cubicTo(41.56, 6.33, 40.71, 5.76, 39.51, 5.76)
    path.cubicTo(38.39, 5.76, 37.57, 6.32, 37.18, 7.34)
    path.closeSubpath()

    # x
    path.moveTo(44.68, 4.11)
    path.lineTo(47.32, 4.11)
    path.lineTo(49.14, 6.81)
    path.lineTo(50.96, 4.11)
    path.lineTo(53.0, 4.11)
    path.lineTo(50.38, 8.36)
    path.lineTo(53.0, 12.96)
    path.lineTo(50.37, 12.96)
    path.lineTo(48.92, 10.11)
    path.lineTo(46.9, 12.96)
    path.lineTo(44.5, 12.96)
    path.lineTo(47.65, 8.42)
    path.closeSubpath()
    return path


_MARK_PATH = _outline()


class CodexWordmarkButton(QToolButton):
    MARK_WIDTH = 46
    MARK_HEIGHT = 12

    def paintEvent(self, event):
        if not self.property('codexWordmark'):
            super().paintEvent(event)
            return
        tint = color('#8b78a6' if self.underMouse() else '#75618d')
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(0, (self.height() - self.MARK_HEIGHT) / 2)
        scale = self.MARK_HEIGHT / 14  # Preserve the reference crop's proportions.
        painter.scale(scale, scale)
        painter.fillPath(_MARK_PATH, QColor(tint))
        painter.end()
