"""Non-modal settings, live controls and character diagnostics."""
from theme_runtime import set_theme_style,theme_style_source
import copy
import threading
from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtGui import QShortcut,QKeySequence
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,QWidget,
    QCheckBox,QDoubleSpinBox,QPlainTextEdit,QPushButton,QComboBox,QLabel,QFileDialog,QMessageBox,QScrollArea,QLineEdit)
from desktop_core import DEFAULTS,VERSION
from desktop_services import autostart_enabled,set_autostart,import_character,validate_character,all_items
from settings_draft import SettingsDraft
from connection_widgets import CapabilityPanel
from ui_theme import MUTED,PRIMARY,BORDER,PANEL,SURFACE,SELECTED,INK,ACCENT,editor_stylesheet,hide_scrollbars
from typography import FONT_CSS
from settings_controls import SwitchRow,SlidingSegments
from choice_controls import ChoiceCombo as QComboBox
from number_controls import DecimalField as QDoubleSpinBox
from card_motion import AnimatedDisclosure
from theme_controls import ThemeChoices

class ConnectionJob(QThread):
    report=Signal(object)
    def __init__(self,parent=None):super().__init__(parent);self.cancel=threading.Event()
    def run(self):
        from codex_connection import check_connection
        try:self.report.emit(check_connection(cancel=self.cancel))
        except Exception:self.report.emit(dict(summary='连接检查暂不可用，请稍后重试。'))

class LibraryJob(QThread):
    result=Signal(object);failed=Signal(str)
    def __init__(self,source,destination=None,parent=None):super().__init__(parent);self.source=source;self.destination=destination
    def run(self):
        try:
            if self.destination:self.result.emit(import_character(self.source,self.destination))
            else:self.result.emit(validate_character(self.source))
        except Exception as error:self.failed.emit(str(error)[:250])

class ConverterJob(LibraryJob):
    def run(self):
        from optional_tools import save_ffmpeg
        try:save_ffmpeg(self.source);self.result.emit(str(self.source))
        except (OSError,ValueError) as error:self.failed.emit(str(error))

class PathsJob(QThread):
    result=Signal(object);failed=Signal(str)
    def __init__(self,values,parent=None):super().__init__(parent);self.values=values
    def run(self):
        from codex_connection import validate_paths
        try:
            if self.values.get('operation')=='list_wsl':
                from wsl_codex import distributions
                self.result.emit(distributions())
            else:self.result.emit(validate_paths(self.values))
        except (OSError,ValueError,RuntimeError) as error:self.failed.emit(str(error))

