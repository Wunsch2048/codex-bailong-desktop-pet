import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import Qt,QRect
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel
from PySide6.QtTest import QTest
from card_motion import AnimatedDisclosure
from inline_confirmation import InlineConfirmation
import test_interaction_batch as fixtures

APP=QApplication.instance() or QApplication([])


class CardMotionTests(unittest.TestCase):
    def setUp(self):
        self.window=QWidget();layout=QVBoxLayout(self.window);body=QWidget();rows=QVBoxLayout(body)
        for i in range(8):rows.addWidget(QLabel('保留的内容 '+str(i)))
        self.card=AnimatedDisclosure(body);layout.addWidget(self.card);self.window.setFixedSize(360,500);self.window.show();APP.processEvents()
    def tearDown(self):self.window.close();self.window.deleteLater();APP.processEvents()
    def test_hidden_clock_callback_has_initialized_endpoints(self):
        from unittest.mock import patch
        errors=[]
        with patch('sys.excepthook',side_effect=lambda *args:errors.append(args)):
            self.card.animation.setCurrentTime(40)
        self.assertFalse(errors);self.assertEqual(self.card.progress,0.)
    def test_reversal_preserves_current_height_and_snapshot_then_releases_it(self):
        c=self.card;c.set_expanded(True);c.animation.setCurrentTime(100);height=c.height();frame=c._frame.cacheKey()
        c.set_expanded(False);self.assertEqual(c.height(),height);self.assertEqual(c._frame.cacheKey(),frame)
        c.animation.setCurrentTime(30);height=c.height();c.set_expanded(True);self.assertEqual(c.height(),height)
        c.complete();self.assertTrue(c.body.isVisible());self.assertIsNone(c._frame);self.assertFalse(c._animating)
    def test_first_show_never_flashes_at_full_height_before_the_first_tick(self):
        c=self.card;c.set_expanded(True)
        self.assertTrue(c._animating);self.assertTrue(c.body.isHidden());self.assertEqual(c.height(),0)
        c.animation.setCurrentTime(16);self.assertGreater(c.height(),0);self.assertLess(c.height(),c.full_height/4)
    def test_open_and_close_rebound_without_resizing_the_native_window(self):
        c=self.card;native=QRect(self.window.geometry())
        for expanded in (True,False):
            c.set_expanded(expanded);c.animation.pause();heights=[]
            for i in range(40):
                c.animation.setCurrentTime(round(i*c.animation.duration()/40));APP.processEvents();heights.append(c.height())
                self.assertEqual(self.window.geometry(),native)
                self.assertTrue(c.rect().contains(c.visual_rect().toAlignedRect()))
                self.assertTrue(c.body.isHidden());self.assertGreaterEqual(c.height(),0)
            self.assertTrue(any(b>a for a,b in zip(heights,heights[1:])))
            if expanded:self.assertGreater(max(heights),c.full_height)
            c.animation.resume();c.complete()
        self.assertFalse(c.isVisible());self.assertIsNone(c._frame)
    def test_hiding_ancestor_settles_and_does_not_leave_an_animation_running(self):
        c=self.card;c.set_expanded(True);c.animation.setCurrentTime(80);self.window.hide()
        self.assertFalse(c._animating);self.assertIsNone(c._frame);self.assertTrue(c.expanded)
        self.window.show();APP.processEvents();self.assertTrue(c.body.isVisible())
    def test_confirmation_cancels_immediately_and_never_accepts_enter_during_reveal(self):
        c=InlineConfirmation(self.window);self.window.layout().addWidget(c);calls=[]
        c.request('确认删除示例？',lambda:calls.append(1));QTest.keyClick(c,Qt.Key.Key_Return);self.assertFalse(calls)
        c.complete();self.assertTrue(c.cancel_button.hasFocus());c.confirm();c.confirm()
        self.assertEqual(calls,[1]);self.assertIsNone(c.callback);self.assertFalse(c.confirm_button.isEnabled())
        c.complete();self.assertFalse(c.isVisible())


class IntegratedCardTests(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.InteractionTests();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def open_containing_disclosures(self,settings,button):
        # Paths now live inside the Codex "more" group. A hidden programmatic
        # click does not represent the user's visible route to that control.
        settings._category_motion.clear();parents=[];parent=button.parentWidget()
        while parent is not None and parent is not settings:
            if isinstance(parent,AnimatedDisclosure):parents.append(parent)
            parent=parent.parentWidget()
        for parent in reversed(parents):parent.set_expanded(True);parent.complete()
        APP.processEvents();self.assertTrue(button.isVisible())
    def test_advanced_and_paths_keep_drafts_and_outer_window_size(self):
        f=self.fixture;s=f.settings();b=f.pet.bubble;native=QRect(b.geometry())
        for tab,button,card in ((1,s.advanced_button,s.advanced_card),(2,s.path_toggle,s.paths_card)):
            s.tabs.setCurrentIndex(tab);APP.processEvents();self.open_containing_disclosures(s,button);button.click();self.assertTrue(card._animating)
            for ms in (30,100,180,300):
                card.animation.setCurrentTime(ms);APP.processEvents();self.assertEqual(b.geometry(),native)
            card.complete();self.assertTrue(card.body.isVisible())
        s.path_fields['home'].setText('保留路径草稿');s.path_toggle.click();s.paths_card.complete();s.path_toggle.click();s.paths_card.complete()
        self.assertEqual(s.path_fields['home'].text(),'保留路径草稿')
        s.tabs.setCurrentIndex(1);s.fields['move_speed'].setValue(123);s.advanced_button.click();s.advanced_card.complete();s.advanced_button.click();s.advanced_card.complete()
        self.assertEqual(s.fields['move_speed'].value(),123);self.assertTrue(s.draft.dirty)
    def test_scrollbar_never_changes_disclosure_width_mid_motion(self):
        s=self.fixture.settings()
        for tab,button,card in ((1,s.advanced_button,s.advanced_card),(2,s.path_toggle,s.paths_card)):
            s.tabs.setCurrentIndex(tab);APP.processEvents();self.open_containing_disclosures(s,button);button.click();card.animation.pause()
            APP.processEvents();initial=card.width()
            heights=[]
            for step in range(40):
                card.animation.setCurrentTime(round(step*card.animation.duration()/40));APP.processEvents()
                self.assertEqual(card.width(),initial);heights.append(card.full_height)
            self.assertEqual(len(set(heights)),1)
            card.animation.resume();card.complete()
    def test_update_notes_remain_visible_while_closing_and_respect_height_cap(self):
        s=self.fixture.settings();s.tabs.setCurrentIndex(s.tabs.count()-1)
        panel=s.update_panel;panel.controller.publish(notes='窗口过渡和内容交接。\n'*9)
        APP.processEvents();card=panel.disclosure;native=QRect(self.fixture.pet.bubble.geometry())
        panel.details_button.click();card.complete();APP.processEvents()
        self.assertEqual(card.body.height(),160)
        panel.details_button.click();card.animation.pause()
        card.animation.setCurrentTime(card.animation.duration()//2);APP.processEvents()
        image=card.grab().toImage()
        dark=sum(image.pixelColor(x,y).red()<150 for y in range(4,image.height()-4,2)
                 for x in range(20,image.width()-20,2))
        self.assertGreater(dark,20,'update text vanished while the disclosure was still large')
        self.assertEqual(self.fixture.pet.bubble.geometry(),native)
        card.animation.resume();card.complete();APP.processEvents()
        self.assertEqual(card.height(),0);self.assertFalse(card.isVisible());self.assertIsNone(card._frame)


if __name__=='__main__':unittest.main()
