"""Outer chassis frame and rack screws."""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QWidget

from ..elements.base import ElementState
from ..look import current_look
from .base import _follow_look, look_element


class ChassisWrapperFrame(QFrame):
    """Full-window outer chassis; the skin's ``frame`` element paints it and sets the margins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rackChassis")
        _follow_look(self)

    def element(self):
        return look_element("frame")

    def update_frame_margins(self):
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(*self.element().content_margins(current_look()))

    def _on_look_changed(self):
        self.update_frame_margins()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()), ElementState(), current_look())
        p.end()


class RackScrew(QWidget):
    """Hardware rack screw: the skin's ``screws`` element (nothing in the minimal skin)."""
    def __init__(self, size=14, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def element(self):
        return look_element("screws")

    def paintEvent(self, _):
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()), ElementState(), current_look())
        p.end()
