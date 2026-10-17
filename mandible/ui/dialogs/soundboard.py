"""Soundboard clip management."""
from __future__ import annotations

import os
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QSlider,
                               QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ...config import SoundboardClipConfig
from ...core import Core
from ...waveform_widget import SoundboardWaveformWidget
from .hotkey import HotkeyDialog


class SoundboardDialog(QDialog):
    """Soundboard management: add clips, assign hotkeys, adjust volumes, and trigger sounds."""
    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("Soundboard")
        self.resize(680, 420)
        lay = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Name", "Hotkey", "Volume", "Out", "Headphones", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        lay.addWidget(self.table, 1)

        # Waveform & Trim Editor
        self.waveform_widget = SoundboardWaveformWidget(self.core, self)
        lay.addWidget(self.waveform_widget)

        # Soundboard Mic Ducking Options Strip
        duck_strip = QFrame()
        duck_strip.setObjectName("duckStrip")
        duck_lay = QHBoxLayout(duck_strip)
        duck_lay.setContentsMargins(6, 4, 6, 4)
        duck_lay.setSpacing(10)

        self.duck_en = QCheckBox("Duck microphone during soundboard playback")
        self.duck_en.setChecked(getattr(self.core.cfg, "soundboard_ducking_enabled", False))
        self.duck_en.toggled.connect(self._on_duck_toggled)
        duck_lay.addWidget(self.duck_en)

        duck_lay.addStretch()

        duck_lbl = QLabel("Attenuation:")
        duck_lbl.setObjectName("duckLabel")
        duck_lay.addWidget(duck_lbl)

        self.duck_slider = QSlider(Qt.Horizontal)
        self.duck_slider.setRange(-30, -3)
        self.duck_slider.setValue(int(round(getattr(self.core.cfg, "soundboard_duck_db", -12.0))))
        self.duck_slider.setFixedWidth(100)
        self.duck_slider.valueChanged.connect(self._on_duck_db_changed)
        duck_lay.addWidget(self.duck_slider)

        self.duck_val_lbl = QLabel(f"{self.duck_slider.value()} dB")
        self.duck_val_lbl.setObjectName("duckValue")
        self.duck_val_lbl.setFixedWidth(45)
        duck_lay.addWidget(self.duck_val_lbl)

        lay.addWidget(duck_strip)

        bottom = QHBoxLayout()
        add_btn = QPushButton("+ Add sound clip…")
        stop_all_btn = QPushButton("Stop all sounds")
        stop_all_btn.setObjectName("testButton")
        bottom.addWidget(add_btn)
        bottom.addWidget(stop_all_btn)
        bottom.addStretch()
        close_btn = QPushButton("Close")
        bottom.addWidget(close_btn)
        lay.addLayout(bottom)

        add_btn.clicked.connect(self._add_clip)
        stop_all_btn.clicked.connect(core.stop_all_soundboard)
        close_btn.clicked.connect(self.accept)
        core.soundboardChanged.connect(self._refresh_rows)

        self.resize(760, 520)
        self._refresh_rows()

    def _refresh_rows(self):
        self.table.setRowCount(0)
        for row, clip in enumerate(self.core.cfg.soundboard):
            self.table.insertRow(row)

            # Name
            self.table.setItem(row, 0, QTableWidgetItem(clip.name))

            # Hotkey button
            hk_btn = QPushButton(clip.hotkey.label if clip.hotkey.is_set() else "Set key…")
            hk_btn.clicked.connect(partial(self._set_hotkey, clip))
            self.table.setCellWidget(row, 1, hk_btn)

            # Volume slider
            vol_slider = QSlider(Qt.Horizontal)
            vol_slider.setRange(-40, 12)
            vol_slider.setValue(int(round(clip.volume_db)))
            vol_slider.valueChanged.connect(partial(self._vol_changed, clip))
            self.table.setCellWidget(row, 2, vol_slider)

            # Route out
            out_cb = QCheckBox()
            out_cb.setChecked(clip.route_output)
            out_cb.toggled.connect(partial(self._route_out_changed, clip))
            self.table.setCellWidget(row, 3, out_cb)

            # Route mon
            mon_cb = QCheckBox()
            mon_cb.setChecked(clip.route_monitor)
            mon_cb.toggled.connect(partial(self._route_mon_changed, clip))
            self.table.setCellWidget(row, 4, mon_cb)

            # Play / Stop button
            action_btn = QPushButton("STOP" if self.core.engine.soundboard.is_playing(clip.id) else "PLAY")
            action_btn.clicked.connect(partial(self._toggle_play, clip))
            self.table.setCellWidget(row, 5, action_btn)

        if self.core.cfg.soundboard:
            cur_r = self.table.currentRow()
            r_sel = cur_r if 0 <= cur_r < len(self.core.cfg.soundboard) else 0
            self.table.selectRow(r_sel)
            self.waveform_widget.set_clip(self.core.cfg.soundboard[r_sel])
        else:
            self.waveform_widget.set_clip(None)

    def _add_clip(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose audio clip",
            "",
            "Audio files (*.wav *.mp3 *.ogg *.flac *.aac *.m4a)",
        )
        if path:
            name = os.path.splitext(os.path.basename(path))[0]
            clip = SoundboardClipConfig(name=name, path=path)
            self.core.cfg.soundboard.append(clip)
            self.core.rebind_hotkeys()
            self.core.save()
            self._refresh_rows()

    def _set_hotkey(self, clip: SoundboardClipConfig):
        dlg = HotkeyDialog(self.core, self, f"Hotkey for '{clip.name}'")
        if dlg.exec() and dlg.result_hotkey is not None:
            clip.hotkey = dlg.result_hotkey
            self.core.rebind_hotkeys()
            self.core.save()
            self._refresh_rows()

    def _vol_changed(self, clip: SoundboardClipConfig, val: int):
        clip.volume_db = float(val)
        self.core.save()

    def _route_out_changed(self, clip: SoundboardClipConfig, val: bool):
        clip.route_output = val
        self.core.save()

    def _route_mon_changed(self, clip: SoundboardClipConfig, val: bool):
        clip.route_monitor = val
        self.core.save()

    def _toggle_play(self, clip: SoundboardClipConfig):
        if self.core.engine.soundboard.is_playing(clip.id):
            self.core.stop_soundboard(clip.id)
        else:
            self.core.play_soundboard(clip)
        self._refresh_rows()

    def _on_table_selection_changed(self):
        rows = self.table.selectedIndexes()
        if not rows:
            return
        row = rows[0].row()
        if 0 <= row < len(self.core.cfg.soundboard):
            clip = self.core.cfg.soundboard[row]
            self.waveform_widget.set_clip(clip)

    def _on_duck_toggled(self, checked: bool):
        db = float(self.duck_slider.value())
        self.core.set_soundboard_ducking(checked, db)

    def _on_duck_db_changed(self, val: int):
        self.duck_val_lbl.setText(f"{val} dB")
        if self.duck_en.isChecked():
            self.core.set_soundboard_ducking(True, float(val))
