"""Soundboard clip management."""
from __future__ import annotations

import os
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ...config import SoundboardClipConfig
from ...core import Core
from ...waveform_widget import SoundboardWaveformWidget
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width
from ..widgets.buttons import make_button
from .hotkey import HotkeyDialog


class SoundboardDialog(QDialog):
    """Soundboard management: add clips, assign hotkeys, adjust volumes, and trigger sounds."""
    ROW_PAD = 8   # the table items' vertical padding (2 px a side in the stylesheet) plus grid
    COL_PAD = 16  # a column's horizontal item padding (6 px a side in the stylesheet) plus grid

    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("Soundboard")
        self._spaced = SpacedLayouts()
        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=3)

        self.table = QTableWidget()
        self.table.setObjectName("soundboardTable")
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Name", "Hotkey", "Volume", "Out", "Headphones", "Action"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        for col in (1, 3, 4, 5):          # sized to their buttons / check boxes (_fit_columns)
            header.setSectionResizeMode(col, QHeaderView.Fixed)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        lay.addWidget(self.table, 1)

        # Waveform & Trim Editor
        self.waveform_widget = SoundboardWaveformWidget(self.core, self)
        lay.addWidget(self.waveform_widget)

        # Soundboard Mic Ducking Options Strip
        duck_strip = QFrame()
        duck_strip.setObjectName("duckStrip")
        duck_lay = self._spaced.add(QHBoxLayout(duck_strip), spacing=2, margins=(1, 2, 1, 2))

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
        duck_lay.addWidget(self.duck_val_lbl)
        reserve_text_width(self.duck_val_lbl, "-30 dB")
        self.duck_val_lbl.setFixedWidth(self.duck_val_lbl.minimumWidth())

        lay.addWidget(duck_strip)

        bottom = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        add_btn = make_button("Add sound clip…", icon="plus")
        stop_all_btn = make_button("Stop all sounds", icon="stop")
        bottom.addWidget(add_btn)
        bottom.addWidget(stop_all_btn)
        bottom.addStretch()
        close_btn = make_button("Close")
        bottom.addWidget(close_btn)
        lay.addLayout(bottom)

        add_btn.clicked.connect(self._add_clip)
        stop_all_btn.clicked.connect(core.stop_all_soundboard)
        close_btn.clicked.connect(self.accept)
        core.soundboardChanged.connect(self._refresh_rows)

        self.resize(760, 520)
        self._refresh_rows()
        _follow_look(self)

    def _fit_row_height(self) -> None:
        """Rows are as tall as their tallest cell widget needs plus the stylesheet's item
        padding (the buttons keep their natural size; the rows follow them)."""
        need = 0
        for row in range(self.table.rowCount()):
            for col in range(self.table.columnCount()):
                w = self.table.cellWidget(row, col)
                if w is not None:
                    w.ensurePolished()
                    need = max(need, w.sizeHint().height())
        if need:
            # a couple of rows stay in view however small the dialog is made
            self.table.setMinimumHeight(self.table.horizontalHeader().sizeHint().height()
                                        + 2 * (need + self.ROW_PAD) + 2 * self.table.frameWidth())
            self.table.verticalHeader().setDefaultSectionSize(need + self.ROW_PAD)
            for row in range(self.table.rowCount()):
                self.table.setRowHeight(row, need + self.ROW_PAD)

    def _fit_columns(self) -> None:
        """Hotkey, route and action columns are as wide as their widest content (header text or
        cell widget), so the hotkey button text and "Headphones" are never cut; Name and Volume
        share the rest."""
        header = self.table.horizontalHeader()
        for col in (1, 3, 4, 5):
            need = header.sectionSizeHint(col)
            for row in range(self.table.rowCount()):
                w = self.table.cellWidget(row, col)
                if w is not None:
                    w.ensurePolished()
                    need = max(need, w.sizeHint().width() + self.COL_PAD)
            self.table.setColumnWidth(col, need)

    @staticmethod
    def _centered(widget: QWidget) -> QWidget:
        """A cell holding ``widget`` in the middle of its column."""
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(widget)
        row.addStretch(1)
        return cell

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._fit_row_height()
        self._fit_columns()

    def _refresh_rows(self):
        selected = self.table.currentRow() if self.table.selectionModel().hasSelection() else -1
        self.table.setRowCount(0)
        for row, clip in enumerate(self.core.cfg.soundboard):
            self.table.insertRow(row)

            # Name
            self.table.setItem(row, 0, QTableWidgetItem(clip.name))

            # Hotkey button
            hk_btn = make_button(clip.hotkey.label if clip.hotkey.is_set() else "Set key…", "quiet",
                                 icon="hotkey", tooltip="Hotkey that plays this clip")
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
            self.table.setCellWidget(row, 3, self._centered(out_cb))

            # Route mon
            mon_cb = QCheckBox()
            mon_cb.setChecked(clip.route_monitor)
            mon_cb.toggled.connect(partial(self._route_mon_changed, clip))
            self.table.setCellWidget(row, 4, self._centered(mon_cb))

            # Play / Stop button
            playing = self.core.engine.soundboard.is_playing(clip.id)
            action_btn = make_button("Stop" if playing else "Play", "quiet",
                                     icon="stop" if playing else "play",
                                     tooltip="Stop this clip" if playing else "Play this clip")
            action_btn.clicked.connect(partial(self._toggle_play, clip))
            self.table.setCellWidget(row, 5, action_btn)

        self._fit_row_height()
        self._fit_columns()
        # Nothing is pre-selected: the detail panel says so until the user picks a clip, and
        # a refresh keeps only a selection the user made.
        if 0 <= selected < len(self.core.cfg.soundboard):
            self.table.selectRow(selected)
            self.waveform_widget.set_clip(self.core.cfg.soundboard[selected])
        else:
            self.table.clearSelection()
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
        row = rows[0].row() if rows else -1
        if 0 <= row < len(self.core.cfg.soundboard):
            self.waveform_widget.set_clip(self.core.cfg.soundboard[row])
        else:
            self.waveform_widget.set_clip(None)

    def _on_duck_toggled(self, checked: bool):
        db = float(self.duck_slider.value())
        self.core.set_soundboard_ducking(checked, db)

    def _on_duck_db_changed(self, val: int):
        self.duck_val_lbl.setText(f"{val} dB")
        if self.duck_en.isChecked():
            self.core.set_soundboard_ducking(True, float(val))
