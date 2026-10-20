"""Software update dialog: checks GitHub Releases, displays release notes, and downloads/launches updates."""
from __future__ import annotations

import os
import threading
import time
import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QProgressBar, QVBoxLayout)

from ... import APP_NAME, __version__
from ... import updater as U
from ...core import Core
from ..look import font_px
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width, set_style_property
from ..widgets.buttons import make_button
from .parts import group_label, hint_label, keep_wrapped_text_visible


def _format_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MB"


class UpdateDialog(QDialog):
    """Checks GitHub Releases for a newer Mandible version and downloads / installs it."""

    _checkFinished = Signal(object, bool, str)     # (ReleaseInfo | None, is_newer, error_msg)
    _downloadProgress = Signal(int, int)           # (downloaded_bytes, total_bytes)
    _downloadFinished = Signal(str, str)           # (file_path, error_msg)

    def __init__(
        self,
        core: Core | None = None,
        parent=None,
        *,
        initial_release: U.ReleaseInfo | None = None,
        auto_check: bool = True,
    ):
        super().__init__(parent)
        self.core = core
        self.release: U.ReleaseInfo | None = initial_release
        self.is_newer: bool = bool(initial_release and U.is_newer_version(initial_release.version, __version__))
        self._checking = False
        self._downloading = False
        self._cancel_download = False
        self._spaced = SpacedLayouts()
        _follow_look(self)

        self.setWindowTitle(f"Check for updates — {APP_NAME}")
        self.setMinimumSize(520, 380)
        self.resize(700, 480)

        lay = self._spaced.add(QVBoxLayout(self), spacing=3, margins=4)

        # Status card (reuses wizardCard styling tokens: neutral, ok, warn)
        self.status_card = QFrame()
        self.status_card.setObjectName("wizardCard")
        card_lay = self._spaced.add(QVBoxLayout(self.status_card), spacing=1, margins=3)

        self.status_title = QLabel(f"Installed version: {APP_NAME} {__version__}")
        self.status_title.setObjectName("wizardCardTitle")
        self.status_title.setWordWrap(True)
        card_lay.addWidget(self.status_title)

        self.status_desc = QLabel("Ready to check GitHub Releases for updates.")
        self.status_desc.setObjectName("wizardCardDesc")
        self.status_desc.setWordWrap(True)
        card_lay.addWidget(self.status_desc)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        card_lay.addWidget(self.progress_bar)

        lay.addWidget(self.status_card)

        # Release notes
        group_label(lay, "Release notes")
        self.notes_view = QPlainTextEdit()
        self.notes_view.setReadOnly(True)
        self.notes_view.setPlaceholderText("Release notes will appear here after checking GitHub Releases.")
        self._apply_notes_font()
        lay.addWidget(self.notes_view, 1)

        self.security_hint = hint_label(
            "Downloaded installers are verified against the release's SHA256SUMS.txt before running."
        )
        lay.addWidget(self.security_hint)

        # Bottom action row (at most one primary button: self.action_btn)
        btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.check_btn = make_button("Check again", "secondary",
                                     tooltip="Query GitHub Releases for the latest version")
        self.web_btn = make_button("View on GitHub", "secondary",
                                   tooltip="Open the release page in your web browser")
        btn_row.addWidget(self.check_btn)
        btn_row.addWidget(self.web_btn)
        btn_row.addStretch(1)

        self.action_btn = make_button("Download and install", "primary",
                                      tooltip="Download the verified installer and update Mandible")
        self.action_btn.setVisible(False)
        self.close_btn = make_button("Close", "secondary")
        btn_row.addWidget(self.action_btn)
        btn_row.addWidget(self.close_btn)
        lay.addLayout(btn_row)
        for btn in (self.check_btn, self.web_btn, self.close_btn):
            reserve_text_width(btn, btn.text())
        reserve_text_width(
            self.action_btn,
            "Download and install",
            "Download installer",
            "Download portable zip",
            "Cancel download",
        )

        self._checkFinished.connect(self._on_check_finished)
        self._downloadProgress.connect(self._on_download_progress)
        self._downloadFinished.connect(self._on_download_finished)

        self.check_btn.clicked.connect(self.start_check)
        self.web_btn.clicked.connect(self._open_release_page)
        self.action_btn.clicked.connect(self._on_action_clicked)
        self.close_btn.clicked.connect(self.reject)

        keep_wrapped_text_visible(self)

        if initial_release is not None:
            self._apply_release_state(initial_release, self.is_newer)
        elif auto_check:
            self.start_check()

    def _apply_notes_font(self) -> None:
        font = QFont("Consolas")
        font.setPixelSize(font_px("body"))
        self.notes_view.setFont(font)

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._apply_notes_font()

    def _set_card_state(self, state: str) -> None:
        for w in (self.status_card, self.status_title):
            set_style_property(w, "state", state)

    def _include_prereleases(self) -> bool:
        if self.core is not None:
            return bool(getattr(self.core.cfg, "check_prereleases", True))
        return True

    # ------------------------------------------------------------------ Checking
    def start_check(self) -> None:
        if self._checking or self._downloading:
            return
        self._checking = True
        self._set_card_state("")
        self.status_title.setText("Checking for updates…")
        self.status_desc.setText(f"Current version: {__version__}. Contacting GitHub Releases…")
        self.check_btn.setEnabled(False)
        self.action_btn.setVisible(False)
        inc_pre = self._include_prereleases()

        def worker():
            try:
                rel, newer = U.check_for_updates(
                    current_version=__version__,
                    include_prereleases=inc_pre,
                )
                self._checkFinished.emit(rel, newer, "")
            except Exception as exc:
                self._checkFinished.emit(None, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_check_finished(self, release: U.ReleaseInfo | None, is_newer: bool, error: str) -> None:
        self._checking = False
        self.check_btn.setEnabled(True)
        if self.core is not None and not error:
            self.core.cfg.last_update_check = time.time()
            self.core.save()

        if error:
            self._set_card_state("warn")
            self.status_title.setText("Could not check for updates")
            self.status_desc.setText(error)
            self.action_btn.setVisible(False)
            return

        if release is None:
            self._set_card_state("")
            self.status_title.setText(f"{APP_NAME} {__version__} is up to date")
            self.status_desc.setText("No published releases were found on GitHub.")
            self.notes_view.setPlainText("")
            self.action_btn.setVisible(False)
            return

        self._apply_release_state(release, is_newer)

    def _apply_release_state(self, release: U.ReleaseInfo, is_newer: bool) -> None:
        self.release = release
        self.is_newer = is_newer
        notes = release.body or f"{release.name} ({release.tag_name}) has no release notes."
        self.notes_view.setPlainText(notes)

        if not is_newer:
            self._set_card_state("ok")
            self.status_title.setText(f"You are running the latest version ({__version__})")
            self.status_desc.setText(f"Latest release on GitHub: {release.name} ({release.tag_name}).")
            self.action_btn.setVisible(False)
            return

        self._set_card_state("warn")
        pre_tag = " (pre-release)" if release.prerelease else ""
        self.status_title.setText(f"Update available: {release.name}{pre_tag}")
        mode = U.detect_install_mode()
        if release.setup_url:
            size_txt = f" ({_format_mb(release.setup_size)})" if release.setup_size > 0 else ""
            if mode == "installer":
                self.status_desc.setText(
                    f"Installed: {__version__}  ·  New: {release.version}{size_txt}. "
                    "Click Download and install to update automatically."
                )
                self.action_btn.setText("Download and install")
            else:
                self.status_desc.setText(
                    f"Current: {__version__} ({mode} build)  ·  New: {release.version}{size_txt}. "
                    "Click Download installer to fetch the verified setup executable."
                )
                self.action_btn.setText("Download installer")
            self.action_btn.setVisible(True)
            self.action_btn.setEnabled(True)
        elif release.portable_url:
            self.status_desc.setText(
                f"Current: {__version__}  ·  New: {release.version}. "
                "Click Download portable zip to save the verified archive."
            )
            self.action_btn.setText("Download portable zip")
            self.action_btn.setVisible(True)
            self.action_btn.setEnabled(True)
        else:
            self.status_desc.setText(
                f"Current: {__version__}  ·  New: {release.version}. "
                "Open the GitHub release page to download it."
            )
            self.action_btn.setVisible(False)

    # ------------------------------------------------------------------ Downloading & Installing
    def _on_action_clicked(self) -> None:
        if self._downloading:
            self._cancel_download = True
            self.action_btn.setEnabled(False)
            self.status_desc.setText("Cancelling download…")
            return
        if self.release is None:
            return
        if self.release.setup_url and self.release.setup_name:
            url, fname = self.release.setup_url, self.release.setup_name
        elif self.release.portable_url and self.release.portable_name:
            url, fname = self.release.portable_url, self.release.portable_name
        else:
            self._open_release_page()
            return
        self.start_download(url, fname, self.release.checksums_url)

    def start_download(self, url: str, filename: str, checksums_url: str = "") -> None:
        if self._downloading:
            return
        self._downloading = True
        self._cancel_download = False
        self.check_btn.setEnabled(False)
        self.action_btn.setText("Cancel download")
        self.action_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_title.setText(f"Downloading {filename}…")
        self.status_desc.setText("Verifying checksum manifest and starting download…")

        def progress(done: int, total: int):
            self._downloadProgress.emit(done, total)

        def cancelled() -> bool:
            return self._cancel_download

        def worker():
            try:
                path = U.download_release_asset(
                    url=url,
                    filename=filename,
                    checksums_url=checksums_url,
                    progress_cb=progress,
                    cancel_check=cancelled,
                )
                self._downloadFinished.emit(path, "")
            except InterruptedError:
                self._downloadFinished.emit("", "Download cancelled.")
            except Exception as exc:
                self._downloadFinished.emit("", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = max(0, min(100, int(round(done * 100.0 / total))))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.status_desc.setText(f"Downloaded {_format_mb(done)} of {_format_mb(total)} ({pct}%)…")
        else:
            self.progress_bar.setRange(0, 0)
            self.status_desc.setText(f"Downloaded {_format_mb(done)}…")

    def _on_download_finished(self, file_path: str, error: str) -> None:
        self._downloading = False
        self.progress_bar.setVisible(False)
        self.check_btn.setEnabled(True)

        if error or not file_path:
            self._set_card_state("warn")
            self.status_title.setText("Update download did not complete")
            self.status_desc.setText(error or "Unknown download error.")
            if self.release is not None:
                self.action_btn.setText(
                    "Download and install" if U.detect_install_mode() == "installer" else "Download installer"
                )
                self.action_btn.setEnabled(True)
            return

        self._set_card_state("ok")
        self.status_title.setText("Download complete (SHA-256 verified)")
        self.status_desc.setText(f"Saved to {file_path}")
        self.action_btn.setVisible(False)

        if file_path.lower().endswith(".exe"):
            ans = QMessageBox.question(
                self,
                "Install update",
                f"{os.path.basename(file_path)} has been downloaded and verified.\n\n"
                f"Run the installer now? {APP_NAME} will close so the update can be installed.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Yes:
                try:
                    U.launch_installer(file_path)
                except Exception as exc:
                    QMessageBox.warning(self, "Could not start installer", str(exc))
                    return
                self._quit_application()
        else:
            folder = os.path.dirname(file_path)
            if os.path.isdir(folder) and hasattr(os, "startfile"):
                try:
                    os.startfile(folder)
                except OSError:
                    pass

    def _quit_application(self) -> None:
        parent = self.parentWidget()
        self.accept()
        while parent is not None:
            if hasattr(parent, "quit") and callable(parent.quit):
                parent.quit()
                return
            parent = parent.parentWidget()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _open_release_page(self) -> None:
        url = self.release.html_url if (self.release and self.release.html_url) else U.RELEASES_WEB_URL
        if U.is_safe_github_url(url):
            webbrowser.open(url)

    def reject(self) -> None:
        if self._downloading:
            self._cancel_download = True
        super().reject()
