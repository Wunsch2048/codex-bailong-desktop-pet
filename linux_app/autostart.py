"""通过 systemd 用户服务登记图形会话自启动"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

UNIT = 'bailong.service'
MARKER = '# Managed by Bailong Linux autostart\n'


def host_environment():
    """宿主 systemd 工具不加载 PyInstaller 私有动态库"""
    import sys
    env = os.environ.copy()
    if getattr(sys, 'frozen', False):
        if 'LD_LIBRARY_PATH_ORIG' in env:
            env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
        else:
            env.pop('LD_LIBRARY_PATH', None)
    return env


def quote(value):
    """转义 systemd ExecStart 参数，禁止控制字符和变量展开"""
    value = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise OSError('启动路径不能包含控制字符')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def launch_command(args, root):
    """记录可持久启动的路径，源码保留虚拟环境而 AppImage 使用外部文件"""
    if getattr(sys, 'frozen', False):
        executable = Path(sys.executable).absolute()
        appimage = os.environ.get('APPIMAGE')
        appdir = os.environ.get('APPDIR')
        if appimage and appdir and executable.resolve().is_relative_to(Path(appdir).resolve()):
            path = Path(appimage).expanduser().resolve()
            if not path.is_file() or not os.access(path, os.X_OK):
                raise OSError('外部 AppImage 不存在或不可执行，请从固定位置重新启动')
            command = [str(path)]
        elif appdir and executable.resolve().is_relative_to(Path(appdir).resolve()):
            raise OSError('无法确认外部 AppImage 路径，不能登记临时挂载目录')
        else:
            command = [str(executable)]
    else:
        command = [str(Path(sys.executable).absolute()), str(root / 'run_linux.py')]
    # 会话环境由桌面导入 systemd，每次登录自动选择 niri 或 KDE
    return command + ['--desktop', 'auto', '--codex-home', str(args.codex_home),
                      '--codex-cli', str(args.codex_cli), '--data-dir', str(args.data_dir)]


class Autostart:
    """只管理本应用用户服务，不启停当前实例或修改系统级设置"""
    def __init__(self, args, root, *, unit=None, flags=(), immediate=False):
        self.args, self.root = args, root
        self.unit, self.flags, self.immediate = unit or UNIT, flags, immediate
        config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
        self.path = config / 'systemd/user' / self.unit

    def run(self, *arguments, check=True):
        """限制 systemctl 等待时间，并将失败反馈给原设置页"""
        try:
            result = subprocess.run(['systemctl', '--user', *arguments], capture_output=True,
                                    text=True, timeout=5, env=host_environment())
        except subprocess.TimeoutExpired as error:
            raise OSError('systemd 用户服务响应超时') from error
        if check and result.returncode:
            raise OSError(result.stderr.strip() or result.stdout.strip() or 'systemd 操作失败')
        return result

    def enabled(self):
        """读取 systemd 登记状态，不启动服务或创建文件"""
        result = self.run('is-enabled', self.unit, check=False)
        state = result.stdout.strip()
        if state in ('enabled', 'enabled-runtime'):
            return True
        if state in ('disabled', 'not-found', 'masked', 'static', 'indirect'):
            return False
        if not state and not self.path.exists():
            # 较旧 systemd 的 is-enabled 只在 stderr 报不存在，LoadState 不依赖语言
            loaded = self.run('show', self.unit, '--property=LoadState', '--value')
            if loaded.stdout.strip() == 'not-found':
                return False
        raise OSError(result.stderr.strip() or '无法读取 systemd 自启动状态')

    def content(self):
        """生成随图形会话启停的服务，正常退出不重启"""
        command = ' '.join(quote(value) for value in launch_command(self.args, self.root) + list(self.flags))
        return MARKER + f'''[Unit]
Description=Bailong desktop pet
PartOf=graphical-session.target
After=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
ExecStart={command}
Restart=on-failure
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=graphical-session.target
'''

    def write(self, content):
        """原子替换本服务文件，不留下半写入的启动命令"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(content)
                stream.flush()
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)

    def configure(self, enabled):
        """仅改变下次登录登记；失败时恢复原文件与启用状态"""
        previous = self.path.read_bytes() if self.path.exists() else None
        if self.path.is_symlink() or (previous is not None and not previous.startswith(MARKER.encode())):
            raise OSError('已有手工管理的 ' + self.unit + '，请先处理该服务，避免覆盖')
        was_enabled = self.enabled()
        if not enabled:
            if previous is not None or was_enabled:
                self.run('disable', *(['--now'] if self.immediate else []), self.unit)
            return
        content = self.content().encode()
        try:
            self.write(content)
            self.run('daemon-reload')
            self.run('enable', self.unit)
            if self.immediate:
                self.run('restart', self.unit)
        except OSError:
            if previous is None:
                self.path.unlink(missing_ok=True)
            else:
                self.write(previous)
            self.run('daemon-reload', check=False)
            self.run('enable' if was_enabled else 'disable', self.unit, check=False)
            if self.immediate:
                self.run('restart' if was_enabled else 'stop', self.unit, check=False)
            raise


def install(stack, args, root):
    """同时替换设置页和托盘导入的函数，不改 Windows 模块源码"""
    from .overrides import replace
    import desktop, desktop_services, desktop_settings
    manager = Autostart(args, root)
    for module in (desktop, desktop_services, desktop_settings):
        stack.enter_context(replace(module, 'autostart_enabled', manager.enabled))
        stack.enter_context(replace(module, 'set_autostart', manager.configure))
