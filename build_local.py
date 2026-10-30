"""Default local iteration: build the app, verify, deploy; never build installers.

Use build_release.py --package only for an explicitly requested public release.
All entry switching and failure recovery still belong to installer.deploy.
Local: --tests relevant_test_modules. Publishing: --build-only --release-check.
"""
import argparse,contextlib,hashlib,json,marshal,os,shutil,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'app'),str(ROOT)]
from desktop_core import VERSION
from deployment_state import atomic,verify_payload

def safe_print(*args,**kwargs):
    """Escape unprintable text when a Windows console uses a legacy code page."""
    try:
        print(*args,**kwargs)
    except UnicodeEncodeError:
        stream=kwargs.get('file') or sys.stdout
        encoding=getattr(stream,'encoding',None) or 'ascii'
        safe_args=[]
        for value in args:
            value=str(value)
            try:value.encode(encoding)
            except UnicodeEncodeError:value=value.encode(encoding,'backslashreplace').decode(encoding)
            safe_args.append(value)
        print(*safe_args,**kwargs)

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def expected_tests():
    return sorted([p.stem for p in (ROOT/'app').glob('test_*.py')]+['test_release_version','test_release_retention','test_local_workflow'])

def validation_plan(tests=None,release=False,native=False,tls=False):
    known=expected_tests();modules=known if release else sorted(set(tests or ()))
    if not modules:raise ValueError('本地构建请用 --tests 指定本轮相关检查；发布前使用 --release-check')
    if set(modules)-set(known):raise ValueError('未知检查模块：'+', '.join(sorted(set(modules)-set(known))))
    return dict(mode='release' if release else 'targeted',modules=modules,native=bool(release or native),tls=bool(release or tls))

def validate_regression(regression,plan=None):
    known=expected_tests();plan=plan or dict(mode='release',modules=known,tls=True,native=True)
    modules=plan.get('modules',[])
    if (not regression.get('passed') or regression.get('expectedModules')!=known
            or regression.get('sourceHashes')!=source_hashes()):raise ValueError('本轮检查未通过或源码已变化')
    if not modules or set(modules)-set(known):raise ValueError('构建缺少有效检查范围')
    if plan.get('mode')=='release':
        if regression.get('scope')!='full' or regression.get('modules')!=len(known) or sorted(modules)!=known:raise ValueError('发布前必须完成完整回归')
    else:
        records=regression.get('records',[])
        if sorted(r.get('module') for r in records)!=sorted(modules) or regression.get('modules')!=len(modules) or any(r.get('returncode')!=0 or r.get('tests',0)<=0 for r in records):raise ValueError('检查凭据与本轮指定范围不一致')
    return plan

def require_release_regression():
    validate_regression(read(ROOT/'本地实装/回归验收/current-regressions.json'))

def source_hashes():
    paths=list((ROOT/'app').glob('*.py'))
    paths += [ROOT/'app/tray_host.cs',ROOT/'build_tray_host.py']
    paths += [ROOT/name for name in ('build_local.py','quality_check.py','build_release.py','build_card_only.py','check_bundle.py','deploy_release.py','release_version.py','release_retention.py','asset_pack.py','build_materials.py','build_program_update.py','program_channel.py','package_trim.py','test_local_workflow.py','test_release_version.py','test_release_retention.py') if (ROOT/name).is_file()]
    if (ROOT/'app/material_catalog.json').is_file():paths.append(ROOT/'app/material_catalog.json')
    paths += [p for p in [ROOT/'requirements-enhanced.txt',ROOT/'app/book_catalog.json'] if p.is_file()]
    paths += [p for p in (ROOT/'app/fonts').glob('*') if p.is_file()]
    paths += list((ROOT/'app/branding').glob('*.ico'))
    manifest=ROOT/'outputs/白龙桌宠素材/素材清单.json'
    if manifest.is_file():
        paths.append(manifest)
        from sustained_assets import seam_items
        for item in seam_items(read(manifest)):
            seam=(manifest.parent/item['playbackFile']).resolve()
            if not seam.is_relative_to(manifest.parent.resolve()):raise ValueError('持续动作接缝路径无效')
            paths.append(seam)
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths}

