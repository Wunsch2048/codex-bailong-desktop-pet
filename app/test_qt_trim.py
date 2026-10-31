"""Trim both PyInstaller Qt layouts without dropping referenced features."""
import tempfile,unittest,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import package_trim

class TrimTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup);self.imports={}
    def file(self,name,deps=(),delay=()):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
        self.imports[str(p)]=(deps,delay);return p
    def pe(self,path,**kwargs):
        normal,delay=self.imports[path]
        class PE:
            def __enter__(inner):return inner
            def __exit__(inner,*args):pass
            def parse_data_directories(inner,**kwargs):
                inner.DIRECTORY_ENTRY_IMPORT=[SimpleNamespace(dll=x.encode()) for x in normal]
                inner.DIRECTORY_ENTRY_DELAY_IMPORT=[SimpleNamespace(dll=x.encode()) for x in delay]
        return PE()
    def trim(self):
        with patch.object(package_trim.pefile,'PE',side_effect=self.pe):return package_trim.trim_qt(self.root)
    def test_current_and_legacy_qt_layouts_are_trimmed(self):
        self.file('_internal/Qt6Pdf.dll');self.file('_internal/PySide6/Qt6Qml.dll')
        self.file('_internal/python312.dll');self.file('BailongEnhanced.exe')
        result=self.trim();self.assertEqual(len(result['removed']),2)
        self.assertFalse((self.root/'_internal/Qt6Pdf.dll').exists());self.assertTrue((self.root/'_internal/python312.dll').exists())
    def test_kept_regular_and_delay_imports_preserve_transitive_dependencies(self):
        self.file('BailongEnhanced.exe',['Qt6Quick.dll'],['Qt6Pdf.dll'])
        self.file('_internal/Qt6Quick.dll',['Qt6Qml.dll']);self.file('_internal/Qt6Qml.dll',['Qt6QmlModels.dll'])
        self.file('_internal/Qt6QmlModels.dll');self.file('_internal/Qt6Pdf.dll');self.file('_internal/Qt6VirtualKeyboard.dll')
        result=self.trim();self.assertEqual([r['path'] for r in result['removed']],['_internal/Qt6VirtualKeyboard.dll'])
    def test_unreferenced_cycle_is_optional_but_similarly_named_user_files_are_not(self):
        self.file('_internal/Qt6Quick.dll',['Qt6Qml.dll']);self.file('_internal/Qt6Qml.dll',['Qt6Quick.dll'])
        user=self.file('app/Qt6Pdf.dll');other=self.file('_internal/custom/Qt6Pdf.dll')
        self.assertEqual(len(self.trim()['removed']),2);self.assertTrue(user.exists());self.assertTrue(other.exists())

if __name__=='__main__':unittest.main()
