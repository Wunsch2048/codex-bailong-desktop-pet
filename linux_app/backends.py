"""Select the compositor adapter before importing Qt."""
import os


def select(desktop='auto', env=None):
    """niri needs native Wayland; Plasma uses X11/XWayland for global placement."""
    env = os.environ if env is None else env
    if desktop == 'auto':
        names = env.get('XDG_CURRENT_DESKTOP', '').lower().split(':')
        session = env.get('DESKTOP_SESSION', '').lower()
        if 'kde' in names or 'plasma' in session:
            desktop = 'kde'
        elif env.get('NIRI_SOCKET'):
            desktop = 'niri'
        else:
            raise ValueError('未识别受支持的桌面；请指定 --desktop kde 或 --desktop niri')
    if desktop == 'niri':
        if not env.get('WAYLAND_DISPLAY') or not env.get('NIRI_SOCKET'):
            raise ValueError('niri 后端需要 WAYLAND_DISPLAY 和 NIRI_SOCKET')
        return desktop, 'wayland'
    if desktop == 'kde':
        if not env.get('DISPLAY'):
            raise ValueError('KDE 后端需要 X11/XWayland；请启用 XWayland 后重试（缺少 DISPLAY）')
        return desktop, 'xcb'
    raise ValueError('不支持的桌面后端：' + desktop)
