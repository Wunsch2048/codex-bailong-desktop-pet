"""Compositor selection must keep the native niri and Plasma paths separate."""
import unittest
from linux_app.backends import select


class BackendTests(unittest.TestCase):
    def test_plasma_wayland_uses_xwayland(self):
        env = dict(XDG_CURRENT_DESKTOP='KDE', WAYLAND_DISPLAY='wayland-0', DISPLAY=':0')
        self.assertEqual(select(env=env), ('kde', 'xcb'))

    def test_plasma_x11_and_session_fallback(self):
        self.assertEqual(select(env=dict(XDG_CURRENT_DESKTOP='KDE', DISPLAY=':0')), ('kde', 'xcb'))
        self.assertEqual(select(env=dict(DESKTOP_SESSION='/usr/share/wayland-sessions/plasma.desktop', DISPLAY=':0')), ('kde', 'xcb'))

    def test_current_plasma_wins_over_inherited_niri_socket(self):
        env = dict(XDG_CURRENT_DESKTOP='KDE', DISPLAY=':0', NIRI_SOCKET='/stale/niri.sock')
        self.assertEqual(select(env=env), ('kde', 'xcb'))

    def test_niri_keeps_native_wayland(self):
        env = dict(NIRI_SOCKET='/run/niri.sock', WAYLAND_DISPLAY='wayland-1', DISPLAY=':1')
        self.assertEqual(select(env=env), ('niri', 'wayland'))

    def test_explicit_desktop_overrides_detection(self):
        env = dict(XDG_CURRENT_DESKTOP='KDE', DISPLAY=':0', WAYLAND_DISPLAY='wayland-1', NIRI_SOCKET='/run/niri.sock')
        self.assertEqual(select('niri', env), ('niri', 'wayland'))

    def test_missing_display_is_actionable(self):
        with self.assertRaisesRegex(ValueError, 'XWayland.*DISPLAY'):
            select('kde', dict(WAYLAND_DISPLAY='wayland-0'))

    def test_niri_requires_its_socket_and_wayland(self):
        for env in ({}, dict(WAYLAND_DISPLAY='wayland-0'), dict(NIRI_SOCKET='/run/niri.sock')):
            with self.subTest(env=env), self.assertRaises(ValueError):
                select('niri', env)

    def test_unknown_compositor_is_not_silently_treated_as_kde(self):
        with self.assertRaisesRegex(ValueError, '--desktop'):
            select(env=dict(XDG_CURRENT_DESKTOP='GNOME', DISPLAY=':0'))
