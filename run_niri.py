"""白龙桌宠 niri 入口（原生 Wayland）。"""
from linux_app import launcher


def main(argv=None):
    return launcher.main(argv, desktop='niri')


if __name__ == '__main__':
    raise SystemExit(main())
