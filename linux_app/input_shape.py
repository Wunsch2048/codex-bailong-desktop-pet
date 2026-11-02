"""Linux 桌面共用的透明像素命中规则"""

def input_bitmap(image):
    """按 alpha >= 12 生成逐行低位优先位图，与原人物命中阈值一致"""
    from PIL import Image
    from PySide6.QtGui import QImage
    alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
    values = Image.frombytes('L', (alpha.width(), alpha.height()), bytes(alpha.constBits()),
                             'raw', 'L', alpha.bytesPerLine(), 1)
    # 查表与位打包由 Pillow 的 C 实现完成，避免 GUI 线程逐像素循环
    return values.point(_ALPHA_HIT_TABLE, '1').tobytes('raw', '1;R')


_ALPHA_HIT_TABLE = [0 if value < 12 else 255 for value in range(256)]


