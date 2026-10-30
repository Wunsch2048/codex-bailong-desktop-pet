"""Semantic theme values, resolved only on selection; no Qt or polling."""
import re
from functools import lru_cache
from theme_catalog import PRESETS,BAILONG_COLORS

NAMES={'bailong':'白龙紫',**{k:v['name'] for k,v in PRESETS.items()},'custom':'自定义'}
THEME_KEYS=('theme','theme_accent','theme_surface','theme_ink')
BASE=dict(surface='#fcfafc',panel='#f5f2f7',ink='#393343',muted='#706879',accent='#8b78a6',accentText='#75618d',accentOn='#ffffff',selected='#e8dff0',track='#e4dfea',border='#ded2e7',secondary='#8297a5',chart='#936a83',pill='#302a3c',onPill='#f7f3fb',pillMuted='#d6c5ed',pillTrack='#494052',pillAccent='#d6c5ed',danger='#ce2c31',dangerBg='#ffebec',success='#218358',successBg='#e6f6eb',warning='#b18e62',tertiary='#aa8194')
BASE.update(BAILONG_COLORS)
ROLE_GROUPS={
 'surface':'fcfafc fffdff faf8fc',
 'panel':'f5f2f7 f5f0f8 f5f1f7 f1ecf6 f3eef7 f0eaf5 f1ebf7 f0ebf5 f2edf6 fbf4f7 efebf2',
 'selected':'e8dff0 eee8f3 eee7f5 e4dbea e9e1ef e6dcec e8def0 eee7f4 eee6f4 eae1f2 f0e9f6 ebe2f2 f0e9f5 eae3f1 e9e0f1 e9dce5 e9e0f0 e7deed eae2f2 eee8f5 ede7f2 eee7f3 ece6f2 e9e1f0 e3d7ef ead6e1',
 'border':'e0d9e6 ded2e7 e0d3eb dacee6 dfcfeb c1b4cc dacbe8 c7b7d7 e3d9ed cfc0de c8b5dc d8cde3 c8bbd7 d3b8c7 e6dfec',
 'ink':'393343 514360 30203e 472c5d 352840 332644 493b5b 665078 5f4c77',
 'muted':'706879 62576e 786d84 8b8195 9b93a4 8e819c',
 'accentText':'75618d 76618f 806095 66517e 76638c',
 'accent':'8b78a6 8d76ab a087b3 c5add9 b19bc9 a47bc9 927aaf a89ab6',
 'secondary':'8297a5 587586 577c78 7d9c94 506e66',
 'warningText':'b18e62 9b7b4c a19170',
 'danger':'915e74 98566d ac6e85 89566c 885c70 a37688 aa8194 ce2c31',
 'dangerBg':'f3eaf0 ffebec ffdbdc ffcdce',
 'success':'218358', 'successBg':'e6f6eb d6f1df c4e8d1',
 'chart':'936a83', 'track':'e4dfea b3a5cb 9b86b0',
 'pill':'302a3c', 'pillTrack':'494052 3c393f', 'onPill':'f7f3fb',
 'pillAccent':'d6c5ed b1a9ff 70b8ff', 'accentOn':'ffffff'}
_roles={'#'+h:role for role,values in ROLE_GROUPS.items() for h in values.split()}
_roles['#7181a3']='accent';_roles['#ff949d']='danger'
_roles['#5f4c77']='primaryPressed'
_roles['#506e66']='success'  # Connection text is semantic, not a decorative secondary colour.
_current='bailong';_palette=dict(BASE);_translation={};_revision=0

def theme_id(value):return value if isinstance(value,str) and value in NAMES else 'bailong'
def current():return _current
def revision():return _revision
def palette():return _palette
def luminance(h):
    a=[int(h[i:i+2],16)/255 for i in (1,3,5)];a=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in a]
    return sum(v*w for v,w in zip(a,(.2126,.7152,.0722)))
def contrast(a,b):
    a,b=luminance(a),luminance(b);return(max(a,b)+.05)/(min(a,b)+.05)
def mix(a,b,f):return '#'+''.join(f'{round(int(a[i:i+2],16)*(1-f)+int(b[i:i+2],16)*f):02x}' for i in (1,3,5))
def valid_hex(value):return isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value) is not None
def readable(value,backgrounds,target,minimum):
    """Nearest mix toward the theme's own ink that works on every listed surface."""
    if min(contrast(value,bg) for bg in backgrounds)>=minimum:return value
    # A tiny palette operation, cached by _resolved/weekly result. No Qt/IO.
    for step in range(1,101):
        adjusted=mix(value,target,step/100)
        if min(contrast(adjusted,bg) for bg in backgrounds)>=minimum:return adjusted
    return max((target,'#ffffff','#000000'),key=lambda c:min(contrast(c,bg) for bg in backgrounds))

