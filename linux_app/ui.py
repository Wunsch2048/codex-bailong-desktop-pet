"""保留共享界面的绘制，只连接 Linux 托盘及本机设置"""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QLabel, QMenu, QPushButton


def install(stack):
    """限定在 Linux 入口生命周期内，不更改 Windows 组件"""
    from .overrides import replace
    from desktop_settings import SettingsDialog
    from hover_hints import TrayHints
    from desktop import DesktopPet

    populate = DesktopPet.populate_tray

    def populate_tray(pet):
        """DBusMenu 保持菜单项身份，展开时仅同步原菜单生成的状态"""
        if not pet.tray_menu.actions():
            populate(pet)
            return
        # 原生成器仍决定文案和勾选，不清空已被桌面端缓存的菜单树
        template = QMenu()
        pet.build_menu(template, tray=True)
        states = {action.objectName(): action for action in template.findChildren(QAction) if action.objectName()}
        for action in pet.tray_menu.findChildren(QAction):
            source = states.get(action.objectName())
            if source is not None:
                action.setText(source.text())
                action.setEnabled(source.isEnabled())
                action.setChecked(source.isChecked())
        template.deleteLater()

    build = SettingsDialog.build_page_2
    maintenance = SettingsDialog.build_page_5

    def maintenance_page(dialog):
        """程序下载指向 Linux 社区发行页，动画仍使用共享的校验流程"""
        maintenance(dialog)
        button = QPushButton('打开 Linux 程序下载页')
        button.setObjectName('linux_program_download')
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://github.com/helantianshen/codex-bailong-desktop-pet/releases')))
        dialog.tab('更新与维护').insertRow(0, button)

    def connection_page(dialog):
        """Linux 直接连接本机 Codex，不提供 Windows 的 WSL 来源"""
        build(dialog)
        dialog.startup.setText('登录图形桌面时启动')
        dialog.codex_startup.setText('随 Codex 桌面端启动')
        dialog.path_source.setCurrentIndex(0, False)
        dialog.path_source.buttons['windows'].setText('Linux 本机')
        dialog.path_source.buttons['wsl'].setEnabled(False)
        dialog.path_source.buttons['wsl'].setToolTip('WSL 来源仅适用于 Windows')
        for label in dialog.findChildren(QLabel):
            if label.text() == 'Windows 登录启动与随 Codex 启动相互独立；按需开启。':
                label.setText('登录图形桌面启动与随 Codex 启动相互独立；按需开启。')
            elif label.text() == '保存后重启桌宠生效。WSL 验证会启动所选发行版；使用 Linux 登录，Windows 数据独立保留。':
                label.setText('Linux 入口使用启动参数指定的本机 Codex 目录和 CLI；修改后重启桌宠生效。')

    text = TrayHints.set_text

    def tray_text(hints, title, subtitle):
        """StatusNotifier 由桌面绘制提示，不提供自定义悬停窗口的全局坐标"""
        text(hints, title, subtitle)
        hints.tray.setToolTip(title + '\n' + subtitle)

    stack.enter_context(replace(SettingsDialog, 'build_page_2', connection_page))
    stack.enter_context(replace(SettingsDialog, 'build_page_5', maintenance_page))
    stack.enter_context(replace(TrayHints, 'set_text', tray_text))
    stack.enter_context(replace(DesktopPet, 'populate_tray', populate_tray))
