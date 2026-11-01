"""Explicit release-only card installer and separately downloadable light assets."""
import hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'app'),str(ROOT)]
from desktop_core import atomic_json
from directory_deploy import inspect_source
PREFIX='outputs/白龙桌宠素材/'

def prepare(source,destination):
    source=Path(source);destination=Path(destination)
    manifest=json.loads((source/'payload-manifest.json').read_text(encoding='utf-8'))
    inspect_source(source,manifest['version'])
    from animation_updates import validate_program_catalog
    validate_program_catalog(json.loads((source/'app/material_catalog.json').read_text(encoding='utf-8')),manifest['version'])
    if destination.exists():raise FileExistsError(destination)
    destination.mkdir(parents=True)
    files={n:f for n,f in manifest['files'].items() if not n.startswith(PREFIX)}
    for name in files:
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,target)
    atomic_json(destination/'payload-manifest.json',dict(version=manifest['version'],files=files))
    inspect_source(destination,manifest['version']);return destination

def package(source,output):
    """Called only with the user's explicit release request; never by local deploy."""
    from build_release import ssl_runtime_data
    source=Path(source);output=Path(output)
    version=json.loads((source/'payload-manifest.json').read_text(encoding='utf-8'))['version']
    card=prepare(source,output/f'card-only-{version}')
    work=ROOT/'build'/f'cards-{version}'
    if work.exists():raise FileExistsError(work)
    work.mkdir(parents=True);payload=work/'payload.zip'
    with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for path in sorted(card.rglob('*')):
            if path.is_file():z.write(path,path.relative_to(card))
    name=f'白龙卡片-{version}-一键部署'
    subprocess.run([sys.executable,str(ROOT/'本地实装/pyinstaller_keep_files.py'),'--windowed','--onefile',
        '--icon',str(ROOT/'app/branding/bailong.ico'),'--name',name,'--distpath',str(output),
        '--workpath',str(work/'installer'),'--specpath',str(work),'--exclude-module','imageio_ffmpeg',
        *ssl_runtime_data(),'--add-data',str(payload)+';.','app/installer.py'],cwd=ROOT,check=True)
    archive=output/f'bailong-desktop-pet-{version}-cards-windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        z.write(output/(name+'.exe'),name+'.exe')
        z.write(ROOT/'发布说明/仅卡片安装说明.txt','先读我.txt')
        z.write(ROOT/'发布说明/来源与授权说明.txt','来源与授权说明.txt')
    # Light resources have an immutable, separate material release URL.
    catalog=json.loads((source/'app/material_catalog.json').read_text(encoding='utf-8'));spec=catalog['tiers']['light']
    materials=output/('materials-'+spec['id']);materials.mkdir(exist_ok=True)
    resource=materials/f"bailong-light-{spec['id']}.zip"
    with zipfile.ZipFile(resource,'w',zipfile.ZIP_STORED) as z:
        for record in spec['files']:
            p=source/PREFIX/record['path']
            with p.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
            if sha!=record['sha256'] or p.stat().st_size!=record['bytes']:raise ValueError('轻量素材已改变')
            z.write(p,record['path'])
    sums=output/'SHA256SUMS.txt'
    with archive.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    with sums.open('a',encoding='utf-8') as stream:stream.write(sha+'  '+archive.name+'\n')
    return dict(cards=str(archive),materials=str(resource),materialTag='materials-'+spec['id'])
