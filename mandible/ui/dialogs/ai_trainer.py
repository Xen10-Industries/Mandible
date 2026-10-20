"""Dialog for preparing vocal datasets and training custom AI voice profiles locally."""
from __future__ import annotations

import os
import threading
import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...ai_trainer import (
    MANDIBLE_RVC_DIR,
    MANDIBLE_RVC_REPO,
    TrainingJobConfig,
    TrainingProgress,
    VoiceModelTrainer,
    download_and_install_rvc_addon,
    find_mandible_rvc_exe,
    inspect_audio_file,
)
from ...ai_voice import AI_MODELS_DIR, F0_METHODS, RVC_WEBUI_URL, detect_training_hardware
from ...core import Core
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width, set_style_property
from ..widgets.buttons import make_button
from .parts import group_label, hint_label, keep_wrapped_text_visible


class RVCAddonDialog(QDialog):
    """Dialog for inspecting, downloading, and managing the Mandible RVC deep-learning add-on."""

    addonInstalled = Signal(str)
    _downloadProgress = Signal(int, int)
    _downloadFinished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spaced = SpacedLayouts()
        self._downloading = False
        _follow_look(self)

        self.setWindowTitle("Mandible RVC v2 Add-on")
        self.setMinimumWidth(640)
        self.resize(720, 520)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        self.card = QFrame()
        self.card.setObjectName("wizardCard")
        self.card_lay = self._spaced.add(QVBoxLayout(self.card), spacing=1, margins=3)

        self.title_lbl = QLabel("Mandible RVC Deep-Learning Add-on")
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

        group_label(lay, "Add-on overview")
        lay.addWidget(
            hint_label(
                "The Mandible RVC add-on bundles headless 40M-parameter VITS neural vocoder training, "
                "ContentVec acoustic feature extraction, and RMVPE GPU pitch tracking into an optional sidecar. "
                "This keeps Mandible's main installer lightweight (~150 MB) while offering genuine "
                "neural voice cloning."
            )
        )

        group_label(lay, "Installation location")
        self.location_lbl = hint_label(f"Installed at: {MANDIBLE_RVC_DIR}")
        lay.addWidget(self.location_lbl)

        lay.addStretch(1)

        btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.download_btn = make_button("Download & install add-on", "primary")
        self.guide_btn = make_button("RVC guide…", "secondary", tooltip="Open RVC training and cloud GPU guide")
        self.folder_btn = make_button("Open tools folder…", "secondary", tooltip=f"Open {MANDIBLE_RVC_DIR} in Explorer")
        self.close_btn = make_button("Close", "secondary")

        btn_row.addWidget(self.download_btn)
        btn_row.addWidget(self.guide_btn)
        btn_row.addWidget(self.folder_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        lay.addLayout(btn_row)

        self.download_btn.clicked.connect(self._on_download_addon)
        self.guide_btn.clicked.connect(self._open_guide)
        self.folder_btn.clicked.connect(self._open_folder)
        self.close_btn.clicked.connect(self.accept)

        self._downloadProgress.connect(self._on_download_progress)
        self._downloadFinished.connect(self._on_download_finished)

        self._refresh_installed_state()
        self._reserve_button_widths()
        keep_wrapped_text_visible(self)

    def _reserve_button_widths(self) -> None:
        for btn in (self.download_btn, self.guide_btn, self.folder_btn, self.close_btn):
            reserve_text_width(btn, btn.text())

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._reserve_button_widths()

    def _refresh_installed_state(self) -> None:
        exe = find_mandible_rvc_exe()
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
            self.location_lbl.setText(f"Target directory: {MANDIBLE_RVC_DIR}")
            self.download_btn.setText("Download & install add-on")
            self.download_btn.setEnabled(True)
        self._reserve_button_widths()

    def _open_folder(self) -> None:
        os.makedirs(MANDIBLE_RVC_DIR, exist_ok=True)
        if hasattr(os, "startfile"):
            try:
                os.startfile(MANDIBLE_RVC_DIR)
            except OSError:
                pass

    def _open_guide(self) -> None:
        RVCGuideDialog(AI_MODELS_DIR, self).exec()

    def _on_download_addon(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self.download_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("Downloading Mandible RVC add-on release from GitHub…")

        def _worker():
            try:
                def _prog(read_bytes, total_bytes):
                    if total_bytes > 0:
                        pct = int(100 * read_bytes / total_bytes)
                        self._downloadProgress.emit(pct, total_bytes)

                exe = download_and_install_rvc_addon(progress_cb=_prog)
                self._downloadFinished.emit(True, exe)
            except Exception as exc:
                self._downloadFinished.emit(False, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_download_progress(self, pct: int, total: int) -> None:
        self.progress_bar.setValue(pct)
        mb = total / (1024 * 1024)
        self.status_lbl.setText(f"Downloading Mandible RVC add-on ({pct}% of {mb:.1f} MB)…")

    def _on_download_finished(self, success: bool, msg: str) -> None:
        self._downloading = False
        self.progress_bar.setVisible(False)
        if success:
            self._refresh_installed_state()
            self.addonInstalled.emit(msg)
            QMessageBox.information(
                self,
                "Add-on Installed",
                f"Mandible RVC add-on was installed successfully!\n\nLocation: {msg}",
            )
        else:
            self._refresh_installed_state()
            QMessageBox.warning(
                self,
                "Download Error",
                f"Could not download Mandible RVC add-on:\n\n{msg}\n\n"
                f"You can also visit https://github.com/{MANDIBLE_RVC_REPO} to download it manually.",
            )


class RVCGuideDialog(QDialog):
    """Step-by-step guide for training heavy 40M-parameter RVC v2 models externally (GPU / Colab)."""

    def __init__(self, models_dir: str = AI_MODELS_DIR, parent=None):
        super().__init__(parent)
        self.models_dir = models_dir or AI_MODELS_DIR
        self._spaced = SpacedLayouts()
        _follow_look(self)

        self.setWindowTitle("RVC Training & Cloud GPU Guide")
        self.setMinimumWidth(640)
        self.resize(740, 580)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        card = QFrame()
        card.setObjectName("wizardCard")
        set_style_property(card, "state", "ok")
        card_lay = self._spaced.add(QVBoxLayout(card), spacing=1, margins=3)

        title = QLabel("In-App Neural Vocoder vs. Full RVC v2 Cloning")
        title.setObjectName("wizardCardTitle")
        set_style_property(title, "state", "ok")
        title.setWordWrap(True)
        card_lay.addWidget(title)

        desc = QLabel(
            "Mandible's built-in trainer fits a lightweight 3-layer ONNX neural spectral vocoder and "
            "phonetic retrieval index (.index) directly on your CPU/GPU in ~15–60 seconds. "
            "If you want ElevenLabs-grade 40M-parameter VITS + ContentVec deep vocal cloning, "
            "you can use the Mandible RVC add-on or train externally using PyTorch/CUDA and import the .onnx file."
        )
        desc.setObjectName("wizardCardDesc")
        desc.setWordWrap(True)
        card_lay.addWidget(desc)
        lay.addWidget(card)

        group_label(lay, "Step 1 — Prepare dry vocal audio")
        lay.addWidget(
            hint_label(
                "Record or export a clean, single-speaker vocal stem (.wav or .flac) without reverb, "
                "delay, or background music. Stereo or echo effects should be added as rack modules "
                "in Mandible after the AI Voice Changer."
            )
        )

        group_label(lay, "Step 2 — Choose your training engine")
        lay.addWidget(
            hint_label(
                "1. Mandible RVC Add-on: click 'RVC add-on\u2026' to install the headless sidecar for 1-click GPU training.\n"
                "2. External RVC WebUI: open Retrieval-based-Voice-Conversion-WebUI locally or run on a free Google Colab cloud GPU.\n"
                "3. In RVC, select 'v2' and 'rmvpe_gpu', point to your recordings folder, and train for 200\u2013250 epochs."
            )
        )

        group_label(lay, "Step 3 — Export .onnx and import")
        lay.addWidget(
            hint_label(
                "1. In RVC WebUI, open the 'Ckpt Processing' / 'Export ONNX' tab and export your trained "
                ".pth checkpoint to an .onnx file.\n"
                "2. In Mandible's AI Voice Changer window, click 'Import .onnx\u2026' and select your .onnx file "
                "and matching trained_*.index file (or drop them directly into the models folder)."
            )
        )

        lay.addStretch(1)

        btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.addon_btn = make_button("RVC add-on…", "secondary", tooltip="Download or manage the Mandible RVC deep-learning add-on")
        self.rvc_btn = make_button(
            "Open RVC GitHub…",
            "secondary",
            tooltip=f"Open {RVC_WEBUI_URL} in your web browser",
        )
        self.folder_btn = make_button(
            "Open models folder…",
            "secondary",
            tooltip=f"Open {self.models_dir} in Windows Explorer",
        )
        self.close_btn = make_button("Close", "primary")
        btn_row.addWidget(self.addon_btn)
        btn_row.addWidget(self.rvc_btn)
        btn_row.addWidget(self.folder_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        lay.addLayout(btn_row)

        self.addon_btn.clicked.connect(self._open_addon)
        self.rvc_btn.clicked.connect(lambda: webbrowser.open(RVC_WEBUI_URL))
        self.folder_btn.clicked.connect(self._open_folder)
        self.close_btn.clicked.connect(self.accept)

        self._reserve_button_widths()
        keep_wrapped_text_visible(self)

    def _open_addon(self) -> None:
        RVCAddonDialog(self).exec()

    def _reserve_button_widths(self) -> None:
        for btn in (self.addon_btn, self.rvc_btn, self.folder_btn, self.close_btn):
            reserve_text_width(btn, btn.text())

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._reserve_button_widths()

    def _open_folder(self) -> None:
        os.makedirs(self.models_dir, exist_ok=True)
        if hasattr(os, "startfile"):
            try:
                os.startfile(self.models_dir)
            except OSError:
                pass


ExternalTrainingGuideDialog = RVCGuideDialog


class AITrainerDialog(QDialog):
    """Wizard and controls for training local AI voice models from audio recordings."""

    progressSignal = Signal(object)  # TrainingProgress

    def __init__(self, core: Core | None = None, parent=None, *, models_dir: str | None = None):
        super().__init__(parent)
        self.core = core
        self.models_dir = models_dir or AI_MODELS_DIR
        self._spaced = SpacedLayouts()
        self._files: list[str] = []
        self._trainer: VoiceModelTrainer | None = None
        self._trained_model_id: str = ""
        _follow_look(self)

        self.setWindowTitle("Train AI Voice Model")
        self.setMinimumWidth(660)
        self.resize(780, 720)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        # 1. Hardware & training time expectation banner
        self.status_card = QFrame()
        self.status_card.setObjectName("wizardCard")
        set_style_property(self.status_card, "state", "ok")
        card_lay = self._spaced.add(QVBoxLayout(self.status_card), spacing=1, margins=3)

        hw_title, hw_guidance = detect_training_hardware()
        self.status_title = QLabel(hw_title)
        self.status_title.setObjectName("wizardCardTitle")
        set_style_property(self.status_title, "state", "ok")
        self.status_title.setWordWrap(True)
        card_lay.addWidget(self.status_title)

        self.status_desc = QLabel(hw_guidance)
        self.status_desc.setObjectName("wizardCardDesc")
        self.status_desc.setWordWrap(True)
        card_lay.addWidget(self.status_desc)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        card_lay.addWidget(self.progress_bar)

        lay.addWidget(self.status_card)

        # 2. Vocal dataset files section
        group_label(lay, "Training audio recordings")
        lay.addWidget(
            hint_label(
                "Add 1–5 minutes of clean, dry, single-speaker vocal audio (.wav, .mp3, .flac). "
                "Non-silent vocal sections will be automatically sliced and extracted."
            )
        )

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setMinimumHeight(100)
        lay.addWidget(self.file_list)

        file_btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.add_files_btn = make_button("Add recordings…", "secondary", tooltip="Select audio files to add to dataset")
        self.remove_files_btn = make_button("Remove selected", "secondary", tooltip="Remove selected audio file from list")
        self.clear_files_btn = make_button("Clear all", "secondary", tooltip="Clear entire file list")
        file_btn_row.addWidget(self.add_files_btn)
        file_btn_row.addWidget(self.remove_files_btn)
        file_btn_row.addWidget(self.clear_files_btn)
        file_btn_row.addStretch(1)

        self.dataset_stats_lbl = hint_label("0 files (0.0s total audio)")
        file_btn_row.addWidget(self.dataset_stats_lbl)
        lay.addLayout(file_btn_row)

        # 3. Model parameters form
        group_label(lay, "Training configuration")
        form_w = QWidget()
        form = self._spaced.add(QFormLayout(form_w), spacing=2, margins=0)

        name_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.name_edit = QComboBox()
        self.name_edit.setEditable(True)
        self.name_edit.setEditText("My Custom Voice")
        name_row.addWidget(self.name_edit, 1)
        form.addRow("Voice name", name_row)

        self.engine_combo = QComboBox()
        self.engine_combo.addItem("In-app neural vocoder (~15–60s)", "builtin")
        self.engine_combo.addItem("Full RVC v2 GAN (~15–25 min on GPU)", "rvc")
        form.addRow("Training engine", self.engine_combo)

        addon_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.addon_status_lbl = hint_label("")
        self.addon_quick_btn = make_button("RVC add-on…", "secondary", tooltip="Download or manage the Mandible RVC add-on")
        addon_row.addWidget(self.addon_status_lbl, 1)
        addon_row.addWidget(self.addon_quick_btn)
        form.addRow("Add-on status", addon_row)

        self.f0_combo = QComboBox()
        for key, label in F0_METHODS:
            self.f0_combo.addItem(label, key)
        form.addRow("Pitch extraction", self.f0_combo)

        self.epoch_spin = QSpinBox()
        self.epoch_spin.setRange(20, 1000)
        self.epoch_spin.setSingleStep(25)
        self.epoch_spin.setValue(150)
        self.epoch_spin.setSuffix(" epochs")
        form.addRow("Training epochs", self.epoch_spin)

        self.clean_chk = QCheckBox("Normalize loudness and remove DC")
        self.clean_chk.setChecked(True)
        form.addRow("", self.clean_chk)

        lay.addWidget(form_w)
        lay.addStretch(1)

        # 4. Action buttons
        btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.train_btn = make_button("Train voice model", "primary", tooltip="Start background neural training")
        self.cancel_btn = make_button("Cancel training", "danger", tooltip="Stop current training job")
        self.cancel_btn.setVisible(False)
        self.addon_bottom_btn = make_button("RVC add-on…", "secondary", tooltip="Download or manage the Mandible RVC deep-learning add-on")
        self.guide_btn = make_button(
            "RVC guide…",
            "secondary",
            tooltip="Step-by-step guide for training RVC v2 models (local GPU or Google Colab)",
        )
        self.close_btn = make_button("Close", "secondary")

        btn_row.addWidget(self.train_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.addon_bottom_btn)
        btn_row.addWidget(self.guide_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        lay.addLayout(btn_row)

        # Signal connections
        self.add_files_btn.clicked.connect(self._on_add_files)
        self.remove_files_btn.clicked.connect(self._on_remove_selected)
        self.clear_files_btn.clicked.connect(self._on_clear_files)
        self.train_btn.clicked.connect(self._on_start_training)
        self.cancel_btn.clicked.connect(self._on_cancel_training)
        self.addon_quick_btn.clicked.connect(self._open_addon_dialog)
        self.addon_bottom_btn.clicked.connect(self._open_addon_dialog)
        self.guide_btn.clicked.connect(self._open_external_guide)
        self.close_btn.clicked.connect(self._on_close)
        self.progressSignal.connect(self._on_progress_update)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)

        self._refresh_addon_status()
        self._reserve_button_widths()
        keep_wrapped_text_visible(self)

    def _reserve_button_widths(self) -> None:
        for btn in (
            self.add_files_btn,
            self.remove_files_btn,
            self.clear_files_btn,
            self.train_btn,
            self.cancel_btn,
            self.addon_quick_btn,
            self.addon_bottom_btn,
            self.guide_btn,
            self.close_btn,
        ):
            reserve_text_width(btn, btn.text())

    def _refresh_addon_status(self) -> None:
        exe = find_mandible_rvc_exe()
        if exe:
            self.addon_status_lbl.setText(f"Installed (ready) — {os.path.basename(exe)}")
        else:
            self.addon_status_lbl.setText("Not installed — click 'RVC add-on…' to download")

    def _on_engine_changed(self) -> None:
        engine = self.engine_combo.currentData()
        if engine == "rvc":
            exe = find_mandible_rvc_exe()
            if not exe:
                self.addon_status_lbl.setText("Not installed — click 'RVC add-on…' to download")

    def _open_addon_dialog(self) -> None:
        dlg = RVCAddonDialog(self)
        dlg.addonInstalled.connect(lambda _: self._refresh_addon_status())
        dlg.exec()
        self._refresh_addon_status()

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._reserve_button_widths()

    def _open_external_guide(self) -> None:
        RVCGuideDialog(self.models_dir, self).exec()

    @property
    def trained_model_id(self) -> str:
        return self._trained_model_id

    def add_files(self, paths: list[str]) -> None:
        for p in paths:
            ap = os.path.abspath(p)
            if ap not in self._files and os.path.isfile(ap):
                self._files.append(ap)
        self._refresh_file_list()

    def _on_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Vocal Audio Recordings",
            "",
            "Audio files (*.wav *.mp3 *.flac *.ogg *.m4a);;All files (*.*)",
        )
        if files:
            self.add_files(files)

    def _on_remove_selected(self) -> None:
        selected_indexes = [item.row() for item in self.file_list.selectedIndexes()]
        for idx in sorted(selected_indexes, reverse=True):
            if 0 <= idx < len(self._files):
                self._files.pop(idx)
        self._refresh_file_list()

    def _on_clear_files(self) -> None:
        self._files.clear()
        self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        total_dur = 0.0
        valid_cnt = 0
        for p in self._files:
            info = inspect_audio_file(p)
            dur_str = f"{info.duration_s:.1f}s" if info.is_valid else "invalid"
            it = QListWidgetItem(f"{info.filename}  ({dur_str})")
            if not info.is_valid:
                it.setToolTip(info.error)
                it.setForeground(Qt.GlobalColor.darkRed)
            else:
                total_dur += info.duration_s
                valid_cnt += 1
            self.file_list.addItem(it)

        self.dataset_stats_lbl.setText(f"{valid_cnt} valid files ({total_dur:.1f}s total audio)")

    def _on_start_training(self) -> None:
        if not self._files:
            QMessageBox.warning(self, "No audio files", "Please add one or more voice recordings to train your model.")
            return

        selected_engine = self.engine_combo.currentData() or "builtin"
        if selected_engine == "rvc" and find_mandible_rvc_exe() is None:
            self._open_addon_dialog()
            if find_mandible_rvc_exe() is None:
                return

        name = self.name_edit.currentText().strip() or "Custom Voice"
        config = TrainingJobConfig(
            voice_name=name,
            input_files=list(self._files),
            target_sr=40000,
            epochs=self.epoch_spin.value(),
            f0_method=self.f0_combo.currentData() or "hybrid",
            normalize_loudness=self.clean_chk.isChecked(),
            clean_audio=self.clean_chk.isChecked(),
            trainer_engine=selected_engine,
        )

        self.train_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.add_files_btn.setEnabled(False)
        self.remove_files_btn.setEnabled(False)
        self.clear_files_btn.setEnabled(False)

        self._trainer = VoiceModelTrainer(
            config,
            models_dir=self.models_dir,
            progress_cb=self.progressSignal.emit,
        )
        self._trainer.start()

    def _on_cancel_training(self) -> None:
        if self._trainer is not None and self._trainer.is_running:
            self._trainer.cancel()

    def _on_progress_update(self, prog: TrainingProgress) -> None:
        if prog.stage == "preparing":
            self.status_desc.setText(prog.stage_description)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(prog.current_step)
        elif prog.stage in ("extracting", "indexing", "slicing"):
            self.status_desc.setText(prog.stage_description)
            self.progress_bar.setValue(prog.current_step)
        elif prog.stage == "training":
            self.progress_bar.setValue(prog.current_step)
            loss_str = f"loss: {prog.loss:.4f}" if prog.loss > 0 else ""
            self.status_desc.setText(
                f"Epoch {prog.epoch}/{prog.total_epochs} ({prog.stage_description})  {loss_str}"
            )
        elif prog.stage == "exporting":
            self.status_desc.setText(prog.stage_description)
            self.progress_bar.setValue(prog.current_step)
        elif prog.stage == "completed":
            self.status_desc.setText(prog.stage_description)
            self.progress_bar.setValue(100)
            self.train_btn.setVisible(True)
            self.cancel_btn.setVisible(False)
            self.add_files_btn.setEnabled(True)
            self.remove_files_btn.setEnabled(True)
            self.clear_files_btn.setEnabled(True)
            if self._trainer is not None:
                self._trained_model_id = self._trainer.trained_model_id
            QMessageBox.information(
                self,
                "Training Complete",
                f"Voice model '{self.name_edit.currentText()}' trained and ready in the AI Voice Changer!",
            )
            self.accept()
        elif prog.stage in ("error", "cancelled"):
            self.status_desc.setText(prog.stage_description)
            self.progress_bar.setVisible(False)
            self.train_btn.setVisible(True)
            self.cancel_btn.setVisible(False)
            self.add_files_btn.setEnabled(True)
            self.remove_files_btn.setEnabled(True)
            self.clear_files_btn.setEnabled(True)
            if prog.stage == "error":
                QMessageBox.critical(self, "Training Error", prog.stage_description)

    def _on_close(self) -> None:
        if self._trainer is not None and self._trainer.is_running:
            ans = QMessageBox.question(
                self,
                "Cancel Training?",
                "A voice model training job is currently in progress. Cancel it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self._trainer.cancel()
                self.reject()
        else:
            self.reject()
