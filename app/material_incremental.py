"""Reuse verified local files and stream selected entries from the SAME release ZIP.

No delta artifact, recursive filesystem scan, in-memory archive or active-file writes.
Only authenticated catalog file hashes authorize reuse and the final staged result.
"""
import io
import json
import re
import shutil
import stat
import zipfile
from urllib.error import HTTPError

from material_store import MaterialError, checked, cancelled, hash_file


class RangeUnavailable(Exception):
    """The transport cannot serve ranges; caller may use the full verified ZIP."""


class RangeZip(io.RawIOBase):
    def __init__(self, url, size, opener, cancel, progress):
        self.url, self.size, self.opener = url, size, opener
        self.cancel, self.progress = cancel, progress
        self.position = self.received = 0
        self.response = None
        self.response_end = 0
        self.window_end = size

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position

    def _disconnect(self):
        if self.response is not None:
            self.response.close()
            self.response = None

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset if whence == 2 else -1
        if not 0 <= position <= self.size:
            raise MaterialError('动画压缩包偏移无效')
        if position != self.position: self._disconnect()
        self.position = position
        return position

    def window(self, end):
        self._disconnect()
        self.window_end = end

    def read(self, count=-1):
        cancelled(self.cancel)
        count = self.size - self.position if count < 0 else min(count, self.size - self.position)
        if count > 2 * 1024 * 1024:
            raise MaterialError('动画压缩包目录过大')
        if not count: return b''
        if self.position + count > self.window_end:
            raise MaterialError('动画压缩包条目越界')
        if self.response is None:
            end = self.window_end - 1
            try:
                response = self.opener(self.url, {'Accept': 'application/octet-stream',
                    'Accept-Encoding': 'identity', 'Range': f'bytes={self.position}-{end}'})
            except HTTPError as exc:
                if exc.code in (400, 405, 416): raise RangeUnavailable() from exc
                raise
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
            length = response.headers.get('Content-Length')
            if (getattr(response, 'status', 200) != 206 or not match or
                tuple(map(int, match.groups())) != (self.position, end, self.size) or
                response.headers.get('Content-Encoding', 'identity') != 'identity' or
                length is not None and length != str(end - self.position + 1)):
                response.close()
                raise RangeUnavailable()
            self.response, self.response_end = response, end + 1
        data = bytearray()
        while len(data) < count:
            cancelled(self.cancel)
            block = self.response.read(min(256 * 1024, count - len(data)))
            if not block: raise MaterialError('动画分段下载不完整，请重试')
            data.extend(block)
            self.position += len(block)
            self.received += len(block)
            self.progress(self.received)
        if self.position == self.response_end: self._disconnect()
        return bytes(data)

    def close(self):
        self._disconnect()
        super().close()


def reuse_files(store, tier, stage, cancel, progress):
    """Read only bounded catalog/receipt paths, hash bytes before copying them."""
    files = store.catalog['tiers'][tier]['files']
    wanted = {(f['bytes'], f['sha256']): [] for f in files}
    for f in files: wanted[(f['bytes'], f['sha256'])].append(f)
    roots = []
    bundled = (store.bundled_catalog or {}).get('tiers', {}).get(tier)
    if tier == 'light' and bundled:
        root = store.app_root / 'build/materials/light' if store.development else store.base
        roots.append((root, [f['path'] for f in bundled['files']]))
    parent = store.cache / tier
    if parent.is_dir() and not parent.is_symlink() and not getattr(parent, 'is_junction', lambda: False)():
        # Avoid scanning obsolete caches indefinitely. Newest complete receipts first.
        candidates = [p for p in parent.iterdir() if p.name.isalnum() and not p.is_symlink() and not getattr(p, 'is_junction', lambda: False)()]
        for root in sorted(candidates, key=lambda p: p.stat().st_mtime_ns, reverse=True)[:16]:
            cancelled(cancel)
            try:
                receipt_path = checked(root, '.verified.json')
                if receipt_path.stat().st_size > 128 * 1024: continue
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                names = receipt['files']
                if receipt['id'] != root.name or not isinstance(names, dict) or len(names) > 128: continue
                roots.append((root, list(names)))
            except (OSError, ValueError, KeyError, TypeError): continue
    reused = set()
    total = sum(f['bytes'] for f in files)
    done = 0
    for root, names in roots:
        for name in names:
            cancelled(cancel)
            if not wanted: return reused
            try:
                source = checked(root, name)
                size = source.stat().st_size
                if size not in {key[0] for key in wanted}: continue
                key = (size, hash_file(source, cancel))
                matches = wanted.pop(key, [])
                for f in matches:
                    target = checked(stage, f['path'])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Separate files keep a damaged old cache from altering the new one.
                    shutil.copyfile(source, target)
                    reused.add(f['path']); done += f['bytes']
                    progress(done, total, 'reusing')
            except (OSError, ValueError, TypeError):
                # Untrusted old paths/receipts never authorize reuse. Download instead.
                continue
    return reused


def extract_missing(url, spec, stage, reused, opener, cancel, progress):
    """zipfile validates local headers/CRC; final MaterialStore.verify checks SHA-256."""
    expected = {f['path']: f for f in spec['files']}
    with RangeZip(url, spec['archiveBytes'], opener, cancel, lambda n: None) as remote:
        with zipfile.ZipFile(remote) as archive:
            infos = archive.infolist()
            if len(infos) != len(expected) or len({i.filename for i in infos}) != len(infos):
                raise MaterialError('素材压缩包文件数量异常')
            for info in infos:
                checked(stage, info.filename)
                if (info.filename not in expected or info.file_size != expected[info.filename]['bytes'] or
                    stat.S_ISLNK(info.external_attr >> 16) or info.is_dir() or info.flag_bits & 1 or
                    info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or
                    not 0 <= info.header_offset < archive.start_dir or info.compress_size > spec['archiveBytes']):
                    raise MaterialError('素材压缩包内容异常')
            missing = [i for i in infos if i.filename not in reused]
            # Account actual response bytes, including directory/header reads, on one scale.
            total = remote.received + sum(i.compress_size + 30 + len(i.filename.encode('utf-8')) + len(i.extra) for i in missing)
            remote.progress = lambda n: progress(n, max(n, total), 'downloading')
            offsets = sorted([i.header_offset for i in infos] + [archive.start_dir])
            for info in missing:
                cancelled(cancel)
                remote.window(next(offset for offset in offsets if offset > info.header_offset))
                target = checked(stage, info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open('wb') as output:
                    count = 0
                    while data := source.read(256 * 1024):
                        cancelled(cancel); count += len(data)
                        if count > info.file_size: raise MaterialError('解压大小异常')
                        output.write(data)
                    if count != info.file_size: raise MaterialError('动画分段下载不完整')
            progress(remote.received, remote.received, 'downloading')
