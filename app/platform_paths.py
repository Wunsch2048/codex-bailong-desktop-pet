"""Per-platform user data folder and program root.

Windows and Linux keep the original LOCALAPPDATA expression unchanged. Only
macOS, where LOCALAPPDATA is normally unset, falls back to Application Support.
"""
import os,sys
from pathlib import Path

MACOS=sys.platform=='darwin'
APP_ID='BailongEnhanced'

def local_appdata(fallback=None):
    """Parent of the data folder; fallback replaces the home-directory default outside macOS."""
    if MACOS:
        # An explicit LOCALAPPDATA still isolates tests and QA runs on macOS.
        value=os.environ.get('LOCALAPPDATA')
        return Path(value) if value else Path.home()/'Library/Application Support'
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home() if fallback is None else fallback)))

def data_dir(fallback=None):return local_appdata(fallback)/APP_ID

def app_root():
    """Folder holding app/ and outputs/: the source tree, the frozen program folder, or a macOS bundle's Resources.

    Windows and Linux keep the original expression unchanged:
    Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[1]
    """
    if getattr(sys,'frozen',False):
        exe=Path(sys.executable).resolve()
        # Only a real Name.app/Contents/MacOS layout maps to Contents/Resources;
        # a plain folder that happens to be called MacOS keeps the executable folder.
        bundle=exe.parent.name=='MacOS' and exe.parents[1].name=='Contents' and exe.parents[2].suffix=='.app'
        return exe.parents[1]/'Resources' if MACOS and bundle else exe.parent
    return Path(__file__).resolve().parents[1]
