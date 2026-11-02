"""One background update operation, explicit installation, and silent periodic checks."""
import threading,time
import app_updates
from PySide6.QtCore import QObject,QThread,QTimer,Signal
from app_updates import check_release,stage_installer,version_tuple,prune_completed,UpdateError,UpdateCancelled,NoRelease,ensure_checksum

class UpdateJob(QThread):
    result=Signal(object);failed=Signal(str,str);progress=Signal(int,int,str);selected=Signal(object)
    def __init__(self,current,cache,release=None,parent=None,program_version=None):
        super().__init__(parent);self.current=current;self.cache=cache;self.release=release;self.cancel=threading.Event();self.program_version=program_version or current
    def run(self):
        """后台检查与暂存按当前平台筛选，程序包不能经动画路径安装"""
        try:
            if self.release is None:
                prune_completed(self.cache,self.current);value=check_release(self.current,cancel=self.cancel.is_set,state_dir=self.cache.parent,program_version=self.program_version,allow_program=app_updates.program_updates_supported())
            else:
                if self.release.kind!='animation' and not app_updates.program_updates_supported():raise UpdateError('当前平台不支持 Windows 程序更新，请手动更新程序')
                if self.release.kind=='animation' and version_tuple(self.program_version)<version_tuple(self.release.minimum_program_version):raise UpdateError('请先手动更新程序，再安装此动画补丁')
                last=[0.,None]
                def progress(n,total,phase):
                    now=time.monotonic()
                    if phase!=last[1] or now-last[0]>=.12 or n==total:
                        last[:]=[now,phase];self.progress.emit(n,total,phase)
                if self.release.animation_catalog:
                    from animation_updates import stage
                    from pet import ROOT
                    animation=stage(self.release,ROOT,self.cache.parent,progress,self.cancel.is_set)
                if self.release.kind=='animation':value=animation
                elif self.release.kind=='program':
                    from program_updates import stage_program,MaterialMismatch
                    from pet import ROOT
                    try:value=stage_program(self.release,self.cache,ROOT,progress,self.cancel.is_set)
                    except MaterialMismatch:
                        if not self.release.fallback:raise UpdateError('本地素材发生变化，且该版本未提供完整包')
                        from dataclasses import replace
                        self.release=ensure_checksum(replace(self.release.fallback,reason='素材在检查后变化，改用完整安装包'),cancel=self.cancel.is_set)
                        self.selected.emit(self.release);value=stage_installer(self.release,self.cache,progress,self.cancel.is_set)
                else:value=stage_installer(self.release,self.cache,progress,self.cancel.is_set)
            if not self.cancel.is_set():self.result.emit(value)
            else:self.failed.emit('cancelled','下载已暂停，可稍后继续')
        except UpdateCancelled as exc:self.failed.emit('cancelled',str(exc))
        except NoRelease as exc:self.failed.emit('none',str(exc))
        except UpdateError as exc:self.failed.emit('error',str(exc))
        except Exception:self.failed.emit('error','更新暂不可用，请稍后重试')

