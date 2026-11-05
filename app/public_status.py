"""On-demand public status, separate from local Token sampling. No credentials."""
import json,time
from datetime import datetime
from PySide6.QtCore import QObject,Signal,QUrl,QTimer
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply

STATUS_URL='https://status.openai.com/api/v2/summary.json'
def decode_status(data,now=None):
    now=time.time() if now is None else now
    if not isinstance(data,dict) or not isinstance(data.get('status'),dict):raise ValueError('invalid status')
    indicator=data['status'].get('indicator')
    if indicator not in ('none','minor','major','critical'):raise ValueError('invalid indicator')
    incidents=[]
    for incident in data.get('incidents',[])[:12]:
        if incident.get('status') in ('resolved','postmortem'):continue
        updates=incident.get('incident_updates') or []
        incidents.append(dict(name=str(incident.get('name',''))[:180],body=str(updates[0].get('body',''))[:1600] if updates else '',updated=str(incident.get('updated_at',''))[:40]))
    delayed=any(any(word in (i['name']+' '+i['body']).lower() for word in ('latency','delay','slow','degraded')) for i in incidents)
    return dict(tone='ok' if indicator=='none' else 'warn',title='未报告异常' if indicator=='none' else '响应延迟' if delayed else '服务有异常',checked=now,incidents=incidents,source='https://status.openai.com/')

class PublicStatus(QObject):
    changed=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent);self.network=QNetworkAccessManager(self);self.reply=None;self.last=None;self.attempt=0;self.value=dict(tone='unknown',title='暂未取得',checked=None,incidents=[])
    def request(self):
        now=time.time()
        if self.reply is not None or now-self.attempt<300:return
        self.attempt=now;request=QNetworkRequest(QUrl(STATUS_URL));request.setTransferTimeout(7000)
        if self.last and now-self.last['checked']>600:
            self.value=dict(tone='unknown',title='暂未取得',checked=None,incidents=[],previous=self.last);self.changed.emit(self.value)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        self.reply=self.network.get(request);self.reply.readyRead.connect(self._limit);self.reply.finished.connect(self._finished)
    def _limit(self):
        if self.reply and self.reply.bytesAvailable()>524288:self.reply.abort()
    def _finished(self):
        reply=self.reply;self.reply=None
        try:
            if reply.error()!=QNetworkReply.NetworkError.NoError:raise ValueError('unavailable')
            raw=bytes(reply.readAll())
            if len(raw)>524288:raise ValueError('oversized')
            self.last=decode_status(json.loads(raw));self.value=self.last
        except (ValueError,TypeError,KeyError):
            self.value=dict(tone='unknown',title='暂未取得',checked=None,incidents=[],previous=self.last)
        finally:reply.deleteLater()
        self.changed.emit(self.value)

def shared():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance()
    if not hasattr(app,'_bailong_public_status'):app._bailong_public_status=PublicStatus(app)
    return app._bailong_public_status

def service_colors(theme,tone):
    dark=__import__('PySide6.QtGui',fromlist=['QColor']).QColor(theme['surface']).lightness()<128
    return ({'ok':('#77cba3','#77cba3'),'warn':('#f2d05b','#edce4d'),'unknown':('#ff949d','#ff7e8c')} if dark else {'ok':('#28785a','#339470'),'warn':('#8a6500','#d4a000'),'unknown':('#b82d3d','#ce3d4e')})[tone]

def bubble_position(card,anchor,size,area):
    """Prefer a non-overlapping edge of the whole card, then bounded fallback."""
    from PySide6.QtCore import QRect
    w,h=size;gap=8
    candidates=[QRect(anchor.center().x()-w//2,card.top()-gap-h,w,h),QRect(card.right()+gap+1,anchor.center().y()-h//2,w,h),QRect(card.left()-gap-w,anchor.center().y()-h//2,w,h),QRect(anchor.center().x()-w//2,card.bottom()+gap+1,w,h)]
    for i,r in enumerate(candidates):
        if i in (0,3):r.moveLeft(max(area.left()+2,min(r.left(),area.right()-w-1)))
        else:r.moveTop(max(area.top()+2,min(r.top(),area.bottom()-h-1)))
        if area.contains(r) and not r.intersects(card):return r
    r=candidates[0];r.moveLeft(max(area.left()+2,min(r.left(),area.right()-w-1)));r.moveTop(max(area.top()+2,min(r.top(),area.bottom()-h-1)));return r
