"""白龙桌宠 KDE Plasma 入口（X11/XWayland）。"""
from linux_app import launcher


def main(argv=None):
    return launcher.main(argv, desktop='kde')


if __name__ == '__main__':
    raise SystemExit(main())
