"""Optional seam assets; keep logical actions separate from their playback files."""
from pathlib import Path

def playback_profile(item):
    """Migrate only the two shipped recipes, without rewriting asset identity.

    The old variants reach back into prop setup. Choosing the already shipped
    stable segment is a player policy change, not a new downloadable asset.
    Any authored/custom recipe difference deliberately opts out of migration.
    """
    profile=item.get('sustained')
    if not isinstance(profile,dict):return None
    result=dict(profile)
    spec={'work02':(55,83,163),'work04':(44,85,139)}.get(item.get('id'))
    if spec is None or item.get('qualityRevision')!=3:return result
    action=item['id']
    if item.get('playbackFile')!=f'quality-v3/{action}.webp':return result
    start,end,frames=spec
    variants=[dict(start=start-offset,end=end,seamFile=f'quality-v5/{action}-seam-{index}.webp',seamFrames=count)
              for index,(offset,count) in enumerate(((0,9),(4,13),(2,11)))]
    expected=dict(variants[0],sourceFrames=frames,variants=variants,revision=2,forwardOnly=True)
    if profile!=expected or profile.get('forwardOnly') is not True:return result
    return dict(result,variants=[dict(variants[0])],steadyProp=True)

def seam_items(manifest):
    items=[]
    for action in manifest.get('workAnimations',[]):
        profile=action.get('sustained') if isinstance(action,dict) else None
        if not isinstance(profile,dict):continue
        name=profile.get('seamFile');frames=profile.get('seamFrames')
        if not isinstance(name,str) or not isinstance(frames,int) or isinstance(frames,bool) or not 1<=frames<=24:raise ValueError('持续动作接缝清单无效')
        items.append(dict(id=action['id']+'-seam',file=name,playbackFile=name,durationMs=round(frames*1000/24),name='持续动作接缝'))
        variants=profile.get('variants',[])
        if not isinstance(variants,list) or len(variants)>4:raise ValueError('持续动作变体清单无效')
        for index,variant in enumerate(variants):
            if not isinstance(variant,dict):raise ValueError('持续动作变体清单无效')
            extra=variant.get('seamFile');count=variant.get('seamFrames')
            if not isinstance(extra,str) or not isinstance(count,int) or isinstance(count,bool) or not 1<=count<=24:raise ValueError('持续动作变体接缝无效')
            if extra==name:continue
            items.append(dict(id=f'{action["id"]}-seam-{index}',file=extra,playbackFile=extra,durationMs=round(count*1000/24),name='持续动作变化接缝'))
    for action in manifest.get('moveAnimations',[]):
        p=action.get('locomotion') if isinstance(action,dict) else None
        if not isinstance(p,dict) or not p.get('seamFile'):continue
        count=p.get('seamFrames');fps=p.get('fps')
        if type(count) is not int or not 1<=count<=24 or fps not in (24,30):raise ValueError('移动动作接缝无效')
        items.append(dict(id=action['id']+'-seam',file=p['seamFile'],playbackFile=p['seamFile'],durationMs=round(count*1000/fps),name='移动动作衔接'))
    return items

def profile_paths(root,item):
    profile=playback_profile(item)
    if profile is None:return None
    start,end,frames=(profile.get(k) for k in ('start','end','sourceFrames'))
    if any(not isinstance(v,int) or isinstance(v,bool) for v in (start,end,frames)) or not 0<=start<end<frames-1 or frames>2000:raise ValueError('持续动作范围无效')
    seam_count=profile.get('seamFrames')
    if not isinstance(seam_count,int) or isinstance(seam_count,bool) or not 1<=seam_count<=24:raise ValueError('持续动作接缝范围无效')
    root=Path(root).resolve();paths=[]
    for name in (item.get('playbackFile') or item['file'],profile.get('seamFile','')):
        if not isinstance(name,str) or not name:raise ValueError('持续动作素材路径无效')
        from material_store import checked
        path=checked(root,name)
        if not path.is_file() or path.suffix.lower()!='.webp':raise ValueError('持续动作素材不存在或路径无效')
        paths.append(path)
    result=dict(profile,source=paths[0],seam=paths[1])
    variants=profile.get('variants',[])
    if not isinstance(variants,list) or len(variants)>4:raise ValueError('持续动作变体清单无效')
    resolved=[]
    for variant in variants:
        if not isinstance(variant,dict) or variant.get('end')!=end or 'variants' in variant:raise ValueError('持续动作变体必须共用原片出口')
        record=profile_paths(root,dict(item,sustained=dict(variant,sourceFrames=frames)))
        resolved.append(record)
    if resolved:result['variants']=resolved
    return result
