"""Theme changes repeatedly repolish Qt widgets. Exercise them in their own process."""
import json
import unittest
from unittest.mock import patch
import test_interaction_batch as interaction

settle=interaction.settle

class ThemeInteractionTests(unittest.TestCase):
    setUp=interaction.InteractionTests.setUp
    tearDown=interaction.InteractionTests.tearDown
    settings=interaction.InteractionTests.settings

    def test_theme_swatches_apply_persist_and_keep_unrelated_draft(self):
        from theme_registry import current,palette
        s=self.settings();s.fields['move_speed'].setValue(123)
        choices=s.fields['theme'];choices.setCurrentIndex(choices.findData('starfield'));s.apply();settle(self.pet)
        self.assertEqual(current(),'starfield');self.assertEqual(self.pet.settings['move_speed'],123)
        stored=json.loads((self.root/'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['theme'],'starfield');self.assertFalse(s.theme_custom.isVisible())
        self.assertIn(palette()['ink'],s.styleSheet());self.assertFalse(s.draft.dirty)
        choices.setCurrentIndex(choices.findData('custom'))
        s.fields['theme_surface'].setText('#ffffff');s.fields['theme_ink'].setText('#ffffff');s.apply();settle(self.pet)
        self.assertIn('对比度不足',s.status.text());self.assertEqual(current(),'custom');self.assertEqual(self.pet.settings['theme'],'starfield');self.assertIn('theme',s.draft.dirty)
        s.reload();settle(self.pet)
        self.pet.apply_settings(dict(theme='bailong'),save=False);settle(self.pet)

    def test_preview_is_not_saved_by_position_or_other_settings_and_navigation_restores(self):
        from theme_registry import current,THEME_KEYS
        s=self.settings();saved={k:self.pet.settings[k] for k in THEME_KEYS}
        s.fields['theme'].setCurrentIndex(s.fields['theme'].findData('division'));settle(self.pet)
        self.assertEqual(current(),'division');self.assertEqual({k:self.pet.settings[k] for k in THEME_KEYS},saved)
        self.pet.save_settings();disk=json.loads((self.root/'settings.json').read_text(encoding='utf-8'))
        self.assertEqual({k:disk[k] for k in THEME_KEYS},saved)
        self.pet.apply_settings(dict(sound=False));settle(self.pet);self.assertEqual(current(),'division')
        s.fields['move_speed'].setValue(123);self.pet.bubble.return_to_status();settle(self.pet)
        self.assertEqual(current(),saved['theme']);self.assertIn('move_speed',s.draft.dirty)
        self.assertFalse(set(THEME_KEYS)&s.draft.dirty);self.assertIsNone(self.pet._theme_preview)

    def test_preview_save_failure_and_discard_keep_committed_theme(self):
        from theme_registry import current
        s=self.settings();saved=self.pet.settings['theme']
        s.fields['theme'].setCurrentIndex(s.fields['theme'].findData('division'));settle(self.pet)
        with patch.object(self.pet,'save_settings',side_effect=OSError('fixture write failure')):s.apply()
        settle(self.pet);self.assertEqual(self.pet.settings['theme'],saved);self.assertEqual(current(),'division')
        self.assertIn('theme',s.draft.dirty);s.discard_button.click();settle(self.pet)
        self.assertEqual(current(),saved);self.assertIsNone(self.pet._theme_preview)
