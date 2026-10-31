"""Remove optional Qt features only when remaining PE imports stay satisfied."""
from pathlib import Path
import pefile

OPTIONAL={'qpdf.dll','Qt6Pdf.dll','qtvirtualkeyboardplugin.dll','Qt6VirtualKeyboard.dll',
          'Qt6Quick.dll','Qt6Qml.dll','Qt6QmlMeta.dll','Qt6QmlModels.dll','Qt6QmlWorkerScript.dll','Qt6OpenGL.dll'}
def trim_qt(folder):
    folder=Path(folder).resolve();internal=folder/'_internal';qt=internal/'PySide6'
    paths=[p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ('.dll','.pyd','.exe')]
    imports={}
    for p in paths:
        try:
            with pefile.PE(str(p),fast_load=True) as pe:
                pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
                imports[p]={x.dll.decode().lower() for attr in ('DIRECTORY_ENTRY_IMPORT','DIRECTORY_ENTRY_DELAY_IMPORT') for x in getattr(pe,attr,[])}
        except pefile.PEFormatError:imports[p]=set()
    def managed(path):
        if not path.resolve().is_relative_to(internal.resolve()):return False
        parts=path.relative_to(folder).parts
        chain=[folder.joinpath(*parts[:i]) for i in range(1,len(parts)+1)]
        return not any(part.is_symlink() or part.is_junction() for part in chain)
    # PyInstaller puts Qt DLLs beside python312.dll in newer layouts, while
    # plugins still live under PySide6. Keep the same exact feature allowlist.
    removable={p for p in paths if (p.parent==internal or p.is_relative_to(qt)) and p.name in OPTIONAL and managed(p)}
    while True:
        required=set().union(*(deps for p,deps in imports.items() if p not in removable))
        keep={p for p in removable if p.name.lower() in required}
        if not keep:break
        removable-=keep
    removed=[]
    for p in sorted(removable):
        assert managed(p)
        removed.append(dict(path=p.relative_to(folder).as_posix(),bytes=p.stat().st_size));p.unlink()
    removed_names={Path(x['path']).name.lower() for x in removed}
    assert not any(deps&removed_names for p,deps in imports.items() if p not in removable)
    return dict(passed=True,removed=removed,savedBytes=sum(x['bytes'] for x in removed),remainingNativeImportsVerified=True)
