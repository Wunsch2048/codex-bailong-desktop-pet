import unittest
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QFontMetricsF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QLabel,QToolButton
from compact_bubble import CompactBubble,Announcement
from dashboard_cards import CardDeck
from test_reset_presentation import NOW,snapshot

app=QApplication.instance() or QApplication([])

class ResetCardTests(unittest.TestCase):
    def tearDown(self):
        for w in app.topLevelWidgets():w.close();w.deleteLater()
        app.processEvents()
    def test_countdown_changes_in_place_and_hides_without_background_timer(self):
        clock=[NOW];card=Announcement(snapshot(3610),False,dense=True,with_refresh=False,clock=lambda:clock[0]);card.resize(106,78);card.show();app.processEvents()
        bounds=card.geometry();self.assertTrue(card.timer.isActive());self.assertEqual(card.view['parts'],[('1','小时'),('01','分钟')])
        clock[0]+=80;card.refresh_time();self.assertEqual(card.view['unit'],'分钟');self.assertEqual(card.geometry(),bounds)
        card.hide();self.assertFalse(card.timer.isActive());clock[0]+=4000;card.show();app.processEvents()
        self.assertEqual(card.view['phase'],'pending');self.assertFalse(card.timer.isActive());self.assertEqual(card.geometry(),bounds)
    def test_all_number_and_unit_glyphs_fit_the_actual_small_deck(self):
        bubble=CompactBubble();bubble.reset_snapshot=snapshot(12.5*3600);bubble.redraw();app.processEvents()
        width=next(w for w in bubble.findChildren(Announcement) if w.isVisible()).width()
        self.assertGreater(width,80)
        for seconds in [12.5*3600,99.9*3600,100.5*3600,9999*3600+59*60,12000*3600,3599,59,-1]:
            card=Announcement(snapshot(seconds),False,dense=True,with_refresh=False,clock=lambda:NOW);card.resize(width,78)
            for text,font,origin in card.text_runs():
                if not text:continue
                rect=QFontMetricsF(font).tightBoundingRect(text).translated(origin)
                self.assertTrue(QRectF(card.rect()).contains(rect),(text,rect,width))
            card.deleteLater()
    def test_countdown_click_opens_reset_details_with_source_and_full_copy(self):
        import time
        bubble=CompactBubble();data=snapshot(7200);data['pending']['scheduled']=time.time()+7200
        bubble.reset_snapshot=data;bubble.redraw();app.processEvents()
        card=next(w for w in bubble.findChildren(Announcement) if w.isVisible())
        QTest.mouseClick(card,Qt.MouseButton.LeftButton,pos=card.rect().center());bubble.size_transition.complete();app.processEvents()
        self.assertEqual(bubble.detail_tab,'reset');self.assertEqual(bubble.details_tabs.currentIndex(),2)
        labels=[w.text() for w in bubble.findChildren(QLabel) if w.isVisible()]
        self.assertIn(data['pending']['text'],labels);self.assertTrue(any('Codex Resets' in text for text in labels))
        # The redesigned details keep the full notice and its source together.
        source=next(w for w in bubble.details_tabs.areas['reset'].findChildren(QToolButton) if w.isVisible() and w.toolTip()=='公告来源')
        from unittest.mock import patch
        from reset_watch import SOURCE_URL
        with patch('detail_sections.QDesktopServices.openUrl',return_value=True) as opened:
            QTest.mouseClick(source,Qt.MouseButton.LeftButton)
            self.assertEqual(opened.call_count,1)
            self.assertEqual(opened.call_args.args[0].toString(),SOURCE_URL)
        self.assertEqual(bubble.details_tabs.currentIndex(),2)
    def test_keyboard_opens_card_and_switch_to_tokens_stops_countdown(self):
        import time
        data=snapshot(7200);data['pending']['scheduled']=time.time()+7200
        deck=CardDeck('reset',None,data,False,False);deck.resize(115,102);deck.show();app.processEvents()
        card=deck.content;seen=[];deck.reset_details_requested.connect(lambda:seen.append(True))
        QTest.keyClick(card,Qt.Key.Key_Return);self.assertEqual(seen,[True]);self.assertTrue(card.timer.isActive())
        deck.set_page('tokens');app.processEvents();self.assertFalse(card.timer.isActive())
    def test_source_button_opens_notice_only_and_keeps_countdown_card_size(self):
        from unittest.mock import patch
        from reset_watch import SOURCE_URL
        card=Announcement(snapshot(45000),False,dense=True,with_refresh=False,clock=lambda:NOW)
        card.resize(106,78);card.show();app.processEvents();expanded=[];card.expand.connect(lambda:expanded.append(True))
        size=card.size();button=card.source_button
        self.assertTrue(card.rect().contains(button.geometry()))
        note,rect=card.note_layout()
        self.assertEqual(button.geometry().bottom(),card.height()-3)
        self.assertLess(rect.right(),button.x())
        self.assertNotIn('最晚',note)
        self.assertLessEqual(QFontMetricsF(__import__('typography').ui_font(10,True)).horizontalAdvance(note),rect.width())
        with patch('reset_card.QDesktopServices.openUrl',return_value=True) as opened:
            QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            self.assertEqual(opened.call_count,1);self.assertEqual(opened.call_args.args[0].toString(),SOURCE_URL)
        self.assertFalse(expanded);self.assertEqual(card.size(),size)
        self.assertEqual(card.view['parts'],[('12','小时'),('30','分钟')])

if __name__=='__main__':unittest.main()
