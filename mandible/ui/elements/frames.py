"""Chassis frame variants: ``metal_rack``, ``wood_cheeks`` and ``frameless``.

A frame paints the whole window chrome into its rect and reports the layout
margins that leave room for it (``content_margins``).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QLinearGradient, QPainter, QPainterPath, QPen

from ..look import Look
from . import registry
from .base import Element, ElementState, alpha, metal, mix, tok, wood

__all__ = ["MetalRack", "WoodCheeks", "Frameless", "resolve_frame"]


def resolve_frame(look: Look, override: str = "auto") -> str:
    """The frame variant to draw: ``override`` when it names a registered frame,
    otherwise the one the look's skin chose (the old ``"auto"`` setting)."""
    if override in registry.variants("frame"):
        return override
    chosen = look.skin.elements.get("frame", registry.DEFAULTS["frame"])
    return chosen if chosen in registry.variants("frame") else registry.DEFAULTS["frame"]


class MetalRack(Element):
    """19-inch brushed anodized steel rack ears with EIA oval slots; the skin's ``screws``
    element bolts the four corners (spec: the skeuomorphic skin keeps only its corner screws)."""

    EAR_W = 22.0
    RAIL_H = 10.0
    SCREW_PX = 12.0
    CORNER_Y = 24.0   # corner screw centre from the top / bottom edge

    def content_margins(self, look: Look) -> tuple[int, int, int, int]:
        # On the spacing scale (24 / 12), clear of the ears and rails.
        return (24, 12, 24, 12)

    def corner_screws(self, w: float, h: float) -> list[QPointF]:
        """Centres of the four corner screws (one per ear, top and bottom)."""
        xs = (1.0 + self.EAR_W / 2.0, w - 1.0 - self.EAR_W / 2.0)
        ys = (self.CORNER_Y, h - self.CORNER_Y)
        return [QPointF(x, y) for y in ys for x in xs]

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        m = metal(look)
        ear_w, rail_h = self.EAR_W, self.RAIL_H
        win = tok(look, "bg.window")
        body_top = tok(look, "bg.overlay")
        body_mid = tok(look, "bg.panel")

        # Outer dark anodized steel body
        base_grad = QLinearGradient(0, 0, 0, h)
        base_grad.setColorAt(0.0, body_top)
        base_grad.setColorAt(0.5, body_mid)
        base_grad.setColorAt(1.0, win)
        p.setPen(QPen(m.mid, 1.2))
        p.setBrush(base_grad)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 9.0, 9.0)

        # Top and bottom cross-rail extrusions (plain: no bolts)
        for ry in (1.0, h - rail_h - 1.0):
            rg = QLinearGradient(0, ry, 0, ry + rail_h)
            rg.setColorAt(0.0, mix(body_top, m.mid, 0.35))
            rg.setColorAt(0.5, tok(look, "bg.raised"))
            rg.setColorAt(1.0, win)
            p.setPen(QPen(m.black, 1.0))
            p.setBrush(rg)
            p.drawRect(QRectF(ear_w, ry, w - 2 * ear_w, rail_h))

        # Left and right brushed steel rack ears
        for ex in (1.0, w - ear_w - 1.0):
            eg = QLinearGradient(ex, 0, ex + ear_w, 0)
            eg.setColorAt(0.0, mix(body_top, m.mid, 0.55))
            eg.setColorAt(0.25, mix(body_top, m.mid, 0.2))
            eg.setColorAt(0.75, tok(look, "bg.raised"))
            eg.setColorAt(1.0, body_mid)
            p.setPen(QPen(m.black, 1.0))
            p.setBrush(eg)
            p.drawRoundedRect(QRectF(ex, 1.0, ear_w, h - 2.0), 7.0, 7.0)

            # Brushed vertical grain
            p.setPen(QPen(alpha(m.hi, 14), 1.0))
            for gx in range(int(ex + 4), int(ex + ear_w - 3), 3):
                p.drawLine(QPointF(gx, 6.0), QPointF(gx, h - 6.0))

            # EIA mounting slots: the corner ones hold the screws, the inner pair stays empty
            ec_x = ex + ear_w / 2.0
            for sy in (self.CORNER_Y, self.CORNER_Y + 48.0, h - self.CORNER_Y - 48.0,
                       h - self.CORNER_Y):
                if sy < 16.0 or sy > h - 16.0:
                    continue
                p.setPen(QPen(m.black, 1.0))
                p.setBrush(m.black.darker(120))
                p.drawRoundedRect(QRectF(ec_x - 6.5, sy - 4.5, 13.0, 9.0), 4.0, 4.0)

        # Inner recessed faceplate well
        p.setPen(QPen(m.black.darker(120), 1.6))
        p.setBrush(win)
        p.drawRect(QRectF(ear_w, rail_h, w - 2 * ear_w, h - 2 * rail_h))

        # The four corner screws, drawn by the skin's screws element (none: no screws)
        screw = registry.get("screws", registry.resolve(look.skin.elements)[0]["screws"])()
        half = self.SCREW_PX / 2.0
        for c in self.corner_screws(w, h):
            screw.paint(p, QRectF(c.x() - half, c.y() - half, self.SCREW_PX, self.SCREW_PX),
                        ElementState(), look)


