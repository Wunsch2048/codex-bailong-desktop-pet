"""Validated chat configuration with crash-safe references to encrypted keys.

A key replacement first creates a new encrypted slot. The sole commit point is
the atomic replacement of chat.json. Old slots remain usable if either write
fails or the process exits between writes; no best-effort rollback is needed.
"""
import copy
import json
import uuid
from pathlib import Path

from desktop_core import atomic_json
from desktop_services import SecretStore

CHAT_DEFAULT=dict(providers=[],active='',service='custom',chatgpt_model='',system_prompt='你是白龙娘，是陪伴用户工作的桌面伙伴。用自然、简洁的中文回应。',history_messages=40,history_chars=24000)


def _invalid():
    return OSError('chat.json 结构损坏；请从用户数据备份恢复，原文件未改动。')


def _validated(value):
    if not isinstance(value,dict):raise _invalid()
    try:
        result=copy.deepcopy(CHAT_DEFAULT);result.update(copy.deepcopy(value))
    except RecursionError:raise _invalid() from None
    if not isinstance(result['providers'],list):raise _invalid()
    for name in ('active','system_prompt','chatgpt_model'):
        if not isinstance(result[name],str):raise _invalid()
    if result['service'] not in ('custom','chatgpt'):raise _invalid()
    for name,low,high in (('history_messages',2,200),('history_chars',1000,200000)):
        number=result[name]
        if type(number) is not int or not low<=number<=high:raise _invalid()
    seen=set()
    for provider in result['providers']:
        if not isinstance(provider,dict):raise _invalid()
        identity=provider.get('id')
        if not isinstance(identity,str) or not identity or identity in seen:raise _invalid()
        seen.add(identity)
        for name in ('name','base_url','model','credential_id'):
            if name in provider and not isinstance(provider[name],str):raise _invalid()
        if 'timeout' in provider and (type(provider['timeout']) is not int or not 5<=provider['timeout']<=600):raise _invalid()
        # The editor never persists plaintext keys, including accidental draft fields.
        provider.pop('key',None)
    if result['active'] and result['active'] not in seen:raise _invalid()
    return result


def load_chat_config(root):
    path=Path(root)/'chat.json'
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:return copy.deepcopy(CHAT_DEFAULT)
    except (OSError,ValueError,UnicodeError,RecursionError):
        raise OSError('无法读取 chat.json；请检查权限或从用户数据备份恢复，原文件未改动。') from None
    return _validated(value)


def select_chat_service(root,service,model=None):
    config=load_chat_config(root)
    config['service']=service
    if model is not None:config['chatgpt_model']=model
    atomic_json(Path(root)/'chat.json',_validated(config))


def _store(root):
    return SecretStore(Path(root)/'credentials.dpapi.json')


def _reference(provider):
    # Absence means a pre-versioned legacy slot. Empty string means explicitly cleared.
    return provider.get('credential_id',provider['id'])


def load_provider_key(root,provider):
    store=_store(root);reference=_reference(provider)
    if reference:return store.get(reference)
    store.read() # A damaged document must not look like a clean, empty key field.
    return ''


def provider_key_present(root,provider):
    return bool(_store(root).read().get(_reference(provider)))


def _preserve_references(candidate,persisted):
    previous={p['id']:p for p in persisted['providers']}
    for provider in candidate['providers']:
        old=previous.get(provider['id'])
        if old is not None:
            if 'credential_id' in old:provider['credential_id']=old['credential_id']
            else:provider.pop('credential_id',None)
        else:
            # New providers never adopt a stale deleted provider's orphaned slot.
            provider['credential_id']=''


def save_chat_config(root,config,provider_id=None,key=''):
    """Commit settings and an optional new key, returning a new configuration.

    Blank keys keep the *persisted* reference, including an explicit clear. A
    draft opened before clearing a key cannot silently resurrect that old key.
    """
    persisted=load_chat_config(root);store=_store(root);store.read()
    candidate=_validated(config);_preserve_references(candidate,persisted)
    if not isinstance(key,str):raise OSError('密钥格式无效。')
    provider=next((p for p in candidate['providers'] if p['id']==provider_id),None)
    if provider_id is not None and provider is None:raise OSError('待保存的模型服务不存在。')
    if key:
        if provider is None:raise OSError('请先选择需要保存密钥的服务。')
        reference='chat:'+provider['id']+':'+uuid.uuid4().hex
        store.put(reference,key)
        provider['credential_id']=reference
    atomic_json(Path(root)/'chat.json',candidate)
    return candidate


def _cleanup_keys(root,provider_id,old_provider,committed):
    """Remove only detached slots after the configuration commit succeeded."""
    store=_store(root)
    try:
        data=store.read();in_use={_reference(p) for p in committed['providers']}
        old_reference=_reference(old_provider) if old_provider else ''
        remove={name for name in data if name not in in_use and
                (name==provider_id or name==old_reference or name.startswith('chat:'+provider_id+':'))}
        if remove:atomic_json(store.path,{k:v for k,v in data.items() if k not in remove})
    except OSError:
        return '密钥已停用，但旧加密副本清理失败；请检查用户目录权限后再次清除。'
    return ''


def clear_provider_key(root,provider_id):
    """Clear only the saved key, without persisting unrelated editor drafts."""
    persisted=load_chat_config(root);_store(root).read()
    old=next((p for p in persisted['providers'] if p['id']==provider_id),None)
    candidate=copy.deepcopy(persisted)
    provider=next((p for p in candidate['providers'] if p['id']==provider_id),None)
    if provider is not None:
        provider['credential_id']=''
        atomic_json(Path(root)/'chat.json',candidate)
    return candidate,_cleanup_keys(root,provider_id,old,candidate)


def delete_chat_provider(root,config,provider_id):
    persisted=load_chat_config(root);_store(root).read()
    old=next((p for p in persisted['providers'] if p['id']==provider_id),None)
    candidate=_validated(config);_preserve_references(candidate,persisted)
    candidate['providers']=[p for p in candidate['providers'] if p['id']!=provider_id]
    if candidate['active']==provider_id:
        candidate['active']=candidate['providers'][0]['id'] if candidate['providers'] else ''
    atomic_json(Path(root)/'chat.json',candidate)
    return candidate,_cleanup_keys(root,provider_id,old,candidate)
