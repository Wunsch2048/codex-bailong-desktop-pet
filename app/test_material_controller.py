import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import time,unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtTest import QTest
import test_material_store as fixtures
from material_controller import MaterialController,MaterialPanel
from material_store import MaterialError
APP=QApplication.instance() or QApplication([])

def until(check):
    if check():return True
    loop=QEventLoop();timer=QTimer();timer.setInterval(10)
    timer.timeout.connect(lambda:loop.quit() if check() else None)
    timer.start();QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
    return check()

class MaterialRollbackTests(unittest.TestCase):
    def test_rollback_write_failure_restores_runtime_and_reports_error(self):
        from pathlib import Path
        from types import SimpleNamespace

        old=(Path('old'),Path('old/light'))
        store=SimpleNamespace(cache=Path('new'),root=Path('new/light'),state=Path('state'),
                              current='light',catalog={},patch_previous=None,known_available=lambda tier:True)
        controller=MaterialController(store)
        controller._move_restore=old
        controller._move_plan={'target':store.cache}
        controller.publish(phase='pending')
        with patch('storage_locations.save_material_root',side_effect=PermissionError('write denied')) as save:
            controller.failed('entry frame failed')
        save.assert_called_once_with(store.state,old[0])
        self.assertEqual((store.cache,store.root),old)
        self.assertIsNone(controller._move_restore)
        self.assertIsNone(controller._move_plan)
        self.assertEqual(controller.state['phase'],'error')
        self.assertIn('旧目录设置未能写回',controller.state['message'])
        self.assertIn('entry frame failed',controller.state['message'])

class MaterialControllerTests(unittest.TestCase):
    def test_ui_snapshots_and_progress_never_rescan_material_files(self):
        with patch.object(self.store,'available',side_effect=AssertionError('UI performed disk scan')):
            for _ in range(12):
                self.assertTrue(self.c.snapshot()['hdCached'])
                self.c._progress(1,2,'verifying')
                self.panel.refresh(self.c.snapshot())
    def test_unstarted_player_resize_during_hidden_material_switch(self):
        from stream_player import StreamPlayer
        player=StreamPlayer();self.assertIsNone(player.resize(308));player.close()
    def setUp(self):
        self.fixture=fixtures.MaterialStoreTests('test_fresh_default_light_and_missing_hd_preference_falls_back');self.fixture.setUp()
        self.store=self.fixture.store;self.store.import_hd(self.fixture.source)
        self.c=MaterialController(self.store);self.panel=MaterialPanel(self.c)
    def tearDown(self):
        self.c.shutdown();until(lambda:self.c.job is None);self.panel.close();self.panel.deleteLater();APP.processEvents();self.fixture.tearDown()
    def test_ready_only_after_worker_verification_and_pending_blocks_new_request(self):
        ready=[];self.c.ready.connect(lambda *args:ready.append(args))
        self.assertTrue(self.c.request('hd'));self.assertFalse(self.c.request('hd'))
        self.assertTrue(until(lambda:self.c.job is None));self.assertEqual(len(ready),1)
        self.assertEqual(self.store.current,'light');self.assertEqual(self.c.state['phase'],'pending');self.assertFalse(self.c.request('hd'))
        self.store.activate(*ready[0]);self.c.applied();self.assertEqual(self.c.snapshot()['current'],'hd')
    def test_settings_offer_cache_switch_and_do_not_commit_draft_selection(self):
        self.panel.choice.setCurrentIndex(1);self.assertEqual(self.panel.action.text(),'切换画质');self.assertTrue(self.panel.action.isEnabled())
        self.assertEqual(self.store.current,'light');self.assertFalse(self.store.preference.exists())
    def test_unready_or_card_only_panel_defaults_to_saved_hd_without_saving(self):
        for card_only in (False,True):
            with self.subTest(cardOnly=card_only):
                self.store.current=None;self.store.preferred='hd';self.store.card_only=card_only
                panel=MaterialPanel(self.c)
                try:
                    self.assertEqual(panel.choice.currentData(),'hd')
                    self.assertTrue(panel.action.isEnabled())
                    self.assertFalse(self.store.preference.exists())
                finally:panel.close();panel.deleteLater();APP.processEvents()
    def test_material_location_move_cleans_old_cache_and_survives_restart(self):
        from material_store import MaterialStore
        old=self.store.cache;target=self.fixture.root/'external/BailongMaterials'
        self.assertTrue(self.c.move_location(target))
        self.assertTrue(until(lambda:self.c.job is None and self.c.state['phase']=='idle'))
        self.assertFalse(old.exists());self.assertEqual(self.store.cache,target)
        restarted=MaterialStore(self.fixture.app,self.fixture.state)
        self.assertEqual(restarted.cache,target);self.assertTrue(restarted.available('hd'))
        self.assertEqual(self.store.current,'light')
    def test_failed_active_material_handoff_retains_original_location(self):
        from storage_locations import material_root
        self.store.activate('hd',self.store.tier_root('hd'))
        old=self.store.cache;old_root=self.store.root;target=self.fixture.root/'external/BailongMaterials'
        self.c.ready.connect(lambda *args:self.c.failed('entry frame failed'))
        self.assertTrue(self.c.move_location(target));self.assertTrue(until(lambda:self.c.job is None))
        self.assertEqual(self.c.state['phase'],'error');self.assertEqual(self.store.cache,old)
        self.assertEqual(self.store.root,old_root);self.assertTrue(old_root.exists())
        self.assertEqual(material_root(self.store.state),old)
    def test_failed_download_keeps_current_and_allows_retry(self):
        with patch.object(self.store,'ensure',side_effect=MaterialError('尚未公开发布')):
            self.c.request('hd');self.assertTrue(until(lambda:self.c.job is None))
        self.assertEqual(self.c.state['phase'],'error');self.assertIn('尚未公开发布',self.panel.message.text());self.assertEqual(self.store.current,'light')
        self.assertTrue(self.c.request('hd'));self.assertTrue(until(lambda:self.c.job is None));self.assertEqual(self.c.state['phase'],'pending')
    def test_shutdown_cancels_and_waits_for_worker_without_activating(self):
        import threading
        started=threading.Event()
        def block(tier,cancel,progress):
            started.set()
            end=time.monotonic()+2
            while not cancel() and time.monotonic()<end:time.sleep(.01)
            return self.store.tier_root('hd')
        with patch.object(self.store,'ensure',side_effect=block):
            self.c.request('hd');self.assertTrue(started.wait(1));self.assertFalse(self.c.shutdown());self.assertTrue(until(lambda:self.c.job is None))
        self.assertEqual(self.store.current,'light');self.assertEqual(self.c.state['phase'],'verifying')

if __name__=='__main__':unittest.main()
