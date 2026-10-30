"""Bounded, screen-local roaming plans. Pure geometry; no timers or UI access."""
from dataclasses import dataclass
import heapq,math

MODES=('edge','side','zone','window')
LABELS={'edge':'边缘散步','side':'侧边驻留','zone':'手动活动区','window':'窗口避让'}
DEFAULT_ZONE=(.50,.18,.99,.99)

def clean_zone(value):
    try:
        if not isinstance(value,(list,tuple)) or len(value)!=4:raise ValueError
        l,t,r,b=map(float,value)
        if not all(math.isfinite(v) for v in (l,t,r,b)):raise ValueError
        l,t=max(0,min(.95,l)),max(0,min(.95,t));r,b=min(1,max(l+.05,r)),min(1,max(t+.05,b))
        return [l,t,r,b]
    except (TypeError,ValueError):return list(DEFAULT_ZONE)

def contains(p,r):return r[0]<p[0]<r[2] and r[1]<p[1]<r[3]
def clamp(p,r):return (min(r[2],max(r[0],p[0])),min(r[3],max(r[1],p[1])))
def distance(a,b):return math.hypot(a[0]-b[0],a[1]-b[1])
def center_rect(area,footprint=None):
    x,y,w,h=area;width=w*.44
    if footprint is not None:
        # Keep a central protected core on small screens without demanding
        # side gutters narrower than the actual character/following panel.
        width=min(width,max(w*.06,w-2*(footprint[2]-footprint[0]+16)))
    return (x+(w-width)/2,y+h*.24,x+(w+width)/2,y+h*.58)
def inflate(rect,footprint,gap=8):
    l,t,r,b=footprint
    return (rect[0]-r-gap,rect[1]-b-gap,rect[2]-l+gap,rect[3]-t+gap)
def legal_bounds(area,footprint):
    x,y,w,h=area;l,t,r,b=footprint
    bounds=(x-l+8,y-t+8,x+w-r-8,y+h-b-8)
    return bounds if bounds[0]<=bounds[2] and bounds[1]<=bounds[3] else None
def crosses(a,b,r):
    """Open rectangle intersection, including starting inside the rectangle."""
    lo,hi=0.,1.
    for axis in (0,1):
        d=b[axis]-a[axis];low,high=r[axis],r[axis+2]
        if abs(d)<1e-9:
            if not low<a[axis]<high:return False
        else:
            u,v=(low-a[axis])/d,(high-a[axis])/d
            lo=max(lo,min(u,v));hi=min(hi,max(u,v))
    return hi-lo>1e-8 and hi>0 and lo<1

def path_between(start,target,bounds,obstacles):
    """Small rectilinear visibility graph; at most two rectangle obstacles."""
    if any(contains(target,r) for r in obstacles):return None
    xs={start[0],target[0],bounds[0],bounds[2]};ys={start[1],target[1],bounds[1],bounds[3]}
    for r in obstacles:
        xs.update((max(bounds[0],r[0]-2),min(bounds[2],r[2]+2)))
        ys.update((max(bounds[1],r[1]-2),min(bounds[3],r[3]+2)))
    nodes={(x,y) for x in xs for y in ys if bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3] and not any(contains((x,y),r) for r in obstacles)}
    nodes.add(start);nodes.add(target);edges={p:[] for p in nodes}
    for axis,values in ((0,ys),(1,xs)):
        for fixed in values:
            row=sorted((p for p in nodes if p[1-axis]==fixed),key=lambda p:p[axis])
            for a,b in zip(row,row[1:]):
                for p,q in ((a,b),(b,a)):
                    # A manually placed pet may begin in the protected area;
                    # let its first segment leave, never re-enter or stop there.
                    if all(not crosses(p,q,r) or p==start and contains(p,r) and not contains(q,r) for r in obstacles):edges[p].append(q)
    costs={start:0};previous={};queue=[(0,start)]
    while queue:
        cost,p=heapq.heappop(queue)
        if cost!=costs[p]:continue
        if p==target:
            points=[]
            while p!=start:points.append(p);p=previous[p]
            points.reverse();return points
        for q in edges[p]:
            new=cost+distance(p,q)
            if new<costs.get(q,float('inf')):costs[q]=new;previous[q]=p;heapq.heappush(queue,(new,q))
    return None

@dataclass(frozen=True)
class WalkPlan:
    points:tuple
    center:tuple
    fast_cross:bool=False
    wait_factor:float=1.
    mode:str='edge'
    reason:str=''

