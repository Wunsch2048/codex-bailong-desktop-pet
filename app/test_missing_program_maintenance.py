"""A quarantined/missing program must not prevent opening recovery controls."""
import os,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
import installer

APP=QApplication.instance() or QApplication([])

class MissingProgramTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve();self.root=self.base/'install'
        self.current='1.3.0-20261031-000000';self.previous='1.2.1-20261030-000000'
        (self.root/'versions'/self.current).mkdir(parents=True)
        self.old=self.root/'versions'/self.previous;self.old.mkdir()
        (self.old/'BailongEnhanced.exe').write_bytes(b'non-executable test fixture')
        self.manifest=dict(current=self.current,versions=[self.current,self.previous])
        (self.root/'installations.json').write_text(json.dumps(self.manifest),encoding='utf-8')
        self.env=patch.dict(os.environ,APPDATA=str(self.base/'roaming'));self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_missing_exe_still_reads_startup_setting_but_cannot_execute(self):
        self.assertFalse(installer.startup_preference(self.root))
        folder=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup';folder.mkdir(parents=True)
        (folder/'白龙桌宠增强版.lnk').write_bytes(b'non-executable shortcut fixture')
        expected=[str(self.root/'versions'/self.current/'BailongEnhanced.exe')]
        with patch('windows_entries.command_matches',return_value=True) as check:
            self.assertTrue(installer.startup_preference(self.root));self.assertEqual(check.call_args.args[1],expected)
        with self.assertRaisesRegex(ValueError,'安装版本目录无效'):installer.checked_version(self.root,self.current)
        self.assertEqual(installer.checked_version(self.root,self.previous),self.old)
    def test_preference_path_safety_is_not_relaxed(self):
        for name in ('../../outside','../versions-other','',str(self.base/'outside')):
            with patch('installer.read_manifest',return_value=dict(current=name,versions=[])):
                if not name:self.assertFalse(installer.startup_preference(self.root))
                else:
                    with self.assertRaises((ValueError,OSError)):installer.startup_preference(self.root)
    def test_maintenance_window_opens_with_rollback_controls_and_missing_current(self):
        original=installer.startup_preference
        with patch('installer.ROOT',self.root),patch('installer.read_manifest',return_value=self.manifest),patch('installer.startup_preference',side_effect=lambda:original(self.root)):
            window=installer.Installer(maintenance=True)
            try:
                window.show();APP.processEvents()
                self.assertTrue(window.isVisible());self.assertFalse(window.install_button.isVisible())
                self.assertTrue(any('回退' in b.text() and b.isEnabled() for b in window.maintenance_buttons))
            finally:window.close();APP.processEvents()

if __name__=='__main__':unittest.main()
