"""Embedded update card; no extra window and no automatic downloads."""
from theme_runtime import set_theme_style,theme_style_source
import re
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QProgressBar,QPlainTextEdit
from card_motion import AnimatedDisclosure
from ui_theme import MUTED,PRIMARY,hide_scrollbars

def size_text(value):
    if value>=1024**3:return f'{value/1024**3:.2f} GB'
    if value>=1024**2:return f'{value/1024**2:.1f} MB'
    return f'{value/1024:.0f} KB'

class UpdatePanel(QWidget):
    def __init__(self,controller,parent=None):
        super().__init__(parent);self.controller=controller;self.setObjectName('app_update_panel')
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        self.version=QLabel();self.version.setWordWrap(True);set_theme_style(self.version,f'font-size:12px;font-weight:500;color:{PRIMARY};');layout.addWidget(self.version)
        self.status=QLabel();self.status.setWordWrap(True);set_theme_style(self.status,'font-size:11px;font-weight:500;color:#393343;');layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,1000);self.progress.setTextVisible(False);self.progress.setFixedHeight(7)
        set_theme_style(self.progress,'QProgressBar{border:0;border-radius:3px;background:#e8e0ef;}QProgressBar::chunk{border-radius:3px;background:#9a81b6;}');layout.addWidget(self.progress)
        self.amount=QLabel();set_theme_style(self.amount,f'font-size:11px;font-weight:500;color:{MUTED};');layout.addWidget(self.amount)
        self.package=QLabel();self.package.setWordWrap(True);set_theme_style(self.package,f'font-size:11px;font-weight:500;color:{MUTED};');layout.addWidget(self.package)
        row=QHBoxLayout();self.check=QPushButton('检查更新');self.check.setObjectName('check_app_update');self.check.clicked.connect(controller.check);row.addWidget(self.check)
        self.install=QPushButton('下载并安装');self.install.setObjectName('install_app_update');self.install.setProperty('role','primary');self.install.clicked.connect(controller.download_install);row.addWidget(self.install)
        self.cancel=QPushButton('暂停下载');self.cancel.clicked.connect(controller.cancel);row.addWidget(self.cancel);layout.addLayout(row)
        self.details_button=QPushButton('查看更新内容');self.details_button.setCheckable(True);layout.addWidget(self.details_button)
        self.details=hide_scrollbars(QPlainTextEdit());self.details.setReadOnly(True);self.details.setMaximumHeight(160);self.details.setAccessibleName('版本更新内容')
        self.disclosure=AnimatedDisclosure(self.details);layout.addWidget(self.disclosure);self.details_button.toggled.connect(self.disclosure.set_expanded)
        self.github=QPushButton('在 GitHub 查看此版本');self.github.clicked.connect(self.open_release);layout.addWidget(self.github)
        note=QLabel('只有点击“下载并安装”才会下载。安装器会保留设置、聊天和回退版本；更新完成后清理下载缓存。')
        note.setWordWrap(True);set_theme_style(note,f'font-size:11px;color:{MUTED};');layout.addWidget(note)
        controller.changed.connect(self.set_state);self.set_state(controller.snapshot())
    def set_state(self,state):
        self.state=state;phase=state['phase'];busy=self.controller.job is not None
        self.version.setText('当前 '+state['current']+('    公开版 '+state['latest'] if state.get('latest') else ''))
        self.status.setText(state['message']);self.check.setEnabled(not busy and phase not in ('installing','pending'));self.check.setText('检查中…' if phase=='checking' else '检查更新')
        from app_updates import version_tuple
        newer=bool(state.get('latest')) and version_tuple(state['latest'])>version_tuple(state['current'])
        self.install.setVisible(newer and not busy and phase not in ('installing','pending'));self.install.setEnabled(not busy);self.install.setText('继续下载并安装' if phase=='cancelled' else '下载并安装')
        downloading=phase in ('materials','downloading','verifying','extracting','ready');self.cancel.setVisible(busy and downloading);self.cancel.setEnabled(not self.controller.job.cancel.is_set() if busy else True)
        self.progress.setVisible(downloading or phase=='cancelled');self.amount.setVisible(downloading or phase=='cancelled' or newer)
        total=state.get('total',0);n=state.get('downloaded',0);self.progress.setValue(round(1000*n/max(1,total)))
        self.amount.setText((size_text(n)+' / ' if downloading or phase=='cancelled' else '安装包约 ')+size_text(total) if total else '')
        self.package.setVisible(newer)
        kind=state.get('package_kind')
        self.package.setText((('动画补丁包 ' if kind=='animation' else '程序补丁包 ')+state.get('latest','')) if kind in ('program','animation') else ('完整安装包：'+state['package_reason'] if state.get('package_reason') else '完整安装包'))
        if kind=='program' and state.get('package_animation'):self.package.setText(self.package.text()+'\n动画补丁包 '+state.get('latest',''))
        notes=re.sub(r'^\s*#{1,6}\s*','',state.get('notes',''),flags=re.M)
        if notes!=self.details.toPlainText():
            self.details.setPlainText(notes)
            if self.disclosure.expanded or self.disclosure._animating:self.disclosure.refresh_content()
        if not notes:self.details_button.setChecked(False)
        self.details_button.setVisible(bool(notes));self.github.setVisible(bool(state.get('url')))
    def open_release(self):
        if self.state.get('url'):QDesktopServices.openUrl(QUrl(self.state['url']))