class SettingsDialog(QDialog):
    def __init__(self,pet,embedded=False,lazy=False):
        super().__init__(pet,Qt.WindowType.Widget if embedded else Qt.WindowType.Dialog);self.pet=pet;self.embedded=embedded;self.fields={};self.job=None;self.connection_job=None
        self.field_tabs={};self.field_titles={};self.factors={};self._writing_widgets=True;self.draft=None;self.path_job=None;self._saving=False
        if embedded:self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle('白龙桌宠设置');self.resize(590,680)
        set_theme_style(self,editor_stylesheet(FONT_CSS)+
            f'QPushButton{{border:0;border-radius:7px;padding:6px 10px;}}'
            # The inherited hover used PANEL, identical to the settings page.
            # Keep a visible filled action on hover across all lazy-built tabs.
            f'QPushButton:hover{{background:{SELECTED};}}'
            f'QPushButton:pressed,QPushButton:checked:hover{{background:{BORDER};}}'
            f'QTabWidget::pane{{border:0;background:{PANEL};}}QTabBar::tab{{background:{SELECTED};color:{MUTED};border:0;border-radius:6px;padding:7px 10px;margin:2px;}}'
            f'QTabBar::tab:selected{{background:{SURFACE};color:{INK};}}'
            f'QScrollBar:vertical{{background:{SELECTED};width:12px;margin:0;border:0;border-radius:6px;}}'
            f'QScrollBar::handle:vertical{{background:{ACCENT};border:2px solid {SELECTED};border-radius:6px;min-height:42px;}}'
            f'QScrollBar::handle:vertical:hover{{background:{PRIMARY};}}QScrollBar::handle:vertical:pressed{{background:{INK};}}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;width:0;border:0;background:transparent;}'
            'QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}'
            'QScrollBar:vertical:disabled,QScrollBar::handle:vertical:disabled{background:transparent;border-color:transparent;}')
        outer=QVBoxLayout(self);self.tabs=QTabWidget();outer.addWidget(self.tabs,1)
        outer.setContentsMargins(10,8,10,8);outer.setSpacing(6);self.tabs.setDocumentMode(True);self.tabs.tabBar().setExpanding(True)
        self._page_forms={};self._built_pages=set();self._building_index=0;self.refresh_buttons={}
        for title in ['面板与显示', '人物与动作', 'Codex 联动', '角色与素材', '闲聊与台词', '更新与维护']:self.tab(title)
        self.build_page(0)
        if not lazy:
            for index in range(1,6):self.build_page(index)
        self.draft_status=QLabel();self.draft_status.setWordWrap(True);outer.addWidget(self.draft_status)
        self.status=QLabel();self.status.setWordWrap(True);outer.addWidget(self.status)
        row=QHBoxLayout()
        self.defaults_button=QPushButton('本页恢复默认');self.defaults_button.clicked.connect(self.defaults);row.addWidget(self.defaults_button)
        self.discard_button=QPushButton('放弃修改');self.discard_button.clicked.connect(self.reload);row.addWidget(self.discard_button)
        self.apply_button=QPushButton('保存');self.apply_button.clicked.connect(self.apply);row.addWidget(self.apply_button)
        button=QPushButton('返回' if embedded else '关闭');button.clicked.connect(self.dismiss);row.addWidget(button)
        for control in self.findChildren(QPushButton):control.setAutoDefault(False)
        self.apply_button.setProperty('role','primary');self.apply_button.setAutoDefault(True);self.apply_button.setDefault(True)
        self.save_shortcut=QShortcut(QKeySequence('Ctrl+S'),self);self.save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);self.save_shortcut.activated.connect(self.apply)
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        outer.addLayout(row);self.tabs.currentChanged.connect(self.activate_page);self.reload()
        if hasattr(pet,'settingsChanged'):pet.settingsChanged.connect(self.sync_from_pet)
        pet.bubble.dataBusyChanged.connect(self.update_refresh_state)
        for key in self.refresh_buttons:self.update_refresh_state(key,getattr(pet.bubble,key+'_busy'))
    def build_page(self,index):
        if index in self._built_pages:return
        self._built_pages.add(index);self._building_index=index;self._writing_widgets=True
        getattr(self,'build_page_'+str(index))()
        if self.draft:self.fill(self.draft.values);self.refresh_library();self.update_draft_state()
        for button in self.findChildren(QPushButton):button.setAutoDefault(False)
        self._writing_widgets=False
    def activate_page(self,index):
        self.build_page(index);self.update_draft_state()
    def build_page_0(self):
        pet=self.pet
        appearance=self.tab('面板与显示')
        motion=SlidingSegments([('性能','performance'),('质量','quality')])
        appearance.addRow('界面动画',motion);self.fields['ui_animation_mode']=motion
        self.field_tabs['ui_animation_mode']=0;self.field_titles['ui_animation_mode']='界面动画'
        motion.currentIndexChanged.connect(lambda:self.edited('ui_animation_mode'))
        self.section(appearance,'颜色主题',None)
        themes=ThemeChoices();appearance.addRow(themes);self.fields['theme']=themes
        self.field_tabs['theme']=0;self.field_titles['theme']='颜色主题'
        themes.currentIndexChanged.connect(lambda:self.edited('theme'))
        custom=QWidget();custom_form=QFormLayout(custom);custom_form.setContentsMargins(0,0,0,0)
        for key,title in (('theme_accent','强调色'),('theme_surface','背景色'),('theme_ink','文字色')):
            field=QLineEdit();field.setMaxLength(7);field.setPlaceholderText('#RRGGBB');field.setAccessibleName(title)
            custom_form.addRow(title,field);self.fields[key]=field;self.field_tabs[key]=0;self.field_titles[key]=title
            field.textChanged.connect(lambda text,key=key:self.edited(key))
        self.theme_custom=custom;appearance.addRow(custom)
        custom.hide()
        themes.currentIndexChanged.connect(lambda:self.theme_custom.setVisible(themes.currentData()=='custom'))
        self.section(appearance,'显示内容',None)
        self.check(appearance,'panel_detached','面板与人物分别移动')
        for key,title in [('character_visible','显示人物'),('on_top','始终置顶'),('mouse_through','鼠标穿透（可从托盘恢复）'),('bubble','显示面板'),('quota_visible','显示额度和重置时间')]:
            self.check(appearance,key,title)
        self.fullscreen_mode=SlidingSegments([('关闭','off'),('仅视频','video'),('游戏和视频','game_video')])
        appearance.addRow('全屏时让位',self.fullscreen_mode);self.fields['fullscreen_yield_mode']=self.fullscreen_mode;self.field_tabs['fullscreen_yield_mode']=0;self.field_titles['fullscreen_yield_mode']='全屏时让位'
        self.fullscreen_mode.currentIndexChanged.connect(lambda:self.edited('fullscreen_yield_mode'))
        note=QLabel('只在桌宠所在屏幕被窗口真正全屏占用时生效。游戏和视频模式隐藏人物和面板，仅保留托盘额度环；不会因完成提醒重新置顶。浏览器、办公和系统窗口不会按游戏处理。')
        note.setWordWrap(True);set_theme_style(note,f'font-size:11px;color:{MUTED};');appearance.addRow(note)
        self.section(appearance,'卡片与快捷入口','自动模式闲置后收为胶囊；手动选择胶囊或极简后不会因新状态自动展开。')
        self.mode=SlidingSegments([('自动','auto'),('胶囊','mini'),('极简','minimal')])
        appearance.addRow('卡片显示模式',self.mode);self.fields['bubble_mode']=self.mode;self.field_tabs['bubble_mode']=0;self.field_titles['bubble_mode']='卡片显示模式'
        self.mode.currentIndexChanged.connect(lambda:self.edited('bubble_mode'))
        from quick_actions import ACTIONS
        self.shortcut=QComboBox()
        for key,title,icon in ACTIONS:self.shortcut.addItem(title,key)
        appearance.addRow('胶囊左侧快捷功能',self.shortcut);self.fields['capsule_action']=self.shortcut;self.field_tabs['capsule_action']=0;self.field_titles['capsule_action']='胶囊快捷功能'
        self.shortcut.currentIndexChanged.connect(lambda:self.edited('capsule_action'))
        self.website=QLineEdit();self.website.setPlaceholderText('https://…');self.website.setAccessibleName('自定义网页地址');self.website.setMaxLength(2048)
        appearance.addRow('自定义网页地址',self.website);self.fields['capsule_website']=self.website;self.field_tabs['capsule_website']=0;self.field_titles['capsule_website']='自定义网页地址'
        self.website.textChanged.connect(lambda:self.edited('capsule_website'))
        note=QLabel('仅卡片时可拖动空白处或极简圆；点击极简圆回到正常卡片，右键可切换显示模式。人物隐藏后暂停动画，Codex 联动继续。');note.setWordWrap(True);appearance.addRow(note)

    def build_page_1(self):
        pet=self.pet
        behavior=self.tab('人物与动作')
        self.section(behavior,'位置与移动',None)
        self.number(behavior,'scale','角色大小（倍）',.4,2.5,.1)
        self.check(behavior,'no_move','锁定人物位置（禁止拖动和自主走动）')
        self.check(behavior,'wandering','允许自主走动（不影响手动拖动）')
        self.roaming_button=QPushButton('走动设置  ›');self.roaming_button.setObjectName('open_roaming_settings');behavior.addRow(self.roaming_button)
        set_theme_style(self.roaming_button,'QPushButton#open_roaming_settings{background:#e8dff0;color:#75618d;border:0;border-radius:7px;padding:6px 9px;}QPushButton#open_roaming_settings:hover{background:#ded2e7;}QPushButton#open_roaming_settings:pressed{background:#d6c5ed;}QPushButton#open_roaming_settings:disabled{background:#efebf2;color:#706879;}')
        self.check(behavior,'drag_physics','松手后惯性滑行与反弹')
        self.check(behavior,'edge_docking','拖动贴边探头')
        self.section(behavior,'动作与声音','自动动作静音；只在你主动点击或手动播放时使用音效。')
        self.check(behavior,'random_actions','自动随机动作')
        self.check(behavior,'sound','主动点击人物或手动动作时播放音效')
        self.advanced_button=QPushButton('展开高级动作参数');self.advanced_button.setCheckable(True);behavior.addRow(self.advanced_button)
        advanced=QWidget();advanced_form=QFormLayout(advanced);advanced_form.setContentsMargins(0,0,0,0)
        for key,title,lo,hi,step in [('playback_speed','播放速度（倍）',.25,3,.25),('action_gap','动作结束后等待（秒）',0,60,1),('random_interval','自主动作间隔（秒）',3,600,1)]:self.number(advanced_form,key,title,lo,hi,step)
        self.advanced_card=AnimatedDisclosure(advanced);behavior.addRow(self.advanced_card)
        self.advanced_button.toggled.connect(self.advanced_card.set_expanded)
        self.advanced_button.toggled.connect(lambda checked:self.advanced_button.setText('收起高级动作参数' if checked else '展开高级动作参数'))
        from roaming_editor import RoamingEditor
        self.roaming_editor=RoamingEditor(self,self);self.roaming_button.clicked.connect(self.roaming_editor.open)

    def build_page_2(self):
        pet=self.pet
        connection=self.tab('Codex 联动')
        self.section(connection,'额度变化提醒',None)
        self.number(connection,'quota_decline_threshold','下降达到',1,100,1,suffix='%')
        self.number(connection,'quota_increase_threshold','上涨达到',1,100,1,suffix='%')
        self.section(connection,'启动与退出','Windows 登录启动与随 Codex 启动相互独立；按需开启。')
        self.startup=SwitchRow('登录 Windows 时启动');connection.addRow(self.startup)
        self.field_tabs['startup']=self._building_index;self.field_titles['startup']='开机启动'
        self.startup.toggled.connect(lambda:self.edited('startup'))
        self.codex_startup=SwitchRow('随 Windows Codex 桌面端启动');connection.addRow(self.codex_startup)
        self.field_tabs['codex_startup']=self._building_index;self.field_titles['codex_startup']='随 Codex 启动'
        self.codex_startup.toggled.connect(lambda:self.edited('codex_startup'))
        note=QLabel('登录时运行轻量监听；识别 Codex 桌面端，不依赖 Codex++。手动退出桌宠后，本次 Codex 使用期间不再拉起。可另行开启关闭联动。');note.setWordWrap(True);set_theme_style(note,f'font-size:11px;color:{MUTED};');connection.addRow(note)
        self.check(connection,'codex_exit','Codex 桌面端关闭后退出桌宠（确认退出后约6秒）')
        self.section(connection,'状态与人物响应','面板持续更新，人物在安全边界切换；不会逐条打断动作。')
        self.check(connection,'commentary','显示 Codex 工作过程与回复摘要')
        self.check(connection,'status_actions','人物响应 Codex 状态')
        self.number(connection,'status_action_interval','单次状态动作最小间隔（秒）',8,120,1)
        note=QLabel('思考/阅读和处理任务在状态稳定1.5秒后进入，保持中段循环，状态改变后自然收尾。其他动作完整播放并按间隔检查。完成消息立即提醒，庆祝等待安全边界。');note.setWordWrap(True);set_theme_style(note,'font-size:11px;color:#706879;');connection.addRow(note)

        self.section(connection,'Codex 连接健康','各项独立检测；失败不会当作已读、零额度或零用量。')
        self.connection_button=QPushButton('检测连接与额度');self.connection_button.setProperty('role','primary');self.connection_button.clicked.connect(self.check_connection);connection.addRow(self.connection_button)
        self.health_panel=CapabilityPanel();self.health_panel.set_snapshot(pet.connection_health.snapshot());connection.addRow(self.health_panel)
        pet.connectionHealthChanged.connect(self.health_panel.set_snapshot)
        row=QWidget();buttons=QHBoxLayout(row);buttons.setContentsMargins(0,0,0,0);self.refresh_buttons={}
        for key,title,slot in [('quota','刷新额度',pet.refresh_quota),('reset','刷新重置消息',pet.refresh_reset_feed),('token','刷新 Token',pet.refresh_tokens)]:
            button=QPushButton(title);button.clicked.connect(slot);buttons.addWidget(button);self.refresh_buttons[key]=(button,title)
        connection.addRow(row)
        self.path_toggle=QPushButton('连接路径与检测报告');self.path_toggle.setCheckable(True);connection.addRow(self.path_toggle)
        path_body=QWidget();paths=QFormLayout(path_body);paths.setContentsMargins(0,4,0,4)
        from codex_connection import saved_paths,data_home
        saved=saved_paths();self.path_fields={};self.native_path_rows=[];self.path_form=paths
        self.path_source=SlidingSegments([('Windows','windows'),('WSL','wsl')]);self.path_source.setCurrentIndex(self.path_source.findData(saved.get('source') or 'windows'),False);paths.addRow('连接来源',self.path_source)
        for key,title in [('home','Codex 数据目录'),('cli','Codex CLI 程序')]:
            row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
            field=QLineEdit(saved.get(key,''));field.setPlaceholderText('留空自动识别');field.setAccessibleName(title);self.path_fields[key]=field;layout.addWidget(field,1)
            browse=QPushButton('选择…');browse.clicked.connect(lambda checked=False,k=key:self.choose_path(k));layout.addWidget(browse);paths.addRow(title,row)
            self.native_path_rows.append(row)
        self.wsl_body=QWidget();wsl_form=QFormLayout(self.wsl_body);wsl_form.setContentsMargins(0,0,0,0)
        distro_row=QWidget();distro_layout=QHBoxLayout(distro_row);distro_layout.setContentsMargins(0,0,0,0)
        self.wsl_distro=QComboBox();self.wsl_distro.setAccessibleName('WSL 发行版')
        self.wsl_distro.addItem(saved.get('wsl_distro') or '请刷新发行版',saved.get('wsl_distro',''));distro_layout.addWidget(self.wsl_distro,1)
        self.wsl_refresh=QPushButton('刷新发行版');self.wsl_refresh.clicked.connect(self.refresh_wsl_sources);distro_layout.addWidget(self.wsl_refresh);wsl_form.addRow('发行版',distro_row)
        self.wsl_fields={};self._wsl_path=saved.get('wsl_path','')
        for key,title,hint in [('wsl_user','Linux 用户','留空使用默认用户'),('wsl_home','Linux 数据目录','留空识别 CODEX_HOME'),('wsl_cli','Linux CLI 路径','留空自动识别 codex')]:
            field=QLineEdit(saved.get(key,''));field.setPlaceholderText(hint);field.setAccessibleName(title);self.wsl_fields[key]=field;wsl_form.addRow(title,field)
        paths.addRow(self.wsl_body)
        self.active_path=QLabel('当前生效目录：'+str(data_home()));self.active_path.setWordWrap(True);set_theme_style(self.active_path,f'font-size:11px;color:{MUTED};');paths.addRow(self.active_path)
        note=QLabel('保存后重启桌宠生效。WSL 验证会启动所选发行版；使用 Linux 登录，Windows 数据独立保留。');note.setWordWrap(True);set_theme_style(note,f'font-size:11px;color:{MUTED};');paths.addRow(note)
        row=QWidget();layout=QHBoxLayout(row);layout.setContentsMargins(0,0,0,0)
        self.save_paths_button=QPushButton('验证并保存路径');self.save_paths_button.clicked.connect(self.validate_paths);layout.addWidget(self.save_paths_button)
        reset=QPushButton('改为自动识别');reset.clicked.connect(self.clear_paths);layout.addWidget(reset);paths.addRow(row)
        self.path_status=QLabel();self.path_status.setWordWrap(True);paths.addRow(self.path_status)
        self.connection_text=hide_scrollbars(QPlainTextEdit());self.connection_text.setReadOnly(True);self.connection_text.setMaximumHeight(140);self.connection_text.setAccessibleName('最近一次连接检测报告')
        self.connection_text.setPlainText('点击“检测连接与额度”生成只读报告；不会发送对话或消耗 Token。');paths.addRow(self.connection_text)
        self.paths_card=AnimatedDisclosure(path_body);connection.addRow(self.paths_card);self.path_toggle.toggled.connect(self.paths_card.set_expanded)
        self.path_source.currentIndexChanged.connect(self.path_source_changed);self.path_source_changed()

    def build_page_3(self):
        pet=self.pet
        library=self.tab('角色与素材')
        if hasattr(pet,'materials'):
            self.section(library,'内置白龙画质','素材与程序独立；下载和切换立即执行，不属于设置草稿。')
            from material_controller import MaterialPanel
            self.material_panel=MaterialPanel(pet.materials);library.addRow(self.material_panel)
        self.section(library,'角色资源','切换、导入和预览立即执行；预览始终静音。')
        self.characters=QComboBox();library.addRow('当前角色',self.characters)
        button=QPushButton('切换到所选角色');button.clicked.connect(self.switch_character);library.addRow(button)
        button=QPushButton('导入角色文件夹（WebP / GIF / WebM）');button.clicked.connect(self.import_pack);library.addRow(button)
        tool=QPushButton('WebM 转换工具…');tool.clicked.connect(self.select_converter);library.addRow(tool)
        self.actions=QComboBox();library.addRow('动作分类与预览',self.actions)
        button=QPushButton('静音预览所选动作');button.clicked.connect(self.preview);library.addRow(button)
        button=QPushButton('检查所有素材');button.clicked.connect(self.validate);library.addRow(button)
        self.library_status=QLabel();self.library_status.setWordWrap(True);library.addRow(self.library_status)

    def build_page_4(self):
        pet=self.pet
        chat=self.tab('闲聊与台词')
        self.section(chat,'白龙聊天服务','与 Codex 的只读联动独立；仅主动发送时调用。')
        button=QPushButton('配置白龙聊天服务…');button.clicked.connect(pet.open_chat_service);chat.addRow(button)
        self.section(chat,'自动台词','自动台词与主动闲聊相互独立；台词始终无声。')
        self.check(chat,'self_talk','启用自动台词')
        self.check(chat,'talk_quiet','Codex 工作时不自言自语')
        self.number(chat,'talk_min','台词最短间隔（秒）',5,3600,5);self.number(chat,'talk_max','台词最长间隔（秒）',5,7200,5)
        self.lines=hide_scrollbars(QPlainTextEdit());self.lines.setMaximumHeight(100);self.lines.setPlaceholderText('每行一句，自动台词不会播放声音');chat.addRow('自定义台词',self.lines)
        self.field_tabs['talk_lines']=self._building_index;self.field_titles['talk_lines']='自定义台词';self.lines.textChanged.connect(lambda:self.edited('talk_lines'))

    def build_page_5(self):
        pet=self.pet
        maintenance=self.tab('更新与维护')
        self.section(maintenance,'软件更新','检查 GitHub 公开稳定版；下载和安装由你主动发起。')
        self.check(maintenance,'update_checks','自动检查更新（不自动下载）')
        if hasattr(pet,'updates'):
            from update_widgets import UpdatePanel
            self.update_panel=UpdatePanel(pet.updates);maintenance.addRow(self.update_panel)
        self.section(maintenance,'诊断与数据','维护操作立即执行；不属于设置草稿。')
        if hasattr(pet,'open_install_manager'):
            button=QPushButton('程序位置与安装管理');button.clicked.connect(pet.open_install_manager);maintenance.addRow(button)
        for title,slot in [('打开配置与聊天记录目录',pet.open_data),('导出诊断报告（不含对话和密钥）',pet.export_diagnostics),('备份设置（不含密钥与对话）',pet.backup_settings),('恢复设置备份',pet.restore_settings),('清理历史版本与备份（先预览）',pet.cleanup_installations)]:
            button=QPushButton(title);button.clicked.connect(slot);maintenance.addRow(button)
        maintenance.addRow(QLabel('当前版本 '+VERSION))

    def section(self,form,title,note):
        name=QLabel(title);set_theme_style(name,f'font-size:13px;font-weight:500;color:{PRIMARY};background:transparent;padding:2px;margin-top:10px;');form.addRow(name)
        if note:
            label=QLabel(note);label.setWordWrap(True);set_theme_style(label,f'font-size:11px;color:{MUTED};margin-bottom:3px;');form.addRow(label)
    def choose_path(self,key):
        if key=='home':value=QFileDialog.getExistingDirectory(self,'选择 Codex 数据目录',self.path_fields[key].text())
        else:value,_=QFileDialog.getOpenFileName(self,'选择 Codex CLI（不是桌面主程序）',self.path_fields[key].text(),'程序 (*.exe);;所有文件 (*)')
        if value:self.path_fields[key].setText(value)
    def path_source_changed(self,*args):
        wsl=self.path_source.currentData()=='wsl'
        if 'codex_exit' in self.fields:self.fields['codex_exit'].setEnabled(not wsl)
        for row in self.native_path_rows:self.path_form.setRowVisible(row,not wsl)
        self.wsl_body.setVisible(wsl)
        if self.paths_card.expanded:self.paths_card.refresh_content()
    def path_values(self):
        values={key:field.text().strip().strip('"') for key,field in {**self.path_fields,**self.wsl_fields}.items()}
        return dict(values,source=self.path_source.currentData(),wsl_distro=self.wsl_distro.currentData() or '',wsl_path=self._wsl_path)
    def clear_paths(self):
        fields=self.wsl_fields if self.path_source.currentData()=='wsl' else self.path_fields
        for field in fields.values():field.clear()
    def refresh_wsl_sources(self):
        if self.path_job and self.path_job.isRunning():return
        self.wsl_refresh.setEnabled(False);self.save_paths_button.setEnabled(False);self.path_status.setText('正在查找已安装的 WSL 发行版…')
        self.path_job=PathsJob(dict(operation='list_wsl'),self);self.path_job.result.connect(self.wsl_sources_done);self.path_job.failed.connect(self.path_status.setText)
        self.path_job.finished.connect(lambda:[self.wsl_refresh.setEnabled(True),self.save_paths_button.setEnabled(True)]);self.path_job.start()
    def wsl_sources_done(self,names):
        selected=self.wsl_distro.currentData();self.wsl_distro.clear()
        for name in names:self.wsl_distro.addItem(name,name)
        if selected in names:self.wsl_distro.setCurrentIndex(self.wsl_distro.findData(selected))
        if not names:self.wsl_distro.addItem('未找到发行版','')
        self.path_status.setText('请选择发行版，再验证并保存。' if names else '尚未安装 WSL 发行版。')
    def validate_paths(self):
        if self.path_job and self.path_job.isRunning():return
        values=self.path_values()
        self.save_paths_button.setEnabled(False);self.path_status.setText('正在验证路径与 CLI 版本…')
        self.path_job=PathsJob(values,self);self.path_job.result.connect(self.paths_done);self.path_job.failed.connect(self.path_status.setText)
        self.path_job.finished.connect(lambda:self.save_paths_button.setEnabled(True));self.path_job.start()
    def paths_done(self,values):
        if self.path_values()!=self.path_job.values:
            self.path_status.setText('验证期间输入已改变，请重新验证；未保存。');return
        from desktop import STATE_DIR
        from codex_connection import save_paths
        try:save_paths(values,STATE_DIR/'connection-paths.json')
        except OSError:self.path_status.setText('路径保存失败，输入仍保留。');return
        for key,field in {**self.path_fields,**self.wsl_fields}.items():field.setText(values.get(key,''))
        self._wsl_path=values.get('wsl_path','')
        self.path_status.setText('已验证并保存，重启桌宠后生效；当前监测继续使用原路径。')
    def update_refresh_state(self,key,busy):
        if key not in self.refresh_buttons:return
        button,title=self.refresh_buttons[key];button.setEnabled(not busy);button.setText('查询中…' if busy else title)
    def tab(self,title):
        if title in self._page_forms:return self._page_forms[title]
        widget=QWidget();form=QFormLayout(widget);form.setVerticalSpacing(5);form.setHorizontalSpacing(12);form.setContentsMargins(9,3,9,10)
        if self.embedded:
            widget.setObjectName('settings_category');set_theme_style(widget,'QWidget#settings_category{background:#f5f2f7;}')
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            area=hide_scrollbars(QScrollArea());area.setWidgetResizable(True)
            # A permanently hidden bar also keeps disclosure viewport width stable.
            area.setWidget(widget)
            bar=area.verticalScrollBar();bar.setSingleStep(32)
            bar.rangeChanged.connect(lambda low,high,b=bar:b.setEnabled(high>low))
            index=self.tabs.addTab(area,{'面板与显示':'面板','人物与动作':'人物','Codex 联动':'Codex','角色与素材':'素材','闲聊与台词':'闲聊','更新与维护':'维护'}.get(title,title))
            self.tabs.setTabToolTip(index,title)
        else:self.tabs.addTab(widget,title)
        self._page_forms[title]=form
        return form
    def dismiss(self):
        if self.embedded:self.pet.bubble.return_to_status()
        else:self.end_theme_preview();self.hide()
    def keyPressEvent(self,event):
        if self.embedded and event.key()==Qt.Key.Key_Escape:self.dismiss();event.accept();return
        super().keyPressEvent(event)
    def check(self,form,key,title):
        widget=SwitchRow(title);self.fields[key]=widget;form.addRow(widget);self.field_tabs[key]=self._building_index;self.field_titles[key]=title
        widget.toggled.connect(lambda:self.edited(key))
    def number(self,form,key,title,lo,hi,step,factor=1,suffix=''):
        widget=QDoubleSpinBox();widget.setRange(lo*factor,hi*factor);widget.setSingleStep(step*factor);widget.setDecimals(0 if step*factor>=1 else 2);widget.setSuffix(suffix)
        self.fields[key]=widget;self.factors[key]=factor;self.field_tabs[key]=self._building_index;self.field_titles[key]=title;form.addRow(title,widget)
        widget.valueChanged.connect(lambda:self.edited(key))
    def fill(self,settings):
        self._writing_widgets=True
        for key,widget in self.fields.items():
            if key=='wander_zone':widget.setValue(settings.get(key,DEFAULTS[key]))
            elif isinstance(widget,QCheckBox):widget.setChecked(settings.get(key,DEFAULTS[key]))
            elif isinstance(widget,(QComboBox,SlidingSegments,ThemeChoices)):widget.setCurrentIndex(widget.findData(settings.get(key,DEFAULTS[key])))
            elif isinstance(widget,QLineEdit):widget.setText(settings.get(key,DEFAULTS[key]))
            else:widget.setValue(settings.get(key,DEFAULTS[key])*self.factors.get(key,1))
        if hasattr(self,'lines'):
            lines='\n'.join(settings.get('talk_lines',DEFAULTS['talk_lines']))
            current=[line.strip() for line in self.lines.toPlainText().splitlines() if line.strip()]
            if current!=settings.get('talk_lines',DEFAULTS['talk_lines']):self.lines.setPlainText(lines)
        if hasattr(self,'startup'):self.startup.setChecked(bool(settings.get('startup',False)))
        if hasattr(self,'codex_startup'):self.codex_startup.setChecked(bool(settings.get('codex_startup',False)))
        self.theme_custom.setVisible(settings.get('theme','bailong')=='custom')
        self.fields['theme'].setCustomColors(settings)
        if hasattr(self,'roaming_editor'):self.roaming_editor.refresh()
        self._writing_widgets=False
    def values_from_pet(self,read_startup=False):
        values={key:copy.deepcopy(self.pet.settings.get(key,DEFAULTS[key])) for key in DEFAULTS}
        values['talk_lines']=copy.deepcopy(self.pet.settings.get('talk_lines',DEFAULTS['talk_lines']))
        if read_startup:
            from codex_startup import enabled
            try:values['startup']=autostart_enabled();values['codex_startup']=enabled()
            except OSError:self.status.setText('开机启动状态读取失败；其他设置仍可修改。')
        return values
    def reload(self):
        if hasattr(self.pet,'preview_theme'):self.pet.preview_theme(None)
        self.status.clear();values=self.values_from_pet(read_startup=True);values.setdefault('startup',False)
        self.draft=SettingsDraft(values);self.fill(self.draft.values);self.refresh_library();self.update_draft_state()
    def sync_from_pet(self,changes=None,read_startup=False):
        if self.draft is None:return
        self.draft.rebase(self.values_from_pet(read_startup));self.fill(self.draft.values);self.update_draft_state()
        if self.pet.bubble.panel_page=='settings' and not self._saving:self.preview_theme_draft()

    def preview_theme_draft(self):
        from theme_registry import THEME_KEYS,valid_hex
        self.fields['theme'].setCustomColors(self.draft.values)
        if not any(k in self.draft.dirty for k in THEME_KEYS):
            if getattr(self.pet,'_theme_preview',None) is not None:self.pet.preview_theme(None)
            return
        if self.draft.values['theme']=='custom' and not all(valid_hex(self.draft.values[k]) for k in THEME_KEYS[1:]):return
        try:self.pet.preview_theme(self.draft.values)
        except ValueError as error:self.status.setText(str(error))

    def end_theme_preview(self):
        if self._saving:return
        from theme_registry import THEME_KEYS
        if self.draft is not None:
            for key in THEME_KEYS:
                value=copy.deepcopy(self.pet.settings[key]);self.draft.set(key,value);self.draft.baseline[key]=copy.deepcopy(value)
            self.fill(self.draft.values);self.update_draft_state()
        if hasattr(self.pet,'preview_theme'):self.pet.preview_theme(None,within_transition=self.pet.bubble.size_transition.preparing)
    def edited(self,key):
        if self._writing_widgets or self.draft is None:return
        if key=='startup':value=self.startup.isChecked()
        elif key=='codex_startup':value=self.codex_startup.isChecked()
        elif key=='talk_lines':value=[line.strip() for line in self.lines.toPlainText().splitlines() if line.strip()]
        elif key=='wander_zone':value=self.fields[key].value()
        else:
            widget=self.fields[key];value=widget.isChecked() if isinstance(widget,QCheckBox) else widget.currentData() if isinstance(widget,(QComboBox,SlidingSegments,ThemeChoices)) else widget.text() if isinstance(widget,QLineEdit) else widget.value()/self.factors.get(key,1)
        self.draft.set(key,value);self.status.clear();self.update_draft_state()
        from theme_registry import THEME_KEYS
        if key in THEME_KEYS:self.preview_theme_draft()
    def update_draft_state(self,*args):
        if self.draft is None:return
        self.website.setEnabled(self.shortcut.currentData()=='website')
        count=len(self.draft.dirty);self.apply_button.setEnabled(bool(count));self.discard_button.setEnabled(bool(count))
        if hasattr(self,'roaming_editor'):
            self.roaming_editor.save.setEnabled(bool(count));self.roaming_editor.discard.setEnabled(bool(count))
        from theme_registry import THEME_KEYS
        theme_only=bool(self.draft.dirty) and self.draft.dirty.issubset(THEME_KEYS)
        text='主题预览，Ctrl+S 保存' if theme_only else f'{count} 项未保存，Ctrl+S 保存' if count else '设置已保存'
        if self.draft.conflicts:
            names='、'.join(self.field_titles[k] for k in sorted(self.draft.conflicts))
            text+='\n外部也修改了：'+names+'。应用将采用此处草稿；放弃修改将采用当前值。'
        self.draft_status.setText(text)
        self.defaults_button.setEnabled(any(tab==self.tabs.currentIndex() and key in DEFAULTS for key,tab in self.field_tabs.items()))
        if 'no_move' in self.fields:
            locked=self.fields['no_move'].isChecked()
            walking=self.fields['wandering'].isChecked() and not locked
            for key in ('wandering','drag_physics'):self.fields[key].setEnabled(not locked)
            if 'edge_docking' in self.fields:self.fields['edge_docking'].setEnabled(not locked and not getattr(self.pet,'_materials_missing',False) and self.pet.settings.get('character_visible',True))
            for key in ('wander_horizontal_only','move_speed','move_range','wander_mode','wander_side','wander_zone'):self.fields[key].setEnabled(walking)
            self.roaming_button.setEnabled(walking)
        if 'status_actions' in self.fields:self.fields['status_action_interval'].setEnabled(self.fields['status_actions'].isChecked())
        if 'self_talk' in self.fields:
            talking=self.fields['self_talk'].isChecked()
            for key in ('talk_quiet','talk_min','talk_max'):self.fields[key].setEnabled(talking)
            self.lines.setEnabled(talking)
    def defaults(self):
        for key,tab in self.field_tabs.items():
            if tab==self.tabs.currentIndex() and key in DEFAULTS:self.draft.set(key,DEFAULTS[key])
        self.fill(self.draft.values);self.update_draft_state();self.preview_theme_draft();self.status.setText('已载入本页默认值，保存后保留。')
    def apply(self):
        values=self.draft.changes();startup=values.pop('startup',None);codex_startup=values.pop('codex_startup',None);messages=[]
        if values:
            try:
                self._saving=True
                self.pet.apply_settings(values)
                for key in values:
                    self.draft.values[key]=copy.deepcopy(self.pet.settings[key]);self.draft.baseline[key]=copy.deepcopy(self.pet.settings[key]);self.draft.conflicts.discard(key)
                messages.append('桌宠设置已保存。')
            except (OSError,ValueError) as error:messages.append('桌宠设置保存失败：'+str(error))
            finally:self._saving=False
        if startup is not None:
            try:set_autostart(startup);self.draft.rebase({'startup':startup});messages.append('开机启动已保存。')
            except OSError as error:messages.append('开机启动保存失败：'+str(error)+'；可单独重试。')
        if codex_startup is not None:
            from codex_startup import configure
            try:configure(codex_startup);self.draft.rebase({'codex_startup':codex_startup});messages.append('Codex 启动联动已保存。')
            except OSError as error:messages.append('Codex 启动联动保存失败：'+str(error)+'；可单独重试。')
        self.fill(self.draft.values);self.update_draft_state();self.status.setText('\n'.join(messages))
    def refresh_library(self):
        if not hasattr(self,'characters'):return
        self.characters.clear()
        for key,name in self.pet.character_choices():self.characters.addItem(name,key)
        self.characters.setCurrentIndex(self.characters.findData(self.pet.settings.get('character','builtin')))
        self.actions.clear()
        for group,items in self.pet.action_groups().items():
            for item in items:self.actions.addItem(group+' / '+item.get('name',item['id']),item)
        self.library_status.setText(f'当前 {len(all_items(self.pet.manifest))} 段素材；缺省类别使用待机或现有动作回退。')
    def switch_character(self):
        try:self.pet.switch_character(self.characters.currentData());self.refresh_library()
        except (OSError,ValueError,KeyError) as error:self.library_status.setText('切换失败：'+str(error))
    def preview(self):
        item=self.actions.currentData()
        if item:self.pet.choose(item,interactive=False,manual=True)
    def select_converter(self):
        if self.job and self.job.isRunning():self.library_status.setText('正在检查或导入，请稍等…');return
        path,_=QFileDialog.getOpenFileName(self,'选择 FFmpeg 转换工具（仅导入 WebM 时使用）','','FFmpeg (ffmpeg*.exe);;所有文件 (*)')
        if not path:return
        self.library_status.setText('正在后台验证转换工具…')
        self.job=ConverterJob(path,None,self)
        self.job.result.connect(lambda _:self.library_status.setText('转换工具已验证，导入 WebM 时使用；日常动画播放不依赖它。'))
        self.job.failed.connect(self.library_status.setText);self.job.start()
    def import_pack(self):
        source=QFileDialog.getExistingDirectory(self,'选择包含素材清单或分类素材文件夹的角色包')
        if source:self.start_job(source,self.pet.character_dir)
    def validate(self):self.start_job(self.pet.asset_root)
    def start_job(self,source,destination=None):
        if self.job and self.job.isRunning():self.library_status.setText('正在检查或导入，请稍等…');return
        self.library_status.setText('后台检查 / 转换中，桌宠仍可操作…')
        self.job=LibraryJob(source,destination,self)
        self.job.result.connect(lambda value:self.job_done(value,destination));self.job.failed.connect(lambda error:self.library_status.setText('素材检查失败：'+error));self.job.start()
    def job_done(self,value,destination):
        self.refresh_library();self.library_status.setText('角色已导入，可在上方切换。' if destination else '所有素材已逐帧检查，可正常读取。')
    def check_connection(self):
        if self.connection_job and self.connection_job.isRunning():return
        self.connection_button.setEnabled(False);self.connection_text.setPlainText('正在检查本机 Codex 和账户额度…')
        self.connection_job=ConnectionJob(self);self.connection_job.report.connect(self.connection_done)
        self.connection_job.finished.connect(lambda:self.connection_button.setEnabled(True));self.connection_job.start()
    def connection_done(self,report):
        from desktop import STATE_DIR
        from desktop_core import atomic_json
        self.pet.update_connection_health(report.get('capabilities',{}))
        path=STATE_DIR/'codex-connection-check.json'
        try:atomic_json(path,report);note='\n\n报告已保存：'+str(path)
        except OSError:note='\n\n报告文件保存失败；检测结果仍可查看。'
        self.connection_text.setPlainText(report.get('summary','检查完成')+note)
    def closeEvent(self,event):self.end_theme_preview();self.hide();event.ignore()
