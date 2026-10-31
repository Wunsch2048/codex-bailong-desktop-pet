import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest, time,tempfile,json
from pathlib import Path
from PIL import Image
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtTest import QTest
from pet import Pet,clamp_position
from quota import quota_windows

app=QApplication.instance() or QApplication([])
class Tests(unittest.TestCase):
    def setUp(self):
        # This legacy eager-player suite tests its mechanics with small real
        # animations, rather than decoding gigabytes of current production art.
        self.tmp=tempfile.TemporaryDirectory();assets=Path(self.tmp.name)
        def item(key,**extra):
            frames=[Image.new('RGBA',(24,24),(40+i*50,80,100,255)) for i in range(3)]
            frames[0].save(assets/(key+'.webp'),save_all=True,append_images=frames[1:],duration=[42,42,41],lossless=True)
            return dict(id=key,name=key,file=key+'.webp',durationMs=125,**extra)
        manifest=dict(idle=item('idle'),additionalIdleAnimations=[item('idle2')],variants=[item('v'+str(i)) for i in range(10)],
                      dragAnimation=item('drag'),landingAnimation=item('landing',originalDurationMs=2000),quotaAnimation=item('quota'))
        (assets/'素材清单.json').write_text(json.dumps(manifest),encoding='utf-8')
        self.patches=[patch('pet.ASSETS',assets),patch('pet.ROOT',assets),patch.object(Pet,'play_click_sound')]
        for p in self.patches:p.start()
        self.pet=Pet();self.pet.show()
    def tearDown(self):
        self.pet.tick.stop();self.pet.bubble.close();self.pet.hide()
        self.pet.frames=[];self.pet.cache.clear();self.pet.pinned_frames.clear();self.pet.transition=None
        self.pet.deleteLater();app.processEvents()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def test_all_assets_and_idle_weights(self):
        self.assertEqual(len(self.pet.variants),10)
        for item in self.pet.idles+self.pet.variants:self.assertEqual(len(self.pet.load(item)),round(item['durationMs']*24/1000))
        with patch('pet.random.choices',return_value=[self.pet.idles[1]]) as choice:
            self.pet.idle();self.assertEqual(choice.call_args.kwargs['weights'],[4,1])
    def test_click_disambiguation(self):
        with patch.object(self.pet,'single_click') as single,patch.object(self.pet,'quota') as quota:
            # Timer slot was connected earlier; inspect resulting state instead below.
            QTest.mouseClick(self.pet,Qt.MouseButton.LeftButton,pos=QPoint(160,160))
            QTest.qWait(80);QTest.mouseClick(self.pet,Qt.MouseButton.LeftButton,pos=QPoint(160,160))
            quota.assert_called_once();self.pet.click_timer.stop()
        self.pet.last_click=None
        QTest.mouseClick(self.pet,Qt.MouseButton.LeftButton,pos=QPoint(160,160));QTest.qWait(300)
        self.assertEqual(self.pet.mode,'variant');self.assertTrue(self.pet.bubble.isVisible())
        self.assertLessEqual(self.pet.bubble_timer.remainingTime(),4000)
    def test_variant_return_and_quota_stale(self):
        self.pet.choose(self.pet.variants[0]);self.pet.started=time.monotonic()-self.pet.current['durationMs']/1000-.01;self.pet.animate()
        self.assertEqual(self.pet.mode,'idle')
        self.pet.quota_generation=1;self.pet.generation=2
        self.pet.quota_failed('obsolete');self.assertNotIn('obsolete',self.pet.bubble.findChildren(__import__('PySide6.QtWidgets',fromlist=['QLabel']).QLabel)[0].text())
    def test_quota_parsing(self):
        data={'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':23,'windowDurationMins':300},'secondary':{'usedPercent':10,'windowDurationMins':10080}}}}
        windows=quota_windows(data);self.assertEqual([w['remaining'] for w in windows],[77,90]);self.assertEqual(windows[1]['name'],'一周')
        with self.assertRaises(RuntimeError):quota_windows({})
    def test_loading_then_progress_and_resume(self):
        with patch('pet.QuotaWorker') as worker:
            self.pet.quota()
            self.assertEqual(self.pet.mode,'quota')
            self.assertEqual(self.pet.current['id'],self.pet.manifest.get('quotaAnimation',self.pet.idles[0])['id'])
            from PySide6.QtWidgets import QLabel,QProgressBar
            self.assertEqual(self.pet.bubble.findChildren(QLabel)[0].text(),'让我看看额度还有多少。。。。。。')
            self.pet.quota_ready([{'name':'5小时','remaining':76,'resetsAt':None},{'name':'一周','remaining':91,'resetsAt':None}])
            self.assertEqual([b.value() for b in self.pet.bubble.findChildren(QProgressBar)],[76,91])
            self.pet.started=time.monotonic()-self.pet.current['durationMs']/1000-.1;self.pet.animate()
            self.assertEqual(self.pet.mode,'idle');self.assertTrue(self.pet.bubble.isVisible())
            self.pet.dismiss_bubble();self.assertEqual(self.pet.mode,'idle')
            self.pet.worker=None
    def test_menu_contains_all_variants_and_exit(self):
        actions=[]
        def inspect():
            menu=app.activePopupWidget()
            actions.extend(a.text() for a in menu.actions() if not a.isSeparator());menu.close()
        QTimer.singleShot(100,inspect)
        QTest.mouseClick(self.pet,Qt.MouseButton.RightButton,pos=QPoint(160,160))
        self.assertEqual(len(actions),len(self.pet.variants)+1)
        self.assertEqual(actions[-1],'退出桌宠')
    def test_drag_landing_and_click_suppression(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QPointF
        press=SimpleNamespace(button=lambda:Qt.MouseButton.LeftButton,globalPosition=lambda:QPointF(200,200))
        move=SimpleNamespace(buttons=lambda:Qt.MouseButton.LeftButton,globalPosition=lambda:QPointF(240,230))
        self.pet.mousePressEvent(press);self.pet.mouseMoveEvent(move)
        self.assertEqual(self.pet.mode,'drag');self.assertEqual(self.pet.current['id'],'drag')
        self.pet.started=time.monotonic()-self.pet.current['durationMs']/1000-.1;self.pet.animate();self.assertEqual(self.pet.mode,'drag')
        self.pet.mouseReleaseEvent(press)
        self.assertEqual(self.pet.mode,'landing');self.assertEqual(len(self.pet.frames),round(self.pet.current['durationMs']*24/1000))
        self.assertEqual(self.pet.current.get('originalDurationMs',self.pet.current['durationMs']),2000);self.assertFalse(self.pet.click_timer.isActive())
        self.pet.started=time.monotonic()-self.pet.current['durationMs']/1000-.1;self.pet.animate();self.assertEqual(self.pet.mode,'idle')
    def test_interaction_frames_survive_variant_eviction(self):
        for item in self.pet.variants[:3]:self.pet.load(item)
        with patch('pet.gzip.decompress',side_effect=AssertionError('drag must not decode on mouse movement')):
            drag=self.pet.manifest['dragAnimation'];landing=self.pet.manifest['landingAnimation']
            self.assertIs(self.pet.load(drag),self.pet.pinned_frames[str(self.pet.asset_path(drag))])
            self.assertEqual(len(self.pet.load(landing)),round(landing['durationMs']*24/1000))
    def test_all_clicks_and_idle_return_do_not_decode(self):
        with patch('pet.gzip.decompress',side_effect=AssertionError('unexpected decoding')):
            for item in self.pet.variants:
                self.pet.choose(item);self.pet.started=time.monotonic()-self.pet.current['durationMs']/1000-.1;self.pet.animate()
                self.assertEqual(self.pet.mode,'idle')
                self.assertIsNone(self.pet.transition)
    def test_quota_zero_percent_is_readable_outside_bar(self):
        from PySide6.QtWidgets import QLabel,QProgressBar
        self.pet.bubble.quota([{'name':'5小时','remaining':0,'resetsAt':None}])
        self.assertTrue(any('剩余 0%' in label.text() for label in self.pet.bubble.findChildren(QLabel)))
        self.assertFalse(self.pet.bubble.findChildren(QProgressBar)[0].isTextVisible())

class BoundaryTests(unittest.TestCase):
    def test_edges_and_corners(self):
        from PySide6.QtCore import QRect,QSize
        area=QRect(0,0,1920,1040);size=QSize(256,256)
        for point in [QPoint(-500,-500),QPoint(3000,-500),QPoint(-500,3000),QPoint(3000,3000),QPoint(800,300)]:
            bounded=clamp_position(point,size,area)
            self.assertTrue(area.contains(QRect(bounded,size)))
        self.assertEqual(clamp_position(QPoint(3000,3000),size,area),QPoint(1664,784))
    def test_negative_monitor_coordinates(self):
        from PySide6.QtCore import QRect,QSize
        area=QRect(-1920,-200,1920,1040);size=QSize(256,256)
        self.assertEqual(clamp_position(QPoint(-4000,-1000),size,area),QPoint(-1920,-200))
        self.assertTrue(area.contains(QRect(clamp_position(QPoint(20,1000),size,area),size)))

if __name__=='__main__':unittest.main()
