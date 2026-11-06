"""Official Standard/short-context USD prices with observation-time history."""
import json,os,re
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path
from official_credit_rates import RateCache,OfficialCreditRates,empty_cache,validate_cache,validate_rates,MAX_BYTES

SOURCE='https://developers.openai.com/api/docs/pricing'
DOCUMENT=SOURCE+'.md'


def api_rates(rates):return validate_rates(rates,unknown_cache=True)


def parse_document(raw):
    if len(raw)>MAX_BYTES:raise ValueError('官方价表页面过大')
    text=raw.decode('utf-8')
    if 'Prices per 1M tokens.' not in text:raise ValueError('无法确认单价单位')
    match=re.search(r'^### Standard pricing data\s*$(.*?)(?=^### |\Z)',text,re.M|re.S)
    if not match:raise ValueError('官方标准价表格式已变化')
    rates={};headers=None;tables=0
    for line in match[1].splitlines():
        if not line.strip().startswith('|'):headers=None;continue
        cells=[v.strip() for v in line.strip().strip('|').split('|')]
        if cells[0]=='Model':
            if cells not in (['Model','Input','Output','Cached input'],['Model','Short context input','Short context output','Short context cached input','Short context 30m write','Short context 12h write','Long context input','Long context output','Long context cached input','Long context 30m write','Long context 12h write']):raise ValueError('官方价表列名已变化')
            headers=cells;tables+=1;continue
        if all(re.fullmatch(r':?-+:?',v) for v in cells):continue
        if headers is None or len(cells)!=len(headers):raise ValueError('官方价表列数已变化')
        model=re.sub(r' \(<272K context length\)$','',cells[0])
        if model in rates:raise ValueError('官方价表模型重复')
        values=[]
        for i in (1,3,2):
            cell=cells[i]
            if i==3 and cell=='-':values.append(None);continue
            if not re.fullmatch(r'\$\d+(?:,\d{3})*(?:\.\d+)?',cell):raise ValueError('官方价表单价格式已变化')
            values.append(float(cell[1:].replace(',','')))
        rates[model]=dict(name=model,rates=values)
    if tables!=2:raise ValueError('无法确认完整标准价表')
    return api_rates(rates)


class ApiPriceCache(RateCache):
    @staticmethod
    def empty():
        from project_cost import RATES
        return dict(empty_cache(),source=SOURCE,unit='usd_per_million_tokens',context='short',baseline={k:list(v) for k,v in RATES.items()})
    @staticmethod
    def validate(data):
        result=validate_cache(data,SOURCE,'usd_per_million_tokens',api_rates)
        if result.get('context')!='short':raise ValueError('价表上下文类型不正确')
        baseline=result.get('baseline')
        if not isinstance(baseline,dict):raise ValueError('缺少初始价表记录')
        api_rates({k:dict(name=k,rates=v) for k,v in baseline.items()})
        return result
    validate_rates=staticmethod(api_rates)


class OfficialApiPrices(OfficialCreditRates):
    cache_type=ApiPriceCache
    document_url=DOCUMENT
    parse=staticmethod(parse_document)


def cache_path():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced/official-api-prices.json'


@lru_cache(maxsize=1)
def _loaded(path,modified,size):return ApiPriceCache(path).data


def catalogue():
    path=cache_path()
    try:st=path.stat();return _loaded(str(path),st.st_mtime_ns,st.st_size)
    except OSError:return ApiPriceCache.empty()


def latest_rates():
    versions=catalogue()['versions']
    return {model:tuple(row['rates']) for model,row in versions[-1]['rates'].items()} if versions else {}


def price_history(manual,builtin):
    # No check timestamps in the pricing identity: unchanged daily checks do
    # not invalidate accounting caches. First-seen time is not an official date.
    data=catalogue()
    return dict(versions=data['versions'],manual=manual,builtin=data.get('baseline',builtin))


def historical_rate(model,stamp,history):
    if model in history['manual']:
        values=history['manual'][model]
    else:
        values=history['builtin'].get(model)
        for version in history['versions']:
            if version['observed_at']>stamp:break
            row=version['rates'].get(model)
            if row is not None:values=row['rates']
    return tuple(values) if values is not None and all(v is not None for v in values) else None


class PriceBook:
    """Compile once per projection; event lookups don't reread files/history."""
    def __init__(self,history):
        def valid(values):return tuple(values) if values is not None and all(v is not None for v in values) else None
        self.manual={k:valid(v) for k,v in history['manual'].items()}
        table={k:valid(v) for k,v in history['builtin'].items()}
        self.times=[];self.tables=[table]
        for v in history['versions']:
            table=dict(table);table.update({k:valid(r['rates']) for k,r in v['rates'].items()})
            self.times.append(v['observed_at']);self.tables.append(table)
    def rate(self,model,stamp):
        model=re.sub(r'-\d{4}-\d{2}-\d{2}$','',model.lower())
        return self.manual[model] if model in self.manual else self.tables[bisect_right(self.times,stamp)].get(model)


def shared():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance()
    if not hasattr(app,'_bailong_api_prices'):
        app._bailong_api_prices=OfficialApiPrices(cache_path(),app)
        app.aboutToQuit.connect(app._bailong_api_prices.close)
    return app._bailong_api_prices
