import json,sys,tempfile,unittest,importlib,os
from pathlib import Path
from unittest.mock import MagicMock,patch
import quota,cli_launch_health as health

class LaunchHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.exe=self.root/'codex.exe';self.exe.write_bytes(b'fixture, never executed');self.state=self.root/'health.json'
    def tearDown(self):self.temp.cleanup()
    def process(self,code=0xC0000142):
        p=MagicMock();p.stdout.__iter__.return_value=iter([]);p.poll.return_value=code;p.wait.return_value=code
        return p
    def patches(self,process):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch('quota.find_codex',return_value=str(self.exe)))
        stack.enter_context(patch('codex_connection.cli_command',return_value=[str(self.exe),'app-server']))
        stack.enter_context(patch('codex_connection.child_environment',return_value={}))
        self.launch=stack.enter_context(patch('subprocess.Popen',return_value=process))
        stack.enter_context(patch('quota.time.sleep'))
        return stack
    def read(self,**kwargs):return quota.read_quota(log_path=False,health_path=self.state,**kwargs)
    def test_native_exit_launches_once_then_blocks_automatic_reads_across_reload(self):
        with self.patches(self.process()):
            with self.assertRaises(quota.QuotaFailure) as error:self.read()
            self.assertEqual(error.exception.code,'cli_native_exit');self.assertFalse(error.exception.retryable)
            self.assertEqual(error.exception.exit_code,'0xC0000142');self.assertEqual(self.launch.call_count,1)
            importlib.reload(health)
            with self.assertRaises(quota.QuotaFailure) as error:self.read()
            self.assertEqual(error.exception.code,'cli_startup_blocked');self.assertEqual(self.launch.call_count,1)
    def test_manual_retry_and_replaced_executable_are_each_allowed_one_attempt(self):
        with self.patches(self.process(-1073741502)):
            for manual in (False,True):
                with self.assertRaises(quota.QuotaFailure):self.read(manual=manual)
            self.assertEqual(self.launch.call_count,2)
            self.exe.write_bytes(b'different CLI build, never executed')
            with self.assertRaises(quota.QuotaFailure):self.read()
            self.assertEqual(self.launch.call_count,3)
    def test_manual_success_unblocks_future_background_queries(self):
        health.record(self.exe,'cli_native_exit','0xC0000142',self.state)
        with patch('quota._read_quota_once',return_value={'ok':True}) as read:
            self.assertEqual(self.read(manual=True),{'ok':True});self.assertEqual(health.load(self.state),{})
            self.assertEqual(self.read(),{'ok':True});self.assertEqual(read.call_count,2)
    def test_spawn_error_is_not_retried_and_records_no_sensitive_error_text(self):
        with self.patches(self.process()):
            self.launch.side_effect=OSError(1114,'sensitive-string-never-log')
            with self.assertRaises(quota.QuotaFailure) as error:self.read()
            self.assertEqual(error.exception.code,'cli_startup_failed');self.assertEqual(self.launch.call_count,1)
            self.assertNotIn('sensitive-string',self.state.read_text(encoding='utf-8'))
    def test_initial_handshake_timeout_is_not_a_network_retry(self):
        times=iter(range(0,10000,50))
        with self.patches(self.process(None)),patch('quota.time.monotonic',side_effect=lambda:next(times)):
            with self.assertRaises(quota.QuotaFailure) as error:self.read()
            self.assertEqual(error.exception.code,'cli_startup_timeout');self.assertEqual(self.launch.call_count,1)
    def test_network_errors_still_retry_without_creating_a_startup_block(self):
        error=quota.classify_error('error sending request','rate_limits')
        with patch('quota._read_quota_once',side_effect=[error,{'ok':True}]) as read,patch('quota.time.sleep'):
            self.assertEqual(self.read(),{'ok':True});self.assertEqual(read.call_count,2);self.assertFalse(self.state.exists())
    def test_cleanup_does_not_replace_the_native_startup_failure(self):
        p=self.process();p.stdout.close.side_effect=OSError('cleanup failed')
        with self.patches(p):
            with self.assertRaises(quota.QuotaFailure) as error:self.read()
            self.assertEqual(error.exception.code,'cli_native_exit')
    def test_external_cli_keeps_proxy_and_account_without_qt_or_parent_bootloader_paths(self):
        from process_launch import external_environment
        root=str(self.root/'parent-runtime')
        with patch.dict(os.environ,dict(QT_PLUGIN_PATH=root,QT_QPA_PLATFORM_PLUGIN_PATH=root,PATH=root+os.pathsep+r'C:\Windows\System32',HTTPS_PROXY='proxy-fixture',CODEX_HOME='home-fixture',_PYI_APPLICATION_HOME_DIR=root),clear=True),patch.object(sys,'_MEIPASS',root,create=True):
            env=external_environment()
            self.assertNotIn('QT_PLUGIN_PATH',env);self.assertNotIn('_PYI_APPLICATION_HOME_DIR',env)
            self.assertEqual(env['PATH'],r'C:\Windows\System32');self.assertEqual(env['HTTPS_PROXY'],'proxy-fixture');self.assertEqual(env['CODEX_HOME'],'home-fixture')
    def test_unwritable_state_still_blocks_same_process_without_hiding_the_failure(self):
        with patch('pathlib.Path.write_text',side_effect=PermissionError('locked')):
            health.record(self.exe,'cli_native_exit','0xC0000142',self.state)
        self.assertTrue(health.blocked(self.exe,self.state))
    def test_manual_worker_passes_retry_intent_and_retains_typed_failure(self):
        from pet import QuotaWorker
        error=quota.QuotaFailure('fixture','cli_native_exit',executable=str(self.exe),exit_code='0xC0000142')
        worker=QuotaWorker(manual=True);events=[];worker.failed.connect(events.append)
        with patch('pet.read_quota',side_effect=error) as read:
            worker.run();read.assert_called_once_with(cancel=worker.cancel,manual=True)
        self.assertEqual(events,[error]);self.assertEqual(events[0].code,'cli_native_exit')
        worker.deleteLater()
