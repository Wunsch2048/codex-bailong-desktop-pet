"""Linux Codex 桌面启动监听，不加载 Qt 或角色素材"""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import threading
import psutil
from .autostart import Autostart, launch_command, host_environment

WATCH_UNIT = 'bailong-codex-watch.service'
PET_UNIT = 'bailong-codex-pet.service'


def desktop_sessions():
    """只识别当前用户的 Electron 桌面主进程，CLI 和子进程不触发启动"""
    sessions, uncertain = set(), False
    for process in psutil.process_iter(['name', 'uids']):
        try:
            if (process.info['name'] or '').lower() not in ('chatgpt', 'codex'):
                continue
            if process.info.get('uids') is None:
                uncertain = True
                continue
            if process.info['uids'].real != os.getuid():
                continue
            binary = Path(process.exe()).resolve()
            if not (binary.parent / 'resources/app.asar').is_file():
                continue
            if any(arg.startswith('--type=') for arg in process.cmdline()[1:]):
                continue
            sessions.add((process.pid, process.create_time()))
        except psutil.AccessDenied:
            uncertain = True
        except (psutil.NoSuchProcess, OSError):
            pass
    return sessions if sessions or not uncertain else None


def start_pet(args, root):
    """桌宠使用独立服务生命周期，停止监听不会杀死已打开的界面"""
    env = host_environment()
    active = subprocess.run(['systemctl', '--user', 'is-active', PET_UNIT],
                            capture_output=True, text=True, timeout=5, env=env)
    if active.stdout.strip() in ('active', 'activating'):
        return
    launch = launch_command(args, root)
    # systemd 对 ExecStart 参数展开美元变量；这里通过 D-Bus 传参，不展开百分号
    launch = launch[:1] + [value.replace('$', '$$') for value in launch[1:]]
    command = ['systemd-run', '--user', '--quiet', '--collect', '--service-type=exec',
               '--unit=' + PET_UNIT, '--property=PartOf=graphical-session.target',
               '--property=After=graphical-session.target', '--'] + launch
    result = subprocess.run(command, capture_output=True, text=True, timeout=5, env=env)
    if result.returncode:
        raise OSError(result.stderr.strip() or '启动桌宠服务失败')


def watch(args, root, state):
    """复用 Windows 的会话去重规则，每两秒检测一次并响应服务停止"""
    from codex_startup import LaunchGate
    stopped = threading.Event()
    lock_path = state / 'codex-watch.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        previous = {sig: signal.signal(sig, lambda *_: stopped.set())
                    for sig in (signal.SIGINT, signal.SIGTERM)}
        gate = LaunchGate()
        try:
            while not stopped.is_set():
                if gate.observe(desktop_sessions()):
                    try:
                        start_pet(args, root)
                        print('检测到 Codex 桌面新会话，已请求启动桌宠', flush=True)
                    except (OSError, subprocess.TimeoutExpired) as error:
                        print('Codex 启动联动失败：' + str(error) + '；本次会话不再自动重试，可重新启用随 Codex 启动或重启 Codex', flush=True)
                stopped.wait(2)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 0


def install(stack, args, root):
    """连接启动服务和退出检测，沿用原设置页与会话确认规则"""
    from .overrides import replace
    import codex_startup
    manager = Autostart(args, root, unit=WATCH_UNIT, flags=('--watch-codex',), immediate=True)
    stack.enter_context(replace(codex_startup, 'enabled', manager.enabled))
    stack.enter_context(replace(codex_startup, 'configure', manager.configure))
    stack.enter_context(replace(codex_startup, 'desktop_sessions', desktop_sessions))