class UpdateController(QObject):
    changed=Signal(object);installerReady=Signal(str);animationReady=Signal(object);idle=Signal()
    def __init__(self,current,cache,parent=None,allow_auto=True):
        from animation_updates import effective_version
        super().__init__(parent);self.program_version=current;self.current=effective_version(current,cache.parent);self.cache=cache;self.allow_auto=allow_auto;self.release=None;self.job=None;self.closing=False;self.enabled=False;self.install_requested=False
        current=self.current
        self.state=dict(phase='idle',message='点击检查 GitHub 公开稳定版' if app_updates.program_updates_supported() else '点击检查可用的动画补丁',program_supported=app_updates.program_updates_supported(),current=current,latest='',notes='',downloaded=0,total=0,checked=0)
        self.timer=QTimer(self);self.timer.setInterval(6*3600*1000);self.timer.timeout.connect(self._automatic)
        self.initial=QTimer(self);self.initial.setSingleShot(True);self.initial.setInterval(15000);self.initial.timeout.connect(self._automatic)
        self.cleanup_timer=QTimer(self);self.cleanup_timer.setSingleShot(True);self.cleanup_timer.setInterval(60000);self.cleanup_timer.timeout.connect(self.cleanup)
        if allow_auto:self.cleanup();self.cleanup_timer.start()
    def cleanup(self):
        if not self.closing:threading.Thread(target=prune_completed,args=(self.cache,self.current),name='BailongUpdateCleanup',daemon=True).start()
    def snapshot(self):return dict(self.state)
    def publish(self,**changes):self.state.update(changes);self.changed.emit(self.snapshot())
    def configure(self,enabled):
        enabled=bool(enabled) and self.allow_auto and not self.closing
        if enabled and not self.enabled:self.initial.start();self.timer.start()
        elif not enabled:self.initial.stop();self.timer.stop()
        self.enabled=enabled
    def _automatic(self):
        if self.enabled:self.check()
    def _bind(self,job):
        self.job=job;job.result.connect(self._result);job.failed.connect(self._failed);job.progress.connect(self._progress);job.selected.connect(self._selected);job.finished.connect(self._finished);self.changed.emit(self.snapshot());job.start()
    def _selected(self,release):
        self.release=release;self.publish(package_kind=release.kind,package_animation=bool(release.animation_info_url),package_reason=release.reason,total=release.size,downloaded=0,message=release.reason)
    def check(self):
        if self.closing or self.job is not None or self.state['phase']=='pending':return False
        self.publish(phase='checking',message='正在检查公开稳定版…')
        self._bind(UpdateJob(self.current,self.cache,parent=self,program_version=self.program_version));return True
    def download_install(self):
        """只为当前平台可安装的附件启动下载，自动检查开关不代替平台限制"""
        if self.closing or self.job is not None or self.state['phase']=='pending' or self.release is None or version_tuple(self.release.version)<=version_tuple(self.current):return False
        if self.release.kind!='animation' and not app_updates.program_updates_supported():
            self.install_failed('当前平台不支持 Windows 程序更新，请手动更新程序');return False
        self.install_requested=True;self.publish(phase='downloading',message='正在准备下载…',total=self.release.size)
        self._bind(UpdateJob(self.current,self.cache,self.release,parent=self,program_version=self.program_version));return True
    def cancel(self):
        self.install_requested=False
        if self.job:
            self.job.cancel.set();self.publish(message='正在暂停，已下载的内容会保留…')
    def _result(self,value):
        """检查结果和下载结果都须符合平台能力，才能显示或触发安装"""
        if self.closing:return
        release=value if self.job.release is None else self.release
        if release.kind!='animation' and not app_updates.program_updates_supported():
            self.install_failed('当前平台不支持 Windows 程序更新，请手动更新程序');return
        if self.job.release is None:
            if self.state.get('latest')!=value.version:self.state['downloaded']=0
            self.release=value;cmp=(version_tuple(value.version)>version_tuple(self.current))-(version_tuple(value.version)<version_tuple(self.current))
            message='发现新版本，可查看说明后下载并安装' if cmp>0 else '已是最新公开版本' if cmp==0 else '本机版本较新，公开稳定版为 '+value.version
            self.publish(phase='available' if cmp>0 else 'current',message=message,latest=value.version,notes=value.notes,total=value.size,checked=time.time(),url=value.url,package_kind=value.kind,package_animation=bool(value.animation_info_url),package_reason=value.reason)
        else:
            if self.release.kind=='animation':
                self.publish(phase='pending',message='动画补丁已校验，等待当前动作结束后切换…')
                if self.install_requested:self.animationReady.emit(value)
                return
            self.publish(phase='ready',message='校验通过，正在启动安装器…')
            if self.install_requested:self.installerReady.emit(str(value))
    def _failed(self,phase,message):
        if phase=='none':self.release=None;self.state.update(latest='',notes='',total=0,url='')
        if not self.closing:self.publish(phase=phase,message=message,checked=time.time())
    def _progress(self,n,total,phase):
        if self.closing or self.job and self.job.cancel.is_set():return
        messages={'materials':'正在校验可复用的本地素材…','downloading':'正在下载更新包…','verifying':'下载完成，正在校验…','extracting':'正在准备程序与本地素材…','ready':'安装程序已就绪'}
        self.publish(phase=phase,message=messages[phase],downloaded=n,total=total)
    def _finished(self):
        job=self.job;self.job=None
        if job:job.deleteLater()
        self.changed.emit(self.snapshot());self.idle.emit()
    def installing(self):self.publish(phase='installing',message='安装器已启动，将关闭桌宠并完成升级')
    def install_failed(self,message):self.install_requested=False;self.publish(phase='error',message=message)
    def animation_applied(self,ready):
        self.current=max((self.program_version,ready['release'].version),key=version_tuple);self.install_requested=False
        self.publish(phase='current',current=self.current,latest=self.current,total=0,downloaded=0,message='动画资源已切换，上一套资源仍保留，可在素材设置回退')
    def rollback_animation(self,previous):
        if self.closing or self.job or self.state['phase']=='pending' or not previous:return False
        from app_updates import Release
        try:
            value=previous['version'];catalog=previous['catalog'];version_tuple(value);version_tuple(previous['minimumProgramVersion'])
            if not isinstance(catalog,dict):raise ValueError('catalog')
        except (TypeError,KeyError,ValueError,UpdateError):
            self.install_failed('上一套动画的回退记录不完整');return False
        self.release=Release(value,'v'+value,'','',0,'',kind='animation',animation_catalog=catalog,minimum_program_version=previous['minimumProgramVersion'],reason='animation-rollback')
        self.install_requested=True;self.publish(phase='materials',message='正在准备上一套动画资源…')
        self._bind(UpdateJob(self.current,self.cache,self.release,parent=self,program_version=self.program_version));return True
    def shutdown(self):
        self.closing=True;self.initial.stop();self.timer.stop();self.cleanup_timer.stop();self.install_requested=False
        if self.job:self.job.cancel.set();return False
        return True
