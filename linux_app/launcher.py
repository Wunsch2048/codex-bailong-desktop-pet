"""持续运行的 Linux KDE/niri 入口，使用本机真实 Codex 数据"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import signal
import sys

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def arguments(argv=None, *, desktop='auto'):
    """独立解析路径，不提供演示数据或定时退出选项"""
    parser = argparse.ArgumentParser(description=__doc__)
    choices = ('auto', 'kde', 'niri') if desktop == 'auto' else (desktop,)
    parser.add_argument('--desktop', choices=choices, default=desktop, help='桌面后端；专用入口固定桌面，通用入口默认自动识别')
    parser.add_argument('--watch-codex', action='store_true', help='仅监听 Codex 桌面启动，不加载人物界面')
    parser.add_argument('--check-runtime', action='store_true', help='检查包内素材、TLS 和只读额度查询后退出')
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    parser.add_argument('--codex-cli', type=Path, help='Codex CLI；默认从 BAILONG_CODEX、PATH 或已知安装目录查找')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'codex-bailong')
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        parser.error('当前入口需要 Linux 会话')
    from .backends import select
    try:
        args.desktop, args.qt_platform = select(args.desktop)
    except ValueError as error:
        parser.error(str(error))
    if args.codex_cli is None:
        candidate = os.environ.get('BAILONG_CODEX') or shutil.which('codex') or '/usr/lib/chatgpt/resources/codex'
        args.codex_cli = Path(candidate)
    args.codex_home = args.codex_home.expanduser().resolve()
    args.codex_cli = args.codex_cli.expanduser().resolve()
    args.data_dir = args.data_dir.expanduser().resolve()
    if not args.codex_home.is_dir():
        parser.error('Codex 数据目录不存在')
    if not args.codex_cli.is_file() or not os.access(args.codex_cli, os.X_OK):
        parser.error('Codex CLI 不存在或不可执行，请指定 --codex-cli')
    if not shutil.which('bwrap'):
        parser.error('缺少 bwrap，不能安全启动只读额度查询')
    if args.data_dir == args.codex_home or args.data_dir.is_relative_to(args.codex_home):
        parser.error('桌宠数据目录不能位于 Codex 数据目录内')
    return args


def environment(args):
    """在导入原应用之前设置本进程路径，保持 Codex 配置只读且桌宠状态独立"""
    sys.path.insert(0, str(ROOT / 'app'))
    os.environ.update(QT_QPA_PLATFORM=getattr(args, 'qt_platform', 'wayland'), QT_QPA_PLATFORMTHEME='',
                      LOCALAPPDATA=str(args.data_dir), APPDATA=str(args.data_dir / 'appdata'),
                      CODEX_HOME=str(args.codex_home), BAILONG_CODEX_HOME=str(args.codex_home))
    state = args.data_dir / 'BailongEnhanced'
    state.mkdir(parents=True, exist_ok=True)
    return state


def prepare_state(state):
    """首次迁移旧设置和已校验素材，后续启动保留用户设置及素材选择"""
    from material_store import MaterialStore
    from desktop_core import atomic_json
    from .live import prepare_materials
    legacy = ROOT / 'work/linux-validation/state-live/BailongEnhanced'
    settings = state / 'settings.json'
    if not settings.exists():
        if not getattr(sys, 'frozen', False) and (legacy / 'settings.json').exists():
            values = json.loads((legacy / 'settings.json').read_text())
        else:
            values = dict(schema=2, character_visible=True, bubble=True, wandering=True,
                          random_actions=True, commentary=True, sound=False)
        atomic_json(settings, values)
    store = MaterialStore(ROOT, state)
    if store.current is None:
        if getattr(sys, 'frozen', False):
            raise RuntimeError('程序包缺少有效素材，请重新解压完整便携包或下载完整 AppImage')
        source = legacy if MaterialStore(ROOT, legacy).available('light') else ROOT / 'work/linux-validation/state/BailongEnhanced'
        try:
            prepare_materials(ROOT, source, state)
        except (OSError, ValueError) as error:
            raise RuntimeError('缺少可用素材；请先按照 docs/LINUX.md 的素材步骤准备') from error


def create_pet(stack, args):
    """装配已验证的平台适配，不启动 Windows 自启动与更新服务"""
    from . import live
    from enhanced import ResetThread
    from desktop import DesktopPet
    from . import autostart
    autostart.install(stack, args, ROOT)
    from . import codex_watch
    codex_watch.install(stack, args, ROOT)
    live.install(stack, args.codex_home, args.codex_cli)
    from . import ui
    ui.install(stack)
    if args.desktop == 'niri':
        from . import niri as windows
        windows.install(stack)
    else:
        from . import kde as windows
        windows.install(stack)
    pet = DesktopPet(monitor=False)
    # StatusNotifier 首次获取布局时必须已有完整菜单，不能依赖展开后的重建
    pet.populate_tray()
    pet._tray_shell_enabled = os.environ.get('BAILONG_ISOLATED') != '1'
    if pet._tray_shell_enabled:
        pet.tray.show()
    pet.apply_settings(dict(sound=False), save=False)
    pet.setWindowTitle('白龙桌宠 Linux')
    pet.bubble.setWindowTitle('白龙桌宠 Linux 状态')
    if args.desktop == 'kde':
        windows.attach(pet, stack)
    else:
        windows.attach(pet)
    pet.show()
    live.start(pet, args.codex_home)
    # 公告查询使用原工作线程，保留缓存、手动刷新和失败状态处理
    pet.reset_worker = ResetThread(pet)
    pet.reset_worker.ready.connect(pet.on_reset_feed)
    pet.reset_worker.failed.connect(pet.on_reset_feed_error)
    pet.reset_worker.diagnostic.connect(pet.on_reset_diagnostic)
    pet.reset_worker.busy.connect(pet._reset_busy_changed)
    pet.reset_worker.completed.connect(pet._reset_refresh_finished)
    pet.reset_worker.start()
    pet.bubble.redraw()
    pet.position_bubble()
    return pet


def main(argv=None, *, desktop='auto'):
    """持有状态目录锁并运行 Qt，退出由用户或进程信号触发"""
    args = arguments(argv, desktop=desktop)
    state = environment(args)
    if args.watch_codex:
        from .codex_watch import watch
        return watch(args, ROOT, state)
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication
    from typography import install_ui_font
    lock = QLockFile(str(state / 'desktop.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        print('该数据目录的桌宠已在运行，或无法取得目录锁', file=sys.stderr)
        return 1
    try:
        prepare_state(state)
        if args.check_runtime:
            from . import live
            from material_store import MaterialStore
            import ssl
            import quota
            store = MaterialStore(ROOT, state)
            store.verify(store.root, store.current)
            ssl.create_default_context()
            with ExitStack() as stack:
                live.install(stack, args.codex_home, args.codex_cli)
                try:
                    value = quota._read_quota_once()
                    print(json.dumps(dict(materials='verified', tls='ok', quota='ok', windows=len(quota.quota_windows(value, allow_empty=True)))))
                    return 0
                except Exception as error:
                    print(json.dumps(dict(materials='verified', tls='ok', quota='failed', error=type(error).__name__, detail=str(error))))
                    return 1
        app = QApplication(['bailong-linux'])
        app.setDesktopFileName('bailong-linux')
        app.setQuitOnLastWindowClosed(False)
        install_ui_font(app)
        with ExitStack() as stack:
            pet = create_pet(stack, args)
            # 信号处理器只设置标记，窗口关闭必须在正常 Qt 事件回调中执行
            from PySide6.QtCore import QTimer
            requested_exit = []
            exit_timer = QTimer(pet)
            exit_timer.setInterval(100)
            exit_timer.timeout.connect(lambda: pet.close() if requested_exit and not pet.closing else None)
            exit_timer.start()
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous = signal.signal(signum, lambda *_: requested_exit.append(True))
                stack.callback(signal.signal, signum, previous)
            print('白龙桌宠 Linux 已启动（' + args.desktop + '/' + app.platformName() + '）；数据目录：' + str(state), flush=True)
            try:
                return app.exec()
            finally:
                if not pet.closing:
                    pet.close()
    finally:
        lock.unlock()
