"""Desktop configuration, action arbitration and bounded physics (no Qt)."""
import copy
import json
import math
import os
import time
from pathlib import Path

from version import VERSION
DEFAULTS=dict(schema=2,ui_animation_mode='quality',theme='bailong',theme_accent='#8b78a6',theme_surface='#fcfafc',theme_ink='#393343',scale=1.0,playback_speed=1.0,action_gap=2.0,
    random_interval=25.0,move_speed=55.0,move_range=1.0,wander_range_revision=1,wander_horizontal_only=True,wander_home=None,wander_mode='edge',wander_side='auto',wander_zone=[.50,.18,.99,.99],drag_physics=True,edge_docking=True,
    on_top=True,video_fullscreen_yield=True,fullscreen_yield_mode='video',no_move=False,mouse_through=False,wandering=True,random_actions=True,
    commentary=True,sound=True,bubble=True,quota_visible=True,quota_decline_threshold=10.,quota_increase_threshold=15.,self_talk=False,character_visible=True,card_anchor=None,panel_detached=False,codex_exit=False,
    status_actions=True,status_action_interval=12.,status_response_revision=2,update_checks=True,token_chart_range='all',bubble_mode='auto',
    capsule_action='chatgpt',capsule_website='',talk_min=30.0,talk_max=90.0,talk_quiet=True,
    talk_lines=['忙完记得休息一下。','我在这里陪着你。','今天也一起把小事做好吧。'],
    facing=1,character='builtin',character_preferences={},chat_follow=False)

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    import uuid
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        for attempt in range(3):
            try:os.replace(temp,path);break
            except PermissionError:
                if attempt==2:raise
                time.sleep(.005*(attempt+1))
    finally:temp.unlink(missing_ok=True)

def normalized(raw):
    out=copy.deepcopy(DEFAULTS);out.update(raw if isinstance(raw,dict) else {})
    if out.get('ui_animation_mode') not in ('performance','quality'):out['ui_animation_mode']='quality'
    from theme_registry import theme_id,valid_hex
    out['theme']=theme_id(out.get('theme'))
    for key in ('theme_accent','theme_surface','theme_ink'):
        if not valid_hex(out.get(key)):out[key]=DEFAULTS[key]
    if out['theme']=='custom':
        from theme_registry import values
        try:values('custom',out)
        except ValueError:out['theme']='bailong'
    # A saved value equal to an older default may still be a deliberate choice.
    # New defaults apply to absent keys, never overwrite valid saved tuning.
    out['wander_range_revision']=1
    from roaming import MODES,clean_zone
    if out.get('wander_mode') not in MODES:out['wander_mode']='edge'
    if out.get('wander_side') not in ('auto','left','right'):out['wander_side']='auto'
    out['wander_zone']=clean_zone(out.get('wander_zone'))
    out['status_response_revision']=2
    for k,lo,hi in [('scale',.4,2.5),('playback_speed',.25,3),('action_gap',0,60),
        ('random_interval',3,600),('move_speed',10,300),('move_range',.1,1),
        ('talk_min',5,3600),('talk_max',5,7200),('status_action_interval',8,120),
        ('quota_decline_threshold',1,100),('quota_increase_threshold',1,100)]:
        try:v=float(out[k]);out[k]=min(hi,max(lo,v)) if math.isfinite(v) else DEFAULTS[k]
        except (TypeError,ValueError):out[k]=DEFAULTS[k]
    for k,v in DEFAULTS.items():
        if isinstance(v,bool):out[k]=out[k] if isinstance(out[k],bool) else v
    home=out.get('wander_home')
    try:
        if not isinstance(home,dict) or not isinstance(home.get('screen'),str):raise ValueError
        rx,ry=float(home['rx']),float(home['ry'])
        if not math.isfinite(rx) or not math.isfinite(ry):raise ValueError
        out['wander_home']=dict(screen=home['screen'][:128],rx=max(0,min(1,rx)),ry=max(0,min(1,ry)))
    except (KeyError,TypeError,ValueError):out['wander_home']=None
    out['talk_max']=max(out['talk_min'],out['talk_max'])
    out['talk_lines']=[str(s)[:500] for s in out['talk_lines'][:200]] if isinstance(out['talk_lines'],list) else DEFAULTS['talk_lines'][:]
    out['facing']=-1 if out['facing']==-1 else 1
    if out['token_chart_range'] not in ('all','30d','7d','day'):out['token_chart_range']='all'
    if isinstance(raw,dict) and 'fullscreen_yield_mode' not in raw:
        out['fullscreen_yield_mode']='video' if raw.get('video_fullscreen_yield',True) else 'off'
    if out.get('fullscreen_yield_mode')=='all':out['fullscreen_yield_mode']='game_video'
    if out.get('fullscreen_yield_mode') not in ('off','video','game_video'):
        out['fullscreen_yield_mode']='video' if out.get('video_fullscreen_yield',True) else 'off'
    # Keep the pre-mode key as a compatibility mirror for older diagnostics.
    out['video_fullscreen_yield']=out['fullscreen_yield_mode']=='video'
    if out['bubble_mode'] not in ('auto','mini','minimal'):out['bubble_mode']='auto'
    from quick_actions import action_info
    out['capsule_action']=action_info(out['capsule_action'])[0]
    out['capsule_website']=str(out['capsule_website'] or '')[:2048]
    if out['capsule_action']=='website':
        from quick_actions import website_url
        try:out['capsule_website']=website_url(out['capsule_website'])
        except ValueError:out['capsule_action']='chatgpt'
    if not isinstance(out['character_preferences'],dict):out['character_preferences']={}
    out['schema']=2
    return out

