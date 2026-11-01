"""Re-encode only VP8L payloads; retain animation rectangles, flags and timing."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import io,json,hashlib,struct,time
from PIL import Image

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/'build/asset-optimization/verified'
RECIPE='vp8l-exact-method4-q80-v1'
def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def chunks(data):
    at=0
    while at<len(data):
        if at+8>len(data):raise ValueError('Truncated WebP chunk')
        size=int.from_bytes(data[at+4:at+8],'little');end=at+8+size
        if end>len(data):raise ValueError('Invalid WebP chunk')
        yield data[at:at+4],data[at+8:end],data[at:end+(size&1)]
        at=end+(size&1)
def chunk(tag,payload):return tag+struct.pack('<I',len(payload))+payload+(b'\0' if len(payload)&1 else b'')
def riff(body):return b'RIFF'+struct.pack('<I',len(body)+4)+b'WEBP'+body
def frame_fingerprints(path):
    frames=[]
    with Image.open(path) as im:
        size=list(im.size);loop=im.info.get('loop')
        for i in range(im.n_frames):
            im.seek(i);im.load();frames.append(dict(rgba=hashlib.sha256(im.convert('RGBA').tobytes()).hexdigest(),duration=im.info.get('duration')))
    return dict(size=size,loop=loop,frames=frames)
def encode_exact(source,target):
    data=source.read_bytes();body=[];saved=0
    if data[:4]!=b'RIFF' or data[8:12]!=b'WEBP':raise ValueError('Expected WebP')
    for tag,payload,original in chunks(data[12:]):
        if tag!=b'ANMF':body.append(original);continue
        header=payload[:16];encoded=payload[16:]
        if not all(t==b'VP8L' for t,p,c in chunks(encoded)):raise ValueError('Only lossless frames are supported')
        with Image.open(io.BytesIO(riff(encoded))) as im:
            pixels=im.convert('RGBA');buffer=io.BytesIO()
            pixels.save(buffer,format='WEBP',lossless=True,exact=True,method=4,quality=80)
            smaller=b''.join(c for t,p,c in chunks(buffer.getvalue()[12:]) if t==b'VP8L')
            with Image.open(io.BytesIO(riff(smaller))) as check:
                if check.convert('RGBA').tobytes()!=pixels.tobytes():raise ValueError('RGBA changed')
        chosen=smaller if len(smaller)<len(encoded) else encoded;saved+=len(encoded)-len(chosen)
        body.append(chunk(tag,header+chosen))
    target.write_bytes(riff(b''.join(body)))
    return saved
def optimize_one(item):
    relative=item.get('playbackFile') or item['file'];source=ROOT/'outputs/白龙桌宠素材'/relative
    key=item['id'];target=CACHE/(key+'.webp');record_path=CACHE/(key+'.json');original_sha=digest(source)
    try:
        record=json.loads(record_path.read_text(encoding='utf-8'))
        if record['recipe']==RECIPE and record['sourceSha256']==original_sha and record['exactRGBA'] and digest(target)==record['outputSha256']:return record
    except (OSError,ValueError,KeyError):pass
    start=time.perf_counter();temp=target.with_suffix('.tmp');encode_exact(source,temp)
    expected=frame_fingerprints(source);actual=frame_fingerprints(temp)
    if expected!=actual:temp.unlink(missing_ok=True);raise ValueError('Animation RGBA/timing changed: '+key)
    temp.replace(target)
    record=dict(id=key,source=relative,recipe=RECIPE,sourceSha256=original_sha,outputSha256=digest(target),rawBytes=source.stat().st_size,optimizedBytes=target.stat().st_size,exactRGBA=True,animation=expected,seconds=round(time.perf_counter()-start,3))
    record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{key}: {record["rawBytes"]} -> {record["optimizedBytes"]}; exact RGBA and timing',flush=True)
    return record
def optimize_all():
    import sys
    sys.path.insert(0,str(ROOT/'app'))
    from desktop_services import all_items
    from sustained_assets import seam_items
    CACHE.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/'outputs/白龙桌宠素材/素材清单.json').read_text(encoding='utf-8'))
    with ThreadPoolExecutor(max_workers=2) as workers:records=list(workers.map(optimize_one,all_items(manifest)+seam_items(manifest)))
    report=dict(recipe=RECIPE,passed=True,files=records,rawBytes=sum(r['rawBytes'] for r in records),optimizedBytes=sum(r['optimizedBytes'] for r in records))
    (CACHE/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
if __name__=='__main__':
    report=optimize_all();print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False))
