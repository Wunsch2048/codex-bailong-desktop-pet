"""Shared, bundled typography for compact cards and editor widgets."""
import os
import sys
from functools import lru_cache
from pathlib import Path
from PySide6.QtGui import QFont,QFontDatabase,QGuiApplication

LATIN_FAMILY='Chakra Petch'
CHINESE_FAMILY='Noto Sans SC'
FONT_FAMILIES=[LATIN_FAMILY,CHINESE_FAMILY,'Microsoft YaHei UI','Microsoft YaHei','Segoe UI','sans-serif']
if sys.platform=='darwin':
    # The bundled faces come first on every platform; only the system fallbacks differ on macOS.
    FONT_FAMILIES=[LATIN_FAMILY,CHINESE_FAMILY,'PingFang SC','Hiragino Sans GB','Helvetica Neue','sans-serif']
FONT_CSS='font-family:'+','.join('"'+name+'"' for name in FONT_FAMILIES)+';font-weight:500;'
from platform_paths import app_root
ROOT=app_root()
BUNDLED_FONTS=('ChakraPetch-Regular.ttf','ChakraPetch-Medium.ttf','ChakraPetch-SemiBold.ttf',
               'NotoSansSC-Regular.otf','NotoSansSC-Medium.otf','NotoSansSC-Bold.otf')
_font_ids=None
_font_loaded=False


def register_font():
    global _font_ids,_font_loaded
    if _font_ids is None and QGuiApplication.instance() is not None:
        _font_ids=[QFontDatabase.addApplicationFont(str(ROOT/'app/fonts'/name)) for name in BUNDLED_FONTS]
        _font_loaded=all(identity>=0 for identity in _font_ids)
        if not _font_loaded:
            # Recovery only: do not load two extra large Windows font
            # collections on every healthy startup.
            system_fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
            for name in ('msyh.ttc','msyhbd.ttc'):
                if (system_fonts/name).is_file():QFontDatabase.addApplicationFont(str(system_fonts/name))
    return _font_loaded


def ui_font(px,bold=False):
    register_font()
    return QFont(_font_template(px,bold))


@lru_cache(maxsize=128)
def _font_template(px,bold):
    value=QFont();value.setFamilies(FONT_FAMILIES);value.setPixelSize(max(11,px))
    # Small text stays at a real Medium weight. Emphasis uses size/color rather
    # than synthesized bold; prominent numerals use the bundled SemiBold face.
    value.setWeight(QFont.Weight.DemiBold if px>14 else QFont.Weight.Medium)
    value.setStyleStrategy(QFont.StyleStrategy.PreferAntialias|QFont.StyleStrategy.ForceOutline)
    value.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return value


def install_ui_font(app):
    register_font()
    app.setFont(ui_font(12))
