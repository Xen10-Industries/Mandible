"""Level-meter bar variants: ``led_segments`` and ``smooth_bar``.

An element paints just the bar into its rect (the caller draws channel names,
dB readouts and scales). ``state.value`` is the level 0..1; ``state.peak`` is the
peak-hold position 0..1, or ``None`` to hide the marker.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QLinearGradient, QPainter, QPen

from ..look import Look
from . import registry
from .base import Element, ElementState, mix, tok

__all__ = ["LedSegments", "SmoothBar"]


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


class LedSegments(Element):
    """Segmented LED ladder: green, then amber from ``warn_at``, red from ``danger_at``.

    Defaults are the 26-segment main meter; the 18-segment thin meter used
    ``(18, 1.5, 1.2, 12/18, 15/18)`` and the 14-segment plugin pre/post meter
    ``(14, 1.6, 1.0, 9/14, 12/14)``.
    """

    def __init__(self, segments: int = 26, gap: float = 2.0, corner: float = 1.5,
                 warn_at: float = 18 / 26, danger_at: float = 22 / 26,
                 size: tuple[int, int] = (140, 13)) -> None:
        self.segments = int(segments)
        self.gap = float(gap)
        self.corner = float(corner)
        self.warn_at = float(warn_at)
        self.danger_at = float(danger_at)
        self._size = size

    def _zone(self, look: Look, i: int):
        frac = i / self.segments
        if frac < self.warn_at - 1e-9:
            on = tok(look, "meter.low")
        elif frac < self.danger_at - 1e-9:
            on = tok(look, "meter.mid")
        else:
            on = tok(look, "meter.high")
        # Unlit segments keep a dim tint of their zone colour.
        return on, mix(tok(look, "meter.off"), on, 0.12)

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        n = self.segments
        seg_w = max(1.0, (w - (n - 1) * self.gap) / n)
        active = int(round(_clamp01(state.value) * n))
        peak_seg = None
        if state.peak is not None:
            peak_seg = min(n - 1, max(0, int(round(_clamp01(state.peak) * n)) - 1))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            on, off = self._zone(look, i)
            if i == peak_seg:
                p.setBrush(tok(look, "text.primary"))
            elif i < active:
                p.setBrush(on)
            else:
                p.setBrush(off)
            p.drawRoundedRect(QRectF(i * (seg_w + self.gap), 0, seg_w, h), self.corner, self.corner)

    def size_hint(self, look: Look) -> QSize:
        return QSize(*self._size)


class SmoothBar(Element):
    """Continuous ribbon bar: accent into green, amber and red at the loud end."""

    def __init__(self, corner: float = 2.5, size: tuple[int, int] = (140, 13)) -> None:
        self.corner = float(corner)
        self._size = size

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        corner = self.corner
        frac = _clamp01(state.value)
        track = QRectF(0, 0, w, h)
        if h >= 12.0:
            p.setPen(QPen(tok(look, "line.subtle"), 1.0))
            inset = 1.0
        else:
            p.setPen(Qt.PenStyle.NoPen)
            inset = 0.0
        p.setBrush(tok(look, "bg.inset"))
        p.drawRoundedRect(track, corner, corner)

        if frac > 0.01:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, tok(look, "accent"))
            grad.setColorAt(0.75, tok(look, "meter.low"))
            grad.setColorAt(0.9, tok(look, "meter.mid"))
            grad.setColorAt(1.0, tok(look, "meter.high"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(
                QRectF(inset, inset, max(2.0, w * frac - 2.0 * inset), h - 2.0 * inset),
                max(1.0, corner - inset), max(1.0, corner - inset))

        if state.peak is not None:
            px = min(w - 2.0, max(inset, w * _clamp01(state.peak)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tok(look, "text.primary"))
            p.drawRect(QRectF(px, inset, 2.0, h - 2.0 * inset))

    def size_hint(self, look: Look) -> QSize:
        return QSize(*self._size)


registry.register("meter", "led_segments", LedSegments, "LED segments")
registry.register("meter", "smooth_bar", SmoothBar, "Smooth bar")
