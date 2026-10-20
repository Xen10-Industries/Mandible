"""GitHub Releases update checker, downloader with SHA-256 verification, and installer launcher."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from ._version import __version__

GITHUB_REPO = "Xen10-Industries/Mandible"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
RELEASES_WEB_URL = f"https://github.com/{GITHUB_REPO}/releases"
CHECK_INTERVAL_S = 24 * 3600.0

ALLOWED_HOSTS = frozenset({
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})

_SEMVER_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-(?P<pre>[0-9A-Za-z.\-]+))?$"
)
_SETUP_RE = re.compile(r"^Mandible-[0-9A-Za-z.\-]+-Setup\.exe$", re.IGNORECASE)
_PORTABLE_RE = re.compile(
    r"^Mandible-[0-9A-Za-z.\-]+-(?:portable-win64|win64-portable)\.zip$",
    re.IGNORECASE,
)
_CHECKSUMS_NAME = "SHA256SUMS.txt"


@dataclass
class ReleaseInfo:
    version: str
    tag_name: str
    name: str
    body: str
    html_url: str
    prerelease: bool = False
    published_at: str = ""
    setup_url: str = ""
    setup_name: str = ""
    setup_size: int = 0
    portable_url: str = ""
    portable_name: str = ""
    portable_size: int = 0
    checksums_url: str = ""


def normalize_version(version: str) -> str:
    """Strip whitespace and a leading ``v`` / ``V`` from a version string."""
    v = (version or "").strip()
    if v.startswith(("v", "V")):
        v = v[1:].strip()
    return v


def parse_version(version: str) -> tuple[int, int, int, int, tuple]:
    """Parse a semver string into a comparable tuple ``(major, minor, patch, is_final, pre_parts)``.

    A final release ``0.1.2`` has ``is_final=1`` and ranks above pre-release ``0.1.2-rc.1``
    (``is_final=0``). Invalid strings return ``(0, 0, 0, -1, ())``.
    """
    m = _SEMVER_RE.match((version or "").strip())
    if not m:
        return (0, 0, 0, -1, ())
    major = int(m.group("major"))
    minor = int(m.group("minor"))
    patch = int(m.group("patch"))
    pre = m.group("pre")
    if not pre:
        return (major, minor, patch, 1, ())
    parts = tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in pre.split("."))
    return (major, minor, patch, 0, parts)


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    """Return True if ``candidate`` is a valid semver strictly newer than ``current``."""
    cand_parsed = parse_version(candidate)
    curr_parsed = parse_version(current)
    if cand_parsed[3] < 0 or curr_parsed[3] < 0:
        return False
    return cand_parsed > curr_parsed


def is_safe_github_url(url: str) -> bool:
    """Only allow HTTPS URLs hosted on official GitHub domains."""
    try:
        parsed = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host in ALLOWED_HOSTS or host.endswith(".githubusercontent.com")


def detect_install_mode() -> str:
    """Return ``'installer'``, ``'portable'`` or ``'source'`` for the running Mandible process."""
    if not getattr(sys, "frozen", False):
        return "source"
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    for marker in ("unins000.exe", "unins000.dat"):
        if os.path.isfile(os.path.join(exe_dir, marker)):
            return "installer"
    return "portable"


def select_latest_release(releases_data: list[dict], include_prereleases: bool = True) -> ReleaseInfo | None:
    """Pick the highest-version non-draft release from the GitHub Releases API JSON list."""
    if not isinstance(releases_data, list):
        return None
    best_key: tuple | None = None
    best_info: ReleaseInfo | None = None

    for item in releases_data:
        if not isinstance(item, dict) or item.get("draft", False):
            continue
        is_pre = bool(item.get("prerelease", False))
        if is_pre and not include_prereleases:
            continue
        tag = str(item.get("tag_name") or "").strip()
        key = parse_version(tag)
        if key[3] < 0:
            continue
        if best_key is not None and key <= best_key:
            continue

        html_url = str(item.get("html_url") or "")
        if not is_safe_github_url(html_url):
            html_url = RELEASES_WEB_URL

        info = ReleaseInfo(
            version=normalize_version(tag),
            tag_name=tag,
            name=str(item.get("name") or f"Mandible {normalize_version(tag)}").strip(),
            body=str(item.get("body") or "").strip(),
            html_url=html_url,
            prerelease=is_pre,
            published_at=str(item.get("published_at") or ""),
        )
        assets = item.get("assets")
        if isinstance(assets, list):
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                aname = str(asset.get("name") or "").strip()
                aurl = str(asset.get("browser_download_url") or "").strip()
                asize = int(asset.get("size") or 0)
                if not aname or os.path.basename(aname) != aname or not is_safe_github_url(aurl):
                    continue
                if _SETUP_RE.match(aname):
                    info.setup_url = aurl
                    info.setup_name = aname
                    info.setup_size = max(0, asize)
                elif _PORTABLE_RE.match(aname):
                    info.portable_url = aurl
                    info.portable_name = aname
                    info.portable_size = max(0, asize)
                elif aname == _CHECKSUMS_NAME:
                    info.checksums_url = aurl

        best_key = key
        best_info = info

    return best_info


def _open_url(url: str, timeout: float = 10.0, opener=None, accept: str = "*/*"):
    if not is_safe_github_url(url):
        raise ValueError(f"Refusing to connect to untrusted URL: {url!r}")
    req = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": f"Mandible/{__version__} (+https://github.com/{GITHUB_REPO})",
        },
    )
    open_fn = opener if opener is not None else urllib.request.urlopen
    return open_fn(req, timeout=timeout)


def fetch_releases(timeout: float = 10.0, opener=None) -> list[dict]:
    """Fetch the JSON release list from GitHub."""
    with _open_url(RELEASES_API_URL, timeout=timeout, opener=opener,
                   accept="application/vnd.github+json") as resp:
        raw = resp.read(2 * 1024 * 1024)  # cap API response at 2 MB
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Unexpected response format from GitHub Releases API")
    return data


def check_for_updates(
    current_version: str = __version__,
    include_prereleases: bool = True,
    timeout: float = 10.0,
    opener=None,
) -> tuple[ReleaseInfo | None, bool]:
    """Query GitHub Releases and return ``(latest_release, is_newer_than_current)``."""
    releases = fetch_releases(timeout=timeout, opener=opener)
    latest = select_latest_release(releases, include_prereleases=include_prereleases)
    if latest is None:
        return None, False
    return latest, is_newer_version(latest.version, current_version)


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse ``SHA256SUMS.txt`` content into ``{filename: sha256_hex_lower}``."""
    sums: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, fname = parts[0].strip().lower(), parts[1].strip().lstrip("*").strip()
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest) and fname:
            sums[os.path.basename(fname)] = digest
    return sums


