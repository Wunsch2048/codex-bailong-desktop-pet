"""Original entrance/body/tail with a small repaired seam and bounded prewarm."""
import threading,zlib,random,math
from PIL import Image
from stream_player import StreamPlayer,PreparedSegment
from decode_runtime import STATS,opened

class SustainedPlayback:
    def __init__(self):
        self.phase=None;self.owner=None;self.profile=None;self.cycles=0;self.exit_requested=False;self.hard_exit_requested=False
        self.warm_stop=None;self.warmer=None;self.warm_ready=threading.Event();self.error=None;self.tail=None
        self.variant=None;self.variant_index=0;self.cycle_speed=1.;self.rng=random.Random();self.seeds={}
    @property
    def active(self):return self.phase is not None
    def begin(self,player,profile,owner,size):
        self.cancel();self.profile=profile;self.owner=owner;self.phase='enter';self.cycles=0;self.exit_requested=False;self.error=None
        self.variant=profile;self.variant_index=0;self.cycle_speed=1.
        self.prewarm(player,size)
        return self._start(player,size)
    def _start(self,player,size):
        p=self.profile;v=self.variant
        spans={'enter':(p['source'],0,p['end'],False),'body':(p['source'],v['start'],p['end'],True),
               'seam':(v['seam'],0,v['seamFrames']-1,True),'exit':(p['source'],p['end']+1,p['sourceFrames']-1,False)}
        path,start,end,cache=spans[self.phase]
        carry=min(.04,max(0,player.playhead-player.next_time)) if player.ended else 0.
        if self.phase=='exit' and self.tail:
            frame=player.adopt(self.tail);self.tail=None
        else:frame=player.start(path,size,(end-start+1)/24,start_frame=start,end_frame=end,cache_loop=cache,seed=self.seeds.get(StreamPlayer.cache_key(path,size,start,end)),cached_frames=self.body_cache(player,size,v) if self.phase=='body' else None)
        player.playhead=carry
        return frame
    def request(self,keep,*,hard=False):
        # Ordinary same-turn semantic changes are speculative until the tail
        # begins. Terminal/lifecycle exits stay latched even if new work arrives.
        if self.phase=='exit':return
        if not keep:
            self.exit_requested=True;self.hard_exit_requested|=hard
        elif not self.hard_exit_requested:self.exit_requested=False
    def speed_factor(self,player):
        if self.phase!='body':return 1.
        duration=(self.profile['end']-self.variant['start']+1)/24
        # Speed is exactly native at each seam; a broad, small modulation in
        # the middle avoids sudden tempo jumps or a jittery random walk.
        t=max(0.,min(1.,player.playhead/max(.001,duration)))
        return 1.+(self.cycle_speed-1.)*math.sin(math.pi*t)**2
    def choices(self,size):
        variants=self.profile.get('variants',[])
        pairs=list(enumerate(variants)) if variants else [(0,self.profile)]
        return sorted(pairs,key=lambda pair:pair[1]['seamFrames'])[:2] if size>=384 else pairs
    def body_start(self,size):
        return min(v['start'] for _,v in self.choices(size))
    def body_cache(self,player,size,variant):
        p=self.profile;cached=player.loop_cache.get(StreamPlayer.cache_key(p['source'],size,self.body_start(size),p['end']))
        if cached is None:return None
        if cached[0][2]>variant['start']:return None
        return tuple(frame for frame in cached if frame[2]>=variant['start'])
    def choose_cycle(self,player,size):
        variants=self.profile.get('variants',[])
        if not variants:return
        choices=self.choices(size)
        if self.variant_index not in [i for i,v in choices]:self.variant_index,self.variant=choices[0]
        if not self.warm_ready.is_set():return
        ready=[]
        for i,v in choices:
            keys=[StreamPlayer.cache_key(self.profile['source'],size,self.body_start(size),v['end']),StreamPlayer.cache_key(v['seam'],size,0,v['seamFrames']-1)]
            if all(player.loop_cache.get(k) is not None for k in keys):ready.append((i,v))
        alternatives=[pair for pair in ready if pair[0]!=self.variant_index]
        if alternatives:self.variant_index,self.variant=self.rng.choice(alternatives)
        elif ready:self.variant_index,self.variant=ready[0]
        # A steady prop is an authored content constraint. Varying its whole
        # clip's tempo cannot create independent finger or facial motion.
        self.cycle_speed=1. if self.profile.get('steadyProp') else self.rng.uniform(.94,1.04)
    def boundary(self,player,size):
        if not self.active:return None,True
        if player.error:
            self.error=player.error;self.cancel();return None,True
        if self.phase=='exit':self.cancel();return None,True
        if self.phase=='seam':self.phase='body'
        elif self.exit_requested:
            if self.tail and self.tail.error:
                self.error=self.tail.error;self.cancel();return None,True
            if self.tail and not self.tail.ready.is_set():self.phase='seam';self.cycles+=1
            else:self.phase='exit'
        else:self.choose_cycle(player,size);self.phase='seam';self.cycles+=1
        try:return self._start(player,size),False
        except (OSError,ValueError):
            self.error='segment_failed';self.cancel();return None,True
    def prewarm(self,player,size):
        self.stop_warm();stop=threading.Event();self.warm_stop=stop;p=self.profile
        ready=threading.Event();self.warm_ready=ready
        if self.phase=='exit':ready.set();return
        if self.tail:self.tail.close()
        tail=self.tail=PreparedSegment(p['source'],size,p['end']+1,p['sourceFrames']-1,autostart=False)
        choices=[v for _,v in self.choices(size)];jobs=[]
        # Small seams are prepared before the source reader waits on its tail queue.
        for v in choices:
            job=(v['seam'],0,v['seamFrames']-1)
            if job not in jobs:jobs.append(job)
        jobs.append((p['source'],self.body_start(size),p['end']))
        cache=player.loop_cache;seeds={};self.seeds=seeds
        def run():
            try:
                if stop.is_set():return
                cache.begin(('sustained-working-set',size),reserve=cache.limit,cancel=stop.is_set)
                for path,start,end in jobs:
                    if stop.is_set():return
                    key=StreamPlayer.cache_key(path,size,start,end);existing=cache.get(key)
                    source=path==p['source']
                    if existing is not None:
                        seeds[key]=existing[0][:2]
                        if source:
                            for v in choices:seeds[StreamPlayer.cache_key(path,size,v['start'],end)]=existing[v['start']-start][:2]
                        if not source:continue
                    entry_limit=cache.limit*2//3 if source and p.get('variants') else cache.entry_limit
                    collect=existing is None and cache.begin(key,reserve=0,cancel=stop.is_set)
                    packed=[];cost=0;opened(path)
                    with Image.open(path) as image:
                        if existing is None:
                            for index in range(start,end+1):
                                if stop.is_set():return
                                image.seek(index);image.load();STATS.add('decoded_frames')
                                raw=image.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS).tobytes()
                                data=zlib.compress(raw,1);delay=max(.015,float(image.info.get('duration',1000/24))/1000)
                                if index==start:seeds[key]=(data,delay)
                                if source:
                                    for v in choices:
                                        if index==v['start']:seeds[StreamPlayer.cache_key(path,size,index,end)]=(data,delay)
                                if collect:
                                    cost+=len(data)
                                    if cost>entry_limit or cost+cache.stats()['bytes']>cache.limit:cache.skip(key);packed=[];collect=False
                                    else:packed.append((data,delay,index))
                            if packed and not stop.is_set():cache.put(key,packed,cost,entry_limit=entry_limit,cancel=stop.is_set)
                        if source:
                            ready.set();STATS.add('shared_body_tail_reads')
                            tail.produce(image,stop.is_set)
            except (OSError,ValueError) as error:
                if not stop.is_set():tail.fail(error)
            finally:ready.set()
        worker=threading.Thread(target=run,name='pet-segment-prewarm',daemon=True)
        self.warmer=worker;tail.thread=worker
        with STATS.lock:STATS.workers.add(worker)
        worker.start()
    def stop_warm(self):
        if self.warm_stop:self.warm_stop.set()
        self.warmer=None;self.warm_stop=None
    def cancel(self):
        if self.tail:self.tail.close();self.tail=None
        self.stop_warm();self.phase=None;self.owner=None;self.profile=None;self.variant=None;self.seeds={};self.exit_requested=False;self.hard_exit_requested=False
