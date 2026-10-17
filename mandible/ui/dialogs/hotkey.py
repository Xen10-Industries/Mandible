"""Capture a global hotkey."""
from __future__ import annotations


from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ...config import Hotkey
from ...core import Core


class HotkeyDialog(QDialog):
    captured = Signal(object)

    def __init__(self, core: Core, parent=None, title="Set hotkey"):
        super().__init__(parent)
        self.core = core
        self.result_hotkey: Hotkey | None = None
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lbl = QLabel("Press the key combination you want to use…\n\n"
                     "Modifiers (Ctrl / Shift / Alt / Win) are allowed.\nEsc cancels.")
        lbl.setAlignment(Qt.AlignCenter)
        f = lbl.font()
        f.setPointSize(f.pointSize() + 1)
        lbl.setFont(f)
        lay.addWidget(lbl)
        row = QHBoxLayout()
        clear = QPushButton("Remove hotkey")
        cancel = QPushButton("Cancel")
        row.addWidget(clear)
        row.addStretch()
        row.addWidget(cancel)
        lay.addLayout(row)
        clear.clicked.connect(self._clear)
        cancel.clicked.connect(self.reject)
        self.captured.connect(self._got)
        self.setMinimumWidth(340)
        core.hotkeys.capture_next(lambda hk: self.captured.emit(hk))

    def _got(self, hk):
        if hk is None:
            self.reject()
            return
        self.result_hotkey = hk
        self.accept()

    def _clear(self):
        self.result_hotkey = Hotkey()
        self.accept()

    def done(self, r):
        self.core.hotkeys.cancel_capture()
        super().done(r)
