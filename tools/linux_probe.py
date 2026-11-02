"""隔离验证 Linux IPC 与原始 Qt 界面，不改变生产入口"""
import argparse
import json
import os
from pathlib import Path
import select
import socket
import stat
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
WORK = ROOT / 'work/linux-validation'


def emit(value):
    """仅输出调用者明确选择的诊断字段"""
    print(json.dumps(value, ensure_ascii=False), flush=True)


def ipc(args):
    """用 Unix socket 驱动原状态解析器，仅记录状态而不记录会话正文"""
    from codex_live_status import LiveStatusReader, valid_id
    target = valid_id(args.thread or os.environ.get('CODEX_THREAD_ID'))
    if not target:
        raise ValueError('请通过 --thread 指定测试会话 UUID')
    endpoint = Path(args.socket).expanduser()
    info = endpoint.stat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('IPC 必须是当前用户拥有的 Unix socket')
    records = []
    for cycle in range(args.cycles):
        stop = threading.Event()
        started = time.monotonic()
        def record(kind, *values):
            """忽略会话及回合标识，只保留投影后的状态值"""
            row = dict(cycle=cycle + 1, seconds=round(time.monotonic()-started, 3), event=kind, value=values[1], cleanup=stop.is_set())
            records.append(row)
            emit(row)
        reader = LiveStatusReader(stop, lambda *v: record('compaction', *v),
            lambda *v: record('waiting', *v), lambda *v: record('activity', *v),
            lambda *v: record('terminal', *v))
        reader.set_targets([target])
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(endpoint))
            class Transport:
                """保留原解析器的 read/write 契约"""
                def read(self, count):
                    data = connection.recv(count)
                    if not data:
                        raise OSError('IPC disconnected')
                    return data
                def write(self, data):
                    return connection.send(data)
            timer = threading.Timer(args.seconds, stop.set)
            timer.start()
            try:
                reader._listen(Transport(), lambda: 65536 if select.select([connection], [], [], 0)[0] else 0)
            finally:
                stop.set()
                timer.cancel()
            emit(dict(cycle=cycle + 1, health=reader.health_snapshot()))
            records.append(dict(cycle=cycle + 1, health=reader.health_snapshot()))
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'ipc-result.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
    return 0 if all(r['health']['code'] == 'ipc_ready' for r in records if 'health' in r) else 1


def environment(codex_home=None):
    """桌宠状态保持隔离，可显式选择只读的真实 Codex 数据源"""
    WORK.mkdir(parents=True, exist_ok=True)
    for name, folder in [('LOCALAPPDATA', 'state'), ('APPDATA', 'appdata'), ('CODEX_HOME', 'empty-codex')]:
        target = WORK / (folder + ('-live' if codex_home is not None and name != 'CODEX_HOME' else ''))
        target.mkdir(exist_ok=True)
        os.environ[name] = str(target)
    if codex_home is not None:
        os.environ['CODEX_HOME'] = str(codex_home)
        os.environ['BAILONG_CODEX_HOME'] = str(codex_home)
    else:
        os.environ.pop('BAILONG_CODEX_HOME', None)
    return WORK / ('state-live' if codex_home is not None else 'state') / 'BailongEnhanced'


def materials(args):
    """仅提取清单允许的原始素材，每个文件均按仓库 SHA-256 验证"""
    import zipfile
    from material_store import MaterialStore, checked
    state = environment()
    store = MaterialStore(ROOT, state)
    target = store.tier_root('light')
    if target.exists():
        store.verify(target, 'light')
    else:
        with zipfile.ZipFile(args.archive) as archive:
            for item in store.catalog['tiers']['light']['files']:
                dst = checked(target, item['path'])
                data = archive.read(item['path'])
                import hashlib
                if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError('素材校验失败：' + item['path'])
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
        store.verify(target, 'light')
    store._receipt(target, 'light')
    store.activate('light', target)
    emit(dict(verified=True, tier='light', files=len(store.catalog['tiers']['light']['files'])))
    return 0


