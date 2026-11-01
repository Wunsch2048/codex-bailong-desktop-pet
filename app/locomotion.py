"""Forward-only entrance, authored step/wing cycle and natural return to idle.

Use the existing six-frame decoder. Prepare a body, tail and short seam off the GUI
thread; a late reader retains the last valid frame rather than blocking input.
"""
from stream_player import PreparedSegment

APPROVED_WALK_SOURCE='5af83f299cf8b8920985ffbc337e6529919ba53e6217f2221033f813c8a3b5e8'

def travel_speed(item,base):
    """Match displacement to the selected action, never to left/right facing."""
    return min(300,base*1.6) if item and item.get('movementKind')=='run' else base

def selection(items,dx,dy,prefer_run=False):
    kind='flight' if abs(dy)>.5 else 'walk';direction='left' if dx<0 else 'right'
    if kind=='walk' and prefer_run:
        run=next((x for x in items if x.get('movementKind')=='run' and x.get('travelDirection') in (direction,'both') and isinstance(x.get('locomotion'),dict)),None)
        if run:return run
    return next((x for x in items if x.get('movementKind')==kind and x.get('travelDirection') in (direction,'both') and isinstance(x.get('locomotion'),dict)),None)

def profile(item):
    p=item.get('locomotion')
    if not isinstance(p,dict):return None
    start,end,count,move_start,fps=(p.get(k) for k in ('start','end','sourceFrames','moveStart','fps'))
    if any(not isinstance(v,int) or isinstance(v,bool) for v in (start,end,count,move_start,fps)) or not 0<=move_start<=start<end<count-1 or fps not in (24,30) or count>2000 or p.get('forwardOnly') is not True:
        raise ValueError('移动动画分段无效')
    if p.get('seamFile') and (type(p.get('seamFrames')) is not int or not 1<=p['seamFrames']<=24):raise ValueError('移动动画衔接无效')
    if 'entryEnd' in p and (type(p['entryEnd']) is not int or not 0<=p['entryEnd']<=end):raise ValueError('移动动画起步范围无效')
    if 'interruptOnStop' in p and type(p['interruptOnStop']) is not bool:raise ValueError('移动动画停止方式无效')
    result=dict(p)
    # The published, user-approved 339-frame walk turns front at frame 281.
    # Keep those frames in the one-shot return, not in every long-distance lap.
    # Normalize the exact legacy descriptor so existing HD/light downloads work
    # without replacing their bytes or changing unrelated/custom characters.
    approved=item.get('userApprovedSource')
    if (item.get('id') in ('move01left','move01right') and isinstance(approved,dict) and
        approved.get('sha256')==APPROVED_WALK_SOURCE and
        (start,end,count,move_start,fps,p.get('entryEnd'))==(96,292,339,36,24,95)):
        result['end']=280
    return result

class Locomotion:
    def __init__(self):self.phase=None;self.body=None;self.tail=None;self.seam=None;self.seam_path=None;self.stopping=False;self.cycles=0;self.error=None
    @property
    def active(self):return self.phase is not None
    def begin(self,player,path,size,item,root=None):
        self.cancel();self.p=profile(item)
        if self.p is None:raise ValueError('缺少移动动画分段')
        self.path=path;self.phase='enter';self.stopping=False;self.cycles=0;self.error=None
        self.cache=getattr(player,'loop_cache',None)
        self.seam_path=None
        if self.p.get('seamFile'):
            from material_store import checked
            if root is None:raise ValueError('缺少移动素材根目录')
            self.seam_path=checked(root,self.p['seamFile'])
        self._prepare(size)
        return player.start(path,size,item['durationMs']/1000,end_frame=self.p.get('entryEnd',self.p['end']))
    def _prepare(self,size):
        p=self.p
        if self.body:self.body.close()
        if self.tail:self.tail.close()
        if self.seam:self.seam.close()
        self.body=PreparedSegment(self.path,size,p['start'],p['end'],cache=self.cache)
        self.tail=PreparedSegment(self.path,size,p['end']+1,p['sourceFrames']-1)
        self.seam=self._prepare_seam(size) if self.seam_path else None
    def _prepare_seam(self,size):
        p=self.p
        # Authored endpoints already play in the original body. Present only
        # the bridge's interior, otherwise both feet pause twice per lap.
        trim=p.get('exactSeamEndpoints') is True and p['seamFrames']>=3
        return PreparedSegment(self.seam_path,size,1 if trim else 0,p['seamFrames']-2 if trim else p['seamFrames']-1,cache=self.cache)
    def moving(self,player):
        return self.active and not self.stopping and (self.phase=='seam' or self.phase in ('enter','body') and player.frame_index>=self.p['moveStart']) and not player.ended
    def request_stop(self):self.stopping=True
    def poll_stop(self,player,size):
        """Long source clips may hand off to their return without finishing a lap.

        This opt-in changes playback boundaries, never source frame order or
        timing. A late prefetch keeps the current animation running on the GUI.
        """
        if not (self.active and self.stopping and self.p.get('interruptOnStop') is True and self.phase in ('enter','body')):return None
        if self.tail.size!=size:self._prepare(size)
        if not self.tail.ready.is_set():return None
        if self.tail.error:
            player.error=self.tail.error;player.ended=True;return None
        try:frame=player.adopt(self.tail,continuous=False)
        except (OSError,ValueError):
            player.error='movement_segment_failed';player.ended=True;return None
        self._entered_exit();return frame
    def _entered_exit(self):
        self.phase='exit';self.tail=None
        if self.body:self.body.close();self.body=None
        if self.seam:self.seam.close();self.seam=None
    def boundary(self,player,size):
        if not self.active:return None,True
        if player.error:
            self.error=player.error;self.cancel();return None,True
        if self.phase=='exit':self.cancel();return None,True
        if self.body.size!=size or self.tail.size!=size:self._prepare(size)
        if self.phase=='seam':kind='body'
        elif self.stopping:kind='exit'
        else:kind='seam' if self.seam_path else 'body'
        next_segment={'body':self.body,'exit':self.tail,'seam':self.seam}[kind]
        if not next_segment.ready.is_set():return None,False
        if next_segment.error:
            self.error=next_segment.error;self.cancel();return None,True
        try:frame=player.adopt(next_segment,continuous=True)
        except (OSError,ValueError):
            self.error='movement_segment_failed';self.cancel();return None,True
        if kind=='exit':
            self._entered_exit()
        elif kind=='seam':
            self.phase='seam';self.seam=self._prepare_seam(size)
        else:
            self.phase='body';self.cycles+=1
            self.body=PreparedSegment(self.path,size,self.p['start'],self.p['end'],cache=self.cache)
        return frame,False
    def cancel(self):
        for part in (self.body,self.tail,self.seam):
            if part:part.close()
        self.body=None;self.tail=None;self.seam=None;self.phase=None;self.stopping=False
