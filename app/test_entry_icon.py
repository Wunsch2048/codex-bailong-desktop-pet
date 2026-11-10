"""Real native Shell links; never launch an interpreter or an entry target."""
import os,sys,tempfile,unittest,threading
from pathlib import Path
from unittest.mock import patch
from windows_entries import write_shortcut,read_shortcut,install_entries,startup_entry,legacy_command

class StartupStagingTests(unittest.TestCase):
 def test_startup_replacement_failure_never_stages_inside_startup(self):
  path=Path('Programs/Startup/auto.lnk').absolute()
  with patch('windows_entries._plain',side_effect=lambda p:Path(p).absolute()),patch.object(Path,'mkdir'),patch.object(Path,'exists',return_value=False),patch.object(Path,'unlink') as remove,patch('windows_entries.legacy_command',return_value=None),patch('windows_entries._link_action'),patch('windows_entries.os.replace',side_effect=PermissionError('locked')) as replace:
   with self.assertRaisesRegex(PermissionError,'locked'):
    startup_entry(path,path.with_suffix('.vbs'),[str(Path(sys.executable))],True)
  staged,target=replace.call_args.args
  self.assertEqual(target,path);self.assertEqual(staged.parent,path.parent.parent)
  remove.assert_called_once_with(missing_ok=True)

@unittest.skipUnless(sys.platform=='win32','Windows shell shortcuts')
class EntryIconTests(unittest.TestCase):
 def test_replaces_arguments_and_icon_in_chinese_path_without_shell_process(self):
  with tempfile.TemporaryDirectory(prefix='bailong-entry-') as folder:
   root=Path(folder)/"中文 空格's";root.mkdir();link=root/'nested/白龙.lnk'
   exe=Path(os.environ['WINDIR'])/'System32/notepad.exe'
   with patch('subprocess.run',side_effect=AssertionError('No shell')),patch('subprocess.Popen',side_effect=AssertionError('No process')):
    write_shortcut(link,exe,'--quit');write_shortcut(link,exe);data=read_shortcut(link)
   self.assertEqual(data['arguments'],'');self.assertEqual(data['target'].casefold(),str(exe).casefold())
   self.assertEqual(data['icon'].casefold(),str(exe).casefold());self.assertEqual(data['iconIndex'],0)
   self.assertEqual(data['cwd'].casefold(),str(exe.parent).casefold())
 def test_upgrade_preserves_unrelated_links_and_retires_only_owned_alias(self):
  with tempfile.TemporaryDirectory(prefix='bailong-alias-') as folder:
   base=Path(folder)/'BailongEnhanced';old=base/'versions/old/BailongEnhanced.exe';new=base/'versions/new/BailongEnhanced.exe'
   desktop=Path(folder)/'Desktop';menu=Path(folder)/'Programs';desktop.mkdir();menu.mkdir()
   alias=desktop/'白龙桌宠.lnk';other=desktop/'OtherPet.lnk';write_shortcut(alias,old);write_shortcut(other,Path(sys.executable));before=other.read_bytes()
   install_entries(new,desktop,menu)
   self.assertEqual(Path(read_shortcut(desktop/'白龙桌宠增强版.lnk')['target']),new)
   self.assertEqual(Path(read_shortcut(menu/'白龙桌宠增强版.lnk')['target']),new)
   self.assertFalse(alias.exists());self.assertEqual(other.read_bytes(),before)
 def test_save_error_is_propagated(self):
  with tempfile.TemporaryDirectory() as folder:
   blocker=Path(folder)/'file';blocker.write_text('blocked')
   with self.assertRaises(OSError):write_shortcut(blocker/'bad.lnk',Path(sys.executable))
 def test_worker_thread_owns_com_apartment(self):
  with tempfile.TemporaryDirectory() as folder:
   link=Path(folder)/'worker.lnk';errors=[]
   def worker():
    try:write_shortcut(link,Path(sys.executable),'--worker');self.assertEqual(read_shortcut(link)['arguments'],'--worker')
    except Exception as error:errors.append(error)
   thread=threading.Thread(target=worker);thread.start();thread.join(5)
   self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
 def test_startup_migrates_known_script_and_preserves_foreign_script(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);old=root/'versions/old/BailongEnhanced.exe';new=root/'versions/new/BailongEnhanced.exe';link=root/'auto.lnk';vbs=root/'BailongEnhanced.vbs'
   vbs.write_text('Set s=CreateObject("WScript.Shell")\ns.Run """'+str(old)+'""",0,False\n',encoding='utf-16')
   self.assertEqual(legacy_command(vbs),[str(old)])
   startup_entry(link,vbs,[str(new)],True);self.assertFalse(vbs.exists());self.assertEqual(Path(read_shortcut(link)['target']),new)
   vbs.write_text('MsgBox "unrelated"',encoding='utf-16');before=vbs.read_bytes()
   startup_entry(link,vbs,[str(new)],False);self.assertFalse(link.exists());self.assertEqual(vbs.read_bytes(),before)
 def test_foreign_named_startup_link_is_not_overwritten(self):
  with tempfile.TemporaryDirectory() as folder:
   link=Path(folder)/'auto.lnk';write_shortcut(link,Path(sys.executable));before=link.read_bytes()
   with self.assertRaises(OSError):startup_entry(link,link.with_suffix('.vbs'),[str(Path(folder)/'versions/new/BailongEnhanced.exe')],True)
   self.assertEqual(link.read_bytes(),before)

if __name__=='__main__':unittest.main()
