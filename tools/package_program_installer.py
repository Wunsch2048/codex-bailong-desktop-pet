"""Package online first-install and optional pinned offline compatibility bridge."""
import argparse,hashlib,json,os,re,subprocess,zipfile,sys,time
from pathlib import Path

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def compiler_paths():
    windows=Path(os.environ.get('WINDIR',r'C:\Windows'))
    framework=windows/'Microsoft.NET/Framework64/v4.0.30319';compiler=framework/'csc.exe'
    if not compiler.is_file():raise FileNotFoundError('Windows .NET Framework C# compiler not found')
    libraries=[]
    for name in ('System.IO.Compression','System.IO.Compression.FileSystem','System.Web.Extensions','System.Windows.Forms','System.Drawing'):
        direct=framework/(name+'.dll')
        candidates=[direct] if direct.is_file() else sorted((windows/'Microsoft.NET/assembly/GAC_MSIL'/name).glob('*/'+name+'.dll'))
        if not candidates:raise FileNotFoundError('Missing .NET runtime library: '+name)
        libraries.append(candidates[-1])
    return compiler,libraries

def build(program,version,destination,icon):
    program=Path(program).resolve();destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):raise ValueError('Invalid public version')
    with zipfile.ZipFile(program) as archive:
        descriptor=json.loads(archive.read('program-update.json'))
        manifest=json.loads(archive.read('payload-manifest.json'))
        if descriptor.get('version')!=version or manifest.get('version')!=version or descriptor.get('optionalMaterials') is not True:raise ValueError('Not a compatible program-only payload')
    sha=digest(program);work=destination/'bootstrap-build'
    if work.exists():raise FileExistsError(work)
    work.mkdir()
    template=Path(__file__).with_name('ProgramPatchBootstrap.cs').read_text(encoding='utf-8')
    source=work/'ProgramPatchBootstrap.cs';source.write_bytes(template.replace('@@VERSION@@',version).replace('@@PAYLOAD_SHA@@',sha).encode('utf-8'))
    compiler,libraries=compiler_paths();exe=destination/f'白龙桌宠-{version}-一键部署.exe'
    command=[str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',f'/out:{exe}',f'/win32icon:{Path(icon).resolve()}',f'/resource:{program},Bailong.Program',*[f'/reference:{p}' for p in libraries],str(source)]
    subprocess.run(command,cwd=work,check=True,capture_output=True)
    return dict(version=version,installer=str(exe),installerBytes=exe.stat().st_size,programSha256=sha,installerSha256=digest(exe))

def build_online(version,destination,icon):
    """No embedded program. The public channel chooses the verified payload."""
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):raise ValueError('Invalid public version')
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    work=destination/('online-bootstrap-build-'+version+'-'+str(time.time_ns()));work.mkdir()
    tools=Path(__file__).resolve().parent
    source=work/'ProgramPatchBootstrap.cs'
    source.write_text((tools/'ProgramPatchBootstrap.cs').read_text(encoding='utf-8').replace('@@VERSION@@',version).replace('@@PAYLOAD_SHA@@','0'*64),encoding='utf-8')
    network=work/'LatestProgramInstaller.cs';network.write_bytes((tools/network.name).read_bytes())
    compiler,libraries=compiler_paths();exe=destination/f'bailong-desktop-pet-{version}-setup.exe'
    command=[str(compiler),'/nologo','/target:winexe','/main:LatestProgramInstaller','/platform:x64','/optimize+',f'/out:{exe}',f'/win32icon:{Path(icon).resolve()}',*[f'/reference:{p}' for p in libraries],str(source),str(network)]
    done=subprocess.run(command,cwd=work,capture_output=True)
    if done.returncode:raise RuntimeError(done.stdout.decode(errors='replace')+done.stderr.decode(errors='replace'))
    return dict(onlineInstaller=str(exe),onlineInstallerBytes=exe.stat().st_size,onlineInstallerSha256=digest(exe),embeddedProgram=False)

def package(program,version,destination,icon):
    result=build(program,version,destination,icon);destination=Path(destination)
    online=build_online(version,destination,icon)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from program_channel import write_channel
    channel=write_channel(destination,version,program=program)
    notes='程序补丁安装器 '+version+'\n\n已有用户：复用可校验的本机动画，保留设置、统计和回退版本。\n新用户：先安装卡片程序，在设置的素材页按需下载轻量或高清动画。\n该安装器不包含动画资源。程序 ZIP / JSON 供软件内更新使用。\n'
    name=f'bailong-desktop-pet-{version}-windows-x64.zip';archive=destination/name
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        z.write(result['installer'],Path(result['installer']).name)
        z.writestr('程序补丁说明.txt',notes)
    sums=destination/'SHA256SUMS.txt';records={}
    if sums.is_file():
        for line in sums.read_text(encoding='utf-8-sig').splitlines():
            fields=line.split(maxsplit=1)
            if len(fields)==2:records[fields[1].lstrip('*')]=fields[0]
    records[name]=digest(archive);records[Path(online['onlineInstaller']).name]=online['onlineInstallerSha256']
    sums.write_bytes(''.join(sha+'  '+name+'\n' for name,sha in sorted(records.items())).encode('utf-8'))
    return dict(result,**online,programChannel=channel,archive=str(archive),archiveBytes=archive.stat().st_size,archiveSha256=records[name],includesAnimations=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('program','version','destination','icon'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--online-only',action='store_true',help='只构建小型在线安装器，不重复嵌入程序ZIP')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(root),str(root/'app')]
    from build_local import require_release_regression
    require_release_regression()
    if args.online_only:
        from program_channel import write_channel
        channel=write_channel(args.destination,args.version,program=args.program)
        result=build_online(args.version,args.destination,args.icon)
        sums=Path(args.destination)/'SHA256SUMS.txt'
        with sums.open('a',encoding='utf-8') as out:out.write(result['onlineInstallerSha256']+'  '+Path(result['onlineInstaller']).name+'\n')
        result['programChannel']=channel
    else:result=package(args.program,args.version,args.destination,args.icon)
    print(json.dumps(result,ensure_ascii=False,indent=2))
