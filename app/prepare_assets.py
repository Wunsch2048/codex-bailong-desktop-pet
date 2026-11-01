"""Pre-scale real alpha frames to avoid decoding a 720px WebP on each click."""
from pathlib import Path
import gzip,json
from PIL import Image

root=Path(__file__).resolve().parents[1];assets=root/'outputs/白龙桌宠素材'
manifest=json.loads((assets/'素材清单.json').read_text(encoding='utf-8'))
items=[manifest['idle']]+manifest.get('additionalIdleAnimations',[])+manifest['variants']
for key in ('quotaAnimation','dragAnimation','landingAnimation'):
    if manifest.get(key):items.append(manifest[key])
cache=root/'app/cache';cache.mkdir(exist_ok=True)
for item in items:
    path=assets/(item.get('playbackFile') or item['file'].replace('.webm','.webp'))
    target=cache/f'{item["id"]}-hq.rgba.gz';meta=target.with_suffix('.json');stat=path.stat()
    if meta.is_file() and target.is_file():
        existing=json.loads(meta.read_text(encoding='utf-8'))
        if existing['sourceSize']==stat.st_size and existing['sourceMtime']==stat.st_mtime_ns:continue
    with Image.open(path) as source:
        frames=[]
        for i in range(source.n_frames):
            source.seek(i);frames.append(source.convert('RGBA').resize((512,512),Image.Resampling.LANCZOS).tobytes())
    target.write_bytes(gzip.compress(b''.join(frames),compresslevel=1))
    meta.write_text(json.dumps({'sourceSize':stat.st_size,'sourceMtime':stat.st_mtime_ns,'frames':len(frames)}),encoding='utf-8')
    print('Prepared '+item['id'],flush=True)
