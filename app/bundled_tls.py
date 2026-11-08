"""Check the Windows frozen OpenSSL pair before loading Qt or Python TLS."""
import ctypes
import sys
from pathlib import Path

OPENSSL_DLLS = ('libcrypto-3-x64.dll', 'libssl-3-x64.dll')


def check_startup():
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return True
    directory = Path(sys.executable).resolve().parent
    missing = [name for name in OPENSSL_DLLS if not (directory / name).is_file()]
    if not missing:
        return True
    message = (
        '白龙桌宠缺少随包 OpenSSL 文件，无法安全启动。\n\n'
        '请重新运行官方安装器，选择当前安装位置以修复安装。\n\n'
        '缺少文件：' + '、'.join(missing) + '\n程序目录：' + str(directory)
    )
    ctypes.windll.user32.MessageBoxW(None, message, '白龙桌宠 · 需要修复安装', 0x10)
    return False
