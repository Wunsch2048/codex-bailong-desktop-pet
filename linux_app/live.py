"""Linux 只读数据适配，不改动 Windows 生产模块"""
import os
import sys
from pathlib import Path
import select
import socket
import stat
import subprocess


def open_codex(session=None):
    """在原导航工作线程中交给桌面协议处理器，不把派发成功当作已读"""
    from desktop_services import codex_conversation_url
    from .autostart import host_environment
    url = codex_conversation_url(session) if session is not None else 'codex://launch'
    env = host_environment()
    # 外部桌面工具使用宿主 Qt，不能继承桌宠的插件目录与后端选择
    for name in ('QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QT_QPA_PLATFORM', 'QT_QPA_PLATFORMTHEME'):
        env.pop(name, None)
    try:
        handler = subprocess.run(['xdg-mime', 'query', 'default', 'x-scheme-handler/codex'],
                                 capture_output=True, text=True, timeout=5, env=env)
        if handler.returncode or not handler.stdout.strip():
            raise OSError('未找到 Codex 链接处理器，请确认 Codex 安装已注册 codex:// 协议')
        result = subprocess.run(['xdg-open', url], capture_output=True, text=True,
                                timeout=8, env=env)
    except FileNotFoundError:
        raise OSError('缺少 xdg-mime 或 xdg-open，请安装 xdg-utils 后重试') from None
    except subprocess.TimeoutExpired:
        raise OSError('打开 Codex 链接超时，请检查桌面协议处理器后重试') from None
    if result.returncode:
        raise OSError('无法打开 Codex 链接，请检查 codex:// 协议处理器后重试')


def install(stack, home, executable):
    """在验证进程内替换 Windows 传输及进程发现，保留原业务解析"""
    from .overrides import replace
    import quota, codex_connection, desktop_services, desktop
    import msgspec
    from codex_live_status import LiveStatusReader
    wrapper = (Path(sys.executable).resolve().parent / 'linux_app/codex_readonly') if getattr(sys, 'frozen', False) else Path(__file__).with_name('codex_readonly')
    os.environ['BAILONG_FROZEN'] = '1' if getattr(sys, 'frozen', False) else '0'
    os.environ['BAILONG_NATIVE_CODEX'] = str(executable)
    os.environ['BAILONG_CODEX_HOME'] = str(home)
    os.environ['CODEX_HOME'] = str(home)
    # 查询程序看见只读配置和认证文件，缓存、日志、数据库均位于临时挂载
    stack.enter_context(replace(quota, 'find_codex', lambda: str(wrapper)))
    stack.enter_context(replace(codex_connection, 'find_executable', lambda: str(executable)))
    stack.enter_context(replace(desktop_services, 'open_codex', open_codex))
    stack.enter_context(replace(desktop, 'open_codex', open_codex))

    def run(reader):
        """Unix socket 断线后重连，订阅与消息解析沿用原实现"""
        endpoint = home / 'ipc/ipc.sock'
        while not reader.stop_event.is_set():
            try:
                info = endpoint.stat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise OSError('IPC socket owner mismatch')
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(2)
                    connection.connect(str(endpoint))
                    class Transport:
                        """将套接字提供为原监听器所需的字节流"""
                        def read(self, count):
                            data = connection.recv(count)
                            if not data:
                                raise OSError('IPC disconnected')
                            return data
                        def write(self, data):
                            return connection.send(data)
                    reader._listen(Transport(), lambda: 65536 if select.select([connection], [], [], 0)[0] else 0)
            except (OSError, ValueError, msgspec.MsgspecError):
                reader.set_health('degraded', 'ipc_disconnected')
            finally:
                reader.connected = False
            reader.stop_event.wait(3)

    def presence():
        """共享 Linux 桌面会话判定，未知权限状态不能被当作桌面退出"""
        from .codex_watch import desktop_sessions
        sessions = desktop_sessions()
        return None if sessions is None else bool(sessions)

    stack.enter_context(replace(LiveStatusReader, 'run', run))
    stack.enter_context(replace(desktop_services, 'codex_desktop_open', presence))


def start(pet, home):
    """接入原活动监测及额度刷新，不启动 Windows 自启动和更新服务"""
    from PySide6.QtCore import QTimer
    from enhanced import ActivityThread
    pet.bubble.quota_caption = '正在读取本机 Codex 额度…'
    pet.bubble.status = '正在连接本机 Codex…'
    pet.activity = ActivityThread(pet, home=home)
    pet.activity.event.connect(pet.on_activity)
    pet.activity.start()
    # 原轮询在后台线程识别进程，关闭选项时不扫描；退出仍经过 ExitGate
    pet.codex_timer.start()
    QTimer.singleShot(1800, pet.refresh_quota)


def prepare_materials(root, source, destination):
    """复用已经校验的不可变素材，真实模式使用独立设置和统计缓存"""
    import shutil
    from material_store import MaterialStore, checked
    store = MaterialStore(root, destination)
    target = store.tier_root('light')
    if not target.exists():
        original = MaterialStore(root, source).tier_root('light')
        store.verify(original, 'light')
        for item in store.catalog['tiers']['light']['files']:
            src = checked(original, item['path'])
            dst = checked(target, item['path'])
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
    store.verify(target, 'light')
    store._receipt(target, 'light')
    store.activate('light', target)
