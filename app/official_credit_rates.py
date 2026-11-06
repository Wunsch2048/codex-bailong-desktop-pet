"""Public Standard Credits rate card. Separate from API USD and plan allowances."""
import copy,hashlib,json,math,os,re,time
from html.parser import HTMLParser
from pathlib import Path
from PySide6.QtCore import QObject,Signal,QTimer,QUrl
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply

SOURCE='https://learn.chatgpt.com/docs/pricing'
DOCUMENT=SOURCE+'.md'
DAY=86400
MAX_BYTES=524288
MAX_CACHE=4*1024*1024


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.tables=[];self.table=None;self.row=None;self.cell=None;self.footer=False
    def handle_starttag(self,tag,attrs):
        if tag=='table':self.table=[]
        elif tag=='tfoot':self.footer=True
        elif tag=='tr' and self.table is not None and not self.footer:self.row=[]
        elif tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,text):
        if self.cell is not None:self.cell.append(text)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        elif tag=='tr' and self.row is not None:
            self.table.append(self.row);self.row=None
        elif tag=='table' and self.table is not None:
            self.tables.append(self.table);self.table=None
        elif tag=='tfoot':self.footer=False


def validate_rates(rates,unknown_cache=False):
    if not isinstance(rates,dict) or not 3<=len(rates)<=100:raise ValueError('价表模型数量不正确')
    for key,row in rates.items():
        if not re.fullmatch(r'[a-z0-9][a-z0-9.()-]{1,100}',key):raise ValueError('价表模型名称不正确')
        if not isinstance(row,dict) or not isinstance(row.get('name'),str) or not 1<=len(row['name'])<=100:raise ValueError('价表模型名称不正确')
        values=row.get('rates')
        if not isinstance(values,list) or len(values)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1000000 for i,v in enumerate(values) if not (unknown_cache and i==1 and v is None)):raise ValueError('价表单价不正确')
        if values[1] is not None and values[1]>values[0] or values[2]<=0:raise ValueError('价表单价结构不正确')
    return rates


