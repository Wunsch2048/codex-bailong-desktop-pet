"""Desktop launchers share one lifecycle while keeping their adapters separate."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from linux_app import launcher
import run_kde
import run_niri


class EntrypointTests(unittest.TestCase):
    def test_dedicated_launchers_select_their_desktop(self):
        for entry, desktop in ((run_kde, 'kde'), (run_niri, 'niri')):
            with self.subTest(desktop=desktop), patch.object(launcher, 'main', return_value=7) as main:
                self.assertEqual(entry.main(['--check-runtime']), 7)
                main.assert_called_once_with(['--check-runtime'], desktop=desktop)

    def test_desktop_entry_cannot_be_switched_by_cli(self):
        for desktop, other in (('kde', 'niri'), ('niri', 'kde')):
            with self.subTest(desktop=desktop), self.assertRaises(SystemExit) as result:
                launcher.arguments(['--desktop', other], desktop=desktop)
            self.assertEqual(result.exception.code, 2)

    def test_fixed_niri_entry_ignores_inherited_plasma_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(XDG_CURRENT_DESKTOP='KDE', DISPLAY=':0', WAYLAND_DISPLAY='wayland-0', NIRI_SOCKET='/run/niri.sock')
            with patch.dict(os.environ, env, clear=True), patch.object(launcher.shutil, 'which', return_value='/usr/bin/bwrap'):
                args = launcher.arguments(['--codex-home', folder, '--codex-cli', '/bin/true', '--data-dir', folder + '-state'], desktop='niri')
            self.assertEqual((args.desktop, args.qt_platform), ('niri', 'wayland'))

    def test_dedicated_help_does_not_need_a_running_desktop(self):
        root = Path(__file__).resolve().parents[1]
        env = {key: value for key, value in os.environ.items() if key not in ('DISPLAY', 'WAYLAND_DISPLAY', 'NIRI_SOCKET', 'XDG_CURRENT_DESKTOP', 'DESKTOP_SESSION')}
        for script, desktop in (('run_kde.py', 'kde'), ('run_niri.py', 'niri')):
            with self.subTest(script=script):
                done = subprocess.run([sys.executable, str(root / script), '--help'], env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn('--desktop {' + desktop + '}', done.stdout)

    def test_importing_desktop_entries_does_not_initialize_qt(self):
        root = Path(__file__).resolve().parents[1]
        done = subprocess.run([sys.executable, '-c',
                               'import sys, run_kde, run_niri; assert "PySide6.QtWidgets" not in sys.modules'],
                              cwd=root, capture_output=True, text=True, timeout=5)
        self.assertEqual(done.returncode, 0, done.stderr)
