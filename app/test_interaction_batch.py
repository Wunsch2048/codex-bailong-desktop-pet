"""User journeys for settings, navigation and destructive chat commands."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PySide6.QtCore import Qt,QObject,QEvent
from PySide6.QtWidgets import QApplication,QMenu,QToolButton
from PySide6.QtTest import QTest
from desktop import DesktopPet
from desktop_core import atomic_json
from chat_window import SessionStore,CHAT_DEFAULT
from settings_draft import SettingsDraft

APP=QApplication.instance() or QApplication([])


def settle(pet):
    for _ in range(4):
        APP.processEvents();pet.bubble.size_transition.complete()
    APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)


class DraftTests(unittest.TestCase):
    def test_rebase_keeps_edits_and_only_commits_changes(self):
        d=SettingsDraft(dict(a=1,b=2));d.set('a',3);d.rebase(dict(a=1,b=4))
        self.assertEqual(d.changes(),dict(a=3));self.assertEqual(d.values['b'],4)
        d.rebase(dict(a=5));self.assertEqual(d.conflicts,{'a'});self.assertEqual(d.values['a'],3)
        d.set('a',5);self.assertFalse(d.dirty);self.assertFalse(d.conflicts)
    def test_external_value_matching_draft_settles_without_conflict(self):
        d=SettingsDraft(dict(a=['one']));d.set('a',['two']);d.rebase(dict(a=['two']))
        self.assertFalse(d.dirty);self.assertFalse(d.conflicts)


class InteractionTests(unittest.TestCase):
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

    @patch('settings_controls.motion_enabled',return_value=True)
    def test_quota_alert_opens_prepared_cycle_page_without_toggling_main_card(self,_motion):
        from card_surface_probe import sample
        self.pet.bubble.token_snapshot=sample();b=self.pet.bubble;before=b.geometry()
        self.pet.open_quota_comparison();r=b.report
        if b.size_transition.running:
            self.assertFalse(r.isVisible());self.assertIsNone(r._frame)
            b.size_transition.complete()
        self.assertTrue(r.requested);self.assertEqual(r.page,'cycle');self.assertIsNotNone(r._frame)
        # Reserving report space may animate the host's position; once landed
        # it must retain the original card size and never expand its contents.
        self.assertEqual(b.size(),before.size());self.assertFalse(b.size_transition.running)
        placed=b.geometry()
        r.animation.setCurrentTime(110);fraction=r.fraction;frame=r._frame
        self.pet.open_quota_comparison()
        self.assertIs(b.report,r);self.assertFalse(r.requested)
        self.assertEqual(r.fraction,fraction);self.assertIs(r._frame,frame)
        self.pet.open_quota_comparison();self.assertTrue(r.requested);self.assertEqual(r.fraction,fraction)
        r.animation.setCurrentTime(r.animation.duration());APP.processEvents();size=r.size()
        r.set_page('models');self.pet.open_quota_comparison()
        self.assertEqual(r.page,'cycle');self.assertTrue(r.requested);self.assertEqual(r.size(),size)
        self.assertEqual(b.geometry(),placed)
        r.page_fade.animation.setCurrentTime(r.page_fade.animation.duration())
        self.pet.open_quota_comparison();self.assertFalse(r.requested)
        r.animation.setCurrentTime(r.animation.duration());APP.processEvents();self.assertFalse(r.isVisible())
        b._header_actions[1].click();r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
        self.assertTrue(r.requested)
        with patch.object(r,'set_snapshot',side_effect=AssertionError('closing must not refresh or rebuild')):
            b._header_actions[1].click()
        self.assertFalse(r.requested);r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
        self.assertFalse(r.isVisible())
        # Closing the panel now returns the host through its own animation.
        # Do not mistake the temporary union canvas for the final card bounds.
        settle(self.pet)
        self.assertEqual(b.size(),before.size());self.assertFalse(b.size_transition.running)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch('enhanced.CONFIG',self.root/'settings.json'),patch('enhanced.STATE_DIR',self.root),
            patch('desktop.CONFIG',self.root/'settings.json'),patch('desktop.STATE_DIR',self.root),
            patch('desktop_settings.autostart_enabled',return_value=False),patch('desktop_settings.set_autostart')]
        for p in self.patches:p.start()
        self.startup=self.patches[-1].target.set_autostart
        self.pet=DesktopPet(monitor=False);self.pet.tick.stop();self.pet.motion_timer.stop()
        self.pet.apply_settings(dict(random_actions=False,wandering=False),save=False);self.pet.show();settle(self.pet)
    def tearDown(self):
        self.pet.close();settle(self.pet)
        self.pet.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def settings(self):
        self.pet.open_settings();settle(self.pet)
        for index in range(6):self.pet.settings_dialog.build_page(index)
        return self.pet.settings_dialog
    def chat(self):
        self.pet.open_chat();settle(self.pet);return self.pet.chat_window
    def test_external_toggle_and_cross_tab_edits_are_not_overwritten(self):
        s=self.settings();s.fields['scale'].setValue(1.2);s.fields['move_speed'].setValue(123)
        self.pet.apply_settings(dict(random_actions=True,on_top=False))
        self.assertTrue(s.fields['random_actions'].isChecked());self.assertFalse(s.fields['on_top'].isChecked())
        with patch.object(self.pet,'apply_settings',wraps=self.pet.apply_settings) as apply:
            s.apply();self.assertEqual(set(apply.call_args.args[0]),{'scale','move_speed'})
        self.assertTrue(self.pet.settings['random_actions']);self.assertFalse(self.pet.settings['on_top'])
        self.assertEqual(self.pet.settings['scale'],1.2);self.assertEqual(self.pet.settings['move_speed'],123)
        self.startup.assert_not_called();self.assertFalse(s.draft.dirty)
    def test_conflict_is_visible_and_discard_uses_current_values(self):
        s=self.settings();s.fields['scale'].setValue(1.3);self.pet.apply_settings(dict(scale=1.1))
        self.assertEqual(s.fields['scale'].value(),1.3);self.assertEqual(s.draft.conflicts,{'scale'})
        self.assertIn('有冲突',s.draft_status.text());s.apply();self.assertEqual(self.pet.settings['scale'],1.3)
        s.fields['scale'].setValue(1.4);self.pet.apply_settings(dict(scale=1.0));s.discard_button.click()
        self.assertEqual(s.fields['scale'].value(),1.0);self.assertFalse(s.draft.dirty)
    def test_startup_failure_does_not_block_other_settings_or_clear_draft(self):
        s=self.settings();s.startup.setChecked(True);s.fields['scale'].setValue(1.1)
        self.startup.side_effect=OSError('isolated write failure');s.apply()
        self.assertEqual(self.pet.settings['scale'],1.1);self.assertEqual(s.draft.dirty,{'startup'})
        self.assertIn('开机启动保存失败',s.status.text());self.startup.side_effect=None
        with patch.object(self.pet,'apply_settings') as apply:s.apply();apply.assert_not_called()
        self.assertFalse(s.draft.dirty);self.startup.assert_called_with(True)
    def test_failed_settings_save_restores_runtime_and_preserves_draft(self):
        s=self.settings();old=self.pet.height();s.fields['scale'].setValue(1.4)
        with patch.object(self.pet,'save_settings',side_effect=OSError('isolated save failure')):s.apply()
        self.assertEqual(self.pet.settings['scale'],1.0);self.assertEqual(self.pet.height(),old)
        self.assertEqual(s.draft.dirty,{'scale'});self.assertIn('保存失败',s.status.text())
    def test_defaults_are_per_tab_and_movement_dependencies_are_explicit(self):
        s=self.settings();s.fields['scale'].setValue(1.2);s.mode.setCurrentIndex(s.mode.findData('mini'));s.startup.setChecked(True);s.tabs.setCurrentIndex(1)
        s.fields['no_move'].setChecked(True);self.assertFalse(s.fields['wandering'].isEnabled())
        self.assertFalse(s.fields['wander_horizontal_only'].isEnabled());self.assertEqual(s.fields['move_range'].value(),100)
        self.assertEqual(s.fields['status_action_interval'].decimals(),0)
        s.defaults_button.click();self.assertFalse(s.fields['no_move'].isChecked());self.assertEqual(s.fields['scale'].value(),1.0)
        self.assertEqual(s.mode.currentData(),'mini');self.assertTrue(s.startup.isChecked());self.startup.assert_not_called()
    def test_setting_categories_keep_startup_response_and_chat_together(self):
        s=self.settings()
        self.assertEqual([s.tabs.tabText(i) for i in range(s.tabs.count())],['面板','人物','Codex','素材','闲聊','维护'])
        for key,tab in [('bubble_mode',0),('panel_detached',0),('scale',1),('drag_physics',1),('startup',2),('codex_startup',2),('codex_exit',2),('commentary',2),('status_actions',2),('self_talk',4),('talk_lines',4),('update_checks',5)]:
            self.assertEqual(s.field_tabs[key],tab,key)
        s.fields['self_talk'].setChecked(True);s.lines.setPlainText('保留的台词草稿')
        s.tabs.setCurrentIndex(1);s.defaults_button.click()
        self.assertEqual(s.lines.toPlainText(),'保留的台词草稿')
        self.assertTrue(s.fields['self_talk'].isChecked())

    def test_menus_have_separate_roles_and_share_live_settings(self):
        menu=QMenu();self.pet.build_menu(menu);self.assertEqual(len([a for a in menu.actions() if not a.isSeparator()]),9)
        panel=next(a for a in menu.actions() if a.objectName()=='command_bubble');self.assertTrue(panel.isCheckable())
        tray=QMenu();self.pet.build_menu(tray,tray=True);self.assertEqual(len([a for a in tray.actions() if not a.isSeparator()]),6)
        self.assertIn('找回组件并关闭穿透',[a.text() for a in tray.actions()])
        pin=next(a for a in menu.findChildren(__import__('PySide6.QtGui',fromlist=['QAction']).QAction) if a.objectName()=='command_pin')
        pin.trigger();settle(self.pet);self.assertFalse(self.pet.settings['on_top'])
        self.pet.apply_settings(dict(no_move=True,mouse_through=True));self.pet.hide();self.pet.bubble.hide()
        self.pet.build_menu(menu);walk=next(a for a in menu.actions() if a.objectName()=='command_walk')
        self.assertFalse(walk.isEnabled());self.assertIn('已锁定',walk.text())
        self.pet.execute_command('recover');self.assertTrue(self.pet.isVisible());self.assertFalse(self.pet.settings['mouse_through'])

    def test_recover_from_tray_restores_panel_when_both_surfaces_are_hidden(self):
        self.pet.settings['character_visible']=False;self.pet.settings['bubble']=False
        self.pet.bubble.enabled=False;self.pet._desktop_hidden=True;self.pet.apply_surface_visibility()
        self.assertFalse(self.pet.isVisible());self.assertFalse(self.pet.bubble.isVisible())
        self.pet.recover();settle(self.pet)
        self.assertTrue(self.pet.bubble.isVisible())
    def test_quota_query_is_a_silent_refresh_without_changing_preferences(self):
        self.pet.apply_settings(dict(bubble=False,quota_visible=False));current=self.pet.current
        with patch.object(self.pet,'refresh_quota') as refresh,patch('enhanced.EnhancedPet.quota') as interaction:
            self.pet.quota();refresh.assert_called_once();interaction.assert_not_called()
        self.assertIs(self.pet.current,current);self.assertFalse(self.pet.settings['bubble']);self.assertFalse(self.pet.settings['quota_visible'])
        self.assertIn(self.pet.manifest['quotaAnimation'],self.pet.action_groups()['额度回应（不刷新数据）'])
    def test_shortcut_failure_restores_state_and_gives_visible_feedback(self):
        before=self.pet.settings['on_top']
        with patch.object(self.pet,'save_settings',side_effect=OSError('isolated failure')),patch.object(self.pet,'say') as say:
            self.pet.execute_command('pin',not before)
            self.assertEqual(self.pet.settings['on_top'],before);self.assertIn('已恢复原值',say.call_args.args[0])
    def test_return_restores_origin_through_multiple_editors_and_preserves_draft(self):
        b=self.pet.bubble
        for mode,expanded in [('mini',False),('auto',False),('auto',True)]:
            b.set_mode(mode);settle(self.pet)
            if expanded:b.show_status(True);settle(self.pet)
            was_island=b.is_island();self.chat().input.setPlainText('draft')
            s=self.settings();s.fields['scale'].setValue(1.2);s.dismiss();settle(self.pet)
            self.assertEqual(b.panel_page,'status');self.assertEqual(b.expanded,expanded);self.assertEqual(b.is_island(),was_island)
            self.assertEqual(self.pet.chat_window.input.toPlainText(),'draft');self.assertEqual(s.fields['scale'].value(),1.2)
    def test_collapse_is_normal_and_queued_navigation_keeps_latest_intent(self):
        b=self.pet.bubble;b.set_mode('mini');settle(self.pet);self.pet.open_chat()
        b.size_transition.animation.setCurrentTime(100);native=b.geometry()
        self.pet.open_settings();b.return_to_status();self.assertEqual(b.geometry(),native);settle(self.pet)
        self.assertEqual(b.panel_page,'status');self.assertTrue(b.is_island())
        self.pet.open_chat();settle(self.pet);b.collapse_to_normal();settle(self.pet)
        self.assertEqual(b.panel_page,'status');self.assertFalse(b.expanded);self.assertFalse(b.is_island())
    def test_chat_clear_requires_inline_confirmation_and_cancel_preserves_disk(self):
        c=self.chat();c.session['messages']=[dict(role='user',content='keep')];c.store.save()
        c.clear();self.assertIn(c.session['title'],c.confirmation.message.text());self.assertEqual(c.session['messages'][0]['content'],'keep')
        c.confirmation.cancel_button.click();self.assertEqual(SessionStore(self.root,c.character).sessions[0]['messages'],c.session['messages'])
        c.clear();c.confirmation.confirm_button.click();self.assertEqual(SessionStore(self.root,c.character).sessions[0]['messages'],[])
    def test_delete_cancels_stream_and_late_completion_cannot_restore_it(self):
        c=self.chat();old=c.session['id'];c.session['messages']=[dict(role='user',content='keep')];c.store.save()
        stream=Mock();stream.cancel.side_effect=lambda:c.on_done(stream,'late reply');c.stream=stream;c.busy=True
        c.delete();self.assertTrue(c.busy);c.confirmation.confirm_button.click()
        stream.cancel.assert_called_once();self.assertNotEqual(c.session['id'],old);self.assertFalse(c.busy)
        c.on_delta(stream,'late');c.on_done(stream,'late');self.assertEqual(c.session['messages'],[])
        self.assertNotIn(old,[s['id'] for s in SessionStore(self.root,c.character).sessions])
    def test_switch_cancels_pending_delete_and_failed_writes_keep_history(self):
        c=self.chat();c.session['messages']=[dict(role='user',content='keep')];c.store.save()
        c.delete();c.new();c.confirmation.confirm();self.assertEqual(len(c.store.sessions),2)
        c.sessions.setCurrentIndex(1);key=c.session['id'];messages=list(c.session['messages'])
        with patch.object(c.store,'save',side_effect=OSError('isolated write failure')):
            c.clear();c.confirmation.confirm();self.assertEqual(c.session['messages'],messages)
            c.delete();c.confirmation.confirm();self.assertEqual(c.session['id'],key);self.assertEqual(len(c.store.sessions),2)
    def test_provider_drafts_survive_switches_and_key_deletion_requires_confirmation(self):
        from chat_config import load_chat_config,load_provider_key
        from desktop_services import SecretStore
        config=dict(CHAT_DEFAULT,providers=[dict(id='a',name='Service A',model='A'),dict(id='b',name='Service B',model='B')],active='a')
        SecretStore(self.root/'credentials.dpapi.json').put('a','isolated-confirm-test-key')
        atomic_json(self.root/'chat.json',config);c=self.chat();c.provider();p=c.provider_dialog
        p.fields['model'].setText('pending-A');p.select.setCurrentIndex(1);p.select.setCurrentIndex(0)
        self.assertEqual(p.fields['model'].text(),'pending-A')
        original=(self.root/'credentials.dpapi.json').read_bytes()
        p.clear_key();self.assertEqual((self.root/'credentials.dpapi.json').read_bytes(),original)
        p.confirmation.cancel();self.assertEqual(load_provider_key(self.root,load_chat_config(self.root)['providers'][0]),'isolated-confirm-test-key')
        p.clear_key();p.confirmation.confirm();self.assertEqual(load_provider_key(self.root,load_chat_config(self.root)['providers'][0]),'')
        self.assertEqual(p.fields['model'].text(),'pending-A')
        p.remove();self.assertEqual(len(json.loads((self.root/'chat.json').read_text(encoding='utf-8'))['providers']),2)
        p.select.setCurrentIndex(1);p.confirmation.confirm();self.assertEqual(len(p.config['providers']),2)
        p.remove();p.confirmation.confirm()
        self.assertEqual([x['id'] for x in json.loads((self.root/'chat.json').read_text(encoding='utf-8'))['providers']],['a'])
    def test_escape_cancels_confirmation_then_returns_without_losing_input(self):
        c=self.chat();c.input.setPlainText('unsent draft');c.delete()
        QTest.keyClick(c,Qt.Key.Key_Escape);self.assertIsNone(c.confirmation.callback);self.assertEqual(self.pet.bubble.panel_page,'chat')
        QTest.keyClick(c,Qt.Key.Key_Escape);settle(self.pet)
        self.assertEqual(self.pet.bubble.panel_page,'status');self.assertFalse(self.pet.bubble.expanded)
        self.assertEqual(c.input.toPlainText(),'unsent draft')
    def test_first_provider_can_be_saved_without_erasing_entered_fields(self):
        c=self.chat();c.provider();p=c.provider_dialog
        p.fields['name'].setText('First service');p.fields['model'].setText('local-model')
        p.fields['base_url'].setText('http://localhost:1234/v1');p.timeout.setValue(120)
        p.save();self.assertFalse((self.root/'credentials.dpapi.json').exists())
        saved=json.loads((self.root/'chat.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['providers'][0]['model'],'local-model');self.assertEqual(saved['providers'][0]['timeout'],120)
        self.assertEqual(saved['providers'][0]['name'],'First service');self.assertEqual(saved['active'],p.current['id'])


if __name__=='__main__':unittest.main()
