"""Element base class, per-paint state and the small colour helpers variants share.

Every colour an element draws comes from ``look.palette.color(token)``; metal,
glass and wood are derived from those tokens with QColor arithmetic (``mix``,
``lighter``/``darker``, ``alpha``), never from literals.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QPainter

from ..look import Look

__all__ = ["ElementState", "Element", "tok", "mix", "alpha", "metal", "Metal", "DISABLED_OPACITY"]

DISABLED_OPACITY = 0.4


@dataclass
class ElementState:
    """What an element needs to know to paint one frame.

    ``value`` is normalized 0..1 (knob position, meter level; a switch is on when
    ``active``). ``peak`` (0..1, ``None`` = no peak marker), ``label`` and
    ``readout`` carry the extra values the old widgets drew with their dial or bar:
    a knob's title and value text, a meter's peak-hold marker. For a panel,
    ``active=True`` selects the recessed (inset) surface instead of the raised one.
    """

    enabled: bool = True
    active: bool = False
    hovered: bool = False
    pressed: bool = False
    value: float = 0.0
    peak: float | None = None
    label: str = ""
    readout: str = ""


def tok(look: Look, token: str) -> QColor:
    """The palette colour for ``token`` as a QColor."""
    return QColor(look.palette.color(token))


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend: ``t=0`` is ``a``, ``t=1`` is ``b`` (alpha included)."""
    t = max(0.0, min(1.0, t))
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
        a.alphaF() + (b.alphaF() - a.alphaF()) * t,
    )


def alpha(color: QColor, a: int) -> QColor:
    """``color`` with alpha ``a`` (0..255)."""
    c = QColor(color)
    c.setAlpha(a)
    return c


class Metal:
    """A five-step steel ramp derived from the palette (highlight .. deep shadow)."""

    def __init__(self, look: Look) -> None:
        self.hi = tok(look, "text.primary")
        self.light = tok(look, "text.secondary")
        self.mid = tok(look, "line.strong")
        self.dark = mix(self.mid, tok(look, "bg.inset"), 0.6)
        self.deep = tok(look, "bg.inset")
        self.black = tok(look, "bg.window").darker(300)


def metal(look: Look) -> Metal:
    return Metal(look)


class Element:
    """One painted variant. Subclasses override ``draw`` (drawn in a 0,0,w,h box)."""

    def paint(self, p: QPainter, rect: QRectF, state: ElementState, look: Look) -> None:
        """Draw into ``rect``; leaves the painter's state as it found it."""
        p.save()
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.translate(rect.topLeft())
            if not state.enabled:
                p.setOpacity(p.opacity() * DISABLED_OPACITY)
            self.draw(p, rect.width(), rect.height(), state, look)
        finally:
            p.restore()

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        """Paint a ``w`` x ``h`` element at the painter origin."""

    def size_hint(self, look: Look) -> QSize:
        """The natural size of the element (today's widget size)."""
        return QSize(0, 0)
