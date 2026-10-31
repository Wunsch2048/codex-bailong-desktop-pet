"""Inline connection cards; no native tooltip windows or account content."""
from theme_runtime import set_theme_style,theme_style_source
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QGridLayout,QVBoxLayout,QHBoxLayout,QLabel
from connection_health import CAPABILITIES,LABELS,REASONS,success_time
from ui_theme import SURFACE,BORDER,HEALTH_COLORS,MUTED

class CapabilityPanel(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);grid=QGridLayout(self);grid.setContentsMargins(0,0,0,0);grid.setSpacing(6);self.labels={}
        for i,(key,title) in enumerate(CAPABILITIES.items()):
            card=QWidget();card.setObjectName('health_'+key);card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            set_theme_style(card,f'QWidget#health_{key}{{background:{SURFACE};border:1px solid {BORDER};border-radius:7px;}}')
            layout=QVBoxLayout(card);layout.setContentsMargins(8,6,8,6);layout.setSpacing(3)
            row=QHBoxLayout();name=QLabel(title);set_theme_style(name,'font-size:12px;font-weight:500;');row.addWidget(name)
            state=QLabel();state.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter);row.addWidget(state);layout.addLayout(row)
            stamp=QLabel();set_theme_style(stamp,f'font-size:11px;color:{MUTED};');layout.addWidget(stamp)
            detail=QLabel();detail.setWordWrap(True);set_theme_style(detail,'font-size:11px;');layout.addWidget(detail)
            self.labels[key]=(state,stamp,detail);grid.addWidget(card,i//2,i%2)
        self.set_snapshot({})
    def set_snapshot(self,snapshot):
        for key,(state,stamp,detail) in self.labels.items():
            value=snapshot.get('capabilities',{}).get(key,{});status=value.get('state','unknown')
            state.setText(LABELS.get(status,'待检测'));set_theme_style(state,f'font-size:11px;font-weight:500;color:{HEALTH_COLORS.get(status,MUTED)};')
            stamp.setText('最近成功 · '+success_time(value.get('last_success')))
            detail.setText(REASONS.get(value.get('code','starting'),REASONS['unavailable']))
