"""Issue #22: stale optional widgets cannot freeze navigation."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch,Mock
from types import SimpleNamespace
from shiboken6 import isValid
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QWidget
from compact_bubble import CompactBubble
from surface_morph import SurfaceState,valid_widget

APP=QApplication.instance() or QApplication([])

def drain():
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.b=CompactBubble();self.b.show();APP.processEvents()
    def tearDown(self):
        self.b.size_transition.cancel();self.b.close();self.b.deleteLater();drain()
    def assert_usable(self):
        self.assertTrue(self.b.updatesEnabled());self.assertTrue(self.b.layout.isEnabled())
        self.assertTrue(self.b.content.isVisible());self.assertFalse(self.b.size_transition.preparing)
        self.assertFalse(self.b.size_transition.cover.isVisible())
    def test_optional_reference_must_exist_as_well_as_be_valid(self):
        self.assertFalse(valid_widget(None))
    def test_deleted_live_footer_skips_capture_and_rebuilds_on_return(self):
        b=self.b;old=b.live_rate_card;old.deleteLater();drain();self.assertFalse(isValid(old))
        self.assertNotIn('live_rate',SurfaceState.capture(b).shared_bounds)
        b.compact_requested();b.size_transition.complete();drain();self.assert_usable()
        b.set_mode('auto');b.size_transition.complete();drain()
        self.assertIsNot(b.live_rate_card,old);self.assertTrue(isValid(b.live_rate_card));self.assert_usable()
        b.show_page('settings',QWidget());b.size_transition.complete();self.assertEqual(b.panel_page,'settings');self.assert_usable()
    def test_deleted_optional_header_action_and_heading_are_ignored(self):
        dead=QWidget();dead.deleteLater();drain()
        self.b._header_actions.append(dead);self.b._status_title=dead
        state=SurfaceState.capture(self.b);self.assertNotIn('heading',state.shared_bounds)
    def test_quota_disabled_then_reenabled_and_all_compact_modes(self):
        b=self.b
        for mode in ('mini','auto','minimal','auto'):
            b.set_mode(mode);b.size_transition.complete();drain();self.assert_usable()
        b.show_quota=False;b.redraw();drain()
        b.show_page('settings',QWidget());b.size_transition.complete();self.assert_usable()
        b.return_to_status();b.size_transition.complete();b.show_quota=True;b.redraw();drain()
        self.assertTrue(isValid(b.live_rate_card));b.toggle_details();b.size_transition.complete();self.assert_usable()
    def test_capture_error_restores_input_and_next_navigation_works(self):
        with patch('panel_transition.SurfaceState.capture',side_effect=RuntimeError('capture failed')):
            with self.assertRaisesRegex(RuntimeError,'capture failed'):self.b.toggle_details()
        self.assert_usable();self.b.toggle_details();self.b.size_transition.complete();self.assert_usable()
    def test_target_capture_error_also_unwinds_preparation(self):
        t=self.b.size_transition;t.begin();self.b.expanded=True;self.b.redraw()
        with patch('panel_transition.SurfaceState.capture',side_effect=RuntimeError('target failed')):
            with self.assertRaisesRegex(RuntimeError,'target failed'):t.commit()
        self.assert_usable();self.b.show_status(False);t.complete();self.assert_usable()
    def test_cached_headers_and_details_do_not_grow_or_stale(self):
        b=self.b;b.toggle_details();b.size_transition.complete();tabs=b.details_tabs;header=b._header
        for _ in range(3):
            b.redraw();drain();self.assertIs(b.details_tabs,tabs);self.assertIs(b._header,header)
        b.show_page('settings',QWidget());b.size_transition.complete();b.return_to_status();b.size_transition.complete()
        self.assertIs(b.details_tabs,tabs)
        b.token_snapshot={'all_total':123456,'total':123456};b.redraw();drain()
        self.assertIsNot(b.details_tabs,tabs)
        self.assertEqual(len(b._status_headers),2)
        self.assertIs(b.quota_refresh_button,b.refresh_button)
    def test_cached_details_follow_explicit_destination(self):
        b=self.b;b.toggle_details();b.size_transition.complete();tabs=b.details_tabs
        b.show_status(False);b.size_transition.complete();b.detail_tab='tokens';b.show_status(True);b.size_transition.complete()
        self.assertIs(b.details_tabs,tabs);self.assertEqual(tabs.currentIndex(),1)

    def test_chart_decks_reuse_only_pure_toggles_and_refresh_source_data(self):
        b=self.b;normal=b.deck
        b.toggle_details();b.size_transition.complete();expanded=b.deck;navigation=b._navigation_widget
        b.toggle_details();b.size_transition.complete();self.assertIs(b.deck,normal)
        b.toggle_details();b.size_transition.complete();self.assertIs(b.deck,expanded)
        self.assertIs(b._navigation_widget,navigation)
        b.token_snapshot={'all_total':99,'total':99};b.redraw();drain()
        self.assertIsNot(b.deck,expanded);self.assertEqual(b.deck.snapshot['all_total'],99)
        b.show_quota=False;b.redraw();drain();self.assertFalse(b._deck_cache)


class HiddenPanelTests(unittest.TestCase):
    def test_explicit_settings_and_chat_open_reenable_hidden_panel(self):
        from desktop import DesktopPet
        for page in ('settings','chat'):
            with self.subTest(page=page):
                window=Mock();window.enabled=False;window.windowHandle.return_value=None
                panel=Mock();panel.isWindow.return_value=False
                pet=SimpleNamespace(bubble=window,settings_dialog=panel if page=='settings' else None,chat_window=panel if page=='chat' else None,
                    stop_walk=Mock(),set_option=Mock(),apply_surface_visibility=Mock(),throwing=True,_desktop_hidden=True)
                with patch('desktop.QApplication.setActiveWindow'):DesktopPet.show_panel(pet,panel)
                pet.set_option.assert_called_once_with('bubble',True);window.show_page.assert_called_once_with(page,panel)

if __name__=='__main__':unittest.main()
