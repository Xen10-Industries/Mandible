"""Pilot lamp."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ..elements.base import metal, mix
from ..look import current_look
from .base import _follow_look, look_color


class PilotLamp(QWidget):
    """Faceted pilot lamp / jewel indicator; a plain dot in skins without depth."""
    def __init__(self, active=True, token="status.ok", size=18, parent=None):
        super().__init__(parent)
        self.active = active
        self.token = token
        self.setFixedSize(size, size)
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def set_active(self, on: bool):
        if self.active != on:
            self.active = on
            self.update()

    def paintEvent(self, _):
        look = current_look()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect().adjusted(1, 1, -1, -1))
        jr = r.adjusted(2.5, 2.5, -2.5, -2.5)
        on = look_color(self.token)

        if look.skin.shape.get("shadow.depth", 1) == 0:
            # Flat: a solid status dot when on, a hollow ring when off (fill and shape, not
            # colour alone), big enough to read on a 10 px chain-card lamp (was a 3 px dot).
            d = max(6.0, round(self.width() * 0.6))
            dot = QRectF((self.width() - d) / 2.0, (self.height() - d) / 2.0, d, d)
            if self.active:
                p.setPen(Qt.NoPen)
                p.setBrush(on)
                p.drawEllipse(dot)
            else:
                # The pill's off outline token: it clears 3:1 on every surface.
                p.setPen(QPen(look_color("text.secondary"), 1.2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(dot.adjusted(0.6, 0.6, -0.6, -0.6))
            p.end()
            return

        # Chrome bezel ring
        m = metal(look)
        bg = QLinearGradient(0, 0, r.width(), r.height())
        bg.setColorAt(0.0, mix(m.hi, m.light, 0.5))
        bg.setColorAt(0.5, mix(m.dark, m.mid, 0.5))
        bg.setColorAt(1.0, m.mid)
        p.setPen(QPen(m.black, 1))
        p.setBrush(QBrush(bg))
        p.drawEllipse(r)

        # Glass jewel
        if self.active:
            jg = QRadialGradient(jr.center(), jr.width() / 2)
            jg.setColorAt(0.0, m.hi)
            jg.setColorAt(0.35, on)
            jg.setColorAt(1.0, on.darker(180))
            p.setBrush(QBrush(jg))
            p.setPen(QPen(on.lighter(140), 1))
        else:
            p.setBrush(look_color("bg.raised"))
            p.setPen(QPen(look_color("line.subtle"), 1))
        p.drawEllipse(jr)
        p.end()
