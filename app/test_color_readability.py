"""Real text, control and graph contexts, including theme changes and custom inputs."""
import os,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QLabel
from PySide6.QtGui import QTextDocument
from theme_registry import values,contrast,PRESETS,activate,palette,chart_color,week_color,_resolved
from theme_runtime import set_theme_text,apply_theme
from settings_controls import SwitchRow
APP=QApplication.instance() or QApplication([])

SAMPLES=[('#ffffff','#222222','#ffffff'),('#ffffff','#222222','#eeeeee'),('#101820','#f0f0f0','#101820'),('#101820','#f0f0f0','#1a2c38'),('#fff8ea','#34312b','#ffdd22'),('#211222','#f0e4f4','#b187e0'),('#a54dca','#ffffff','#182530'),('#9d5c34','#ffffff','#60be31'),('#000000','#777777','#dedede')]

class ColorReadabilityTests(unittest.TestCase):
 def tearDown(self):apply_theme('bailong',{})
 def check_palette(self,p):
  for role in ('ink','muted','accentText','warningText','danger'):
   for bg in ('surface','panel','selected'):
    self.assertGreaterEqual(contrast(p[role],p[bg]),4.5,(role,bg,p[role],p[bg]))
  for fraction in (0,.07,.14):
   from theme_registry import mix
   for fg,bg in (('successBadge','successBg'),('dangerBadge','dangerBg')):
    self.assertGreaterEqual(contrast(p[fg],mix(p[bg],p['ink'],fraction)),4.5,(fg,bg,fraction))
  self.assertGreaterEqual(contrast(p['accentOn'],p['accentText']),4.5)
  self.assertGreaterEqual(contrast(p['accentOn'],p['primaryPressed']),4.5)
  for fg,bg in (('switchOffKnob','border'),('switchOnKnob','accentText')):
   self.assertGreaterEqual(contrast(p[fg],p[bg]),3)
  for value in p['chartSeries']:
   for bg in ('panel','surface'):self.assertGreaterEqual(contrast(value,p[bg]),3)
 def test_every_preset_in_real_text_and_badge_contexts(self):
  for key in ('bailong',*PRESETS):
   with self.subTest(theme=key):self.check_palette(values(key))
 def test_entire_week_balance_gradient_and_all_six_model_series(self):
  for key in ('bailong',*PRESETS):
   activate(key);p=palette()
   for n in range(101):self.assertGreaterEqual(contrast(week_color(n),p['panel']),3,(key,n))
   for i in range(6):self.assertGreaterEqual(contrast(chart_color(i),p['panel']),3,(key,i))
 def test_valid_custom_inputs_cannot_hide_charts_or_primary_buttons(self):
  for surface,ink,accent in SAMPLES:
   with self.subTest(surface=surface,accent=accent):
    self.check_palette(values('custom',dict(theme_surface=surface,theme_ink=ink,theme_accent=accent)))
 def test_rich_text_recolors_back_and_forth_without_losing_source(self):
  label=QLabel();source='<span style="color:#62576e">累计用量</span><br><span style="color:#514360">73 本《圣诞颂歌》</span>'
  set_theme_text(label,source)
  for key in ('cyber','amber','division','night','bailong','jade','cyber'):
   apply_theme(key,{},roots=(label,));p=palette();doc=QTextDocument();doc.setHtml(label.text())
   block=doc.begin()
   while block.isValid():
    it=block.begin()
    while not it.atEnd():
     fragment=it.fragment()
     if fragment.isValid() and fragment.text().strip():self.assertGreaterEqual(contrast(fragment.charFormat().foreground().color().name(),p['panel']),4.5,key)
     it+=1
    block=block.next()
   self.assertIn('73 本《圣诞颂歌》',doc.toPlainText());self.assertEqual(label._theme_text_source,source)
  label.deleteLater()
 def test_cached_report_book_text_and_new_books_follow_live_theme(self):
  from compact_bubble import CompactBubble
  from daily_report import DailyReport
  from test_daily_report import sample
  b=CompactBubble();r=DailyReport(b);b.report=r;r.set_snapshot(sample());r.open();r.animation.setCurrentTime(r.animation.duration());APP.processEvents()
  r.set_page('models');r.page_fade.clear()
  for key in ('cyber','bailong','division'):
   apply_theme(key,{},roots=(b,r));r.set_page('overview');r.page_fade.clear();APP.processEvents()
   self.assertIn(palette()['muted'],r.analogy.text());self.assertIn(palette()['ink'],r.analogy.text())
   r.next_book();self.assertIn(palette()['ink'],r.analogy.text())
   r.set_page('models');r.page_fade.clear()
  r.close();b.close();r.deleteLater();b.deleteLater();APP.processEvents()
 def test_switch_endpoints_render_a_distinct_thumb_in_every_theme(self):
  for key in ('bailong',*PRESETS):
   apply_theme(key,{})
   w=SwitchRow('启用');w.resize(240,42);w.show();APP.processEvents()
   for checked in (False,True):
    w.setChecked(checked);w.animation.stop();w.position=float(checked)
    image=w.grab().toImage();cx=204+(16 if checked else 0);track=199 if checked else 225
    self.assertGreaterEqual(contrast(image.pixelColor(cx,21).name(),image.pixelColor(track,21).name()),3,(key,checked))
   w.close();w.deleteLater();APP.processEvents()
 def test_palette_contrast_work_is_reused_on_normal_reads(self):
  values('cyber');before=_resolved.cache_info()
  for _ in range(100):values('cyber')
  after=_resolved.cache_info();self.assertEqual(after.misses,before.misses);self.assertEqual(after.hits-before.hits,100)

if __name__=='__main__':unittest.main()