def readable_palette(source):
    p=dict(source);ink=p['ink']
    for bg in ('panel','selected'):p[bg]=readable(p[bg],(ink,),p['surface'],4.5)
    surfaces=(p['surface'],p['panel'],p['selected'])
    p['ink']=readable(ink,surfaces,ink,4.5)
    p['muted']=readable(p['muted'],surfaces,ink,4.5)
    p['accentText']=readable(p['accentText'],surfaces,ink,4.5)
    p['warningText']=readable(p['warning'],surfaces,ink,4.5)
    p['warning']=readable(p['warning'],(p['panel'],p['surface']),ink,3)
    p['success']=readable(p['success'],surfaces,ink,4.5)
    success_bgs=tuple(mix(p['successBg'],ink,f) for f in (0,.07,.14))
    success_ink=max(('#ffffff','#111113'),key=lambda c:min(contrast(c,bg) for bg in success_bgs))
    p['successBadge']=readable(p['success'],success_bgs,success_ink,4.5)
    p['danger']=readable(p['danger'],surfaces,ink,4.5)
    danger_bgs=tuple(mix(p['dangerBg'],ink,f) for f in (0,.07,.14))
    danger_ink=max(('#ffffff','#111113'),key=lambda c:min(contrast(c,bg) for bg in danger_bgs))
    p['dangerBadge']=readable(p.get('dangerBadge',p['danger']),danger_bgs,danger_ink,4.5)
    # PRIMARY and its hover are text-readable colors; choose their shared ink.
    p['accentOn']=max(('#ffffff','#111113'),key=lambda c:contrast(c,p['accentText']))
    p['primaryPressed']=readable(mix(p['accentText'],ink,.12),(*surfaces,p['accentOn']),p['accentText'],4.5)
    p['switchOffKnob']=readable(ink,(p['border'],),ink,3)
    p['switchOnKnob']=readable(p['accentOn'],(p['accentText'],),ink,3)
    p['onPill']=readable(p['onPill'],(p['pill'],),max(('#ffffff','#111113'),key=lambda c:contrast(c,p['pill'])),4.5)
    p['pillMuted']=readable(p['pillMuted'],(p['pill'],),p['onPill'],4.5)
    for role in ('pillAccent','ringWarn','ringDanger'):
        p[role]=readable(p.get(role,p['pillAccent']),(p['pillTrack'],p['pill']),p['onPill'],3)
    chart_roles=('chart','chartSecondary','tertiary','warning','accent','muted')
    p['chartSeries']=tuple(readable(p.get(role,p['secondary']),(p['panel'],p['surface']),ink,3) for role in chart_roles)
    p['chart']=p['chartSeries'][0];p['chartSecondary']=p['chartSeries'][1]
    return p

def values(key,custom=None):
    key=theme_id(key)
    if key!='custom':return dict(_resolved(key,'','',''))
    custom=custom or {};colors=tuple(custom.get(k,BASE[k[6:]]) for k in THEME_KEYS[1:])
    if not all(valid_hex(c) for c in colors):raise ValueError('颜色请使用 #RRGGBB 格式。')
    return dict(_resolved(key,*colors))

@lru_cache(maxsize=128)
def _resolved(key,accent,surface,ink):
    return readable_palette(_raw_values(key,dict(theme_accent=accent,theme_surface=surface,theme_ink=ink)))

def _raw_values(key,custom=None):
    key=theme_id(key)
    if key=='bailong':return dict(BASE)
    if key!='custom':return dict(BASE,**PRESETS[key]['colors'])
    custom=custom or {};surface=custom.get('theme_surface',BASE['surface']);accent=custom.get('theme_accent',BASE['accent']);ink=custom.get('theme_ink',BASE['ink'])
    if not all(valid_hex(x) for x in (surface,accent,ink)):raise ValueError('颜色请使用 #RRGGBB 格式。')
    if contrast(surface,ink)<4.5:raise ValueError('正文与背景对比度不足，请调整颜色后应用。')
    dark=luminance(surface)<.15;p=dict(_raw_values('night' if dark else 'mist'))
    p.update(surface=surface,ink=ink,accent=accent,chart=accent,panel=mix(surface,accent,.055),selected=mix(surface,accent,.17),track=mix(surface,accent,.25),border=mix(surface,ink,.18),muted=mix(ink,surface,.25),accentOn='#ffffff' if contrast(accent,'#ffffff')>=4.5 else '#1c2024')
    text=accent
    for _ in range(24):
        if contrast(text,surface)>=4.5:break
        text=mix(text,ink,.15)
    p['accentText']=text;p['pillAccent']=mix(accent,'#ffffff',.35)
    p['chartSecondary']=p['secondary'];p['dangerBadge']=p['danger'];return p