def gui(args):
    """运行原始人物和气泡，后台服务隔离，仅探测窗口几何及原面板"""
    source = Path(args.codex_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()
    if args.live and not source.is_dir():
        raise ValueError('Codex 数据目录不存在')
    state = environment(source if args.live else None)
    # 仅本进程绕开 GTK 3 主题桥接，继续使用原来的 Fusion 和项目样式
    os.environ['QT_QPA_PLATFORMTHEME'] = ''
    state.mkdir(parents=True, exist_ok=True)
    if args.live:
        from linux_app.live import prepare_materials
        prepare_materials(ROOT, WORK / 'state/BailongEnhanced', state)
    if not args.live or not (state / 'settings.json').exists():
        (state / 'settings.json').write_text(json.dumps(dict(schema=2, character_visible=True, bubble=True, wandering=False, random_actions=False, commentary=False, sound=False, position=[1300, 700])))
    os.environ['QT_QPA_PLATFORM'] = args.backend
    from contextlib import ExitStack
    from PySide6.QtCore import QTimer, QPoint
    from PySide6.QtWidgets import QApplication
    from typography import install_ui_font, register_font
    from desktop import DesktopPet
    from enhanced import EnhancedPet
    app = QApplication(['bailong-linux-probe'])
    app.setDesktopFileName('bailong-linux-probe')
    app.setQuitOnLastWindowClosed(False)
    install_ui_font(app)
    results = dict(backend=app.platformName(), fonts_loaded=register_font(), samples=[], errors=[])
    def exception(kind, value, traceback):
        """Qt 回调异常必须记录为验证失败"""
        results['errors'].append(str(value))
        sys.__excepthook__(kind, value, traceback)
    sys.excepthook = exception
    destination = WORK / (args.backend + ('-niri' if args.niri else '') + ('-live' if args.live else ''))
    destination.mkdir(exist_ok=True)
    with ExitStack() as stack:
        # 仅禁用验证进程的外部副作用，不替换任何绘制、布局或移动函数
        for name in (('refresh_reset_feed',) if args.live else ('refresh_quota', 'refresh_reset_feed', 'refresh_tokens', 'refresh_all')):
            stack.enter_context(patch.object(EnhancedPet, name, lambda *a, **k: None))
        stack.enter_context(patch('desktop_settings.autostart_enabled', return_value=False))
        stack.enter_context(patch('codex_startup.enabled', return_value=False))
        if args.live:
            from linux_app.live import install
            executable = Path(args.codex_cli).expanduser().resolve()
            if not executable.is_file():
                raise ValueError('Codex CLI 不存在')
            install(stack, source, executable)
        if args.niri:
            from linux_app.niri import install as install_niri
            install_niri(stack)
        pet = DesktopPet(monitor=False)
        if pet.material_store.current is None:
            pet.close()
            raise RuntimeError('缺少已校验素材，请先运行 materials 子命令')
        pet.apply_settings(dict(wandering=False, random_actions=False, commentary=False, sound=False), save=False)
        pet.setWindowTitle('Bailong Linux Probe - Pet')
        pet.bubble.setWindowTitle('Bailong Linux Probe - Bubble')
        if args.niri:
            from linux_app.niri import attach
            attach(pet)
        pet.show()
        if args.live:
            from linux_app.live import start
            start(pet, source)
        else:
            pet.update_quota([dict(name='5小时', remaining=68, resetsAt=None), dict(name='一周', remaining=82, resetsAt=None)], time.time(), 'live')
            pet.bubble.quota_caption = '界面演示数据 · 非真实账户额度'
            pet.bubble.status = 'Linux 隔离验证 · 未连接账户'
        pet.bubble.redraw()
        pet.position_bubble()
        def sample(label):
            """Qt 几何仅作诊断，原生位置还需与 niri 输出及屏幕对照"""
            import subprocess
            windows = json.loads(subprocess.check_output(['niri', 'msg', '--json', 'windows'])) if args.backend != 'offscreen' else []
            row = dict(label=label, native_ids=[int(pet.winId()), int(pet.bubble.winId())], pet=list(pet.geometry().getRect()), bubble=list(pet.bubble.geometry().getRect()),
                windows=[dict(id=w['id'], title=w.get('title'), is_floating=w.get('is_floating'), layout=w.get('layout')) for w in windows if w.get('pid') == os.getpid() or w.get('title') in ('Bailong Linux Probe - Pet', 'Bailong Linux Probe - Bubble')],
                material=pet.material_store.current, decode_error=pet.decode_error, frames=len(pet.frames))
            results['samples'].append(row)
            if args.live:
                row['live'] = dict(quota_source=pet.quota_source, quota_windows=len(pet.quota_windows),
                    token_available=bool(pet.bubble.token_snapshot and not pet.bubble.token_snapshot.get('unavailable')),
                    health=pet.connection_health.snapshot()['capabilities'],
                    ipc=pet.activity.live_reader.health_snapshot() if pet.activity.live_reader else None)
            else:
                pet.grab().save(str(destination / (label + '-pet.png')))
                pet.bubble.grab().save(str(destination / (label + '-bubble.png')))
            emit(row)
        def move():
            """调用原有移动路径，检查合成器是否接受位置变化"""
            sample('before-move')
            point = pet.pos() + QPoint(120, -80)
            results['requested_position'] = [point.x(), point.y()]
            pet.move(point)
            pet.position_bubble()
        def finish():
            """关闭测试拥有的窗口并保存不含账户数据的结果"""
            sample('final')
            (destination / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
            pet.close()
            app.quit()
        if args.manual or args.live or args.niri:
            QTimer.singleShot(1800, lambda: sample('manual-start'))
        else:
            QTimer.singleShot(1800, move)
            QTimer.singleShot(2600, lambda: sample('after-move'))
            QTimer.singleShot(3500, lambda: pet.bubble.set_mode('auto'))
            QTimer.singleShot(4500, lambda: sample('normal'))
            QTimer.singleShot(5500, pet.open_settings)
            QTimer.singleShot(7000, lambda: sample('settings'))
            QTimer.singleShot(8000, pet.open_status)
        QTimer.singleShot(int(args.seconds * 1000), finish)
        emit(dict(pid=os.getpid(), backend=app.platformName(), isolated=True))
        code = app.exec()
        return code or bool(results['errors'])


def main():
    """提供素材校验、真实通信和界面三个可独立复现的入口"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('ipc')
    p.add_argument('--thread')
    p.add_argument('--socket', default=str(Path.home() / '.codex/ipc/ipc.sock'))
    p.add_argument('--seconds', type=float, default=8)
    p.add_argument('--cycles', type=int, default=2)
    p = sub.add_parser('materials')
    p.add_argument('archive', type=Path)
    p = sub.add_parser('gui')
    p.add_argument('--backend', choices=['wayland', 'xcb', 'offscreen'], default='wayland')
    p.add_argument('--seconds', type=float, default=15)
    p.add_argument('--niri', action='store_true', help='使用原生 Wayland 交互移动和 niri 气泡定位')
    p.add_argument('--live', action='store_true', help='读取本机真实状态、额度和统计，桌宠状态仍隔离')
    p.add_argument('--codex-home', help='真实 Codex 数据目录，默认 CODEX_HOME 或 ~/.codex')
    p.add_argument('--codex-cli', default='/usr/lib/chatgpt/resources/codex')
    p.add_argument('--manual', action='store_true', help='不自动移动或切换页面，便于手动拖动验收')
    args = parser.parse_args()
    if getattr(args, 'seconds', 1) <= 0 or getattr(args, 'cycles', 1) <= 0:
        parser.error('seconds 和 cycles 必须大于零')
    if getattr(args, 'niri', False) and (args.backend != 'wayland' or sys.platform != 'linux' or not os.environ.get('NIRI_SOCKET')):
        parser.error('--niri 需要 Linux niri 会话和 --backend wayland')
    return dict(ipc=ipc, materials=materials, gui=gui)[args.command](args)


if __name__ == '__main__':
    raise SystemExit(main())
