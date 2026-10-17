"""Microphone pre-processing settings."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
                               QSlider, QSpinBox, QVBoxLayout)

from ...core import Core


class PreFXDialog(QDialog):
    """Microphone Pre-processing: High-pass rumble filter, RNNoise AI, and Noise Gate."""
    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.cfg = copy.copy(core.cfg.prefx)
        self.setWindowTitle("Microphone Clean-up (Pre-FX)")
        self.resize(460, 380)
        lay = QVBoxLayout(self)

        # Highpass
        hp_box = QGroupBox("Rumble Filter (Low-Cut)")
        hp_lay = QVBoxLayout(hp_box)
        self.hp_en = QCheckBox("Enable High-pass filter (removes desk thumps, AC rumble, and plosives)")
        self.hp_en.setChecked(self.cfg.highpass_enabled)
        hp_row = QHBoxLayout()
        hp_row.addWidget(QLabel("Cutoff frequency:"))
        self.hp_freq = QSpinBox()
        self.hp_freq.setRange(20, 300)
        self.hp_freq.setValue(int(self.cfg.highpass_cutoff_hz))
        self.hp_freq.setSuffix(" Hz")
        hp_row.addWidget(self.hp_freq)
        hp_row.addStretch()
        hp_lay.addWidget(self.hp_en)
        hp_lay.addLayout(hp_row)
        lay.addWidget(hp_box)

        # AI RNNoise
        rnn_box = QGroupBox("AI Noise Suppression (RNNoise)")
        rnn_lay = QVBoxLayout(rnn_box)
        self.rnn_en = QCheckBox("Enable RNNoise AI suppression (removes fan noise, keyboard clicks, and mic hiss)")
        self.rnn_en.setChecked(self.cfg.rnnoise_enabled)
        rnn_row = QHBoxLayout()
        rnn_row.addWidget(QLabel("Suppression intensity:"))
        self.rnn_wet = QSlider(Qt.Horizontal)
        self.rnn_wet.setRange(0, 100)
        self.rnn_wet.setValue(int(round(self.cfg.rnnoise_wet * 100)))
        self.rnn_lbl = QLabel(f"{self.rnn_wet.value()}%")
        self.rnn_wet.valueChanged.connect(lambda v: self.rnn_lbl.setText(f"{v}%"))
        rnn_row.addWidget(self.rnn_wet, 1)
        rnn_row.addWidget(self.rnn_lbl)
        rnn_lay.addWidget(self.rnn_en)
        rnn_lay.addLayout(rnn_row)
        lay.addWidget(rnn_box)

        # Noise Gate
        gate_box = QGroupBox("Noise Gate (Silence during pauses)")
        gate_lay = QVBoxLayout(gate_box)
        self.gate_en = QCheckBox("Enable Noise Gate (completely mutes room background when you are silent)")
        self.gate_en.setChecked(self.cfg.noise_gate_enabled)
        g_row1 = QHBoxLayout()
        g_row1.addWidget(QLabel("Threshold:"))
        self.gate_thresh = QSlider(Qt.Horizontal)
        self.gate_thresh.setRange(-70, -20)
        self.gate_thresh.setValue(int(round(self.cfg.noise_gate_threshold_db)))
        self.gate_t_lbl = QLabel(f"{self.gate_thresh.value()} dB")
        self.gate_thresh.valueChanged.connect(lambda v: self.gate_t_lbl.setText(f"{v} dB"))
        g_row1.addWidget(self.gate_thresh, 1)
        g_row1.addWidget(self.gate_t_lbl)

        g_row2 = QHBoxLayout()
        g_row2.addWidget(QLabel("Release:"))
        self.gate_rel = QSpinBox()
        self.gate_rel.setRange(10, 1000)
        self.gate_rel.setValue(int(round(self.cfg.noise_gate_release_ms)))
        self.gate_rel.setSuffix(" ms")
        g_row2.addWidget(self.gate_rel)
        g_row2.addStretch()

        gate_lay.addWidget(self.gate_en)
        gate_lay.addLayout(g_row1)
        gate_lay.addLayout(g_row2)
        lay.addWidget(gate_box)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        self.cfg.highpass_enabled = self.hp_en.isChecked()
        self.cfg.highpass_cutoff_hz = float(self.hp_freq.value())
        self.cfg.rnnoise_enabled = self.rnn_en.isChecked()
        self.cfg.rnnoise_wet = self.rnn_wet.value() / 100.0
        self.cfg.noise_gate_enabled = self.gate_en.isChecked()
        self.cfg.noise_gate_threshold_db = float(self.gate_thresh.value())
        self.cfg.noise_gate_release_ms = float(self.gate_rel.value())
        self.core.set_prefx(self.cfg)
        self.accept()
