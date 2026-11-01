"""Replace only the explicitly registered preceding minor release, after verification."""
import hashlib,json,shutil
from pathlib import Path

def checked_path(release,name,version):
    prefixes=(f'白龙桌宠-{version}-',f'bailong-desktop-pet-{version}-')
    if Path(name).name!=name or not name.startswith(prefixes):raise ValueError('Unregistered artifact name')
    p=release/name
    if p.is_symlink() or p.is_junction() or p.resolve()!=p.absolute() or p.parent!=release:raise ValueError('Unsafe artifact path')
    if p.is_dir():
        for child in p.rglob('*'):
            if child.is_symlink() or child.is_junction() or not child.resolve().is_relative_to(release):raise ValueError('Linked artifact content')
    return p

def replace_previous(root,version,new_names,proof):
    root=Path(root).resolve();release=root/'release'
    if release.is_symlink() or release.is_junction() or release.resolve()!=release:raise ValueError('Unsafe release root')
    policy_path=root/'发布说明/发布保留策略.json';policy=json.loads(policy_path.read_text(encoding='utf-8'))
    old=policy['currentReplaceableVersion']
    if old==version:raise ValueError('Already finalized')
    required=('compiledCodeVerified','installationVerified','zipVerified')
    if proof.get('volumesRequired',True):required+=('volumesVerified',)
    if not proof.get('passed') or proof.get('version')!=version or not all(proof.get(k) for k in required):raise ValueError('New release verification incomplete')
    new=[checked_path(release,n,version) for n in new_names]
    if not new or not all(p.exists() and (not p.is_file() or p.stat().st_size>0) for p in new):raise ValueError('New artifacts missing')
    old_paths=[checked_path(release,n,old) for n in dict.fromkeys(policy['replaceableArtifacts']+policy.get('replaceableProgramArtifacts',[]))]
    total=sum(p.stat().st_size for rootpath in old_paths for p in ([rootpath] if rootpath.is_file() else rootpath.rglob('*')) if p.is_file())
    # Validate the entire deletion list and nested contents before deleting any.
    removed=[]
    for p in old_paths:
        if p.is_dir():shutil.rmtree(p);removed.append(p.name)
        elif p.exists():p.unlink();removed.append(p.name)
    policy['replaceableProgramArtifacts']=[n for n in new_names if n.startswith('bailong-desktop-pet-') and '-program.' in n]
    policy.update(updated=__import__('datetime').date.today().isoformat(),currentReplaceableVersion=version,replaceableArtifacts=new_names)
    policy_path.write_text(json.dumps(policy,ensure_ascii=False,indent=2),encoding='utf-8')
    hashes_path=release/'SHA256.json';hashes=json.loads(hashes_path.read_text(encoding='utf-8')) if hashes_path.exists() else {}
    for p in old_paths:hashes.pop(p.name,None)
    for p in new:
        if p.is_file():
            with p.open('rb') as stream:hashes[p.name]=hashlib.file_digest(stream,'sha256').hexdigest()
    hashes_path.write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(passed=True,previousVersion=old,version=version,removed=removed,freedBytes=total,installedRollbackPreserved=True,historicalPackagesUntouched=True)
