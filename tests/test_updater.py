"""Tests for mandible.updater and mandible.ui.dialogs.updater."""
from __future__ import annotations

import hashlib
import io
import os

import pytest

from mandible import updater as U
from mandible.config import AppConfig
from mandible.ui.app import apply_theme
from mandible.ui.dialogs.updater import UpdateDialog
from mandible.ui.inspect import (
    find_clipped_text,
    find_overflow,
    off_scale_spacing,
    untiered_buttons,
)


SAMPLE_RELEASES = [
    {
        "tag_name": "v0.1.1",
        "name": "Mandible 0.1.1",
        "body": "Older release.",
        "html_url": "https://github.com/Xen10-Industries/Mandible/releases/tag/v0.1.1",
        "prerelease": False,
        "draft": False,
        "published_at": "2026-10-10T00:00:00Z",
        "assets": [],
    },
    {
        "tag_name": "v0.2.0",
        "name": "Mandible 0.2.0",
        "body": "### Added\n- Automatic update checker\n- Verified SHA-256 downloads",
        "html_url": "https://github.com/Xen10-Industries/Mandible/releases/tag/v0.2.0",
        "prerelease": True,
        "draft": False,
        "published_at": "2026-10-20T00:00:00Z",
        "assets": [
            {
                "name": "Mandible-0.2.0-Setup.exe",
                "browser_download_url": "https://github.com/Xen10-Industries/Mandible/releases/download/v0.2.0/Mandible-0.2.0-Setup.exe",
                "size": 104857600,
            },
            {
                "name": "Mandible-0.2.0-portable-win64.zip",
                "browser_download_url": "https://github.com/Xen10-Industries/Mandible/releases/download/v0.2.0/Mandible-0.2.0-portable-win64.zip",
                "size": 125829120,
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://github.com/Xen10-Industries/Mandible/releases/download/v0.2.0/SHA256SUMS.txt",
                "size": 256,
            },
        ],
    },
    {
        "tag_name": "v0.3.0",
        "name": "Draft release",
        "body": "Should be ignored because draft=True",
        "html_url": "https://github.com/Xen10-Industries/Mandible/releases/tag/v0.3.0",
        "prerelease": False,
        "draft": True,
        "published_at": "2026-10-21T00:00:00Z",
        "assets": [],
    },
]


# =============================================================== version parsing
def test_version_comparison():
    assert U.normalize_version("v0.1.2") == "0.1.2"
    assert U.is_newer_version("0.2.0", "0.1.2")
    assert U.is_newer_version("v0.1.3", "0.1.2")
    assert not U.is_newer_version("0.1.2", "0.1.2")
    assert not U.is_newer_version("0.1.1", "0.1.2")
    # Stable release is newer than pre-release of the same version
    assert U.is_newer_version("0.1.2", "0.1.2-beta.1")
    assert not U.is_newer_version("0.1.2-beta.1", "0.1.2")
    assert U.is_newer_version("0.1.3-alpha.1", "0.1.2")


def test_safe_github_url():
    assert U.is_safe_github_url("https://api.github.com/repos/Xen10-Industries/Mandible/releases")
    assert U.is_safe_github_url("https://github.com/Xen10-Industries/Mandible/releases/download/v0.1.2/Mandible-0.1.2-Setup.exe")
    assert U.is_safe_github_url("https://objects.githubusercontent.com/github-production-release-asset/123")
    assert not U.is_safe_github_url("http://github.com/Xen10-Industries/Mandible")
    assert not U.is_safe_github_url("https://evil.example.com/Mandible-Setup.exe")
    assert not U.is_safe_github_url("file:///C:/Windows/System32/calc.exe")
    assert not U.is_safe_github_url("")


def test_detect_install_mode(monkeypatch, tmp_path):
    monkeypatch.delattr(U.sys, "frozen", raising=False)
    assert U.detect_install_mode() == "source"

    fake_exe = tmp_path / "Mandible.exe"
    fake_exe.write_bytes(b"MZ")
    monkeypatch.setattr(U.sys, "frozen", True, raising=False)
    monkeypatch.setattr(U.sys, "executable", str(fake_exe))
    assert U.detect_install_mode() == "portable"

    (tmp_path / "unins000.exe").write_bytes(b"MZ")
    assert U.detect_install_mode() == "installer"


# =============================================================== release selection
def test_select_latest_release():
    rel_pre = U.select_latest_release(SAMPLE_RELEASES, include_prereleases=True)
    assert rel_pre is not None
    assert rel_pre.version == "0.2.0"
    assert rel_pre.prerelease is True
    assert rel_pre.setup_name == "Mandible-0.2.0-Setup.exe"
    assert rel_pre.portable_name == "Mandible-0.2.0-portable-win64.zip"
    assert rel_pre.checksums_url.endswith("SHA256SUMS.txt")

    rel_stable = U.select_latest_release(SAMPLE_RELEASES, include_prereleases=False)
    assert rel_stable is not None
    assert rel_stable.version == "0.1.1"
    assert rel_stable.prerelease is False


def test_check_for_updates(monkeypatch):
    monkeypatch.setattr(U, "fetch_releases", lambda timeout=10.0, opener=None: SAMPLE_RELEASES)
    # 0.2.0 > 0.1.2
    rel, is_newer = U.check_for_updates(current_version="0.1.2", include_prereleases=True)
    assert rel is not None
    assert rel.version == "0.2.0"
    assert is_newer is True

    # Already on 0.2.0 -> not newer
    rel2, is_newer2 = U.check_for_updates(current_version="0.2.0", include_prereleases=True)
    assert rel2 is not None
    assert is_newer2 is False

    # Stable-only when on 0.1.2 -> latest stable is 0.1.1 -> not newer
    rel3, is_newer3 = U.check_for_updates(current_version="0.1.2", include_prereleases=False)
    assert rel3 is not None
    assert rel3.version == "0.1.1"
    assert is_newer3 is False