def revision(rates):
    return hashlib.sha256(json.dumps(rates,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def parse_document(raw):
    if len(raw)>MAX_BYTES:raise ValueError('官方价表页面过大')
    text=raw.decode('utf-8')
    match=re.search(r'^#### Token rates\s*$(.*?)(?=^### |\Z)',text,re.M|re.S)
    if not match:raise ValueError('官方价表格式已变化')
    section=match.group(1)
    if 'Standard speed' not in section or 'included subscription usage' not in section:raise ValueError('无法确认价表适用范围')
    parser=Tables();parser.feed(section)
    tables=[t for t in parser.tables if t and t[0]==['Credits per 1M tokens','Input Tokens','Cached input tokens','Output Tokens']]
    if len(tables)!=1:raise ValueError('无法确认 Credits 价表')
    rates={}
    for row in tables[0][1:]:
        if len(row)!=4:raise ValueError('价表列数已变化')
        name=row[0];key=re.sub(r'\s+','-',name.strip().lower())
        if key in rates:raise ValueError('价表模型重复')
        values=[]
        for cell in row[1:]:
            value=re.fullmatch(r'(\d+(?:,\d{3})*(?:\.\d+)?) credits',cell)
            if not value:raise ValueError('价表单价格式已变化')
            values.append(float(value[1].replace(',','')))
        rates[key]=dict(name=name,rates=values)
    return validate_rates(rates)


def empty_cache():return dict(schema=1,source=SOURCE,unit='credits_per_million_tokens',speed='standard',checked_at=0,attempted_at=0,versions=[])


def validate_cache(data,source=SOURCE,unit='credits_per_million_tokens',rates_validator=validate_rates):
    if not isinstance(data,dict) or any(data.get(k)!=v for k,v in [('schema',1),('source',source),('unit',unit),('speed','standard')]):raise ValueError('价表缓存类型不正确')
    for key in ('checked_at','attempted_at'):
        value=data.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('价表缓存时间不正确')
    versions=data.get('versions')
    if not isinstance(versions,list) or len(versions)>1000:raise ValueError('价表历史数量不正确')
    for v in versions:
        if not isinstance(v,dict) or isinstance(v.get('observed_at'),bool) or not isinstance(v.get('observed_at'),(float,int)) or not math.isfinite(v['observed_at']) or v['observed_at']<=0:raise ValueError('价表历史时间不正确')
        if v.get('revision')!=revision(rates_validator(v.get('rates'))):raise ValueError('价表历史校验不通过')
    if any(a['observed_at']>b['observed_at'] for a,b in zip(versions,versions[1:])):raise ValueError('价表历史时间顺序不正确')
    return data


class RateCache:
    empty=staticmethod(empty_cache)
    validate=staticmethod(validate_cache)
    validate_rates=staticmethod(validate_rates)
    def __init__(self,path):
        self.path=Path(path);self.invalid=False;self.data=self.empty();self.error=''
        try:
            if self.path.stat().st_size>MAX_CACHE:raise ValueError('价表缓存过大')
            self.data=self.validate(json.loads(self.path.read_text(encoding='utf-8')))
        except FileNotFoundError:pass
        except (OSError,ValueError,TypeError,KeyError):self.invalid=True;self.error='本地价表缓存未能读取'
    def save(self,data):
        self.validate(data)
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
        if len(raw)>MAX_CACHE:raise ValueError('价表历史已满，保留现有记录')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.invalid and self.path.exists():
            # Preserve the original bytes before repairing only this cache.
            backup=self.path.with_name(self.path.name+'.invalid-'+str(time.time_ns()))
            with backup.open('xb') as stream:stream.write(self.path.read_bytes())
        pending=self.path.with_name(self.path.name+'.pending')
        with pending.open('wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(pending,self.path);self.data=data;self.invalid=False
    def accept(self,rates,now):
        rates=copy.deepcopy(self.validate_rates(rates));data=dict(self.data,checked_at=now,attempted_at=now,versions=list(self.data['versions']))
        key=revision(rates)
        if not data['versions'] or data['versions'][-1]['revision']!=key:
            if data['versions'] and now<data['versions'][-1]['observed_at']:raise ValueError('系统时间早于价表记录，请校准时间')
            data['versions'].append(dict(revision=key,observed_at=now,rates=rates))
        self.save(data);self.error=''
    def failed(self,now,message):
        self.error=message
        # Failed checks retain every prior table and its successful check time.
        if not self.invalid:self.save(dict(self.data,attempted_at=now))
    def due(self,now):
        last=self.data['attempted_at']
        return not last or now<last or now-last>=DAY


class OfficialCreditRates(QObject):
    changed=Signal()
    updated=Signal()
    cache_type=RateCache
    document_url=DOCUMENT
    parse=staticmethod(parse_document)
    def __init__(self,path,parent=None,clock=time.time,network=None):
        super().__init__(parent);self.cache=self.cache_type(path);self.clock=clock
        self.network=network or QNetworkAccessManager(self);self.reply=None;self.busy=False;self.last_request=None
        self.timer=QTimer(self);self.timer.setInterval(3600000);self.timer.timeout.connect(self.ensure_due)
    def start(self):
        if not self.timer.isActive():self.timer.start();QTimer.singleShot(30000,self,self.ensure_due)
    def ensure_due(self):
        if self.cache.due(self.clock()):self.request()
    def request(self):
        now=self.clock()
        if self.busy or self.last_request is not None and 0<=now-self.last_request<30:return
        self.last_request=now;self.busy=True
        request=QNetworkRequest(QUrl(self.document_url));request.setTransferTimeout(10000)
        request.setRawHeader(b'Accept',b'text/markdown')
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        self.reply=self.network.get(request);self.reply.readyRead.connect(self._limit);self.reply.finished.connect(self._finished)
        self.changed.emit()
    def _limit(self):
        if self.reply and self.reply.bytesAvailable()>MAX_BYTES:self.reply.abort()
    def _finished(self):
        reply=self.reply;self.reply=None;self.busy=False
        try:
            if reply.error()!=QNetworkReply.NetworkError.NoError:raise ValueError('官方价表暂未取得')
            if reply.url()!=QUrl(self.document_url) or reply.bytesAvailable()>MAX_BYTES:raise ValueError('官方价表地址或大小异常')
            before=len(self.cache.data['versions'])
            self.cache.accept(self.parse(bytes(reply.readAll())),self.clock())
            if len(self.cache.data['versions'])!=before:self.updated.emit()
        except (OSError,ValueError,TypeError,KeyError,UnicodeError) as error:
            message=str(error) if isinstance(error,ValueError) else '价表缓存未能保存'
            try:self.cache.failed(self.clock(),message)
            except (OSError,ValueError):self.cache.error='价表缓存未能保存，保留原记录'
        finally:reply.deleteLater()
        self.changed.emit()
    def close(self):
        self.timer.stop()
        if self.reply:
            reply=self.reply;self.reply=None;self.busy=False
            reply.finished.disconnect(self._finished);reply.abort();reply.deleteLater()


def shared():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance()
    if not hasattr(app,'_bailong_credit_rates'):
        from storage_locations import data_dir
        app._bailong_credit_rates=OfficialCreditRates(data_dir()/'official-credit-rates.json',app)
        app.aboutToQuit.connect(app._bailong_credit_rates.close)
    return app._bailong_credit_rates
