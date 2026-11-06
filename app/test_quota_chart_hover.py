"""Keep one opaque quota inspection surface across scans and data refreshes."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtCore import QPointF,Qt,QEvent
from PySide6.QtWidgets import QApplication
from quota_compare_ui import CyclePlot

APP=QApplication.instance() or QApplication([])

def cycles():
    return [dict(id=str(i),start=1792300000+i*604800,end=None,used=100+i*10,estimated_total=300,remaining=70,fresh=True) for i in range(3)]

class QuotaHoverTests(unittest.TestCase):
    def setUp(self):
        self.plot=CyclePlot();self.plot.resize(246,94);self.data=cycles();self.plot.set_data(self.data,'2');self.plot.show();APP.processEvents()
        self.plot.reveal.animation.stop();self.plot.reveal.progress=1.;self.plot.grab()
    def tearDown(self):
        self.plot.hide();self.plot.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()
    def inspect(self,index=1):
        self.plot.inspect_at(self.plot.hits[index][0].center());self.plot.show_inspection()
        self.assertTrue(self.plot._popup.isVisible())
    def test_first_show_is_opaque_and_rows_are_available(self):
        self.inspect();popup=self.plot._popup
        self.assertEqual(popup.level,1.);self.assertEqual(popup.record['rows'][0][0],'已用 Token')
        image=popup.grab().toImage();self.assertEqual(image.pixelColor(image.width()//2,image.height()//2).alpha(),255)
    def test_painted_gutters_are_part_of_continuous_hit_cells(self):
        self.inspect(0);p=self.plot;chart=p.chart_rect();slot=chart.width()/len(p.cycles)
        with patch.object(p._popup,'hide',wraps=p._popup.hide) as hide:
            for offset in (-1.,-.1,.1,1.):
                p.inspect_at(QPointF(chart.left()+slot+offset,chart.center().y()));self.assertGreaterEqual(p._inspection,0);self.assertTrue(p._popup.isVisible())
            hide.assert_not_called()
    def test_refresh_changes_rows_without_hiding_or_representing_same_surface(self):
        self.inspect();p=self.plot;ident=p.cycles[p._inspection]['id']
        updated=[dict(c,fresh=False,used=c['used']+10) for c in self.data]
        with patch.object(p._popup,'hide',wraps=p._popup.hide) as hide,patch.object(p._popup,'present',wraps=p._popup.present) as present:
            p.set_data(updated,'2');self.assertTrue(p._popup.isVisible());self.assertEqual(p.cycles[p._inspection]['id'],ident)
            self.assertIn('120',p._popup.record['rows'][0][1]);hide.assert_not_called();present.assert_not_called()
    def test_removed_history_and_real_hide_dismiss_inspection(self):
        self.inspect();self.plot.set_data([],None);self.assertFalse(self.plot._popup.isVisible());self.assertEqual(self.plot._inspection,-1)
        self.plot.set_data(self.data,'2');self.plot.grab();self.inspect();self.plot.hide();self.assertFalse(self.plot._popup.isVisible());self.assertFalse(self.plot._inspect_delay.isActive())