# =============================================================== download & SHA-256 verification
def test_parse_sha256sums():
    text = (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  Mandible-0.2.0-Setup.exe\n"
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef *dist/Mandible-0.2.0-portable-win64.zip\n"
    )
    sums = U.parse_sha256sums(text)
    assert sums["Mandible-0.2.0-Setup.exe"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sums["Mandible-0.2.0-portable-win64.zip"] == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_download_release_asset_verifies_sha256(tmp_path):
    payload = b"Mandible installer payload bytes" * 1024
    digest = hashlib.sha256(payload).hexdigest()
    sums_text = f"{digest}  Mandible-0.2.0-Setup.exe\n".encode("utf-8")

    def fake_opener(req, timeout=30.0):
        url = req.full_url
        if url.endswith("SHA256SUMS.txt"):
            return _FakeResponse(sums_text)
        return _FakeResponse(payload)

    progress_calls = []
    out = U.download_release_asset(
        url="https://github.com/Xen10-Industries/Mandible/releases/download/v0.2.0/Mandible-0.2.0-Setup.exe",
        filename="Mandible-0.2.0-Setup.exe",
        dest_dir=str(tmp_path),
        checksums_url="https://github.com/Xen10-Industries/Mandible/releases/download/v0.2.0/SHA256SUMS.txt",
        progress_cb=lambda done, total: progress_calls.append((done, total)),
        opener=fake_opener,
    )
    assert os.path.isfile(out)
    assert open(out, "rb").read() == payload
    assert progress_calls[-1] == (len(payload), len(payload))


def test_download_release_asset_rejects_bad_sha256(tmp_path):
    payload = b"corrupted payload"
    wrong_digest = "0" * 64
    sums_text = f"{wrong_digest}  Mandible-0.2.0-Setup.exe\n".encode("utf-8")

    def fake_opener(req, timeout=30.0):
        if req.full_url.endswith("SHA256SUMS.txt"):
            return _FakeResponse(sums_text)
        return _FakeResponse(payload)

    with pytest.raises(ValueError, match="SHA-256 checksum mismatch"):
        U.download_release_asset(
            url="https://github.com/Xen10-Industries/Mandible/releases/download/v0.2.0/Mandible-0.2.0-Setup.exe",
            filename="Mandible-0.2.0-Setup.exe",
            dest_dir=str(tmp_path),
            checksums_url="https://github.com/Xen10-Industries/Mandible/releases/download/v0.2.0/SHA256SUMS.txt",
            opener=fake_opener,
        )
    assert not (tmp_path / "Mandible-0.2.0-Setup.exe").exists()
    assert not (tmp_path / "Mandible-0.2.0-Setup.exe.part").exists()


def test_launch_installer(monkeypatch, tmp_path):
    exe = tmp_path / "Mandible-0.2.0-Setup.exe"
    exe.write_bytes(b"MZ")
    launched = []
    monkeypatch.setattr(U.subprocess, "Popen", lambda args, **kw: launched.append((args, kw)))
    U.launch_installer(str(exe), silent=False)
    assert len(launched) == 1
    assert launched[0][0] == [str(exe), "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"]


# =============================================================== UI dialog & integration
def test_update_dialog_ui_compliance_and_states(qapp, tmp_path, monkeypatch):
    from mandible.core import Core

    apply_theme(qapp)
    cfg = AppConfig()
    core = Core(cfg)
    rel = U.select_latest_release(SAMPLE_RELEASES, include_prereleases=True)
    dlg = UpdateDialog(core, initial_release=rel, auto_check=False)
    dlg.show()
    for _ in range(3):
        qapp.processEvents()

    assert not off_scale_spacing(dlg)
    assert not untiered_buttons(dlg)
    assert not find_clipped_text(dlg)
    assert not find_overflow(dlg)
    assert "0.2.0" in dlg.status_title.text()
    assert dlg.action_btn.isVisible()

    # Switch to up-to-date state
    dlg._on_check_finished(rel, False, "")
    qapp.processEvents()
    assert "latest version" in dlg.status_title.text()
    assert not dlg.action_btn.isVisible()

    # Switch to error state
    dlg._on_check_finished(None, False, "Network unreachable")
    qapp.processEvents()
    assert "Could not check" in dlg.status_title.text()
    dlg.close()
    core.shutdown()


def test_main_window_and_settings_update_integration(qapp, monkeypatch):
    from mandible.core import Core
    from mandible.ui.dialogs.settings import SettingsDialog
    from mandible.ui.main_window import MainWindow

    apply_theme(qapp)
    cfg = AppConfig(close_to_tray=False)
    core = Core(cfg)
    win = MainWindow(core, show_tray=False)
    rel = U.select_latest_release(SAMPLE_RELEASES, include_prereleases=True)
    assert rel is not None

    win._on_update_found(rel)
    assert win._available_update == rel
    assert "v0.2.0" in win.update_action.text()
    assert "v0.2.0" in win.act_update.text()
    assert win.header.help_btn.property("state") == "warn"

    settings = SettingsDialog(core, False, None)
    assert settings.auto_updates.isChecked() is True
    assert settings.prerelease_updates.isChecked() is True
    settings.auto_updates.setChecked(False)
    settings.prerelease_updates.setChecked(False)
    settings.apply_all()
    assert cfg.auto_check_updates is False
    assert cfg.check_prereleases is False

    settings.close()
    win.meter_timer.stop()
    win.status_timer.stop()
    win._quitting = True
    win.close()
    core.shutdown()
