"""GitHub Voice Model Hub browser dialog: browse, filter, and download neural ``.onnx`` voice models."""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from ...ai_voice import (
    AI_MODELS_DIR,
    DEFAULT_REMOTE_MODELS,
    GITHUB_MODELS_REPO,
    RemoteVoiceModelInfo,
    download_remote_voice_model,
    fetch_remote_voice_models,
    is_remote_model_installed,
)
from ...core import Core
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width, set_style_property
from ..widgets.buttons import make_button
from .parts import group_label, hint_label, keep_wrapped_text_visible


class ModelHubDialog(QDialog):
    """Browse neural ``.onnx`` voice models hosted on GitHub and download them into ``ai_models``."""

    _catalogLoaded = Signal(object)            # list[RemoteVoiceModelInfo]
    _downloadProgress = Signal(int, int)       # (read_bytes, total_bytes)
    _downloadFinished = Signal(object, str)    # (VoiceModelInfo | None, error_msg)

    def __init__(
        self,
        core: Core | None = None,
        parent=None,
        *,
        models_dir: str | None = None,
        auto_fetch: bool = True,
    ):
        super().__init__(parent)
        self.core = core
        self.models_dir = models_dir or AI_MODELS_DIR
        self._remote_models: list[RemoteVoiceModelInfo] = list(DEFAULT_REMOTE_MODELS)
        self._downloading = False
        self._downloaded_model_id: str = ""
        self._spaced = SpacedLayouts()
        _follow_look(self)

        self.setWindowTitle("Browse AI Voice Models — GitHub Hub")
        self.setMinimumWidth(640)
        self.resize(740, 560)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        # Status card
        self.status_card = QFrame()
        self.status_card.setObjectName("wizardCard")
        set_style_property(self.status_card, "state", "ok")
        card_lay = self._spaced.add(QVBoxLayout(self.status_card), spacing=1, margins=3)

        self.status_title = QLabel(f"GitHub Voice Model Hub ({GITHUB_MODELS_REPO})")
        self.status_title.setObjectName("wizardCardTitle")
        set_style_property(self.status_title, "state", "ok")
        self.status_title.setWordWrap(True)
        card_lay.addWidget(self.status_title)

        self.status_desc = QLabel(
            "Select a neural RVC .onnx voice model below to download it into your local voice library."
        )
        self.status_desc.setObjectName("wizardCardDesc")
        self.status_desc.setWordWrap(True)
        card_lay.addWidget(self.status_desc)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        card_lay.addWidget(self.progress_bar)
        lay.addWidget(self.status_card)

        # Search + Refresh row
        search_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter models by name, tag, or author…")
        self.search_edit.setClearButtonEnabled(True)
        self.refresh_btn = make_button(
            "Refresh catalog",
            "secondary",
            tooltip="Query GitHub for the latest voice model manifest",
        )
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.refresh_btn)
        lay.addLayout(search_row)

        # Catalog list
        group_label(lay, "Available neural voice models")
        self.model_list = QListWidget()
        self.model_list.setAccessibleName("Available neural voice models")
        lay.addWidget(self.model_list, 1)

        # Selected model details
        self.detail_title = QLabel("")
        self.detail_title.setWordWrap(True)
        lay.addWidget(self.detail_title)

        self.detail_desc = hint_label("Select a voice model from the list to view details.")
        lay.addWidget(self.detail_desc)

        # Bottom action row
        btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.download_btn = make_button(
            "Download model",
            "primary",
            tooltip="Download the selected .onnx voice model into Mandible",
        )
        self.close_btn = make_button("Close", "secondary")
        btn_row.addWidget(self.download_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        lay.addLayout(btn_row)

        self._catalogLoaded.connect(self._on_catalog_loaded)
        self._downloadProgress.connect(self._on_download_progress)
        self._downloadFinished.connect(self._on_download_finished)

        self.search_edit.textChanged.connect(self._repopulate_list)
        self.refresh_btn.clicked.connect(self.refresh_catalog)
        self.model_list.currentRowChanged.connect(self._on_selection_changed)
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.close_btn.clicked.connect(self.accept)

        self._reserve_button_widths()
        self._repopulate_list()
        keep_wrapped_text_visible(self)

        if auto_fetch:
            self.refresh_catalog()

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._reserve_button_widths()

    def _reserve_button_widths(self) -> None:
        reserve_text_width(self.refresh_btn, self.refresh_btn.text())
        reserve_text_width(
            self.download_btn,
            "Download model",
            "Re-download model",
            "Downloading…",
        )
        reserve_text_width(self.close_btn, self.close_btn.text())

    @property
    def downloaded_model_id(self) -> str:
        return self._downloaded_model_id

    def refresh_catalog(self) -> None:
        if self._downloading:
            return
        self.refresh_btn.setEnabled(False)

        def _worker():
            models = fetch_remote_voice_models()
            self._catalogLoaded.emit(models)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_catalog_loaded(self, models: list[RemoteVoiceModelInfo]) -> None:
        self.refresh_btn.setEnabled(True)
        if models:
            self._remote_models = list(models)
            self._repopulate_list()

    def _repopulate_list(self) -> None:
        query = self.search_edit.text().strip().lower()
        cur_remote = self._selected_remote()
        cur_id = cur_remote.id if cur_remote else ""

        self.model_list.blockSignals(True)
        self.model_list.clear()
        select_row = 0
        for m in self._remote_models:
            haystack = f"{m.name} {m.author} {m.description} {' '.join(m.tags)}".lower()
            if query and query not in haystack:
                continue
            installed = is_remote_model_installed(m, self.models_dir)
            tags_str = f" [{', '.join(m.tags)}]" if m.tags else ""
            status_str = "  ·  Installed" if installed else f"  ·  {m.size_mb:.1f} MB"
            item = QListWidgetItem(f"{m.name}{tags_str} — by {m.author}{status_str}")
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            if m.id == cur_id:
                select_row = self.model_list.count()
            self.model_list.addItem(item)
        self.model_list.blockSignals(False)

        if self.model_list.count() > 0:
            self.model_list.setCurrentRow(select_row)
        else:
            self._on_selection_changed(-1)

    def _selected_remote(self) -> RemoteVoiceModelInfo | None:
        item = self.model_list.currentItem()
        if item is None:
            return None
        mid = item.data(Qt.ItemDataRole.UserRole)
        for m in self._remote_models:
            if m.id == mid:
                return m
        return None

    def _on_selection_changed(self, _row: int) -> None:
        m = self._selected_remote()
        if m is None:
            self.detail_title.setText("No model selected")
            self.detail_desc.setText("Try clearing your search filter.")
            self.download_btn.setEnabled(False)
            return
        installed = is_remote_model_installed(m, self.models_dir)
        badge = " (Installed in library)" if installed else f" ({m.size_mb:.1f} MB download)"
        self.detail_title.setText(f"{m.name} — {m.author}{badge}")
        self.detail_desc.setText(
            f"{m.description}  ·  Recommended pitch: {m.default_pitch:+.1f} st, formant: {m.default_formant:+.1f} st"
        )
        if not self._downloading:
            self.download_btn.setEnabled(True)
            self.download_btn.setText("Re-download model" if installed else "Download model")

    def _on_download_clicked(self) -> None:
        m = self._selected_remote()
        if m is None or self._downloading:
            return
        self._downloading = True
        self.download_btn.setEnabled(False)
        self.download_btn.setText("Downloading…")
        self.refresh_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_title.setText(f"Downloading {m.name}…")

        def _worker():
            try:
                info = download_remote_voice_model(
                    m,
                    models_dir=self.models_dir,
                    progress_cb=self._downloadProgress.emit,
                )
                self._downloadFinished.emit(info, "")
            except Exception as exc:
                self._downloadFinished.emit(None, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_download_progress(self, read_bytes: int, total_bytes: int) -> None:
        if total_bytes > 0:
            pct = max(0, min(100, int(round(read_bytes / total_bytes * 100))))
            self.progress_bar.setValue(pct)

    def _on_download_finished(self, info, error_msg: str) -> None:
        self._downloading = False
        self.progress_bar.setVisible(False)
        self.refresh_btn.setEnabled(True)
        if error_msg or info is None:
            set_style_property(self.status_card, "state", "warn")
            self.status_title.setText("Download failed")
            self.status_desc.setText(error_msg or "Could not download the selected voice model.")
            self._on_selection_changed(self.model_list.currentRow())
            return

        set_style_property(self.status_card, "state", "ok")
        self.status_title.setText(f"Installed '{info.name}' into Mandible!")
        self.status_desc.setText(
            f"Saved to {info.model_path}. This voice model is now ready to use in the AI Voice Changer."
        )
        self._downloaded_model_id = info.id
        self._repopulate_list()
