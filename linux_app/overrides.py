"""将平台替换限制在当前 Linux 进程的运行周期内"""
from contextlib import contextmanager


@contextmanager
def replace(target, name, value):
    """退出时恢复原成员，保证独立启动和嵌入验证均可清理"""
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)
