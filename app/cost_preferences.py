"""Local price overrides and display currency; accounting always remains USD."""
import json,math,os,tempfile
from pathlib import Path
_cached=None

def path():return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced'/'cost-pricing.json'
def defaults():return dict(currency='USD',mode='manual',fx=1.,prices={})
def validate(value):
    result=defaults();result.update(value)
    if result['currency'] not in ('USD','CNY','HKD') or result['mode'] not in ('manual','auto'):raise ValueError('请选择有效币种和汇率来源')
    fx=result['fx']
    if isinstance(fx,bool) or not isinstance(fx,(float,int)) or not math.isfinite(fx) or fx<=0:raise ValueError('汇率必须大于 0')
    prices={}
    if not isinstance(result['prices'],dict):raise ValueError('价格表格式不正确')
    for model,values in result['prices'].items():
        if not isinstance(model,str) or not model or len(model)>128 or not isinstance(values,(list,tuple)) or len(values)!=3:raise ValueError('模型价格格式不正确')
        if any(v is not None and (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0) for v in values):raise ValueError('单价需为非负数，留空表示未知')
        prices[model]=list(values)
    result['prices']=prices;return result
def load():
    global _cached
    try:_cached=validate(json.loads(path().read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError):_cached=defaults()
    return _cached
def current():return _cached if _cached is not None else load()
def save(value):
    global _cached
    value=validate(value);target=path();target.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='cost-pricing-',suffix='.tmp',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
        os.replace(name,target)
    finally:
        if Path(name).exists():Path(name).unlink()
    _cached=value;return value
def prices(value=None):
    from project_cost import RATES
    result=dict(RATES)
    from official_api_prices import latest_rates
    for model,values in latest_rates().items():
        if all(v is not None for v in values):result[model]=values
        else:result.pop(model,None)
    for model,values in (load() if value is None else value)['prices'].items():
        if all(v is not None for v in values):result[model]=tuple(values)
        else:result.pop(model,None)
    return result

def price_history(value=None):
    from project_cost import RATES
    from official_api_prices import price_history as history
    return history((load() if value is None else value)['prices'],RATES)
def money(amount,value=None):
    if amount is None:return '—'
    value=current() if value is None else value;currency=value['currency'];fx=1 if currency=='USD' else value['fx']
    prefix={'USD':'$','CNY':'¥','HKD':'HK$'}[currency];amount*=fx
    return prefix+('<0.01' if 0<amount<.01 else f'{amount:,.2f}')
