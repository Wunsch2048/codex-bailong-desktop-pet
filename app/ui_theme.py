"""Low-chroma plum, porcelain and balanced cool/warm companion accents."""
SURFACE='#fcfafc'
INK='#393343'
MUTED='#706879'
ACCENT='#8b78a6'
QUOTA_WEEK='#7181a3'
QUOTA_FIVE='#76618f'
QUOTA_LOW='#98566d'
TRACK='#e4dfea'
PANEL='#f5f2f7'
BORDER='#ded2e7'
PRIMARY='#75618d'
PRIMARY_PRESSED='#5f4c77'
ON_PRIMARY='#ffffff'
SELECTED='#e8dff0'
DANGER='#89566c'
DANGER_SURFACE='#f3eaf0'
DISABLED='#8b8195'
HEALTH_COLORS={'available':'#506e66','degraded':'#885c70','unavailable':'#89566c','unknown':'#706879'}
ISLAND='#302a3c'
ON_ISLAND='#f7f3fb'
ISLAND_ICON='#d6c5ed'
# Tray-only high-contrast accents (Radix dark mauve / iris / blue / ruby).
TRAY_TRACK='#3c393f'
TRAY_FIVE='#b1a9ff'
TRAY_WEEK='#70b8ff'
TRAY_LOW='#ff949d'
MODEL_COLORS=['#8b78a6','#8297a5','#aa8194','#a19170','#7d9c94','#a89ab6']

def hide_scrollbars(area):
    """Keep wheel scrolling and caret navigation without visible scrollbars."""
    from PySide6.QtCore import Qt
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area

def editor_stylesheet(font_css):
    return ('QWidget{'+font_css+f'font-size:12px;color:{INK};}}'
        f'QLabel,QCheckBox,QRadioButton,QGroupBox{{color:{INK};}}'
        f'QLineEdit,QPlainTextEdit,QComboBox,QAbstractSpinBox{{color:{INK};background:{SURFACE};border:2px solid {BORDER};border-radius:6px;padding:5px;selection-color:{INK};selection-background-color:{SELECTED};}}'
        f'QComboBox QAbstractItemView{{color:{INK};background:{SURFACE};selection-color:{INK};selection-background-color:{SELECTED};}}'
        f'QPushButton{{color:{INK};background:{SURFACE};border:0;border-radius:7px;padding:6px 9px;min-height:16px;}}'
        f'QPushButton:hover{{background:{PANEL};border-color:{ACCENT};}}'
        f'QPushButton:pressed{{background:{SELECTED};}}'
        f'QPushButton[role="primary"]{{color:{ON_PRIMARY};background:{PRIMARY};border-color:{PRIMARY};font-weight:500;}}'
        f'QPushButton[role="primary"]:hover{{background:{PRIMARY_PRESSED};}}'
        f'QPushButton[role="primary"]:pressed{{background:{PRIMARY_PRESSED};border-color:{INK};}}'
        f'QPushButton[role="danger"]{{color:{DANGER};background:{DANGER_SURFACE};border-color:#d3b8c7;}}'
        f'QPushButton[role="danger"]:hover{{background:#ead6e1;border-color:{DANGER};}}'
        f'QPushButton:disabled{{color:{DISABLED};background:#efebf2;border-color:#e6dfec;}}'
        f'QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus,QAbstractSpinBox:focus{{border:2px solid {ACCENT};}}'
        f'QPushButton:focus,QToolButton:focus{{border:0;outline:0;background:{SELECTED};}}QPushButton[role="primary"]:focus{{background:{PRIMARY_PRESSED};}}'
        'QCheckBox{border:0;padding:2px 1px;}'
        f'QCheckBox:focus{{border:0;background:{PANEL};border-radius:3px;}}'
        f'QPushButton:checked{{background:{SELECTED};border-color:{PRIMARY};}}'
        'QTabWidget::pane{border:0;}'
        f'QTabBar::tab{{color:{MUTED};padding:7px 10px;background:transparent;border:0;}}'
        f'QTabBar::tab:selected{{background:{SELECTED};color:{PRIMARY_PRESSED};border:0;border-radius:5px;}}'
        f'QTabBar::tab:focus{{border:0;}}'
        'QScrollArea{border:0;}')

def contrast(a,b):
    def luminance(color):
        v=[int(color[i:i+2],16)/255 for i in (1,3,5)]
        v=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in v]
        return sum(x*y for x,y in zip(v,(.2126,.7152,.0722)))
    x,y=sorted((luminance(a),luminance(b)))
    return (y+.05)/(x+.05)
