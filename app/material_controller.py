"""Explicit background material operations and embedded settings controls."""
from theme_runtime import set_theme_style,theme_style_source
import threading,time
from PySide6.QtCore import QObject,QThread,QTimer,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QProgressBar,QFileDialog,QMessageBox,QSizePolicy
from pathlib import Path
from material_store import MaterialError
from app_updates import UpdateCancelled

class MaterialJob(QThread):
    result=Signal(str,object);failed=Signal(str);progress=Signal(int,int,str)
    def __init__(self,store,tier,parent=None):
        super().__init__(parent);self.store=store;self.tier=tier;self.cancel=threading.Event()
    def run(self):
        last=[0.]
        def progress(n,t,p):
            now=time.monotonic()
            if now-last[0]>=.12 or n==t:
                last[0]=now;self.progress.emit(n,t,p)
        try:
            root=self.store.ensure(self.tier,self.cancel.is_set,progress)
            if not self.cancel.is_set():self.result.emit(self.tier,root)
        except (MaterialError,UpdateCancelled,OSError,ValueError) as exc:self.failed.emit(str(exc)[:220])
        except Exception:self.failed.emit('素材准备失败，继续使用原画质')

class MaterialController(QObject):
    changed=Signal(object);ready=Signal(str,object);idle=Signal();removeRequested=Signal();rollbackRequested=Signal()
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.job=None;self.closing=False
        self.state=dict(phase='idle',message='',downloaded=0,total=0)
    def snapshot(self):
        return dict(self.state,current=self.store.current,lightCached=self.store.known_available('light'),hdCached=self.store.known_available('hd'),supported=bool(self.store.catalog),busy=self.job is not None,canRollback=bool(self.store.patch_previous),storagePath=str(self.store.cache),locationError=getattr(self.store,'location_error',''))
    def publish(self,**changes):self.state.update(changes);self.changed.emit(self.snapshot())
    def request(self,tier):
        if getattr(self.store,'location_error',''):self.failed(self.store.location_error);return False
        updates=getattr(self.parent(),'updates',None)
        if updates and (updates.job or updates.state['phase']=='pending'):self.publish(message='请先完成当前更新');return False
        if self.closing or self.job or self.state['phase']=='pending' or tier not in ('light','hd'):return False
        if tier==self.store.current and self.store.known_available(tier):self.publish(message='当前已使用所选画质');return False
        self.publish(phase='verifying' if self.store.known_available(tier) else 'downloading',message='正在准备素材…',downloaded=0,total=0)
        job=self.job=MaterialJob(self.store,tier,self);job.result.connect(self._result);job.failed.connect(lambda text:self.publish(phase='error',message=text));job.progress.connect(self._progress);job.finished.connect(self._finished);self.changed.emit(self.snapshot());job.start();return True
    def _progress(self,n,total,phase):
        if not self.closing:self.publish(phase=phase,downloaded=n,total=total,message='正在下载动画资源…' if phase=='downloading' else '正在复用已有动画…' if phase=='reusing' else '正在迁移并校验动画…' if phase=='moving' else '正在校验素材…')
    def _result(self,tier,root):
        if self.closing or self.job.cancel.is_set():return
        self.publish(phase='pending',message='素材已就绪，等待当前动作自然结束后切换…');self.ready.emit(tier,root)
    def applied(self):
        if getattr(self,'_move_plan',None):
            self._cleanup_plan=self._move_plan;self._move_plan=None;self._move_restore=None
            self.publish(phase='pending',message='新动画目录已启用，正在清理原缓存…')
            if not self.job:self._start_location_cleanup()
        else:self.publish(phase='idle',message='画质已切换，原动画与 Codex 联动继续保留')
    def move_location(self,target):
        updates=getattr(self.parent(),'updates',None)
        if self.closing or self.job or self.state['phase']=='pending' or updates and (updates.job or updates.state['phase']=='pending'):return False
        from storage_locations import destination
        try:target=destination(target,'materials',self.store.cache)
        except (OSError,ValueError) as exc:self.failed(str(exc));return False
        job=self.job=MaterialMoveJob(self.store.cache,target,self)
        job.result.connect(self._location_ready);job.failed.connect(self.failed);job.progress.connect(self._progress);job.finished.connect(self._finished)
        self.publish(phase='moving',message='正在迁移并校验动画资源…',downloaded=0,total=0);job.start();return True
    def _location_ready(self,plan):
        if self.closing or self.job and self.job.cancel.is_set():return
        from storage_locations import save_material_root
        old=self.store.cache;old_root=self.store.root
        try:
            save_material_root(self.store.state,plan['target'])
            self._move_restore=(old,old_root);self._move_plan=plan
            self.store.cache=Path(plan['target']);self.store.location_error=''
            tier=self.store.current
            if tier and old_root.is_relative_to(old):
                target=self.store.cache/old_root.relative_to(old)
                if getattr(self.parent(),'settings',{}).get('character','builtin')=='builtin':
                    self.publish(phase='pending',message='目录已校验，等待当前动作结束后切换…');self.ready.emit(tier,target);return
                self.store.root=target
            self.applied()
        except (OSError,ValueError) as exc:self.failed(str(exc))
    def _start_location_cleanup(self):
        plan=getattr(self,'_cleanup_plan',None)
        if not plan:return
        self._cleanup_plan=None
        job=self.job=MaterialCleanupJob(plan,self)
        job.done.connect(lambda clean:self.publish(phase='idle',message='动画目录已迁移，原缓存已清理' if clean else '动画目录已迁移，原目录剩余文件已保留'))
        job.failed.connect(lambda text:self.publish(phase='idle',message='新目录已启用，原缓存暂未清理：'+text))
        job.finished.connect(self._finished);self.publish(phase='removing',message='正在清理已迁移的原缓存…');job.start()
    def remove(self,plan):
        if self.job:return False
        job=self.job=RemovalJob(self.store,plan,self)
        job.done.connect(lambda:self.publish(phase='idle',message='动画资源已移除，仅保留卡片'))
        job.failed.connect(self.failed);job.finished.connect(self._finished)
        self.publish(phase='removing',message='正在移除动画资源…');job.start();return True
    def failed(self,text):
        restore=getattr(self,'_move_restore',None)
        if restore:
            from storage_locations import save_material_root
            self.store.cache,self.store.root=restore;save_material_root(self.store.state,self.store.cache)
            self._move_restore=None;self._move_plan=None
        self.publish(phase='error',message=str(text)[:220])
    def _finished(self):
        job=self.job;self.job=None
        if job:
            if job.cancel.is_set() and not self.closing:self.publish(phase='idle',message='已取消，继续使用原画质')
            job.deleteLater()
        if getattr(self,'_cleanup_plan',None):self._start_location_cleanup()
        self.changed.emit(self.snapshot());self.idle.emit()
    def cancel(self):
        if self.job:self.job.cancel.set();self.publish(message='正在取消素材操作…')
    def shutdown(self):
        self.closing=True
        if self.job:self.job.cancel.set();return False
        return True

