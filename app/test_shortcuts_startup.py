"""User-facing shortcut routing and companion launch lifecycle regressions."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from desktop import DesktopPet
from desktop_core import normalized
import codex_startup as cs
from quick_actions import website_url

APP=QApplication.instance() or QApplication([])
def settle(pet):
    for _ in range(4):APP.processEvents();pet.bubble.size_transition.complete()
    APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch('enhanced.CONFIG',self.root/'settings.json'),patch('enhanced.STATE_DIR',self.root),
            patch('desktop.CONFIG',self.root/'settings.json'),patch('desktop.STATE_DIR',self.root),
            patch('desktop_settings.autostart_enabled',return_value=False),patch('codex_startup.enabled',return_value=False)]
        for p in self.patches:p.start()
        self.pet=DesktopPet(monitor=False);self.pet.tick.stop();self.pet.motion_timer.stop()
        self.pet.apply_settings(dict(random_actions=False,wandering=False,bubble_mode='mini'),save=False)
        self.pet.show();settle(self.pet)
    def tearDown(self):
        self.pet.close();settle(self.pet)
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def click(self,key):
        self.pet.apply_settings(dict(capsule_action=key),save=False);settle(self.pet)
        self.pet.bubble.shortcut_button.click()
    def test_default_gpt_uses_browser_without_expanding_or_changing_size(self):
        b=self.pet.bubble;size=b.size()
        with patch('desktop.QDesktopServices.openUrl',return_value=True) as opened:
            b.shortcut_button.click()
        self.assertEqual(opened.call_args.args[0].toString(),'https://chatgpt.com/')
        self.assertTrue(b.is_island());self.assertEqual(b.size(),size)
        self.assertEqual(b.shortcut_button.accessibleName(),'GPT 网页')
    def test_local_actions_dispatch_once_to_existing_entry_points(self):
        for key,method in [('codex','open_assistant'),('chat','open_chat'),('settings','open_settings'),('report','open_report')]:
            with self.subTest(key=key),patch.object(self.pet,method) as called:
                self.click(key);called.assert_called_once_with()
    def test_refresh_shortcut_joins_existing_busy_and_result_animation(self):
        b=self.pet.bubble
        with patch.object(b,'refreshAllRequested') as signal:
            self.click('refresh');self.assertTrue(b.shortcut_button.busy);self.assertFalse(b.shortcut_button.isEnabled())
            b.shortcut_button.click();signal.emit.assert_called_once_with()
            b.finish_refresh(False);self.assertTrue(b.shortcut_button.isEnabled());self.assertFalse(b.shortcut_button.result)
    def test_settings_draft_validates_url_and_reloads_saved_choice(self):
        self.pet.open_settings();settle(self.pet);s=self.pet.settings_dialog
        s.shortcut.setCurrentIndex(s.shortcut.findData('website'));s.website.setText('file:///C:/Windows/cmd.exe');s.apply()
        self.assertEqual(self.pet.settings['capsule_action'],'chatgpt');self.assertIn('失败',s.status.text())
        s.website.setText('https://example.org/a?lang=zh');s.apply()
        self.assertFalse(s.draft.dirty);self.assertEqual(self.pet.settings['capsule_action'],'website')
        self.pet.bubble.return_to_status();settle(self.pet)
        with patch('desktop.QDesktopServices.openUrl',return_value=True) as opened:self.pet.bubble.shortcut_button.click()
        self.assertEqual(opened.call_args.args[0].toString(),'https://example.org/a?lang=zh')
        self.assertEqual(json.loads((self.root/'settings.json').read_text(encoding='utf-8'))['capsule_action'],'website')
    def test_codex_link_is_separate_draft_and_failed_registration_stays_dirty(self):
        self.pet.open_settings();settle(self.pet);s=self.pet.settings_dialog
        s.tabs.setCurrentIndex(2)
        s.codex_startup.setChecked(True)
        with patch('codex_startup.configure',side_effect=OSError('denied')):s.apply()
        self.assertIn('codex_startup',s.draft.dirty)
        with patch('codex_startup.configure') as configured:s.apply();configured.assert_called_once_with(True)
        self.assertNotIn('codex_startup',s.draft.dirty);self.assertNotIn('codex_startup',self.pet.settings)

class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,LOCALAPPDATA=str(self.root/'local'),APPDATA=str(self.root/'roaming'));self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_url_and_old_configuration_fallbacks(self):
        for bad in ('javascript:alert(1)','file:///x','cmd.exe','https://name:pw@host','https://host:bad','https://host/\ncmd'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):website_url(bad)
        self.assertEqual(normalized({'capsule_action':'unknown'})['capsule_action'],'chatgpt')
        self.assertEqual(normalized({'capsule_action':'website','capsule_website':'file:///x'})['capsule_action'],'chatgpt')
    def test_gate_does_not_relaunch_after_pet_quit_or_unknown_presence(self):
        gate=cs.LaunchGate();first={(10,123.)}
        self.assertTrue(gate.observe(first))
        for value in (first,None,first,set(),first):self.assertFalse(gate.observe(value))
        self.assertFalse(gate.observe(first|{(20,234.)}));self.assertFalse(gate.observe({(20,234.)}))
        self.assertFalse(gate.observe(set()));self.assertFalse(gate.observe(set()))
        self.assertTrue(gate.observe({(30,345.)}));self.assertFalse(gate.observe({(30,345.)}))
        self.assertTrue(gate.observe({(40,456.)})) # restart entirely between samples
    def test_listener_survives_close_reopen_and_transient_io_failure(self):
        kernel=Mock();kernel.CreateMutexW.return_value=123
        reads=[{(10,1.)},OSError('transient'),set(),set(),{(20,2.)}]
        with patch.object(cs.ctypes,'WinDLL',return_value=kernel),patch.object(cs.ctypes,'get_last_error',return_value=0),patch.object(cs,'enabled',side_effect=[True]*5+[False]),patch.object(cs,'install_root',return_value=self.root),patch.object(cs,'current_command',return_value=['pet.exe']),patch.object(cs,'desktop_sessions',side_effect=reads),patch.object(cs,'spawn') as launch,patch.object(cs.time,'sleep'):
            self.assertEqual(cs.main(),0)
        self.assertEqual(launch.call_count,2)
        self.assertTrue(all(c.args[0]==['pet.exe','--from-codex'] for c in launch.call_args_list))
        state=cs.read_json(cs.data_dir()/'codex-watch-state.json')
        self.assertTrue(state['codex_open']);self.assertNotIn('error',state)
        kernel.CloseHandle.assert_called_once_with(123)
    def test_listener_retries_failed_state_write_without_relaunching_pet(self):
        kernel=Mock();kernel.CreateMutexW.return_value=123
        with patch.object(cs.ctypes,'WinDLL',return_value=kernel),patch.object(cs.ctypes,'get_last_error',return_value=0),patch.object(cs,'enabled',side_effect=[True,True,False]),patch.object(cs,'install_root',return_value=self.root),patch.object(cs,'current_command',return_value=['pet.exe']),patch.object(cs,'desktop_sessions',return_value={(10,1.)}),patch.object(cs,'spawn') as launch,patch.object(cs,'atomic',side_effect=[OSError('locked'),None]) as write,patch.object(cs.time,'sleep'):
            self.assertEqual(cs.main(),0)
        self.assertEqual(write.call_count,2);launch.assert_called_once()
    def test_desktop_detector_excludes_cli_chatgpt_only_and_helpers(self):
        def process(pid,path,args):
            p=Mock(pid=pid,info={'name':Path(path).name});p.exe.return_value=path;p.cmdline.return_value=args;p.create_time.return_value=100.;return p
        gui=str(self.root/'OpenAI.Codex_123/app/ChatGPT.exe');cli=str(self.root/'OpenAI/Codex/bin/123/codex.exe');chat=str(self.root/'OpenAI.ChatGPT_123/ChatGPT.exe')
        values=[process(1,gui,[gui]),process(2,gui,[gui,'--type=renderer']),process(3,cli,[cli]),process(4,chat,[chat])]
        with patch.object(cs.psutil,'process_iter',return_value=values):self.assertEqual(cs.desktop_sessions(),{(1,100.)})
        values[0].exe.side_effect=cs.psutil.AccessDenied(1)
        with patch.object(cs.psutil,'process_iter',return_value=values):self.assertIsNone(cs.desktop_sessions())
    def test_enable_disable_registration_and_failed_spawn_are_reversible(self):
        exe=self.root/'versions/0.8.1-test/BailongEnhanced.exe'
        with patch.object(cs,'spawn') as launch:
            cs.configure(True,exe);self.assertTrue(cs.enabled());self.assertIn('--watch-codex',__import__('windows_entries').read_shortcut(cs.startup_path())['arguments'])
            launch.assert_called_once_with([str(exe),'--watch-codex'])
            cs.configure(False,exe);self.assertFalse(cs.enabled());self.assertFalse(cs.startup_path().exists())
        before=cs.preference_path().read_bytes()
        with patch.object(cs,'spawn',side_effect=OSError('denied')),self.assertRaises(OSError):cs.configure(True,exe)
        self.assertEqual(cs.preference_path().read_bytes(),before);self.assertFalse(cs.startup_path().exists())
    def test_registration_follows_upgrade_and_disables_incompatible_rollback_entry(self):
        cs.atomic(cs.preference_path(),{'enabled':True})
        cs.register(self.root/'versions/0.8.1-test/BailongEnhanced.exe')
        cs.register(self.root/'versions/0.8.2-test/BailongEnhanced.exe')
        self.assertIn('0.8.2-test',__import__('windows_entries').read_shortcut(cs.startup_path())['target'])
        cs.register(self.root/'versions/0.8.0-test/BailongEnhanced.exe');self.assertFalse(cs.startup_path().exists())
    def test_launch_drops_stale_installer_nonce(self):
        with patch.dict(os.environ,BAILONG_DEPLOY_TOKEN='private',BAILONG_DEPLOY_RECEIPT='old'),patch.object(cs.subprocess,'Popen') as launch:
            cs.spawn(['pet.exe','--from-codex'])
        self.assertNotIn('BAILONG_DEPLOY_TOKEN',launch.call_args.kwargs['env']);self.assertNotIn('BAILONG_DEPLOY_RECEIPT',launch.call_args.kwargs['env'])
    def test_corrupt_preference_does_not_crash_startup_or_enable_it(self):
        cs.atomic(cs.preference_path(),['enabled'])
        self.assertFalse(cs.enabled())
    def test_stop_watchers_never_stops_gui_or_unrelated_same_name(self):
        root=cs.install_root();version='0.8.1-test';exe=root/'versions'/version/'BailongEnhanced.exe'
        cs.atomic(root/'installations.json',dict(current=version,versions=[version]))
        watcher=Mock(info={'exe':str(exe)});watcher.cmdline.return_value=[str(exe),'--watch-codex']
        gui=Mock(info={'exe':str(exe)});gui.cmdline.return_value=[str(exe)]
        unrelated=Mock(info={'exe':str(self.root/'other/BailongEnhanced.exe')});unrelated.cmdline.return_value=['other','--watch-codex']
        with patch.object(cs.psutil,'process_iter',return_value=[watcher,gui,unrelated]),patch.object(cs.psutil,'wait_procs',return_value=([watcher],[])):
            cs.stop_watchers(root)
        watcher.terminate.assert_called_once();gui.terminate.assert_not_called();unrelated.terminate.assert_not_called()

if __name__=='__main__':unittest.main()
