"""Layer, focus and linked size checks at the desktop entry points."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint,QRect,Qt
from PySide6.QtTest import QTest

import test_interaction_batch as fixture
from desktop_core import normalized, surface_settings


class SurfaceSettingsTests(unittest.TestCase):
    def test_legacy_layer_and_non_default_relative_resize(self):
        self.assertEqual(normalized({'on_top':False})['window_layer'],'normal')
        self.assertFalse(normalized({'window_layer':'bottom','on_top':True})['on_top'])
        settings=normalized(dict(scale=1.7,card_scale=1.15,link_surface_scale=True))
        larger=surface_settings(settings,dict(card_scale=1.2))
        self.assertAlmostEqual(larger['scale']/larger['card_scale'],1.7/1.15,places=5)
        capped=surface_settings(settings,dict(scale=2.5))
        self.assertEqual(capped['card_scale'],1.25)
        self.assertAlmostEqual(capped['scale']/capped['card_scale'],1.7/1.15,places=5)
        independent=surface_settings(larger,dict(link_surface_scale=False,scale=.8))
        self.assertEqual(independent['card_scale'],1.2)


class SurfaceUiTests(unittest.TestCase):
    setUp=fixture.InteractionTests.setUp
    tearDown=fixture.InteractionTests.tearDown

    def test_offscreen_layer_settings_and_focus_keep_layers_in_sync(self):
        p=self.pet;b=p.bubble
        p.apply_settings(dict(window_layer='bottom'),save=False)
        self.assertTrue(p.windowFlags()&Qt.WindowType.WindowStaysOnBottomHint)
        self.assertTrue(b.windowFlags()&Qt.WindowType.WindowStaysOnBottomHint)
        p.apply_settings(dict(window_layer='normal'),save=False)
        for widget in (p,b):
            self.assertFalse(widget.windowFlags()&(Qt.WindowType.WindowStaysOnBottomHint|Qt.WindowType.WindowStaysOnTopHint))
        p.apply_settings(dict(window_layer='top'),save=False)
        self.assertTrue(b.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
        api=SimpleNamespace(foreground=Mock(return_value=15),window_pid=Mock(side_effect=lambda hwnd:hwnd+100))
        p._materials_missing=False;p.apply_surface_visibility()
        with patch.object(p.surface_policy,'api',api),patch('desktop_services.codex_desktop_process',side_effect=lambda pid:pid==115) as codex:
            p.surface_policy.poll_focus();self.assertTrue(p.isVisible());self.assertTrue(b.isVisible())
            p.surface_policy.poll_focus();codex.assert_called_once_with(115)
            api.foreground.return_value=16
            p.surface_policy.poll_focus();self.assertFalse(p.isVisible());self.assertFalse(b.isVisible())
            api.foreground.return_value=15
            p.surface_policy.poll_focus();self.assertTrue(p.isVisible());self.assertTrue(b.isVisible())

    def test_scaled_cards_keep_calendar_motion_and_compact_ring(self):
        from test_daily_report import sample
        p=self.pet;b=p.bubble
        b.set_mode('auto');fixture.settle(p)
        pet_size=p.size();p.apply_settings(dict(card_scale=1.2),save=False);fixture.settle(p)
        self.assertEqual(p.size(),pet_size)
        self.assertEqual(b.width(),round(268*1.2))
        b.token_snapshot=sample();p.open_report();fixture.settle(p)
        r=b.report;r.animation.setCurrentTime(r.animation.duration());fixture.settle(p)
        r.set_page('models');r.set_period('7d');r.page_fade.clear()
        r.model_date_entry.click();r.page_fade.clear();fixture.APP.processEvents()
        self.assertIsNotNone(r.calendar)
        b.toggle_details()
        # The calendar remains present during the host's real width transition.
        self.assertTrue(r.follow.committed);self.assertGreater(r.follow.end.width(),r.follow.start.width())
        fixture.settle(p);r.follow.release()
        self.assertEqual(r.content_geometry().width(),round(360*1.2))
        self.assertIsNotNone(r.calendar)
        b.toggle_details()
        self.assertTrue(r.follow.committed);self.assertLess(r.follow.end.width(),r.follow.start.width())
        b.size_transition.advance(.5);self.assertGreater(r.follow.geometry().width(),r.follow.end.width())
        fixture.settle(p);r.follow.release()
        self.assertEqual(r.content_geometry().width(),round(268*1.2))
        r.close_calendar(False);b.set_mode('minimal');fixture.settle(p)
        self.assertEqual(b.minimal_quota.width(),round(54*1.2))
        p.apply_settings(dict(card_scale=1.25),save=False);fixture.settle(p)
        self.assertEqual(b.minimal_quota.width(),round(54*1.25))

    def test_linked_size_controls_apply_from_saved_non_default_sizes(self):
        p=self.pet;p.apply_settings(dict(scale=1.6,card_scale=1.1),save=False)
        p.open_settings();fixture.settle(p)
        view=p.settings_dialog;view.tabs.setCurrentIndex(1);fixture.settle(p)
        view.fields['link_surface_scale'].setChecked(True)
        self.assertEqual(view.draft.values['scale'],1.6)
        card=view.fields['card_scale'];character=view.fields['scale']
        card.parentWidget().slider.setValue(120)
        self.assertEqual(card.value(),120)
        self.assertEqual(character.parentWidget().slider.value(),round(character.value()))
        self.assertAlmostEqual(view.draft.values['scale']/view.draft.values['card_scale'],1.6/1.1,places=5)
        view.apply();fixture.settle(p)
        self.assertAlmostEqual(p.settings['scale']/p.settings['card_scale'],1.6/1.1,places=5)
        self.assertEqual(p.bubble.width(),432)

    def test_size_input_keeps_fractional_values_while_slider_tracks_nearest_percent(self):
        p=self.pet;p.open_settings();fixture.settle(p)
        view=p.settings_dialog;view.tabs.setCurrentIndex(1);fixture.settle(p)
        control=view.fields['scale']
        control.lineEdit().setText('84.25%');control.interpretText()
        self.assertEqual(control.value(),84.25)
        self.assertEqual(control.parentWidget().slider.value(),84)
        self.assertAlmostEqual(view.draft.values['scale'],.8425)
        self.assertEqual(view.draft.values['card_scale'],p.settings['card_scale'])

    def test_size_preview_updates_both_surfaces_without_saving_until_apply(self):
        p=self.pet;original=QRect(p.geometry())
        p.open_settings();fixture.settle(p)
        view=p.settings_dialog;view.tabs.setCurrentIndex(1);fixture.settle(p)
        decode_size=p.frame_size;card_width=p.bubble.width()
        card=view.fields['card_scale'];person=view.fields['scale']
        person.parentWidget().slider.setValue(120)
        QTest.qWait(40)
        self.assertEqual(p.width(),307);self.assertEqual(p.bubble.width(),card_width)
        self.assertEqual(p.settings['scale'],1.);self.assertEqual(p.frame_size,decode_size)
        view.discard_button.click();QTest.qWait(40)
        self.assertEqual(p.geometry(),original)
        right=p.bubble.screen().availableGeometry().right()
        p.bubble.move(right-p.bubble.width()+1,p.bubble.y())
        view.fields['link_surface_scale'].setChecked(True)
        card.parentWidget().slider.setValue(120)
        QTest.qWait(40)
        self.assertEqual(p.width(),307);self.assertEqual(p.bubble.width(),432)
        self.assertLessEqual(p.bubble.geometry().right(),right)
        self.assertEqual(p.settings['card_scale'],1.)
        p.bubble.return_to_status();fixture.settle(p)
        self.assertEqual(p.geometry(),original)
        self.assertIsNone(p._surface_preview)
        self.assertEqual(view.draft.values['card_scale'],1.2)
        p.open_settings();fixture.settle(p);QTest.qWait(40)
        self.assertEqual(p.bubble.width(),432)
        view.apply();fixture.settle(p)
        self.assertEqual(p.settings['card_scale'],1.2)
        self.assertEqual(p.settings['scale'],1.2)
        self.assertIsNone(p._surface_preview)

    def test_card_grows_before_releasing_slider_handle(self):
        from PySide6.QtWidgets import QStyleOptionSlider
        p=self.pet;p.open_settings();fixture.settle(p)
        view=p.settings_dialog;view.tabs.setCurrentIndex(1);fixture.settle(p)
        slider=view.fields['card_scale'].parentWidget().slider
        option=QStyleOptionSlider();slider.initStyleOption(option)
        thumb=slider.handle_rect(option).center()
        start=p.bubble.width()
        QTest.mousePress(slider,Qt.MouseButton.LeftButton,pos=thumb)
        try:
            QTest.mouseMove(slider,thumb+QPoint(18,0));QTest.qWait(40)
            middle=p.bubble.width()
            self.assertTrue(slider.isSliderDown())
            self.assertGreater(middle,start)
            QTest.mouseMove(slider,thumb+QPoint(32,0));QTest.qWait(40)
            self.assertGreater(p.bubble.width(),middle)
            self.assertEqual(p.settings['card_scale'],1.)
        finally:QTest.mouseRelease(slider,Qt.MouseButton.LeftButton,pos=thumb+QPoint(32,0))
    def test_cost_menu_second_click_and_outside_click_clear_state_immediately(self):
        from test_daily_report import sample
        p=self.pet;p.bubble.token_snapshot=sample()
        p.open_report();fixture.settle(p)
        r=p.bubble.report;r.animation.setCurrentTime(r.animation.duration());fixture.settle(p)
        r.set_page('projects');r.page_fade.clear();fixture.APP.processEvents()
        button=r.cost_more_button
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        pop=r.project_view._cost_actions
        self.assertTrue(pop.isVisible());self.assertTrue(button.isChecked())
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        self.assertFalse(pop.isVisible());self.assertFalse(button.isChecked())
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        pop.native=SimpleNamespace(foreground=lambda:2,mouse_button_down=lambda:False)
        pop.foreground=1;pop.check_outside()
        self.assertFalse(pop.isVisible());self.assertFalse(button.isChecked())
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        QTest.mouseClick(r.page_buttons['overview'],Qt.MouseButton.LeftButton)
        self.assertFalse(pop.isVisible());self.assertFalse(button.isChecked());self.assertEqual(r.page,'overview')


if __name__=='__main__':unittest.main()