class RemovalJob(QThread):
    done=Signal();failed=Signal(str)
    def __init__(self,store,plan,parent=None):
        super().__init__(parent);self.store=store;self.plan=plan;self.cancel=threading.Event()
    def run(self):
        from material_removal import remove_animations
        try:remove_animations(self.store,self.plan);self.done.emit()
        except (OSError,ValueError) as exc:self.failed.emit('移除未完成，卡片继续可用：'+str(exc)[:150])

class MaterialMoveJob(QThread):
    result=Signal(object);failed=Signal(str);progress=Signal(object,object,str)
    def __init__(self,source,target,parent=None):
        super().__init__(parent);self.source=source;self.target=target;self.cancel=threading.Event()
    def run(self):
        from storage_locations import copy_tree
        last=[0.]
        def progress(n,total,phase):
            if time.monotonic()-last[0]>=.12 or n==total:last[0]=time.monotonic();self.progress.emit(n,total,phase)
        try:self.result.emit(copy_tree(self.source,self.target,'materials',self.cancel.is_set,progress))
        except (OSError,ValueError) as exc:self.failed.emit(str(exc)[:220])

class MaterialCleanupJob(QThread):
    done=Signal(bool);failed=Signal(str)
    def __init__(self,plan,parent=None):super().__init__(parent);self.plan=plan;self.cancel=threading.Event()
    def run(self):
        from storage_locations import clean_source
        try:self.done.emit(clean_source(self.plan))
        except (OSError,ValueError) as exc:self.failed.emit(str(exc)[:150])

