"""Per-user installer for our own release; version folders enable rollback."""
import json
import stat
import uuid
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QTimer,QLockFile
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,QMessageBox,QLineEdit,QFileDialog

from storage_locations import install_root
ROOT=install_root()
DATA=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'BailongEnhanced'
from desktop_core import VERSION
def read_manifest(root=ROOT):
    try:return json.loads((root/'installations.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return dict(current='',versions=[])
def write_manifest(value,root=ROOT):
    root.mkdir(parents=True,exist_ok=True);temp=root/'installations.tmp'
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,root/'installations.json')
def checked_version(root,name):
    from deployment_state import owned_destination
    path=owned_destination(root,name)
    if not (path/'BailongEnhanced.exe').is_file():raise ValueError('安装版本目录无效')
    return path
def ps_string(value):return "'"+str(value).replace("'","''")+"'"
def register(exe,maintenance,startup):
    import winreg
    # A renamed copy has the exact same binary content and detection surface.
    # Keep the argument for old callers, but bind management to the current
    # verified executable, including when rolling back to an older release.
    maintenance=exe
    root=exe.parent
    from storage_locations import registered_install_root
    from windows_entries import install_entries,startup_entry
    previous_root=registered_install_root()
    install_entries(exe,previous_root=previous_root)
    startup_dir=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup'
    startup_entry(startup_dir/'白龙桌宠增强版.lnk',startup_dir/'BailongEnhanced.vbs',[str(exe)],startup,previous_root)
    from codex_startup import register as register_codex_startup
    register_codex_startup(exe,previous_root=previous_root)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BailongEnhanced') as key:
        for name,value in dict(DisplayName='白龙桌宠增强版',DisplayVersion=exe.parent.name.split('-')[0],Publisher='本地白龙桌宠项目',InstallLocation=str(exe.parent.parent.parent),DataLocation=str(DATA),UninstallString='"'+str(maintenance)+'" --manage').items():winreg.SetValueEx(key,name,0,winreg.REG_SZ,value)
        winreg.SetValueEx(key,'NoModify',0,winreg.REG_DWORD,1)

def install(payload,root=ROOT,startup=False,copy_installer=True,before_commit=None,old_running=None,populate=None,data_backup=None,data_root=None,system=None):
    from deployment_state import capture_entries,restore_entries,owned_destination,atomic,recover,verify_payload,stop_version
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True);system=root==ROOT.resolve() if system is None else system
    recover(root,system)
    name=VERSION+'-'+time.strftime('%Y%m%d-%H%M%S')
    if (root/'versions'/name).exists():name+='-'+str(time.time_ns())
    dest=owned_destination(root,name);dest.mkdir(parents=True)
    snapshot=None;journal=None;committed=False
    try:
        snapshot=capture_entries(root,system)
        journal=dict(phase='extracting',new_version=name,snapshot=snapshot,old_running=Path(old_running).parent.name if old_running else '')
        if data_backup:journal.update(data_backup=str(data_backup),data_root=str(data_root))
        atomic(root/'deployment-journal.json',journal)
        if populate is not None:populate(dest)
        else:
            with zipfile.ZipFile(payload) as archive:
                for member in archive.infolist():
                    target=(dest/member.filename).resolve()
                    if not target.is_relative_to(dest) or stat.S_ISLNK(member.external_attr>>16):raise ValueError('安装包路径无效')
                archive.extractall(dest)
        exe=checked_version(root,name)/'BailongEnhanced.exe';verify_payload(dest,VERSION)
        manifest=read_manifest(root);manifest['versions'].insert(0,name);manifest['current']=name
        maintenance=exe
        from shared_assets import share
        def register_shared(sha):
            journal.setdefault('new_shared_objects',[]).append(sha);atomic(root/'deployment-journal.json',journal)
        shared=share(dest,root,register_shared)
        if shared:manifest.setdefault('sharedAssets',{})[name]=shared
        journal['phase']='prepared';atomic(root/'deployment-journal.json',journal)
        if before_commit:
            ready=before_commit(exe,journal)
            if ready:manifest['lastHealth']={key:ready[key] for key in ('version','pid','windowReady','serverReady')}
        if system:register(exe,maintenance,startup)
        write_manifest(manifest,root)
        journal['phase']='committed';atomic(root/'deployment-journal.json',journal);committed=True
        try:(root/'deployment-journal.json').unlink(missing_ok=True)
        except OSError:pass  # Committed journal is safely cleaned on next run.
        return exe
    except Exception as error:
        if committed:raise
        try:
            if before_commit and journal:stop_version(dest/'BailongEnhanced.exe')
            if snapshot:restore_entries(root,snapshot,system)
            if journal and journal.get('data_backup'):
                from directory_deploy import restore_data
                restore_data(data_root,journal['data_backup'],root)
        except Exception as restore_error:
            raise OSError('安装未提交，入口恢复尚未完成；已保留恢复记录和程序，请重试安装。') from restore_error
        # Never remove old versions or user data, and recheck the absolute path.
        if owned_destination(root,name)==dest and dest.exists():shutil.rmtree(dest)
        from shared_assets import cleanup_new
        if journal:cleanup_new(root,journal.get('new_shared_objects',[]))
        (root/'deployment-journal.json').unlink(missing_ok=True)
        raise error

