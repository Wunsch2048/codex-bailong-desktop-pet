import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bundled_tls import OPENSSL_DLLS, check_startup


class BundledTlsStartupTests(unittest.TestCase):
    def check(self, platform, frozen, present):
        message_box = Mock()
        with patch.object(sys, 'platform', platform), patch.object(sys, 'frozen', frozen, create=True), \
             patch.object(Path, 'is_file', autospec=True, side_effect=lambda path: path.name in present), \
             patch.object(ctypes, 'windll', Mock(user32=Mock(MessageBoxW=message_box)), create=True):
            return check_startup(), message_box

    def test_missing_pair_member_reports_repair_and_blocks_startup(self):
        for missing in OPENSSL_DLLS:
            with self.subTest(missing=missing):
                allowed, dialog = self.check('win32', True, set(OPENSSL_DLLS) - {missing})
                self.assertFalse(allowed)
                dialog.assert_called_once()
                self.assertIn(missing, dialog.call_args.args[1])
                self.assertIn('修复安装', dialog.call_args.args[1])

    def test_complete_pair_and_unaffected_launches_continue(self):
        for platform, frozen, present in (
            ('win32', True, OPENSSL_DLLS), ('win32', False, ()), ('linux', True, ())
        ):
            allowed, dialog = self.check(platform, frozen, present)
            self.assertTrue(allowed)
            dialog.assert_not_called()
