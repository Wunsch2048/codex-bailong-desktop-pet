"""Versioned animation-only releases, staged beside immutable old materials."""
import hashlib,json,re,time
from dataclasses import replace
from pathlib import Path

from app_updates import UpdateError,read_small,ensure_checksum,version_tuple,asset_url

RECEIPT='animation-release.json'

def validate_catalog(catalog,version):
    from material_store import checked
    if not isinstance(catalog,dict) or catalog.get('schema')!=1 or set(catalog.get('tiers',{}))!={'light','hd'}:
        raise UpdateError('动画补丁素材目录无效')
    version_tuple(version)
    if catalog.get('releaseVersion')!=version:raise UpdateError('动画补丁目录版本不匹配')
    for tier,spec in catalog['tiers'].items():
        if spec.get('resolution')!={'light':512,'hd':720}[tier]:raise UpdateError('动画补丁分辨率无效')
        files=spec.get('files')
        if not isinstance(files,list) or not 1<=len(files)<=128:raise UpdateError('动画补丁清单无效')
        names=set();total=0
        for item in files:
            name=item.get('path');checked(Path.cwd(),name)
            if name.casefold() in names or type(item.get('bytes')) is not int or not 0<item['bytes']<2**31 or not re.fullmatch('[0-9a-f]{64}',str(item.get('sha256',''))):raise UpdateError('动画补丁文件信息无效')
            names.add(name.casefold());total+=item['bytes']
        if '素材清单.json'.casefold() not in names or total!=spec.get('bytes') or total>2**31:raise UpdateError('动画补丁素材大小无效')
        identity=hashlib.sha256(json.dumps(sorted(files,key=lambda f:f['path']),sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
        if spec.get('id')!=identity:raise UpdateError('动画补丁内容标识不匹配')
        name=f'bailong-desktop-pet-{version}-animation-{tier}.zip'
        asset_url(spec.get('url'),'v'+version,name)
        if type(spec.get('archiveBytes')) is not int or not 0<spec['archiveBytes']<2**31 or not re.fullmatch('[0-9a-f]{64}',str(spec.get('archiveSha256',''))):raise UpdateError('动画补丁压缩包校验信息无效')
    return catalog

def read_descriptor(release,program_version,opener,cancel):
    checked_release=ensure_checksum(replace(release,asset_name=release.animation_info_name,
        download_url=release.animation_info_url,sha256=release.animation_info_sha,
        size=release.animation_info_size),opener,cancel)
    raw=read_small(release.animation_info_url,131072,opener,cancel)
    if hashlib.sha256(raw).hexdigest()!=checked_release.sha256:raise UpdateError('动画补丁描述校验失败')
    data=json.loads(raw)
    if data.get('schema')!=1 or data.get('kind')!='animation' or data.get('version')!=release.version:raise UpdateError('动画补丁版本不匹配')
    minimum=data.get('minimumProgramVersion')
    if version_tuple(program_version)<version_tuple(minimum):raise UpdateError('请先更新程序，再安装此动画补丁')
    catalog=validate_catalog(data.get('catalog'),release.version)
    return catalog,minimum,checked_release.sha256


def validate_program_catalog(catalog,program_version):
    """An optional-animation program must carry a complete download contract.

    File identities alone allow local reuse but cannot provision a fresh or
    incomplete installation. Never silently ship computed materials-* URLs.
    Public availability is verified separately against the actual release.
    """
    version=catalog.get('releaseVersion') if isinstance(catalog,dict) else None
    if not version:raise UpdateError('人物素材缺少发布下载目录，请先关联对应动画包')
    validate_catalog(catalog,version)
    if version_tuple(version)>version_tuple(program_version):
        raise UpdateError('人物素材发布版本高于程序版本')
    return catalog

def prepare(release,program_version,state_dir,opener,cancel):
    catalog,minimum,sha=read_descriptor(release,program_version,opener,cancel)
    release=replace(release,animation_catalog=catalog,minimum_program_version=minimum,animation_info_sha=sha)
    if release.kind!='animation':return release
    tier='light'
    try:
        prefs=json.loads((Path(state_dir)/'material-preferences.json').read_text(encoding='utf-8'))
        tier='hd' if prefs.get('tier')=='hd' else 'light'
    except (OSError,ValueError,AttributeError):pass
    spec=catalog['tiers'][tier]
    return replace(release,asset_name=spec['url'].rsplit('/',1)[-1],download_url=spec['url'],
        size=spec['archiveBytes'],sha256=spec['archiveSha256'],animation_tier=tier)

def load_override(app_version,state_dir,base_catalog=None):
    try:
        data=json.loads((Path(state_dir)/RECEIPT).read_text(encoding='utf-8'))
        if data.get('schema')!=1:return None
        if base_catalog is None:
            if version_tuple(data['version'])<=version_tuple(app_version):return None
        elif base_catalog.get('releaseVersion') and version_tuple(base_catalog['releaseVersion'])>=version_tuple(data['version']):return None
        if version_tuple(data['minimumProgramVersion'])>version_tuple(app_version):return None
        validate_catalog(data['catalog'],data['version'])
        return data
    except (OSError,ValueError,TypeError,KeyError,AttributeError,UpdateError):return None

def effective_version(app_version,state_dir):
    data=load_override(app_version,state_dir)
    return data['version'] if data else app_version

def stage(release,app_root,state_dir,progress,cancel,opener=None):
    """Background-only: hash/decode new media without touching active state."""
    from material_store import MaterialStore
    from app_updates import open_url,check_cancel
    candidate=MaterialStore(app_root,state_dir,catalog_override=release.animation_catalog)
    tier=release.animation_tier or candidate.preferred
    root=None
    if not candidate.card_only:
        root=candidate.ensure(tier,cancel,progress,opener or open_url)
        validate_playback(root,candidate.catalog['tiers'][tier],cancel)
    check_cancel(cancel)
    return dict(store=candidate,tier=tier,root=root,release=release)

def validate_playback(root,spec,cancel):
    from app_updates import check_cancel
    from material_store import checked
    from desktop_services import all_items
    from sustained_assets import seam_items
    from PIL import Image
    manifest=json.loads(checked(root,'素材清单.json').read_text(encoding='utf-8'))
    if not manifest.get('idle'):raise UpdateError('动画补丁缺少待机动作')
    names={f['path'] for f in spec['files']}
    for item in all_items(manifest)+seam_items(manifest):
        check_cancel(cancel);name=item.get('playbackFile') or item.get('file')
        if name not in names:raise UpdateError('动画补丁缺少动作文件')
        with Image.open(checked(root,name)) as image:
            image.load()
            if image.width!=spec['resolution'] or image.height!=spec['resolution']:raise UpdateError('动画补丁动作尺寸不一致')

def commit(ready):
    """One atomic pointer switches the catalog; old cache and receipt survive."""
    from desktop_core import atomic_json
    store=ready['store'];release=ready['release'];path=store.state/RECEIPT
    previous=None
    try:previous=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    if previous:
        history=store.state/'animation-history';history.mkdir(exist_ok=True)
        atomic_json(history/(str(time.time_ns())+'.json'),previous)
    else:
        from version import VERSION
        previous=dict(version=VERSION,minimumProgramVersion=VERSION,catalog=store.bundled_catalog)
    previous={k:v for k,v in previous.items() if k!='previous'} if release.reason!='animation-rollback' else None
    atomic_json(path,dict(schema=1,version=release.version,minimumProgramVersion=release.minimum_program_version,
        catalog=release.animation_catalog,appliedAt=time.time(),previous=previous))
    store.patch_previous=previous

