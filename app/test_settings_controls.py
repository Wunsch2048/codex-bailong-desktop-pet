import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint,Signal,QObject,QEvent
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout
from PySide6.QtTest import QTest
from settings_controls import SlidingSegments,SwitchRow
from choice_controls import ChoiceCombo
from desktop_core import DEFAULTS

APP=QApplication.instance() or QApplication([])


class BubbleStub(QObject):
    dataBusyChanged=Signal(str,bool)
    panel_page='status'
    quota_busy=reset_busy=token_busy=False
    def return_to_status(self):pass


class PetStub(QWidget):
    settingsChanged=Signal(object);connectionHealthChanged=Signal(object)
    def __init__(self):
        super().__init__();self.settings=copy.deepcopy(DEFAULTS);self.bubble=BubbleStub(self)
        self.connection_health=SimpleNamespace(snapshot=lambda:{})
        self.manifest={'idle':{'id':'idle','file':'idle.webp'}}
    def apply_settings(self,values):self.settings.update(values);self.settingsChanged.emit(values)
    def character_choices(self):return [('builtin','白龙')]
    def action_groups(self):return {'待机':[self.manifest['idle']]}
    def refresh_quota(self):pass
    def refresh_reset_feed(self):pass
    def refresh_tokens(self):pass
    def open_chat_service(self):pass
    def open_data(self):pass
    def export_diagnostics(self):pass
    def backup_settings(self):pass
    def restore_settings(self):pass
    def cleanup_installations(self):pass


class ControlsTests(unittest.TestCase):
    def tearDown(self):
        for w in APP.topLevelWidgets():w.close();w.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
    def test_segment_pill_moves_and_refresh_does_not_cancel_it(self):
        w=SlidingSegments([('全部','all'),('月','30d'),('周','7d')],compact=True);w.resize(110,27);w.show();APP.processEvents()
        start=w.pill.x()
        with patch('settings_controls.motion_enabled',return_value=True):
            w.buttons['7d'].click();w.animation.setCurrentTime(75);mid=w.pill.x();w.setCurrentIndex(2)
            self.assertGreater(mid,start);self.assertEqual(w.animation.currentTime(),75)
            w.animation.setCurrentTime(170)
        self.assertEqual(w.currentData(),'7d');self.assertGreater(w.pill.x(),mid)
        w.hide();self.assertEqual(w.animation.state(),w.animation.State.Stopped)
    def test_switch_full_row_keyboard_and_disabled_state(self):
        w=SwitchRow('显示面板');w.resize(270,44);w.show();APP.processEvents()
        QTest.mouseClick(w,Qt.MouseButton.LeftButton,pos=QPoint(20,20));self.assertTrue(w.isChecked())
        QTest.keyClick(w,Qt.Key.Key_Space);self.assertFalse(w.isChecked())
        w.setEnabled(False);QTest.mouseClick(w,Qt.MouseButton.LeftButton,pos=QPoint(20,20));self.assertFalse(w.isChecked())
    def test_choice_is_inside_card_searchable_and_preserves_item_data(self):
        host=QWidget();host.resize(420,350);layout=QVBoxLayout(host);choice=ChoiceCombo();layout.addWidget(choice);layout.addStretch()
        for i in range(12):choice.addItem('选项 '+str(i),i)
        host.show();APP.processEvents();choice.showPopup();APP.processEvents();panel=choice._panel
        self.assertIs(panel.parentWidget(),host);self.assertFalse(panel.isWindow());self.assertTrue(host.rect().contains(panel.geometry()))
        panel.search.setText('选项 11');self.assertFalse(panel.list.item(11).isHidden());self.assertTrue(panel.list.item(0).isHidden())
        panel.choose(panel.list.item(11));self.assertEqual(choice.currentData(),11);self.assertIsNone(choice._panel)
    def test_choice_wheel_scrolls_outer_page_without_editing_even_when_focused(self):
        from PySide6.QtWidgets import QScrollArea
        host=QWidget();host.resize(360,300);outer=QVBoxLayout(host);area=QScrollArea();area.setWidgetResizable(True);outer.addWidget(area)
        body=QWidget();layout=QVBoxLayout(body);choice=ChoiceCombo();choice.addItems(['A','B','C']);layout.addWidget(choice);layout.addSpacing(1200);area.setWidget(body)
        host.show();APP.processEvents()
        for focused in (False,True):
            choice.setFocus() if focused else choice.clearFocus()
            area.verticalScrollBar().setValue(0);APP.processEvents()
            QTest.wheelEvent(host.windowHandle(),choice.mapTo(host,choice.rect().center()),QPoint(0,-120));APP.processEvents()
            self.assertEqual(choice.currentIndex(),0)
            self.assertGreater(area.verticalScrollBar().value(),0)
    def test_settings_still_keep_drafts_and_only_apply_on_request(self):
        from desktop_settings import SettingsDialog
        pet=PetStub()
        with patch('desktop_settings.autostart_enabled',return_value=False),patch('codex_startup.enabled',return_value=False):
            settings=SettingsDialog(pet,embedded=True)
        self.assertIsInstance(settings.mode,SlidingSegments)
        self.assertIsInstance(settings.fields['on_top'],SwitchRow)
        self.assertIsInstance(settings.shortcut,ChoiceCombo)
        settings.mode.setCurrentIndex(settings.mode.findData('minimal'))
        self.assertEqual(pet.settings['bubble_mode'],'auto')
        self.assertEqual(settings.draft.changes()['bubble_mode'],'minimal')
        settings.tabs.setCurrentIndex(1);settings.fields['no_move'].setChecked(True)
        self.assertFalse(settings.fields['wandering'].isEnabled())
        settings.apply();self.assertEqual(pet.settings['bubble_mode'],'minimal');self.assertTrue(pet.settings['no_move'])
        self.assertFalse(settings.draft.dirty)
    def test_numeric_stepper_keeps_native_editing_range_and_keyboard(self):
        from number_controls import DecimalField,IntegerField
        from PySide6.QtWidgets import QAbstractSpinBox
        for w,lo,hi,step,start in [(DecimalField(),.4,2.5,.1,1.),(IntegerField(),5,600,1,30)]:
            w.setRange(lo,hi);w.setSingleStep(step);w.setValue(start);w.resize(240,34);w.show();APP.processEvents()
            self.assertEqual(w.buttonSymbols(),QAbstractSpinBox.ButtonSymbols.NoButtons)
            self.assertTrue(w.rect().contains(w.plus.geometry()));self.assertTrue(w.rect().contains(w.minus.geometry()))
            self.assertLess(w.lineEdit().geometry().right(),w.minus.x())
            QTest.mouseClick(w.plus,Qt.MouseButton.LeftButton);self.assertAlmostEqual(w.value(),start+step)
            QTest.mouseClick(w.minus,Qt.MouseButton.LeftButton);self.assertAlmostEqual(w.value(),start)
            w.setValue(hi);self.assertFalse(w.plus.isEnabled());self.assertTrue(w.minus.isEnabled())
            w.selectAll();QTest.keyClicks(w,str(start));QTest.keyClick(w,Qt.Key.Key_Return);self.assertAlmostEqual(w.value(),start)
            QTest.keyClick(w,Qt.Key.Key_Up);self.assertAlmostEqual(w.value(),start+step)
            w.setReadOnly(True);self.assertFalse(w.plus.isEnabled());self.assertFalse(w.minus.isEnabled())
            w.hide();self.assertEqual(w.plus.animation.state(),w.plus.animation.State.Stopped)


if __name__=='__main__':unittest.main()
