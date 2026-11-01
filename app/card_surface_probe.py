"""Real Qt/native card routes, isolated synthetic data; no external services."""
import json,time
from pathlib import Path
from PySide6.QtCore import QObject,QEvent,QTimer,QRect,Qt
from PySide6.QtWidgets import QApplication,QWidget,QToolButton

def sample():
    return dict(total=12000000,month='2026-10',history_days={},hours=[10000+i*8000 for i in range(24)],
        report=dict(day='2026-10-20',sessions=24,messages=80,active_days=7,all_total=12000000,yesterday_total=1680000,favorite_model='demo-model',peak_hour=15,
                    hours=[20000+(i%6)*20000 for i in range(24)],total=1000000,daily_models=[]))

def run(destination):
    from desktop import DesktopPet
    from desktop_core import VERSION
    from typography import install_ui_font
    app=QApplication.instance() or QApplication([]);install_ui_font(app);app.setQuitOnLastWindowClosed(False)
    p=DesktopPet(monitor=False);p.apply_settings(dict(wandering=False,random_actions=False,self_talk=False,video_fullscreen_yield=False,update_checks=False))
    backdrop=QWidget(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint);backdrop.setStyleSheet('background:#182436;');backdrop.setGeometry(app.primaryScreen().availableGeometry());backdrop.show();backdrop.lower()
    p.update_quota([dict(name='一周',remaining=73,resetsAt=time.time()+86400)],time.time(),'demo')
    b=p.bubble;b.set_mode('auto');b.size_transition.complete();app.processEvents()
    b.token_snapshot=sample();b.redraw();b.move(150,650)
    from daily_report import DailyReport
    r=DailyReport(b);b.report=r;r.set_snapshot(sample())
    folder=Path(destination).parent;folder.mkdir(parents=True,exist_ok=True)
    checks={};frames=[];started=time.monotonic();route=0;launched=False;seen=False;frame_index=0;preparation_exposures=0;native_events=[];previous_report=None;pixel_samples=[];native_report=None
    routes=[('to_mini',lambda:b.set_mode('mini')),('to_normal',lambda:b.set_mode('auto')),('reuse_mini',lambda:b.set_mode('mini')),('reuse_normal',lambda:b.set_mode('auto')),
            ('to_minimal',lambda:b.set_mode('minimal')),('minimal_normal',lambda:b.set_mode('auto')),('report_open',r.open),
            ('status_expand',lambda:b.status_view.set_status('正在分析并编辑较长的测试内容，检查日报是否随着正常卡片高度连续变化。'*2)),('status_shrink',lambda:b.status_view.set_status('正在思考')),
            ('report_models',lambda:r.set_page('models')),('report_cycle',lambda:r.set_page('cycle')),('report_overview',lambda:r.set_page('overview')),
            ('report_to_capsule',lambda:b.set_mode('mini')),('capsule_report_open',r.open),('capsule_report_models',lambda:r.set_page('models')),
            ('capsule_report_cycle',lambda:r.set_page('cycle')),('capsule_report_overview',lambda:r.set_page('overview')),
            ('report_to_minimal',lambda:b.set_mode('minimal')),('minimal_report_open',r.open),('minimal_report_models',lambda:r.set_page('models')),
            ('minimal_report_normal',lambda:b.set_mode('auto')),('normal_report_reopen',r.open),
            ('details_report',b.toggle_details),('normal_report',b.toggle_details),('report_close',r.dismiss),
            ('quota_alert_open',p.open_quota_comparison),('quota_alert_models',lambda:r.set_page('models')),
            ('quota_alert_cycle',p.open_quota_comparison),('quota_alert_close',r.dismiss),
            ('details_editor',b.toggle_details),('chat_editor',p.open_chat),('settings_editor',p.open_settings),('status_editor',b.return_to_status)]
    class Recorder(QObject):
        def eventFilter(self,obj,event):
            nonlocal preparation_exposures
            if event.type()==QEvent.Type.Paint and b.size_transition.preparing and obj is not b and isinstance(obj,QWidget) and b.content.isAncestorOf(obj) and obj.isVisible():preparation_exposures+=1
            if obj is b and event.type() in (QEvent.Type.Resize,QEvent.Type.Move) and b.size_transition.target_rect is not None:
                t=b.size_transition
                native_events.append(dict(type=event.type().name,updates=b.updatesEnabled(),preparing=t.preparing,active=t.active,opacity=b.windowOpacity(),progress=t.raw_progress))
                if t.canvas_morph and t.raw_progress==0. and app.platformName()=='windows':
                    checks['nativeCanvasHiddenUntilFirstPaint']=checks.get('nativeCanvasHiddenUntilFirstPaint',True) and b.windowOpacity()==0. and t.landing.image is not None
            if obj is r and event.type()==QEvent.Type.Show and app.platformName()=='windows':
                checks['reportNativeShowStartsInvisible']=checks.get('reportNativeShowStartsInvisible',True) and r.windowOpacity()==0.
            t=b.size_transition
            if obj is t.cover and event.type() in (QEvent.Type.Move,QEvent.Type.Paint) and t.same_size_fade and t.cover.isVisible():
                nav=b.layout.itemAt(1).widget()
                checks['bodyNeverOverlapsHeaderAtHandoff']=checks.get('bodyNeverOverlapsHeaderAtHandoff',True) and t.cover.y()>nav.geometry().bottom()
            return False
    recorder=Recorder();app.installEventFilter(recorder)
    def compositor_sample(surface,image,point,label):
        # Only sample known opaque pixels on our own card over our own solid
        # background. No desktop screenshot or external window is captured.
        import ctypes
        from ctypes import wintypes
        user=ctypes.WinDLL('user32');gdi=ctypes.WinDLL('gdi32');dwm=ctypes.WinDLL('dwmapi')
        user.GetDC.argtypes=[wintypes.HWND];user.GetDC.restype=wintypes.HDC;user.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC]
        user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)];gdi.GetPixel.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int];gdi.GetPixel.restype=wintypes.DWORD
        ratio=image.devicePixelRatioF();x,y=round(point[0]*ratio),round(point[1]*ratio);expected=image.toImage().pixelColor(x,y)
        if expected.alpha()<254:return
        location=wintypes.POINT(x,y);user.ClientToScreen(int(surface.winId()),ctypes.byref(location));dwm.DwmFlush()
        dc=user.GetDC(0)
        try:pixel=gdi.GetPixel(dc,location.x,location.y)
        finally:user.ReleaseDC(0,dc)
        actual=[pixel&255,(pixel>>8)&255,(pixel>>16)&255];wanted=[expected.red(),expected.green(),expected.blue()]
        pixel_samples.append(dict(route=label,progress=round(r.follow.progress,4),error=max(abs(a-z) for a,z in zip(actual,wanted)),actual=actual,expected=wanted))
    def save(name):
        b.grab().save(str(folder/(name+'.png')))
        if r.isVisible():
            surface=r.follow.landing if r.follow.landing.image is not None else r
            surface.grab().save(str(folder/(name+'-report.png')))
    def finish(failure=None):
        timer.stop();checks['targetControlsNeverExposedDuringPreparation']=preparation_exposures==0
        checks['nativeGeometryChangesUpdatesDisabled']=all(not e['updates'] for e in native_events)
        checks['nativeReportPresentationPixels']=bool(pixel_samples) and max(s['error'] for s in pixel_samples)<=3
        result=dict(version=VERSION,passed=failure is None and all(checks.values()),error=failure,checks=checks,seconds=round(time.monotonic()-started,3),dpr=b.devicePixelRatioF(),nativePlatform=app.platformName(),realClock=True,
                    frames=frames,preparationExposures=preparation_exposures,nativeEvents=native_events,compositorSamples=pixel_samples,syntheticData=True,displayFrameRateMeasured=False)
        Path(destination).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');app.removeEventFilter(recorder);p.close();backdrop.close();app.exit(0 if result['passed'] else 1)
    def next_route():
        nonlocal route,launched,seen,previous_report,native_report
        route+=1;launched=False;seen=False;previous_report=None;native_report=None
    def tick():
        nonlocal route,launched,seen,frame_index,previous_report,native_report
        try:
            if time.monotonic()-started>35:finish('timeout');return
            if route==len(routes):
                p.apply_settings(dict(character_visible=False));p.pause_hidden_animation()
                checks['cardVisibleWithoutCharacter']=b.isVisible() and not p.isVisible() and b.parentWidget() is None
                checks['characterDecoderPaused']=not p.tick.isActive() and p.player.thread is None
                b.set_mode('minimal');route+=1;return
            if route>len(routes):
                if b.size_transition.running or b.size_transition.landing.image is not None:return
                checks['minimalSingleReadableControl']=b.size().width()==54 and b.size().height()==54 and [w.objectName() for w in b.findChildren(QToolButton) if w.isVisible()]==['minimal_quota']
                save('minimal-card-only');p.apply_settings(dict(character_visible=True));checks['characterRestores']=p.isVisible() and p.tick.isActive();finish();return
            name,action=routes[route]
            if not launched:action();launched=True;seen=False
            t=b.size_transition
            if r.follow.active and r.follow.status_tracking:
                seen=True;q=r.follow.geometry();host=b.geometry()
                checks['statusHeightReportAligned']=checks.get('statusHeightReportAligned',True) and abs(q.left()-host.left())<.6 and abs(q.width()-host.width())<.6 and abs(q.bottom()+r.GAP-host.top())<=1
                checks['statusHeightReportSuppressed']=checks.get('statusHeightReportSuppressed',True) and r.windowOpacity()==0.
                if native_report is None:native_report=QRect(r.geometry())
                checks['statusHeightNativeStable']=checks.get('statusHeightNativeStable',True) and r.geometry()==native_report
                relative=q.translated(-r.follow.canvas.x(),-r.follow.canvas.y());compositor_sample(r.follow.landing,r.follow.frame,(relative.center().x(),relative.top()+7),name)
                frames.append(dict(route=name,progress=round(r.follow.progress,4)));return
            if t.running:
                seen=True;geometry=t.visible_geometry();record=dict(route=name,at=round(time.monotonic()-started,3),progress=round(t.raw_progress,4),card=[geometry.x(),geometry.y(),geometry.width(),geometry.height()])
                if t.same_size_fade:
                    image=b.grab().toImage();ratio=image.devicePixelRatioF()
                    alpha=[image.pixelColor(round(x*ratio),round(y*ratio)).alpha() for x,y in ((0,b.height()-1),(b.width()-1,b.height()-1),(2,b.height()-3))]
                    checks['pageSlidesKeepRoundedCorners']=checks.get('pageSlidesKeepRoundedCorners',True) and all(a==0 for a in alpha)
                if r.follow.active and r.follow.committed:
                    host=t.morph.geometry(t.raw_progress);q=r.follow.geometry()
                    aligned=q.width()>=min(r.MIN_WIDTH,r.bubble.screen().availableGeometry().width()-2*r.PAD)-.6 and abs(q.center().x()-host.center().x())<1.1 and abs(q.bottom()+r.GAP-host.top())<=1
                    checks['reportAlignedEverySample']=checks.get('reportAlignedEverySample',True) and aligned
                    record['report']=[round(q.x(),2),round(q.y(),2),round(q.width(),2),round(q.height(),2)]
                    if previous_report:
                        old_report,old_host=previous_report
                        checks['reportStepFollowsHost']=checks.get('reportStepFollowsHost',True) and abs((q.bottom()-old_report.bottom())-(host.top()-old_host.top()))<=1
                    previous_report=(q,host)
                    if native_report is None:native_report=QRect(r.geometry())
                    checks['liveReportInvisibleDuringHostMotion']=checks.get('liveReportInvisibleDuringHostMotion',True) and r.windowOpacity()==0.
                    checks['liveReportNativeSizeStable']=checks.get('liveReportNativeSizeStable',True) and r.geometry()==native_report
                    relative=q.translated(-r.follow.canvas.x(),-r.follow.canvas.y())
                    compositor_sample(r.follow.landing,r.follow.frame,(relative.center().x(),relative.top()+7),name)
                if frame_index%5==0:save(name+'-'+str(frame_index))
                frames.append(record);frame_index+=1;return
            if r._animating:seen=True;return
            if r.page_fade.animation.state()==r.page_fade.animation.State.Running:
                seen=True
                frames.append(dict(route=name,progress=round(r.page_fade.progress,4)))
                if frame_index%2==0:save(name+'-'+str(frame_index))
                frame_index+=1;return
            if t.landing.image is not None or r.follow.landing.image is not None:return
            if seen:
                checks[name]=True;save(name+'-end')
                checks['mainOpacityRestored']=checks.get('mainOpacityRestored',True) and b.windowOpacity()==1.
                if name in ('details_editor','chat_editor','settings_editor','status_editor'):
                    checks['sharedEditorSize']=checks.get('sharedEditorSize',True) and b.width()==360 and b.height()==480
                if name in ('details_report','normal_report'):
                    compositor_sample(r,r.grab(),(r.width()/2,r.PAD+7),name+'-live')
                    checks['liveReportOpacityRestored']=checks.get('liveReportOpacityRestored',True) and r.windowOpacity()==1.
                next_route()
        except Exception as problem:finish(type(problem).__name__+': '+str(problem))
    timer=QTimer();timer.timeout.connect(tick);timer.start(16);return app.exec()
