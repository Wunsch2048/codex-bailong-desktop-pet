"""Six-frame decoder with a cumulative presentation clock and live resizing.

The first frame is presented exactly once. An adaptive GUI wake follows the
cumulative clock, without adding rounding drift to each 41/42 ms source frame.
Use perf_counter here: Windows Python 3.11 monotonic is a coarse GetTickCount64.
Business-state timestamps stay in their existing independent monotonic domain.
"""
import queue
import threading
import time
import zlib
from collections import OrderedDict
from pathlib import Path
from PIL import Image
from PySide6.QtGui import QImage,QPixmap
from loop_cache import DecodedLoopCache
from decode_runtime import STATS,opened

class PreparedSegment:
    """Decode a tail ahead of time; one first frame plus a six-frame queue."""
    def __init__(self,path,size,start,end,autostart=True,cache=None):
        self.path=Path(path);self.size=size;self.start=start;self.end=end;self.ready=threading.Event()
        self.cache=cache;self.cache_key=(str(self.path),size,self.path.stat().st_mtime_ns,start,end) if cache is not None else None
        self.stop=threading.Event();self.frames=queue.Queue(6);self.first=None;self.error=None
        self.thread=None
        def decode():
            try:
                cached=self.cache.get(self.cache_key) if self.cache is not None else None
                if cached is not None:
                    packed,delay,index=cached[0];self.first=(zlib.decompress(packed),delay,index);self.ready.set()
                    for packed,delay,index in cached[1:]:
                        if not self.emit((zlib.decompress(packed),delay,index)):return
                    self.emit((None,0,None));return
                opened(Path(path))
                with Image.open(path) as image:
                    self.produce(image)
            except Exception as error:
                self.fail(error)
        if autostart:self.thread=STATS.start(decode,'pet-tail-prefetch')
    def emit(self,value,cancel=lambda:False):
        while not self.stop.is_set() and not cancel():
            try:self.frames.put(value,timeout=.02);return True
            except queue.Full:pass
        return False
    def fail(self,error):
        self.error=type(error).__name__;self.ready.set();self.emit((None,0,self.error))
    def produce(self,image,cancel=lambda:False):
        if not 0<=self.start<=self.end<image.n_frames:raise ValueError('动画帧范围超出素材')
        collect=self.cache is not None and self.cache.begin(self.cache_key,cancel=self.stop.is_set)
        packed_frames=[];packed_size=0
        for i in range(self.start,self.end+1):
            if self.stop.is_set() or cancel():return
            image.seek(i);image.load();STATS.add('decoded_frames')
            raw=image.convert('RGBA').resize((self.size,self.size),Image.Resampling.LANCZOS).tobytes()
            frame=(raw,max(.015,float(image.info.get('duration',1000/24))/1000),i)
            if collect:
                packed=zlib.compress(raw,1);packed_size+=len(packed)
                if packed_size>self.cache.entry_limit:self.cache.skip(self.cache_key);packed_frames.clear();collect=False
                else:packed_frames.append((packed,frame[1],i))
            if i==self.start:self.first=frame;self.ready.set()
            elif not self.emit(frame,cancel):return
        if collect and not cancel():self.cache.put(self.cache_key,packed_frames,packed_size,cancel=self.stop.is_set)
        self.emit((None,0,None),cancel)
    def close(self):
        self.stop.set();STATS.add('asynchronous_cancels')

