"""Mandible Clarity Add-on manager dialog."""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from ...clarity import (
    MANDIBLE_CLARITY_DIR,
    detect_clarity_hardware,
    download_and_install_clarity_addon,
    find_mandible_clarity_exe,
)
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width, set_style_property
from ..widgets.buttons import make_button
from .parts import group_label, hint_label, keep_wrapped_text_visible


class ClarityAddonDialog(QDialog):
    """Dialog for inspecting, downloading, and managing the Mandible Clarity studio de-noising add-on."""

    addonInstalled = Signal(str)
    _downloadProgress = Signal(int, int)
    _downloadFinished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spaced = SpacedLayouts()
        self._downloading = False
        _follow_look(self)

        self.setWindowTitle("Mandible Clarity Add-on")
        self.setMinimumWidth(640)
        self.resize(700, 500)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        self.card = QFrame()
        self.card.setObjectName("wizardCard")
        self.card_lay = self._spaced.add(QVBoxLayout(self.card), spacing=1, margins=3)

        self.title_lbl = QLabel("Mandible Clarity Deep-Learning Add-on")
        self.title_lbl.setObjectName("wizardCardTitle")
        self.title_lbl.setWordWrap(True)
        self.card_lay.addWidget(self.title_lbl)

        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("wizardCardDesc")
        self.status_lbl.setWordWrap(True)
        self.card_lay.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.card_lay.addWidget(self.progress_bar)

        lay.addWidget(self.card)

        # Hardware acceleration status
        group_label(lay, "Hardware acceleration")
        _, dev_name, backend_desc = detect_clarity_hardware()
        self.hw_lbl = hint_label(f"Processor: {dev_name}  ·  Inference Engine: {backend_desc}")
        lay.addWidget(self.hw_lbl)

        group_label(lay, "Add-on overview")
        lay.addWidget(
            hint_label(
                "Mandible Clarity provides deep-learning vocal enhancement via DeepFilterNet3 and ONNX Runtime. "
                "Unlike standard noise suppressors, Clarity operates at full 48 kHz studio bandwidth, strips out "
                "room reverberation and untreated flutter echo, and eliminates mechanical keyboard clatter and HVAC hum."
            )
        )

        group_label(lay, "Installation location")
        self.location_lbl = hint_label(f"Installed at: {MANDIBLE_CLARITY_DIR}")
        lay.addWidget(self.location_lbl)

        lay.addStretch(1)

        btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.download_btn = make_button("Download & install add-on", "primary")
        self.folder_btn = make_button("Open tools folder…", "secondary", tooltip=f"Open {MANDIBLE_CLARITY_DIR} in Explorer")
        self.close_btn = make_button("Close", "secondary")

        btn_row.addWidget(self.download_btn)
        btn_row.addWidget(self.folder_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        lay.addLayout(btn_row)

        self.download_btn.clicked.connect(self._on_download_addon)
        self.folder_btn.clicked.connect(self._open_folder)
        self.close_btn.clicked.connect(self.accept)

        self._downloadProgress.connect(self._on_download_progress)
        self._downloadFinished.connect(self._on_download_finished)

        self._refresh_installed_state()
        self._reserve_button_widths()
        keep_wrapped_text_visible(self)

    def _reserve_button_widths(self) -> None:
        for btn in (self.download_btn, self.folder_btn, self.close_btn):
            reserve_text_width(btn, btn.text())

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._reserve_button_widths()

    def _refresh_installed_state(self) -> None:
        exe = find_mandible_clarity_exe()
        if exe:
            set_style_property(self.card, "state", "ok")
            set_style_property(self.title_lbl, "state", "ok")
            self.status_lbl.setText(f"Status: Installed (ready) — detected at {exe}")
            self.location_lbl.setText(f"Executable: {exe}")
            self.download_btn.setText("Reinstall add-on")
            self.download_btn.setEnabled(True)
        else:
            set_style_property(self.card, "state", "default")
            set_style_property(self.title_lbl, "state", "default")
            self.status_lbl.setText("Status: Not installed on this PC.")
            self.location_lbl.setText(f"Target directory: {MANDIBLE_CLARITY_DIR}")
            self.download_btn.setText("Download & install add-on")
            self.download_btn.setEnabled(True)
        self._reserve_button_widths()

    def _open_folder(self) -> None:
        os.makedirs(MANDIBLE_CLARITY_DIR, exist_ok=True)
        if hasattr(os, "startfile"):
            try:
                os.startfile(MANDIBLE_CLARITY_DIR)
            except OSError:
                pass

    def _on_download_addon(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self.download_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_lbl.setText("Downloading Mandible Clarity add-on release from GitHub…")

        def _worker():
            def _prog(cur: int, tot: int):
                self._downloadProgress.emit(cur, tot)

            try:
                exe = download_and_install_clarity_addon(progress_cb=_prog)
                self._downloadFinished.emit(True, exe)
            except Exception as exc:
                self._downloadFinished.emit(False, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_download_progress(self, current: int, total: int) -> None:
        if total > 0:
            pct = int(current * 100 / total)
            mb = total / (1024 * 1024)
            self.progress_bar.setValue(pct)
            self.status_lbl.setText(f"Downloading Mandible Clarity add-on ({pct}% of {mb:.1f} MB)…")

    def _on_download_finished(self, success: bool, msg: str) -> None:
        self._downloading = False
        self.progress_bar.setVisible(False)
        self._refresh_installed_state()
        if success:
            self.addonInstalled.emit(msg)
            QMessageBox.information(
                self,
                "Add-on Installed",
                f"Mandible Clarity add-on was installed successfully!\n\nLocation: {msg}",
            )
        else:
            QMessageBox.warning(
                self,
                "Installation Failed",
                f"Could not download Mandible Clarity add-on:\n\n{msg}\n\n"
                "You can also download it manually or build it from source.",
            )
