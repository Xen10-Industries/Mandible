"""Channel strip card."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .base import _follow_look, look_color
from .meters import LevelMeter
from .sliders import GainSlider


class _ChannelDot(QWidget):
    """Small round channel colour marker drawn from a palette token."""
    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self.token = token
        self.setFixedSize(8, 8)
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(look_color(self.token))
        p.drawEllipse(QRectF(0, 0, self.width(), self.height()))
        p.end()


class ChannelStripCard(QFrame):
    """Studio Console Channel Strip containing meter + gain slider.

    ``dot_token`` is the palette token of the channel marker colour (e.g. ``status.ok``).
    """
    def __init__(self, title: str, dot_token: str, meter: LevelMeter, slider: GainSlider, parent=None):
        super().__init__(parent)
        self.setObjectName("channelStripCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(_ChannelDot(dot_token))

        t_lbl = QLabel(title)
        t_lbl.setObjectName("channelTitle")
        head.addWidget(t_lbl, 1)
        lay.addLayout(head)

        lay.addWidget(meter)
        lay.addWidget(slider)