class StreamPlayer:
    def __init__(self):
        self.stop=threading.Event();self.thread=None;self.frames=queue.Queue(6)
        self.first=OrderedDict();self.deadline=0;self.ended=False;self.error=None;self.path=None
        self.frame_index=0;self.playhead=0.;self.frame_start=0.;self.next_time=0.;self.last_clock=0.
        self.loop_cache=DecodedLoopCache();self.cache_loop=False
    @staticmethod
    def pixmap(raw,size):
        return QPixmap.fromImage(QImage(raw,size,size,size*4,QImage.Format.Format_RGBA8888).copy())
    @staticmethod
    def cache_key(path,size,start_frame=0,end_frame=None):
        path=Path(path);return (str(path),size,path.stat().st_mtime_ns,start_frame,end_frame)

    def adopt(self,prepared,continuous=False):
        if not prepared.ready.is_set() or prepared.error or prepared.first is None:raise ValueError('收尾素材尚未准备好')
        lateness=max(0.,self.playhead-self.next_time) if continuous and self.ended else 0.
        self.close();self.path=prepared.path;self.size=prepared.size;self.duration=(prepared.end-prepared.start+1)/24
        self.stop=prepared.stop;self.frames=prepared.frames;self.thread=prepared.thread;self.ended=False;self.error=None;self.cache_loop=False
        self.range_start=prepared.start;self.range_end=prepared.end
        raw,delay,index=prepared.first;self.frame_index=index;self.playhead=min(lateness,delay*.9);self.frame_start=0.;self.next_time=delay
        self.last_clock=time.perf_counter();self.deadline=self.last_clock+delay-self.playhead
        return self.pixmap(raw,self.size)

    def start(self,path,size,duration=4,start_frame=0,first_fraction=0.,cache_loop=False,end_frame=None,seed=None,cached_frames=None):
        self.close();self.path=Path(path);self.stop=threading.Event();self.frames=queue.Queue(6)
        self.size=size;self.duration=duration;self.ended=False;self.error=None
        if start_frame<0 or end_frame is not None and end_frame<start_frame:raise ValueError('动画帧范围无效')
        self.range_start=start_frame;self.range_end=end_frame
        self.cache_loop=cache_loop;loop_key=self.cache_key(path,size,start_frame,end_frame)
        cached=(cached_frames if cached_frames is not None else self.loop_cache.get(loop_key)) if cache_loop else None
        key=loop_key+(start_frame,)
        if key not in self.first:
            if cached is not None:
                packed,delay,_=cached[0];self.first[key]=(zlib.decompress(packed),delay)
            elif seed is not None:
                # The tiny prepared first frame survives full-loop eviction;
                # reopening/late seeking is then confined to the worker.
                self.first[key]=(zlib.decompress(seed[0]),seed[1])
            else:
                opened(Path(path))
                with Image.open(path) as src:
                    count=getattr(src,'n_frames',1)
                    if start_frame>=count or end_frame is not None and end_frame>=count:raise ValueError('动画帧范围超出素材')
                    src.seek(start_frame);src.load()
                    im=src.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS)
                    STATS.add('decoded_frames')
                    delay=float(src.info.get('duration',duration*1000/max(1,count)))/1000
                    self.first[key]=(im.tobytes(),max(.015,delay))
            while len(self.first)>20:self.first.popitem(last=False)
        self.first.move_to_end(key)
        raw,first_delay=self.first[key];first=self.pixmap(raw,size)
        first_fraction=max(0,min(.999,first_fraction))
        self.frame_index=start_frame;self.playhead=0.;self.frame_start=-first_delay*first_fraction
        self.next_time=first_delay*(1-first_fraction)
        self.last_clock=time.perf_counter();self.deadline=self.last_clock+self.next_time
        stop,frames=self.stop,self.frames;first_raw=raw
        def emit(value):
            while not stop.is_set():
                try:frames.put(value,timeout=.05);return True
                except queue.Full:pass
            return False
        def decode():
            try:
                if cached is not None:
                    for packed,delay,i in cached[1:]:
                        if stop.is_set():return
                        if not emit((zlib.decompress(packed),delay,i)):return
                else:
                    if stop.is_set():return
                    collect=cache_loop and self.loop_cache.begin(loop_key,cancel=stop.is_set)
                    packed_frames=[];packed_size=0
                    if collect:
                        packed=zlib.compress(first_raw,1);packed_frames.append((packed,first_delay,start_frame));packed_size=len(packed)
                        if packed_size>self.loop_cache.entry_limit:
                            self.loop_cache.skip(loop_key);packed_frames.clear();collect=False
                    opened(Path(path))
                    with Image.open(path) as src:
                        count=getattr(src,'n_frames',1)
                        for i in range(start_frame+1,min(count,end_frame+1 if end_frame is not None else count)):
                            if stop.is_set():return
                            src.seek(i)
                            STATS.add('decoded_frames')
                            raw=src.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS).tobytes()
                            delay=max(.015,float(src.info.get('duration',duration*1000/max(1,count)))/1000)
                            if collect:
                                packed=zlib.compress(raw,1);packed_size+=len(packed)
                                if packed_size>self.loop_cache.entry_limit:
                                    self.loop_cache.skip(loop_key);packed_frames.clear();collect=False
                                else:packed_frames.append((packed,delay,i))
                            if not emit((raw,delay,i)):return
                    if collect and not stop.is_set():self.loop_cache.put(loop_key,packed_frames,packed_size,cancel=stop.is_set)
                emit((None,0,None))
            except Exception as error:
                if not stop.is_set():
                    emit((None,0,type(error).__name__))
        self.thread=STATS.start(decode,'pet-frame-reader')
        return first
    def advance(self,size,speed=1):
        if self.ended:return None,False
        now=time.perf_counter();speed=max(.25,min(3.,speed))
        self.playhead+=max(0,now-self.last_clock)*speed;self.last_clock=now;latest=None;ended=False
        while self.playhead+1e-8>=self.next_time:
            try:raw,delay,index=self.frames.get_nowait()
            except queue.Empty:break
            if raw is None:
                self.ended=True;self.error=index;ended=True;break
            self.frame_start=self.next_time;self.next_time+=delay;self.frame_index=index;latest=raw
        self.deadline=now+max(0,self.next_time-self.playhead)/speed
        return (self.pixmap(latest,self.size) if latest is not None else None),ended
    def resize(self,size):
        """Reopen at the current source frame, preserving its remaining time."""
        if self.path is None or size==self.size:return None
        fraction=(self.playhead-self.frame_start)/max(.001,self.next_time-self.frame_start)
        return self.start(self.path,size,self.duration,self.frame_index,fraction,cache_loop=self.cache_loop,end_frame=self.range_end)
    def close(self):
        self.stop.set()
        STATS.add('asynchronous_cancels')
        self.thread=None
    def next_delay_ms(self,speed=1,now=None):
        if self.path is None or self.ended:return 16
        now=time.perf_counter() if now is None else now
        remaining=(self.next_time-self.playhead)/max(.25,min(3.,speed))-max(0,now-self.last_clock)
        # Waiting for a slow decoder should not turn into 250 wakeups/sec.
        # Keep the existing 16ms retry ceiling, catch up immediately if ready.
        if remaining<=0:return 16 if self.frames.empty() else 1
        import math
        return max(1,min(100,math.ceil(remaining*1000)))
