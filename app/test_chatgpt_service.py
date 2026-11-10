"""Exercise the optional service without a real login or paid request."""
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlencode,urlsplit
from urllib.request import urlopen

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest
from chatgpt_oauth import ChatGPTAccount
from chat_transport import ChatGPTStream
from chat_window import ChatWindow
from chat_config import load_chat_config

APP=QApplication.instance() or QApplication([])


class ChatGPTServiceTests(unittest.TestCase):
    def test_model_catalog_can_exceed_authorization_response_limit(self):
        from chatgpt_oauth import TOKEN,_json
        payload=json.dumps({'models':[dict(slug='test-model',display_name='Test Model',
                                           visibility='list',metadata='x'*(128*1024))]}).encode()
        with patch('chatgpt_oauth.build_opener') as opener:
            opener.return_value.open.side_effect=lambda *args,**kwargs:io.BytesIO(payload)
            self.assertEqual(ChatGPTAccount(Path('.')).models('synthetic-token'),{'test-model':'Test Model'})
            with self.assertRaisesRegex(OSError,'授权响应过大'):
                _json(TOKEN)

    def test_signed_id_token_accepts_single_client_audience_array(self):
        from base64 import urlsafe_b64encode
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding,rsa
        from chatgpt_oauth import ISSUER,verify_id_token
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=key.public_key().public_numbers()
        def encode(value):return urlsafe_b64encode(value).rstrip(b'=').decode('ascii')
        def integer(value):return encode(value.to_bytes((value.bit_length()+7)//8,'big'))
        keys={'keys':[dict(kid='test',kty='RSA',e=integer(public.e),n=integer(public.n))]}
        header=encode(json.dumps(dict(alg='RS256',kid='test')).encode())
        def token(audience):
            claims=dict(iss=ISSUER,aud=audience,nonce='attempt',sub='account',exp=200)
            signed=header+'.'+encode(json.dumps(claims).encode())
            signature=key.sign(signed.encode(),padding.PKCS1v15(),hashes.SHA256())
            return signed+'.'+encode(signature)
        self.assertEqual(verify_id_token(token(['issued']),'issued','attempt',keys,100)['sub'],'account')
        with self.assertRaises(OSError):
            verify_id_token(token(['issued','other']),'issued','attempt',keys,100)
        with self.assertRaises(OSError):
            verify_id_token(token(['issued']),'issued','other',keys,100)

    def test_callback_ignores_wrong_state_then_accepts_matching_attempt(self):
        account=ChatGPTAccount(Path('unused'))
        account.store=Mock()
        account.record=Mock(return_value=None)
        account.host_id=Mock(return_value='urn:uuid:host')
        account.pending_client_id=Mock(return_value=None)
        results=[];workers=[]
        def browser(url):
            params=parse_qs(urlsplit(url).query)
            redirect=params['redirect_uri'][0]
            def callbacks():
                def request(state):
                    with urlopen(redirect+'?'+urlencode(dict(state=state,code='synthetic',client_id='issued')),timeout=3) as reply:
                        return reply.status
                try:request('unrelated')
                except HTTPError as error:
                    results.append(error.code);error.close()
                results.append(request(params['state'][0]))
            worker=threading.Thread(target=callbacks,daemon=True)
            workers.append(worker);worker.start()
        response=dict(access_token='access',refresh_token='refresh',id_token='verified',
                      scope='chatgpt.tokens.use.direct',expires_in=1000)
        stages=[]
        with patch('chatgpt_oauth.atomic_json'),patch('chatgpt_oauth._json',return_value=response) as exchange,\
             patch('chatgpt_oauth.verify_id_token',return_value={'sub':'account'}):
            account.login(browser,progress=stages.append)
        workers[0].join(3)
        self.assertEqual(results,[400,200])
        self.assertEqual(stages,['exchange','verify'])
        self.assertEqual(exchange.call_args.args[1]['client_id'],'issued')
        self.assertEqual(json.loads(account.store.put.call_args.args[1])['subject'],'account')

    def test_responses_requires_completed_and_keeps_local_context(self):
        stream=ChatGPTStream()
        with patch.object(stream,'post') as post:
            stream.start({'model':'example'},'access',[
                {'role':'system','content':'style'},{'role':'user','content':'first'},
                {'role':'assistant','content':'reply'},{'role':'user','content':'follow-up'}])
        url,_,payload,_=post.call_args.args
        self.assertEqual(url,'https://api.openai.com/v1/responses')
        self.assertFalse(payload['store'])
        self.assertEqual([m['content'] for m in payload['input']],['first','reply','follow-up'])
        stream.text=''
        stream.event_lines=[b'[DONE]'];stream.event_size=6
        done=[];stream.done.connect(done.append)
        stream.sse_line(b'')
        stream.consume_event(b'{"type":"response.output_text.delta","delta":"text"}',True)
        self.assertEqual(done,[])
        stream.consume_event(b'{"type":"response.completed"}',True)
        self.assertEqual(done,['text'])

    def test_switch_preserves_draft_and_ignores_late_authorization(self):
        pet=QWidget();pet.settings={};pet.manifest={}
        with tempfile.TemporaryDirectory() as root:
            view=ChatWindow(pet,root,embedded=True)
            view.input.setPlainText('保留草稿')
            view.choose_service('chatgpt')
            self.assertEqual(load_chat_config(root)['service'],'chatgpt')
            launched=threading.Event();release=threading.Event()
            def login(_account,browser,cancelled,progress):
                launched.set();release.wait(2)
                self.assertTrue(cancelled())
                raise OSError('late error')
            with patch.object(ChatGPTAccount,'login',login):
                view.connect_account()
                self.assertTrue(launched.wait(2))
                job=view.account_job
                view.choose_service('custom')
                release.set();QTest.qWait(50)
            self.assertTrue(job.cancelled.is_set())
            self.assertIsNone(view.account_job)
            self.assertEqual(load_chat_config(root)['service'],'custom')
            self.assertEqual(view.input.toPlainText(),'保留草稿')
            self.assertNotIn('late error',view.status.text())
            view.shutdown()
