"""检查源码验证入口实际运行了指定用例，而不是发现其他目录"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import check_source


class SourceChecksTests(unittest.TestCase):
    def test_only_requested_case_runs_and_unknown_case_fails(self):
        """未选择的失败用例不能被执行，不存在的用例不能误报成功"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'app').mkdir()
            (root / 'app/settings_controls.py').write_text('def _system_motion_enabled(): return True\n')
            (root / 'test_scope.py').write_text('import unittest\nclass Scope(unittest.TestCase):\n def test_selected(self): pass\n def test_unselected(self): self.fail("wrong selection")\n')
            with patch.object(check_source, 'ROOT', root):
                selected = check_source.run('test_scope.Scope.test_selected')
                self.assertEqual((selected['returncode'], selected['tests']), (0, 1), selected)
                missing = check_source.run('test_scope.Scope.test_missing')
                self.assertNotEqual(missing['returncode'], 0)

    def test_empty_suite_and_import_failure_are_rejected(self):
        """零用例和模块导入失败都不能成为成功记录，tools 目录也须可导入"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'app').mkdir()
            (root / 'tools').mkdir()
            (root / 'app/settings_controls.py').write_text('def _system_motion_enabled(): return True\n')
            (root / 'tools/test_empty.py').write_text('import unittest\n')
            (root / 'tools/test_broken.py').write_text('raise RuntimeError("import failed")\n')
            with patch.object(check_source, 'ROOT', root):
                empty = check_source.run('test_empty')
                self.assertEqual((empty['returncode'], empty['tests']), ('no_tests', 0), empty)
                broken = check_source.run('test_broken')
                self.assertNotEqual(broken['returncode'], 0)
                self.assertIn('import failed', broken['failure'])
