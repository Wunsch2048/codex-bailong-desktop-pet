"""In-memory settings checks: no profiles, startup entries or worker jobs."""
import copy
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PySide6.QtCore import QObject,Signal,Qt,QEvent
from PySide6.QtWidgets import QWidget,QPushButton,QScrollArea
from test_settings_controls import APP,PetStub
from desktop_settings import SettingsDialog
from settings_presentation import SettingsDisclosureButton
from typography import install_ui_font


class MaterialsStub(QObject):
    changed=Signal(object);rollbackRequested=Signal();removeRequested=Signal()
    def __init__(self):
        super().__init__();self.store=SimpleNamespace(current='hd',cache=Path('isolated/materials'))
    def snapshot(self):
        return dict(current='hd',busy=False,phase='ready',supported=True,storagePath='isolated/materials',
                    hdCached=True,lightCached=False,message='',downloaded=0,total=0)
    def request(self,tier):pass
    def cancel(self):pass


class UpdatesStub(QObject):
    changed=Signal(object)
    job=None
    def snapshot(self):return dict(phase='idle',current='1.13.5',message='尚未检查',latest=None)
    def check(self):pass
    def download_install(self):pass
    def cancel(self):pass


class SettingsPet(PetStub):
    def __init__(self):
        super().__init__();self.applied=[];self.previews=[];self.exported=0
        self.bubble.size_transition=SimpleNamespace(preparing=False)
        self.materials=MaterialsStub();self.updates=UpdatesStub()
    def apply_settings(self,values):self.applied.append(copy.deepcopy(values));super().apply_settings(values)
    def preview_theme(self,values,**kwargs):self.previews.append(copy.deepcopy(values))
    def export_diagnostics(self):self.exported+=1
    def open_install_manager(self):pass


