"""Screw variants: ``corners_only`` (a countersunk steel screw) and ``none``.

The host places one element per corner; ``corners_only`` paints a single screw
filling its rect. ``draw_silver_screw`` is the bigger chrome-dome screw the
frames use on their rails and cheeks.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QLinearGradient, QPainter, QPen

from ..look import Look
from . import registry
from .base import Element, ElementState, alpha, metal, mix

__all__ = ["CornersOnly", "NoScrews", "draw_silver_screw"]


def draw_silver_screw(p: QPainter, cx: float, cy: float, look: Look,
                      r: float = 5.4, angle_deg: float = 35.0) -> None:
    """Bright brushed silver/chrome countersunk screwhead with a cross drive."""
    m = metal(look)
    # Recessed shadow ring
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(alpha(m.black, 150))
    p.drawEllipse(QPointF(cx + 0.6, cy + 0.9), r + 0.8, r + 0.8)

    # Machined silver dome
    sg = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
    sg.setColorAt(0.0, m.hi)
    sg.setColorAt(0.3, mix(m.hi, m.light, 0.5))
    sg.setColorAt(0.7, m.light)
    sg.setColorAt(1.0, m.mid)
    p.setPen(QPen(m.dark, 0.9))
    p.setBrush(sg)
    p.drawEllipse(QPointF(cx, cy), r, r)

    # Specular rim highlight
    p.setPen(QPen(alpha(m.hi, 110), 0.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(cx - r + 1.0, cy - r + 1.0, (r - 1.0) * 2, (r - 1.0) * 2), 45 * 16, 160 * 16)

    # Cross drive slot
    rad1 = math.radians(angle_deg)
    rad2 = math.radians(angle_deg + 90.0)
    arm = r * 0.56
    p.setPen(QPen(m.black, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for rad in (rad1, rad2):
        p.drawLine(QPointF(cx - arm * math.cos(rad), cy - arm * math.sin(rad)),
                   QPointF(cx + arm * math.cos(rad), cy + arm * math.sin(rad)))


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
