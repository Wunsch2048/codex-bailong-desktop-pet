import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest,tempfile,json,math
from pathlib import Path
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QImage,QPainter,QRegion
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication,QWidget
from status_indicator import StatusIndicator,busy_ring_centers,BUSY_RING_RADIUS
from status_motion import BUSY_ROTATION_SECONDS
from compact_bubble import CompactBubble

app=QApplication.instance() or QApplication([])

class IndicatorTests(unittest.TestCase):
    def test_precise_cadence_and_frames_do_not_repeat_semantic_ui_sync(self):
        from unittest.mock import patch
        self.assertEqual(self.icon.timer.timerType(),Qt.TimerType.PreciseTimer)
        self.assertEqual(self.icon.timer.interval(),33)
        self.icon.observe(dict(state='working',active=1))
        self.assertEqual(self.icon.timer.interval(),16)
        with patch.object(self.icon,'_sync',wraps=self.icon._sync) as sync:
            for _ in range(50):self.now+=.016;self.icon._tick()
            sync.assert_not_called()
        self.icon.observe(dict(state='idle',active=0))
        self.assertEqual(self.icon.timer.interval(),16)  # Complete the morph first.
        self.now+=.6;self.icon._tick();self.assertEqual(self.icon.timer.interval(),33)
        self.icon.hide();self.assertFalse(self.icon.timer.isActive())
    def setUp(self):
        self.now=100.
        self.icon=StatusIndicator(clock=lambda:self.now);self.icon.show();app.processEvents()
    def tearDown(self):
        self.icon.close();self.icon.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_activity_changes_do_not_restart_rotation(self):
        self.icon.observe(dict(state='thinking',active=1));start=self.icon.busy_since
        self.now+=.7
        self.icon.observe(dict(state='working',active=1));self.icon.observe(dict(state='responding',active=1))
        self.assertEqual(self.icon.busy_since,start);self.assertEqual(self.icon.visual(),'busy')
        self.assertTrue(self.icon.timer.isActive())
    def test_liquid_orbit_stays_inside_small_icon_and_closes_by_identity(self):
        edge=BUSY_RING_RADIUS
        for frame in range(1081):
            centers=busy_ring_centers(frame/100)
            self.assertEqual(len(centers),3)
            for x,y in centers:
                self.assertGreaterEqual(min(x,y)-edge,.6)
                self.assertLessEqual(max(x,y)+edge,15.4)
        start=busy_ring_centers(0);end=busy_ring_centers(BUSY_ROTATION_SECONDS)
        self.assertTrue(all(math.dist(a,b)<1e-9 for a,b in zip(start,end)))
        # The mint ball must retain its identity across the whole-loop seam.
        before=busy_ring_centers(BUSY_ROTATION_SECONDS-.001)
        after=busy_ring_centers(.001)
        self.assertTrue(all(math.dist(a,b)<.02 for a,b in zip(before,after)))
    def test_busy_render_has_solid_balls_and_no_clipped_edges(self):
        self.icon.observe(dict(state='working',active=1))
        self.icon.motion.settle()
        for island in (False,True):
            self.icon.set_island(island)
            for scale in (1,1.25,1.5,2,4):
                for elapsed in (0,.4,.95,1.6,2.75,4.55,10.799):
                    self.now=100+elapsed
                    side=round(16*scale)
                    image=QImage(side,side,QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(Qt.GlobalColor.transparent)
                    painter=QPainter(image);painter.scale(scale,scale)
                    self.icon.render(painter,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren);painter.end()
                    # Liquid balls replace outlines, including the mint one.
                    if scale==4:
                        for x,y in busy_ring_centers(elapsed):
                            self.assertGreater(image.pixelColor(round(x*scale),round(y*scale)).alpha(),250)
                    self.assertTrue(any(image.pixelColor(x,y).alpha()>150 for x in range(side) for y in range(side)))
                    border=[(i,0) for i in range(side)]+[(i,side-1) for i in range(side)]+[(0,i) for i in range(side)]+[(side-1,i) for i in range(side)]
                    # Fractional DPR antialiasing must not produce a solid edge.
                    self.assertLess(max(image.pixelColor(x,y).alpha() for x,y in border),128)
    def test_real_completion_stays_unread_until_clicked(self):
        self.icon.observe(dict(state='working',active=1))
        event=dict(session='a',turn='1')
        self.assertTrue(self.icon.notify_complete(event));self.assertEqual(self.icon.visual(),'attention')
        self.icon.observe(dict(state='complete',active=0));self.now+=.5
        self.assertFalse(self.icon.notify_complete(event));self.assertEqual(self.icon.completed_at,100.)
        self.now+=2;self.icon._tick()
        self.assertEqual(self.icon.visual(),'attention');self.assertFalse(self.icon.timer.isActive())
        self.icon.observe(dict(state='idle',active=0));self.assertEqual(self.icon.visual(),'attention')
        QTest.mouseClick(self.icon,Qt.MouseButton.LeftButton)
        self.assertEqual(self.icon.visual(),'complete');self.assertFalse(self.icon.unread)
        self.now+=1;self.icon.observe(dict(state='thinking',active=1));self.assertEqual(self.icon.visual(),'busy')
    def test_parallel_activity_cannot_clear_unread_notice(self):
        self.icon.observe(dict(state='working',active=2));self.icon.notify_complete(dict(session='a',turn='1'))
        self.icon.observe(dict(state='complete',active=1));self.assertEqual(self.icon.visual(),'attention')
        self.now+=2;self.icon._tick()
        self.assertEqual(self.icon.visual(),'attention');self.assertFalse(self.icon.timer.isActive())
        self.icon.acknowledge();self.assertEqual(self.icon.visual(),'complete')
        self.now+=1;self.icon._tick();self.assertEqual(self.icon.visual(),'busy');self.assertTrue(self.icon.timer.isActive())
    def test_read_old_failed_turn_removes_roster_notice_and_never_resurrects(self):
        import sqlite3
        from contextlib import closing
        from session_read_state import ReadAcknowledgements
        from conversation_roster import ConversationRoster
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);store=home/'notifications.json';self.icon.set_store(store,home)
            (home/'.codex-global-state.json').write_text(json.dumps({'electron-thread-read-state-v1':dict(version=1,unreadByIdentity={'account':{'local:host':['b']}})}),encoding='utf-8')
            with closing(sqlite3.connect(home/'thread_history_1.sqlite')) as db,db:
                db.execute('CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,status TEXT,rollout_ordinal INTEGER)')
                db.executemany('INSERT INTO thread_turns VALUES (?,?,?,?)',[('a','old','failed',1),('a','new','inProgress',2),('b','done','completed',1)])
            roster=ConversationRoster()
            for event in [dict(kind='complete',session='a',turn='old'),dict(kind='complete',session='b',turn='done')]:
                self.icon.notify_complete(event);roster.observe(event)
            running=dict(kind='status',session='a',turn='new',state='working',active=1)
            self.icon.observe(running);roster.observe(running)
            reader=ReadAcknowledgements();self.assertEqual(reader.poll(home,self.icon.unread,100),[])
            self.now=104;keys=reader.poll(home,self.icon.unread,104)
            self.assertTrue(self.icon.acknowledge_seen(keys));self.assertEqual(self.icon.unread,[('b','done')])
            chosen,_=roster.selection(self.icon.unread)
            self.assertEqual([(v['session'],v['state']) for v in chosen],[('b','complete'),('a','working')])
            restored=StatusIndicator();restored.set_store(store,home)
            self.assertEqual(restored.unread,[('b','done')]);self.assertFalse(restored.notify_complete(dict(session='a',turn='old')))
            restored.deleteLater()
    def test_visible_idle_rotates_and_hidden_still_has_no_animation_timer(self):
        self.assertTrue(self.icon.timer.isActive())
        pose=self.icon.motion.sample(self.icon._motion_now())
        self.icon.hide();self.assertFalse(self.icon.timer.isActive())
        self.now+=10;self.assertEqual(pose,self.icon.motion.sample(self.icon._motion_now()))
        self.icon.show();self.assertTrue(self.icon.timer.isActive())
        self.icon.observe(dict(state='working',active=1));start=self.icon.busy_since
        self.icon.hide();self.assertFalse(self.icon.timer.isActive());self.now+=10
        self.icon.show();self.assertTrue(self.icon.timer.isActive());self.assertEqual(self.icon.busy_since,start)
        self.icon.notify_complete(dict(session='visible-task',turn='completed-turn'));self.icon.hide();self.now+=3;self.icon.show()
        self.assertEqual(self.icon.visual(),'attention');self.assertFalse(self.icon.timer.isActive())
    def test_only_actual_reply_in_matching_session_acknowledges(self):
        self.icon.notify_complete(dict(session='a',turn='1'))
        self.icon.notify_complete(dict(session='b',turn='1'))
        self.icon.observe(dict(state='thinking',session='a',active=1))
        self.assertEqual(len(self.icon.unread),2)
        self.icon.observe(dict(state='thinking',session='c',user_message=True,active=1))
        self.assertEqual(len(self.icon.unread),2)
        self.icon.observe(dict(state='thinking',session='a',user_message=True,active=1))
        self.assertEqual(self.icon.unread,[('b','1')]);self.assertEqual(self.icon.visual(),'attention')
        self.icon.observe(dict(state='thinking',session='b',user_message=True,active=2))
        self.assertEqual(self.icon.visual(),'complete');self.assertFalse(self.icon.unread)
        self.now+=1;self.icon._tick();self.assertEqual(self.icon.visual(),'busy')
    def test_unread_survives_restart_without_replaying_wiggle(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'notifications.json';self.icon.set_store(path)
            self.icon.notify_complete(dict(session='a',turn='1'))
            restored=StatusIndicator(clock=lambda:self.now);restored.set_store(path);restored.show()
            try:
                self.assertEqual(restored.visual(),'attention');self.assertFalse(restored.timer.isActive())
                self.assertFalse(restored.notify_complete(dict(session='a',turn='1')))
                restored.acknowledge();self.assertFalse(json.loads(path.read_text())['unread'])
                again=StatusIndicator(clock=lambda:self.now);again.set_store(path)
                self.assertFalse(again.unread);again.deleteLater()
            finally:restored.close();restored.deleteLater()
    def test_long_idle_and_errors_do_not_expire_unread(self):
        self.icon.notify_complete(dict(session='a',turn='1'));self.now+=86400
        self.icon.observe(dict(state='offline',active=0));self.icon._tick()
        self.assertEqual(self.icon.visual(),'attention');self.assertFalse(self.icon.timer.isActive())

    def test_warning_is_static_and_no_false_completion_from_text(self):
        self.icon.observe(dict(state='working',active=1,text='部分测试已完成，继续工作'))
        self.assertEqual(self.icon.visual(),'busy')
        self.icon.observe(dict(state='offline',active=0));self.assertEqual(self.icon.visual(),'warning')
        self.now+=.5;self.icon._tick()
        self.assertFalse(self.icon.timer.isActive())
    def test_bubble_redraw_and_navigation_preserve_widget_and_clock(self):
        bubble=CompactBubble();bubble.show();app.processEvents()
        try:
            icon=bubble.status_indicator;icon.observe(dict(state='working',active=1));start=icon.busy_since
            for i in range(6):
                bubble.redraw();app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
                self.assertIs(bubble.status_indicator,icon);self.assertTrue(icon.isVisible())
            editor=QWidget();bubble.show_page('settings',editor);bubble.size_transition.complete()
            self.assertTrue(icon.isVisible());self.assertTrue(icon.timer.isActive())
            bubble.show_status(False);bubble.size_transition.complete();app.processEvents()
            self.assertIs(bubble.status_indicator,icon);self.assertEqual(icon.busy_since,start)
            self.assertEqual(len(bubble.findChildren(StatusIndicator)),1)
            app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
            title=bubble.findChild(__import__('PySide6.QtWidgets',fromlist=['QToolButton']).QToolButton,'open_codex')
            gap=title.mapTo(bubble,title.rect().topLeft()).x()-icon.mapTo(bubble,icon.rect().topRight()).x()-1
            self.assertEqual(gap,2)
        finally:bubble.close();bubble.deleteLater()

if __name__=='__main__':unittest.main()