class SettingsPresentationTests(unittest.TestCase):
    def setUp(self):
        install_ui_font(APP)
        for target,value in [('desktop_settings.autostart_enabled',False),('codex_startup.enabled',False),
                             ('codex_connection.saved_paths',{}),('codex_connection.data_home',Path('isolated-codex'))]:
            handle=patch(target,return_value=value);handle.start();self.addCleanup(handle.stop)
        self.pet=SettingsPet();self.pet.resize(334,386)
        self.editor=SettingsDialog(self.pet,embedded=True,lazy=True);self.editor.resize(334,386)
        self.pet.show();self.editor.show();APP.processEvents()
    def tearDown(self):
        self.editor.hide();self.pet.hide();self.pet.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
    def page(self,index):
        self.editor.tabs.setCurrentIndex(index);APP.processEvents();return self.editor.tabs.currentWidget()
    def test_all_six_categories_fit_narrow_pane_and_keep_fixed_footer(self):
        footer=self.editor.findChild(QWidget,'settings_footer');baseline=footer.geometry()
        self.assertEqual(self.editor.findChild(QWidget,'settings_sidebar').width(),57)
        for index,button in enumerate(self.editor.category_buttons):
            self.assertEqual(button.size().toTuple(),(49,33))
            self.assertEqual(button.y(),index*37)
        self.assertFalse(self.editor.tabs.tabBar().isVisible())
        for index in range(6):
            area=self.page(index)
            self.assertEqual(area.horizontalScrollBar().maximum(),0,index)
            self.assertEqual(area.verticalScrollBarPolicy(),Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertTrue(self.editor.category_buttons[index].isChecked())
            self.assertEqual(footer.geometry(),baseline)
            self.assertTrue(self.editor.rect().contains(footer.geometry()))
        self.assertFalse(any(b.text()=='返回' for b in self.editor.findChildren(QPushButton)))
        self.assertEqual(len(self.editor.fields['theme'].buttons),9)
        self.assertEqual(sum(not button.isHidden() for button in self.editor.fields['theme'].buttons),8)
    def test_category_and_roaming_subpage_have_body_transitions(self):
        from unittest.mock import patch
        with patch('settings_controls.motion_enabled',return_value=True):
            self.page(1)
            self.assertTrue(self.editor._category_motion.isVisible())
            self.editor._category_motion.clear()
            self.editor.roaming_editor.open();APP.processEvents()
            self.assertTrue(self.editor.roaming_editor.page_motion.isVisible())
            self.editor.roaming_editor.close_page();APP.processEvents()
            self.assertEqual(self.editor.roaming_editor.page_motion.direction,-1)
            self.assertFalse(self.editor.roaming_editor.isVisible())
    def test_update_disclosure_keeps_a_filled_hover_and_checked_surface(self):
        self.page(5)
        from theme_runtime import theme_style_source
        from update_widgets import UpdatePanel
        panel=self.editor.findChild(UpdatePanel)
        source=theme_style_source(panel.details_button)
        self.assertIn('QPushButton:checked:hover{background:#ded2e7;}',source)
        self.assertNotIn('background:transparent',source)
    def test_sidebar_hit_rows_keep_preview_size_after_theme_repolish(self):
        from theme_runtime import set_theme_style,theme_style_source
        for button in self.editor.category_buttons:set_theme_style(button,theme_style_source(button))
        APP.processEvents()
        self.assertEqual([button.height() for button in self.editor.category_buttons],[33]*6)
        self.assertEqual(self.editor.mode.height(),28)
        self.assertTrue(self.editor.mode.property('largeCardPalette'))
    def test_display_options_and_custom_colors_are_directly_available(self):
        area=self.page(0)
        self.assertFalse(any(b.text()=='更多显示选项' for b in area.findChildren(SettingsDisclosureButton)))
        self.assertTrue(self.editor.fields['on_top'].isVisible())
        next(b for b in area.findChildren(QPushButton) if b.text()=='自定义颜色').click();APP.processEvents()
        self.assertTrue(self.editor.theme_custom.isVisible())
        self.assertEqual(self.editor.draft.changes()['theme'],'custom')
        self.assertEqual(self.pet.settings['theme'],'bailong')
    def test_position_and_inertia_and_windows_startup_are_outside_disclosures(self):
        from card_motion import AnimatedDisclosure
        for index,keys in [(1,['no_move','drag_physics']),(2,['startup'])]:
            self.page(index)
            for key in keys:
                control=self.editor.startup if key=='startup' else self.editor.fields[key]
                self.assertTrue(control.isVisible())
                parent=control.parentWidget()
                while parent is not self.editor and parent is not None:
                    self.assertNotIsInstance(parent,AnimatedDisclosure);parent=parent.parentWidget()
    def test_category_reentry_resets_scroll_without_losing_draft(self):
        area=self.page(2)
        fold=next(b for b in area.findChildren(SettingsDisclosureButton) if b.text()=='连接与更多选项')
        fold.click()
        from card_motion import AnimatedDisclosure
        for disclosure in area.findChildren(AnimatedDisclosure):
            if disclosure.expanded:disclosure.complete()
        APP.processEvents();area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
        self.assertGreater(area.verticalScrollBar().value(),0)
        self.editor.fields['quota_decline_threshold'].setValue(23)
        self.page(1);self.page(2)
        self.assertEqual(area.verticalScrollBar().value(),0)
        self.assertEqual(self.editor.draft.changes()['quota_decline_threshold'],23)
    def test_theme_only_previews_and_save_writes_only_changed_fields(self):
        original=copy.deepcopy(self.pet.settings)
        self.editor.fields['theme'].setCurrentIndex(self.editor.fields['theme'].findData('night'))
        self.assertEqual(self.pet.settings,original)
        self.assertEqual(self.pet.previews[-1]['theme'],'night')
        self.assertEqual(self.editor.draft_status.text(),'主题预览')
        self.page(1);self.editor.fields['sound'].setChecked(not original['sound'])
        self.editor.apply()
        self.assertEqual(self.pet.applied,[{'theme':'night','sound':not original['sound']}])
        self.assertFalse(self.editor.draft.dirty)
    def test_discard_rebases_external_changes_instead_of_overwriting_them(self):
        self.editor.mode.setCurrentIndex(self.editor.mode.findData('minimal'))
        self.pet.apply_settings({'capsule_action':'website','capsule_website':'https://example.invalid'})
        self.editor.reload()
        self.assertEqual(self.editor.draft.values['capsule_action'],'website')
        self.assertEqual(self.editor.draft.values['bubble_mode'],self.pet.settings['bubble_mode'])
        self.assertFalse(self.editor.draft.dirty)
    def test_immediate_action_does_not_apply_unrelated_draft(self):
        self.editor.mode.setCurrentIndex(self.editor.mode.findData('minimal'));self.page(5)
        next(b for b in self.editor.findChildren(QPushButton) if b.text()=='导出诊断').click()
        self.assertEqual(self.pet.exported,1);self.assertEqual(self.pet.applied,[])
        self.assertEqual(self.editor.draft.changes()['bubble_mode'],'minimal')
    def test_defaults_only_affect_current_category_and_roaming_remains_editable(self):
        self.editor.mode.setCurrentIndex(self.editor.mode.findData('minimal'))
        self.page(1);self.editor.fields['sound'].setChecked(False);self.editor.defaults_button.click()
        self.assertEqual(self.editor.draft.changes()['bubble_mode'],'minimal')
        self.assertNotIn('sound',self.editor.draft.changes())
        self.editor.roaming_button.click();APP.processEvents()
        self.assertTrue(self.editor.roaming_editor.isVisible())
        self.editor.roaming_editor.mode.setCurrentIndex(self.editor.roaming_editor.mode.findData('zone'))
        self.assertEqual(self.editor.draft.changes()['wander_mode'],'zone')
        self.page(0);self.assertFalse(self.editor.roaming_editor.isVisible())
    def test_real_card_reentry_resets_scroll_but_refresh_and_subpage_return_preserve_it(self):
        from compact_bubble import CompactBubble
        from card_motion import AnimatedDisclosure
        self.pet.resize(150,150);bubble=CompactBubble(self.pet);self.pet.bubble=bubble;self.pet.settings_dialog=self.editor
        def settle():
            for _ in range(4):bubble.size_transition.complete();APP.processEvents()
        bubble.show();bubble.show_page('settings',self.editor);settle()
        area=self.page(1);self.editor.advanced_button.setChecked(True)
        for disclosure in area.findChildren(AnimatedDisclosure):
            if disclosure.expanded:disclosure.complete()
        settle();area.verticalScrollBar().setValue(min(40,area.verticalScrollBar().maximum()));before=area.verticalScrollBar().value()
        self.assertGreater(before,0)
        self.editor.sync_from_pet();settle();self.assertEqual(area.verticalScrollBar().value(),before)
        self.editor.roaming_button.click();settle();self.editor.roaming_editor.hide();settle()
        self.assertEqual(area.verticalScrollBar().value(),before)
        area=self.page(3);area.verticalScrollBar().setValue(area.verticalScrollBar().maximum());self.assertGreater(area.verticalScrollBar().value(),0)
        bubble.return_to_status();settle();bubble.show_page('settings',self.editor);settle()
        self.assertEqual(self.editor.tabs.currentIndex(),3);self.assertEqual(area.verticalScrollBar().value(),0)
        self.assertEqual(self.editor.size().toTuple(),(334,386));bubble.hide()
    def test_manual_zone_reset_uses_vector_action_and_preserves_draft_boundary(self):
        from settings_presentation import SettingsResetButton
        self.page(1);self.editor.roaming_button.click();roaming=self.editor.roaming_editor
        roaming.mode.setCurrentIndex(roaming.mode.findData('zone'));APP.processEvents()
        self.assertIsInstance(roaming.reset_zone,SettingsResetButton)
        self.assertEqual(roaming.reset_zone.text(),'');self.assertEqual(roaming.reset_zone.accessibleName(),'重置活动区')
        roaming.diagram.setValue([.2,.2,.6,.6]);roaming.diagram.valueChanged.emit();roaming.reset_zone.click()
        self.assertEqual(roaming.diagram.value(),self.pet.settings['wander_zone']);self.assertEqual(self.pet.applied,[])
    def test_download_and_update_controls_still_fit_when_actions_are_available(self):
        area=self.page(3);panel=self.editor.material_panel
        self.assertGreaterEqual(panel.height(),panel.minimumSizeHint().height()-3)
        panel.refresh(dict(panel.controller.snapshot(),current=None,busy=True,phase='downloading',total=1000,downloaded=300))
        APP.processEvents();self.assertEqual(area.horizontalScrollBar().maximum(),0)
        area=self.page(5);panel=self.editor.update_panel
        panel.set_state(dict(panel.controller.snapshot(),latest='1.14.0',phase='available',notes='新的更新说明',url='https://example.invalid'))
        APP.processEvents();self.assertEqual(area.horizontalScrollBar().maximum(),0)


if __name__=='__main__':unittest.main()
