"""Boundary regressions from the v0.8.8 audit; never touch installed user data."""
import hashlib,io,json,os,tempfile,time,unittest
from pathlib import Path
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtCore import QTimer,QLockFile,QSize
from PySide6.QtWidgets import QApplication,QWidget
APP=QApplication.instance() or QApplication([])

class AuditTests(unittest.TestCase):
 def test_restore_data_restores_sqlite_json_and_removes_new_files(self):
  import sqlite3
  from directory_deploy import backup_data,restore_data
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);data=root/'user-data';data.mkdir();(data/'settings.json').write_text('{"v":1}')
   with closing(sqlite3.connect(data/'usage.sqlite3')) as db,db:db.execute('create table x(v)');db.execute('insert into x values(1)')
   backup=backup_data(data,root,'old');(data/'settings.json').write_text('{"v":2}');(data/'new.json').write_text('{}')
   with closing(sqlite3.connect(data/'usage.sqlite3')) as db,db:db.execute('update x set v=2')
   restore_data(data,backup,root)
   self.assertEqual(json.loads((data/'settings.json').read_text()),{'v':1});self.assertFalse((data/'new.json').exists())
   with closing(sqlite3.connect(data/'usage.sqlite3')) as db,db:self.assertEqual(db.execute('select v from x').fetchone()[0],1)
   (backup/'settings.json').write_text('tampered');(data/'settings.json').write_text('keep')
   with self.assertRaises(ValueError):restore_data(data,backup,root)
   self.assertEqual((data/'settings.json').read_text(),'keep')
 def test_full_deploy_failed_start_restores_data_before_restarting_old(self):
  import installer,deployment_state as state
  from test_deployment_transaction import TransactionTests
  case=TransactionTests();case.setUp()
  try:
   data=case.root/'user-data';data.mkdir();settings=data/'settings.json';settings.write_text('{"schema":1}')
   def fail(*a,**kw):settings.write_text('{"schema":2}');raise OSError('not ready')
   with patch.object(installer,'stop_existing',return_value=case.old),patch.object(installer.subprocess,'Popen',return_value=Mock(pid=123)),patch.object(state,'wait_ready',side_effect=fail):
    with self.assertRaises(OSError):installer.deploy(case.payload,False,root=case.root,data_root=data)
   self.assertEqual(json.loads(settings.read_text()),{'schema':1});case.restored()
   self.assertEqual(len(list((case.root/'deployment-backups').iterdir())),1)
  finally:case.tearDown()
 def test_recovery_restores_snapshot_after_process_interruption(self):
  import installer,deployment_state as state
  from directory_deploy import backup_data
  from test_deployment_transaction import TransactionTests
  case=TransactionTests();case.setUp()
  try:
   data=case.root/'user-data';data.mkdir();f=data/'settings.json';f.write_text('old');backup=backup_data(data,case.root,'old')
   snapshot=state.capture_entries(case.root,True);dest=case.root/'versions/interrupted';dest.mkdir();(dest/'BailongEnhanced.exe').write_bytes(b'new')
   state.atomic(case.root/'deployment-journal.json',dict(new_version='interrupted',phase='prepared',snapshot=snapshot,data_root=str(data),data_backup=str(backup)))
   f.write_text('new')
   with patch.object(installer,'DATA',data):state.recover(case.root,True)
   self.assertEqual(f.read_text(),'old');case.restored()
  finally:case.tearDown()
 def test_interrupted_rollback_restores_entries_from_durable_journal(self):
  import deployment_state as state
  from test_deployment_transaction import TransactionTests
  case=TransactionTests();case.setUp()
  try:
   snapshot=state.capture_entries(case.root,True)
   state.atomic(case.root/'maintenance-journal.json',dict(operation='rollback',snapshot=snapshot))
   case.shortcut.write_bytes(b'partial')
   state.recover(case.root,True);case.restored();self.assertFalse((case.root/'maintenance-journal.json').exists())
  finally:case.tearDown()
 def test_rollback_respects_existing_deployment_lock(self):
  import installer
  with tempfile.TemporaryDirectory() as tmp,patch.object(installer,'DATA',Path(tmp)):
   lock=QLockFile(str(Path(tmp)/'deployment.lock'));self.assertTrue(lock.tryLock(0))
   obj=SimpleNamespace(job=None,status=Mock());obj.maintenance_lock=lambda:installer.Installer.maintenance_lock(obj)
   try:
    with patch.object(installer,'register') as register:installer.Installer.rollback(obj);register.assert_not_called()
   finally:lock.unlock()
 def test_absolute_character_file_is_rejected_before_converter(self):
  from desktop_services import import_character
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.mkdir();webm=source/'idle.webm';webm.write_bytes(b'x');original=source/'idle.webp';original.write_bytes(b'preserve')
   (source/'manifest.json').write_text(json.dumps({'idle':{'file':str(webm)}}))
   with patch('desktop_services.subprocess.run') as run:
    with self.assertRaises(ValueError):import_character(source,root/'library')
    run.assert_not_called()
   self.assertEqual(original.read_bytes(),b'preserve')
 def test_token_sources_do_not_mix_and_legacy_database_is_preserved(self):
  from token_calendar import TokenUsageIndex
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);legacy=root/'usage.sqlite3';legacy.write_bytes(b'legacy');a=TokenUsageIndex(legacy,root/'A');b=TokenUsageIndex(legacy,root/'B')
   for index,n in ((a,100),(b,70)):
    with closing(index.connect()) as db,db:db.execute('INSERT INTO usage(fingerprint,stamp,tokens) VALUES(?,?,?)',('x',time.time(),n));self.assertEqual(index.snapshot(db)['all_total'],n)
   self.assertNotEqual(a.path,b.path);self.assertEqual(legacy.read_bytes(),b'legacy')
 def test_legacy_token_history_is_attributed_even_when_logs_are_deleted(self):
  import sqlite3
  from token_analytics import migrate
  from token_calendar import TokenUsageIndex
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);legacy=root/'usage.sqlite3'
   with closing(sqlite3.connect(legacy)) as db,db:
    db.execute('create table files(path TEXT PRIMARY KEY,offset INTEGER,highwater INTEGER)');db.execute('create table usage(fingerprint TEXT PRIMARY KEY,stamp REAL,tokens INTEGER)');migrate(db)
    for home,sid,n in (('A','a',100),('B','b',70)):
     db.execute('insert into files(path,offset,highwater,session) values(?,0,0,?)',(str(root/home/'sessions/deleted.jsonl'),sid))
     db.execute('insert into usage(fingerprint,stamp,tokens,session) values(?,?,?,?)',(sid,time.time(),n,sid))
   original=legacy.read_bytes()
   for home,n in (('A',100),('B',70)):
    index=TokenUsageIndex(legacy,root/home)
    for _ in range(2):
     with closing(index.connect()) as db:self.assertEqual(index.snapshot(db)['all_total'],n)
   self.assertEqual(legacy.read_bytes(),original)
 def test_terminal_ipc_clears_only_matching_active_turn_and_notifies_once(self):
  from enhanced_core import ActivityReducer,Session
  from codex_live_status import LifecycleProjection
  r=ActivityReducer();r.sessions['s']=Session(turn='new',done=False,state='thinking');events=[]
  p=LifecycleProjection(lambda *a:None,emit_terminal=lambda sid,status,turn:events.extend(r.terminate(sid,status,turn)))
  p.states['s']={'turns':[{'turnId':'old','status':'completed'}]};p.heartbeat(10);self.assertFalse(r.sessions['s'].done)
  p.states['s']={'turns':[{'turnId':'new','status':'completed'}]};p.heartbeat(26);p.heartbeat(42)
  self.assertTrue(r.sessions['s'].done);self.assertEqual(sum(e['kind']=='complete' for e in events),1)
  r.sessions['s']=Session(turn='next',done=False,state='working');self.assertEqual(r.terminate('s','unknown','next'),[])
  self.assertEqual(r.terminate('s','failed','next')[-1]['state'],'interrupted')
 def test_chat_disk_error_does_not_leave_busy_or_lose_in_memory_answer(self):
  from chat_window import ChatWindow
  with tempfile.TemporaryDirectory() as tmp:
   pet=QWidget();pet.settings={};pet.manifest={};chat=ChatWindow(pet,tmp,embedded=True);stream=Mock();chat.stream=stream;chat.busy=True
   with patch.object(chat.store,'save',side_effect=OSError('disk full')):chat.on_done(stream,'answer')
   self.assertFalse(chat.busy);self.assertIsNone(chat.stream);self.assertTrue(chat.send_button.isEnabled());self.assertEqual(chat.session['messages'][-1]['content'],'answer')
   chat.shutdown();chat.deleteLater();pet.deleteLater()
 def test_hidden_self_talk_has_no_overdue_one_ms_timer(self):
  from desktop import DesktopPet
  timer=QTimer();timer.start(1000)
  obj=SimpleNamespace(motion_timer=timer,walking=False,throwing=False,settings={'self_talk':True,'character_visible':False},_desktop_hidden=False,next_talk=time.monotonic()-5)
  DesktopPet.schedule_movement(obj);self.assertEqual(timer.interval(),1000);timer.stop()
 def test_cleanup_keeps_current_recent_and_pinned_versions_and_rejects_stale_plan(self):
  import installer
  from installation_cleanup import cleanup_plan,cleanup
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);data=root/'data';data.mkdir();names=['current','recent1','recent2','old','pinned']
   for n in names:(root/'versions'/n).mkdir(parents=True)
   installer.write_manifest(dict(current='current',versions=names,pinnedVersions=['pinned']),root)
   plan=cleanup_plan(root);self.assertNotIn('pinned',plan['versions']);self.assertIn('current',plan['kept'])
   installer.write_manifest(dict(current='recent1',versions=names,pinnedVersions=['pinned']),root)
   with self.assertRaises(OSError):cleanup(root,data,plan)
   self.assertTrue((root/'versions/old').exists())
 def test_cleanup_only_removes_approved_old_versions(self):
  import installer
  from installation_cleanup import cleanup_plan,cleanup
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);data=root/'data';data.mkdir();names=['0.8.9-new','0.8.8-new','0.8.8-old','0.8.7-stable','0.8.6-old','0.7.9-pinned']
   for name in names:(root/'versions'/name).mkdir(parents=True)
   installer.write_manifest(dict(current=names[0],versions=names,pinnedVersions=[names[-1]]),root)
   plan=cleanup_plan(root);self.assertEqual(plan['versions'],[names[2],names[4]])
   result=cleanup(root,data,plan);self.assertEqual(result['versions'],2)
   m=installer.read_manifest(root);self.assertEqual(m['current'],names[0]);self.assertIn('0.8.7-stable',m['versions']);self.assertTrue((root/'versions'/names[-1]).is_dir())
 def test_rollback_registration_failure_restores_entries(self):
  import installer,deployment_state as state
  from test_deployment_transaction import TransactionTests
  case=TransactionTests();case.setUp()
  try:
   m=dict(current='new',versions=['new','old'])
   def fail(*a):case.shortcut.write_bytes(b'partial');raise OSError('COM failure')
   obj=SimpleNamespace(job=None,status=Mock(),startup=Mock());lock=Mock();obj.maintenance_lock=lambda:lock
   with patch.object(installer,'read_manifest',return_value=m),patch.object(installer,'register',side_effect=fail),patch.object(installer,'checked_version',return_value=case.old.parent),patch.object(state,'verify_payload'):
    installer.Installer.rollback(obj)
   case.restored();lock.unlock.assert_called_once()
  finally:case.tearDown()
 def test_fallback_uses_verified_program_package_with_full_fallback(self):
  from app_updates import release_without_api,check_release,API
  import urllib.error
  version='0.8.9';base='bailong-desktop-pet-'+version;info=json.dumps(dict(schema=1,kind='program',version=version,materialId='a'*24)).encode()
  sums=('b'*64+'  '+base+'-windows-x64.zip\n'+'c'*64+'  '+base+'-program.zip\n'+hashlib.sha256(info).hexdigest()+'  '+base+'-program.json\n').encode()
  class Response(io.BytesIO):
   status=206
   def __init__(self,data,headers=None):super().__init__(data);self.headers=headers or {}
  def fetch(url,headers=None):
   if url==API:raise urllib.error.HTTPError(url,403,'limited',{'X-RateLimit-Remaining':'0'},None)
   if url.endswith('SHA256SUMS.txt'):return Response(sums)
   if url.endswith('program.json'):return Response(info)
   return Response(b'',{'Content-Range':'bytes 0-0/'+('100' if '-program.zip' in url else '1000')})
  with patch('program_updates.local_materials'):
   release=check_release('0.8.8',fetch)
  self.assertEqual(release.kind,'program');self.assertEqual(release.size,100);self.assertEqual(release.fallback.kind,'full');self.assertEqual(release.sha256,'c'*64)