class MaterialPanel(QWidget):
    def __init__(self,controller,parent=None):
        super().__init__(parent);self.controller=controller
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.rollback=QPushButton('回退动画补丁');self.rollback.clicked.connect(controller.rollbackRequested.emit);layout.addWidget(self.rollback)
        from settings_controls import SlidingSegments
        row=QHBoxLayout();self.choice=SlidingSegments([('轻量 512px','light'),('高清 720px','hd')]);row.addWidget(self.choice,1)
        self.action=QPushButton();row.addWidget(self.action);self.cancel_button=QPushButton('取消');row.addWidget(self.cancel_button);layout.addLayout(row)
        self.progress=QProgressBar();self.progress.setRange(0,1000);layout.addWidget(self.progress)
        self.message=QLabel();self.message.setWordWrap(True);layout.addWidget(self.message)
        self.remove_button=QPushButton('移除动画资源，仅保留卡片');self.remove_button.setProperty('role','danger');layout.addWidget(self.remove_button)
        self.remove_button.clicked.connect(controller.removeRequested.emit)
        note=QLabel('动画按需下载，升级可复用；移除后可重新下载。');note.setWordWrap(True);set_theme_style(note,'font-size:11px;font-weight:500;color:#706879;');layout.addWidget(note)
        location=QHBoxLayout();self.storage_path=QLabel();self.storage_path.setWordWrap(True);self.storage_path.setMinimumWidth(0);self.storage_path.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);self.storage_path.setAccessibleName('动画资源存储位置');location.addWidget(self.storage_path,1)
        self.storage_button=QPushButton('更改位置');self.storage_button.clicked.connect(self.choose_location);location.addWidget(self.storage_button);layout.addLayout(location)
        self.choice.setCurrentIndex(max(0,self.choice.findData(controller.store.current)))
        self.choice.currentIndexChanged.connect(lambda:self.refresh(controller.snapshot()));self.action.clicked.connect(lambda:controller.request(self.choice.currentData()));self.cancel_button.clicked.connect(controller.cancel)
        controller.changed.connect(self.refresh);self.refresh(controller.snapshot())
    def choose_location(self):
        chosen=QFileDialog.getExistingDirectory(self,'选择动画资源位置',str(self.controller.store.cache.parent))
        if not chosen:return
        target=Path(chosen)
        if target.name!='BailongMaterials':target=target/'BailongMaterials'
        text='将已下载的内置动画迁移到：\n'+str(target)+'\n\n校验并切换成功后清理原缓存，之后的素材下载使用新目录。程序自带轻量素材随程序目录保存。'
        if QMessageBox.question(self,'迁移动画资源',text)==QMessageBox.StandardButton.Yes:self.controller.move_location(target)
    def refresh(self,s):
        self.rollback.setVisible(bool(s.get('canRollback')));self.rollback.setEnabled(not s['busy'])
        self.summary.setText('当前：'+({'hd':'高清 720px','light':'轻量 512px'}.get(s['current'],'仅卡片')))
        tier=self.choice.currentData();busy=s['busy'] or s['phase']=='pending'
        self.storage_path.setText(s['storagePath']);self.storage_button.setEnabled(not busy)
        self.choice.setEnabled(not busy);self.action.setEnabled(s['supported'] and not busy and tier!=s['current'])
        cached=s.get('hdCached' if tier=='hd' else 'lightCached',False)
        self.action.setText('下载并启用' if not cached else '启用动画' if s['current'] is None else '切换画质')
        self.remove_button.setEnabled(s['supported'] and not busy)
        self.cancel_button.setVisible(s['busy'] and s['phase'] not in ('pending','removing'));self.cancel_button.setEnabled(s['busy']);self.message.setText(s['message'] or s.get('locationError',''))
        self.progress.setVisible(s['busy'])
        total=s['total'];self.progress.setRange(0,1000 if total else 0)
        if total:self.progress.setValue(min(1000,round(s['downloaded']*1000/total)));self.progress.setFormat(f"{s['downloaded']/1048576:.1f} / {total/1048576:.1f} MB")