def activate(key,custom=None):
    global _current,_palette,_translation,_revision
    key=theme_id(key);p=values(key,custom)
    if key==_current and p==_palette:return False
    _current=key;_palette=p;_translation={old:p[role] for old,role in _roles.items()}
    _revision+=1;stylesheet.cache_clear();status_rgb.cache_clear();week_color.cache_clear();return True
def color(value):
    if isinstance(value,str):return _translation.get(value.lower(),value)
    return value

def chart_color(index=0,original='#8b78a6'):
    return _palette['chartSeries'][index%6]

def quota_ring_color(remaining):
    p=_palette
    if remaining is not None and remaining<=15:return p.get('ringDanger',p['danger'])
    if remaining is not None and remaining<=35:return p.get('ringWarn',p['warning'])
    return p['pillAccent']

def tray_palette():
    # Tiny tray rings need a dark center/track even when the theme's capsule is light.
    if _current=='cyber':return dict(surface='#14120b',track='#494020',five='#ffe629',week='#ffe629',low='#ff9592')
    if _current=='starfield':return dict(surface='#182638',track='#34445a',five='#8db7ed',week='#ff9a76',low='#ff737b')
    return dict(surface=_palette['pill'],track=color('#3c393f'),five=color('#b1a9ff'),week=color('#70b8ff'),low=color('#ff949d'))

# Dedicated small-glyph colours: do not borrow muted text or pastel pill fills.
# Pairs are light-surface / dark-surface, retaining each theme's colour family.
STATUS_COLORS={
 'bailong':(('#6e56cf','#12a594','#e54666'),('#9e8cfc','#0bd8b6','#ff5c9b')),
 'mist':(('#205d9e','#ab6400','#60646c'),('#7ce2fe','#ffc53d','#b0b4ba')),
 'jade':(('#208368','#ad5700','#0894b3'),('#1fd8a4','#ffb381','#4ccce6')),
 'amber':(('#e5484d','#00a2c7','#f76b15'),('#ff6369','#4ccce6','#ffb224')),
 'night':(('#8e4ec6','#d6409f','#3e63dd'),('#d19dff','#ff92ce','#8da4ef')),
 'cyber':(('#ffe629','#00a2c7','#f76b15'),('#ffe629','#4ccce6','#ff801f')),
 'starfield':(('#3e63dd','#ab6400','#d64f00'),('#8da4ef','#ffc53d','#ff801f')),
 'division':(('#f76b15','#80838d','#e5484d'),('#ff801f','#d9d9e0','#ff6369')),
}
@lru_cache(maxsize=2)
def status_rgb(island=False):
    """Cache tiny-glyph contrast on theme changes, never on animation frames."""
    p=_palette;bg=p['pill' if island else 'surface'];ink=p['onPill' if island else 'ink']
    result=[]
    colors=STATUS_COLORS.get(_current)
    if colors:colors=colors[int(luminance(bg)<.15)]
    else:
        import colorsys
        colors=[]
        for role in ('accent','secondary','tertiary'):
            raw=p[role];rgb=[int(raw[i:i+2],16)/255 for i in (1,3,5)]
            h,s,v=colorsys.rgb_to_hsv(*rgb)
            colors.append('#'+''.join(f'{round(c*255):02x}' for c in colorsys.hsv_to_rgb(h,max(s,.55),max(v,.75))))
    for value in colors:
        for _ in range(24):
            if contrast(value,bg)>=3:break
            value=mix(value,ink,.15)
        result.append(tuple(int(value[i:i+2],16) for i in (1,3,5)))
    return tuple(result)
@lru_cache(maxsize=256)
def stylesheet(text):
    return re.sub(r'#[0-9a-fA-F]{6}\b',lambda m:color(m[0]),text) if _translation else text
@lru_cache(maxsize=256)
def week_color(remaining):
    """Shared actual-balance colour, independent of reveal progress."""
    p=_palette;high=p['accent']
    if contrast(high,p['panel'])<2.2:high=p['accentText']
    stops=((0,p['danger']),(15,p['danger']),(35,p['warning']),(65,high),(100,high))
    for (a,x),(b,y) in zip(stops,stops[1:]):
        if remaining<=b:return readable(mix(x,y,max(0.,min(1.,(remaining-a)/(b-a)))),(p['panel'],p['surface']),p['ink'],3)
    return high

# Initialise semantic colors before paint modules import QColor references.
_palette=values('bailong');_translation={old:_palette[role] for old,role in _roles.items()}
