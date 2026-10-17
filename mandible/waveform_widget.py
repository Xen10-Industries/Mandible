"""Waveform display and draggable start/end trim marker widget for Soundboard."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
)

from .soundboard import SoundboardEngine
from .ui.look import current_look
from .ui.widgets.base import _follow_look, look_color

if TYPE_CHECKING:
    from .config import SoundboardClipConfig
    from .core import Core


class WaveformCanvas(QWidget):
    """Interactive canvas that paints the audio envelope with draggable start/end handles."""

    trimChanged = Signal(float, float)  # (start_s, end_s)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setMouseTracking(True)
        self.peaks: list[float] = []
        self.duration_s: float = 0.0
        self.trim_start_s: float = 0.0
        self.trim_end_s: float = 0.0
        self._dragging: str | None = None  # "start" | "end" | None
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def set_audio_data(self, peaks: list[float], duration_s: float, start_s: float, end_s: float):
        self.peaks = peaks
        self.duration_s = max(0.01, duration_s)
        self.trim_start_s = max(0.0, min(self.duration_s, start_s))
        self.trim_end_s = max(self.trim_start_s, min(self.duration_s, end_s if end_s > 0.0 else self.duration_s))
        self.update()

    def _x_to_seconds(self, x: float) -> float:
        w = max(1, self.width() - 20)
        x_rel = max(0.0, min(w, x - 10))
        return (x_rel / w) * self.duration_s

    def _seconds_to_x(self, s: float) -> float:
        w = max(1, self.width() - 20)
        frac = max(0.0, min(1.0, s / self.duration_s))
        return 10 + frac * w

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.duration_s <= 0.01:
            return
        x = event.position().x()
        xs = self._seconds_to_x(self.trim_start_s)
        xe = self._seconds_to_x(self.trim_end_s)

        # Handle hit-testing (within 12px)
        if abs(x - xs) <= 12:
            self._dragging = "start"
        elif abs(x - xe) <= 12:
            self._dragging = "end"
        else:
            # Clicked somewhere else: move closer handle
            s_click = self._x_to_seconds(x)
            if abs(s_click - self.trim_start_s) < abs(s_click - self.trim_end_s):
                self.trim_start_s = min(s_click, self.trim_end_s - 0.05)
                self._dragging = "start"
            else:
                self.trim_end_s = max(s_click, self.trim_start_s + 0.05)
                self._dragging = "end"
            self.trimChanged.emit(self.trim_start_s, self.trim_end_s)
            self.update()

    def mouseMoveEvent(self, event):
        if not self._dragging or self.duration_s <= 0.01:
            # Cursor hint
            x = event.position().x()
            xs = self._seconds_to_x(self.trim_start_s)
            xe = self._seconds_to_x(self.trim_end_s)
            if abs(x - xs) <= 8 or abs(x - xe) <= 8:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            return

        s = self._x_to_seconds(event.position().x())
        if self._dragging == "start":
            self.trim_start_s = max(0.0, min(self.trim_end_s - 0.05, s))
        elif self._dragging == "end":
            self.trim_end_s = min(self.duration_s, max(self.trim_start_s + 0.05, s))

        self.trimChanged.emit(self.trim_start_s, self.trim_end_s)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 1. Dark anodized backdrop
        p.fillRect(0, 0, w, h, look_color("bg.inset"))
        p.setPen(look_color("line.subtle"))
        p.drawRect(0, 0, w - 1, h - 1)

        # Subtle center line
        mid_y = h / 2.0
        p.setPen(QPen(look_color("line.subtle"), 1, Qt.PenStyle.DashLine))
        p.drawLine(10, int(mid_y), w - 10, int(mid_y))

        if not self.peaks or self.duration_s <= 0.01:
            p.setPen(look_color("text.secondary"))
            p.setFont(QFont("Consolas", 8))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Select a sound clip to view waveform")
            return

        # 2. Draw waveform peaks
        wave_w = w - 20
        n_peaks = len(self.peaks)
        bar_w = max(1.0, wave_w / float(n_peaks))

        grad = QLinearGradient(0, 0, 0, h)
        wave = look_color("readout.text")
        grad.setColorAt(0.0, wave)
        grad.setColorAt(0.5, wave.darker(150))
        grad.setColorAt(1.0, wave)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)

        for i, pk in enumerate(self.peaks):
            x = 10 + i * bar_w
            half_amp = max(2.0, (pk * (h - 16)) / 2.0)
            p.drawRoundedRect(QRectF(x, mid_y - half_amp, max(1.5, bar_w - 0.8), half_amp * 2), 1.0, 1.0)

        # 3. Trimmed out dimmed regions
        xs = self._seconds_to_x(self.trim_start_s)
        xe = self._seconds_to_x(self.trim_end_s)

        dim = look_color("bg.window")
        dim.setAlpha(160)
        dim_brush = QBrush(dim)
        if xs > 10:
            p.fillRect(QRectF(10, 0, xs - 10, h), dim_brush)
        if xe < w - 10:
            p.fillRect(QRectF(xe, 0, w - 10 - xe, h), dim_brush)

        # 4. Draggable Handles (Left = Start, Right = End)
        # Start handle (readout blue)
        start_col = look_color("readout.text")
        p.setPen(QPen(start_col, 2))
        p.drawLine(int(xs), 0, int(xs), h)
        p.setBrush(start_col)
        p.drawRoundedRect(QRectF(xs - 5, 0, 10, 14), 2, 2)
        p.setPen(look_color("bg.window"))
        p.setFont(QFont("Consolas", 6, QFont.Bold))
        p.drawText(QRectF(xs - 5, 1, 10, 12), Qt.AlignmentFlag.AlignCenter, "S")

        # End handle (accent)
        end_col = look_color("accent.hover")
        p.setPen(QPen(end_col, 2))
        p.drawLine(int(xe), 0, int(xe), h)
        p.setBrush(end_col)
        p.drawRoundedRect(QRectF(xe - 5, h - 14, 10, 14), 2, 2)
        p.setPen(look_color("text.on_accent"))
        p.setFont(QFont("Consolas", 6, QFont.Bold))
        p.drawText(QRectF(xe - 5, h - 13, 10, 12), Qt.AlignmentFlag.AlignCenter, "E")


class SoundboardWaveformWidget(QFrame):
    """Complete container with canvas, time labels, and trim action buttons."""

    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.current_clip: SoundboardClipConfig | None = None
        self.setObjectName("waveformPanel")


        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)

        # Header info row
        head_row = QHBoxLayout()
        self.clip_name_lbl = QLabel("NO CLIP SELECTED")
        self.clip_name_lbl.setObjectName("waveformClipName")
        self.timing_lbl = QLabel("Start: 0.00s | End: 0.00s | Len: 0.00s")
        self.timing_lbl.setObjectName("waveformTiming")
        self._timing: tuple[float, float, float] | None = None

        head_row.addWidget(self.clip_name_lbl)
        head_row.addStretch()
        head_row.addWidget(self.timing_lbl)
        lay.addLayout(head_row)

        # Waveform Canvas
        self.canvas = WaveformCanvas(self)
        self.canvas.trimChanged.connect(self._on_canvas_trim_changed)
        lay.addWidget(self.canvas)

        # Buttons row: [ PLAY TRIMMED ] [ STOP ] [ RESET TRIM ]
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.play_btn = QPushButton("PLAY TRIMMED")
        self.play_btn.setObjectName("waveformPlayBtn")

        self.play_btn.clicked.connect(self._play_trimmed)
        btn_row.addWidget(self.play_btn)

        self.stop_btn = QPushButton("STOP")
        self.stop_btn.clicked.connect(self._stop_clip)
        btn_row.addWidget(self.stop_btn)

        self.reset_btn = QPushButton("RESET TRIM")
        self.reset_btn.setObjectName("waveformResetBtn")
        self.reset_btn.clicked.connect(self._reset_trim)
        btn_row.addWidget(self.reset_btn)

        btn_row.addStretch()
        hint = QLabel("Drag S (Start) and E (End) markers to trim audio")
        hint.setObjectName("waveformHint")
        btn_row.addWidget(hint)
        lay.addLayout(btn_row)
        _follow_look(self)

    def _on_look_changed(self):
        if self._timing is not None:
            self._update_timing_label(*self._timing)

    def set_clip(self, clip: SoundboardClipConfig | None):
        self.current_clip = clip
        if not clip or not clip.path or not os.path.isfile(clip.path):
            self.clip_name_lbl.setText("NO CLIP SELECTED")
            self._timing = None
            self.timing_lbl.setText("Start: 0.00s | End: 0.00s | Len: 0.00s")
            self.canvas.set_audio_data([], 0.0, 0.0, 0.0)
            self.play_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.reset_btn.setEnabled(False)
            return

        self.clip_name_lbl.setText(clip.name.upper())
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)

        peaks, dur = SoundboardEngine.extract_waveform(clip.path, num_points=120)
        start_s = getattr(clip, "trim_start_s", 0.0)
        end_s = getattr(clip, "trim_end_s", 0.0)
        if end_s <= 0.0 or end_s > dur:
            end_s = dur

        self.canvas.set_audio_data(peaks, dur, start_s, end_s)
        self._update_timing_label(start_s, end_s, dur)

    def _update_timing_label(self, start_s: float, end_s: float, dur: float):
        self._timing = (start_s, end_s, dur)
        trimmed_len = max(0.0, end_s - start_s)
        c = current_look().palette.color
        self.timing_lbl.setText(
            f"Start: <span style='color:{c('readout.text')};'>{start_s:.2f}s</span> | "
            f"End: <span style='color:{c('status.danger')};'>{end_s:.2f}s</span> | "
            f"Trimmed: <span style='color:{c('status.ok')};font-weight:bold;'>{trimmed_len:.2f}s</span> / {dur:.2f}s"
        )

    def _on_canvas_trim_changed(self, start_s: float, end_s: float):
        if not self.current_clip:
            return
        self.current_clip.trim_start_s = round(start_s, 3)
        self.current_clip.trim_end_s = round(end_s, 3)
        self._update_timing_label(start_s, end_s, self.canvas.duration_s)
        self.core.save()

    def _play_trimmed(self):
        if self.current_clip:
            self.core.play_soundboard(self.current_clip)

    def _stop_clip(self):
        if self.current_clip:
            self.core.stop_soundboard(self.current_clip.id)

    def _reset_trim(self):
        if not self.current_clip:
            return
        self.current_clip.trim_start_s = 0.0
        self.current_clip.trim_end_s = self.canvas.duration_s
        self.canvas.trim_start_s = 0.0
        self.canvas.trim_end_s = self.canvas.duration_s
        self._update_timing_label(0.0, self.canvas.duration_s, self.canvas.duration_s)
        self.canvas.update()
        self.core.save()
