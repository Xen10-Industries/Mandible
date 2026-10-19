"""Inline value editing and the gain slider."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSlider, QStackedWidget, QWidget

from ..look import space


def parse_audio_value(text: str, default: float, min_val: float, max_val: float) -> float:
    """Parses a numeric value from text input, handling dB, %, s, +/-, and -inf."""
    text = text.strip().lower()
    if not text:
        return default
    if "inf" in text:
        return min_val
    m = re.search(r"[-+]?(?:\d*\.?\d+|\d+)", text)
    if m:
        try:
            val = float(m.group(0))
            return max(min_val, min(max_val, val))
        except ValueError:
            pass
    return default


class InlineValueEdit(QLineEdit):
    """Sleek studio inline value editor with Enter-commit and Escape-cancel."""
    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inlineValueEdit")   # styled by the generated stylesheet
        self._committing = False

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.cancelled.emit()
            ev.accept()
            return
        elif ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if self.isVisible() and not self._committing:
            self._commit()

    def _commit(self):
        if self._committing or not self.isVisible():
            return
        self._committing = True
        try:
            self.committed.emit(self.text())
        finally:
            self._committing = False


class GainSlider(QWidget):
    changed = Signal(float)

    def __init__(self, label: str, value_db: float):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(space(2))
        lbl = QLabel(label)
        lbl.setObjectName("gainLabel")
        lay.addWidget(lbl)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(-600, 240)  # tenths of dB
        self.slider.setValue(int(round(value_db * 10)))
        self.slider.setMinimumWidth(90)
        self.slider.setToolTip("Drag or scroll to adjust · Double-click to reset (0.0 dB)")
        self.slider.mouseDoubleClickEvent = lambda e: self.slider.setValue(0)
        lay.addWidget(self.slider, 1)

        self.val_stack = QStackedWidget()
        self.val_stack.setMinimumWidth(62)
        self.val_stack.setFixedHeight(22)

        self.val = QLabel()
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.val.setObjectName("gainValue")
        self.val.setCursor(Qt.IBeamCursor)
        self.val.setToolTip("Double-click to type custom value")
        self.val.mouseDoubleClickEvent = self._start_val_edit

        self.val_edit = InlineValueEdit()
        self.val_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.val_edit.setObjectName("gainValueEdit")
        self.val_edit.committed.connect(self._commit_val_edit)
        self.val_edit.cancelled.connect(lambda: self.val_stack.setCurrentIndex(0))

        self.val_stack.addWidget(self.val)
        self.val_stack.addWidget(self.val_edit)
        self.val_stack.setCurrentIndex(0)
        lay.addWidget(self.val_stack)

        self.slider.valueChanged.connect(self._on)
        self._on(self.slider.value(), emit=False)

    def _start_val_edit(self, ev=None):
        cur_v = self.slider.value() / 10.0
        self.val_edit.setText(f"{cur_v:+.1f}")
        self.val_stack.setCurrentIndex(1)
        self.val_edit.selectAll()
        self.val_edit.setFocus()

    def _commit_val_edit(self, txt: str):
        if self.val_stack.currentIndex() != 1:
            return
        self.val_stack.setCurrentIndex(0)
        cur_v = self.slider.value() / 10.0
        new_v = parse_audio_value(txt, default=cur_v, min_val=-60.0, max_val=24.0)
        self.slider.setValue(int(round(new_v * 10)))

    def _on(self, v, emit=True):
        self.val.setText(f"{v / 10:+.1f} dB")
        if emit:
            self.changed.emit(v / 10)

    def set_value_quiet(self, value_db: float):
        v = max(-600, min(240, int(round(value_db * 10))))
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.val.setText(f"{v / 10:+.1f} dB")
