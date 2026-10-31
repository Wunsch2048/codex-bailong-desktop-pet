"""Compile the small tray owner at build time; no user-machine compiler or downloads."""
import os,subprocess,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def build(destination):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    windows=Path(os.environ.get('WINDIR','C:/Windows'))
    compiler=windows/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():compiler=windows/'Microsoft.NET/Framework/v4.0.30319/csc.exe'
    if not compiler.is_file():raise OSError('缺少系统C#编译器，不能构建固定托盘宿主')
    source=ROOT/'app/tray_host.cs'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/optimize+','/debug-',
        '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll',
        '/win32icon:'+str(ROOT/'app/branding/bailong.ico'),'/out:'+str(destination),str(source)],check=True,cwd=ROOT)
    subprocess.run([str(destination),'--self-check'],check=True,timeout=10)
    return dict(sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(),executableSha256=hashlib.sha256(destination.read_bytes()).hexdigest(),bytes=destination.stat().st_size)

if __name__=='__main__':
    import sys
    print(json.dumps(build(sys.argv[1]),ensure_ascii=False))
