"""从同一已校验目录生成便携归档与 AppImage"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def sha(path):
    """以流式读取计算产物校验值"""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    """构建工具与运行时由调用者提供，目标目录必须不存在"""
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('bundle','destination','appimagetool','runtime'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--name',default='Bailong-1.0.0-linux-preview.1-x86_64')
    args=parser.parse_args()
    bundle=args.bundle.resolve();out=args.destination.resolve()
    if out.exists():parser.error('目标目录已存在')
    records=json.loads((bundle/'payload-sha256.json').read_text())
    for name,value in records.items():
        if sha(bundle/name)!=value:raise ValueError('载荷校验失败：'+name)
    out.mkdir(parents=True)
    archive=out/(args.name+'.tar.zst');appimage=out/(args.name+'.AppImage')
    subprocess.run(['tar','--zstd','-cf',str(archive),'-C',str(bundle.parent),bundle.name],check=True)
    subprocess.run([str(args.appimagetool.resolve()),'--appimage-extract-and-run','--runtime-file',str(args.runtime.resolve()),
                    '--mksquashfs-opt','-processors','--mksquashfs-opt','2',str(bundle),str(appimage)],check=True,env={**os.environ,'ARCH':'x86_64'})
    appimage.chmod(0o755)
    (out/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in (archive,appimage)))


if __name__=='__main__':
    main()
