"""Element base class, per-paint state and the small colour helpers variants share.

Every colour an element draws comes from ``look.palette.color(token)``; metal,
glass and wood are derived from those tokens with QColor arithmetic (``mix``,
``lighter``/``darker``, ``alpha``), never from literals.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QPainter

from ..look import Look

__all__ = ["ElementState", "Element", "tok", "mix", "alpha", "metal", "Metal", "wood", "Wood",
           "DISABLED_OPACITY"]

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


# Walnut and bakelite: OKLCH (lightness, chroma) steps at the hue of the fixed-hue
# ``status.warn`` (amber, ~75 degrees), never derived from the accent. Lightness stays at or
# below 0.38, so the warm wood keeps well clear of any accent (a built-in or derived accent
# clears 3:1 on bg.panel, which puts it at OKLCH L >= ~0.55), the Amber palette's included.
_WOOD_STEPS = {"light": (0.37, 0.074), "mid": (0.32, 0.066), "dark": (0.26, 0.055),
               "deep": (0.195, 0.042), "edge": (0.15, 0.03)}
_BAKELITE_STEP = (0.245, 0.045)


@lru_cache(maxsize=16)
def _warm_ramp(warn_hex: str) -> dict[str, str]:
    from ..palette_gen import hex_to_oklch, oklch_to_hex

    hue = hex_to_oklch(warn_hex)[2]
    ramp = {name: oklch_to_hex(l, c, hue) for name, (l, c) in _WOOD_STEPS.items()}
    ramp["bakelite"] = oklch_to_hex(*_BAKELITE_STEP, hue)
    return ramp


class Wood:
    """Walnut ramp (``light`` .. ``edge``) and the ``bakelite`` knob body for the vintage skin."""

    def __init__(self, look: Look) -> None:
        ramp = _warm_ramp(look.palette.color("status.warn"))
        self.light, self.mid, self.dark, self.deep, self.edge, self.bakelite = (
            QColor(ramp[k]) for k in ("light", "mid", "dark", "deep", "edge", "bakelite"))


def wood(look: Look) -> Wood:
    return Wood(look)


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
