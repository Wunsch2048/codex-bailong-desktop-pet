"""New cost routes, saved pricing, private exports and service/placement contracts."""
import os,json,sqlite3,tempfile,time,unittest
from contextlib import closing
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QRect,QPoint,QEvent,QCoreApplication
from PySide6.QtWidgets import QApplication,QWidget,QPushButton
from PySide6.QtTest import QTest
import cost_preferences as prefs
from project_cost import migrate,update,snapshot
from cost_details import detail_snapshot,export_rows,encode_export
from public_status import decode_status,bubble_position,shared,service_colors
from pricing_ui import PricingEditor
from project_cost_ui import ProjectCosts
APP=QApplication.instance() or QApplication([])

def fixture(home):
    now=time.time()-50;rows=[dict(type='session_meta',payload=dict(id='s1',cwd='D:/pet')),dict(type='turn_context',payload=dict(turn_id='t1',model='gpt-6.1-sol'))]
    for i,turn in enumerate(('t1','t2')):
        rows.append(dict(type='turn_context',payload=dict(turn_id=turn,model='gpt-6.1-sol')))
        rows.append(dict(type='event_msg',timestamp=__import__('datetime').datetime.fromtimestamp(now+i).astimezone().isoformat(),payload=dict(type='token_count',info=dict(total_token_usage=dict(total_tokens=(i+1)*1000,input_tokens=(i+1)*800,cached_input_tokens=(i+1)*100,output_tokens=(i+1)*200)))))
    source=home/'log.jsonl';source.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8');dbpath=home/'cost.sqlite'
    with closing(sqlite3.connect(dbpath)) as db,db:
        migrate(db);progress=update(db,[source],budget=2);data=snapshot(db,time.time(),progress,[source])
    return dbpath,data

class CostExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.patcher=patch('cost_preferences.path',return_value=self.home/'pricing.json');self.patcher.start();prefs._cached=None;self.widgets=[]
    def tearDown(self):
        for widget in self.widgets:widget.close();widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents();self.patcher.stop();prefs._cached=None;self.temp.cleanup()
    def test_save_reload_and_blank_vs_free(self):
        p=prefs.defaults();p['prices']={'free':[0,0,0],'missing':[None,0,0]};prefs.save(p);self.assertEqual(prefs.load()['prices'],p['prices']);self.assertEqual(prefs.prices()['free'],(0,0,0));self.assertNotIn('missing',prefs.prices())
    def test_bad_prices_never_replace_saved_values(self):
        prefs.save(prefs.defaults())
        for value in (-1,float('nan'),True):
            p=prefs.defaults();p['prices']={'bad':[value,0,0]}
            with self.assertRaises(ValueError):prefs.save(p)
        self.assertEqual(prefs.load()['prices'],{})
    def test_price_save_changes_projection_without_changing_ledger(self):
        dbpath,data=fixture(self.home);p=prefs.defaults();p['prices']={'gpt-6.1-sol':[0,0,0]};prefs.save(p)
        with closing(sqlite3.connect(dbpath)) as db:after=snapshot(db,time.time(),{},[])
        self.assertNotEqual(after['price_revision'],data['price_revision']);self.assertEqual(after['ranges']['all'][0]['cost'],0);self.assertEqual(after['ranges']['all'][0]['tokens'],2000)
    def test_readonly_detail_two_turns_and_cost_conservation(self):
        dbpath,data=fixture(self.home);project=data['ranges']['all'][0];sessions=detail_snapshot(dbpath,project)
        self.assertEqual(len(sessions),1);self.assertEqual({t['id'] for t in sessions[0]['turns']},{'t1','t2'});self.assertEqual(sessions[0]['tokens'],project['tokens']);self.assertAlmostEqual(sessions[0]['cost'],project['cost'])
    def test_old_metadata_is_derived_without_reindex_or_writes(self):
        dbpath,data=fixture(self.home)
        before=dbpath.read_bytes();rows=detail_snapshot(dbpath,data['ranges']['all'][0]);self.assertEqual(len(rows[0]['turns']),2);self.assertEqual(dbpath.read_bytes(),before)
    def test_export_uses_current_filter_and_omits_private_fields(self):
        _,data=fixture(self.home);rows=list(export_rows(data,'all','pet','all'));raw=encode_export(rows,'JSON');self.assertEqual(json.loads(raw)['currency'],'USD');self.assertNotIn(b'D:/',raw);self.assertNotIn(b's1',raw);self.assertEqual(list(export_rows(data,'all','notpresent','all')),[])
    def test_csv_bom_and_formula_data(self):
        raw=encode_export([dict(project='=1+1',period='all',model='m',tokens=1,usd_cost=0,unpriced_tokens=0)],'CSV');self.assertTrue(raw.startswith(b'\xef\xbb\xbf'));self.assertIn(b"'=1+1",raw)
    def test_pricing_editor_discard_never_saves(self):
        host=QWidget();self.widgets.append(host);host.resize(230,410);host.show();editor=PricingEditor(host);editor.draft['currency']='HKD';editor.close();self.assertFalse(prefs.path().exists())
    def test_pricing_editor_save_and_restore_builtin(self):
        host=QWidget();self.widgets.append(host);host.resize(230,410);host.show();editor=PricingEditor(host);editor.edit_model('gpt-6.1-sol');editor.price_fields[0].setText('0');editor.finish_model();editor.commit_draft();self.assertEqual(prefs.load()['prices']['gpt-6.1-sol'][0],0)
    def test_new_visit_resets_session_and_scroll(self):
        _,data=fixture(self.home);view=ProjectCosts();self.widgets.append(view);view.resize(260,370);view.set_data(data,'all');view.select(data['ranges']['all'][0]);view.session={'id':'s'};view.reset_navigation();self.assertIsNone(view.selected);self.assertIsNone(view.session);self.assertEqual(view.list.verticalScrollBar().value(),0)
    def test_project_defaults_to_sessions_and_composition_is_separate(self):
        from project_cost_ui import MetricLine,SessionButton,DetailSummary
        _,data=fixture(self.home);view=ProjectCosts();self.widgets.append(view);view.resize(248,370);view.set_data(data,'all');view.select(data['ranges']['all'][0])
        body=view.details.widget();self.assertTrue(body.findChildren(SessionButton));self.assertFalse(body.findChildren(MetricLine));self.assertEqual(body.findChild(DetailSummary).height(),94)
        view.project_part='composition';view._detail_key=None;view.refresh();self.assertTrue(view.details.widget().findChildren(MetricLine));self.assertFalse(view.details.widget().findChildren(SessionButton))
    def test_model_back_discards_uncommitted_fields(self):
        host=QWidget();self.widgets.append(host);host.resize(248,370);host.show();editor=PricingEditor(host);editor.edit_model('gpt-6.1-sol');editor.price_fields[0].setText('-2');editor.go_back();self.assertIsNone(editor.model);self.assertNotIn('gpt-6.1-sol',editor.draft['prices']);self.assertFalse(prefs.path().exists())
    def test_status_classification_and_validation(self):
        self.assertEqual(decode_status({'status':{'indicator':'none'}})['tone'],'unknown');self.assertEqual(decode_status({'status':{'indicator':'major'},'components':[dict(name='Codex in ChatGPT Desktop',status='major_outage')]})['tone'],'warn')
        with self.assertRaises(ValueError):decode_status({'status':{}})
    def test_color_semantics_in_dark_and_light(self):
        for surface in ('#fff','#111'):
            theme=dict(surface=surface);yellow=service_colors(theme,'warn');red=service_colors(theme,'unknown');self.assertNotEqual(yellow,red)
    def test_placement_four_edges_and_fallback(self):
        area=QRect(0,0,1000,800)
        for card in (QRect(400,400,268,180),QRect(0,0,268,180),QRect(730,0,268,180),QRect(200,0,600,180)):
            r=bubble_position(card,card,(294,140),area);self.assertTrue(area.contains(r));self.assertFalse(r.intersects(card))
        area=QRect(0,0,300,200);card=QRect(0,0,268,180);self.assertTrue(area.contains(bubble_position(card,card,(294,140),area)))
    def test_service_detail_keeps_rate_and_back_returns_same_popup(self):
        from live_rate_ui import LiveRateCard
        host=LiveRateCard(dict(rate=20,details=[dict(name='a',rate=20)]));self.widgets.append(host);host.setGeometry(350,400,121,20);host.show()
        with patch.object(shared(),'request'):
            QTest.mouseClick(host,__import__('PySide6.QtCore',fromlist=['Qt']).Qt.MouseButton.LeftButton);popup=host.service_panel;popup.geometry_motion.setCurrentTime(200);APP.processEvents();self.assertEqual(popup.page,'service');self.assertEqual(popup.total,20)
            QTest.mouseClick(popup,__import__('PySide6.QtCore',fromlist=['Qt']).Qt.MouseButton.LeftButton,pos=QPoint(40,16));self.assertEqual(popup.page,'sessions')
    def test_native_session_route_shows_token_parts_without_expansion_and_returns(self):
        dbpath,data=fixture(self.home);view=ProjectCosts();self.widgets.append(view);view.resize(260,360);view.set_data(data,'all');view.show();view.select(data['ranges']['all'][0]);session=detail_snapshot(dbpath,data['ranges']['all'][0])[0];view.open_session(session);QTest.qWait(280)
        from project_cost_ui import TurnRow
        from PySide6.QtWidgets import QAbstractButton
        rows=view.findChildren(TurnRow);self.assertEqual(len(rows),2);self.assertEqual(rows[0].token_parts,[700,100,200]);self.assertFalse(isinstance(rows[0],QAbstractButton));view.go_back();QTest.qWait(220);self.assertIsNone(view.session);self.assertIsNotNone(view.selected);view.go_back();self.assertIsNone(view.selected)
    def test_export_handler_writes_actual_chosen_file(self):
        _,data=fixture(self.home);view=ProjectCosts();self.widgets.append(view);view.set_data(data,'all');target=self.home/'export.csv'
        with patch('project_cost_ui.QFileDialog.getSaveFileName',return_value=(str(target),'CSV')),patch('project_cost_ui.QMessageBox.information') as notice:
            view.show_export();button=next(b for b in view.findChildren(QPushButton) if b.text()=='导出文件');button.click();self.assertTrue(target.read_bytes().startswith(b'\xef\xbb\xbf'));notice.assert_called_once()
    def test_export_handler_reports_write_failure(self):
        _,data=fixture(self.home);view=ProjectCosts();self.widgets.append(view);view.set_data(data,'all')
        with patch('project_cost_ui.QFileDialog.getSaveFileName',return_value=(str(self.home/'absent'/'a.csv'),'CSV')),patch('project_cost_ui.QMessageBox.warning') as error,patch('project_cost_ui.QMessageBox.information') as success:
            view.show_export();next(b for b in view.findChildren(QPushButton) if b.text()=='导出文件').click();error.assert_called_once();success.assert_not_called()
    def test_service_failure_retains_last_good_as_previous(self):
        from public_status import PublicStatus
        from PySide6.QtNetwork import QNetworkReply
        from types import SimpleNamespace
        service=PublicStatus();service.last=decode_status({'status':{'indicator':'none'}},now=123)
        service.reply=SimpleNamespace(error=lambda:QNetworkReply.NetworkError.TimeoutError,deleteLater=lambda:None);service._finished();self.assertEqual(service.value['tone'],'unknown');self.assertEqual(service.value['previous']['checked'],123)
    def test_new_currency_requires_rate_and_does_not_save_one_by_accident(self):
        host=QWidget();self.widgets.append(host);host.resize(230,410);host.show();editor=PricingEditor(host);editor.currency.setCurrentIndex(editor.currency.findData('CNY'));editor.commit_draft();self.assertFalse(prefs.path().exists());self.assertIn('未保存',editor.status.text())
    def test_project_summary_reuses_snapshot_without_detail_job(self):
        _,data=fixture(self.home);project=data['ranges']['all'][0];self.assertEqual(sum(s['tokens'] for s in project['session_usage']),project['tokens']);self.assertAlmostEqual(sum(s['cost'] for s in project['session_usage']),project['cost'])
        view=ProjectCosts();self.widgets.append(view);view.set_data(data,'all')
        with patch('project_cost_ui.DetailJob') as job:
            for _ in range(3):view.select(project);view.select(None)
            job.assert_not_called()
    def test_long_multiline_session_title_has_bounded_row_and_amount(self):
        from project_cost_ui import SessionButton
        button=SessionButton(dict(id='x',name='项目说明\n# Files mentioned by user\n'+('长标题'*100),tokens=1040000000,cost=329));self.widgets.append(button);button.resize(240,57);button.show();APP.processEvents();button.grab()
        self.assertEqual(button.height(),57);self.assertNotIn('\n',button.title);self.assertLess(button.title_rect.right(),button.width()-35)
    def test_warm_turn_entry_reuses_complete_result_and_new_revision_reloads(self):
        dbpath,data=fixture(self.home);project=data['ranges']['all'][0];session=project['session_usage'][0]
        view=ProjectCosts();self.widgets.append(view);view.detail_index_path=dbpath;view.set_data(data,'all');view.select(project);view.open_session(session)
        for _ in range(100):
            APP.processEvents();QTest.qWait(10)
            if view.detail_job is None:break
        self.assertIn('turns',view.session);self.assertEqual(len(view.session['turns']),2);view.open_session(None)
        with patch('project_cost_ui.DetailJob') as job:
            view.open_session(session);job.assert_not_called();self.assertEqual(len(view.session['turns']),2)
        view.open_session(None)
        with patch('project_cost_ui.DetailJob') as job:
            view.open_session(dict(session,detail_revision='changed'));job.assert_called_once()
            view.detail_job=None
    def test_cost_names_prefer_sidebar_name_and_rename_preserves_usage_revision(self):
        dbpath,data=fixture(self.home)
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:
            db.execute('CREATE TABLE threads(id TEXT,cwd TEXT,name TEXT,title TEXT)');db.execute('INSERT INTO threads VALUES(?,?,?,?)',('s1','D:/pet','龙娘桌宠','帮我找找有没有gpt龙娘'))
        with closing(sqlite3.connect(dbpath)) as db,db:first=snapshot(db,time.time(),{},home=self.home)
        a=first['ranges']['all'][0]['session_usage'][0];self.assertEqual(a['name'],'龙娘桌宠');self.assertEqual(detail_snapshot(dbpath,first['ranges']['all'][0],home=self.home)[0]['name'],'龙娘桌宠')
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:db.execute('UPDATE threads SET name=?',('新的会话名字',))
        with closing(sqlite3.connect(dbpath)) as db,db:second=snapshot(db,time.time(),{},home=self.home)
        b=second['ranges']['all'][0]['session_usage'][0];self.assertEqual(b['name'],'新的会话名字');self.assertEqual((a['tokens'],a['cost'],a['detail_revision']),(b['tokens'],b['cost'],b['detail_revision']))
    def test_legacy_title_only_store_remains_readable(self):
        from session_read_state import conversation_names,conversation_display_name
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db,db:
            db.execute('CREATE TABLE threads(id TEXT,title TEXT)');db.execute('INSERT INTO threads VALUES(?,?)',('s','旧会话标题'))
        self.assertEqual(conversation_names(self.home,['s']),{'s':'旧会话标题'});self.assertEqual(conversation_display_name(dict(name='  ',title='后备标题')),'后备标题')
    def test_visible_session_rename_updates_heading_without_reloading_turns(self):
        import copy
        _,data=fixture(self.home);p=data['ranges']['all'][0];view=ProjectCosts();self.widgets.append(view);view.set_data(data,'all');view.select(p);view.session=dict(p['session_usage'][0],turns=[])
        changed=copy.deepcopy(data);changed['ranges']['all'][0]['session_usage'][0]['name']='侧栏新名字'
        with patch('project_cost_ui.DetailJob') as job:view.set_data(changed,'all');self.assertEqual(view.session['name'],'侧栏新名字');job.assert_not_called()

if __name__=='__main__':unittest.main()
