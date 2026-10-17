"""Capture a global hotkey."""
from __future__ import annotations


from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from ...config import Hotkey
from ...core import Core
from ..widgets.buttons import make_button
from .parts import keep_wrapped_text_visible


class HotkeyDialog(QDialog):
    captured = Signal(object)

    def __init__(self, core: Core, parent=None, title="Set hotkey"):
        super().__init__(parent)
        self.core = core
        self.result_hotkey: Hotkey | None = None
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lbl = QLabel("Press the key combination you want to use…")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setObjectName("hotkeyPrompt")
        lay.addWidget(lbl)
        hint = QLabel("Modifiers (Ctrl / Shift / Alt / Win) are allowed. Esc cancels.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        lay.addWidget(hint)
        row = QHBoxLayout()
        clear = make_button("Remove hotkey", "danger")
        cancel = make_button("Cancel")
        row.addWidget(clear)
        row.addStretch()
        row.addWidget(cancel)
        lay.addLayout(row)
        clear.clicked.connect(self._clear)
        cancel.clicked.connect(self.reject)
        self.captured.connect(self._got)
        self.setMinimumWidth(400)
        keep_wrapped_text_visible(self)
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