@unittest.skipUnless((Path(__file__).resolve().parents[1]/'outputs/白龙桌宠素材/quality-v1/idle.webp').is_file(),'local animation fixtures')
class DesktopAuditTests(unittest.TestCase):
 def setUp(self):
  from test_interaction_batch import InteractionTests
  self.case=InteractionTests();self.case.setUp();self.pet=self.case.pet
 def tearDown(self):self.case.tearDown()
 def test_lazy_pages_preserve_draft_while_visiting_every_category(self):
  self.pet.open_settings();s=self.pet.settings_dialog
  self.assertEqual(s._built_pages,{0});self.assertNotIn('self_talk',s.fields)
  s.fields['on_top'].setChecked(not self.pet.settings['on_top'])
  for index in (2,1,4,3,5,0):s.tabs.setCurrentIndex(index);APP.processEvents()
  self.assertEqual(s._built_pages,set(range(6)));self.assertIn('on_top',s.draft.dirty)
  self.assertEqual(s.field_tabs['status_actions'],2);self.assertEqual(s.field_tabs['self_talk'],4)
 def test_detached_details_do_not_change_height_when_pet_moves(self):
  from test_interaction_batch import settle
  p=self.pet;p.apply_settings({'panel_detached':True},save=False);p.bubble.show_status(True);settle(p)
  heights=[]
  for y in (10,260,510):p.move(p.x(),y);p.bubble.redraw();settle(p);heights.append(p.bubble.content.height())
  self.assertEqual(len(set(heights)),1)
 def test_restore_updates_live_anchor(self):
  p=self.pet;desired=dict(p.settings,panel_detached=True,card_anchor={'screen':'missing','rx':.1,'bottom':.4})
  path=Path(self.case.tmp.name)/'backup-input.json';path.write_text(json.dumps(desired),encoding='utf8')
  with patch('desktop.QFileDialog.getOpenFileName',return_value=(str(path),'')):p.restore_settings()
  self.assertEqual(p._card_anchor,p.settings['card_anchor']);self.assertEqual(p._card_anchor['rx'],.1)

if __name__=='__main__':unittest.main()
