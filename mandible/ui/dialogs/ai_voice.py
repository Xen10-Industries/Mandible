"""AI Voice Changer configuration & model manager dialog."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ... import plugins as P
from ...ai_voice import (
    AI_MODELS_DIR,
    F0_METHODS,
    detect_onnx_backend,
    get_voice_model,
    import_voice_model,
    list_voice_models,
    remove_voice_model,
)
from ...config import PluginSlot
from ...core import Core, inst
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width, set_style_property
from ..widgets.buttons import make_button
from .ai_trainer import AITrainerDialog
from .model_hub import ModelHubDialog
from .parts import group_label, hint_label, keep_wrapped_text_visible


class AIVoiceDialog(QDialog):
    """Model manager and real-time voice conversion controls for an ``internal:ai_voice`` slot."""

    def __init__(self, slot: PluginSlot, core: Core, parent=None, *, models_dir: str | None = None):
        super().__init__(parent)
        self.slot = slot
        self.core = core
        self.models_dir = models_dir or AI_MODELS_DIR
        self.plugin = inst(slot)
        self._spaced = SpacedLayouts()
        _follow_look(self)

        self.setWindowTitle("AI Voice Changer — Model & Timbre")
        self.setMinimumWidth(680)
        self.resize(800, 580)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        # Runtime status card
        self.status_card = QFrame()
        self.status_card.setObjectName("wizardCard")
        set_style_property(self.status_card, "state", "ok")
        card_lay = self._spaced.add(QVBoxLayout(self.status_card), spacing=1, margins=3)

        _, backend_desc = detect_onnx_backend()
        sr = (core.engine.samplerate if core and core.engine.samplerate else 48000) or 48000
        lat_smp = getattr(self.plugin, "reported_latency_samples", 1024)
        lat_ms = lat_smp / sr * 1000.0

        self.status_title = QLabel("AI Voice Changer active")
        self.status_title.setObjectName("wizardCardTitle")
        set_style_property(self.status_title, "state", "ok")
        self.status_title.setWordWrap(True)
        card_lay.addWidget(self.status_title)

        self.status_desc = QLabel(
            f"Engine: {backend_desc}  ·  Latency: {lat_ms:.1f} ms ({lat_smp} samples)"
        )
        self.status_desc.setObjectName("wizardCardDesc")
        self.status_desc.setWordWrap(True)
        card_lay.addWidget(self.status_desc)
        lay.addWidget(self.status_card)

        # Voice model section
        group_label(lay, "Voice model")
        model_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.model_combo = QComboBox()
        self.model_combo.setAccessibleName("Voice model")
        self.model_combo.setMinimumContentsLength(18)
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        model_row.addWidget(self.model_combo, 1)

        self.defaults_btn = make_button(
            "Use model defaults",
            "secondary",
            tooltip="Set pitch, vocal tract, and timbre controls to this model's recommended values",
        )
        self.browse_btn = make_button(
            "Browse models…",
            "secondary",
            tooltip="Browse and download trained .onnx voice models from the GitHub Model Hub",
        )
        model_row.addWidget(self.browse_btn)
        model_row.addWidget(self.defaults_btn)
        lay.addLayout(model_row)

        self.model_desc_lbl = hint_label("")
        lay.addWidget(self.model_desc_lbl)

        mgr_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.train_btn = make_button(
            "Train voice…",
            "secondary",
            tooltip="Open the AI Voice Model Trainer to train a custom voice from recordings",
        )
        self.import_btn = make_button(
            "Import .onnx…",
            "secondary",
            tooltip="Import a trained RVC .onnx voice model (and optional .index file)",
        )
        self.remove_btn = make_button(
            "Remove model",
            "danger",
            tooltip="Delete the selected imported .onnx model from disk",
        )
        self.folder_btn = make_button(
            "Open folder…",
            "secondary",
            tooltip=f"Open {self.models_dir} in Windows Explorer",
        )
        mgr_row.addWidget(self.train_btn)
        mgr_row.addWidget(self.import_btn)
        mgr_row.addWidget(self.remove_btn)
        mgr_row.addWidget(self.folder_btn)
        mgr_row.addStretch(1)
        lay.addLayout(mgr_row)

        # Conversion & synthesis parameters
        group_label(lay, "Voice conversion parameters")
        form_widget = QWidget()
        form = self._spaced.add(QFormLayout(form_widget), spacing=2, margins=0)

        self.f0_combo = QComboBox()
        for key, label in F0_METHODS:
            self.f0_combo.addItem(label, key)
        form.addRow("Pitch tracker", self.f0_combo)

        self._slider_pairs: list[tuple[QSlider, QDoubleSpinBox, int]] = []
        self.pitch_slider, self.pitch_spin = self._slider_spin(
            min_v=-24.0, max_v=24.0, step=0.5, suffix=" st", decimals=1
        )
        form.addRow("Pitch shift", self._pair_row(self.pitch_slider, self.pitch_spin))

        self.formant_slider, self.formant_spin = self._slider_spin(
            min_v=-12.0, max_v=12.0, step=0.5, suffix=" st", decimals=1
        )
        form.addRow("Vocal tract (formant)", self._pair_row(self.formant_slider, self.formant_spin))

        self.index_slider, self.index_spin = self._slider_spin(
            min_v=0.0, max_v=100.0, step=1.0, suffix=" %", decimals=0
        )
        form.addRow("Timbre match", self._pair_row(self.index_slider, self.index_spin))

        self.breath_slider, self.breath_spin = self._slider_spin(
            min_v=0.0, max_v=100.0, step=1.0, suffix=" %", decimals=0
        )
        form.addRow("Breath && air", self._pair_row(self.breath_slider, self.breath_spin))

        self.mix_slider, self.mix_spin = self._slider_spin(
            min_v=0.0, max_v=100.0, step=1.0, suffix=" %", decimals=0
        )
        form.addRow("Dry / wet mix", self._pair_row(self.mix_slider, self.mix_spin))

        lay.addWidget(form_widget)
        lay.addStretch(1)

        close_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        close_row.addStretch(1)
        self.close_btn = make_button("Close", "secondary")
        self.close_btn.clicked.connect(self.accept)
        close_row.addWidget(self.close_btn)
        lay.addLayout(close_row)

        self._reserve_button_widths()
        self._populate_models()
        self._load_from_plugin()

        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.f0_combo.currentIndexChanged.connect(self._on_f0_changed)
        self.defaults_btn.clicked.connect(self._apply_model_defaults)
        self.browse_btn.clicked.connect(self._open_model_hub)
        self.train_btn.clicked.connect(self._open_voice_trainer)
        self.import_btn.clicked.connect(self._import_model)
        self.remove_btn.clicked.connect(self._remove_selected_model)
        self.folder_btn.clicked.connect(self._open_models_folder)

        keep_wrapped_text_visible(self)

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._reserve_button_widths()

    def _reserve_button_widths(self) -> None:
        for btn in (
            self.defaults_btn,
            self.browse_btn,
            self.train_btn,
            self.import_btn,
            self.remove_btn,
            self.folder_btn,
            self.close_btn,
        ):
            reserve_text_width(btn, btn.text())

    def _slider_spin(
        self, *, min_v: float, max_v: float, step: float, suffix: str, decimals: int
    ) -> tuple[QSlider, QDoubleSpinBox]:
        scale = int(round(1.0 / step)) if step > 0 else 1
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(round(min_v * scale)), int(round(max_v * scale)))

        spin = QDoubleSpinBox()
        spin.setRange(min_v, max_v)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)

        self._slider_pairs.append((slider, spin, scale))
        slider.valueChanged.connect(self._on_any_slider_changed)
        spin.valueChanged.connect(self._on_any_spin_changed)
        return slider, spin

    def _on_any_slider_changed(self, _val: int) -> None:
        sender = self.sender()
        for slider, spin, scale in self._slider_pairs:
            if sender is slider:
                fval = slider.value() / scale
                spin.blockSignals(True)
                spin.setValue(fval)
                spin.blockSignals(False)
                break
        self._sync_to_plugin()

    def _on_any_spin_changed(self, _fval: float) -> None:
        sender = self.sender()
        for slider, spin, scale in self._slider_pairs:
            if sender is spin:
                slider.blockSignals(True)
                slider.setValue(int(round(spin.value() * scale)))
                slider.blockSignals(False)
                break
        self._sync_to_plugin()

    def _pair_row(self, slider: QSlider, spin: QDoubleSpinBox) -> QWidget:
        w = QWidget()
        row = self._spaced.add(QHBoxLayout(w), spacing=2, margins=0)
        row.addWidget(slider, 1)
        row.addWidget(spin)
        return w

    def _populate_models(self, select_id: str | None = None) -> None:
        target = select_id if select_id is not None else getattr(self.plugin, "model_id", "")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        models = list_voice_models(self.models_dir)
        if not models:
            self.model_combo.addItem(
                "No .onnx voice models installed — click Browse models… or Train voice…",
                "",
            )
            self.model_combo.setEnabled(False)
        else:
            self.model_combo.setEnabled(True)
            for m in models:
                self.model_combo.addItem(m.name, m.id)
            idx = max(0, self.model_combo.findData(target))
            self.model_combo.setCurrentIndex(idx)
            cur_id = self.model_combo.currentData() or ""
            if self.plugin is not None and hasattr(self.plugin, "set_model") and not getattr(self.plugin, "model_id", ""):
                self.plugin.set_model(cur_id, apply_defaults=True, models_dir=self.models_dir)
                self._persist_state()
        self.model_combo.blockSignals(False)
        self._update_model_info()

    def _update_model_info(self) -> None:
        model_id = self.model_combo.currentData() or ""
        info = get_voice_model(model_id, self.models_dir)
        if info is None:
            self.model_desc_lbl.setText(
                "Download a pre-trained voice from the GitHub Model Hub (Browse models…), "
                "train your own in Train voice…, or import an .onnx model."
            )
            self.defaults_btn.setEnabled(False)
            self.remove_btn.setEnabled(False)
            self.status_title.setText("No .onnx voice model selected")
        else:
            self.model_desc_lbl.setText(info.description)
            self.defaults_btn.setEnabled(True)
            self.remove_btn.setEnabled(info.kind == "onnx")
            self.status_title.setText(f"Active model: {info.name}")

    def _load_from_plugin(self) -> None:
        if self.plugin is None:
            return
        f0 = getattr(self.plugin, "f0_method", "hybrid")
        self.f0_combo.blockSignals(True)
        self.f0_combo.setCurrentIndex(max(0, self.f0_combo.findData(f0)))
        self.f0_combo.blockSignals(False)

        params = getattr(self.plugin, "parameters", {})
        mapping = (
            ("pitch", self.pitch_slider, self.pitch_spin, 2),
            ("formant", self.formant_slider, self.formant_spin, 2),
            ("index_rate", self.index_slider, self.index_spin, 1),
            ("breathiness", self.breath_slider, self.breath_spin, 1),
            ("mix", self.mix_slider, self.mix_spin, 1),
        )
        for key, slider, spin, scale in mapping:
            p = params.get(key)
            if p is not None:
                val = float(p.value)
                slider.blockSignals(True)
                spin.blockSignals(True)
                spin.setValue(val)
                slider.setValue(int(round(val * scale)))
                slider.blockSignals(False)
                spin.blockSignals(False)

    def _sync_to_plugin(self) -> None:
        if self.plugin is None:
            return
        params = getattr(self.plugin, "parameters", {})
        for key, spin in (
            ("pitch", self.pitch_spin),
            ("formant", self.formant_spin),
            ("index_rate", self.index_spin),
            ("breathiness", self.breath_spin),
            ("mix", self.mix_spin),
        ):
            if key in params:
                params[key].value = float(spin.value())
        self._persist_state()

    def _persist_state(self) -> None:
        if self.plugin is None:
            return
        st = P.capture_state(self.plugin)
        if st:
            self.slot.state = st
            if self.core is not None:
                self.core.save()

    def _on_model_changed(self, _idx: int) -> None:
        model_id = self.model_combo.currentData() or ""
        if self.plugin is not None and hasattr(self.plugin, "set_model"):
            self.plugin.set_model(model_id, apply_defaults=True, models_dir=self.models_dir)
            self._load_from_plugin()
            self._persist_state()
        self._update_model_info()

    def _on_f0_changed(self, _idx: int) -> None:
        if self.plugin is not None:
            self.plugin.f0_method = self.f0_combo.currentData() or "hybrid"
            self._persist_state()

    def _apply_model_defaults(self) -> None:
        model_id = self.model_combo.currentData() or ""
        if model_id and self.plugin is not None and hasattr(self.plugin, "set_model"):
            self.plugin.set_model(model_id, apply_defaults=True, models_dir=self.models_dir)
            self._load_from_plugin()
            self._persist_state()

    def _open_model_hub(self) -> None:
        dlg = ModelHubDialog(self.core, self, models_dir=self.models_dir)
        if dlg.exec() and dlg.downloaded_model_id:
            self._populate_models(select_id=dlg.downloaded_model_id)
            self._on_model_changed(self.model_combo.currentIndex())

    def _import_model(self) -> None:
        onnx_path, _ = QFileDialog.getOpenFileName(
            self, "Select RVC voice model (.onnx)", "", "ONNX voice models (*.onnx)"
        )
        if not onnx_path:
            return
        index_path, _ = QFileDialog.getOpenFileName(
            self,
            "Optional: select matching feature index (.index) or Cancel to skip",
            os.path.dirname(onnx_path),
            "FAISS index files (*.index)",
        )
        try:
            info = import_voice_model(onnx_path, index_path=index_path or "", models_dir=self.models_dir)
        except Exception as exc:
            QMessageBox.warning(self, "Could not import model", str(exc))
            return
        self._populate_models(select_id=info.id)
        self._on_model_changed(self.model_combo.currentIndex())

    def _remove_selected_model(self) -> None:
        model_id = self.model_combo.currentData() or ""
        if not str(model_id).startswith("onnx:"):
            return
        info = get_voice_model(model_id, self.models_dir)
        if info is None:
            return
        ans = QMessageBox.question(
            self,
            "Remove voice model",
            f"Delete the imported model '{info.name}' from Mandible?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            remove_voice_model(model_id, self.models_dir)
            self._populate_models()
            self._on_model_changed(self.model_combo.currentIndex())

    def _open_voice_trainer(self) -> None:
        dlg = AITrainerDialog(self.core, self)
        if dlg.exec() and dlg.trained_model_id:
            self._populate_models(select_id=dlg.trained_model_id)
            self._on_model_changed(self.model_combo.currentIndex())

    def _open_models_folder(self) -> None:
        os.makedirs(self.models_dir, exist_ok=True)
        if hasattr(os, "startfile"):
            try:
                os.startfile(self.models_dir)
            except OSError:
                pass
