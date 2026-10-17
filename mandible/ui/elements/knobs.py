"""Rotary knob variants: ``machined``, ``vintage_bakelite`` and ``flat_ring``.

Each paints a title, the dial and (when ``state.readout`` is set) a value readout
into the widget rect. ``state.value`` is the knob position 0..1 over a 270 degree
sweep from 7 o'clock to 5 o'clock.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from ..look import Look
from . import registry
from .base import Element, ElementState, alpha, metal, mix, tok

__all__ = ["Machined", "VintageBakelite", "FlatRing"]

_SWEEP = 270.0
_START = 225.0


class _Knob(Element):
    def __init__(self, compact: bool = False) -> None:
        self.compact = bool(compact)

    def size_hint(self, look: Look) -> QSize:
        return QSize(64, 58) if self.compact else QSize(54, 62)

    # ----------------------------------------------------------- shared pieces
    def _geometry(self, w: float) -> tuple[float, float, float]:
        cx = w / 2.0
        cy = 26.0 if self.compact else 27.5
        radius = 10.8 if self.compact else 11.8
        return cx, cy, radius

    def _title(self, p: QPainter, w: float, title: str, color: QColor) -> None:
        f = p.font()
        f.setFamily("Segoe UI")
        f.setPointSizeF(6.5 if self.compact else 7.0)
        f.setBold(True)
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(0, 0, w, 11.5), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, title)

    def _readout(self, p: QPainter, w: float, h: float, text: str, color: QColor, bold: bool) -> None:
        f = p.font()
        f.setFamily("Consolas")
        f.setPointSizeF(7.0 if self.compact else 7.5)
        f.setBold(bold)
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(0, h - 14, w, 14),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text)

    @staticmethod
    def _pointer(p: QPainter, cx: float, cy: float, angle_rad: float, r_in: float, r_out: float,
                 color: QColor, width: float) -> None:
        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx + r_in * math.cos(angle_rad), cy - r_in * math.sin(angle_rad)),
                   QPointF(cx + r_out * math.cos(angle_rad), cy - r_out * math.sin(angle_rad)))


class Machined(_Knob):
    """Milled aluminium 500-series knob with tick marks, graduation arc and LCD readout."""

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        frac = max(0.0, min(1.0, float(state.value)))
        m = metal(look)
        accent = tok(look, "accent")
        cx, cy, radius = self._geometry(w)
        angle_rad = math.radians(_START - frac * _SWEEP)
        self._title(p, w, state.label, mix(m.hi, m.light, 0.3))

        # Outer tick marks
        unlit = mix(tok(look, "line.subtle"), m.mid, 0.5)
        for i in range(11):
            tf = i / 10.0
            ta = math.radians(_START - tf * _SWEEP)
            p.setPen(QPen(accent if tf <= frac + 0.01 else unlit, 1.1,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx + (radius + 2.2) * math.cos(ta), cy - (radius + 2.2) * math.sin(ta)),
                       QPointF(cx + (radius + 4.0) * math.cos(ta), cy - (radius + 4.0) * math.sin(ta)))

        # Active arc ring inside the ticks
        track_r = radius + 2.0
        track = QRectF(cx - track_r, cy - track_r, track_r * 2, track_r * 2)
        p.setPen(QPen(tok(look, "bg.inset"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(track, int(_START * 16), int(-_SWEEP * 16))
        if frac > 0.005:
            p.setPen(QPen(accent, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(track, int(_START * 16), int(-frac * _SWEEP * 16))

        # Drop shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(m.black, 150))
        p.drawEllipse(QPointF(cx + 0.7, cy + 1.3), radius, radius)

        # Knurled metallic skirt
        dial = QLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
        dial.setColorAt(0.0, mix(m.mid, m.light, 0.2))
        dial.setColorAt(0.5, mix(m.dark, m.mid, 0.4))
        dial.setColorAt(1.0, m.deep)
        p.setPen(QPen(m.mid, 0.9))
        p.setBrush(dial)
        p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # Brushed aluminium inner cap
        cap_r = radius * 0.76
        cap = QLinearGradient(cx - cap_r, cy - cap_r, cx + cap_r, cy + cap_r)
        cap.setColorAt(0.0, mix(m.dark, m.mid, 0.5))
        cap.setColorAt(0.5, tok(look, "bg.raised"))
        cap.setColorAt(1.0, tok(look, "bg.inset"))
        p.setPen(QPen(mix(m.dark, m.mid, 0.8), 0.7))
        p.setBrush(cap)
        p.drawEllipse(QPointF(cx, cy), cap_r, cap_r)

        self._pointer(p, cx, cy, angle_rad, 3.2, radius - 1.2, tok(look, "text.primary"), 1.8)

        # Recessed LCD readout box
        if state.readout:
            lcd = QRectF(3.0, h - 14.5, w - 6.0, 13.5)
            p.setPen(QPen(tok(look, "line.subtle"), 0.9))
            p.setBrush(tok(look, "bg.inset").darker(130))
            p.drawRoundedRect(lcd, 2.5, 2.5)
            f = p.font()
            f.setFamily("Consolas")
            f.setPointSizeF(6.8 if self.compact else 7.2)
            f.setBold(False)
            p.setFont(f)
            p.setPen(tok(look, "readout.text"))
            p.drawText(lcd, Qt.AlignmentFlag.AlignCenter, state.readout)


class VintageBakelite(_Knob):
    """Skirted bakelite pointer knob ringed by scale dots."""

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        frac = max(0.0, min(1.0, float(state.value)))
        m = metal(look)
        accent = tok(look, "accent")
        bake = tok(look, "status.warn.subtle")        # warm brown-black bakelite
        cx, cy, radius = self._geometry(w)
        angle_rad = math.radians(_START - frac * _SWEEP)
        self._title(p, w, state.label, tok(look, "text.primary"))

        # Perimeter scale dots
        dot_r = radius + 3.4
        num_dots = 11
        unlit = mix(bake, m.mid, 0.5)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(num_dots):
            df = i / float(num_dots - 1)
            da = math.radians(_START - df * _SWEEP)
            p.setBrush(accent if df <= frac + 0.02 else unlit)
            p.drawEllipse(QPointF(cx + dot_r * math.cos(da), cy - dot_r * math.sin(da)), 1.25, 1.25)

        # Drop shadow
        p.setBrush(alpha(m.black, 140))
        p.drawEllipse(QPointF(cx + 0.8, cy + 1.4), radius + 0.8, radius + 0.8)

        # Outer dark bakelite skirt
        p.setPen(QPen(m.black, 1.0))
        p.setBrush(bake.darker(110))
        p.drawEllipse(QPointF(cx, cy), radius + 0.5, radius + 0.5)

        # Inner raised cap
        cap_r = radius - 2.0
        cg = QLinearGradient(cx - cap_r, cy - cap_r, cx + cap_r, cy + cap_r)
        cg.setColorAt(0.0, mix(bake, m.mid, 0.3))
        cg.setColorAt(0.5, bake)
        cg.setColorAt(1.0, bake.darker(160))
        p.setPen(QPen(mix(bake, m.mid, 0.6), 0.9))
        p.setBrush(cg)
        p.drawEllipse(QPointF(cx, cy), cap_r, cap_r)

        # Full-radius cream pointer stripe
        self._pointer(p, cx, cy, angle_rad, 1.8, radius - 0.6,
                      mix(tok(look, "text.primary"), tok(look, "status.warn"), 0.25), 2.0)

        if state.readout:
            self._readout(p, w, h, state.readout, tok(look, "readout.text"), True)


class FlatRing(_Knob):
    """Minimalist vector arc around a flat matte cap with a crisp indicator line."""

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        frac = max(0.0, min(1.0, float(state.value)))
        accent = tok(look, "accent")
        cx, cy, radius = self._geometry(w)
        angle_rad = math.radians(_START - frac * _SWEEP)
        self._title(p, w, state.label, tok(look, "text.secondary"))

        arc_r = radius + 2.4
        track = QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)
        p.setPen(QPen(tok(look, "bg.raised"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(track, int(_START * 16), int(-_SWEEP * 16))
        if frac > 0.005:
            p.setPen(QPen(accent, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(track, int(_START * 16), int(-frac * _SWEEP * 16))

        # Flat matte inner cap
        p.setPen(QPen(tok(look, "line.subtle"), 1.0))
        p.setBrush(tok(look, "bg.inset"))
        p.drawEllipse(QPointF(cx, cy), radius - 0.8, radius - 0.8)

        self._pointer(p, cx, cy, angle_rad, 3.0, radius - 2.0, tok(look, "text.primary"), 1.8)

        if state.readout:
            self._readout(p, w, h, state.readout, tok(look, "text.secondary"), False)


registry.register("knob", "machined", Machined, "Machined")
registry.register("knob", "vintage_bakelite", VintageBakelite, "Vintage bakelite")
registry.register("knob", "flat_ring", FlatRing, "Flat ring")
