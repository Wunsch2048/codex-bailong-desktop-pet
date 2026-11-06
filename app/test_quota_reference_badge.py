"""Reference badges are descriptive, current-window-bound and theme readable."""
import os,time,copy,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from quota_history import visible_quota_change,visible_anomaly
from quota_summary import QuotaSummary
from theme_registry import values,NAMES,contrast,mix,activate,current,palette

APP=QApplication.instance() or QApplication([])

class ReferenceBadgeTests(unittest.TestCase):
    def setUp(self):
        self.now=time.time();self.deadline=self.now+86400
        self.windows=[dict(name='一周',remaining=60,resetsAt=self.deadline,plan='pro')]
        base=dict(closed=True,complete=True,fresh=True,drop=30,estimated_total=1000,plan='pro',eligible=False)
        self.snapshot=dict(quota_history=dict(cycles=[dict(base,closed=False,estimated_total=856,through=self.now,reset_at=self.deadline,remaining=60),base]))
    def test_mixed_usage_reference_is_yellow_payload_not_a_quota_alert(self):
        badge=visible_quota_change(self.snapshot,self.windows,self.now)
        self.assertEqual((badge['kind'],badge['change']),('reference',-14.4))
        self.assertIn('参考差异',badge['description']);self.assertIsNone(visible_anomaly(self.snapshot,self.windows,self.now))
        self.assertEqual(self.snapshot['quota_history']['cycles'][0]['estimated_total'],856)
    def test_existing_qualified_red_green_alert_wins_without_double_badges(self):
        alert=dict(change=18,description='同条件推测容量增加')
        with patch('quota_history.visible_anomaly',return_value=alert):
            self.assertIs(visible_quota_change(self.snapshot,self.windows,self.now),alert)
    def test_partial_stale_new_cycle_plan_change_and_missing_data_hide_reference(self):
        mutations=[lambda s:s.update(partial=True),lambda s:s.update(refresh_failed=True),
          lambda s:s['quota_history'].update(pending=True),lambda s:s['quota_history'].update(partial=True),
          lambda s:s['quota_history']['cycles'].pop(),lambda s:s['quota_history']['cycles'][0].update(through=self.now-901),
          lambda s:s['quota_history']['cycles'][0].update(closed=True),
          lambda s:s['quota_history']['cycles'][0].update(plan='plus'),
          lambda s:s['quota_history']['cycles'][0].update(drop=4),
          lambda s:s['quota_history']['cycles'][0].update(reset_at=self.deadline+3600)]
        for mutate in mutations:
            snapshot=copy.deepcopy(self.snapshot);mutate(snapshot)
            self.assertIsNone(visible_quota_change(snapshot,self.windows,self.now))
        self.assertIsNone(visible_quota_change(self.snapshot,[dict(self.windows[0],remaining=90)],self.now))
        self.assertIsNone(visible_quota_change(self.snapshot,[],self.now))
    def test_five_to_twenty_points_is_explicitly_preliminary_in_hover(self):
        self.snapshot['quota_history']['cycles'][0]['drop']=5
        badge=visible_quota_change(self.snapshot,self.windows,self.now)
        self.assertTrue(badge['preliminary']);self.assertIn('初步参考差异',badge['description'])
    def test_all_themes_and_custom_surfaces_keep_text_contrast_on_all_button_states(self):
        cases=[(key,None) for key in NAMES if key!='custom']
        cases += [('custom',dict(theme_surface='#fafafa',theme_ink='#222222',theme_accent='#305080')),
                  ('custom',dict(theme_surface='#141414',theme_ink='#eeeeee',theme_accent='#b470d0'))]
        for key,custom in cases:
            p=values(key,custom)
            for f in (0,.07,.14):
                self.assertGreaterEqual(contrast(p['referenceBadge'],mix(p['referenceBg'],p['ink'],f)),4.5,(key,f))
            self.assertNotEqual(p['referenceBg'],p['successBg']);self.assertNotEqual(p['referenceBg'],p['dangerBg'])
    def test_badge_no_approximation_same_size_click_route_and_theme_refresh(self):
        original=current();custom=dict(theme_accent=palette()['accent'],theme_surface=palette()['surface'],theme_ink=palette()['ink'])
        try:
            for expanded in (False,True):
                for five_hour in (False,True):
                    windows=([dict(name='5小时',remaining=30)]+self.windows) if five_hour else self.windows
                    badge=visible_quota_change(self.snapshot,self.windows,self.now)
                    card=QuotaSummary(windows,anomaly=badge,expanded=expanded);card.setFixedWidth(160 if expanded else 121);card.show();APP.processEvents()
                    try:
                        self.assertEqual(card.height(),105 if expanded else 102)
                        self.assertEqual(card.alert_badge.text(),'-14%');self.assertNotIn('≈',card.alert_badge.text())
                        self.assertIn('参考差异',card.alert_badge.toolTip())
                        self.assertTrue(card.rect().contains(card.alert_badge.geometry()))
                        called=[];card.anomalyRequested.connect(lambda:called.append(True))
                        QTest.mouseClick(card.alert_badge,Qt.MouseButton.LeftButton);self.assertEqual(called,[True])
                        for key in NAMES:
                            if key=='custom':continue
                            activate(key);card.refresh_theme_colors()
                            self.assertIn(palette()['referenceBg'],card.alert_badge.styleSheet())
                    finally:card.close();card.deleteLater();APP.processEvents()
        finally:activate(original,custom)
    def test_rounded_zero_is_not_negative_or_positive_zero(self):
        self.snapshot['quota_history']['cycles'][0]['estimated_total']=999
        card=QuotaSummary(self.windows,anomaly=visible_quota_change(self.snapshot,self.windows,self.now))
        self.assertEqual(card.alert_badge.text(),'0%');card.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
