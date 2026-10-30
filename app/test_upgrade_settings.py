"""Simulated other-machine upgrades; no real installation or user settings."""
import copy,hashlib,json,os,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch,Mock
from desktop_core import DEFAULTS,VERSION,normalized,atomic_json
from quick_actions import ACTIONS
from theme_registry import NAMES

KEYS=('capsule_action','capsule_website','bubble_mode','theme','theme_accent','theme_surface','theme_ink',
      'panel_detached','card_anchor','ui_animation_mode','move_range','status_action_interval','wandering',
      'wander_mode','wander_zone','wander_horizontal_only','edge_docking','quota_decline_threshold','quota_increase_threshold','bubble','character_visible')


def preferences(mode='minimal',action='website',theme='cyber'):
    return dict(schema=2,bubble_mode=mode,capsule_action=action,capsule_website='https://example.org/my-shortcut',
        theme=theme,theme_accent='#de3570',theme_surface='#181c23',theme_ink='#eeeeee',bubble=True,character_visible=True,
        panel_detached=True,card_anchor=dict(screen='another-monitor',rx=.23,bottom=.67),ui_animation_mode='performance',
        move_range=.75,status_action_interval=18,wandering=False,wander_mode='zone',wander_zone=[.1,.6,.8,.95],
        wander_horizontal_only=False,edge_docking=False,quota_decline_threshold=12,quota_increase_threshold=17,
        future_setting=dict(keep='other-machine'))


class UpgradeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def assert_preferences(self,raw,value):
        for key in KEYS:self.assertEqual(value.get(key),raw.get(key),key)
        self.assertEqual(value['future_setting'],raw['future_setting'])
    def test_valid_choices_and_values_equal_to_old_defaults_survive_normalization(self):
        for mode in ('auto','mini','minimal'):
            for action,_,_ in ACTIONS:
                for theme in NAMES:
                    for detached in (False,True):
                        with self.subTest(mode=mode,action=action,theme=theme,detached=detached):
                            raw=preferences(mode,action,theme);raw['panel_detached']=detached
                            value=normalized(raw);self.assert_preferences(raw,value)
                            self.assertEqual(normalized(value),value);self.assertEqual(raw['move_range'],.75)
        self.assertEqual(normalized({})['move_range'],DEFAULTS['move_range'])
        self.assertEqual(normalized({})['status_action_interval'],DEFAULTS['status_action_interval'])
    def source(self):
        source=self.root/'source';source.mkdir();records={}
        # Even a differently configured package lives under the version, not DATA.
        for name,content in [('BailongEnhanced.exe',b'isolated-placeholder'),('settings.json',json.dumps(dict(theme='teal',bubble_mode='auto',capsule_action='chatgpt')).encode())]:
            (source/name).write_bytes(content);records[name]=dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
        (source/'payload-manifest.json').write_text(json.dumps(dict(version=VERSION,files=records)),encoding='utf-8')
        return source
    def deploy(self,directory=False):
        import installer,directory_deploy,deployment_state
        source=self.source();data=self.root/'other-machine-data';data.mkdir()
        raw=preferences();config=data/'settings.json';atomic_json(config,raw);before=config.read_bytes()
        root=self.root/'other-machine-install';old=root/'versions/old/BailongEnhanced.exe';old.parent.mkdir(parents=True);old.write_bytes(b'old')
        installer.write_manifest(dict(current='old',versions=['old']),root)
        payload=self.root/'payload.zip'
        with zipfile.ZipFile(payload,'w') as archive:
            for p in source.iterdir():archive.write(p,p.name)
        def ready(process,exe,*args):
            self.assertEqual(config.read_bytes(),before)
            self.assert_preferences(raw,normalized(json.loads(config.read_text(encoding='utf-8'))))
            return dict(version=VERSION,pid=321,windowReady=True,serverReady=True)
        options=dict(populate=lambda dest:directory_deploy.populate_directory(source,dest,VERSION)) if directory else {}
        with patch.object(installer,'stop_existing',return_value=old),patch('process_launch.launch_own',return_value=Mock(pid=321)),patch.object(deployment_state,'wait_ready',side_effect=ready):
            exe=installer.deploy(None if directory else payload,False,root=root,data_root=data,system=False,**options)
        self.assertEqual(config.read_bytes(),before);self.assertTrue(old.is_file());self.assertTrue(exe.is_file())
        backups=list((root/'deployment-backups').iterdir());self.assertEqual(len(backups),1)
        self.assertEqual((backups[0]/'settings.json').read_bytes(),before)
        # Exercise actual verified restoration without creating extra files that
        # would need deleting. This is not a full failed-process recovery test.
        atomic_json(config,dict(theme='bailong',bubble_mode='auto'))
        directory_deploy.restore_data(data,backups[0],root)
        self.assertEqual(config.read_bytes(),before)
    def test_public_zip_upgrade_and_backup_preserve_other_machine_settings(self):self.deploy()
    def test_program_directory_upgrade_and_backup_preserve_other_machine_settings(self):self.deploy(True)
    def test_actual_application_start_close_retains_shortcut_mode_and_theme(self):
        from PySide6.QtWidgets import QApplication
        import desktop,enhanced
        app=QApplication.instance() or QApplication([])
        for number,(mode,action,theme) in enumerate([('minimal','website','cyber'),('mini','settings','bailong'),('auto','report','custom')]):
            data=self.root/str(number);data.mkdir();raw=preferences(mode,action,theme);config=data/'settings.json';atomic_json(config,raw)
            with patch.object(desktop,'STATE_DIR',data),patch.object(desktop,'CONFIG',config),patch.object(enhanced,'STATE_DIR',data),patch.object(enhanced,'CONFIG',config),patch('codex_startup.enabled',return_value=False):
                pet=desktop.DesktopPet(monitor=False)
                try:
                    pet.tick.stop();pet.motion_timer.stop()
                    self.assert_preferences(raw,pet.settings)
                    self.assertEqual(pet.bubble.bubble_mode,mode);self.assertEqual(pet.bubble.capsule_action,action)
                finally:pet.close();app.processEvents()
                saved=json.loads(config.read_text(encoding='utf-8'));self.assert_preferences(raw,saved)
    def test_unavailable_resources_do_not_overwrite_saved_visibility_or_shortcuts(self):
        from PySide6.QtWidgets import QApplication
        import desktop,enhanced,material_store
        from types import SimpleNamespace
        app=QApplication.instance() or QApplication([]);real=material_store.MaterialStore
        def missing(*args,**kwargs):
            store=real(*args,**kwargs);store.current=None;return store
        for shown in (False,True):
            data=self.root/str(shown);data.mkdir();raw=preferences();raw['bubble']=shown
            config=data/'settings.json';atomic_json(config,raw)
            with patch.object(desktop,'STATE_DIR',data),patch.object(desktop,'CONFIG',config),patch.object(enhanced,'STATE_DIR',data),patch.object(enhanced,'CONFIG',config),patch.object(material_store,'MaterialStore',side_effect=missing),patch('codex_startup.enabled',return_value=False):
                pet=desktop.DesktopPet(monitor=False)
                try:
                    pet.tick.stop();pet.motion_timer.stop();self.assertTrue(pet._materials_missing)
                    self.assert_preferences(raw,pet.settings);self.assertFalse(pet.isVisible())
                    self.assertEqual(pet.bubble.isVisible(),shown)
                    # A subsequent unrelated save must not persist a fallback.
                    pet.apply_settings(dict(sound=False));self.assert_preferences(raw,pet.settings)
                    with patch.object(pet,'apply_material',return_value=True) as apply:
                        pet.queue_material('light',Path('not-read'));apply.assert_called_once()
                        pet._pending_material=None
                finally:pet.close();app.processEvents()
                self.assert_preferences(raw,json.loads(config.read_text(encoding='utf-8')))

if __name__=='__main__':unittest.main()
