"""Explicit publication of a complete program archive without character animations."""
import argparse,hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'app'))
from directory_deploy import inspect_source
from program_updates import PREFIX

def package(source,destination):
    source=Path(source);destination=Path(destination);manifest=json.loads((source/'payload-manifest.json').read_text(encoding='utf-8'))
    version=manifest['version'];inspect_source(source,version)
    catalog=json.loads((source/'app/material_catalog.json').read_text(encoding='utf-8'));tier=catalog['tiers']['light']
    animation_info=destination/f'bailong-desktop-pet-{version}-animation.json'
    if animation_info.exists() and json.loads(animation_info.read_text(encoding='utf-8'))['catalog']!=catalog:raise ValueError('同批程序包与动画补丁目录不一致')
    media={PREFIX+f['path']:dict(bytes=f['bytes'],sha256=f['sha256']) for f in tier['files']}
    if {n:f for n,f in manifest['files'].items() if n.startswith(PREFIX)}!=media:raise ValueError('素材目录与载荷不一致')
    descriptor=dict(schema=1,kind='program',version=version,materialId=tier['id'],optionalMaterials=True)
    destination.mkdir(parents=True,exist_ok=True);name=f'bailong-desktop-pet-{version}-program'
    archive=destination/(name+'.zip');temp=archive.with_suffix('.tmp');meta=destination/(name+'.json')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        z.writestr('program-update.json',json.dumps(descriptor,ensure_ascii=False))
        z.write(source/'payload-manifest.json','payload-manifest.json')
        for n in sorted(manifest['files']):
            if n not in media:z.write(source/n,n)
    temp.replace(archive);meta.write_text(json.dumps(descriptor,ensure_ascii=False,indent=2),encoding='utf-8')
    with archive.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    sums=destination/'SHA256SUMS.txt';checks={}
    if sums.is_file():
        for line in sums.read_text(encoding='utf-8-sig').splitlines():
            fields=line.split(maxsplit=1)
            if len(fields)==2 and len(fields[0])==64:checks[fields[1].lstrip('*')]=fields[0]
    checks[archive.name]=sha;checks[meta.name]=hashlib.sha256(meta.read_bytes()).hexdigest()
    sums.write_text(''.join(digest+'  '+name+'\n' for name,digest in sorted(checks.items())),encoding='utf-8')
    from program_channel import write_channel
    channel=write_channel(destination,version,program=archive)
    return dict(version=version,archive=str(archive),metadata=str(meta),bytes=archive.stat().st_size,sha256=sha,materialId=tier['id'],omittedMaterialBytes=tier['bytes'],coreFiles=len(manifest['files'])-len(media),programChannel=channel)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',default=str(ROOT/'release/BailongEnhanced'));parser.add_argument('--destination',default=str(ROOT/'release'));args=parser.parse_args()
    from build_local import require_release_regression
    require_release_regression()
    print(json.dumps(package(args.source,args.destination),ensure_ascii=False,indent=2))
