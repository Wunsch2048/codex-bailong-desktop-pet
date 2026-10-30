"""Isolated native interaction acceptance for source and frozen builds.

Uses Win32 messages against this process's test HWND only. Does not move the
cursor, alter display scaling, start monitors, open Codex, or join its singleton.
"""
import ctypes,json,os,time
from pathlib import Path
from ctypes import wintypes as w

def run(output,material_root=None):
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt,QPointF,QRectF,QEvent
    from PySide6.QtGui import QPixmap,QImage,QPainter
    from desktop import DesktopPet
    from desktop_services import all_items
    from desktop_core import VERSION
    from native_coordinates import client_position
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    class ProbePet(DesktopPet):
        def context_menu(self,point):self.probe_menus+=1
    pet=ProbePet(monitor=False);pet.probe_menus=0;pet.tick.stop();pet.motion_timer.stop();pet.hide();pet.bubble.hide()
    if material_root is not None:
        if os.environ.get('BAILONG_ISOLATED')!='1':raise ValueError('素材验收仅允许隔离进程')
        from material_store import checked
        from sustained_assets import seam_items
        pet.asset_root=Path(material_root).resolve();pet.manifest=json.loads((pet.asset_root/'素材清单.json').read_text(encoding='utf-8'))
        # Asset decoding is checked separately once. DPI probes read actual
        # frame samples, without redundantly decoding every clip four times.
        for item in all_items(pet.manifest)+seam_items(pet.manifest):
            if not checked(pet.asset_root,item.get('playbackFile') or item['file']).is_file():raise ValueError('验收素材缺失')
        pet.idles=[pet.manifest['idle']]+pet.manifest.get('additionalIdleAnimations',[]);pet.variants=pet.manifest.get('variants',[])
        pet._materials_missing=False;pet.reactions.set_actions(x['id'] for x in all_items(pet.manifest));pet.gate.state='idle';pet.idle()
    pet.apply_settings(dict(wandering=False,random_actions=False,on_top=False,sound=False,drag_physics=False,no_move=False,mouse_through=False),save=False)
    pet.show();pet.bubble.hide();app.processEvents()
    u=ctypes.WinDLL('user32',use_last_error=True)
    u.ClientToScreen.argtypes=[w.HWND,ctypes.POINTER(w.POINT)];u.ClientToScreen.restype=w.BOOL
    u.GetClientRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)];u.GetClientRect.restype=w.BOOL
    u.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.SendMessageW.restype=ctypes.c_ssize_t
    hwnd=int(pet.winId());rect=w.RECT();assert u.GetClientRect(hwnd,ctypes.byref(rect))
    pw,ph=rect.right,rect.bottom
    records=[];painted=0;body=0;clear=0
    def packed(x,y):return (x&0xffff)|((y&0xffff)<<16)
    def native_hit(x,y):
        p=w.POINT(round(x*pw/pet.width()),round(y*ph/pet.height()));assert u.ClientToScreen(hwnd,ctypes.byref(p))
        logical=client_position(hwnd,p.x,p.y,pet.width(),pet.height())
        result=u.SendMessageW(hwnd,0x84,0,packed(p.x,p.y))
        expected=pet.alpha_hit(*logical)
        assert (result!=-1)==expected,(logical,result,expected)
        return expected
    try:
        items=all_items(pet.manifest)
        # New actions also need body/end coverage: their shared idle entrance
        # alone cannot verify a moving wing, turned head or extended prop.
        for item in items:
            with Image.open(pet.asset_path(item)) as image:
                frames=[0]
                if item.get('qualityRevision')==6 or item['id'] in {pet.idles[0]['id'],pet.manifest.get('dragAnimation',{}).get('id'),pet.manifest.get('landingAnimation',{}).get('id')}:
                    frames=sorted({0,image.n_frames//2,image.n_frames-1})
                for index in frames:
                    image.seek(index);rgba=image.convert('RGBA').resize((256,256))
                    frame=QImage(rgba.tobytes(),256,256,1024,QImage.Format.Format_RGBA8888).copy()
                    pet.frames=[QPixmap.fromImage(frame)];pet.index=0;pet._hit_image=frame;pet.current=item;pet.press_feedback=0
                    for facing in (1,-1):
                        pet.walk_direction=facing
                        for position in ((40,40),(420,180),(-80,-40)):
                            pet.move(*position);app.processEvents()
                            for y in range(8,256,24):
                                for x in range(8,256,24):
                                    if native_hit(x,y):body+=1
                                    else:clear+=1
                            records.append(dict(action=item['id'],frame=index,facing=facing,position=list(position)))
                    painted+=1
        # Real native press/move/release messages: Qt must receive a drag and
        # finish it. No QTest direct call bypasses the native adapter here.
        pet.gate.state='idle';pet.idle();pet.walk_direction=1;pet.press_feedback=0;pet.move(120,100);app.processEvents()
        point=next((QPointF(x,y) for y in range(40,220,12) for x in range(40,220,12) if pet.alpha_hit(x,y)),None)
        assert point is not None
        px,py=round(point.x()*pw/pet.width()),round(point.y()*ph/pet.height())
        u.SendMessageW(hwnd,0x201,1,packed(px,py))
        app.processEvents()
        assert pet._pointer_pressed
        u.SendMessageW(hwnd,0x200,1,packed(px+round(40*pw/256),py+round(30*ph/256)))
        app.processEvents()
        assert pet.dragging,'Native move did not enter drag'
        u.SendMessageW(hwnd,0x202,0,packed(px+round(40*pw/256),py+round(30*ph/256)))
        app.processEvents();assert not pet.dragging and pet.mode=='landing'
        u.SendMessageW(hwnd,0x204,2,packed(px,py));app.processEvents();u.SendMessageW(hwnd,0x205,0,packed(px,py));app.processEvents()
        assert pet.probe_menus==1
        pet.gate.state='idle';pet.idle()
        u.SendMessageW(hwnd,0x201,1,packed(px,py));app.processEvents();u.SendMessageW(hwnd,0x202,0,packed(px,py));app.processEvents()
        assert pet.click_timer.isActive();pet.click_timer.stop()
        pet.dragging=True;pet.gate.state='drag';pet.mode='drag'
        app.sendEvent(pet,QEvent(QEvent.Type.UngrabMouse));app.processEvents()
        assert not pet.dragging and pet.gate.state=='idle'
        u.SendMessageW(hwnd,0x202,0,packed(px,py));app.processEvents()
        assert not pet.click_timer.isActive(),'Late release after cancellation became a click'
        pet.switch_character('builtin');assert not pet.codex_navigation.closed
        edge_points=0
        for side in ('left','right'):
            # Native click coverage above (and the previous dock exit) starts
            # a time-based press squash. Static alpha comparisons must use
            # one settled pose on both sides of SendMessageW.
            pet.press_feedback=0
            pet.edge_dock.clear(immediate=True);area=pet.screen().availableGeometry()
            pet.move(area.left() if side=='left' else area.right()-pet.width()+1,area.top()+80)
            assert pet.edge_dock.try_dock()
            pet.edge_dock.animation.stop();pet.edge_dock._advance(1.);app.processEvents()
            assert int(pet.winId())==hwnd and area.contains(pet.geometry())
            points=[(x,y) for y in range(8,248,12) for x in range(8,248,12) if native_hit(x,y)]
            assert len(points)>10;edge_points+=len(points)
            x,y=points[len(points)//2];x=round(x*pw/pet.width());y=round(y*ph/pet.height())
            u.SendMessageW(hwnd,0x201,1,packed(x,y));app.processEvents()
            u.SendMessageW(hwnd,0x202,0,packed(x,y));app.processEvents()
            assert not pet.edge_dock.active and not pet._pointer_pressed
        pet.edge_dock.clear(immediate=True)
        proof=dict(passed=True,version=VERSION,dpr=pet.devicePixelRatioF(),clientPixels=[pw,ph],
            realWin32HitTests=True,nativePressDragRelease=True,nativeClickAndContextMenu=True,
            lostCaptureRecovered=True,characterNavigationAlive=True,actions=len(items),sampledFrames=painted,
            bodyPoints=body,transparentPoints=clear,records=records,osDisplaySettingsChanged=False,
            cursorMoved=False,syntheticProcessScale=os.environ.get('QT_SCALE_FACTOR','1'),edgeDockNativeHitTests=True,edgeDockHitPoints=edge_points,edgeDockNativeHandleStable=True)
        Path(output).write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
        return 0
    finally:pet.close();app.processEvents()
