"""Publication metadata for the small, runtime-free Windows online installer.

Carry this descriptor forward on animation-only releases. It always points to
one complete cumulative program archive, never to a sequence of delta patches.
"""
import hashlib,json,re,zipfile
from pathlib import Path

REPOSITORY='Wunsch2048/codex-bailong-desktop-pet'
CHANNEL='program-channel.json'
MAX_PACKAGE=2_147_483_647

def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',value):raise ValueError('程序通道版本格式无效')
    return tuple(map(int,value.split('.')))

def validate(data,maximum=None,minimum=None):
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema']!=1 or data.get('kind')!='program-channel' or type(data.get('installerProtocol')) is not int or data['installerProtocol']!=1:raise ValueError('首次安装通道协议不受支持')
    v=data.get('version');vtuple=version(v)
    if maximum and vtuple>version(maximum):raise ValueError('程序通道不能指向本次发布之后的版本')
    if minimum and vtuple<version(minimum):raise ValueError('程序通道版本不足以支持本次动画补丁')
    p=data.get('program')
    name=f'bailong-desktop-pet-{v}-program.zip'
    if not isinstance(p,dict) or p.get('name')!=name or p.get('url')!=f'https://github.com/{REPOSITORY}/releases/download/v{v}/{name}':raise ValueError('程序通道必须使用本仓库正式附件')
    if type(p.get('bytes')) is not int or not 0<p['bytes']<=MAX_PACKAGE or not re.fullmatch('[0-9a-f]{64}',str(p.get('sha256',''))):raise ValueError('程序通道缺少有效大小或SHA-256')
    return data

def from_archive(program,v):
    version(v);program=Path(program)
    if program.name!=f'bailong-desktop-pet-{v}-program.zip':raise ValueError('程序包名称与公开版本不一致')
    with zipfile.ZipFile(program) as z:
        for name in ('program-update.json','payload-manifest.json'):
            if z.getinfo(name).file_size>8*1024*1024:raise ValueError('程序说明过大')
        info=json.loads(z.read('program-update.json'));manifest=json.loads(z.read('payload-manifest.json'))
        if info.get('schema')!=1 or info.get('kind')!='program' or info.get('optionalMaterials') is not True or info.get('version')!=v or manifest.get('version')!=v:raise ValueError('首次安装需要兼容的完整累计程序包')
    with program.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return validate(dict(schema=1,kind='program-channel',installerProtocol=1,version=v,program=dict(name=program.name,url=f'https://github.com/{REPOSITORY}/releases/download/v{v}/{program.name}',bytes=program.stat().st_size,sha256=sha)))

def write_channel(destination,release_version,program=None,previous=None,minimum=None):
    """Write a new program target or explicitly carry the last public target.

    No network or publishing here. The caller verifies public availability
    before publishing a release and must not substitute a private local build.
    """
    if bool(program)==bool(previous):raise ValueError('请选择本次累计程序包或上一公开程序通道')
    data=from_archive(program,release_version) if program else json.loads(Path(previous).read_text(encoding='utf-8-sig'))
    validate(data,release_version,minimum)
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    path=destination/CHANNEL;raw=json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')
    if not path.exists() or path.read_bytes()!=raw:path.write_bytes(raw)
    sums=destination/'SHA256SUMS.txt';records={}
    if sums.exists():
        for line in sums.read_text(encoding='utf-8-sig').splitlines():
            fields=line.split(maxsplit=1)
            if len(fields)==2:records[fields[1].lstrip('*')]=fields[0]
    records[CHANNEL]=hashlib.sha256(raw).hexdigest()
    sums.write_text(''.join(sha+'  '+name+'\n' for name,sha in sorted(records.items())),encoding='utf-8')
    return data
