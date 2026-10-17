"""Hardware switch."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from ..elements.base import ElementState
from ..look import current_look
from .base import _follow_look, look_element


class HardwareSwitch(QWidget):
    """Two-state hardware switch; the skin's ``switch`` element paints it (bat toggle,
    rocker or pill). ``compact`` and ``vertical`` pick the smaller widget variants."""
    toggled = Signal(bool)

    def __init__(self, active: bool = True, compact: bool = False, vertical: bool = False, parent=None):
        super().__init__(parent)
        self.active = bool(active)
        self.compact = compact
        self.vertical = vertical
        if self.vertical:
            self.setFixedSize(46, 28)
        elif self.compact:
            self.setFixedSize(50, 24)
        else:
            self.setFixedSize(68, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to toggle ON / BYPASS")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def element(self):
        return look_element("switch", compact=self.compact, vertical=self.vertical)

    def set_active(self, on: bool):
        if self.active != bool(on):
            self.active = bool(on)
            self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.active = not self.active
            self.update()
            self.toggled.emit(self.active)
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def paintEvent(self, _):
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()),
                             ElementState(active=self.active), current_look())
        p.end()
