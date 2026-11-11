"""Sign in with ChatGPT, adapted from pengxitai37-stack's issue #27 prototype."""
import base64
import hashlib
import json
import math
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError,URLError

from desktop_core import atomic_json
from desktop_services import SecretStore

ISSUER = 'https://auth.openai.com'
AUTHORIZE = ISSUER + '/api/accounts/authorize'
TOKEN = ISSUER + '/api/accounts/oauth/token'
JWKS = ISSUER + '/.well-known/jwks.json'
RESOURCE = 'https://api.openai.com/v1'
MODELS = RESOURCE + '/models'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
APP_NAME = 'bailong_desktop_pet'
_REFRESH_LOCK = threading.Lock()


def _b64(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def _json(url, form=None, token=None):
    is_model_list = url == MODELS
    response_limit = 8 * 1024 * 1024 if is_model_list else 128 * 1024
    response_name = 'ChatGPT 模型列表' if is_model_list else '授权响应'
    headers={'Accept':'application/json'}
    if form is not None:headers['Content-Type']='application/x-www-form-urlencoded'
    if token:headers['Authorization']='Bearer '+token
    request = Request(url, data=urlencode(form).encode('ascii') if form is not None else None,
                      headers=headers)
    try:
        with build_opener(NoRedirect()).open(request, timeout=12) as reply:
            data = reply.read(response_limit + 1)
    except HTTPError as error:
        code=None
        try:
            if url==TOKEN:
                response=json.loads(error.read(8192))
                if isinstance(response,dict):code=response.get('error')
        except (OSError,ValueError):pass
        finally:error.close()
        if code=='invalid_grant':
            raise OSError('授权码或续期凭据已失效，请在聊天服务菜单重新连接 ChatGPT。') from None
        if error.code in (401,403):raise OSError('ChatGPT 授权不可用，请重新连接。') from None
        if error.code==429:raise OSError('ChatGPT 套餐暂不可用，请稍后重试。') from None
        raise OSError(f'ChatGPT 服务请求失败（HTTP {error.code}），请重试。') from None
    except (URLError,TimeoutError):
        raise OSError('无法连接 ChatGPT 授权或模型服务，请检查网络后重试。') from None
    if len(data) > response_limit:
        raise OSError(f'{response_name}过大')
    try:
        value = json.loads(data)
    except ValueError:
        raise OSError(f'{response_name}格式错误') from None
    if not isinstance(value, dict):
        raise OSError(f'{response_name}格式错误')
    return value


def verify_id_token(token, client_id, nonce, keys=None, now=None):
    """Verify signature and OIDC claims before a new account becomes active."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.exceptions import InvalidSignature
    try:
        header, claims, signature = token.split('.')
        meta = json.loads(_b64(header)); payload = json.loads(_b64(claims))
        if meta.get('alg') != 'RS256' or not isinstance(meta.get('kid'), str):
            raise ValueError()
        keyset = keys if keys is not None else _json(JWKS)
        jwk = next(k for k in keyset['keys'] if k.get('kid') == meta['kid'] and k.get('kty') == 'RSA' and k.get('use', 'sig') == 'sig')
        public = rsa.RSAPublicNumbers(int.from_bytes(_b64(jwk['e']), 'big'), int.from_bytes(_b64(jwk['n']), 'big')).public_key()
        public.verify(_b64(signature), (header + '.' + claims).encode('ascii'), padding.PKCS1v15(), hashes.SHA256())
        current = time.time() if now is None else now
        audience=payload.get('aud')
        audience_ok=(audience==client_id or
                     isinstance(audience,list) and client_id in audience and
                     (len(audience)==1 or payload.get('azp')==client_id))
        if (payload.get('iss') != ISSUER or not audience_ok or
                payload.get('azp',client_id)!=client_id or
                payload.get('nonce') != nonce or not isinstance(payload.get('sub'), str) or not payload['sub'] or
                type(payload.get('exp')) not in (int,float) or not math.isfinite(payload['exp']) or payload['exp'] <= current or
                (isinstance(payload.get('iat'), (int, float)) and payload['iat'] > current + 60)):
            raise ValueError()
        return payload
    except (KeyError, StopIteration, ValueError, TypeError, UnicodeError, InvalidSignature) as error:
        raise OSError('ChatGPT 身份验证失败；授权未保存。') from error


class ChatGPTAccount:
    def __init__(self, root):
        self.root = Path(root)
        self.store = SecretStore(self.root / 'chatgpt-oauth.dpapi.json')

    def record(self):
        raw = self.store.get('active')
        if not raw:
            return None
        try:
            value = json.loads(raw)
            if not isinstance(value,dict) or not all(isinstance(value.get(k), str) and value[k] for k in ('client_id', 'subject', 'access_token', 'refresh_token')):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise OSError('ChatGPT 授权记录损坏；原文件已保留。') from None

    def label(self):
        value = self.record()
        return value.get('email') or '已连接 ChatGPT' if value else '尚未连接 ChatGPT'

    def models(self,token):
        document=_json(MODELS,token=token)
        rows=document.get('models')
        if not isinstance(rows,list):raise OSError('无法读取 ChatGPT 可用模型，请重试。')
        models={}
        for row in rows:
            if not isinstance(row,dict) or row.get('visibility')!='list':continue
            slug=row.get('slug');name=row.get('display_name')
            if isinstance(slug,str) and slug and len(slug)<=160:
                models[slug]=name[:100] if isinstance(name,str) and name else slug
        if not models:raise OSError('当前 ChatGPT 账户没有可用的聊天模型。')
        return models

    def disconnect(self):
        with _REFRESH_LOCK:
            self.store.put('active','')
            path=self.root/'chatgpt-client.json'
            if path.exists():path.unlink()

    def host_id(self):
        path = self.root / 'chatgpt-host.json'
        if path.exists():
            value = json.loads(path.read_text(encoding='utf-8'))
            host = value.get('ext_agent_host_id') if isinstance(value, dict) else None
            if isinstance(host, str) and host.startswith('urn:uuid:'):
                return host
            raise OSError('白龙 ChatGPT 主机标识损坏；原文件已保留。')
        host = 'urn:uuid:' + str(uuid.uuid4())
        atomic_json(path, {'ext_agent_host_id': host})
        return host

    def pending_client_id(self):
        path = self.root / 'chatgpt-client.json'
        if not path.exists(): return None
        value = json.loads(path.read_text(encoding='utf-8'))
        client_id = value.get('client_id') if isinstance(value, dict) else None
        if not isinstance(client_id, str) or not client_id or client_id == 'dynamic_agent_client':
            raise OSError('ChatGPT 客户端标识损坏；原文件已保留。')
        return client_id

    def access_token(self):
        with _REFRESH_LOCK:
            record = self.record()
            if not record:
                raise OSError('请先使用“继续使用 ChatGPT”完成授权。')
            if 'chatgpt.tokens.use.direct' not in record.get('scopes', []):
                raise OSError('此 ChatGPT 授权未包含计划额度使用权限。')
            if record.get('expires_at', 0) <= time.time() + 90:
                response = _json(TOKEN, {'grant_type': 'refresh_token', 'client_id': record['client_id'],
                                         'refresh_token': record['refresh_token'], 'resource': RESOURCE})
                for key in ('access_token', 'refresh_token'):
                    if not isinstance(response.get(key), str) or not response[key]:
                        raise OSError('ChatGPT 续期响应不完整；原授权已保留。')
                scopes = response.get('scope', ' '.join(record['scopes'])).split()
                if 'chatgpt.tokens.use.direct' not in scopes:
                    raise OSError('ChatGPT 续期后缺少计划额度使用权限；原授权已保留。')
                record.update(access_token=response['access_token'], refresh_token=response['refresh_token'],
                              scopes=scopes, expires_at=time.time() + int(response.get('expires_in', 3600)))
                self.store.put('active', json.dumps(record, ensure_ascii=False))
            return record['access_token']

    def login(self, open_browser, cancelled=lambda: False, progress=lambda stage: None):
        """Run the one-time browser callback on a worker thread, then commit verified tokens."""
        existing = self.record()
        state = secrets.token_urlsafe(32); nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        result = {}
        class Callback(BaseHTTPRequestHandler):
            timeout = 2
            def log_message(self, *args):
                pass
            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path != '/auth/callback' or len(self.path) > 8192:
                    self.send_error(404); return
                params={key: values[0] for key, values in parse_qs(parsed.query).items() if len(values) == 1}
                if not secrets.compare_digest(params.get('state','').encode('utf-8'),state.encode('ascii')):
                    self.send_error(400);return
                result.update(params)
                body = '白龙已收到授权回调，正在核验账户权限。请返回桌宠查看结果。'.encode('utf-8')
                self.send_response(200); self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        pending = self.pending_client_id() if not existing else None
        host_id=self.host_id()
        server = HTTPServer(('127.0.0.1', 0), Callback)
        server.timeout = 0.5
        redirect = f'http://127.0.0.1:{server.server_port}/auth/callback'
        client_id = existing['client_id'] if existing else pending or 'dynamic_agent_client'
        params = dict(client_id=client_id, ext_agent_host_id=host_id, response_type='code',
                      redirect_uri=redirect, scope=SCOPES, resource=RESOURCE, state=state, nonce=nonce,
                      code_challenge_method='S256', code_challenge=challenge)
        if existing:
            if existing.get('id_token'): params['id_token_hint'] = existing['id_token']
            if existing.get('email'): params['login_hint'] = existing['email']
        elif not pending:
            params['agent_name_hint'] = APP_NAME
        try:
            if cancelled():raise OSError('授权已取消。')
            open_browser(AUTHORIZE + '?' + urlencode(params))
            deadline = time.monotonic() + 180
            while not result and time.monotonic() < deadline and not cancelled():
                server.handle_request()
        finally:
            server.server_close()
        if cancelled(): raise OSError('授权已取消。')
        if not result: raise OSError('没有收到 ChatGPT 授权回调，请回到浏览器完成授权后重试。')
        if result.get('error'): raise OSError('ChatGPT 授权未完成。')
        issued = result.get('client_id') or (existing or {}).get('client_id') or pending
        if not issued or issued == 'dynamic_agent_client' or ((existing or pending) and issued != client_id):
            raise OSError('授权客户端标识不匹配；授权未保存。')
        if not result.get('code'):raise OSError('ChatGPT 未返回授权码，请重新连接。')
        if not existing and not cancelled():
            # A failed code exchange must not force another dynamic registration.
            atomic_json(self.root / 'chatgpt-client.json', {'client_id': issued})
        progress('exchange')
        try:
            response = _json(TOKEN, {'grant_type': 'authorization_code', 'client_id': issued,
                                     'code': result['code'], 'code_verifier': verifier,
                                     'redirect_uri': redirect, 'resource': RESOURCE})
        except (OSError,ValueError) as error:
            message=str(error) if isinstance(error,OSError) else '服务返回了无法读取的响应。'
            raise OSError('兑换 ChatGPT 授权失败。'+message) from None
        if cancelled():raise OSError('授权已取消。')
        progress('verify')
        try:
            claims = verify_id_token(response.get('id_token', ''), issued, nonce)
        except (OSError,ImportError,AttributeError):
            raise OSError('无法验证 ChatGPT 账户身份，请检查网络后重新连接。') from None
        if existing and claims['sub'] != existing['subject']:
            raise OSError('返回了不同的 ChatGPT 账户；原授权未改动。')
        scopes = response.get('scope', '').split()
        if 'chatgpt.tokens.use.direct' not in scopes:
            raise OSError('此授权未包含 ChatGPT 计划额度使用权限；未保存。')
        if not all(isinstance(response.get(k), str) and response[k] for k in ('access_token', 'refresh_token', 'id_token')):
            raise OSError('授权响应不完整；未保存。')
        record = dict(client_id=issued, subject=claims['sub'], email=claims.get('email', ''),
                      access_token=response['access_token'], refresh_token=response['refresh_token'],
                      id_token=response['id_token'], scopes=scopes,
                      expires_at=time.time() + int(response.get('expires_in', 3600)))
        with _REFRESH_LOCK:
            if cancelled():raise OSError('授权已取消。')
            try:self.store.put('active', json.dumps(record, ensure_ascii=False))
            except OSError:raise OSError('无法保存 ChatGPT 授权，请检查用户数据目录权限。') from None
        return record.get('email') or 'ChatGPT 账户已连接'
