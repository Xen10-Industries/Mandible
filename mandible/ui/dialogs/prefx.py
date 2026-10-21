"""Microphone pre-processing settings ("Mic cleanup")."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)
from .clarity import ClarityAddonDialog
from ..widgets.buttons import make_button

from ...core import Core
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width
from ..widgets.buttons import tier_button_box
from .parts import check_row, group_label, keep_wrapped_text_visible

FIELD_LABELS = ("Cutoff frequency", "Engine", "Intensity", "Threshold", "Attack", "Release")


class PreFXDialog(QDialog):
    """Mic cleanup: high-pass rumble filter, RNNoise AI suppression and a noise gate."""

    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.cfg = copy.copy(core.cfg.prefx)
        self.setWindowTitle("Mic cleanup")
        self.setMinimumWidth(360)
        self.resize(480, 420)
        self._spaced = SpacedLayouts()
        self._labels: list[QLabel] = []
        _follow_look(self)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        group_label(lay, "Rumble filter")
        self.hp_en = check_row(lay, "Enable high-pass filter", self.cfg.highpass_enabled,
                               "Removes desk thumps, air-conditioning rumble and plosives.")
        self.hp_freq = QSpinBox()
        self.hp_freq.setRange(20, 300)
        self.hp_freq.setValue(int(self.cfg.highpass_cutoff_hz))
        self.hp_freq.setSuffix(" Hz")
        self._field(lay, "Cutoff frequency", self.hp_freq)

        group_label(lay, "Noise suppression")
        self.rnn_en = check_row(lay, "Enable AI noise suppression", self.cfg.rnnoise_enabled,
                                "Removes fan noise, keyboard clicks, mic hiss, and room echo.")
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("RNNoise (Fast CPU)", "rnnoise")
        self.engine_combo.addItem("Mandible Clarity (DeepFilter AI)", "clarity")
        idx = self.engine_combo.findData(self.cfg.noise_engine)
        if idx >= 0:
            self.engine_combo.setCurrentIndex(idx)
        self.clarity_btn = make_button("Clarity add-on…", "secondary", tooltip="Inspect, download, or manage Mandible Clarity add-on")
        reserve_text_width(self.clarity_btn, "Clarity add-on…")
        self.clarity_btn.clicked.connect(lambda: ClarityAddonDialog(self).exec())
        self._field(lay, "Engine", self.engine_combo, self.clarity_btn)

        self.rnn_wet = QSlider(Qt.Horizontal)
        self.rnn_wet.setRange(0, 100)
        self.rnn_wet.setValue(int(round(self.cfg.rnnoise_wet * 100)))
        self.rnn_lbl = self._readout(self.rnn_wet, "{}%", "100%")
        self._field(lay, "Intensity", self.rnn_wet, self.rnn_lbl)

        group_label(lay, "Noise gate")
        self.gate_en = check_row(lay, "Enable noise gate", self.cfg.noise_gate_enabled,
                                 "Silences the room while you are not speaking.")
        self.gate_thresh = QSlider(Qt.Horizontal)
        self.gate_thresh.setRange(-70, -20)
        self.gate_thresh.setValue(int(round(self.cfg.noise_gate_threshold_db)))
        self.gate_t_lbl = self._readout(self.gate_thresh, "{} dB", "-70 dB")
        self._field(lay, "Threshold", self.gate_thresh, self.gate_t_lbl)
        self.gate_att = QSpinBox()
        self.gate_att.setRange(1, 50)
        self.gate_att.setValue(int(round(self.cfg.noise_gate_open_ms)))
        self.gate_att.setSuffix(" ms")
        self.gate_att.setToolTip("How quickly the gate fades in when you start talking. "
                                 "Raise it if the first syllable clicks or thumps.")
        self._field(lay, "Attack", self.gate_att)
        self.gate_rel = QSpinBox()
        self.gate_rel.setRange(10, 1000)
        self.gate_rel.setValue(int(round(self.cfg.noise_gate_release_ms)))
        self.gate_rel.setSuffix(" ms")
        self._field(lay, "Release", self.gate_rel)

        for label in self._labels:           # one label column: the fields line up
            reserve_text_width(label, *FIELD_LABELS)

        lay.addStretch(1)
        bb = tier_button_box(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        keep_wrapped_text_visible(self)

    def _on_look_changed(self) -> None:
        self._spaced.apply()

    def _field(self, lay: QVBoxLayout, text: str, field: QWidget, trailing: QWidget | None = None) -> None:
        """``text`` and its field on one row. A slider takes the width that is left (its value
        label follows it); a spin box keeps its natural width, at the left."""
        row = self._spaced.add(QHBoxLayout(), spacing=3, margins=0)
        label = QLabel(text)
        self._labels.append(label)
        row.addWidget(label)
        if trailing is not None:
            row.addWidget(field, 1)
            row.addWidget(trailing)
        else:
            row.addWidget(field)
            row.addStretch(1)
        lay.addLayout(row)

    @staticmethod
    def _readout(slider: QSlider, fmt: str, widest: str) -> QLabel:
        """A value label that follows the slider and keeps one width, so the slider does not
        change length as the number gains or loses digits."""
        label = QLabel(fmt.format(slider.value()))
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(lambda v: label.setText(fmt.format(v)))
        reserve_text_width(label, widest)
        return label

    def _save(self):
        self.cfg.highpass_enabled = self.hp_en.isChecked()
        self.cfg.highpass_cutoff_hz = float(self.hp_freq.value())
        self.cfg.rnnoise_enabled = self.rnn_en.isChecked()
        self.cfg.rnnoise_wet = self.rnn_wet.value() / 100.0
        self.cfg.noise_engine = str(self.engine_combo.currentData() or "rnnoise")
        self.cfg.noise_gate_enabled = self.gate_en.isChecked()
        self.cfg.noise_gate_threshold_db = float(self.gate_thresh.value())
        self.cfg.noise_gate_open_ms = float(self.gate_att.value())
        self.cfg.noise_gate_release_ms = float(self.gate_rel.value())
        self.core.set_prefx(self.cfg)
        self.accept()
