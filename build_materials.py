"""Build verified light assets; never overwrite originals or create release archives."""
import hashlib,io,json,struct,sys,time,shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from asset_pack import chunk,chunks,riff,digest,optimize_all,CACHE
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'app'))
from desktop_services import all_items
from sustained_assets import seam_items
DEST=ROOT/'build/materials/light'
RECIPE='512-lanczos-exact-independent-m4q80-v1'

def convert(record):
    source=CACHE/(record['id']+'.webp');target=DEST/record['source'];receipt=ROOT/'build/materials/receipts'/(record['id']+'.json')
    try:
        previous=json.loads(receipt.read_text(encoding='utf-8'))
        if previous['recipe']==RECIPE and previous['sourceSha256']==digest(source) and previous['sha256']==digest(target):return previous
    except (OSError,ValueError,KeyError):pass
    began=time.monotonic();body=[];expected=[];durations=[]
    with Image.open(source) as animation:
        width=height=512;loop=animation.info.get('loop',0)
        u24=lambda n:int(n).to_bytes(3,'little')
        body=[chunk(b'VP8X',b'\x12\0\0\0'+u24(width-1)+u24(height-1)),chunk(b'ANIM',struct.pack('<IH',0,loop))]
        for i in range(animation.n_frames):
            animation.seek(i);animation.load();pixels=animation.convert('RGBA').resize((width,height),Image.Resampling.LANCZOS)
            delay=animation.info['duration'];durations.append(delay);expected.append(hashlib.sha256(pixels.tobytes()).hexdigest())
            buf=io.BytesIO();pixels.save(buf,format='WEBP',lossless=True,exact=True,method=4,quality=80)
            encoded=b''.join(c for tag,p,c in chunks(buf.getvalue()[12:]) if tag==b'VP8L')
            body.append(chunk(b'ANMF',u24(0)+u24(0)+u24(width-1)+u24(height-1)+u24(delay)+b'\x02'+encoded))
    target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_suffix('.tmp');temp.write_bytes(riff(b''.join(body)));del body
    with Image.open(temp) as check:
        assert check.size==(512,512) and check.n_frames==len(expected) and check.info.get('loop',0)==loop
        for i,sha in enumerate(expected):
            check.seek(i);check.load()
            if hashlib.sha256(check.convert('RGBA').tobytes()).hexdigest()!=sha or check.info['duration']!=durations[i]:raise ValueError('Light frame verification failed '+record['id'])
    temp.replace(target)
    result=dict(path=record['source'],id=record['id'],bytes=target.stat().st_size,sha256=digest(target),sourceSha256=digest(source),recipe=RECIPE,frames=len(expected),durations=durations,resolution=512,loop=loop,exactResizedRGBA=True,seconds=round(time.monotonic()-began,2))
    receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print(f"light {record['id']}: {result['bytes']} bytes; {len(expected)} frames verified",flush=True)
    return result

def retain_publication_catalog(computed,existing):
    """Keep versioned download metadata only when every verified file matches."""
    if not existing or not existing.get('releaseVersion'):return computed
    from animation_updates import validate_catalog
    validate_catalog(existing,existing['releaseVersion'])
    if computed.get('schema')!=existing.get('schema') or computed.get('default')!=existing.get('default'):
        raise ValueError('发布素材目录结构与本轮构建不一致')
    for name in ('light','hd'):
        for key in ('id','resolution','files','bytes'):
            if computed['tiers'][name][key]!=existing['tiers'][name][key]:
                raise ValueError('发布素材目录与本轮校验文件不一致：'+name+'/'+key)
    return existing

def build():
    optimized=optimize_all();DEST.mkdir(parents=True,exist_ok=True)
    manifest=ROOT/'outputs/白龙桌宠素材/素材清单.json';shutil.copy2(manifest,DEST/manifest.name)
    with ThreadPoolExecutor(max_workers=2) as pool:light=list(pool.map(convert,optimized['files']))
    hd=[dict(path=r['source'],bytes=r['optimizedBytes'],sha256=r['outputSha256'],resolution=720,frames=len(r['animation']['frames'])) for r in optimized['files']]
    descriptor=dict(path=manifest.name,bytes=manifest.stat().st_size,sha256=digest(manifest))
    tiers={}
    for name,records in [('light',light),('hd',hd)]:
        files=[dict(path=r['path'],bytes=r['bytes'],sha256=r['sha256']) for r in records]+[descriptor]
        files.sort(key=lambda r:r['path']);identity=hashlib.sha256(json.dumps(files,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
        tiers[name]=dict(id=identity,resolution=512 if name=='light' else 720,files=files,bytes=sum(r['bytes'] for r in files))
    tier=tiers['hd'];tag='materials-'+tier['id'];name='bailong-hd-'+tier['id']+'.zip'
    tier['url']=f'https://github.com/Wunsch2048/codex-bailong-desktop-pet/releases/download/{tag}/{name}'
    catalog=dict(schema=1,default='light',tiers=tiers)
    catalog_path=ROOT/'app/material_catalog.json'
    existing=json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.is_file() else None
    catalog=retain_publication_catalog(catalog,existing)
    (ROOT/'app/material_catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
    proof=dict(passed=True,recipe=RECIPE,lightBytes=tiers['light']['bytes'],hdBytes=tier['bytes'],files=light)
    (ROOT/'build/materials/verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k!='files'}),flush=True)
    return catalog
def package_hd(catalog):
    """Explicit future publication step only; normal local builds never call it."""
    import zipfile
    tier=catalog['tiers']['hd'];folder=ROOT/'release'/('materials-'+tier['id']);folder.mkdir(parents=True,exist_ok=True)
    target=folder/('bailong-hd-'+tier['id']+'.zip')
    records=json.loads((CACHE/'summary.json').read_text(encoding='utf-8'))['files'];sources={r['source']:CACHE/(r['id']+'.webp') for r in records}
    sources['素材清单.json']=ROOT/'outputs/白龙桌宠素材/素材清单.json'
    temp=target.with_suffix('.tmp')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_STORED) as z:
        for f in tier['files']:
            p=sources[f['path']]
            if digest(p)!=f['sha256']:raise ValueError('HD resource changed')
            z.write(p,f['path'])
    temp.replace(target)
    print('Explicit HD resource archive: '+str(target),flush=True)
    return target

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--package-hd',action='store_true',help='Explicitly create the version-independent HD release archive (does not upload)')
    args=parser.parse_args();catalog=build()
    if args.package_hd:package_hd(catalog)
