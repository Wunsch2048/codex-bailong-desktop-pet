"""独立构建 Linux 便携目录，不调用 Windows 构建或部署流程"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    """计算交付文件或素材的 SHA256"""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    """用显式资源清单构建，拒绝覆盖已有产物及夹带用户状态"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--materials', type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists():
        parser.error('目标目录已存在，请指定新的构建目录')
    source = args.materials.resolve()
    catalog = json.loads((ROOT / 'app/material_catalog.json').read_text())
    for record in catalog['tiers']['light']['files']:
        item = source / record['path']
        if not item.resolve().is_relative_to(source) or digest(item) != record['sha256']:
            raise ValueError('素材校验失败：' + record['path'])
    destination.mkdir(parents=True)
    command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--contents-directory', '.',
               '--name', 'bailong-linux', '--distpath', str(destination / 'dist'),
               '--workpath', str(destination / 'work'), '--specpath', str(destination),
               '--paths', str(ROOT / 'app'), '--add-data', str(ROOT / 'linux_app/codex_readonly') + ':linux_app',
               '--exclude-module', 'PySide6.QtWebEngineCore', '--exclude-module', 'PySide6.QtWebEngineWidgets']
    # 某些 Python 发行版的 ssl 模块依赖解释器旁的证书数据
    import ssl
    certificate = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
    if certificate.is_file():
        command += ['--add-data', str(certificate) + ':.']
    elif 'codex-rejected-cas.pem' in Path(ssl.__file__).read_text():
        raise RuntimeError('Python TLS 运行时证书文件缺失')
    subprocess.run(command + [str(ROOT / 'run_linux.py')], cwd=ROOT, check=True)
    bundle = destination / 'dist/bailong-linux'
    for folder in ('fonts', 'branding', 'licenses', 'sounds'):
        if (ROOT / 'app' / folder).is_dir():
            shutil.copytree(ROOT / 'app' / folder, bundle / 'app' / folder)
    for resource in (ROOT / 'app').glob('*.json'):
        shutil.copy2(resource, bundle / 'app' / resource.name)
    materials = bundle / 'outputs/白龙桌宠素材'
    materials.mkdir(parents=True)
    for record in catalog['tiers']['light']['files']:
        target = materials / record['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / record['path'], target)
    (bundle / 'configs').mkdir()
    shutil.copy2(ROOT / 'configs/niri-probe.kdl', bundle / 'configs/bailong-linux.kdl')
    for name in ('NOTICE.md',):
        shutil.copy2(ROOT / name, bundle / name)
    shutil.copy2(ROOT / 'docs/LINUX_PACKAGE.md', bundle / 'README.md')
    (bundle / 'AppRun').write_text('#!/bin/sh\nset -eu\nAPP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$APP_DIR/bailong-linux" "$@"\n')
    (bundle / 'AppRun').chmod(0o755)
    (bundle / 'linux_app/codex_readonly').chmod(0o755)
    shutil.copy2(ROOT / 'app/branding/bailong.png', bundle / 'bailong-linux.png')
    (bundle / 'bailong-linux.desktop').write_text('[Desktop Entry]\nType=Application\nName=Bailong Linux\nName[zh_CN]=白龙桌宠\nExec=bailong-linux\nIcon=bailong-linux\nTerminal=false\nCategories=Utility;\n')
    payload = {str(p.relative_to(bundle)): digest(p) for p in sorted(bundle.rglob('*')) if p.is_file() and not p.is_symlink()}
    (bundle / 'payload-sha256.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(bundle, flush=True)


if __name__ == '__main__':
    main()
