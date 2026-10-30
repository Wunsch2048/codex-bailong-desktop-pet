import os,json,sqlite3,tempfile,time,unittest
from contextlib import closing
from pathlib import Path
from datetime import datetime
os.environ['QT_QPA_PLATFORM']='offscreen'
from project_cost import migrate,update,snapshot,search_rows

class CostTests(unittest.TestCase):
    def test_legacy_models_are_priced_without_inventing_unknown_or_incomplete_costs(self):
        from project_cost import rate
        self.assertEqual(rate('gpt-6-sol-2026-09-22'),(2,.2,10))
        self.assertEqual(rate('gpt-5.6-luna'),(.2,.02,1.2))
        self.assertIsNone(rate('gpt-6-sol-custom'))
        with sqlite3.connect(':memory:') as db:
            migrate(db);now=time.time()
            for ident,model,known in [('sol','gpt-6-sol',1),('luna','gpt-5.6-luna',1),('unknown','new-unknown',1),('incomplete','gpt-6-sol',0)]:
                db.execute('INSERT INTO cost_events VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,now-1,ident,'d:/project',model,1000,800,600,200,known))
            result=snapshot(db,now,dict(pending=False,errors=0))['ranges']['all'][0]
            self.assertEqual(result['pending_tokens'],2000)
            self.assertAlmostEqual(result['cost'],.002812)
    def test_yesterday_excludes_today_and_older_records_and_keeps_unknown(self):
        now=datetime(2026,10,29,12).timestamp()
        with sqlite3.connect(':memory:') as db:
            migrate(db)
            for ident,stamp,model in [('older',datetime(2026,10,27,23,59).timestamp(),'gpt-6.1-sol'),('start',datetime(2026,10,28).timestamp(),'gpt-6.1-sol'),('end',datetime(2026,10,28,23,59).timestamp(),'unknown'),('today',datetime(2026,10,29).timestamp(),'gpt-6.1-sol')]:
                db.execute('INSERT INTO cost_events VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,stamp,ident,'d:/project',model,1000,800,600,200,1))
            data=snapshot(db,now,dict(pending=False,errors=0))
            p=data['ranges']['yesterday'][0]
            self.assertEqual(data['yesterday'],'2026-10-28');self.assertEqual(p['tokens'],2000)
            self.assertEqual(p['pending_tokens'],1000);self.assertAlmostEqual(p['cost'],.00246)
            self.assertEqual(data['ranges']['all'][0]['tokens'],4000)

    def test_incremental_cache_restart_archive_and_independent_equal_events(self):
        with tempfile.TemporaryDirectory() as folder:
            h=Path(folder);now=time.time();stamp=datetime.fromtimestamp(now-1).astimezone().isoformat()
            def file(sid,path,total=1000):
                p=h/(sid+'.jsonl');rows=[dict(type='session_meta',timestamp=stamp,payload=dict(id=sid,cwd=path)),dict(type='turn_context',timestamp=stamp,payload=dict(model='gpt-6.1-sol')),dict(type='event_msg',timestamp=stamp,payload=dict(type='token_count',info=dict(total_token_usage=dict(total_tokens=total,input_tokens=800,cached_input_tokens=600,output_tokens=200))))]
                p.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8');return p
            a=file('a','D:/Project/One');b=file('b','D:/Project/Two');files=[a,b]
            db=sqlite3.connect(h/'index.sqlite');migrate(db)
            progress=update(db,files,budget=5);data=snapshot(db,now,progress,files,h)
            self.assertEqual(len(data['ranges']['all']),2)
            self.assertAlmostEqual(data['ranges']['all'][0]['cost'],.00246)
            update(db,files,budget=5);self.assertEqual(len(__import__('project_cost_store').active_events(db)[0]),2)
            db.commit();db.close();db=sqlite3.connect(h/'index.sqlite');update(db,files,budget=5)
            self.assertEqual(len(__import__('project_cost_store').active_events(db)[0]),2)
            with sqlite3.connect(h/'state_5.sqlite') as meta:
                meta.execute('CREATE TABLE threads(id TEXT,archived INTEGER)');meta.execute("INSERT INTO threads VALUES ('a',1)")
            meta.close()
            data=snapshot(db,now,progress,files,h)
            self.assertEqual(len(search_rows(data,query='ONE d:\\project',archive='archived')),1)
            self.assertEqual(len(search_rows(data,archive='active')),1)
            self.assertNotIn('message', '\n'.join(db.iterdump()));db.close()
    def test_unknown_models_missing_cache_and_partial_line_are_not_zero_cost(self):
        with tempfile.TemporaryDirectory() as folder:
            h=Path(folder);p=h/'x.jsonl';now=time.time();stamp=datetime.fromtimestamp(now-1).astimezone().isoformat()
            rows=[dict(type='session_meta',timestamp=stamp,payload=dict(id='x',cwd='D:/X',model='unpriced')),dict(type='event_msg',timestamp=stamp,payload=dict(type='token_count',info=dict(total_token_usage=dict(total_tokens=100,input_tokens=80,output_tokens=20))))]
            p.write_text(''.join(json.dumps(r)+'\n' for r in rows)+'{"partial":',encoding='utf-8')
            with sqlite3.connect(':memory:') as db:
                second=h/'z.jsonl';second.write_text(''.join(json.dumps(r).replace('"x"','"z"')+'\n' for r in rows),encoding='utf-8')
                migrate(db);progress=update(db,[p,second],budget=1);r=snapshot(db,now,progress,[p,second])
                self.assertTrue(r['pending']);self.assertEqual(r['ranges']['all'][0]['pending_tokens'],200)
                self.assertEqual(len(__import__('project_cost_store').active_events(db)[0]),2)
    def test_native_search_scroll_and_return(self):
        from PySide6.QtWidgets import QApplication
        from project_cost_ui import ProjectCosts
        app=QApplication.instance() or QApplication([])
        rows=[dict(id=str(i),name='项目'+str(i),path='D:/project/'+str(i),cost=1.,parts=[.5,.1,.4],tokens=1000,pending_tokens=0,models=['gpt-6.1-sol'],sessions=1,archived=False) for i in range(5)]
        view=ProjectCosts();view.resize(246,280);view.set_data(dict(ranges={'all':rows}),'all');view.show();app.processEvents()
        self.assertEqual(view.list.count(),6)  # summary scrolls with the five projects
        self.assertEqual(view.list.verticalScrollBarPolicy(),__import__('PySide6.QtCore',fromlist=['Qt']).Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        view.select(view.list.item(3).data(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.ItemDataRole.UserRole));self.assertIsNotNone(view.selected)
        view.back.click();self.assertIsNone(view.selected)
        view.search.setText('项目3 project');self.assertEqual(view.list.count(),2)
        self.assertEqual(view.list.item(1).data(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.ItemDataRole.UserRole)['id'],'3');view.close()
        from test_daily_report import ReportUiTests,sample
        case=ReportUiTests();case.setUp()
        try:
            data=sample();data['projects']=dict(ranges={'all':rows})
            case.r.set_snapshot(data);case.r.open();case.complete();case.r.set_page('projects')
            case.r.page_fade.animation.setCurrentTime(case.r.page_fade.animation.duration());app.processEvents()
            self.assertTrue(case.r.project_view.search.isVisible())
            self.assertTrue(callable(case.r.project_view.layout))
            # The scrollable list, not an outer bottom spacer, owns all remaining body height.
            body=case.r.scroll.widget();view=case.r.project_view
            self.assertLessEqual(body.rect().bottom()-view.geometry().bottom(),5)
            case.r.set_page('models');case.r.set_page('projects');app.processEvents()
        finally:case.tearDown()

    def test_detail_travel_preserves_search_and_list_position(self):
        from PySide6.QtWidgets import QApplication
        from project_cost_ui import ProjectCosts
        from unittest.mock import patch
        app=QApplication.instance() or QApplication([])
        rows=[dict(id=str(i),name='项目'+str(i),path='D:/project/'+str(i),cost=1.,parts=[.5,.1,.4],tokens=1000,pending_tokens=0,models=['gpt-6.1-sol'],sessions=1,archived=False) for i in range(20)]
        view=ProjectCosts();view.resize(246,350);view.set_data(dict(ranges={'all':rows}),'all');view.show();app.processEvents()
        view.search.setText('project');view.list.verticalScrollBar().setValue(200);before=view.list.verticalScrollBar().value()
        with patch('project_cost_ui.motion_enabled',return_value=True):
            view.select(rows[6]);app.processEvents();self.assertTrue(view.detail_motion.slide);self.assertEqual(view.detail_motion.direction,1)
            view.detail_motion.animation.setCurrentTime(view.detail_motion.animation.duration());view.select(None);app.processEvents()
            self.assertEqual(view.detail_motion.direction,-1);self.assertEqual(view.search.text(),'project');self.assertEqual(view.list.verticalScrollBar().value(),before)
            view.detail_motion.animation.setCurrentTime(view.detail_motion.animation.duration())
            view.select(rows[6]);view.hide();app.processEvents();self.assertFalse(view.detail_motion.isVisible())
        view.close();view.deleteLater();app.processEvents()

    def test_detail_reentry_resets_scroll_but_refresh_and_back_preserve_visit_context(self):
        from PySide6.QtWidgets import QApplication
        from project_cost_ui import ProjectCosts
        app=QApplication.instance() or QApplication([])
        rows=[dict(id=str(i),name='项目'+str(i),path='D:/project/'+str(i),cost=1.,parts=[.5,.1,.4],tokens=1000,pending_tokens=0,models=['模型'+str(n) for n in range(15)],sessions=1,archived=False) for i in range(12)]
        view=ProjectCosts();view.resize(246,350);view.set_data(dict(ranges={'all':rows}),'all');view.show();app.processEvents()
        try:
            view.list.verticalScrollBar().setValue(180);parent_position=view.list.verticalScrollBar().value()
            for _ in range(2):
                view.select(rows[4]);app.processEvents();view.detail_motion.animation.setCurrentTime(view.detail_motion.animation.duration())
                self.assertEqual(view.details.verticalScrollBar().value(),0)
                bar=view.details.verticalScrollBar();self.assertGreater(bar.maximum(),100);bar.setValue(120)
                body=view.details.widget();view.set_data(dict(ranges={'all':rows}),'all');app.processEvents()
                self.assertIs(view.details.widget(),body);self.assertEqual(bar.value(),120)
                view.select(None);app.processEvents();view.detail_motion.animation.setCurrentTime(view.detail_motion.animation.duration())
                self.assertEqual(view.list.verticalScrollBar().value(),parent_position)
            view.select(rows[4]);ticket=view._detail_transition;view.select(None);view._reset_detail_entry(ticket,rows[4]['id'])
            self.assertIsNone(view.selected)
        finally:view.close();view.deleteLater();app.processEvents()

    def test_reassignment_keeps_history_totals_and_survives_metadata_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            h=Path(folder);now=time.time()
            from project_cost import project_path
            self.assertEqual(project_path(r'\\?\D:\New'),project_path('d:/new'))
            with sqlite3.connect(':memory:') as db:
                migrate(db)
                db.execute("INSERT INTO cost_events VALUES ('e',?,'moved','d:/old','gpt-6.1-sol',1000,800,600,200,1)",(now-1,))
                with closing(sqlite3.connect(h/'state_5.sqlite')) as meta,meta:
                    meta.execute('CREATE TABLE threads(id TEXT,archived INTEGER,cwd TEXT)')
                    meta.execute("INSERT INTO threads VALUES ('moved',0,?)",(r'\\?\D:\New',))
                result=snapshot(db,now,dict(pending=False,errors=0),[],h)
                self.assertEqual(result['ranges']['all'][0]['path'],'d:/new')
                self.assertEqual(result['ranges']['all'][0]['tokens'],1000)
                self.assertEqual(db.execute('SELECT project FROM cost_events').fetchone()[0],'d:/old')
                again=snapshot(db,now,dict(pending=False,errors=0),[],None)
                self.assertEqual(again['ranges']['all'][0]['path'],'d:/new')

    def test_explicit_membership_does_not_merge_shared_roots_and_children_count_once(self):
        with tempfile.TemporaryDirectory() as folder:
            h=Path(folder);now=time.time()
            global_state={'local-projects':{'a':{'name':'原项目','rootPaths':['D:/shared']},'b':{'name':'新项目','rootPaths':['D:/new','D:/shared']}},'thread-project-assignments':{'stays':{'projectId':'a'},'moves':{'projectId':'b'}}}
            (h/'.codex-global-state.json').write_text(json.dumps(global_state),encoding='utf-8')
            with closing(sqlite3.connect(h/'state_5.sqlite')) as meta,meta:
                meta.execute('CREATE TABLE threads(id TEXT,cwd TEXT,archived INTEGER,source TEXT)')
                meta.executemany('INSERT INTO threads VALUES (?,?,0,?)',[('stays','D:/shared','vscode'),('moves','D:/shared','vscode'),('child','D:/shared',json.dumps({'subagent':{'thread_spawn':{'parent_thread_id':'moves'}}}))])
            with sqlite3.connect(':memory:') as db:
                migrate(db)
                for i,sid in enumerate(('stays','moves','child')):db.execute('INSERT INTO cost_events VALUES (?,?,?,?,?,?,?,?,?,?)',(str(i),now-1,sid,'d:/shared','gpt-6.1-sol',1000,800,600,200,1))
                data=snapshot(db,now,dict(pending=False,errors=0),[],h)
                projects={p['id']:p for p in data['ranges']['all']}
                self.assertEqual(projects['project:a']['tokens'],1000)
                self.assertEqual(projects['project:b']['tokens'],2000)
                self.assertEqual(projects['project:b']['sessions'],1)
                self.assertEqual(projects['project:b']['path'],'d:/new')


    def test_wheel_interpolates_and_unchanged_refresh_keeps_items(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
        from PySide6.QtGui import QWheelEvent
        from project_cost_ui import ProjectCosts
        from unittest.mock import patch
        app=QApplication.instance() or QApplication([])
        rows=[dict(id=str(i),name='项目'+str(i),path='D:/project/'+str(i),cost=1.,parts=[.5,.1,.4],tokens=1000,pending_tokens=0,models=[],sessions=1,archived=False) for i in range(20)]
        data=dict(ranges={'all':rows});view=ProjectCosts();view.resize(246,350);view.set_data(data,'all');view.show();app.processEvents()
        bar=view.list.verticalScrollBar();item=view.list.item(1)
        event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        with patch('project_cost_ui.motion_enabled',return_value=True):
            self.assertTrue(view.list_scroll.eventFilter(view.list.viewport(),event))
            self.assertEqual(bar.value(),0)
            view.list_scroll.animation.setCurrentTime(80);self.assertGreater(bar.value(),0);self.assertLess(bar.value(),60)
            view.list_scroll.animation.setCurrentTime(160);self.assertEqual(bar.value(),60)
            view.set_data(data,'all');self.assertIs(view.list.item(1),item);self.assertEqual(bar.value(),60)
            self.assertIn('_summary',view.list.item(0).data(Qt.ItemDataRole.UserRole))
            view.list.grab()  # include scrolled summary/delegate painting
        view.close();view.deleteLater();app.processEvents()

if __name__=='__main__':unittest.main()
