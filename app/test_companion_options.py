import os,tempfile,unittest,io,json,urllib.error,time
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from desktop import DesktopPet
from codex_startup import ExitGate
from app_updates import check_release,API,REPOSITORY,release_without_api,UpdateError
APP=QApplication.instance() or QApplication([])
class Changes(unittest.TestCase):
 def speaking_task(self):
  p=self.pet;p.apply_settings(dict(bubble_mode='auto',self_talk=True,talk_quiet=False,wandering=False,random_actions=False,status_actions=False),save=False)
  p.on_activity(dict(kind='status',session='speech-test',state='working',active=1,title='测试会话',display='正在编辑文件'))
  p.status_hold=0;p.flush_status();return p
 def test_click_speech_is_visible_then_restores_latest_codex_status(self):
  p=self.speaking_task();b=p.bubble
  with patch.object(p,'play',return_value=True),patch.object(p,'play_click_sound'):
   p.choose(dict(id='synthetic',line='测试点击台词'),interactive=True)
  self.assertEqual(b.status_view.text(),'测试点击台词')
  p.on_activity(dict(kind='status',session='speech-test',state='working',active=1,title='测试会话',display='正在运行命令'))
  self.assertEqual(b.status_view.text(),'测试点击台词')
  p.status_hold=time.monotonic()-1;p.flush_status();self.assertIn('正在运行命令',b.status_view.text())
 def test_auto_speech_obeys_busy_quiet_setting_and_stays_silent(self):
  p=self.speaking_task();p.settings['talk_lines']=['测试自动台词'];p.next_talk=0
  with patch.object(p,'play_click_sound') as sound:p._move_frame();sound.assert_not_called()
  self.assertEqual(p.bubble.status_view.text(),'测试自动台词')
  p.status_hold=0;p.bubble.set_activity_text('正在编辑文件');p.settings['talk_quiet']=True;p.next_talk=0
  with patch.object(p,'say') as say:p._move_frame();say.assert_not_called()
 def test_five_second_talk_interval_is_saved_and_loaded_on_restart(self):
  p=self.pet
  with patch('desktop_settings.autostart_enabled',return_value=False),patch('codex_startup.enabled',return_value=False):p.open_settings()
  s=p.settings_dialog;s.tabs.setCurrentIndex(4);s.fields['self_talk'].setChecked(True)
  s.fields['talk_min'].setValue(5);s.fields['talk_max'].setValue(5);s.apply()
  saved=json.loads((Path(self.tmp.name)/'settings.json').read_text(encoding='utf-8'))
  self.assertEqual((saved['talk_min'],saved['talk_max']),(5,5))
  p.close();APP.processEvents();self.pet=DesktopPet(monitor=False)
  self.assertEqual((self.pet.settings['talk_min'],self.pet.settings['talk_max']),(5,5))
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();r=Path(self.tmp.name);self.patches=[patch(m+'.'+k,r/('settings.json' if k=='CONFIG' else '')) for m in ('desktop','enhanced') for k in ('CONFIG','STATE_DIR')]
  for p in self.patches:p.start()
  self.pet=DesktopPet(monitor=False);self.pet.apply_settings(dict(wandering=False,random_actions=False,drag_physics=False),save=False);self.pet.bubble.size_transition.complete();APP.processEvents()
 def tearDown(self):
  self.pet.close();APP.processEvents()
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def test_hidden_panel_stays_hidden_after_data_and_message(self):
  p=self.pet;p.apply_settings({'bubble':False},save=False)
  p.bubble.message('test');p.position_bubble();p.bubble.size_transition.complete();APP.processEvents();self.assertFalse(p.bubble.isVisible())
  p.apply_settings({'bubble':True},save=False);p.bubble.size_transition.complete();APP.processEvents();self.assertTrue(p.bubble.isVisible())
 def test_view_status_does_not_replace_saved_minimal_preference(self):
  p=self.pet;b=p.bubble;p.apply_settings({'bubble_mode':'minimal'})
  b.size_transition.complete();p.open_status();b.size_transition.complete();APP.processEvents()
  self.assertEqual(b.bubble_mode,'minimal');self.assertEqual(p.settings['bubble_mode'],'minimal')
  saved=json.loads((Path(self.tmp.name)/'settings.json').read_text(encoding='utf-8'))
  self.assertEqual(saved['bubble_mode'],'minimal');self.assertFalse(b.is_compact())
  b.evaluate_mode(b.last_task_update+100);b.size_transition.complete();self.assertTrue(b.is_minimal())
 def test_minimal_setting_clears_previous_automatic_capsule_state(self):
  p=self.pet;b=p.bubble;b.auto_compact=True
  p.apply_settings({'bubble_mode':'minimal'},save=False);b.size_transition.complete();APP.processEvents()
  self.assertFalse(b.auto_compact);self.assertFalse(b.is_island());self.assertTrue(b.is_minimal())
 def test_detached_panel_keeps_anchor_when_pet_moves(self):
  p=self.pet;p.apply_settings({'panel_detached':True},save=False);p.bubble.size_transition.complete();APP.processEvents();before=p.bubble.pos()
  p.move(p.x()-50,p.y()-30);p.position_bubble();self.assertEqual(p.bubble.pos(),before)
  p.bubble.show_status(True);p.bubble.size_transition.complete();p.position_bubble();self.assertEqual(p.bubble.geometry(),p.card_geometry(p.bubble.content.size()))
 def test_pet_and_panel_can_each_be_dragged_without_moving_the_other(self):
  p=self.pet;p.apply_settings(dict(panel_detached=True,no_move=False,drag_physics=False),save=False);b=p.bubble;b.size_transition.complete();b.size_transition.release_landing();APP.processEvents()
  def drag(widget,delta):
   start=widget.mapToGlobal(widget.rect().center());end=start+delta
   for kind,pos,button,buttons in [(QEvent.Type.MouseButtonPress,start,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton),(QEvent.Type.MouseMove,end,Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton),(QEvent.Type.MouseButtonRelease,end,Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)]:
    APP.sendEvent(widget,QMouseEvent(kind,QPointF(widget.mapFromGlobal(pos)),QPointF(pos),button,buttons,Qt.KeyboardModifier.NoModifier))
    if widget is p and kind==QEvent.Type.MouseMove:self.assertTrue(b.isVisible())
  panel_before=b.pos();pet_before=p.pos();drag(p,QPoint(-25,-20));APP.processEvents();self.assertNotEqual(p.pos(),pet_before);self.assertEqual(b.pos(),panel_before)
  pet_before=p.pos();panel_before=b.pos();drag(b,QPoint(-30,-25));APP.processEvents();self.assertEqual(p.pos(),pet_before);self.assertNotEqual(b.pos(),panel_before);self.assertIsInstance(p.settings['card_anchor'],dict)
 def test_hiding_panel_from_editor_does_not_reopen_editor_on_data(self):
  from PySide6.QtWidgets import QWidget
  p=self.pet;b=p.bubble;b.show_page('settings',QWidget());b.size_transition.complete();b.size_transition.release_landing()
  p.apply_settings({'bubble':False},save=False);b.message('new data');b.size_transition.complete();APP.processEvents();self.assertEqual(b.panel_page,'status');self.assertFalse(b.isVisible())
 def test_glide_uses_precise_16ms_scheduler(self):
  p=self.pet;p.throwing=True;p.motion_timer.start();p.schedule_movement();self.assertEqual(p.motion_timer.interval(),16);self.assertEqual(p.motion_timer.timerType(),Qt.TimerType.PreciseTimer)
 def test_exit_gate_requires_seen_and_three_confirmed_absences(self):
  g=ExitGate()
  for _ in range(5):self.assertFalse(g.observe(set()))
  self.assertFalse(g.observe({(1,1)}));self.assertFalse(g.observe(set()));self.assertFalse(g.observe(None));self.assertFalse(g.observe(set()));self.assertFalse(g.observe(set()));self.assertTrue(g.observe(set()))
  g.reset();self.assertFalse(g.observe({(2,2)}));self.assertFalse(g.observe(set()));self.assertFalse(g.observe({(3,3)}))
