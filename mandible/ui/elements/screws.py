"""Screw variants: ``corners_only`` (a countersunk steel screw) and ``none``.

The host places one element per corner; ``corners_only`` paints a single screw
filling its rect (the metal rack and wood cheeks frames bolt their four corners with it).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QLinearGradient, QPainter, QPen

from ..look import Look
from . import registry
from .base import Element, ElementState, metal, mix

__all__ = ["CornersOnly", "NoScrews"]


class CornersOnly(Element):
    """Countersunk light brushed-steel rack screw."""

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        m = metal(look)
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) / 2.0 - 1.0
        p.setPen(QPen(m.black, 0.9))
        g = QLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
        g.setColorAt(0.0, mix(m.hi, m.light, 0.15))
        g.setColorAt(0.35, m.light)
        g.setColorAt(0.75, mix(m.light, m.mid, 0.6))
        g.setColorAt(1.0, m.dark)
        p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0))

        # Dead-centre cross socket
        arm = radius * 0.52
        p.setPen(QPen(m.black, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
        p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))

    def size_hint(self, look: Look) -> QSize:
        return QSize(14, 14)


class NoScrews(Element):
    """Paints nothing (the minimal skin hides its screws)."""

    def size_hint(self, look: Look) -> QSize:
        return QSize(0, 0)


registry.register("screws", "corners_only", CornersOnly, "Corner screws")
registry.register("screws", "none", NoScrews, "None")