PRIORITY={'idle':0,'turn':1,'walk':1,'variant':2,'reaction':2,'click':5,'quota':5,'task':7,'landing':8,'throw':9,'drag':10}
class ActionGate:
    def __init__(self):self.state='idle';self.pending=None
    def request(self,state,item=None,force=False):
        if force or PRIORITY.get(state,2)>=PRIORITY.get(self.state,2):
            self.state=state;return True
        if state=='task':self.pending=(state,item)
        return False
    def finish(self):
        pending=self.pending;self.pending=None;self.state='idle';return pending

def physics_step(x,y,vx,vy,dt,bounds):
    dt=min(.05,max(0,dt));left,top,right,bottom=bounds
    x+=vx*dt;y+=vy*dt
    if x<left:x=left;vx=abs(vx)*.45
    if x>right:x=right;vx=-abs(vx)*.45
    if y<top:y=top;vy=abs(vy)*.45
    if y>bottom:y=bottom;vy=-abs(vy)*.45
    drag=math.exp(-3.8*dt);vx*=drag;vy*=drag
    return x,y,vx,vy,math.hypot(vx,vy)<15

def relative_position(x,y,w,h,area,name):
    left,top,aw,ah=area
    return dict(screen=name,rx=max(0,min(1,(x-left)/max(1,aw-w))),ry=max(0,min(1,(y-top)/max(1,ah-h))))

def restore_position(saved,w,h,area):
    left,top,aw,ah=area
    return round(left+max(0,aw-w)*max(0,min(1,float(saved.get('rx',.85))))),round(top+max(0,ah-h)*max(0,min(1,float(saved.get('ry',.85)))))


def local_roam_bounds(home,size,area,amount,horizontal_only):
    """Use the screen width for full horizontal roam, or a local free corridor."""
    left,top,width,height=area;pet_width,pet_height=size
    minimum_x=left+8;maximum_x=max(minimum_x,left+width-pet_width-8)
    minimum_y=top+8;maximum_y=max(minimum_y,top+height-pet_height-8)
    anchor_x=min(maximum_x,max(minimum_x,home[0]))
    anchor_y=min(maximum_y,max(minimum_y,home[1]))
    if horizontal_only:
        span=(maximum_x-minimum_x)*max(.1,min(1,amount))
        start=max(minimum_x,min(anchor_x-span/2,maximum_x-span))
        return (start,anchor_y,start+span,anchor_y)
    reach_x=max(24,width*.22*amount)
    reach_y=max(16,height*.10*amount)
    return (max(minimum_x,anchor_x-reach_x),max(minimum_y,anchor_y-reach_y),
            min(maximum_x,anchor_x+reach_x),min(maximum_y,anchor_y+reach_y))


def local_roam_target(position,bounds,speed,horizontal_only,uniform,amount=.75):
    """Stop horizontal strolls at corridor edges; keep free movement local."""
    x,y=position;left,top,right,bottom=bounds
    if horizontal_only:
        width=right-left
        if width<48:return None
        edge=min(140,max(36,width*.12))
        if x<=left+edge:side='right' if uniform(0,1)<.35 else 'left'
        elif x>=right-edge:side='left' if uniform(0,1)<.35 else 'right'
        else:side='left' if x-left<right-x else 'right'
        zone=(left,min(right,left+edge)) if side=='left' else (max(left,right-edge),right)
        tx=uniform(*zone)
        if abs(tx-x)<24:
            tx=max(zone,key=lambda candidate:abs(candidate-x))
            if abs(tx-x)<24:tx=right if side=='left' else left
        return (tx,y) if abs(tx-x)>=24 else None
    travel=max(48,speed*(1+4*max(.1,min(1,amount))))
    start_x,end_x=max(left,x-travel),min(right,x+travel)
    if start_x>end_x:start_x=end_x=left if x<left else right
    tx=uniform(start_x,end_x)
    if abs(tx-x)<24:tx=start_x if abs(start_x-x)>abs(end_x-x) else end_x
    start_y,end_y=max(top,y-travel*.5),min(bottom,y+travel*.5)
    if start_y>end_y:start_y=end_y=top if y<top else bottom
    ty=uniform(start_y,end_y)
    return (tx,ty) if math.hypot(tx-x,ty-y)>=24 else None