def startup_preference(root=ROOT):
    """Fresh installs require opt-in; upgrades retain recognized Startup entries."""
    manifest=read_manifest(root)
    if not manifest.get('current'):return False
    folder=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup'
    from windows_entries import command_matches,legacy_command
    command=[str(checked_version(root,manifest['current'])/'BailongEnhanced.exe')]
    if (folder/'白龙桌宠增强版.lnk').exists():return command_matches(folder/'白龙桌宠增强版.lnk',command)
    old=legacy_command(folder/'BailongEnhanced.vbs')
    return old is not None and [os.path.normcase(x) for x in old]==[os.path.normcase(x) for x in command]

def stop_existing(root=ROOT):
    """Close only running binaries inside this user's registered versions."""
    import psutil
    from codex_startup import stop_watchers
    stop_watchers(root)
    root=Path(root).resolve();manifest=read_manifest(root);known=set()
    for name in manifest.get('versions',[]):
        try:known.add((checked_version(root,name)/'BailongEnhanced.exe').resolve())
        except (OSError,ValueError):continue
    running=[]
    for process in psutil.process_iter(['exe']):
        try:
            if process.info['exe'] and Path(process.info['exe']).resolve() in known:running.append(process)
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    if not running:return None
    old=Path(running[0].info['exe'])
    subprocess.run([str(old),'--quit'],timeout=20,creationflags=0x08000000,check=True)
    _,alive=psutil.wait_procs(running,timeout=25)
    if alive:raise OSError('旧桌宠尚未退出，请退出后重试；已有文件和设置未改动。')
    return old