class WoodCheeks(Element):
    """Sculpted walnut cheek blocks, valence rail and padded leather armrest bolster; the
    skin's ``screws`` element fixes the four corners (one top and one bottom per cheek)."""

    CHEEK_W = 22.0
    TOP_RAIL_H = 12.0
    BOLSTER_H = 16.0
    SCREW_PX = 12.0
    CORNER_Y = 24.0   # corner screw centre from the top / bottom edge

    def content_margins(self, look: Look) -> tuple[int, int, int, int]:
        # On the spacing scale (24 / 12 / 16), clear of the cheeks, rail and bolster.
        return (24, 12, 24, 16)

    def corner_screws(self, w: float, h: float) -> list[QPointF]:
        """Centres of the four corner screws (one per cheek, top and bottom)."""
        xs = (0.5 + self.CHEEK_W / 2.0, w - 0.5 - self.CHEEK_W / 2.0)
        ys = (self.CORNER_Y, h - self.CORNER_Y)
        return [QPointF(x, y) for y in ys for x in xs]

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        wd = wood(look)
        m = metal(look)
        win = tok(look, "bg.window")
        cheek_w, top_rail_h, bolster_h = self.CHEEK_W, self.TOP_RAIL_H, self.BOLSTER_H

        # Top carved wood valence rail
        top_grad = QLinearGradient(0, 0, 0, top_rail_h)
        top_grad.setColorAt(0.0, wd.mid)
        top_grad.setColorAt(0.5, wd.dark)
        top_grad.setColorAt(1.0, wd.deep)
        p.setPen(QPen(wd.edge, 1.0))
        p.setBrush(top_grad)
        p.drawRect(QRectF(cheek_w - 2.0, 0.5, w - 2 * cheek_w + 4.0, top_rail_h))

        # Inner console well
        p.setPen(QPen(wd.edge.darker(130), 1.6))
        p.setBrush(win)
        p.drawRect(QRectF(cheek_w, top_rail_h, w - 2 * cheek_w, h - top_rail_h - bolster_h))

        # Bottom padded leather armrest bolster
        bol_y = h - bolster_h
        leather = tok(look, "bg.raised")
        bol_grad = QLinearGradient(0, bol_y, 0, h)
        bol_grad.setColorAt(0.0, mix(leather, wd.dark, 0.35))
        bol_grad.setColorAt(0.35, tok(look, "bg.inset"))
        bol_grad.setColorAt(1.0, win.darker(150))
        p.setPen(QPen(m.black, 1.2))
        p.setBrush(bol_grad)
        p.drawRect(QRectF(cheek_w - 2.0, bol_y, w - 2 * cheek_w + 4.0, bolster_h - 0.5))
        # Warm stitch line along the top of the bolster
        p.setPen(QPen(alpha(wd.light.lighter(220), 75), 1.0, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(cheek_w + 8.0, bol_y + 3.0), QPointF(w - cheek_w - 8.0, bol_y + 3.0))

        # Left and right sculpted wood cheek blocks
        for cx_left in (0.5, w - cheek_w - 0.5):
            wg = QLinearGradient(cx_left, 0, cx_left + cheek_w, 0)
            wg.setColorAt(0.0, wd.light)
            wg.setColorAt(0.22, wd.mid)
            wg.setColorAt(0.65, wd.dark)
            wg.setColorAt(1.0, wd.deep)
            p.setPen(QPen(wd.edge, 1.2))
            p.setBrush(wg)
            p.drawRoundedRect(QRectF(cx_left, 0.5, cheek_w, h - 1.0), 6.0, 6.0)

            # Organic vertical grain fibres
            for gi in range(4):
                gx = cx_left + 4.0 + gi * 4.6
                p.setPen(QPen(alpha(wd.edge, 70 if gi % 2 == 0 else 40), 1.1))
                path = QPainterPath(QPointF(gx, 5.0))
                path.cubicTo(
                    QPointF(gx + (1.6 if gi % 2 == 0 else -1.4), h * 0.33),
                    QPointF(gx + (-1.5 if gi % 2 == 0 else 1.5), h * 0.66),
                    QPointF(gx, h - 5.0),
                )
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)

            # Inner chamfered highlight edge
            hl_x = cx_left + cheek_w - 1.5 if cx_left < 10 else cx_left + 1.5
            p.setPen(QPen(alpha(wd.light.lighter(260), 45), 1.0))
            p.drawLine(QPointF(hl_x, 6.0), QPointF(hl_x, h - 6.0))

        # The four corner screws, drawn by the skin's screws element (none: no screws)
        screw = registry.get("screws", registry.resolve(look.skin.elements)[0]["screws"])()
        half = self.SCREW_PX / 2.0
        for c in self.corner_screws(w, h):
            screw.paint(p, QRectF(c.x() - half, c.y() - half, self.SCREW_PX, self.SCREW_PX),
                        ElementState(), look)


class Frameless(Element):
    """No chrome: one flat window panel outlined by a ``line.subtle`` hairline with the skin's
    panel radius. Content sits flush inside it (margins 0), so the header strip is the
    panel's top zone and the console strip its bottom zone. Because that content covers the
    edge, the chassis re-strokes the outline on top of its children (``overlay_outline``);
    a border on the strips themselves would push their content 1 px off the body's edges."""

    overlay_outline = True

    def content_margins(self, look: Look) -> tuple[int, int, int, int]:
        return (0, 0, 0, 0)

    def outline(self, p: QPainter, w: float, h: float, look: Look) -> None:
        """The hairline outline alone (what the chassis overlay paints over the content)."""
        bw = float(look.skin.shape.get("border.width", 1))
        radius = float(look.skin.shape.get("radius.panel", 10))
        p.setPen(QPen(tok(look, "line.subtle"), bw))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(bw / 2.0, bw / 2.0, w - bw, h - bw), radius, radius)

    def draw(self, p: QPainter, w: float, h: float, state: ElementState, look: Look) -> None:
        radius = float(look.skin.shape.get("radius.panel", 10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tok(look, "bg.window"))
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
        self.outline(p, w, h, look)


registry.register("frame", "metal_rack", MetalRack, "Metal rack")
registry.register("frame", "wood_cheeks", WoodCheeks, "Wood cheeks")
registry.register("frame", "frameless", Frameless, "Frameless")