class DownloadFallback(unittest.TestCase):
 def test_api_limit_falls_back_to_same_repo_verified_full_package(self):
  tag='v0.8.6';name='bailong-desktop-pet-0.8.6-windows-x64.zip';sha='a'*64;calls=[]
  class Response(io.BytesIO):
   headers={'Content-Range':'bytes 0-0/1234'}
   def geturl(self):return 'https://github.com/'+REPOSITORY+'/releases/tag/'+tag
  def fetch(url,headers=None):
   calls.append(url)
   if url==API:raise urllib.error.HTTPError(API,429,'limit',{},None)
   if url.endswith('SHA256SUMS.txt'):return Response((sha+'  '+name+'\n').encode())
   return Response(b'')
  r=check_release('0.8.5',fetch);self.assertEqual((r.version,r.sha256,r.size,r.kind),('0.8.6',sha,1234,'full'));self.assertTrue(r.download_url.startswith('https://github.com/'+REPOSITORY+'/releases/download/'))
 def test_fallback_rejects_missing_checksum(self):
  class Response(io.BytesIO):
   def geturl(self):return 'https://github.com/other/repo/releases/tag/v0.8.6'
  with self.assertRaises(UpdateError):release_without_api(lambda *args:Response(b''))
if __name__=='__main__':unittest.main()
