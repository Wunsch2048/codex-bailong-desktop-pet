"""Regression checks for observable timing, buffer and scaling failures."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,queue,tempfile,time
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QApplication
from stream_player import StreamPlayer

APP=QApplication.instance() or QApplication([])

class PlaybackClockTests(unittest.TestCase):
    def clock_player(self):
        p=StreamPlayer();p.size=8;p.last_clock=0;p.next_time=.042;p.frame_start=0
        p.frames=queue.Queue();raw=Image.new('RGBA',(8,8),'white').tobytes()
        durations=[round((i+1)*1000/24)-round(i*1000/24) for i in range(96)]
        for i in range(1,96):p.frames.put((raw,durations[i]/1000,i))
        p.frames.put((None,0,None));return p
    def test_first_frame_is_not_presented_twice_and_24fps_does_not_drift(self):
        p=self.clock_player()
        with patch('stream_player.time.perf_counter',return_value=.016):self.assertIsNone(p.advance(8)[0])
        for tick in range(2,251):
            with patch('stream_player.time.perf_counter',return_value=tick*.016):p.advance(8)
        self.assertTrue(p.ended);self.assertEqual(p.frame_index,95)
        self.assertAlmostEqual(p.next_time,4.,places=8)
    def test_gui_stall_skips_to_due_frame_without_stretching_clip(self):
        p=self.clock_player()
        with patch('stream_player.time.perf_counter',return_value=.52):frame,ended=p.advance(8)
        self.assertIsNotNone(frame);self.assertFalse(ended);self.assertEqual(p.frame_index,12)
        with patch('stream_player.time.perf_counter',return_value=4.):_,ended=p.advance(8)
        self.assertTrue(ended)
    def test_speed_change_preserves_progress(self):
        p=self.clock_player()
        with patch('stream_player.time.perf_counter',return_value=1.):p.advance(8,1)
        with patch('stream_player.time.perf_counter',return_value=2.5):_,ended=p.advance(8,2)
        self.assertTrue(ended);self.assertAlmostEqual(p.playhead,4.)
    def test_resize_preserves_current_pose_and_frame_fraction(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'frames.webp';frames=[Image.new('RGBA',(16,16),(i*70,30,30,255)) for i in range(4)]
            frames[0].save(path,save_all=True,append_images=frames[1:],duration=100,lossless=True)
            p=StreamPlayer()
            with patch('stream_player.time.perf_counter',return_value=0.):p.start(path,16)
            deadline=time.monotonic()+2
            while p.frames.qsize()<4 and time.monotonic()<deadline:time.sleep(.005)
            with patch('stream_player.time.perf_counter',return_value=.15):p.advance(16)
            self.assertEqual(p.frame_index,1)
            with patch('stream_player.time.perf_counter',return_value=.15):frame=p.resize(32)
            self.assertEqual(frame.width(),32);self.assertEqual(p.frame_index,1)
            self.assertAlmostEqual(p.next_time,.05,places=6)
            with patch('stream_player.time.perf_counter',return_value=.15):p.resize(64)
            self.assertAlmostEqual(p.next_time,.05,places=6);p.close()

if __name__=='__main__':unittest.main()
