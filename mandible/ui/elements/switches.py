"""Two-state switch variants: ``bat_toggle``, ``rocker`` and ``pill``.

``state.active`` is "on". Sizes follow ``HardwareSwitch``: 72x24 normally (room for the
11 px IN / BYP label), 50x24 ``compact`` and 46x28 ``vertical`` (the vertical one swings its
lever up/down).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QLinearGradient, QPainter, QPen, QRadialGradient

from ..look import Look, font_px
from . import registry
from .base import Element, ElementState, alpha, metal, mix, tok

__all__ = ["BatToggle", "Rocker", "Pill"]


class _Switch(Element):
    def __init__(self, compact: bool = False, vertical: bool = False) -> None:
        self.compact = bool(compact)
        self.vertical = bool(vertical)

    def size_hint(self, look: Look) -> QSize:
        if self.vertical:
            return QSize(46, 28)
        if self.compact:
            return QSize(50, 24)
        return QSize(72, 24)

    @property
    def _small(self) -> bool:
        return self.compact or self.vertical

    def _jewel(self, p: QPainter, cy: float, state: ElementState, look: Look) -> None:
        """Pilot LED in a chrome bezel at the left of a skeuomorphic switch."""
        m = metal(look)
        led_cx = 9.0 if self._small else 10.0
        led_r = 4.0 if self._small else 4.5
        ok = tok(look, "status.ok")

        p.setPen(QPen(m.mid, 0.8))
        p.setBrush(tok(look, "bg.inset").darker(130))
        p.drawEllipse(QPointF(led_cx, cy), led_r + 1.2, led_r + 1.2)

        if state.active:
            jg = QRadialGradient(QPointF(led_cx - 1.0, cy - 1.0), led_r)
            jg.setColorAt(0.0, tok(look, "text.primary"))
            jg.setColorAt(0.35, ok.lighter(125))
            jg.setColorAt(0.8, ok)
            jg.setColorAt(1.0, ok.darker(220))
            p.setPen(QPen(ok.lighter(150), 0.8))
            p.setBrush(QBrush(jg))
        else:
            p.setPen(QPen(tok(look, "line.subtle"), 0.8))
            p.setBrush(tok(look, "bg.inset"))
        p.drawEllipse(QPointF(led_cx, cy), led_r, led_r)

    def _state_text(self, p: QPainter, x: float, h: float, state: ElementState, look: Look) -> None:
        f = p.font()
        f.setFamily("Consolas")
        f.setPixelSize(font_px("readout"))
        f.setBold(True)
        p.setFont(f)
        p.setPen(tok(look, "status.ok") if state.active else tok(look, "status.danger"))
        p.drawText(QRectF(x, 0, 20, h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "IN" if state.active else "BYP")


class BatToggle(_Switch):
    """3D bat-handle metal toggle with a jewel pilot LED."""

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        m = metal(look)
        cy = h / 2.0
        active = state.active
        self._jewel(p, cy, state, look)

        if self.vertical:
            sw_cx, bush_r = 28.0, 5.8
        else:
            sw_cx = 32.0 if self.compact else 39.0
            bush_r = 5.8 if self.compact else 7.0

        # Chrome bushing
        bg = QLinearGradient(sw_cx - bush_r, cy - bush_r, sw_cx + bush_r, cy + bush_r)
        bg.setColorAt(0.0, m.light)
        bg.setColorAt(0.3, m.mid)
        bg.setColorAt(0.7, mix(m.dark, m.deep, 0.5))
        bg.setColorAt(1.0, m.mid)
        p.setPen(QPen(m.black, 0.9))
        p.setBrush(QBrush(bg))
        p.drawEllipse(QPointF(sw_cx, cy), bush_r, bush_r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(m.black)
        p.drawEllipse(QPointF(sw_cx, cy), bush_r * 0.6, bush_r * 0.6)

        # Lever tip position
        if self.vertical:
            tip_x, tip_y = sw_cx + 1.0, cy + (-8.0 if active else 8.0)
            tip_r, lever_w = 2.0, 2.8
        else:
            span = 7.0 if self.compact else 8.5
            tip_x, tip_y = sw_cx + (span if active else -span), cy - 2.0
            tip_r = 2.0 if self.compact else 2.4
            lever_w = 2.8 if self.compact else 3.2

        # Lever shadow
        p.setPen(QPen(alpha(m.black, 135), lever_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if self.vertical:
            if active:
                p.drawLine(QPointF(sw_cx + 1.2, cy + 1.2), QPointF(tip_x + 2.2, tip_y + 2.2))
            else:
                p.drawLine(QPointF(sw_cx + 1.2, cy + 1.0), QPointF(tip_x + 2.0, tip_y + 1.2))
        else:
            p.drawLine(QPointF(sw_cx, cy + 1.5), QPointF(tip_x, tip_y + 2.5))

        # Lever
        lg = QLinearGradient(sw_cx, cy, tip_x, tip_y)
        if active:
            lg.setColorAt(0.0, m.mid)
            lg.setColorAt(0.5, mix(m.light, m.hi, 0.4))
            lg.setColorAt(1.0, m.hi)
        else:
            lg.setColorAt(0.0, mix(m.dark, m.mid, 0.5))
            lg.setColorAt(0.6, m.mid)
            lg.setColorAt(1.0, m.light)
        lever = QPen()
        lever.setWidthF(lever_w)
        lever.setCapStyle(Qt.PenCapStyle.RoundCap)
        lever.setBrush(QBrush(lg))
        p.setPen(lever)
        p.drawLine(QPointF(sw_cx, cy), QPointF(tip_x, tip_y))

        # Lever knob
        tg = QRadialGradient(QPointF(tip_x - 0.5, tip_y - 0.5), tip_r)
        tg.setColorAt(0.0, m.hi)
        tg.setColorAt(0.5, mix(m.light, m.hi, 0.4) if active else m.light)
        tg.setColorAt(1.0, m.mid if active else mix(m.dark, m.mid, 0.5))
        p.setPen(QPen(m.dark, 0.5))
        p.setBrush(QBrush(tg))
        p.drawEllipse(QPointF(tip_x, tip_y), tip_r, tip_r)

        if not self.vertical and not self.compact:
            self._state_text(p, sw_cx + 12, h, state, look)


class Rocker(_Switch):
    """Studio beveled rocker switch with a jewel pilot LED."""

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        m = metal(look)
        active = state.active
        self._jewel(p, h / 2.0, state, look)

        if self.vertical:
            rw, rh, rx = 16.0, 24.0, 22.0
            ry = (h - rh) / 2.0
            glyph_r = 1.7
        elif self.compact:
            rx, rw, rh = 18.0, 30.0, 16.0
            ry = (h - rh) / 2.0
            glyph_r = 1.8
        else:
            rx, rw, rh = 22.0, 42.0, 18.0
            ry = (h - rh) / 2.0
            glyph_r = 2.2

        housing = QRectF(rx, ry, rw, rh)
        p.setPen(QPen(tok(look, "line.subtle"), 1.0))
        p.setBrush(m.black.darker(110))
        p.drawRoundedRect(housing, 2.5, 2.5)

        pad = housing.adjusted(1.2, 1.2, -1.2, -1.2)
        if self.vertical:
            half = pad.height() / 2.0
            first = QRectF(pad.left(), pad.top(), pad.width(), half)           # top
            second = QRectF(pad.left(), pad.top() + half, pad.width(), half)   # bottom
        else:
            half = pad.width() / 2.0
            first = QRectF(pad.left(), pad.top(), half, pad.height())          # left
            second = QRectF(pad.left() + half, pad.top(), half, pad.height())  # right
        # The lifted pad is the right (horizontal) or top (vertical) one when on, else the other.
        if self.vertical:
            lifted, sunk = (first, second) if active else (second, first)
        else:
            lifted, sunk = (second, first) if active else (first, second)

        face_top = tok(look, "bg.overlay")
        face_bot = tok(look, "bg.raised")
        dark_pad = tok(look, "bg.inset")

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dark_pad)
        p.drawRoundedRect(sunk, 1.5, 1.5)
        if self.vertical:
            rg = QLinearGradient(lifted.left(), lifted.top(), lifted.right(), lifted.bottom())
        else:
            rg = QLinearGradient(lifted.left(), lifted.top(), lifted.left(), lifted.bottom())
        rg.setColorAt(0.0, face_top)
        rg.setColorAt(1.0, face_bot)
        p.setBrush(QBrush(rg))
        p.drawRoundedRect(lifted, 1.5, 1.5)

        # Edge highlight on the lifted pad
        if active:
            p.setPen(QPen(tok(look, "readout.text"), 1.0))
            if self.vertical:
                p.drawLine(QPointF(lifted.left() + 1, lifted.top() + 1),
                           QPointF(lifted.right() - 1, lifted.top() + 1))
            else:
                p.drawLine(QPointF(lifted.left(), lifted.top() + 1),
                           QPointF(lifted.right() - 2, lifted.top() + 1))
        else:
            p.setPen(QPen(m.mid, 1.0))
            if self.vertical:
                p.drawLine(QPointF(lifted.left() + 1, lifted.bottom() - 1),
                           QPointF(lifted.right() - 1, lifted.bottom() - 1))
            else:
                p.drawLine(QPointF(lifted.left() + 2, lifted.top() + 1),
                           QPointF(lifted.right(), lifted.top() + 1))

        # Glyphs: a lit dot on the lifted pad when on; a red ring when off
        if active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tok(look, "status.ok"))
            p.drawEllipse(lifted.center(), glyph_r, glyph_r)
            p.setPen(QPen(m.mid, 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(sunk.center(), glyph_r, glyph_r)
        else:
            p.setPen(QPen(tok(look, "status.danger"), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(lifted.center(), glyph_r, glyph_r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mix(m.dark, m.mid, 0.5))
            p.drawEllipse(sunk.center(), glyph_r, glyph_r)


class Pill(_Switch):
    """Flat sliding pill toggle (the minimal skin's switch)."""

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        active = state.active
        accent = tok(look, "accent")
        pw = 34.0 if self._small else 38.0
        ph = 16.0
        px, py = (w - pw) / 2.0, (h - ph) / 2.0
        p.setPen(QPen(accent if active else tok(look, "line.subtle"), 1.0))
        p.setBrush(accent if active else tok(look, "bg.inset"))
        p.drawRoundedRect(QRectF(px, py, pw, ph), ph / 2.0, ph / 2.0)

        thumb_r = (ph - 4.0) / 2.0
        tx = (px + pw - thumb_r - 2.0) if active else (px + thumb_r + 2.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tok(look, "text.on_accent") if active else tok(look, "line.strong"))
        p.drawEllipse(QPointF(tx, h / 2.0), thumb_r, thumb_r)


registry.register("switch", "bat_toggle", BatToggle, "Bat toggle")
registry.register("switch", "rocker", Rocker, "Rocker")
registry.register("switch", "pill", Pill, "Pill")