def deploy(payload,startup,root=ROOT,progress=lambda text:None,populate=None,after_stop=None,data_root=None,system=None):
    from deployment_state import recover,atomic,wait_ready
    root=Path(root).resolve()
    system=root==ROOT.resolve() if system is None else system
    if (root/'uninstall-pending.json').exists():raise OSError('卸载尚未结束，请先关闭维护窗口，等待清理后重新安装')
    recover(root,system)
    progress('正在关闭旧桌宠…');old=stop_existing(root)
    data_root=Path(data_root or (DATA if root==ROOT.resolve() else root/'user-data'))
    data_backup=None;ready_receipt=None
    def launch_and_confirm(exe,journal):
        nonlocal ready_receipt
        token=uuid.uuid4().hex;ready_receipt=exe.parent/('.ready-'+token+'.json')
        env=dict(BAILONG_DEPLOY_TOKEN=token,BAILONG_DEPLOY_RECEIPT=str(ready_receipt))
        progress('正在确认新版窗口与本地服务就绪…')
        from process_launch import launch_own
        process=launch_own([str(exe)],cwd=str(exe.parent),env=env,creationflags=0x08000000)
        journal['pid']=process.pid;atomic(root/'deployment-journal.json',journal)
        ready=wait_ready(process,exe,ready_receipt,token,VERSION)
        ready_receipt.unlink(missing_ok=True)
        progress('启动检查通过，正在更新入口…')
        return ready
    progress('正在暂存与校验程序及素材…')
    try:
        if after_stop:data_backup=after_stop(old)
        if not data_backup:
            from directory_deploy import backup_data
            data_backup=backup_data(data_root,root,read_manifest(root).get('current',''))
        options=dict(populate=populate) if populate is not None else {}
        return install(payload,root=root,startup=startup,before_commit=launch_and_confirm,old_running=old,data_backup=data_backup,data_root=data_root,system=system,**options)
    except Exception as error:
        restarted=False
        if (root/'deployment-journal.json').exists():
            try:recover(root,system);restarted=True
            except Exception as recovery_error:raise OSError('用户数据或入口尚未恢复，旧版暂不启动；请保留备份并重试安装：'+str(recovery_error)) from error
        if old and not restarted:
            try:
                from process_launch import launch_own
                launch_own([str(old)],cwd=str(old.parent),creationflags=0x08000000)
            except OSError:raise OSError(str(error)+'；旧版未能自动恢复，请从安装目录启动旧版。') from error
        raise

def quick_mode(arguments,executable):
    return '--manage' not in arguments and ('--quick' in arguments or '一键部署' in Path(executable).stem)

class InstallJob(QThread):
    done=Signal(str);failed=Signal(str);progress=Signal(str)
    def __init__(self,payload,startup,parent=None,quick=False,root=None):super().__init__(parent);self.payload=payload;self.startup=startup;self.quick=quick;self.root=Path(root or ROOT)
    def run(self):
        lock=None
        try:
            DATA.mkdir(parents=True,exist_ok=True);lock=QLockFile(str(DATA/'deployment.lock'))
            if not lock.tryLock(0):raise OSError('另一个安装程序正在运行，请等待完成后再试。')
            self.done.emit(str(deploy(self.payload,self.startup,root=self.root,data_root=DATA,system=True,progress=self.progress.emit)))
        except Exception as error:self.failed.emit(str(error))
        finally:
            if lock and lock.isLocked():lock.unlock()

