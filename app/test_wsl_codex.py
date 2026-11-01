import io,json,os,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import wsl_codex as wsl
import codex_connection as connection

PROFILE=dict(source='wsl',home='',cli='',wsl_distro='Ubuntu',wsl_user='alice',wsl_home='/home/alice/.codex',wsl_cli='/home/alice/.nvm/versions/node/v22/bin/codex',wsl_path='/home/alice/.nvm/versions/node/v22/bin:/usr/local/bin:/usr/bin:/bin')

class WslCodexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);wsl._cache.clear()
    def tearDown(self):self.temp.cleanup();wsl._cache.clear()
    def test_distribution_decode_and_list_never_start_or_install_a_distro(self):
        done=SimpleNamespace(returncode=0,stdout='Ubuntu\r\nDebian\r\n'.encode('utf-16-le'))
        with patch('wsl_codex.executable',return_value='wsl.exe'),patch('wsl_codex.subprocess.run',return_value=done) as run:
            self.assertEqual(wsl.distributions(),['Ubuntu','Debian'])
            self.assertEqual(run.call_args.args[0],['wsl.exe','--list','--quiet'])
            self.assertEqual(wsl.distributions(True),['Ubuntu','Debian'])
            self.assertEqual(run.call_args.args[0],['wsl.exe','--list','--running','--quiet'])
    def test_unavailable_wsl_is_clear_and_never_falls_back_to_windows(self):
        with patch('wsl_codex.executable',return_value='wsl.exe'),patch('wsl_codex.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=b'')):
            with self.assertRaises(wsl.WslError):wsl.distributions()
        with patch('codex_connection.saved_paths',return_value=PROFILE),patch('wsl_codex.running',return_value=False),patch.object(Path,'is_dir',side_effect=AssertionError('UNC access')):
            result=connection.check_connection()
            self.assertEqual(result['source'],'wsl');self.assertFalse(result['quota_read']);self.assertEqual(result['capabilities']['tasks']['code'],'wsl_stopped')
    def test_unc_home_keeps_linux_case_and_never_resolves_network_on_ui_startup(self):
        a=wsl.unc('Ubuntu','/home/Alice/.codex');b=wsl.unc('Ubuntu','/home/alice/.codex')
        self.assertNotEqual(wsl.identity(a),wsl.identity(b))
        self.assertEqual(wsl.identity(a),wsl.identity(a.replace('wsl$','wsl.localhost')))
        with patch('codex_connection.saved_paths',return_value=PROFILE),patch.object(Path,'resolve',side_effect=AssertionError('network resolve')):
            self.assertEqual(str(connection.data_home()),b)
            self.assertEqual(connection.source_identity(connection.data_home()),'wsl:ubuntu:/home/alice/.codex')
    def test_windows_environment_does_not_override_or_leak_into_wsl_codex_home(self):
        with patch('codex_connection.saved_paths',return_value=PROFILE),patch.dict(os.environ,{'CODEX_HOME':r'C:\WindowsUser\.codex','BAILONG_CODEX_HOME':r'C:\Other'}):
            before=dict(os.environ)
            self.assertEqual(str(connection.data_home()),wsl.unc('Ubuntu','/home/alice/.codex'))
            self.assertNotIn('CODEX_HOME',connection.child_environment());self.assertEqual(dict(os.environ),before)
    def test_positional_arguments_keep_spaces_and_shell_characters_out_of_script(self):
        profile=dict(PROFILE,wsl_home='/home/alice space/$(echo bad)/.codex')
        with patch('wsl_codex.executable',return_value='wsl.exe'),patch('wsl_codex.running',return_value=True):
            command=wsl.command(profile,'resume','123')
        script=command[command.index('-lc')+1]
        self.assertNotIn(profile['wsl_home'],script);self.assertIn(profile['wsl_home'],command)
        self.assertEqual(command[-3:],[profile['wsl_cli'],'resume','123'])
        with self.assertRaises(ValueError):wsl.unc('Ubuntu','../../Windows')
        with self.assertRaises(ValueError):wsl.unc('../Ubuntu','/home/alice/.codex')
    def test_validation_probes_linux_user_home_cli_and_node_path_in_background(self):
        probe=('__BAILONG_USER=alice\n__BAILONG_HOME=/home/alice/.codex\n__BAILONG_CLI='+PROFILE['wsl_cli']+'\n__BAILONG_PATH='+PROFILE['wsl_path']+'\n__BAILONG_READABLE=1\n').encode()
        results=[SimpleNamespace(returncode=0,stdout='Ubuntu\n'.encode('utf-16-le')),SimpleNamespace(returncode=0,stdout=probe),SimpleNamespace(returncode=0,stdout=b'codex-cli 0.100.0\n')]
        with patch('wsl_codex.executable',return_value='wsl.exe'),patch('wsl_codex.subprocess.run',side_effect=results) as run,patch('wsl_codex.verify_share') as share,patch.dict(os.environ,{'CODEX_HOME':r'C:\native'}):
            result=connection.validate_paths(dict(PROFILE,wsl_user='',wsl_home='',wsl_cli=''))
            self.assertEqual(result['wsl_home'],PROFILE['wsl_home']);self.assertEqual(result['wsl_user'],'alice');self.assertEqual(result['wsl_cli'],PROFILE['wsl_cli'])
            self.assertNotIn('CODEX_HOME',run.call_args_list[1].kwargs['env'])
            self.assertEqual(run.call_args_list[-1].args[0][-1],'--version')
            share.assert_called_once_with('Ubuntu',PROFILE['wsl_home'])
    def test_unreadable_windows_share_cannot_report_successful_import(self):
        with patch.object(Path,'is_dir',return_value=False):
            with self.assertRaisesRegex(ValueError,'Windows 无法读取'):wsl.verify_share('Ubuntu',PROFILE['wsl_home'])
    def test_no_linux_cli_is_actionable_and_cannot_import_windows_exe(self):
        for cli in ('','/mnt/c/tools/codex.exe'):
            probe=f'__BAILONG_USER=alice\n__BAILONG_HOME=/home/alice/.codex\n__BAILONG_CLI={cli}\n__BAILONG_READABLE=1\n'.encode()
            with patch('wsl_codex.distributions',return_value=['Ubuntu']),patch('wsl_codex.executable',return_value='wsl.exe'),patch('wsl_codex.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=probe)):
                with self.assertRaisesRegex(ValueError,'Linux Codex CLI'):connection.validate_paths(PROFILE)
    def test_quota_protocol_uses_linux_cli_without_windows_account_credentials(self):
        import quota
        result=dict(rateLimits=dict(primary=dict(usedPercent=12,windowDurationMins=10080,resetsAt=1800000000)))
        process=SimpleNamespace(stdin=io.StringIO(),stdout=io.StringIO(json.dumps(dict(id=1,result={}))+'\n'+json.dumps(dict(id=2,result=result))+'\n'),poll=lambda:0,wait=lambda timeout:0,terminate=Mock(),kill=Mock())
        with patch('codex_connection.saved_paths',return_value=PROFILE),patch('wsl_codex.executable',return_value='wsl.exe'),patch('wsl_codex.running',return_value=True),patch('quota.subprocess.Popen',return_value=process) as popen:
            self.assertEqual(quota._read_quota_once(),result)
            args=popen.call_args.args[0];self.assertEqual(args[-2:],[PROFILE['wsl_cli'],'app-server']);self.assertIn(PROFILE['wsl_home'],args)
            self.assertNotIn('CODEX_HOME',popen.call_args.kwargs['env'])
    def test_wsl_history_and_notifications_do_not_share_windows_or_other_user_counters(self):
        from token_calendar import TokenUsageIndex
        a=wsl.unc('Ubuntu','/home/Alice/.codex');b=wsl.unc('Ubuntu','/home/alice/.codex')
        first=TokenUsageIndex(self.root/'token.sqlite3',a);second=TokenUsageIndex(self.root/'token.sqlite3',b)
        self.assertNotEqual(first.path,second.path)
        self.assertNotEqual(wsl.state_dir(self.root,a),wsl.state_dir(self.root,b))
        with patch.object(Path,'is_file',side_effect=AssertionError('native DB read')):
            self.assertTrue(first.import_legacy(None))
        self.assertEqual(wsl.state_dir(self.root,self.root/'native'),self.root)
    def test_wsl_never_reads_windows_ipc_or_desktop_sqlite_receipts(self):
        from session_read_state import read_tracking_probe,subagent_sessions
        home=wsl.unc('Ubuntu',PROFILE['wsl_home'])
        with patch('sqlite3.connect',side_effect=AssertionError('cross-platform SQLite read')):
            self.assertEqual(read_tracking_probe(home)['code'],'wsl_logs_only');self.assertEqual(subagent_sessions(home,['x']),set())
        with patch('codex_connection.is_wsl_source',return_value=True):
            from desktop_services import codex_desktop_open
            self.assertIsNone(codex_desktop_open())
    def test_corrupt_wsl_profile_fails_closed_without_blocking_settings(self):
        with patch('codex_connection.saved_paths',return_value={'source':'wsl'}),patch.object(Path,'resolve',side_effect=AssertionError('network resolve')):
            home=connection.data_home();self.assertTrue(connection.is_wsl_source(home))
            self.assertIn('Invalid-Bailong-Profile',str(home))
    def test_session_jump_opens_linux_resume_in_terminal_without_native_deep_link(self):
        from desktop_services import open_codex
        sid='12345678-1234-4234-8234-123456789abc'
        with patch('codex_connection.saved_paths',return_value=PROFILE),patch('wsl_codex.running',return_value=True),patch('wsl_codex.executable',return_value='wsl.exe'),patch('desktop_services.shutil.which',return_value='wt.exe'),patch('desktop_services.subprocess.Popen') as popen,patch('os.startfile',create=True) as native:
            open_codex(sid);native.assert_not_called();self.assertEqual(popen.call_args.args[0][-3:],[PROFILE['wsl_cli'],'resume',sid])
    def test_stopped_source_does_not_scan_unc_or_start_native_live_reader(self):
        from enhanced import ActivityThread
        with patch('enhanced.STATE_DIR',self.root),patch('codex_connection.saved_paths',return_value=PROFILE):thread=ActivityThread(home=wsl.unc('Ubuntu',PROFILE['wsl_home']))
        with patch('wsl_codex.running',return_value=False),patch('codex_live_status.LiveStatusReader') as native,patch.object(thread.tail,'poll') as poll,patch.object(thread.stop,'wait',side_effect=lambda seconds:thread.stop.set()):
            thread.run();native.assert_not_called();poll.assert_not_called()
        self.assertFalse(thread.live_reader.connected)
    def test_stopped_token_refresh_finishes_and_does_not_read_unc(self):
        from enhanced import ActivityThread
        with patch('enhanced.STATE_DIR',self.root),patch('codex_connection.saved_paths',return_value=PROFILE):thread=ActivityThread(home=wsl.unc('Ubuntu',PROFILE['wsl_home']))
        events=[];thread.event.connect(events.append)
        with patch('wsl_codex.running',return_value=False),patch.object(thread.token_index,'poll') as poll:
            thread.read_tokens();poll.assert_not_called()
        self.assertTrue(any(e['kind']=='token_usage_error' for e in events))
        self.assertTrue(any(e['kind']=='token_busy' and not e['busy'] for e in events))
    def test_saved_source_is_frozen_until_restart_and_preserves_native_profile(self):
        with patch.dict(os.environ,{'LOCALAPPDATA':str(self.root),'CODEX_HOME':'','BAILONG_CODEX_HOME':''}),patch('codex_connection.user_environment',return_value=''):
            connection._saved_paths.cache_clear();before=connection.data_home()
            connection.save_paths(dict(PROFILE,home=r'C:\native-data',cli=r'C:\native\codex.exe'))
            self.assertEqual(connection.data_home(),before)
            connection._saved_paths.cache_clear()
            self.assertEqual(str(connection.data_home()),wsl.unc('Ubuntu',PROFILE['wsl_home']))
            self.assertEqual(connection.saved_paths()['home'],r'C:\native-data')
            self.assertEqual(connection.saved_paths()['cli'],r'C:\native\codex.exe')
        connection._saved_paths.cache_clear()
    def test_wsl_source_never_exits_when_windows_codex_closes(self):
        from desktop import DesktopPet
        from codex_startup import ExitGate
        fake=SimpleNamespace(settings=dict(codex_exit=True),_codex_polling=False,_codex_closing=False,_codex_exit_gate=ExitGate())
        with patch('codex_connection.is_wsl_source',return_value=True),patch('threading.Thread') as launch:
            DesktopPet.poll_codex_presence(fake);launch.assert_not_called()

class WslSettingsTests(unittest.TestCase):
    import test_second_batch as fixtures
    setUp=fixtures.VisualInteractionTests.setUp
    tearDown=fixtures.VisualInteractionTests.tearDown
    settings=fixtures.VisualInteractionTests.settings
    def source_settings(self):
        from PySide6.QtWidgets import QApplication
        s=self.settings();s.tabs.setCurrentIndex(2);QApplication.processEvents();s.path_toggle.setChecked(True)
        s.path_source.setCurrentIndex(s.path_source.findData('wsl'));QApplication.processEvents();return s
    def finish(self,s):
        import time
        from PySide6.QtTest import QTest
        deadline=time.monotonic()+3
        while s.path_job and s.path_job.isRunning() and time.monotonic()<deadline:QTest.qWait(10)
        QTest.qWait(20);self.assertFalse(s.path_job.isRunning())
    def test_source_choice_hides_native_file_pickers_and_keeps_linux_fields(self):
        s=self.source_settings()
        self.assertEqual(s.path_values()['source'],'wsl');self.assertFalse(s.wsl_body.isHidden())
        self.assertTrue(all(row.isHidden() for row in s.native_path_rows))
        self.assertEqual(set(s.wsl_fields),{'wsl_user','wsl_home','wsl_cli'})
    def test_missing_wsl_reports_error_and_keeps_configuration_unchanged(self):
        s=self.source_settings()
        with patch('wsl_codex.distributions',side_effect=wsl.WslError('WSL 尚未安装完成')),patch('codex_connection.save_paths') as save:
            s.refresh_wsl_sources();self.finish(s)
        self.assertIn('WSL',s.path_status.text());save.assert_not_called();self.assertTrue(s.wsl_refresh.isEnabled())
    def test_validated_linux_profile_is_saved_without_native_file_dialog(self):
        s=self.source_settings();s.wsl_distro.clear();s.wsl_distro.addItem('Ubuntu','Ubuntu')
        def validated(values):return dict(values,**{key:value for key,value in PROFILE.items() if key.startswith('wsl_')})
        with patch('codex_connection.validate_paths',side_effect=validated),patch('codex_connection.save_paths') as save:
            s.validate_paths();self.finish(s)
        self.assertEqual(save.call_args.args[0]['source'],'wsl');self.assertEqual(s.wsl_fields['wsl_cli'].text(),PROFILE['wsl_cli'])
        self.assertIn('重启',s.path_status.text())

if __name__=='__main__':unittest.main()
