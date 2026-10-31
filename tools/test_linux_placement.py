"""验证显示器位置恢复与启动期间的位置保护"""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PySide6.QtCore import QRect, QSize, QPoint
from linux_app.placement import restore_target, install


def screen(name, rect):
    """构造逻辑像素工作区，不依赖真实显示器"""
    return SimpleNamespace(name=lambda: name, availableGeometry=lambda: rect)


class PlacementTests(unittest.TestCase):
    """缺失输出、缩放后工作区及无效配置均不得把角色恢复到屏幕外"""
    def test_named_monitor_and_negative_origin(self):
        screens = [screen('primary', QRect(0, 0, 1920, 1080)), screen('left', QRect(-1280, 25, 1280, 695))]
        selected, point = restore_target(dict(screen='left', rx=.5, ry=1), QSize(256, 256), screens)
        self.assertEqual(selected.name(), 'left')
        self.assertEqual(point, QPoint(-768, 464))

    def test_missing_monitor_and_clamping(self):
        screens = [screen('remaining', QRect(0, 25, 1280, 695))]
        selected, point = restore_target(dict(screen='unplugged', rx=5, ry=-2), QSize(256, 256), screens)
        self.assertEqual(selected.name(), 'remaining')
        self.assertEqual(point, QPoint(1024, 25))

    def test_invalid_values(self):
        screens = [screen('a', QRect(0, 0, 1920, 1080))]
        for saved in (None, {}, dict(rx=float('nan'), ry=.5), dict(rx='bad', ry=.5)):
            self.assertIsNone(restore_target(saved, QSize(256, 256), screens))

    def test_startup_save_retains_position_and_preferences(self):
        from desktop import DesktopPet
        saved = dict(screen='left', rx=.3, ry=.7)
        pet = SimpleNamespace(enhanced_ready=True, settings=dict(screen_position=saved, position=[300, 400]),
                              wandering=False, random_actions=False, commentary=False, sound=True,
                              bubble=SimpleNamespace(enabled=True, show_quota=True), walk_direction=-1)
        original = DesktopPet.save_settings
        with patch('desktop_core.atomic_json') as write, ExitStack() as stack:
            install(stack)
            DesktopPet.save_settings(pet)
            write.assert_called_once()
            self.assertEqual(pet.settings['screen_position'], saved)
            self.assertEqual(pet.settings['position'], [300, 400])
            self.assertTrue(pet.settings['sound'])
        self.assertIs(DesktopPet.save_settings, original)


if __name__ == '__main__':
    unittest.main()
