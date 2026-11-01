"""Compile/run the shared staging and download code with retained fixtures.

The injected transport supplies synthetic bytes; no staged EXE is executable.
No public download, registry write, installation or recursive deletion occurs.
"""
import hashlib,json,os,subprocess,sys,time,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
TOOLS=ROOT/'tools'
sys.path.insert(0,str(TOOLS))
from package_program_installer import compiler_paths
work=ROOT/'build'/('download-check-'+str(time.time_ns()));work.mkdir(parents=True)
media={'idle.webp':b'verified-media-fixture','素材清单.json':b'{"idle":{"file":"idle.webp"}}'}
records=[dict(path=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in sorted(media.items())]
identity=hashlib.sha256(json.dumps(records,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
catalog=dict(schema=1,tiers={'light':dict(id=identity,files=records,bytes=sum(x['bytes'] for x in records))})
core={'BailongEnhanced.exe':b'MZ-only-a-stage-fixture','app/version.py':b"VERSION = '1.2.1'\n",'app/material_catalog.json':json.dumps(catalog).encode(),'_internal/runtime.dll':os.urandom(65536)}
files={n:dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in core.items()}
files.update({'outputs/白龙桌宠素材/'+n:dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in media.items()})
program=work/'program.zip'
with zipfile.ZipFile(program,'w',zipfile.ZIP_DEFLATED) as z:
    z.writestr('program-update.json',json.dumps(dict(schema=1,kind='program',version='1.2.1',materialId=identity,optionalMaterials=True)))
    z.writestr('payload-manifest.json',json.dumps(dict(version='1.2.1',files=files)))
    for n,b in core.items():z.writestr(n,b)
name='bailong-desktop-pet-1.2.1-program.zip'
channel=dict(schema=1,kind='program-channel',installerProtocol=1,version='1.2.1',program=dict(name=name,url='https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/v1.2.1/'+name,bytes=program.stat().st_size,sha256=hashlib.sha256(program.read_bytes()).hexdigest()))
(work/'program-channel.json').write_text(json.dumps(channel),encoding='utf-8')
shared=work/'ProgramPatchBootstrap.cs';shared.write_text((TOOLS/shared.name).read_text(encoding='utf-8').replace('@@VERSION@@','1.0.1').replace('@@PAYLOAD_SHA@@','0'*64),encoding='utf-8')
compiler,libraries=compiler_paths();exe=work/'NetworkHarness.exe'
command=[str(compiler),'/nologo','/target:exe','/main:NetworkHarness','/platform:x64',f'/out:{exe}',*[f'/reference:{p}' for p in libraries],str(shared),str(TOOLS/'LatestProgramInstaller.cs'),str(HERE/'NetworkHarness.cs')]
compiled=subprocess.run(command,capture_output=True)
(work/'compile.log').write_bytes(compiled.stdout+compiled.stderr)
if compiled.returncode:print((compiled.stdout+compiled.stderr).decode(errors='replace'));raise SystemExit(compiled.returncode)
done=subprocess.run([str(exe),str(work)],capture_output=True,timeout=40)
data=json.loads((work/'native-checks.json').read_text(encoding='utf-8-sig'))
if data.get('passed'):
    sys.path.insert(0,str(ROOT/'app'))
    from program_updates import verify_ready
    for name in ('fresh','existing','cache'):
        state=work/name/'BailongEnhanced/updates'
        verify_ready(state/'1.2.1/program/source',state,'1.2.1')
    data['checks']['pythonInstallationReceiptAccepted']=True
data['fixtures']=str(work)
data['sourceHashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [TOOLS/'ProgramPatchBootstrap.cs',TOOLS/'LatestProgramInstaller.cs',HERE/'NetworkHarness.cs']}
(work/'result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(data,ensure_ascii=False));raise SystemExit(done.returncode)
