"""Level-meter bar variants: ``led_segments`` and ``smooth_bar``.

An element paints just the bar into its rect (the caller draws channel names,
dB readouts and scales). ``state.value`` is the level 0..1; ``state.peak`` is the
peak-hold position 0..1, or ``None`` to hide the marker. ``state.enabled=False`` is an
inactive row (a bypassed plugin's POST meter): unlit, with no level and no peak.

Every meter variant offers the same three presets, one per meter widget:
``main()`` (channel meter), ``thin()`` (condensed strip) and ``prepost()`` (plugin row).
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

    Defaults are the 26-segment main meter. ``thin()`` and ``prepost()`` reproduce the
    18-segment condensed-strip meter and the 14-segment plugin pre/post meter exactly.
    The peak-hold segment is ``round(peak * segments) + peak_offset`` (the main meter
    used offset 0, the other two -1); an index outside the ladder lights nothing.
    """

    def __init__(self, segments: int = 26, gap: float = 2.0, corner: float = 1.5,
                 warn_at: float = 18 / 26, danger_at: float = 22 / 26,
                 size: tuple[int, int] = (140, 13), peak_offset: int = 0,
                 min_seg_w: float = 1.0) -> None:
        self.segments = int(segments)
        self.peak_offset = int(peak_offset)
        self.min_seg_w = float(min_seg_w)
        self.gap = float(gap)
        self.corner = float(corner)
        self.warn_at = float(warn_at)
        self.danger_at = float(danger_at)
        self._size = size

    @classmethod
    def main(cls) -> "LedSegments":
        """26 segments: the main channel meter."""
        return cls()

    @classmethod
    def thin(cls) -> "LedSegments":
        """18 segments: the 8 px condensed-strip meter."""
        return cls(18, 1.5, 1.2, 12 / 18, 15 / 18, size=(80, 8), peak_offset=-1, min_seg_w=1.5)

    @classmethod
    def prepost(cls) -> "LedSegments":
        """14 segments: one row of the plugin pre/post meter."""
        return cls(14, 1.6, 1.0, 9 / 14, 12 / 14, size=(78, 9), peak_offset=-1, min_seg_w=1.5)

    def peak_segment(self, peak: float | None) -> int | None:
        """Index of the lit peak segment for ``peak`` 0..1 (None if hidden or off the ladder)."""
        if peak is None:
            return None
        idx = int(round(_clamp01(peak) * self.segments)) + self.peak_offset
        return idx if 0 <= idx < self.segments else None

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
        seg_w = max(self.min_seg_w, (w - (n - 1) * self.gap) / n)
        p.setPen(Qt.PenStyle.NoPen)
        if not state.enabled:
            # Inactive row: every segment flat unlit, no zone tint, level or peak.
            p.setBrush(tok(look, "meter.off"))
            for i in range(n):
                p.drawRoundedRect(QRectF(i * (seg_w + self.gap), 0, seg_w, h), self.corner, self.corner)
            return
        active = int(round(_clamp01(state.value) * n))
        peak_seg = self.peak_segment(state.peak)
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
    """Continuous ribbon bar: green (``meter.low``) from the quiet end, amber and red only at
    the loud end. Never the accent, which reads as a warning in red palettes."""

    def __init__(self, corner: float = 2.5, size: tuple[int, int] = (140, 13)) -> None:
        self.corner = float(corner)
        self._size = size

    @classmethod
    def main(cls) -> "SmoothBar":
        """The main channel meter's 13 px bar."""
        return cls()

    @classmethod
    def thin(cls) -> "SmoothBar":
        """The 8 px condensed-strip bar."""
        return cls(2.5, size=(80, 8))

    @classmethod
    def prepost(cls) -> "SmoothBar":
        """One 7 px row of the plugin pre/post meter."""
        return cls(2.0, size=(78, 7))

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        corner = self.corner
        frac = _clamp01(state.value) if state.enabled else 0.0
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
            grad.setColorAt(0.0, tok(look, "meter.low"))
            grad.setColorAt(0.7, tok(look, "meter.low"))
            grad.setColorAt(0.85, tok(look, "meter.mid"))
            grad.setColorAt(1.0, tok(look, "meter.high"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(
                QRectF(inset, inset, max(2.0, w * frac - 2.0 * inset), h - 2.0 * inset),
                max(1.0, corner - inset), max(1.0, corner - inset))

        if state.peak is not None and state.enabled:
            px = min(w - 2.0, max(inset, w * _clamp01(state.peak)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tok(look, "text.primary"))
            p.drawRect(QRectF(px, inset, 2.0, h - 2.0 * inset))

    def size_hint(self, look: Look) -> QSize:
        return QSize(*self._size)


registry.register("meter", "led_segments", LedSegments, "LED segments")
registry.register("meter", "smooth_bar", SmoothBar, "Smooth bar")