def verify_code(folder):
    from PyInstaller.archive.readers import CArchiveReader
    from check_bundle import check,signature
    exe=folder/'BailongEnhanced.exe';archive=CArchiveReader(str(exe))
    pyz=next(k for k in archive.toc if k.endswith('.pyz'))
    if hashlib.sha256(archive.extract(pyz)).hexdigest()!=sha(ROOT/'build/BailongEnhanced/PYZ-00.pyz'):raise ValueError('主程序与被核对的编译归档不一致')
    if signature(marshal.loads(archive.extract('enhanced')))!=signature(compile((ROOT/'app/enhanced.py').read_text(encoding='utf-8'),'enhanced.py','exec')):raise ValueError('程序入口与当前源码不一致')
    import io
    with contextlib.redirect_stdout(io.StringIO()) as output:passed=check()
    (ROOT/'本地实装/编译模块核对.json').write_text(output.getvalue(),encoding='utf-8')
    if not passed:raise ValueError('程序编译模块与当前源码不一致')
    host=read(folder/'tray/host-build.json')
    if host.get('sourceSha256')!=sha(ROOT/'app/tray_host.cs') or host.get('executableSha256')!=sha(folder/'tray/BailongTray.exe'):raise ValueError('托盘宿主与当前源码或构建不一致')
    return dict(passed=True,embeddedArchiveBoundToExecutable=True,entrySourceMatched=True,modules=read(ROOT/'本地实装/编译模块核对.json'))

def native_matrix(exe,label):
    proofs=[]
    for factor in ('1','1.25','1.5','2'):
        output=ROOT/'本地实装'/f'{label}-原生交互-{factor}x.json'
        with tempfile.TemporaryDirectory(prefix='bailong-native-check-') as folder:
            env=os.environ.copy();env.update(LOCALAPPDATA=folder,CODEX_HOME=str(Path(folder)/'codex'),QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=factor,BAILONG_ISOLATED='1')
            output.unlink(missing_ok=True)
            with (output.with_suffix('.log')).open('w',encoding='utf-8') as log:
                try:subprocess.run([str(exe),'--interaction-probe',str(output)],cwd=exe.parent,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=100,check=True,creationflags=0x08000000)
                except (subprocess.SubprocessError,OSError):
                    error=Path(folder)/'BailongEnhanced/error.log'
                    if error.exists():log.write(error.read_text(encoding='utf-8',errors='replace'))
                    raise
        proof=read(output)
        if not proof['passed'] or proof['version']!=VERSION:raise ValueError('原生交互验收未通过')
        proofs.append(proof)
        safe_print(f'原生交互通过：{factor}x，{proof["actions"]} 段动作，{proof["bodyPoints"]} 个人物采样点',flush=True)
    return proofs

def verify_tls_runtime(exe):
    output=ROOT/'本地实装/冻结TLS验收.json';output.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='bailong-tls-check-') as folder:
        env=os.environ.copy();env.update(LOCALAPPDATA=folder,CODEX_HOME=str(Path(folder)/'codex'),BAILONG_ISOLATED='1')
        subprocess.run([str(exe),'--reset-diagnostics',str(output),'--tls-only'],cwd=exe.parent,env=env,check=True,timeout=20,creationflags=0x08000000)
    proof=read(output)
    if not all(proof.get(k) is True for k in ('contextReady','certificateVerification','hostnameVerification','offline')):raise ValueError('冻结程序TLS初始化或证书验证验收失败')
    return dict(passed=True,offline=True,certificateVerification=True,hostnameVerification=True)

def snapshot_source():
    dest=ROOT/'本地实装/源码快照'/(VERSION+'-'+time.strftime('%Y%m%d-%H%M%S'));dest.mkdir(parents=True)
    files=[p for p in (ROOT/'app').glob('*.py') if not p.name.startswith(('test_','qa_'))]
    files += [ROOT/'app/tray_host.cs',ROOT/'build_tray_host.py']
    files += [ROOT/p for p in ('build_local.py','quality_check.py','build_release.py','check_bundle.py','deploy_release.py','release_version.py','package_trim.py','asset_pack.py','build_materials.py','build_program_update.py','app/material_catalog.json','AGENTS.md','app/book_catalog.json','outputs/白龙桌宠素材/素材清单.json')]
    files += list((ROOT/'app/branding').glob('*.ico'))
    records={}
    for path in files:
        relative=path.relative_to(ROOT);target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);records[relative.as_posix()]=sha(target)
    atomic(dest/'snapshot.json',dict(version=VERSION,files=records,artworkStoredInInstalledRollbackAndVerifiedAssetCache=True))
    return dest