def plan(position,home,area,footprint,settings,uniform,foreground=None):
    mode=settings.get('wander_mode','edge');mode=mode if mode in MODES else 'edge'
    bounds=legal_bounds(area,footprint);protected=inflate(center_rect(area,footprint),footprint)
    if bounds is None:return WalkPlan((),protected,mode=mode,reason='当前屏幕空间不足')
    horizontal=settings.get('wander_horizontal_only',True);amount=max(.1,min(1,settings.get('move_range',1.)))
    obstacles=[protected];wait=2.4 if mode=='side' else 1.
    if mode=='window' and foreground:
        x,y,w,h=area;l,t,r,b=foreground
        overlap=max(0,min(x+w,r)-max(x,l))*max(0,min(y+h,b)-max(y,t))
        if overlap<w*h*.85:obstacles.append(inflate(foreground,footprint,12))
    active=bounds
    if mode=='zone':
        z=clean_zone(settings.get('wander_zone'));x,y,w,h=area
        zone=(x+z[0]*w,y+z[1]*h,(z[2]-z[0])*w,(z[3]-z[1])*h)
        active=legal_bounds(zone,footprint)
        if active is None:return WalkPlan((),protected,mode=mode,reason='活动区放不下人物和跟随面板')
        # The explicitly drawn area takes priority in free mode. Horizontal
        # mode still never chooses a stop in the visual center.
        if not horizontal:obstacles=[]
    elif mode=='side':
        side=settings.get('wander_side','auto')
        right=side=='right' or side=='auto' and position[0]>(bounds[0]+bounds[2])/2
        band=min((bounds[2]-bounds[0])*.18*amount,max(32,area[2]*.10*amount))
        active=(max(bounds[0],protected[2]+2),bounds[1],bounds[2],bounds[3]) if right else (bounds[0],bounds[1],min(bounds[2],protected[0]-2),bounds[3])
        if active[0]>active[2]:return WalkPlan((),protected,mode=mode,reason='当前侧空间不足')
        active=(max(active[0],active[2]-band),active[1],active[2],active[3]) if right else (active[0],active[1],min(active[2],active[0]+band),active[3])
    if horizontal:
        if not active[1]<=position[1]<=active[3]:return WalkPlan((),protected,mode=mode,reason='当前高度不在活动区内')
        reach=(bounds[2]-bounds[0])*amount
        if mode not in ('side','zone'):active=(max(active[0],home[0]-reach/2),active[1],min(active[2],home[0]+reach/2),active[3]) if amount<.999 else active
        candidates=[(active[0],position[1]),(active[2],position[1])]
        # User explicitly permits quick center crossing. A foreground window
        # is still an obstacle; this permission applies only to the center.
        movement_obstacles=obstacles[1:]
        candidates=[p for p in candidates if not contains(p,protected) and distance(position,p)>16 and not any(contains(p,r) or crosses(position,p,r) and not contains(position,r) for r in movement_obstacles)]
        if not candidates:return WalkPlan((),protected,mode=mode,reason='没有合适的水平落点')
        target=candidates[min(len(candidates)-1,int(uniform(0,len(candidates))))]
        return WalkPlan((target,),protected,crosses(position,target,protected),wait,mode)
    l,t,r,b=active;cx,cy=clamp(position,active)
    reach_x=max(24,(bounds[2]-bounds[0])*amount);reach_y=max(24,(bounds[3]-bounds[1])*amount)
    if mode=='side':
        t=max(t,home[1]-reach_y*.55);b=min(b,home[1]+reach_y*.55)
    candidates=[(l,cy),(r,cy),(cx,t),(cx,b),(l,t),(r,t),(l,b),(r,b),
                (min(r,cx+reach_x),cy),(max(l,cx-reach_x),cy),(cx,min(b,cy+reach_y)),(cx,max(t,cy-reach_y))]
    for left,right in ((l,min(r,protected[0]-2)),(max(l,protected[2]+2),r)):
        if left<=right:candidates.append(((left+right)/2,cy))
    candidates=[p for p in candidates if distance(position,p)>16 and abs(p[0]-position[0])<=reach_x+1 and abs(p[1]-position[1])<=reach_y+1 and not any(contains(p,o) for o in obstacles)]
    # If a manually moved pet starts outside its chosen area, allow one entry
    # journey instead of silently moving the area or teleporting the pet.
    if mode=='zone' and not (l<=position[0]<=r and t<=position[1]<=b):candidates=[clamp(position,active)]
    groups=[[p for p in candidates if abs(p[0]-position[0])>=abs(p[1]-position[1])],[p for p in candidates if abs(p[0]-position[0])<abs(p[1]-position[1])]]
    groups=[g for g in groups if g]
    if not groups:return WalkPlan((),protected,mode=mode,reason='没有合适的边缘落点')
    choice=min(len(groups)-1,int(uniform(0,len(groups))))
    for group in groups[choice:]+groups[:choice]:
        offset=min(len(group)-1,int(uniform(0,len(group))))
        for target in group[offset:]+group[:offset]:
            points=path_between(position,target,bounds,obstacles)
            if points:return WalkPlan(tuple(points),protected,False,wait,mode)
    return WalkPlan((),protected,mode=mode,reason='当前路线被窗口或面板占位挡住')
