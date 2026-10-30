import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from stream_player import StreamPlayer,PreparedSegment
from decode_runtime import STATS
from loop_cache import DecodedLoopCache
APP=QApplication.instance() or QApplication([])

class DecoderRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.path=self.root/'red.webp';self.blue=self.root/'blue.webp'
        for path,color in ((self.path,(200,0,0,255)),(self.blue,(0,0,200,255))):
            frames=[Image.new('RGBA',(16,16),(*color[:2],color[2]+i,color[3])) for i in range(10)]
            frames[0].save(path,save_all=True,append_images=frames[1:],duration=42,lossless=True)
        self.p=StreamPlayer()
    def tearDown(self):
        self.p.close();self.assertTrue(STATS.drain());self.tmp.cleanup()
    def test_blocked_old_worker_never_blocks_close_or_delivers_into_new_clip(self):
        entered=threading.Event();release=threading.Event();original=Image.open
        def blocked(path,*a,**kw):
            if Path(path)==self.path and threading.current_thread()!=threading.main_thread():
                entered.set();release.wait(3)
            return original(path,*a,**kw)
        with patch('stream_player.Image.open',side_effect=blocked):
            try:
                self.p.start(self.path,16);self.assertTrue(entered.wait(2));old=self.p.thread
                begin=time.monotonic();self.p.close();self.assertLess(time.monotonic()-begin,.05)
                self.assertTrue(old.is_alive());first=self.p.start(self.blue,16)
                self.assertEqual(first.toImage().pixelColor(0,0).blue(),200)
                release.set();indices=[]
                while True:
                    raw,delay,index=self.p.frames.get(timeout=3)
                    if raw is None:break
                    self.assertEqual(raw[0],0);self.assertEqual(raw[2],200+index);indices.append(index)
                self.assertEqual(indices,list(range(1,10)))
            finally:release.set()
    def test_prepared_cancel_returns_while_worker_is_blocked_and_then_releases(self):
        entered=threading.Event();release=threading.Event();original=Image.open
        def blocked(*a,**kw):entered.set();release.wait(3);return original(*a,**kw)
        tail=None
        with patch('stream_player.Image.open',side_effect=blocked):
            try:
                tail=PreparedSegment(self.path,16,7,9);self.assertTrue(entered.wait(2))
                begin=time.monotonic();tail.close();self.assertLess(time.monotonic()-begin,.05)
                self.assertTrue(tail.thread.is_alive())
            finally:
                if tail:tail.close()
                release.set()
        self.assertTrue(STATS.drain());self.assertIsNone(tail.first)
    def test_cancelled_cache_publish_does_not_evict_new_work(self):
        cache=DecodedLoopCache(limit=100);cache.put('new',[],60,entry_limit=100)
        self.assertFalse(cache.begin('stale',reserve=100,cancel=lambda:True))
        cache.put('stale',[],90,entry_limit=100,cancel=lambda:True)
        self.assertEqual(cache.stats()['bytes'],60);self.assertIsNotNone(cache.get('new'));self.assertIsNone(cache.get('stale'))
    def test_prepared_loop_reuses_exact_frames_without_reopening_source(self):
        cache=DecodedLoopCache();segments=[]
        def drain(segment):
            self.assertTrue(segment.ready.wait(2));self.assertIsNone(segment.error);frames=[segment.first]
            while True:
                raw,delay,index=segment.frames.get(timeout=2)
                if raw is None:self.assertIsNone(index);break
                frames.append((raw,delay,index))
            return frames
        try:
            cold=PreparedSegment(self.path,16,3,6,cache=cache);segments.append(cold);expected=drain(cold)
            with patch('stream_player.Image.open',side_effect=AssertionError('Source reopened for a warm loop')):
                warm=PreparedSegment(self.path,16,3,6,cache=cache);segments.append(warm);actual=drain(warm)
            self.assertEqual(expected,actual);self.assertEqual([x[2] for x in actual],[3,4,5,6]);self.assertGreater(cache.stats()['hits'],0)
        finally:
            for segment in segments:segment.close()
    def test_cancelled_prepared_loop_does_not_publish_partial_cache(self):
        cache=DecodedLoopCache();segment=PreparedSegment(self.path,16,0,9,autostart=False,cache=cache);calls=[0]
        def cancelled():calls[0]+=1;return calls[0]>3
        try:
            with Image.open(self.path) as image:segment.produce(image,cancel=cancelled)
            self.assertEqual(cache.stats()['entries'],0);self.assertLessEqual(segment.frames.qsize(),6)
        finally:segment.close()
    def test_adaptive_clock_follows_native_frame_and_speed_without_busy_wait(self):
        self.p.path=self.path;self.p.next_time=.042;self.p.playhead=0;self.p.last_clock=100
        self.assertEqual(self.p.next_delay_ms(now=100),42)
        self.assertEqual(self.p.next_delay_ms(speed=2,now=100),21)
        self.assertLessEqual(abs(self.p.next_delay_ms(now=100.02)-22),1)
        self.assertEqual(self.p.next_delay_ms(now=101),16)
        self.p.frames.put((b'pending',.042,1));self.assertEqual(self.p.next_delay_ms(now=101),1)
    def test_movement_idle_sleeps_and_resumes_without_one_second_jump(self):
        from desktop import DesktopPet
        timer=QTimer();timer.start(33)
        obj=SimpleNamespace(motion_timer=timer,walking=False,throwing=False,settings={'self_talk':False},motion_clock=1)
        try:
            DesktopPet.schedule_movement(obj);self.assertEqual(timer.interval(),1000)
            obj.throwing=True;before=time.perf_counter();DesktopPet.schedule_movement(obj)
            self.assertEqual(timer.interval(),16);self.assertGreaterEqual(obj.motion_clock,before)
            obj.throwing=False;obj.walking=True;DesktopPet.schedule_movement(obj);self.assertEqual(timer.interval(),16)
            timer.stop();DesktopPet.schedule_movement(obj);self.assertFalse(timer.isActive())
        finally:timer.stop()
    def test_frame_clock_uses_high_resolution_counter_independent_of_business_clock(self):
        self.p.path=self.path;self.p.size=16;self.p.next_time=.042;self.p.last_clock=100
        self.p.frames.put((bytes(16*16*4),.042,1))
        with patch('stream_player.time.monotonic',side_effect=AssertionError('coarse clock')),patch('stream_player.time.perf_counter',return_value=100.042):
            image,ended=self.p.advance(16)
            self.assertIsNotNone(image);self.assertFalse(ended);self.assertEqual(self.p.frame_index,1)
            self.assertLessEqual(abs(self.p.next_delay_ms()-42),1)
    def test_rapid_switches_release_all_owned_workers_and_file_handles(self):
        for i in range(12):self.p.start(self.path if i%2 else self.blue,32,cache_loop=True)
        self.p.close();self.assertTrue(STATS.drain())
        self.assertEqual(STATS.snapshot()['active_workers'],0)
        # Windows forbids replacing an open input file. After workers exit,
        # both original files can be renamed and their queue stays bounded.
        for path in (self.path,self.blue):path.rename(path.with_suffix('.released'))
        self.assertLessEqual(self.p.frames.qsize(),6)
    def test_press_feedback_temporarily_keeps_fast_clock_and_stopped_tick_stays_stopped(self):
        from desktop import DesktopPet
        tick=QTimer();tick.start(42)
        obj=SimpleNamespace(locomotion=SimpleNamespace(active=False),tick=tick,player=SimpleNamespace(next_delay_ms=lambda speed:42),settings={'playback_speed':1},sustained=SimpleNamespace(speed_factor=lambda p:1),press_feedback=time.monotonic(),schedule_movement=lambda:None)
        try:
            DesktopPet.schedule_animation(obj);self.assertEqual(tick.interval(),16)
            obj.press_feedback=0;DesktopPet.schedule_animation(obj);self.assertEqual(tick.interval(),42)
            tick.stop();DesktopPet.schedule_animation(obj);self.assertFalse(tick.isActive())
        finally:tick.stop()

if __name__=='__main__':unittest.main()