class Installer(QWidget):
    def __init__(self,quick=False,maintenance=False):
        super().__init__();self.quick=quick;self.maintenance=maintenance;self.setWindowTitle('白龙桌宠增强版 · '+('一键部署' if quick else '安装与维护'));self.resize(510,220 if quick else 340);layout=QVBoxLayout(self)
        self.status=QLabel('安装版本 '+VERSION+'\n安装到当前用户，无需管理员权限。\n每次升级保留上一版本；设置和聊天记录放在独立用户目录。');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.current_root=ROOT;self.existing=bool(read_manifest().get('current'))
        location=QHBoxLayout();self.location=QLineEdit(str(ROOT));self.location.setReadOnly(True);self.location.setAccessibleName('程序安装目录');location.addWidget(self.location,1)
        self.browse=QPushButton('选择位置');self.browse.clicked.connect(self.choose_location);location.addWidget(self.browse);layout.addLayout(location)
        self.browse.setEnabled(maintenance or not self.existing)
        self.startup=QCheckBox('登录 Windows 时自动启动');self.startup.setChecked(startup_preference());layout.addWidget(self.startup);self.startup.setVisible(not quick or not self.existing)
        self.install_button=QPushButton('安装 / 升级');self.install_button.clicked.connect(self.start);layout.addWidget(self.install_button)
        self.maintenance_buttons=[]
        b=QPushButton('回退到上一安装版本');self.maintenance_buttons.append(b);b.clicked.connect(self.rollback);layout.addWidget(b);b.setVisible(not quick)
        b=QPushButton('卸载程序（保留配置与聊天记录）');self.maintenance_buttons.append(b);b.clicked.connect(self.uninstall);layout.addWidget(b);b.setVisible(not quick)
        self.job=None;self.exe=None
        if maintenance:
            self.install_button.hide();self.status.setText('白龙桌宠 '+VERSION+' · 轻量维护\n可回退或卸载；升级请运行下载的一键部署程序。\n设置、聊天记录与账号数据保存在独立用户目录。')
            self.move_button=QPushButton('迁移程序目录');self.move_button.clicked.connect(self.move_location);layout.addWidget(self.move_button);self.maintenance_buttons.append(self.move_button)
        if quick:
            if self.existing:
                self.status.setText('正在准备一键部署 '+VERSION+'…\n将沿用现有安装位置，已有设置和记录保留。')
                self.install_button.setEnabled(False);QTimer.singleShot(0,self.start)
            else:self.status.setText('选择程序安装位置，然后安装并启动。');self.install_button.setText('安装并启动')
    def choose_location(self):
        chosen=QFileDialog.getExistingDirectory(self,'选择程序安装位置',str(Path(self.location.text()).parent))
        if not chosen:return
        target=Path(chosen)
        if target.name.casefold()!='bailongenhanced':target=target/'BailongEnhanced'
        try:
            from storage_locations import destination
            destination(target,'program',self.current_root if self.maintenance else None)
            self.location.setText(str(target))
        except (OSError,ValueError) as exc:self.status.setText(str(exc))
    def move_location(self):
        target=Path(self.location.text())
        if target==self.current_root:self.status.setText('请先选择新的程序位置');return
        text='迁移程序、已安装的回退版本及安装备份到：\n'+str(target)+'\n\n校验成功后更新快捷方式与启动入口；关闭此维护窗口后清理原程序目录。设置、聊天和统计数据仍保存在用户数据目录。'
        if QMessageBox.question(self,'迁移程序目录',text)!=QMessageBox.StandardButton.Yes:return
        from program_location import ProgramMoveJob
        for button in self.maintenance_buttons:button.setEnabled(False)
        self.browse.setEnabled(False)
        self.job=ProgramMoveJob(self.current_root,target,self.startup.isChecked(),self)
        self.job.progress.connect(self.status.setText);self.job.failed.connect(self.failed)
        self.job.done.connect(self.moved);self.job.start()
    def moved(self,exe):
        self.exe=exe;self.status.setText('迁移完成，程序已从新位置启动。关闭此窗口后清理原程序目录。')
        self.install_button.show();self.install_button.setText('关闭');self.install_button.setEnabled(True)
        self.install_button.clicked.disconnect();self.install_button.clicked.connect(self.close)
    def start(self):
        if self.job and self.job.isRunning():return
        payload=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'payload.zip'
        if not payload.exists():self.status.setText('缺少安装载荷，请使用完整安装程序。');return
        for button in self.maintenance_buttons:button.setEnabled(False)
        self.install_button.setEnabled(False);self.status.setText('正在解压程序与素材，请稍等…')
        from storage_locations import destination
        target=Path(self.location.text())
        if target!=ROOT:
            try:destination(target,'program')
            except (OSError,ValueError) as exc:self.failed(str(exc));return
        self.browse.setEnabled(False)
        self.job=InstallJob(payload,self.startup.isChecked(),self,quick=self.quick,root=target);self.job.progress.connect(self.status.setText);self.job.done.connect(self.finished);self.job.failed.connect(self.failed);self.job.start()
    def finished(self,exe):
        for button in self.maintenance_buttons:button.setEnabled(True)
        if self.quick:
            self.exe=exe;self.status.setText('部署完成，桌宠已启动。\nCodex 将由桌宠自动识别，无需重启 Codex。\n本窗口即将自动关闭；可从 Windows 应用列表进入安装管理。')
            self.install_button.setText('关闭');self.install_button.setEnabled(True);self.install_button.clicked.disconnect();self.install_button.clicked.connect(self.close)
            QTimer.singleShot(4000,self.close);return
        self.exe=exe;self.status.setText('安装完成，已确认桌宠窗口与本地服务就绪。\n程序：'+exe)
        self.install_button.setText('显示桌宠');self.install_button.setEnabled(True);self.install_button.clicked.disconnect();self.install_button.clicked.connect(lambda:os.startfile(self.exe))
    def failed(self,message):
        for button in self.maintenance_buttons:button.setEnabled(True)
        self.install_button.setEnabled(True);self.install_button.setText('重试部署' if self.quick else '安装 / 升级');self.status.setText('安装失败：'+message)
        self.browse.setEnabled(self.maintenance or not self.existing)
    def maintenance_lock(self,allow_uninstall=False):
        if self.job and self.job.isRunning():raise OSError('安装正在运行，请等待完成')
        if not allow_uninstall and (ROOT/'uninstall-pending.json').exists():raise OSError('卸载尚未结束，请先关闭维护窗口')
        DATA.mkdir(parents=True,exist_ok=True);lock=QLockFile(str(DATA/'deployment.lock'))
        if not lock.tryLock(0):raise OSError('另一个维护操作正在运行，请稍后重试')
        return lock
    def rollback(self):
        lock=None;snapshot=None
        try:
            lock=self.maintenance_lock()
            from deployment_state import recover,capture_entries
            recover(ROOT,True);snapshot=capture_entries(ROOT,True)
            m=read_manifest();others=[v for v in m['versions'] if v!=m['current']]
            if not others:self.status.setText('当前没有上一安装版本。工作目录中的源码版仍保留。');return
            folder=checked_version(ROOT,others[0])
            from shared_assets import verify_version
            from deployment_state import verify_payload
            verify_version(folder,m.get('sharedAssets',{}).get(others[0]));verify_payload(folder,others[0].split('-')[0])
            from deployment_state import atomic
            atomic(ROOT/'maintenance-journal.json',dict(operation='rollback',snapshot=snapshot))
            register(folder/'BailongEnhanced.exe',folder/'BailongEnhanced.exe',self.startup.isChecked())
            m['current']=others[0];write_manifest(m)
            (ROOT/'maintenance-journal.json').unlink(missing_ok=True)
            self.status.setText('已回退快捷方式到 '+others[0]+'。退出正在运行的桌宠后重新打开。')
        except (OSError,ValueError) as error:
            if snapshot:
                from deployment_state import restore_entries
                try:
                    restore_entries(ROOT,snapshot,True)
                    (ROOT/'maintenance-journal.json').unlink(missing_ok=True)
                except (OSError,ValueError) as restore_error:error=OSError(str(error)+'；入口恢复失败：'+str(restore_error))
            self.status.setText('回退失败：'+str(error))
        finally:
            if lock:lock.unlock()
    def uninstall(self):
        if QMessageBox.question(self,'卸载白龙','卸载所有已安装的白龙版本？配置、角色包和聊天记录会保留。')!=QMessageBox.StandardButton.Yes:return
        lock=None
        try:
            lock=self.maintenance_lock(allow_uninstall=True)
            from storage_locations import plain,registered_install_root,MARKER
            expected=plain(ROOT);registered=registered_install_root()
            default=Path(os.environ['LOCALAPPDATA'])/'Programs/BailongEnhanced'
            marker={}
            try:marker=json.loads((ROOT/MARKER).read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
            if expected not in (default.resolve(),registered.resolve() if registered else None) and marker.get('kind')!='program':raise OSError('安装目录校验失败')
            from deployment_state import recover
            recover(ROOT,True)
            from codex_startup import configure,stop_watchers
            configure(False);stop_watchers(ROOT)
            m=read_manifest()
            # Close the app through its local control socket, never unrelated Python/Codex processes.
            from deployment_state import owned_destination
            active=owned_destination(ROOT,m['current']) if m['current'] else None
            if active and not (active/'BailongEnhanced.exe').exists():active=None
            if active:
                subprocess.run([str(active/'BailongEnhanced.exe'),'--quit'],timeout=20,creationflags=0x08000000)
            # Keep our running maintenance version until process exit; other versions can be removed.
            current_exe=Path(sys.executable).resolve()
            for version in list(m['versions']):
                folder=owned_destination(ROOT,version)
                if not current_exe.is_relative_to(folder):
                    if folder.exists():shutil.rmtree(folder)
                    m['versions'].remove(version);m.get('sharedAssets',{}).pop(version,None)
                    if m.get('current')==version:m['current']=''
                    write_manifest(m)
            startup=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup'
            for name in ('BailongEnhanced.vbs','白龙桌宠增强版.lnk'):
                path=startup/name
                if path.exists():path.unlink()
            script="$s=New-Object -ComObject WScript.Shell\n$paths=@((Join-Path ([Environment]::GetFolderPath('Desktop')) '白龙桌宠增强版.lnk'),(Join-Path ([Environment]::GetFolderPath('Desktop')) '白龙桌宠.lnk'),(Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\\白龙桌宠增强版.lnk'))\nforeach($p in $paths){if(Test-Path -LiteralPath $p){$l=$s.CreateShortcut($p);if($l.TargetPath.StartsWith("+ps_string(ROOT)+",[StringComparison]::OrdinalIgnoreCase)){Remove-Item -LiteralPath $p}}}"
            subprocess.run(['powershell.exe','-NoProfile','-Command',script],creationflags=0x08000000,capture_output=True)
            import winreg
            try:winreg.DeleteKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Uninstall\BailongEnhanced')
            except FileNotFoundError:pass
            # Cleanup waits for this maintenance process to exit. Its target is the
            # exact per-user install root, with the config directory outside it.
            from deployment_state import atomic
            atomic(ROOT/'uninstall-pending.json',dict(operation='uninstall',pid=os.getpid()))
            script='$ErrorActionPreference="Stop"; Wait-Process -Id '+str(os.getpid())+' -ErrorAction SilentlyContinue; $target='+ps_string(ROOT.resolve())+'; if([IO.Path]::GetFullPath($target) -eq '+ps_string(expected.resolve())+'){Remove-Item -LiteralPath $target -Recurse -Force}'
            encoded=__import__('base64').b64encode(script.encode('utf-16-le')).decode()
            subprocess.Popen(['powershell.exe','-NoProfile','-WindowStyle','Hidden','-EncodedCommand',encoded],creationflags=0x08000000)
            self.status.setText('卸载完成。关闭此窗口后清理剩余安装文件；设置、角色包和对话已保留。')
            self.install_button.setEnabled(False)
            for button in self.maintenance_buttons:button.setEnabled(False)
        except (OSError,ValueError,subprocess.SubprocessError) as error:self.status.setText('卸载未完成，可重试：'+str(error))
        finally:
            if lock:lock.unlock()
    def closeEvent(self,event):
        if self.job and self.job.isRunning():event.ignore()
        else:event.accept()

def maintenance_main():
    app=QApplication.instance() or QApplication(sys.argv);app.setQuitOnLastWindowClosed(True)
    window=Installer(maintenance=True);window.show()
    if '--maintenance-smoke' in sys.argv:
        index=sys.argv.index('--maintenance-smoke')
        def record():
            output=Path(sys.argv[index+1]);output.write_text(json.dumps(dict(passed=window.isVisible(),version=VERSION,maintenance=True,installButtonHidden=not window.install_button.isVisible(),payloadPresent=(Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'payload.zip').exists())),encoding='utf-8');window.close()
        QTimer.singleShot(300,record)
    return app.exec()

if __name__=='__main__':
    app=QApplication(sys.argv);window=Installer(quick_mode(sys.argv[1:],sys.executable));window.show();sys.exit(app.exec())
