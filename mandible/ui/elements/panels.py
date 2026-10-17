"""Panel surface variants: how raised and inset surfaces are shaded.

``brushed`` and ``lacquer`` keep the stylesheet's vertical card gradient (the
"raised" surface of the non-flat skins) and add their material cue; ``flat``
drops gradients for one surface colour. ``state.active`` selects the recessed
(inset) surface, which is a single colour in every variant.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QLinearGradient, QPainter, QPen

from ..look import Look
from . import registry
from .base import Element, ElementState, alpha, tok

__all__ = ["Brushed", "Lacquer", "Flat"]


class _Panel(Element):
    def raised_brush(self, look: Look, h: float):
        """Brush for the raised surface (``h`` is the panel height)."""
        raise NotImplementedError

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        bw = float(look.skin.shape.get("border.width", 1))
        radius = float(look.skin.shape.get("radius.panel", 6))
        body = QRectF(bw / 2.0, bw / 2.0, w - bw, h - bw)
        p.setPen(QPen(tok(look, "line.subtle"), bw))
        p.setBrush(tok(look, "bg.inset") if state.active else self.raised_brush(look, h))
        p.drawRoundedRect(body, radius, radius)
        if not state.active:
            self.finish(p, body, radius, look)

    def finish(self, p: QPainter, body: QRectF, radius: float, look: Look) -> None:
        """Material cue drawn over the raised body."""

    def size_hint(self, look: Look) -> QSize:
        return QSize(0, 0)


def _card_gradient(look: Look, h: float) -> QLinearGradient:
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0.0, tok(look, "bg.raised"))
    g.setColorAt(1.0, tok(look, "bg.panel"))
    return g


class Brushed(_Panel):
    """Card gradient with faint vertical brushed-metal grain."""

    def raised_brush(self, look: Look, h: float):
        return _card_gradient(look, h)

    def finish(self, p: QPainter, body: QRectF, radius: float, look: Look) -> None:
        p.setPen(QPen(alpha(tok(look, "text.primary"), 12), 1.0))
        top, bottom = body.top() + radius, body.bottom() - radius
        for gx in range(int(body.left() + radius), int(body.right() - radius), 3):
            p.drawLine(QPointF(gx, top), QPointF(gx, bottom))


class Lacquer(_Panel):
    """The stylesheet's lacquer surface: a thin glossy band (``bg.overlay``) on top, a deeper
    finish (``bg.inset``) at the bottom, and a highlight along the top edge."""

    def raised_brush(self, look: Look, h: float):
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, tok(look, "bg.overlay"))
        g.setColorAt(0.08, tok(look, "bg.raised"))
        g.setColorAt(0.6, tok(look, "bg.panel"))
        g.setColorAt(1.0, tok(look, "bg.inset"))
        return g

    def finish(self, p: QPainter, body: QRectF, radius: float, look: Look) -> None:
        p.setPen(QPen(alpha(tok(look, "text.primary"), 38), 1.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        y = body.top() + 1.5
        p.drawLine(QPointF(body.left() + radius, y), QPointF(body.right() - radius, y))


class Flat(_Panel):
    """One flat surface colour, no gradient and no material cue."""

    def raised_brush(self, look: Look, h: float):
        return tok(look, "bg.raised")


registry.register("panel", "brushed", Brushed, "Brushed metal")
registry.register("panel", "lacquer", Lacquer, "Lacquer")
registry.register("panel", "flat", Flat, "Flat")
