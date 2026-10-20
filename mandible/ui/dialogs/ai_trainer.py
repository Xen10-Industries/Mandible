"""Dialog for preparing vocal datasets and training custom AI voice profiles locally."""
from __future__ import annotations

import os
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
    TrainingJobConfig,
    TrainingProgress,
    VoiceModelTrainer,
    find_mandible_rvc_exe,
    inspect_audio_file,
)
from ...ai_voice import AI_MODELS_DIR, F0_METHODS, RVC_WEBUI_URL, detect_training_hardware
from ...core import Core
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width, set_style_property
from ..widgets.buttons import make_button
from .parts import group_label, hint_label, keep_wrapped_text_visible


class ExternalTrainingGuideDialog(QDialog):
    """Step-by-step guide for training heavy 40M-parameter RVC v2 models externally (GPU / Colab)."""

    def __init__(self, models_dir: str = AI_MODELS_DIR, parent=None):
        super().__init__(parent)
        self.models_dir = models_dir or AI_MODELS_DIR
        self._spaced = SpacedLayouts()
        _follow_look(self)

        self.setWindowTitle("External RVC v2 Training & Cloud GPU Guide")
        self.setMinimumWidth(640)
        self.resize(740, 580)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        card = QFrame()
        card.setObjectName("wizardCard")
        set_style_property(card, "state", "ok")
        card_lay = self._spaced.add(QVBoxLayout(card), spacing=1, margins=3)

        title = QLabel("In-App Neural Vocoder vs. Full External RVC v2 Cloning")
        title.setObjectName("wizardCardTitle")
        set_style_property(title, "state", "ok")
        title.setWordWrap(True)
        card_lay.addWidget(title)

        desc = QLabel(
            "Mandible's built-in trainer fits a lightweight 3-layer ONNX neural spectral vocoder and "
            "phonetic retrieval index (.index) directly on your CPU/GPU in ~15–60 seconds. "
            "If you want ElevenLabs-grade 40M-parameter VITS + ContentVec deep vocal cloning, "
            "you can train a full RVC v2 model externally using PyTorch/CUDA and import the .onnx file."
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

        group_label(lay, "Step 2 — Train in RVC WebUI or Colab")
        lay.addWidget(
            hint_label(
                "1. Open Retrieval-based-Voice-Conversion-WebUI locally (takes ~15–25 minutes on an RTX 3060 "
                "for 200–250 epochs) or launch its free Google Colab notebook for cloud T4/A100 GPU training.\n"
                "2. In the 'Train' tab, point to your audio folder, choose 'v2' and 'rmvpe_gpu', and click "
                "'One-click training'."
            )
        )

        group_label(lay, "Step 3 — Export .onnx and import")
        lay.addWidget(
            hint_label(
                "1. In RVC WebUI, open the 'Ckpt Processing' / 'Export ONNX' tab and export your trained "
                ".pth checkpoint to an .onnx file.\n"
                "2. In Mandible's AI Voice Changer window, click 'Import .onnx…' and select your .onnx file "
                "and matching trained_*.index file (or drop them directly into the models folder)."
            )
        )

        lay.addStretch(1)

        btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
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
        btn_row.addWidget(self.rvc_btn)
        btn_row.addWidget(self.folder_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        lay.addLayout(btn_row)

        self.rvc_btn.clicked.connect(lambda: webbrowser.open(RVC_WEBUI_URL))
        self.folder_btn.clicked.connect(self._open_folder)
        self.close_btn.clicked.connect(self.accept)

        self._reserve_button_widths()
        keep_wrapped_text_visible(self)

    def _reserve_button_widths(self) -> None:
        for btn in (self.rvc_btn, self.folder_btn, self.close_btn):
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
        self.resize(780, 700)

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
        lay.addWidget(self.status_card)

        # 2. Dataset section
        group_label(lay, "Training dataset (vocal audio)")
        self.dataset_hint = hint_label(
            "Add clean voice recordings (.wav, .mp3, .flac, .m4a) of the target speaker without background music."
        )
        lay.addWidget(self.dataset_hint)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setMaximumHeight(130)
        lay.addWidget(self.file_list)

        file_btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.add_files_btn = make_button("Add audio files…", "secondary", tooltip="Select audio samples of the speaker")
        self.remove_files_btn = make_button("Remove selected", "quiet", tooltip="Remove chosen files from the dataset")
        self.clear_files_btn = make_button("Clear all", "quiet", tooltip="Clear the dataset list")
        file_btn_row.addWidget(self.add_files_btn)
        file_btn_row.addWidget(self.remove_files_btn)
        file_btn_row.addWidget(self.clear_files_btn)
        file_btn_row.addStretch(1)

        self.dataset_stats_lbl = hint_label("0 files (0.0s total audio)")
        file_btn_row.addWidget(self.dataset_stats_lbl)
        lay.addLayout(file_btn_row)

        # 3. Model parameters
        group_label(lay, "Voice model configuration")
        form_w = QWidget()
        form = self._spaced.add(QFormLayout(form_w), spacing=2, margins=0)

        name_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.name_edit = QComboBox()
        self.name_edit.setEditable(True)
        self.name_edit.setEditText("My Custom Voice")
        name_row.addWidget(self.name_edit, 1)
        form.addRow("Voice name", name_row)

        self.engine_combo = QComboBox()
        self.engine_combo.addItem("In-app neural vocoder (~15\u201360s)", "builtin")
        self.engine_combo.addItem("Full RVC v2 GAN (~15\u201325 min on GPU)", "rvc")
        form.addRow("Training engine", self.engine_combo)

        self.f0_combo = QComboBox()
        for key, label in F0_METHODS:
            self.f0_combo.addItem(label, key)
        form.addRow("Pitch extraction", self.f0_combo)

        epoch_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.epoch_spin = QSpinBox()
        self.epoch_spin.setRange(10, 800)
        self.epoch_spin.setSingleStep(25)
        self.epoch_spin.setValue(150)
        self.epoch_spin.setSuffix(" epochs")
        epoch_row.addWidget(self.epoch_spin)
        epoch_row.addWidget(hint_label("(150–300 recommended for ONNX vocoder convergence)"))
        epoch_row.addStretch(1)
        form.addRow("Training length", epoch_row)

        self.clean_chk = QCheckBox("Normalize audio and trim silence")
        self.clean_chk.setChecked(True)
        self.clean_chk.setToolTip("Normalize vocal loudness and automatically remove silent audio pauses")
        form.addRow("Preprocessing", self.clean_chk)

        lay.addWidget(form_w)

        # 4. Live Progress Card
        group_label(lay, "Training progress")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        lay.addWidget(self.progress_bar)

        self.progress_desc = hint_label("Ready. Select training audio files and click 'Start training'.")
        lay.addWidget(self.progress_desc)

        lay.addStretch(1)

        # 5. Bottom action bar
        btn_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.train_btn = make_button("Start training", "primary", tooltip="Begin dataset STFT extraction and ONNX neural vocoder training")
        self.cancel_btn = make_button("Cancel training", "danger", tooltip="Stop current training job")
        self.cancel_btn.setVisible(False)
        self.guide_btn = make_button(
            "External training guide…",
            "secondary",
            tooltip="How to train full 40M-parameter RVC v2 models externally (local GPU or Google Colab) and import them",
        )
        self.close_btn = make_button("Close", "secondary")

        btn_row.addWidget(self.train_btn)
        btn_row.addWidget(self.cancel_btn)
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
        self.guide_btn.clicked.connect(self._open_external_guide)
        self.close_btn.clicked.connect(self._on_close)
        self.progressSignal.connect(self._on_progress_update)

        self._reserve_button_widths()
        keep_wrapped_text_visible(self)

    def _reserve_button_widths(self) -> None:
        for btn in (
            self.add_files_btn,
            self.remove_files_btn,
            self.clear_files_btn,
            self.train_btn,
            self.cancel_btn,
            self.guide_btn,
            self.close_btn,
        ):
            reserve_text_width(btn, btn.text())

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._reserve_button_widths()

    def _open_external_guide(self) -> None:
        ExternalTrainingGuideDialog(self.models_dir, self).exec()

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
            ans = QMessageBox.question(
                self,
                "RVC Add-on Not Installed",
                "Mandible's full RVC v2 deep-learning add-on is not installed on this PC yet.\n\n"
                "Would you like to open the External Training Guide to learn how to download the "
                "add-on or train on a free cloud GPU?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self._open_external_guide()
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
            self.progress_desc.setText("Cancelling training…")

    def _on_progress_update(self, prog: TrainingProgress) -> None:
        self.progress_bar.setValue(prog.current_step)
        self.progress_desc.setText(prog.stage_description)

        if prog.stage == "completed":
            self.train_btn.setVisible(True)
            self.cancel_btn.setVisible(False)
            self.add_files_btn.setEnabled(True)
            self.remove_files_btn.setEnabled(True)
            self.clear_files_btn.setEnabled(True)
            set_style_property(self.status_card, "state", "ok")
            self.status_title.setText(f"Model '{self.name_edit.currentText()}' trained successfully!")
            self._trained_model_id = f"onnx:{_slugify(self.name_edit.currentText())}.onnx"
            QMessageBox.information(
                self,
                "Training Complete",
                f"Voice model '{self.name_edit.currentText()}' has been trained and saved to Mandible's voice library.\n\nYou can now select it in the AI Voice Changer plugin!",
            )

        elif prog.stage == "error":
            self.train_btn.setVisible(True)
            self.cancel_btn.setVisible(False)
            self.add_files_btn.setEnabled(True)
            self.remove_files_btn.setEnabled(True)
            self.clear_files_btn.setEnabled(True)
            set_style_property(self.status_card, "state", "warn")
            self.status_title.setText("Training failed")
            QMessageBox.warning(self, "Training failed", f"Could not train voice model:\n{prog.error_message}")

        elif prog.stage == "cancelled":
            self.train_btn.setVisible(True)
            self.cancel_btn.setVisible(False)
            self.add_files_btn.setEnabled(True)
            self.remove_files_btn.setEnabled(True)
            self.clear_files_btn.setEnabled(True)
            self.status_title.setText("Training cancelled")

    def _on_close(self) -> None:
        if self._trainer is not None and self._trainer.is_running:
            ans = QMessageBox.question(
                self,
                "Cancel Training?",
                "A voice model is currently training. Closing this window will cancel the training job. Are you sure?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            self._trainer.cancel()
            self._trainer.join(timeout=1.0)
        self.accept()


def _slugify(name: str) -> str:
    import re
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_").lower()
    return slug or "custom_voice"