def download_release_asset(
    url: str,
    filename: str,
    checksums_url: str = "",
    dest_dir: str | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout: float = 30.0,
    opener=None,
) -> str:
    """Download a release asset to ``dest_dir`` and verify its SHA-256 against ``SHA256SUMS.txt``.

    When ``checksums_url`` is given, the asset must appear in ``SHA256SUMS.txt`` and its SHA-256
    digest must match, or the partial file is removed and ``ValueError`` is raised.
    """
    clean_name = os.path.basename(filename or "")
    if not clean_name or clean_name != filename or clean_name in (".", ".."):
        raise ValueError(f"Invalid asset filename: {filename!r}")
    if not is_safe_github_url(url):
        raise ValueError(f"Untrusted asset download URL: {url!r}")

    expected_hash = ""
    if checksums_url:
        with _open_url(checksums_url, timeout=timeout, opener=opener) as resp:
            sums_text = resp.read(256 * 1024).decode("utf-8", errors="replace")
        sums = parse_sha256sums(sums_text)
        expected_hash = sums.get(clean_name, "")
        if not expected_hash:
            raise ValueError(f"{clean_name} was not found in SHA256SUMS.txt")

    target_dir = dest_dir or os.path.join(tempfile.gettempdir(), "Mandible-Update")
    os.makedirs(target_dir, exist_ok=True)
    part_path = os.path.join(target_dir, clean_name + ".part")
    final_path = os.path.join(target_dir, clean_name)

    hasher = hashlib.sha256()
    downloaded = 0
    try:
        with _open_url(url, timeout=timeout, opener=opener) as resp:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            with open(part_path, "wb") as out_fh:
                while True:
                    if cancel_check is not None and cancel_check():
                        raise InterruptedError("Download cancelled")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out_fh.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None:
                        progress_cb(downloaded, total)
    except BaseException:
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass
        raise

    actual_hash = hasher.hexdigest().lower()
    if expected_hash and actual_hash != expected_hash.lower():
        try:
            os.remove(part_path)
        except OSError:
            pass
        raise ValueError(
            f"SHA-256 checksum mismatch for {clean_name} "
            f"(expected {expected_hash[:12]}…, got {actual_hash[:12]}…)"
        )

    os.replace(part_path, final_path)
    return final_path


def launch_installer(installer_path: str, silent: bool = False) -> None:
    """Start the downloaded Inno Setup installer so it can upgrade and relaunch Mandible."""
    path = os.path.abspath(installer_path or "")
    if not os.path.isfile(path) or not path.lower().endswith(".exe"):
        raise ValueError(f"Installer executable not found: {installer_path!r}")
    args = [path, "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]
    if silent:
        args.append("/SILENT")
    subprocess.Popen(args, close_fds=True)
