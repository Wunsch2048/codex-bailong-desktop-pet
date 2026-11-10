"""Per-platform user data folder.

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
