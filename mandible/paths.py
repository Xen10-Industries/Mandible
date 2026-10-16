"""User data locations for Mandible (kept free of heavy imports so logging can start early)."""
from __future__ import annotations

import os
import shutil

_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))

APP_DIR = os.path.join(_APPDATA, "Xen10", "Mandible")
LOG_PATH = os.path.join(APP_DIR, "mandible.log")

# Pre-release builds were called "VoiceFX" and stored data in %APPDATA%\VoiceFX.
LEGACY_APP_DIR = os.path.join(_APPDATA, "VoiceFX")
_LEGACY_FILES = ("config.json", "plugin_cache.json")
_MIGRATION_MARKER = "migrated_from_voicefx.txt"


def migrate_legacy_data() -> bool:
    """Copy config and plugin cache from the old VoiceFX folder on first launch.

    The legacy folder is left untouched so nothing is lost if the copy is incomplete.
    Returns True if anything was copied.
    """
    if os.path.exists(os.path.join(APP_DIR, "config.json")) or not os.path.isdir(LEGACY_APP_DIR):
        return False
    copied = False
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        for name in _LEGACY_FILES:
            src = os.path.join(LEGACY_APP_DIR, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(APP_DIR, name))
                copied = True
        if copied:
            with open(os.path.join(APP_DIR, _MIGRATION_MARKER), "w", encoding="utf-8") as fh:
                fh.write(f"Settings copied from {LEGACY_APP_DIR}. The original folder was not modified.\n")
    except OSError as exc:
        print(f"[Mandible] could not migrate legacy VoiceFX data: {exc}")
    return copied


def migrate_legacy_startup_entry() -> None:
    """Remove the old 'VoiceFX' Run key (it points at the old exe); the caller re-registers Mandible."""
    try:
        import winreg
        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "VoiceFX")
    except (FileNotFoundError, OSError, ImportError):
        pass
