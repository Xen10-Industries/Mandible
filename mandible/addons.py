"""Mandible Add-on Registry and Manager.

Provides:
- Registry of official Mandible add-ons (Clarity, RVC, Stream Deck, etc.).
- Detection of installation status and local installed versions.
- GitHub Releases update checking for add-ons.
- Automatic background checks on startup with desktop notifications.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .paths import APP_DIR
from .updater import is_newer_version, is_safe_github_url, parse_version

TOOLS_DIR = os.path.abspath(os.path.join(APP_DIR, "tools"))


@dataclass
class AddonInfo:
    id: str
    name: str
    repo: str
    summary: str
    category: str
    find_exe_fn: Callable[[], str | None]
    download_fn: Callable[[Callable[[int, int], None] | None], str]
    open_dialog_fn: Callable[[object], None]
    default_version: str = "v0.1.0"
    icon: str = ""


def _find_rvc_exe() -> str | None:
    from .ai_trainer import find_mandible_rvc_exe
    return find_mandible_rvc_exe()


def _download_rvc(progress_cb=None) -> str:
    from .ai_trainer import download_and_install_rvc_addon
    return download_and_install_rvc_addon(progress_cb=progress_cb)


def _open_rvc_dialog(parent) -> None:
    from .ui.dialogs.ai_trainer import RVCAddonDialog
    dlg = RVCAddonDialog(parent)
    dlg.exec()


def _find_clarity_exe() -> str | None:
    from .clarity import find_mandible_clarity_exe
    return find_mandible_clarity_exe()


def _download_clarity(progress_cb=None) -> str:
    from .clarity import download_and_install_clarity_addon
    return download_and_install_clarity_addon(progress_cb=progress_cb)


def _open_clarity_dialog(parent) -> None:
    from .ui.dialogs.clarity import ClarityAddonDialog
    dlg = ClarityAddonDialog(parent)
    dlg.exec()


ADDON_REGISTRY: dict[str, AddonInfo] = {
    "clarity": AddonInfo(
        id="clarity",
        name="Mandible Clarity",
        repo="Xen10-Industries/mandible-clarity",
        summary="DeepFilterNet3 AI vocal studio enhancement: removes mechanical keyboard clicks, HVAC hum, and flutter echo.",
        category="Audio AI",
        find_exe_fn=_find_clarity_exe,
        download_fn=_download_clarity,
        open_dialog_fn=_open_clarity_dialog,
        default_version="v0.1.0",
    ),
    "rvc": AddonInfo(
        id="rvc",
        name="Mandible RVC",
        repo="Xen10-Industries/mandible-rvc",
        summary="Retrieval-based Voice Conversion companion for offline AI vocal timbre cloning and model training.",
        category="Voice AI",
        find_exe_fn=_find_rvc_exe,
        download_fn=_download_rvc,
        open_dialog_fn=_open_rvc_dialog,
        default_version="v0.1.0",
    ),
    "streamdeck": AddonInfo(
        id="streamdeck",
        name="Mandible Stream Deck Plugin",
        repo="Xen10-Industries/mandible-streamdeck",
        summary="Official Elgato Stream Deck plugin with dynamic preset buttons, active chain status, and soundboard keys.",
        category="Integration",
        find_exe_fn=lambda: None,
        download_fn=lambda cb=None: "",
        open_dialog_fn=lambda p: None,
        default_version="v0.1.0",
    ),
}


def get_addon_installed_version(addon_id: str) -> str | None:
    """Read local version for an installed add-on."""
    info = ADDON_REGISTRY.get(addon_id)
    if not info:
        return None
    exe = info.find_exe_fn()
    if not exe:
        return None

    # Check for version file or pyproject.toml next to the executable / package
    base_dirs = [
        os.path.dirname(exe),
        os.path.dirname(os.path.dirname(exe)),
        os.path.join(TOOLS_DIR, f"mandible-{addon_id}"),
    ]
    for d in base_dirs:
        ver_file = os.path.join(d, "VERSION")
        if os.path.isfile(ver_file):
            try:
                with open(ver_file, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                    if txt:
                        return txt
            except Exception:
                pass

        pyproject = os.path.join(d, "pyproject.toml")
        if os.path.isfile(pyproject):
            try:
                with open(pyproject, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("version"):
                            m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', line)
                            if m:
                                return m.group(1)
            except Exception:
                pass

    return info.default_version


def check_addon_update(addon_id: str, timeout: float = 6.0) -> tuple[str | None, bool]:
    """Check GitHub Releases for the given add-on.

    Returns ``(latest_tag, is_newer)``.
    """
    info = ADDON_REGISTRY.get(addon_id)
    if not info or not info.repo:
        return (None, False)

    current = get_addon_installed_version(addon_id)
    if not current:
        return (None, False)

    url = f"https://api.github.com/repos/{info.repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mandible-App", "Accept": "application/vnd.github.v3+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag = str(data.get("tag_name") or "").strip()
            if not tag:
                return (None, False)
            newer = is_newer_version(tag, current)
            return (tag, newer)
    except Exception:
        return (None, False)
