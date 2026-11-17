"""Isolated storage failure tests; never read user credentials or call a provider."""
import base64
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chat_config as cfg
from desktop_core import atomic_json
from desktop_services import SecretStore


def fake_protect(value,decrypt=False):
    return base64.b64decode(value,validate=True).decode('utf-8') if decrypt else base64.b64encode(value.encode('utf-8')).decode('ascii')


class ChatConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config_path=self.root/'chat.json';self.secret_path=self.root/'credentials.dpapi.json'
        self.crypto=patch('desktop_services.protect',side_effect=fake_protect);self.crypto.start();self.addCleanup(self.crypto.stop)
        self.old=copy.deepcopy(cfg.CHAT_DEFAULT)
        self.old.update(active='provider-a',providers=[dict(id='provider-a',name='原服务',base_url='https://old.example/v1',model='old-model',timeout=90)])

    def seed(self):
        atomic_json(self.config_path,self.old);SecretStore(self.secret_path).put('provider-a','old-synthetic-key')
        return copy.deepcopy(self.old)

    def replacement(self):
        candidate=copy.deepcopy(self.old);candidate['providers'][0].update(base_url='https://new.example/v1',model='new-model')
        return candidate

    def assert_old_usable(self):
        saved=cfg.load_chat_config(self.root)
        self.assertEqual(saved,self.old)
        self.assertEqual(cfg.load_provider_key(self.root,saved['providers'][0]),'old-synthetic-key')

    def test_absent_files_are_clean_new_install(self):
        self.assertEqual(cfg.load_chat_config(self.root),cfg.CHAT_DEFAULT)
        self.assertEqual(SecretStore(self.secret_path).read(),{})
        self.assertFalse(self.config_path.exists());self.assertFalse(self.secret_path.exists())

    def test_provider_draft_cannot_restore_old_conversation_preferences(self):
        draft=self.seed()
        cfg.select_chat_service(self.root,'chatgpt','known-model')
        cfg.save_chat_preferences(self.root,'新的提示词',26,18000)
        saved=cfg.save_chat_config(self.root,draft,'provider-a',provider_only=True)
        self.assertEqual((saved['service'],saved['chatgpt_model']),('chatgpt','known-model'))
        self.assertEqual((saved['system_prompt'],saved['history_messages'],saved['history_chars']),('新的提示词',26,18000))
        self.assertEqual(cfg.load_provider_key(self.root,saved['providers'][0]),'old-synthetic-key')

    def test_success_uses_new_slot_and_keeps_input_immutable(self):
        self.seed();candidate=self.replacement();original=copy.deepcopy(candidate)
        saved=cfg.save_chat_config(self.root,candidate,'provider-a','new-synthetic-key')
        self.assertEqual(candidate,original)
        self.assertNotEqual(saved['providers'][0]['credential_id'],'provider-a')
        self.assertEqual(cfg.load_chat_config(self.root),saved)
        self.assertEqual(cfg.load_provider_key(self.root,saved['providers'][0]),'new-synthetic-key')
        self.assertEqual(cfg.load_provider_key(self.root,self.old['providers'][0]),'old-synthetic-key')
        self.assertNotIn('synthetic-key',self.config_path.read_text(encoding='utf-8'))
        self.assertNotIn('synthetic-key',self.secret_path.read_text(encoding='utf-8'))

    def test_first_write_failure_keeps_old_pair(self):
        self.seed();before=self.secret_path.read_bytes()
        with patch('desktop_services.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):cfg.save_chat_config(self.root,self.replacement(),'provider-a','new-synthetic-key')
        self.assertEqual(self.secret_path.read_bytes(),before);self.assert_old_usable()

    def test_second_write_failure_keeps_old_pair_and_retry_works(self):
        self.seed();candidate=self.replacement()
        with patch('chat_config.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):cfg.save_chat_config(self.root,candidate,'provider-a','new-synthetic-key')
        self.assert_old_usable()
        saved=cfg.save_chat_config(self.root,candidate,'provider-a','new-synthetic-key')
        self.assertEqual(cfg.load_provider_key(self.root,saved['providers'][0]),'new-synthetic-key')

    def test_process_exit_between_writes_needs_no_rollback(self):
        self.seed()
        with patch('chat_config.atomic_json',side_effect=SystemExit):
            with self.assertRaises(SystemExit):cfg.save_chat_config(self.root,self.replacement(),'provider-a','new-synthetic-key')
        self.assert_old_usable()

    def test_blank_key_preserves_legacy_and_versioned_keys(self):
        self.seed();saved=cfg.save_chat_config(self.root,self.replacement(),'provider-a','')
        self.assertNotIn('credential_id',saved['providers'][0])
        self.assertEqual(cfg.load_provider_key(self.root,saved['providers'][0]),'old-synthetic-key')
        saved=cfg.save_chat_config(self.root,saved,'provider-a','new-synthetic-key')
        again=cfg.save_chat_config(self.root,saved,'provider-a','')
        self.assertEqual(again,saved)
        self.assertEqual(cfg.load_provider_key(self.root,again['providers'][0]),'new-synthetic-key')

    def test_new_provider_without_key_does_not_adopt_orphan(self):
        SecretStore(self.secret_path).put('provider-a','orphan-synthetic-key')
        saved=cfg.save_chat_config(self.root,self.old,'provider-a')
        self.assertEqual(saved['providers'][0]['credential_id'],'')
        self.assertEqual(cfg.load_provider_key(self.root,saved['providers'][0]),'')

    def test_corrupt_config_formats_reject_read_and_write_without_changes(self):
        wrong=[b'[',b'[]',b'null',b'{"providers": {}}',b'{"system_prompt": []}',b'{"history_messages": "40"}',b'\xff',
               json.dumps(dict(providers=[None])).encode(),json.dumps(dict(providers=[dict(id='a',model=[])] )).encode(),
               json.dumps(dict(providers=[dict(id='a',timeout=True)])).encode(),
               json.dumps(dict(providers=[dict(id='a'),dict(id='a')])).encode(),b'{"active":"missing"}',b'['*1200+b'0'+b']'*1200]
        for content in wrong:
            with self.subTest(content=content):
                self.config_path.write_bytes(content)
                with self.assertRaises(OSError):cfg.load_chat_config(self.root)
                with self.assertRaises(OSError):cfg.save_chat_config(self.root,self.old,'provider-a','new-synthetic-key')
                self.assertEqual(self.config_path.read_bytes(),content);self.assertFalse(self.secret_path.exists())

    def test_corrupt_credential_document_never_overwritten(self):
        self.seed()
        for content in (b'[',b'[]',b'null',b'{"provider-a": []}',b'{"provider-a": null}',b'\xff',b'['*1200+b'0'+b']'*1200):
            with self.subTest(content=content):
                self.secret_path.write_bytes(content)
                for action in (lambda:SecretStore(self.secret_path).get('provider-a'),
                               lambda:SecretStore(self.secret_path).put('provider-a','new-synthetic-key'),
                               lambda:cfg.save_chat_config(self.root,self.replacement(),'provider-a','new-synthetic-key'),
                               lambda:cfg.clear_provider_key(self.root,'provider-a'),
                               lambda:cfg.delete_chat_provider(self.root,self.old,'provider-a')):
                    with self.assertRaises(OSError):action()
                    self.assertEqual(self.secret_path.read_bytes(),content)
                    self.assertEqual(cfg.load_chat_config(self.root),self.old)

    def test_permission_read_errors_are_not_treated_as_missing(self):
        self.seed();real_read=Path.read_text
        for denied in (self.config_path,self.secret_path):
            def read(path,*args,**kwargs):
                if path==denied:raise PermissionError('denied')
                return real_read(path,*args,**kwargs)
            with self.subTest(path=denied.name),patch.object(Path,'read_text',read):
                with self.assertRaises(OSError):cfg.save_chat_config(self.root,self.replacement(),'provider-a','new-synthetic-key')
            self.assert_old_usable()

    def test_broken_cipher_gives_safe_error_and_status_does_not_decrypt(self):
        self.seed();atomic_json(self.secret_path,{'provider-a':'not valid base64 !'})
        self.assertTrue(cfg.provider_key_present(self.root,self.old['providers'][0]))
        with self.assertRaises(OSError) as context:cfg.load_provider_key(self.root,self.old['providers'][0])
        self.assertNotIn('not valid base64',str(context.exception))

    def test_clear_commits_first_and_stale_draft_cannot_restore_key(self):
        self.seed();stale=cfg.save_chat_config(self.root,self.old,'provider-a','new-synthetic-key')
        cleared,warning=cfg.clear_provider_key(self.root,'provider-a')
        self.assertFalse(warning);self.assertEqual(cleared['providers'][0]['credential_id'],'')
        self.assertEqual(SecretStore(self.secret_path).read(),{})
        stale['providers'][0]['model']='updated-model'
        saved=cfg.save_chat_config(self.root,stale,'provider-a','')
        self.assertEqual(cfg.load_provider_key(self.root,saved['providers'][0]),'')

    def test_clear_first_write_failure_keeps_old_pair(self):
        self.seed()
        with patch('chat_config.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):cfg.clear_provider_key(self.root,'provider-a')
        self.assert_old_usable()

    def test_clear_cleanup_failure_reports_committed_disabled_key(self):
        self.seed();real_atomic=cfg.atomic_json
        def write(path,value):
            if Path(path)==self.secret_path:raise OSError('disk full')
            return real_atomic(path,value)
        with patch('chat_config.atomic_json',side_effect=write):saved,warning=cfg.clear_provider_key(self.root,'provider-a')
        self.assertTrue(warning);self.assertEqual(cfg.load_provider_key(self.root,saved['providers'][0]),'')
        self.assertTrue(SecretStore(self.secret_path).read())
        saved,warning=cfg.clear_provider_key(self.root,'provider-a')
        self.assertFalse(warning);self.assertEqual(SecretStore(self.secret_path).read(),{})

    def test_clear_does_not_save_unrelated_drafts(self):
        self.seed();candidate=self.replacement()
        saved,_=cfg.clear_provider_key(self.root,'provider-a')
        self.assertEqual(saved['providers'][0]['model'],'old-model')
        self.assertEqual(candidate['providers'][0]['model'],'new-model')

    def test_delete_cleans_keys_without_removing_another_service(self):
        self.seed();saved=cfg.save_chat_config(self.root,self.old,'provider-a','new-synthetic-key')
        saved['providers'].append(dict(id='provider-b',name='B',base_url='http://localhost:8000/v1',model='local'))
        saved=cfg.save_chat_config(self.root,saved,'provider-b','other-synthetic-key')
        result,warning=cfg.delete_chat_provider(self.root,saved,'provider-a')
        self.assertFalse(warning);self.assertEqual(result['active'],'provider-b')
        self.assertEqual(cfg.load_provider_key(self.root,result['providers'][0]),'other-synthetic-key')
        self.assertEqual(len(SecretStore(self.secret_path).read()),1)

    def test_delete_write_failure_keeps_old_pair(self):
        self.seed()
        with patch('chat_config.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):cfg.delete_chat_provider(self.root,self.old,'provider-a')
        self.assert_old_usable()

    def test_accidental_plaintext_draft_field_never_saved(self):
        self.seed();draft=self.replacement();draft['providers'][0]['key']='draft-synthetic-key'
        saved=cfg.save_chat_config(self.root,draft,'provider-a')
        self.assertNotIn('key',saved['providers'][0]);self.assertNotIn('draft-synthetic-key',self.config_path.read_text(encoding='utf-8'))


@unittest.skipUnless(os.name=='nt','Windows DPAPI only')
class ActualDPAPITests(unittest.TestCase):
    def test_new_slot_roundtrip_uses_real_windows_dpapi(self):
        with tempfile.TemporaryDirectory() as directory:
            value=copy.deepcopy(cfg.CHAT_DEFAULT)
            value.update(active='synthetic',providers=[dict(id='synthetic',base_url='http://localhost:12345/v1',model='fixture')])
            saved=cfg.save_chat_config(directory,value,'synthetic','isolated-fixture-key-not-a-real-token')
            self.assertEqual(cfg.load_provider_key(directory,saved['providers'][0]),'isolated-fixture-key-not-a-real-token')


if __name__=='__main__':unittest.main()
