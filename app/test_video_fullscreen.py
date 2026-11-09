"""Fullscreen classification, user preference and native-window handoff journeys."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QWidget
from video_fullscreen import VideoGate,FullscreenGate,VideoProbe,BrowserVideoProbe,fills_monitor,video_coverage,game_fullscreen
from video_yield import VideoYield
APP=QApplication.instance() or QApplication([])
M=(0,0,1920,1080)
def frame(**values):return dict(dict(hwnd=700,monitor=M,fullscreen=True,video=True,reason='player'),**values)
class ClassifierTests(unittest.TestCase):
    def test_probe_exception_keeps_known_fullscreen_until_recovery_or_timeout(self):
        g=VideoGate();g.update(frame(),0);g.update(frame(),1)
        failed=dict(hwnd=0,fullscreen=False,video=None,reason='probe_error')
        self.assertTrue(g.update(failed,2))
        self.assertTrue(g.update(frame(),2.5))
        self.assertTrue(g.update(failed,3))
        self.assertIsNone(g.update(failed,6))
        self.assertIsNone(g.update(frame(),7))
    def controls(self,width=1920,offscreen=False):
        from types import SimpleNamespace as S
        values=[S(CurrentName=name,CurrentControlType=kind,CurrentIsOffscreen=offscreen,
            CurrentBoundingRectangle=S(left=0,top=1000,right=width,bottom=1050))
            for kind,name in ((50000,'暂停'),(50000,'进入全屏模式'),(50015,'视频时间进度条'))]
        elements=S(Length=3,GetElement=lambda i:values[i]);element=S(FindAll=lambda *a:elements)
        p=object.__new__(BrowserVideoProbe);p.types=S(TreeScope_Descendants=4);p.controls=None
        return p,element
    def test_full_video_control_combination_is_recognized(self):
        p,e=self.controls();self.assertTrue(p.media_controls(e,M))
    def test_embedded_seek_bar_cannot_classify_a_full_page_as_video(self):
        p,e=self.controls(width=320);self.assertFalse(p.media_controls(e,M))
    def test_offscreen_playback_controls_do_not_trigger_yield(self):
        p,e=self.controls(offscreen=True);self.assertFalse(p.media_controls(e,M))
    def test_maximized_workarea_is_not_fullscreen(self):self.assertFalse(fills_monitor((0,0,1920,1040),M))
    def test_fullscreen_tolerates_one_pixel_border(self):self.assertTrue(fills_monitor((-1,-1,1921,1081),M))
    def test_letterbox_and_portrait_video(self):
        self.assertTrue(video_coverage((0,140,1920,940),M));self.assertTrue(video_coverage((650,0,1270,1080),M))
    def test_embedded_and_offset_video_are_rejected(self):
        self.assertFalse(video_coverage((0,0,640,360),M));self.assertFalse(video_coverage((0,0,960,1080),M))
    def test_negative_monitor_coordinates(self):self.assertTrue(video_coverage((-1920,0,0,1080),(-1920,0,0,1080)))
    def test_entry_requires_stable_observation(self):
        g=VideoGate();self.assertIsNone(g.update(frame(),0));self.assertIsNone(g.update(frame(),.2));self.assertTrue(g.update(frame(),.8))
    def test_all_window_gate_does_not_require_video_tag(self):
        g=FullscreenGate(require_video=False);generic=frame(video=False,reason='window_fullscreen')
        self.assertIsNone(g.update(generic,0));self.assertIsNone(g.update(generic,.2));self.assertTrue(g.update(generic,.8))
    def test_game_candidate_excludes_browser_and_office_but_accepts_unknown(self):
        self.assertTrue(game_fullscreen(frame(process='game.exe',cls='GameWindow',video=False)))
        self.assertFalse(game_fullscreen(frame(process='firefox.exe',cls='MozillaWindowClass',video=False)))
        self.assertFalse(game_fullscreen(frame(process='winword.exe',cls='OpusApp',video=False)))
    def test_alt_tab_clears_immediately(self):
        g=VideoGate();g.update(frame(),0);g.update(frame(),1);self.assertIsNone(g.update(frame(hwnd=701),1.1))
    def test_fullscreen_exit_clears_immediately(self):
        g=VideoGate();g.update(frame(),0);g.update(frame(),1);self.assertIsNone(g.update(frame(fullscreen=False),1.1))
    def test_transient_missing_controls_do_not_flicker(self):
        g=VideoGate();g.update(frame(),0);g.update(frame(),1)
        self.assertTrue(g.update(frame(video=False),2));self.assertTrue(g.update(frame(),2.4))
    def test_accessibility_failure_expires(self):
        g=VideoGate();g.update(frame(),0);g.update(frame(),1)
        self.assertTrue(g.update(frame(video=None),2));self.assertIsNone(g.update(frame(video=None),5.1))
    def test_player_and_ordinary_fullscreen(self):
        class API:
            def snapshot(self):return dict(hwnd=700,monitor=M,fullscreen=True,process=self.name,cls='')
        class Browser:
            known=None
            def video(self,*a):return False
        api=API();p=VideoProbe(api,Browser());api.name='vlc.exe';self.assertTrue(p.read()['video'])
        api.name='game.exe';self.assertFalse(p.read()['video']);api.name='msedge.exe';self.assertFalse(p.read()['video'])
    def test_firefox_uses_real_video_node_adapter(self):
        from unittest.mock import Mock
        api=Mock();api.snapshot.return_value=dict(hwnd=700,monitor=M,fullscreen=True,process='firefox.exe',cls='MozillaWindowClass')
        browser=Mock();browser.firefox_video.return_value=True;p=VideoProbe(api,browser)
        result=p.read();self.assertTrue(result['video']);self.assertEqual(result['reason'],'firefox_ia2');browser.video.assert_not_called()

class FakeAPI:
    def __init__(self):self.focus=700;self.calls=[];self.rects={}
    def valid(self,h):return True
    def foreground(self):return self.focus
    def rect(self,h):return self.rects.get(h,(100,100,300,300))
    def set_topmost(self,h,top,behind=0):self.calls.append((h,top,behind));return True

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.pet=QWidget();self.pet.settings={'on_top':True,'video_fullscreen_yield':True};self.pet._video_yielded=False
        self.pet.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint);self.pet.resize(200,200);self.pet.show()
        self.bubble=QWidget(self.pet,Qt.WindowType.Tool);self.bubble.show();APP.processEvents()
        from status_indicator import StatusIndicator
        self.pet.bubble=self.bubble;self.bubble.status_indicator=StatusIndicator(self.bubble)
        self.api=FakeAPI();self.guard=VideoYield(self.pet,self.api,start=False)
    def tearDown(self):self.guard.shutdown();self.bubble.close();self.pet.close();self.guard.deleteLater();APP.processEvents()
    def enter(self):self.guard.accept(frame(),0);self.guard.accept(frame(),.8)
    def test_pet_and_bubble_yield_without_visibility_or_geometry_change(self):
        before=(self.pet.geometry(),self.bubble.geometry());self.enter()
        self.assertTrue(self.pet._video_yielded);self.assertEqual(len(self.guard.changed),2)
        self.assertTrue(all(not c[1] for c in self.api.calls));self.assertTrue(self.pet.settings['on_top'])
        self.assertEqual(before,(self.pet.geometry(),self.bubble.geometry()));self.assertTrue(self.pet.isVisible())
    def test_exit_restores_latest_preference(self):
        self.enter();self.guard.accept(frame(fullscreen=False),1);self.assertFalse(self.pet._video_yielded)
        self.assertTrue(any(c[1] for c in self.api.calls))
    def test_manual_unpin_is_never_reenabled(self):
        self.enter();self.api.calls.clear();self.pet.settings['on_top']=False;self.guard.reconcile()
        self.guard.accept(frame(fullscreen=False),1);self.assertFalse(self.pet._video_yielded)
        self.assertFalse(any(c[1] for c in self.api.calls));self.assertFalse(self.pet.settings['on_top'])
    def test_turning_feature_off_restores_pin(self):
        self.enter();self.pet.settings['video_fullscreen_yield']=False;self.guard.reconcile()
        self.assertFalse(self.pet._video_yielded);self.assertTrue(any(c[1] for c in self.api.calls))
    def test_other_monitor_does_not_yield(self):
        self.api.rects={int(w.winId()):(2100,0,2300,300) for w in (self.pet,self.bubble)};self.enter()
        self.assertFalse(self.pet._video_yielded);self.assertFalse(self.api.calls)
    def test_delayed_result_after_foreground_change_is_ignored(self):
        self.guard.accept(frame(),0);self.api.focus=701;self.guard.accept(frame(),1)
        self.assertFalse(self.pet._video_yielded);self.assertFalse(self.api.calls)
    def test_new_owned_window_joins_without_recreating_existing_windows(self):
        self.enter();old=int(self.pet.winId());report=QWidget(self.bubble,Qt.WindowType.Tool);report.show();APP.processEvents()
        self.assertIn(int(report.winId()),self.guard.changed);self.assertEqual(old,int(self.pet.winId()));report.close()
    def test_hidden_owned_window_is_restored_only_after_video_exit(self):
        self.enter();self.api.calls.clear();self.bubble.hide();self.guard.reconcile()
        self.assertIn(int(self.bubble.winId()),self.guard.changed);self.assertFalse(any(c[1] for c in self.api.calls))
        self.guard.accept(frame(fullscreen=False),1);self.assertFalse(self.guard.changed)
    def test_unread_completion_temporarily_overrides_video_yield(self):
        indicator=self.bubble.status_indicator
        self.enter();self.assertTrue(self.pet._video_yielded)
        indicator.notify_complete(dict(session='test',turn='one'))
        self.assertTrue(self.guard.attention_override);self.assertFalse(self.pet._video_yielded)
        self.assertTrue(any(c[1] for c in self.api.calls))
        self.api.calls.clear();self.guard.accept(frame(),3)
        self.assertTrue(self.guard.attention_override);self.assertFalse(self.pet._video_yielded)
        indicator.acknowledge();self.assertFalse(self.guard.attention_override);self.assertTrue(self.pet._video_yielded)
        self.assertFalse(any(c[1] for c in self.api.calls))
    def test_all_window_mode_hides_without_completion_override(self):
        self.pet.settings['fullscreen_yield_mode']='game_video';self.guard.reconcile()
        generic=frame(video=True,reason='game_fullscreen');self.guard.accept(generic,0);self.guard.accept(generic,.8)
        self.assertTrue(self.pet._fullscreen_yielded);self.assertFalse(self.pet._video_yielded);self.assertFalse(self.guard.attention_override)
        self.bubble.status_indicator.notify_complete(dict(session='test',turn='all'))
        self.assertTrue(self.pet._fullscreen_yielded);self.assertFalse(self.guard.attention_override)
        self.guard.accept(generic,3);self.assertTrue(self.pet._fullscreen_yielded)
        self.guard.accept(frame(fullscreen=False,video=False),4);self.assertFalse(self.pet._fullscreen_yielded)
    def test_all_window_mode_uses_pet_monitor_not_foreground_monitor_only(self):
        self.pet.settings['fullscreen_yield_mode']='game_video';self.guard.reconcile()
        self.api.rects={int(self.pet.winId()):(2100,0,2300,300),int(self.bubble.winId()):(2100,0,2300,300)}
        generic=frame(video=True,reason='game_fullscreen');self.guard.accept(generic,0);self.guard.accept(generic,.8)
        self.assertFalse(self.pet._fullscreen_yielded)
    def test_manual_unpin_still_wins_over_unread_completion(self):
        self.bubble.status_indicator.notify_complete(dict(session='test',turn='one'))
        self.pet.settings['on_top']=False;self.enter()
        self.assertFalse(self.guard.attention_override);self.assertFalse(any(c[1] for c in self.api.calls))

if __name__=='__main__':unittest.main()
