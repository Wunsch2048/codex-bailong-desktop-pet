"""Theme persistence, live-page repaint and small-control contracts."""
import os,time,unittest
from datetime import datetime
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QLabel,QToolButton
from PySide6.QtCore import QEvent,Qt
from theme_registry import PRESETS,BASE,values,palette,current,contrast,week_color,revision
from theme_runtime import apply_theme,set_theme_style,theme_style_source
from theme_controls import ThemeChoices,ORDER
from desktop_core import DEFAULTS,normalized
from compact_bubble import CompactBubble
from token_charts import TokenPlot
APP=QApplication.instance() or QApplication([])

class ThemeTests(unittest.TestCase):
    def setUp(self):apply_theme('bailong',{})
    def tearDown(self):apply_theme('bailong',{});APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_upgrade_and_invalid_saved_theme_keep_original(self):
        self.assertEqual(DEFAULTS['theme'],'bailong')
        for value in (None,[],{},'missing'):
            self.assertEqual(normalized(dict(theme=value))['theme'],'bailong')
        bad=normalized(dict(theme='custom',theme_surface='#ffffff',theme_ink='#eeeeee'))
        self.assertEqual(bad['theme'],'bailong')
    def test_all_presets_are_readable_and_starfield_uses_user_colors(self):
        self.assertEqual(len(PRESETS),7)
        for key in PRESETS:
            p=values(key)
            self.assertGreaterEqual(contrast(p['ink'],p['surface']),4.5,key)
            self.assertGreaterEqual(contrast(p['muted'],p['panel']),4.5,key)
            apply_theme(key,{})
            from theme_registry import color
            self.assertEqual(color('#506e66'),p['success'])
            self.assertGreaterEqual(contrast(color('#506e66'),p['surface']),4.5,key)
        self.assertEqual({values('starfield')[r] for r in ('signalBlue','signalGold','signalOrange','signalRed')},{'#2f4c79','#e06236','#d7ab61','#c82337'})
        self.assertEqual(PRESETS['amber']['name'],'赛博');self.assertEqual(PRESETS['amber']['mode'],'dark')
    def test_custom_validation_preserves_readability(self):
        with self.assertRaises(ValueError):values('custom',dict(theme_accent='red'))
        with self.assertRaises(ValueError):values('custom',dict(theme_surface='#ffffff',theme_ink='#ffffff'))
        p=values('custom',dict(theme_surface='#101820',theme_ink='#f0f0f0',theme_accent='#e08030'))
        self.assertGreaterEqual(contrast(p['accentText'],p['surface']),4.5)
        saved=normalized(dict(theme='custom',theme_surface='#101820',theme_ink='#f0f0f0',theme_accent='#e08030'))
        self.assertEqual(saved['theme'],'custom')
    def test_swatches_have_only_hover_and_accessible_names(self):
        choices=ThemeChoices();changes=[];choices.currentIndexChanged.connect(changes.append)
        self.assertFalse(choices.findChildren(QLabel))
        for i,button in enumerate(choices.buttons):
            self.assertEqual(button.toolTip(),'');self.assertTrue(button.property('headerActionHint'))
            button.click();self.assertEqual(choices.currentData(),ORDER[i]);self.assertEqual(sum(b.isChecked() for b in choices.buttons),1)
        choices.deleteLater()
    def test_week_colors_follow_real_balance_for_each_theme(self):
        for key in PRESETS:
            apply_theme(key,{})
            self.assertNotEqual(week_color(5),week_color(80),key)
            self.assertEqual(week_color(35),palette()['warning'])
            self.assertEqual(week_color(5),palette()['danger'])
    def test_style_roundtrip_does_not_accumulate_translated_colors(self):
        from PySide6.QtGui import QPalette,QColor
        label=QLabel('Codex');raw='color:#393343;background:#fcfafc;';set_theme_style(label,raw)
        own=QPalette();own.setColor(QPalette.ColorRole.PlaceholderText,QColor('#786d84'));label.setPalette(own)
        for key in (*PRESETS,'bailong'):
            apply_theme(key,{})
            self.assertEqual(theme_style_source(label),raw)
            self.assertIn(palette()['ink'] if key!='bailong' else BASE['ink'],label.styleSheet())
            self.assertEqual(label.palette().color(QPalette.ColorRole.PlaceholderText).name(),palette()['muted'])
        from theme_registry import stylesheet
        self.assertEqual(label.styleSheet(),stylesheet(raw));label.deleteLater()
    def test_theme_change_invalidates_rasters_without_resetting_reveal(self):
        # At midnight one hourly point has no area; a transparent layer cannot
        # demonstrate a theme recolor. Fix the fixture clock, not the real chart.
        now=datetime(2026,10,18,13,40).timestamp()
        plot=TokenPlot(dict(today='2026-10-18',hours=[100]*24),'day',now=now);plot.resize(200,100)
        plot.ensure_layers();old=plot._layers[1].toImage();plot.reveal.progress=.63;builds=plot.layer_builds
        apply_theme('cyber',{});self.assertIsNone(plot._layer_key);self.assertEqual(plot.reveal.progress,.63)
        plot.ensure_layers();self.assertEqual(plot.layer_builds,builds+1);self.assertNotEqual(plot._layers[1].toImage(),old)
        r=revision();self.assertFalse(apply_theme('cyber',{}));self.assertEqual(revision(),r);plot.deleteLater()
    def test_capsule_circle_sizes_and_number_font(self):
        from island_widgets import QuotaSatellite,MinimalQuota
        b=CompactBubble();b.windows=[dict(name='一周',remaining=73)];b.set_mode('mini');b.size_transition.complete()
        self.assertEqual((b.width(),b.height()),(210,38))
        self.assertEqual(b.findChild(QToolButton,'island_shortcut').size(),b.findChild(QuotaSatellite).size())
        for cls in (QuotaSatellite,MinimalQuota):
            q=cls(b.windows,'');self.assertEqual(q._text_runs[0][0].stretch(),100);q.deleteLater()
        b.close();b.deleteLater()

if __name__=='__main__':unittest.main()
