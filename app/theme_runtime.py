"""Apply theme changes once; preserve live pages, progress and current drafts."""
from PySide6.QtGui import QColor,QPalette
from PySide6.QtCore import QEvent,QObject,Qt
from PySide6.QtWidgets import QApplication,QWidget
from theme_registry import color,stylesheet,palette,activate

def set_theme_style(widget,text):
    widget._theme_style_source=text
    widget.setStyleSheet(stylesheet(text))
def theme_style_source(widget):return getattr(widget,'_theme_style_source',widget.styleSheet())

def set_theme_text(widget,text):
    """Keep the untranslated rich text so both cached and live pages recolor."""
    widget._theme_text_source=text
    translated=stylesheet(text)
    if widget.text()!=translated:widget.setText(translated)

class _ThemeOnShow(QObject):
    def eventFilter(self,widget,event):
        if event.type()==QEvent.Type.Show:prepare_theme_widget(widget)
        return False


_on_show=None

def prepare_theme_widget(widget):
    pending=getattr(widget,'_theme_pending',None)
    if pending is not None:
        widget._theme_pending=None
        widget.removeEventFilter(_on_show)
        _apply_widget(widget,pending)

def _apply_widget(widget,q):
    if widget.testAttribute(Qt.WidgetAttribute.WA_SetPalette) and widget.palette()!=q:widget.setPalette(q)
    source=getattr(widget,'_theme_style_source',None)
    if source is not None:
        translated=stylesheet(source)
        if widget.styleSheet()!=translated:widget.setStyleSheet(translated)
    rich=getattr(widget,'_theme_text_source',None)
    if rich is not None:set_theme_text(widget,rich)
    if hasattr(widget,'invalidate_layers'):widget.invalidate_layers()
    if hasattr(widget,'_static_key'):widget._static_key=None
    if hasattr(widget,'_prepare_dial'):widget._prepare_dial()
    if hasattr(widget,'refresh_theme_colors'):widget.refresh_theme_colors()
    if hasattr(widget,'_static') and hasattr(widget,'_revision'):widget._revision+=1
    kind=widget.property('themeIconKind')
    if kind:
        from compact_bubble import action_icon
        widget.setIcon(action_icon(kind,island=bool(widget.property('themeIconIsland'))))
    if widget.isVisible():QWidget.update(widget)

def apply_theme(key,custom,roots=None,*,defer_hidden=False):
    global _on_show
    if not activate(key,custom):return False
    p=palette();app=QApplication.instance();q=QPalette(app.palette())
    for role,key in ((QPalette.ColorRole.Window,'surface'),(QPalette.ColorRole.Base,'surface'),(QPalette.ColorRole.AlternateBase,'panel'),(QPalette.ColorRole.WindowText,'ink'),(QPalette.ColorRole.Text,'ink'),(QPalette.ColorRole.Button,'panel'),(QPalette.ColorRole.ButtonText,'ink'),(QPalette.ColorRole.Highlight,'selected'),(QPalette.ColorRole.HighlightedText,'ink'),(QPalette.ColorRole.ToolTipBase,'surface'),(QPalette.ColorRole.ToolTipText,'ink')):q.setColor(role,QColor(p[key]))
    q.setColor(QPalette.ColorRole.PlaceholderText,QColor(p['muted']))
    if roots is None:app.setPalette(q)
    else:
        for window in {root.window() for root in roots if root is not None}:window.setPalette(q)
    # These QColor instances are imported by reference by the paint modules.
    import compact_bubble as bubble
    for name,raw in dict(INK='#393343',MUTED='#706879',PURPLE='#8b78a6',GREEN='#b3a5cb',AMBER='#915e74',TRACK='#e4dfea').items():getattr(bubble,name).setRgb(*QColor(color(raw)).getRgb())
    if roots is None:widgets=app.allWidgets()
    else:
        widgets=set()
        for root in roots:
            if root is not None:widgets.update([root,*root.findChildren(QWidget)])
        # Parent QSS first. Descendant styles then override semantic roles.
        def depth(widget):
            n=0
            while widget.parentWidget():n+=1;widget=widget.parentWidget()
            return n
        widgets=sorted(widgets,key=depth)
    for widget in widgets:
        pending=getattr(widget,'_theme_pending',None)
        if defer_hidden and not widget.isVisible():
            if _on_show is None:_on_show=_ThemeOnShow(app)
            if pending is None:widget.installEventFilter(_on_show)
            widget._theme_pending=q
        else:
            if pending is not None:
                widget._theme_pending=None
                widget.removeEventFilter(_on_show)
            _apply_widget(widget,q)
    return True
