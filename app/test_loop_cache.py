import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,unittest,time,zlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QApplication
from stream_player import StreamPlayer
from loop_cache import DecodedLoopCache

APP=QApplication.instance() or QApplication([])


def drain(player):
    result=[]
    while True:
        value=player.frames.get(timeout=4)
        if value[0] is None:
            assert value[2] is None,value[2]
            return result
        result.append(value)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'frames.webp';self.player=StreamPlayer()
        images=[Image.new('RGBA',(16,16),(i*20,50,30,255)) for i in range(12)]
        images[0].save(self.path,save_all=True,append_images=images[1:],duration=42,lossless=True)
    def tearDown(self):self.player.close();self.temp.cleanup()
    def test_cached_playback_is_pixel_and_timing_identical_without_reopening_image(self):
        p=self.player;first=p.start(self.path,16,cache_loop=True);cold=drain(p)
        self.assertEqual(p.loop_cache.stats()['entries'],1)
        with patch('stream_player.Image.open',side_effect=AssertionError('unexpected decode')):
            again=p.start(self.path,16,cache_loop=True);warm=drain(p)
        self.assertEqual(first.toImage(),again.toImage());self.assertEqual(cold,warm)
        self.assertEqual(p.loop_cache.stats()['hits'],1);self.assertEqual(len(warm),11)
    def test_cancelled_clip_is_never_cached_as_a_complete_loop(self):
        p=self.player;p.start(self.path,16,cache_loop=True);time.sleep(.03);p.close()
        self.assertEqual(p.loop_cache.stats()['entries'],0)
        p.start(self.path,16,cache_loop=True);self.assertEqual(len(drain(p)),11)
        self.assertEqual(p.loop_cache.stats()['entries'],1)
    def test_resolution_and_modified_asset_do_not_reuse_stale_pixels(self):
        p=self.player;p.start(self.path,16,cache_loop=True);drain(p)
        frame=p.start(self.path,32,cache_loop=True);self.assertEqual(frame.width(),32)
        self.assertTrue(all(len(raw)==32*32*4 for raw,_,_ in drain(p)))
        previous=self.path.stat().st_mtime_ns
        Image.new('RGBA',(16,16),'blue').save(self.path,lossless=True);os.utime(self.path,ns=(previous+1000000000,previous+1000000000))
        frame=p.start(self.path,16,cache_loop=True);drain(p)
        self.assertEqual(frame.toImage().pixelColor(0,0).blue(),255)
    def test_oversized_entry_falls_back_without_recompressing_every_loop(self):
        p=self.player;p.loop_cache=DecodedLoopCache(limit=32);p.start(self.path,16,cache_loop=True);drain(p)
        self.assertEqual(p.loop_cache.stats()['bytes'],0)
        with patch('stream_player.zlib.compress',wraps=zlib.compress) as compress:
            p.start(self.path,16,cache_loop=True);drain(p);compress.assert_not_called()
    def test_total_and_build_reservation_are_bounded(self):
        cache=DecodedLoopCache(limit=100)
        for key in range(4):
            self.assertTrue(cache.begin(key));self.assertLessEqual(cache.bytes+cache.entry_limit,100)
            cache.put(key,[(b'X'*45,.042,0)],45);self.assertLessEqual(cache.stats()['bytes'],100)
        self.assertIsNotNone(cache.get(3));self.assertIsNone(cache.get(0))
