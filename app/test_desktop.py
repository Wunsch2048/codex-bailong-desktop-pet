import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import copy,json,tempfile,time,threading,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PIL import Image
from PySide6.QtWidgets import QApplication,QMenu,QToolButton
from PySide6.QtCore import Qt,QPointF
from PySide6.QtTest import QTest
from desktop_core import ActionGate,physics_step,normalized,relative_position,restore_position
from stream_player import StreamPlayer
from desktop_services import SecretStore,validate_character,import_character
from chat_window import ChatStream,ChatWindow,SessionStore,trim_messages
from desktop import DesktopPet
from installer import install,read_manifest

app=QApplication.instance() or QApplication([])

def settle():
    app.processEvents()
    for window in app.topLevelWidgets():
        transition=getattr(window,'size_transition',None)
        if transition:transition.complete()
    app.processEvents()

def until(check,seconds=4):
    deadline=time.monotonic()+seconds
    while not check() and time.monotonic()<deadline:QTest.qWait(15)
    return check()

class CoreTests(unittest.TestCase):
    def test_priority_and_deferred_completion(self):
        gate=ActionGate();self.assertTrue(gate.request('drag'))
        self.assertFalse(gate.request('task',{'id':'done'}));self.assertFalse(gate.request('variant'))
        self.assertEqual(gate.finish(),('task',{'id':'done'}));self.assertTrue(gate.request('click'));self.assertTrue(gate.request('drag'))
    def test_throw_bounces_and_stops_inside_bounds(self):
        x,y,vx,vy=98,30,1500,-400
        for _ in range(160):
            x,y,vx,vy,done=physics_step(x,y,vx,vy,.033,(0,0,100,100))
            self.assertTrue(0<=x<=100 and 0<=y<=100)
        self.assertTrue(done);self.assertLess(abs(vx)+abs(vy),1)
    def test_normalized_position_survives_changed_resolution(self):
        saved=relative_position(-1500,200,256,256,(-1920,0,1920,1080),'second')
        x,y=restore_position(saved,384,384,(0,0,2560,1440))
        self.assertTrue(0<=x<=2176 and 0<=y<=1056)
        self.assertEqual(normalized({'scale':float('nan'),'talk_min':80,'talk_max':20})['talk_max'],80)
    def test_context_trim_and_character_sessions_do_not_mix(self):
        messages=[dict(role='user',content='a'*20),dict(role='assistant',content='b'*20),dict(role='user',content='c'*20)]
        clipped=trim_messages(messages,2,25);self.assertEqual(clipped,[messages[-1]])
        with tempfile.TemporaryDirectory() as folder:
            a=SessionStore(folder,'a');a.new()['messages'].append(messages[0]);a.save()
            self.assertEqual(SessionStore(folder,'b').sessions,[])
            self.assertEqual(len(SessionStore(folder,'a').sessions[0]['messages']),1)
    @unittest.skipUnless(os.name=='nt','DPAPI Windows')
    def test_secrets_roundtrip_without_plaintext(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SecretStore(Path(folder)/'keys.json');store.put('test','example-local-test-secret')
            self.assertNotIn('example-local-test-secret',store.path.read_text());self.assertEqual(store.get('test'),'example-local-test-secret')
            store.put('test','');self.assertEqual(store.get('test'),'')
    def test_decoder_bounded_and_cancelled(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'a.gif';frames=[Image.new('RGBA',(64,64),(i*10,0,0,255)) for i in range(20)]
            frames[0].save(path,save_all=True,append_images=frames[1:],duration=40,loop=0)
            player=StreamPlayer();player.start(path,128);time.sleep(.2)
            self.assertLessEqual(player.frames.qsize(),6)
            # A live scale change must never reinterpret old RGBA bytes as a larger buffer.
            pixmap,done=player.advance(512);self.assertEqual(pixmap.width(),128)
            thread=player.thread;player.close()
            from decode_runtime import STATS
            self.assertTrue(STATS.drain());self.assertFalse(thread.is_alive())
    def test_import_validation_rejects_escaping_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'素材清单.json').write_text(json.dumps(dict(idle=dict(id='a',file='../escape.gif'),variants=[])))
            with self.assertRaises(ValueError):validate_character(root)
    def test_directory_import_and_install_upgrade_preserve_data(self):
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';(source/'idle').mkdir(parents=True)
            Image.new('RGBA',(32,32),(0,0,0,0)).save(source/'idle/a.gif')
            key,manifest=import_character(source,root/'characters')
            self.assertEqual(len(validate_character(root/'characters'/key)['variants']),0)
            payload=root/'payload.zip'
            with zipfile.ZipFile(payload,'w') as z:z.writestr('BailongEnhanced.exe',b'unit-test-placeholder')
            target=root/'install';first=install(payload,target,copy_installer=False)
            marker=target/'user-data-marker.txt';marker.write_text('keep')
            second=install(payload,target,copy_installer=False)
            self.assertNotEqual(first,second);self.assertTrue(first.exists());self.assertEqual(marker.read_text(),'keep')
            self.assertEqual(len(read_manifest(target)['versions']),2)
    def test_webm_import_preserves_transparent_background(self):
        import subprocess,imageio_ffmpeg
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';(source/'idle').mkdir(parents=True)
            image=Image.new('RGBA',(64,64),(0,0,0,0));ImageDraw.Draw(image).rectangle((20,20,44,44),fill=(255,255,255,255));image.save(root/'frame.png')
            result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-loop','1','-i',str(root/'frame.png'),'-t','0.2','-c:v','libvpx-vp9','-pix_fmt','yuva420p','-auto-alt-ref','0','-y',str(source/'idle/a.webm')],capture_output=True,timeout=30,creationflags=0x08000000 if os.name=='nt' else 0)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
            key,m=import_character(source,root/'characters')
            with Image.open(root/'characters'/key/m['idle']['playbackFile']) as converted:
                rgba=converted.convert('RGBA');self.assertEqual(rgba.getpixel((0,0))[3],0);self.assertGreater(rgba.getpixel((360,360))[3],240)

class DesktopUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch('enhanced.CONFIG',self.root/'settings.json'),patch('enhanced.STATE_DIR',self.root),patch('desktop.CONFIG',self.root/'settings.json'),patch('desktop.STATE_DIR',self.root)]
        for p in self.patches:p.start()
        self.pet=DesktopPet(monitor=False);self.pet.show();self.pet.bubble.redraw();settle()
    def tearDown(self):
        self.pet.close();settle()
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    def test_real_player_starts_without_pinning_all_assets(self):
        self.assertFalse(self.pet.pinned_frames);self.assertEqual(len(self.pet.frames),1)
        self.assertTrue(until(lambda:self.pet.player.frames.qsize()>0));self.assertLessEqual(self.pet.player.frames.qsize(),6)
    def test_scale_feet_anchor_and_global_through_recovery(self):
        self.pet.move(250,200);foot=self.pet.y()+self.pet.height()
        self.pet.apply_settings({'scale':1.2,'mouse_through':True})
        self.assertEqual(self.pet.y()+self.pet.height(),foot)
        self.assertTrue(self.pet.windowFlags()&Qt.WindowType.WindowTransparentForInput)
        self.pet.recover();self.assertFalse(self.pet.settings['mouse_through']);self.assertTrue(self.pet.isVisible())
    def test_task_completion_survives_drag_and_protects_bubble(self):
        self.pet.dragging=True;self.pet.gate.state='drag'
        with patch.object(self.pet,'notify'),patch.object(self.pet,'refresh_quota'):
            self.pet.on_activity(dict(kind='complete',session='11111111-1111-4111-8111-111111111111',turn='turn-1',title='完成样例'))
        self.assertIsNotNone(self.pet.pending_completion)
        self.assertEqual(self.pet.bubble.status_indicator.visual(),'attention')
        before=self.pet.bubble.status;self.pet.choose(self.pet.variants[0]);self.assertEqual(self.pet.bubble.status,before)
        self.pet.dragging=False;self.pet.gate.state='idle';self.pet.complete_animation(self.pet.pending_completion)
        self.assertNotEqual(self.pet.mode,'task')
        self.pet.player.ended=True
        with patch('desktop.time.monotonic',return_value=time.monotonic()+12),patch.object(self.pet.player,'advance',return_value=(None,True)):
            self.pet.animate()
        self.assertEqual(self.pet.mode,'task')
    def test_indicator_updates_even_while_message_is_held(self):
        self.pet.status_hold=time.monotonic()+30
        self.pet.on_activity(dict(kind='status',state='working',active=1,text='工作中'))
        self.assertEqual(self.pet.bubble.status_indicator.visual(),'busy')
        self.pet.on_activity(dict(kind='token_usage',snapshot={}))
        self.assertEqual(self.pet.bubble.status_indicator.visual(),'busy')
        self.pet.on_activity(dict(kind='monitor_error',text='监听不可用'))
        self.assertEqual(self.pet.bubble.status_indicator.visual(),'warning')

    def test_reply_acknowledgement_survives_held_status_text(self):
        with patch.object(self.pet,'notify'),patch.object(self.pet,'refresh_quota'):
            self.pet.on_activity(dict(kind='complete',session='a',turn='1'))
        icon=self.pet.bubble.status_indicator
        self.pet.status_hold=time.monotonic()+30
        self.pet.on_activity(dict(kind='status',state='thinking',session='b',user_message=True,active=1))
        self.assertEqual(icon.unread,[('a','1')])
        self.pet.on_activity(dict(kind='status',state='thinking',session='a',user_message=True,active=1))
        self.assertFalse(icon.unread);self.assertEqual(icon.visual(),'complete')

    def test_hidden_pet_hides_bubble_on_quota_redraw(self):
        self.pet.toggle_pet();self.pet.update_quota([dict(name='一周',remaining=80,resetsAt=None)],time.time(),'live')
        self.assertFalse(self.pet.bubble.isVisible())
    def test_nonmodal_settings_and_chat_window_reuse(self):
        with patch('desktop_settings.autostart_enabled',return_value=False):self.pet.open_settings()
        self.assertFalse(self.pet.settings_dialog.isModal())
        self.pet.open_chat();window=self.pet.chat_window;window.close();self.pet.open_chat();self.assertIs(self.pet.chat_window,window)
        window.input.setPlainText('不应自动请求');self.assertIsNone(window.stream)
    def test_integrated_pages_stay_interactive_and_follow_topmost_setting(self):
        with patch('desktop_settings.autostart_enabled',return_value=False):self.pet.open_settings()
        self.pet.open_chat();settle()
        for panel in (self.pet.settings_dialog,self.pet.chat_window):
            self.assertIs(panel.parentWidget(),self.pet.bubble.editor_stack);self.assertFalse(panel.isWindow())
        self.assertFalse(self.pet.bubble.windowFlags()&Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertFalse(self.pet.bubble.windowFlags()&Qt.WindowType.WindowTransparentForInput)
        with patch.object(self.pet.bubble,'raise_') as raise_bubble:
            self.pet.position_bubble();self.pet.flush_status();raise_bubble.assert_not_called()
        self.pet.apply_settings({'on_top':False})
        self.assertFalse(self.pet.bubble.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
        self.pet.apply_settings({'on_top':True,'mouse_through':True})
        self.assertTrue(self.pet.bubble.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
        self.assertFalse(self.pet.bubble.windowFlags()&Qt.WindowType.WindowTransparentForInput)
        self.pet.bubble.show_status()
        self.assertTrue(self.pet.bubble.windowHandle().flags()&Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(self.pet.bubble.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        settle()
        self.assertTrue(until(lambda:not self.pet.bubble.size_transition.running
                              and self.pet.bubble.size_transition.landing.image is None))
        with patch.object(self.pet.bubble,'raise_') as raise_bubble:
            self.pet.position_bubble();raise_bubble.assert_called_once()
    def test_page_switch_and_status_updates_preserve_drafts_and_editor_position(self):
        self.pet.open_chat();chat=self.pet.chat_window;settle()
        self.pet.bubble.set_quota_busy(True);self.pet.bubble.set_reset_busy(True);self.pet.bubble.set_token_busy(True)
        chat.input.setFocus();QTest.keyClicks(chat.input,'draft text')
        position=self.pet.bubble.pos();stack=self.pet.bubble.editor_stack
        for i in range(10):self.pet.bubble.message('new status '+str(i));self.pet.position_bubble()
        self.assertEqual(chat.input.toPlainText(),'draft text');self.assertIs(chat.parentWidget(),stack)
        self.assertEqual(self.pet.bubble.pos(),position);self.assertTrue(chat.input.hasFocus())
        self.pet.start_walk();self.assertFalse(self.pet.walking)
        with patch('desktop_settings.autostart_enabled',return_value=False):self.pet.open_settings()
        settings=self.pet.settings_dialog;settings.tabs.setCurrentIndex(1);settings.fields['move_speed'].setValue(123)
        self.pet.open_chat();self.pet.open_settings();self.assertEqual(settings.fields['move_speed'].value(),123)
        self.pet.bubble.show_status();self.pet.open_chat();self.assertEqual(chat.input.toPlainText(),'draft text')
        chat.provider();provider=chat.provider_dialog;self.assertFalse(provider.isWindow())
        provider.fields['model'].setText('unsaved-model');self.pet.open_settings();self.pet.open_chat()
        self.assertIs(chat.pages.currentWidget(),chat.provider_page)
        self.assertEqual(provider.fields['model'].text(),'unsaved-model')
        provider.reject();self.assertIs(chat.pages.currentWidget(),chat.chat_body);self.assertIsNone(chat.stream)
    def test_settings_menu_waits_until_menu_event_has_finished(self):
        menu=QMenu();self.pet.build_menu(menu)
        action=next(a for a in menu.actions() if a.text()=='桌宠设置…')
        menu.popup(self.pet.pos());settle()
        with patch.object(self.pet.bubble,'raise_') as raise_bubble:
            self.pet.position_bubble();raise_bubble.assert_not_called()
        menu.close()
        with patch('desktop_settings.autostart_enabled',return_value=False):
            action.trigger();self.assertIsNone(self.pet.settings_dialog)
            settle();self.assertTrue(self.pet.settings_dialog.isVisible())
    def test_alpha_hit_keeps_transparent_corners_clear(self):
        self.assertFalse(self.pet.alpha_hit(0,0));self.assertFalse(self.pet.alpha_hit(-1,-1))
        self.assertTrue(any(self.pet.alpha_hit(x,y) for x in range(20,240,20) for y in range(20,240,20)))
    def test_bubble_refresh_coalesces_requests_without_sound_or_gestures(self):
        self.pet.choose(self.pet.variants[0]);current=self.pet.current;mode=self.pet.mode;status=self.pet.bubble.status
        with patch('enhanced.QuotaWorker') as worker,patch('pet.Pet.play_click_sound') as sound:
            self.pet.bubble.quota_refresh_button.click();self.pet.refresh_quota()
            self.assertEqual(worker.call_count,1);self.assertTrue(self.pet.quota_inflight)
            self.assertFalse(self.pet.bubble.quota_refresh_button.isEnabled())
            self.assertIs(self.pet.current,current);self.assertEqual(self.pet.mode,mode);self.assertEqual(self.pet.bubble.status,status);sound.assert_not_called()
            self.pet.quota_failed('simulated failure');self.assertTrue(self.pet.bubble.quota_refresh_button.isEnabled())
            self.pet.bubble.quota_refresh_button.click();self.assertEqual(worker.call_count,2)
            self.pet.quota_ready([dict(name='一周',remaining=80,resetsAt=None)])
            self.assertFalse(self.pet.bubble.quota_busy);self.assertIs(self.pet.current,current);sound.assert_not_called()
    def test_one_header_refresh_also_requests_reset_without_per_card_button(self):
        worker=Mock();worker.request_refresh.return_value=1;self.pet.reset_worker=worker
        self.pet.bubble.windows=[dict(name='一周',remaining=80)];self.pet.bubble.select_dashboard('reset')
        with patch('enhanced.QuotaWorker'):
            self.pet.bubble.refresh_button.click();self.pet.refresh_all()
            worker.request_refresh.assert_called_once();self.assertTrue(self.pet.bubble.reset_busy)
            self.assertEqual(self.pet.bubble.reset_refresh_buttons,[])
            self.pet.quota_failed('simulated');self.pet._reset_refresh_finished(1,True)
            self.assertFalse(self.pet.bubble.refresh_busy)
        self.pet.reset_worker=None
    def test_unified_token_refresh_keeps_sound_and_status_unchanged(self):
        worker=Mock();worker.request_tokens.return_value=1;self.pet.activity=worker;status=self.pet.bubble.status
        with patch('pet.Pet.play_click_sound') as sound:
            with patch('enhanced.QuotaWorker'):
                self.pet.bubble.refresh_button.click();self.pet.refresh_all()
                worker.request_tokens.assert_called_once();self.assertTrue(self.pet.bubble.token_busy)
                self.assertEqual(self.pet.bubble.token_refresh_buttons,[])
                self.pet.quota_failed('simulated');self.pet.refresh_flow.result('token',1,True)
            self.assertEqual(self.pet.bubble.status,status);sound.assert_not_called()
        self.pet.activity=None
    def test_bubble_expanded_controls_reuse_windows_and_persist_options(self):
        self.pet.bubble.toggle_details();settle()
        def button(name):return next(b for b in self.pet.bubble.findChildren(QToolButton) if b.objectName()==name and b.isVisible())
        with patch('desktop_settings.autostart_enabled',return_value=False),patch('desktop.open_codex') as open_codex:
            button('bubble_settings').click();settle();self.assertTrue(self.pet.settings_dialog.isVisible())
            button('bubble_chat').click();settle();self.assertTrue(self.pet.chat_window.isVisible())
            button('open_codex').click();deadline=time.monotonic()+2
            while not open_codex.called and time.monotonic()<deadline:app.processEvents();time.sleep(.003)
            open_codex.assert_called_once()
        button('bubble_pin').click();self.assertFalse(self.pet.settings['on_top']);self.assertFalse(self.pet.bubble.pinned)
        self.pet.apply_settings({'no_move':True});settle();self.assertFalse(button('bubble_move').isEnabled())

class StreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                try:
                    for value in ['你','好','！']:
                        data=('data: '+json.dumps(dict(choices=[dict(delta=dict(content=value))]),ensure_ascii=False)+'\n\n').encode()
                        # Includes UTF8 split across writes, exercising byte buffering.
                        self.wfile.write(data[:8]);self.wfile.flush();time.sleep(.04);self.wfile.write(data[8:]);self.wfile.flush()
                    self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def provider(self):return dict(base_url=f'http://127.0.0.1:{self.server.server_port}/v1',model='local-test',timeout=5)
    def test_sse_unicode_and_completion(self):
        stream=ChatStream();deltas=[];done=[];errors=[]
        stream.delta.connect(deltas.append);stream.done.connect(done.append);stream.failed.connect(errors.append)
        stream.start(self.provider(),'', [dict(role='user',content='test')]);self.assertTrue(until(lambda:bool(done or errors)))
        self.assertEqual(errors,[]);self.assertEqual(''.join(deltas),'你好！');self.assertEqual(done,['你好！'])
    def test_cancel_discards_subsequent_stream_events(self):
        stream=ChatStream();deltas=[];done=[];stream.delta.connect(deltas.append);stream.done.connect(done.append)
        stream.start(self.provider(),'',[]);self.assertTrue(until(lambda:bool(deltas)))
        stream.cancel();count=len(deltas);QTest.qWait(250);self.assertEqual(len(deltas),count);self.assertFalse(done)

if __name__=='__main__':unittest.main()