def settings_differences(earlier,settings):
    dynamic={'position','screen_position','facing'}
    home=settings.get('wander_home');position=settings.get('screen_position')
    if (isinstance(home,dict) and home==position and position!=earlier.get('screen_position') and
        isinstance(home.get('screen'),str) and bool(home['screen']) and
        home['screen']==(earlier.get('screen_position') or {}).get('screen') and
        all(type(home.get(k)) in (int,float) and 0<=home[k]<=1 for k in ('rx','ry'))):dynamic.add('wander_home')
    return [k for k,v in earlier.items() if k not in dynamic and settings.get(k)!=v]

def verify_installed(result):
    import psutil
    from installer import ROOT as INSTALL_ROOT,DATA,read_manifest
    from shared_assets import verify_version
    current=Path(result['executable']).parent;deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        try:
            runtime=read(DATA/'runtime.json')
            if runtime.get('version')==VERSION and Path(psutil.Process(runtime['pid']).exe()).resolve()==current/'BailongEnhanced.exe':break
        except (OSError,ValueError,psutil.Error,KeyError):pass
        time.sleep(.2)
    else:raise OSError('新版已提交，但安装后运行状态未能确认；保留旧版本可回退')
    m=read_manifest();previous=result['previous']
    if previous:
        if previous not in m['versions']:raise ValueError('安装清单缺少回退版本')
        old=INSTALL_ROOT/'versions'/previous
        verify_payload(old,previous.split('-')[0]);verify_version(old,m.get('sharedAssets',{}).get(previous))
    backup=Path(result['backup']);before=backup/'settings.json'
    if before.exists():
        settings=read(DATA/'settings.json');earlier=read(before)
        # Drag/drop and a completed throw deliberately save the activity home
        # together with the current position while startup acceptance runs.
        changed=settings_differences(earlier,settings)
        if changed:raise ValueError('安装后设置与部署前不一致：'+','.join(changed))
    if sha(current/'BailongEnhanced.exe')!=sha(ROOT/'release/BailongEnhanced/BailongEnhanced.exe'):raise ValueError('实际安装程序与检查过的构建不同')
    return dict(passed=True,pid=runtime['pid'],version=runtime['version'],uiRevision=runtime['ui_revision'],rollbackRetainedAndVerified=bool(previous),userSettingsPreserved=True,backupVerified=read(backup/'backup.json')['complete'],actualInstalledExecutableVerified=True)

