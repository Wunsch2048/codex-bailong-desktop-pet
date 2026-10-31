"""Bounded SSE/JSON Chat Completions transport; no automatic credential redirects."""
import json
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from chat_protocol import normalize_provider, endpoint_for, service_error, ProviderValidationError


class ChatStream(QObject):
    delta = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)
        self.cancelled = False

    def start(self, provider, key, messages):
        provider = normalize_provider(provider)
        if not isinstance(key, str) or any(ord(c) < 32 or ord(c) == 127 for c in key):
            raise ProviderValidationError('API 密钥包含无效字符，请重新粘贴。', 'key')
        if self.reply is not None:
            raise ValueError('当前请求尚未结束')
        self.key = key.strip()
        self.buffer = b''
        self.raw = b''
        self.event_lines = []
        self.event_size = 0
        self.text = ''
        self.completed = False
        self.cancelled = False
        self.mode = None
        self.prefix_pending = True
        self.skip_lf = False
        request = QNetworkRequest(QUrl(endpoint_for(provider)))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        request.setRawHeader(b'Accept', b'text/event-stream, application/json')
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        if self.key:
            request.setRawHeader(b'Authorization', ('Bearer '+self.key).encode('utf-8'))
        body = json.dumps(dict(model=provider['model'], messages=messages, stream=True), ensure_ascii=False).encode('utf-8')
        self.reply = self.manager.post(request, body)
        reply = self.reply
        reply.readyRead.connect(lambda: self.read(reply))
        reply.finished.connect(lambda: self.finish(reply))
        self.timer.start(provider['timeout']*1000)

    def read(self, reply):
        if self.cancelled or reply is not self.reply:
            return
        data = bytes(reply.readAll())
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status and int(status) >= 300:
            self.mode = 'error'
            self.raw = (self.raw + data)[:65536]
            return
        if not data:
            return
        self.buffer += data
        if self.prefix_pending:
            if len(self.buffer) < 3 and b'\xef\xbb\xbf'.startswith(self.buffer):
                return
            if self.buffer.startswith(b'\xef\xbb\xbf'):
                self.buffer = self.buffer[3:]
            self.prefix_pending = False
        if self.mode is None:
            content_type = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').lower()
            head = self.buffer.lstrip()
            if head.startswith((b'{', b'[')) or 'application/json' in content_type:
                self.mode = 'json'
            elif 'text/event-stream' in content_type or head.startswith((b'data:', b'event:', b':', b'id:', b'retry:')):
                self.mode = 'sse'
            elif len(head) > 32:
                self.mode = 'unknown'
        if self.mode == 'sse':
            self.drain_sse()
            if len(self.buffer) + self.event_size > 2_000_000:
                self.fail('接口返回的单条事件过大，已停止。')
        elif len(self.buffer) > 2_000_000:
            self.fail('接口返回数据过大，已停止。')

    def drain_sse(self, eof=False):
        while not self.cancelled:
            if self.skip_lf:
                if not self.buffer:
                    return
                if self.buffer.startswith(b'\n'):
                    self.buffer = self.buffer[1:]
                self.skip_lf = False
            positions = [p for p in (self.buffer.find(b'\r'), self.buffer.find(b'\n')) if p >= 0]
            if not positions:
                return
            index = min(positions)
            self.skip_lf = self.buffer[index:index+1] == b'\r'
            line, self.buffer = self.buffer[:index], self.buffer[index+1:]
            self.sse_line(line)

    def complete_stream(self):
        # [DONE] terminates the protocol even if a gateway keeps HTTP alive.
        self.completed = True
        self.cancelled = True
        self.timer.stop()
        reply, self.reply = self.reply, None
        self.key = ''
        if reply:
            reply.abort()
            reply.deleteLater()
        if self.text.strip():
            self.done.emit(self.text)
        else:
            self.failed.emit('服务已结束，但没有返回文字回复；请检查模型是否支持当前聊天接口。')

    def sse_line(self, line):
        if not line:
            if self.event_lines:
                data = b'\n'.join(self.event_lines)
                self.event_lines = []
                self.event_size = 0
                if data.strip() == b'[DONE]':
                    self.complete_stream()
                else:
                    self.consume_event(data, streaming=True)
        elif line.startswith(b'data:'):
            data = line[5:]
            if data.startswith(b' '):
                data = data[1:]
            self.event_lines.append(data)
            self.event_size += len(data)
            if self.event_size > 2_000_000:
                self.fail('接口返回的单条事件过大，已停止。')

    def consume_event(self, data, streaming):
        try:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError()
            if value.get('error') is not None:
                self.fail(service_error(200, value, self.key))
                return
            choices = value.get('choices', [])
            if not isinstance(choices, list):
                raise ValueError()
            if not choices:
                return
            choice = next((c for c in choices if isinstance(c, dict) and c.get('index', 0) == 0), None)
            if choice is None:
                return
            message = choice.get('delta' if streaming else 'message') or {}
            if not isinstance(message, dict):
                raise ValueError()
            text = message.get('content') or message.get('refusal')
            if isinstance(text, str):
                if len(self.text)+len(text) > 500000:
                    self.fail('回复过长，已停止。')
                    return
                self.text += text
                self.delta.emit(text)
            if choice.get('finish_reason') or not streaming:
                self.completed = True
        except (ValueError, TypeError, UnicodeError):
            self.fail('无法解析服务响应；当前支持 Chat Completions 的 SSE 或 JSON 格式。')

    def finish(self, reply):
        if reply is not self.reply:
            reply.deleteLater()
            return
        if not self.cancelled:
            self.read(reply)
        if reply is not self.reply:
            return
        if not self.cancelled:
            if self.mode == 'sse':
                self.drain_sse(eof=True)
                if self.buffer and not self.cancelled:
                    self.sse_line(self.buffer)
                    self.buffer = b''
                if not self.cancelled:
                    self.sse_line(b'')
            elif self.mode == 'json':
                self.consume_event(self.buffer, streaming=False)
        if reply is not self.reply:
            return
        self.timer.stop()
        self.reply = None
        if not self.cancelled:
            status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
            if status >= 300:
                try:
                    document = json.loads(self.raw)
                except (ValueError, UnicodeError):
                    document = None
                self.failed.emit(service_error(status, document, self.key))
            elif reply.error() != QNetworkReply.NetworkError.NoError:
                name = reply.error().name
                if 'Ssl' in name:
                    message = 'TLS 或证书验证失败，请检查系统时间、证书及代理配置。'
                elif 'HostNotFound' in name:
                    message = '无法解析服务域名，请检查 API 地址或网络。'
                elif 'Proxy' in name:
                    message = '代理连接失败，请检查系统代理设置。'
                else:
                    message = '连接中断或服务不可用，请检查网络及服务状态后重试。'
                self.failed.emit(message)
            elif not self.completed:
                self.failed.emit('服务在回复完成前断开，可以重试。' if self.mode == 'sse' else
                                 '接口没有返回可识别的 Chat Completions 回复，请检查地址及协议。')
            elif not self.text.strip():
                self.failed.emit('服务已结束，但没有返回文字回复；请检查模型是否支持当前聊天接口。')
            else:
                self.done.emit(self.text)
        self.key = ''
        reply.deleteLater()

    def fail(self, message):
        if self.cancelled:
            return
        self.cancel()
        self.failed.emit(message)

    def timeout(self):
        self.fail('请求超时，可调整服务超时后重试。')

    def cancel(self):
        self.cancelled = True
        self.timer.stop()
        if self.reply:
            self.reply.abort()
        self.key = ''
