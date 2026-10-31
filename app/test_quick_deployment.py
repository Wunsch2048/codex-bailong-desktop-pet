import os,json,tempfile,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch,Mock,call
from PySide6.QtWidgets import QApplication
import installer
APP=QApplication.instance() or QApplication([])

class QuickDeploymentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.startup=self.root/'Microsoft/Windows/Start Menu/Programs/Startup';self.startup.mkdir(parents=True)
  self.environment=patch.dict(os.environ,{'APPDATA':str(self.root)});self.environment.start()
 def tearDown(self):self.environment.stop();self.tmp.cleanup()
 def existing(self):
  version='0.6.25-test';exe=self.root/'versions'/version/'BailongEnhanced.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'test')
  installer.write_manifest(dict(current=version,versions=[version]),self.root);return exe
 def test_new_install_requires_startup_opt_in_and_upgrade_retains_disabled(self):
  self.assertFalse(installer.startup_preference(self.root));self.existing();self.assertFalse(installer.startup_preference(self.root))
 def test_enabled_startup_is_preserved_and_corrupt_existing_registration_is_repaired(self):
  exe=self.existing();vbs=self.startup/'BailongEnhanced.vbs';vbs.write_text('Set s=CreateObject("WScript.Shell")\ns.Run """'+str(exe)+'""",0,False\n',encoding='utf-16');self.assertTrue(installer.startup_preference(self.root))
  vbs.write_bytes(b'broken');self.assertFalse(installer.startup_preference(self.root));self.assertEqual(vbs.read_bytes(),b'broken')
 def test_maintenance_never_runs_automatic_deployment(self):
  self.assertTrue(installer.quick_mode([],Path('白龙桌宠-一键部署.exe')))
  self.assertTrue(installer.quick_mode(['--quick'],Path('renamed.exe')))
  self.assertFalse(installer.quick_mode(['--manage','--quick'],Path('一键部署.exe')))
  self.assertFalse(installer.quick_mode([],Path('白龙安装管理.exe')))
 def test_deployment_stops_then_installs_then_launches(self):
  events=[];new=self.root/'new/BailongEnhanced.exe'
  def staged(*a,**k):
   events.append(('install',k['startup']));k['before_commit'](new,{});events.append('commit');return new
  with patch('deployment_state.atomic'),patch('deployment_state.wait_ready',side_effect=lambda *a,**k:events.append('ready')),patch.object(installer,'stop_existing',side_effect=lambda r:events.append('stop')),patch.object(installer,'install',side_effect=staged),patch.object(installer.subprocess,'Popen',side_effect=lambda *a,**k:events.append('launch') or Mock(pid=123)):
   self.assertEqual(installer.deploy(Path('payload.zip'),False,self.root),new)
  self.assertEqual(events,['stop',('install',False),'launch','ready','commit'])
 def test_failed_upgrade_restarts_previous_executable(self):
  old=self.root/'old/BailongEnhanced.exe'
  with patch.object(installer,'stop_existing',return_value=old),patch.object(installer,'install',side_effect=OSError('bad payload')),patch.object(installer.subprocess,'Popen') as launch:
   with self.assertRaises(OSError):installer.deploy(Path('payload.zip'),True,self.root)
   launch.assert_called_once();self.assertEqual(launch.call_args.args[0],[str(old)])
   self.assertEqual(launch.call_args.kwargs['cwd'],str(old.parent))
   self.assertEqual(launch.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'],'1')
 def test_unrelated_process_with_same_filename_is_never_stopped(self):
  exe=self.existing();owned=Mock();owned.info={'exe':str(exe)};owned.cmdline.return_value=[str(exe)];other=Mock();other.info={'exe':str(self.root/'unrelated/BailongEnhanced.exe')}
  with patch('psutil.process_iter',return_value=[other,owned]),patch('psutil.wait_procs',return_value=([owned],[])) as wait,patch.object(installer.subprocess,'run') as run:
   self.assertEqual(installer.stop_existing(self.root),exe)
   self.assertEqual(run.call_args.args[0],[str(exe),'--quit']);self.assertEqual(wait.call_args.args[0],[owned])
 def test_unclosed_old_app_prevents_installation(self):
  with patch.object(installer,'stop_existing',side_effect=OSError('still running')),patch.object(installer,'install') as install:
   with self.assertRaises(OSError):installer.deploy(Path('payload.zip'),True,self.root)
   install.assert_not_called()
 def test_lock_collision_reports_failure_without_running_deploy(self):
  lock=Mock();lock.tryLock.return_value=False;lock.isLocked.return_value=False
  with patch.object(installer,'DATA',self.root),patch.object(installer,'QLockFile',return_value=lock),patch.object(installer,'deploy') as deploy:
   job=installer.InstallJob(Path('payload.zip'),True,quick=True);errors=[];job.failed.connect(errors.append);job.run()
   self.assertEqual(len(errors),1);deploy.assert_not_called()
 def test_normal_installer_retains_manual_flow(self):
  lock=Mock();lock.tryLock.return_value=True;lock.isLocked.return_value=True
  with patch.object(installer,'DATA',self.root),patch.object(installer,'QLockFile',return_value=lock),patch.object(installer,'deploy',return_value=Path('installed.exe')) as quick,patch.object(installer,'install') as install:
   job=installer.InstallJob(Path('payload.zip'),False);results=[];job.done.connect(results.append);job.run()
   quick.assert_called_once();install.assert_not_called();self.assertEqual(results,['installed.exe']);lock.unlock.assert_called_once()
 def test_quick_window_starts_automatically_and_preserves_preference(self):
  with patch.object(installer,'read_manifest',return_value={'current':'installed'}),patch.object(installer,'startup_preference',return_value=False),patch.object(installer.QTimer,'singleShot') as schedule:
   window=installer.Installer(quick=True)
   self.assertFalse(window.startup.isChecked());self.assertFalse(window.install_button.isEnabled());self.assertEqual(schedule.call_args.args[0],0)
   window.close();window.deleteLater();APP.processEvents()
 def test_fresh_quick_install_allows_directory_choice_before_start(self):
  with patch.object(installer,'read_manifest',return_value={'current':''}),patch.object(installer,'startup_preference',return_value=False),patch.object(installer.QTimer,'singleShot') as schedule:
   window=installer.Installer(quick=True)
   self.assertTrue(window.install_button.isEnabled());self.assertTrue(window.browse.isEnabled());schedule.assert_not_called()
   window.close();window.deleteLater();APP.processEvents()

 def test_fresh_program_installer_waits_and_passes_explicit_startup_choice(self):
  from program_update_apply import ProgramInstaller
  with patch.object(installer,'read_manifest',return_value={'current':''}),patch.object(installer,'startup_preference',return_value=False),patch.object(installer.QTimer,'singleShot') as schedule,patch('program_update_apply.ProgramApplyJob') as job:
   window=ProgramInstaller(Path('staged-program'))
   schedule.assert_not_called();self.assertFalse(window.startup.isChecked());self.assertFalse(window.startup.isHidden())
   window.startup.setChecked(True);window.start()
   self.assertTrue(job.call_args.kwargs['startup'])
   window.close();window.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