def main(argv=None):
    args=argparse.ArgumentParser(description=__doc__);args.add_argument('--build-only',action='store_true',help='Build and validate without changing the installed program')
    args.add_argument('--deploy-verified',action='store_true',help='Deploy the exact unchanged build that already passed --build-only')
    args.add_argument('--tests',nargs='+',help='Only the test modules related to this local change')
    args.add_argument('--release-check',action='store_true',help='Full regression, TLS and four-scale checks before publishing')
    args.add_argument('--native-check',action='store_true',help='Include native four-scale checks when affected')
    args.add_argument('--tls-check',action='store_true',help='Include frozen TLS checks when affected')
    options=args.parse_args(argv)
    if options.build_only and options.deploy_verified:args.error('choose either --build-only or --deploy-verified')
    if not options.deploy_verified:
        try:options.validation=validation_plan(options.tests,options.release_check,options.native_check,options.tls_check)
        except ValueError as error:args.error(str(error))
    from PySide6.QtCore import QLockFile
    (ROOT/'build').mkdir(exist_ok=True);(ROOT/'本地实装').mkdir(exist_ok=True)
    lock=QLockFile(str(ROOT/'build/local-build.lock'))
    if not lock.tryLock(0):raise OSError('另一个本地构建正在运行')
    try:
        if options.deploy_verified:
            proof=read(ROOT/'本地实装/构建验收.json');folder=ROOT/'release/BailongEnhanced'
            if options.release_check and proof.get('validation',{}).get('mode')!='release':raise ValueError('该构建只做过定向检查，不能作为发布检查凭据')
            verify_code(folder)
            if proof.get('version')!=VERSION or proof.get('executableSha256')!=sha(folder/'BailongEnhanced.exe'):raise ValueError('构建已变化，必须重新运行默认构建验收')
            from directory_deploy import inspect_source
            inspect_source(folder,VERSION)
        else:
            safe_print('运行发布完整回归…' if options.release_check else '运行本轮相关检查：'+', '.join(options.validation['modules']),flush=True)
            with (ROOT/'本地实装/回归检查.log').open('w',encoding='utf-8') as log:
                command=[sys.executable,str(ROOT/'quality_check.py'),'current']
                if not options.release_check:command+=options.validation['modules']
                subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
            return build_and_deploy(options)
        return install_verified(proof,folder)
    finally:lock.unlock()

def build_and_deploy(options):
    safe_print('构建应用目录，不生成完整安装包…',flush=True)
    with (ROOT/'本地实装/应用构建.log').open('w',encoding='utf-8') as log:
        subprocess.run([sys.executable,str(ROOT/'build_release.py')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    folder=ROOT/'release/BailongEnhanced'
    plan=options.validation
    code=verify_code(folder)
    tls=verify_tls_runtime(folder/'BailongEnhanced.exe') if plan['tls'] else dict(skipped=True,reason='本轮未涉及TLS')
    probes=native_matrix(folder/'BailongEnhanced.exe','构建') if plan['native'] else []
    snapshot=snapshot_source()
    proof=dict(version=VERSION,validation=plan,executableSha256=sha(folder/'BailongEnhanced.exe'),compiledCode=code,tlsRuntime=tls,nativeMatrix=[{k:p[k] for k in ('passed','dpr','actions','sampledFrames','bodyPoints','transparentPoints','nativePressDragRelease')} for p in probes],sourceSnapshot=str(snapshot),fullInstallerGenerated=False,githubUploaded=False)
    atomic(ROOT/'本地实装/构建验收.json',proof)
    if options.build_only:return 0
    return install_verified(proof,folder)

def install_verified(proof,folder):
    from PySide6.QtCore import QLockFile
    # Directory deploy changes are Python-side too: tie the reusable build
    # to a passing regression receipt for the current production/test tree.
    regression=read(ROOT/'本地实装/回归验收/current-regressions.json')
    plan=validate_regression(regression,proof.get('validation'))
    if plan.get('tls') and not all(proof.get('tlsRuntime',{}).get(k) is True for k in ('passed','certificateVerification','hostnameVerification','offline')):raise ValueError('当前构建缺少冻结程序TLS验收')
    if proof.get('validation') and plan.get('native') and (len(proof.get('nativeMatrix',[]))!=4 or not all(p.get('passed') for p in proof['nativeMatrix'])):raise ValueError('本轮要求的原生交互检查未通过')
    from installer import DATA,startup_preference
    from directory_deploy import deploy_directory
    DATA.mkdir(parents=True,exist_ok=True);deployment_lock=QLockFile(str(DATA/'deployment.lock'))
    if not deployment_lock.tryLock(0):raise OSError('另一个安装程序正在运行')
    try:
        result=deploy_directory(folder,startup_preference())
        proof.update(deployment=result,installed=verify_installed(result))
        proof['regression']=dict(scope=regression['scope'],modules=regression['modules'],tests=regression['tests'],passed=True)
        atomic(ROOT/'本地实装/最终验收.json',proof)
        safe_print(json.dumps(dict(version=VERSION,current=result['current'],previous=result['previous'],backup=result['backup'],fullInstallerGenerated=False,passed=True),ensure_ascii=False),flush=True)
    finally:deployment_lock.unlock()
    return 0

if __name__=='__main__':raise SystemExit(main())
