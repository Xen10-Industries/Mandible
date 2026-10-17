"""Mandible's vector icon set (spec 7.7): path data on a 24-unit grid, one stroke weight.

Every icon is drawn from the shapes below, never from a typed character. ``icon_pixmap``
renders one icon in one colour; ``icon`` builds a ``QIcon`` in the current look's colours (a
normal and a disabled pixmap at several sizes). A ``QIcon`` is a value, so widgets that show
one call ``bind_button_icon`` / ``bind_label_icon``, which re-render it on ``lookChanged``.

Shapes (all coordinates in grid units, 0..24):

* ``("path", cmds, fill)`` - ``M``/``L``/``C``/``Z`` commands as in ``branding``; stroked,
  and filled too when ``fill`` is true
* ``("circle", cx, cy, r, fill)``
* ``("arc", cx, cy, r, start_deg, span_deg)`` - counter-clockwise from 3 o'clock, as Qt
* ``("rect", x, y, w, h, radius, fill)``
* ``("dot", x, y)`` - a filled dot one stroke wide (the point of "?" and "!")
"""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

__all__ = ["ICON_NAMES", "STEP_ICON_NAMES", "GRID", "STROKE", "icon_pixmap", "icon",
           "bind_button_icon", "bind_label_icon", "icon_token"]

ICON_NAMES = ("power", "mic", "monitor", "panic", "settings", "help", "plus", "menu", "up", "down",
              "remove", "map", "open_window", "play", "stop", "record", "hotkey", "chevron_left",
              "chevron_right", "chevron_down")
# Signal-flow steps (header strip in icons mode): mic clean-up, plugin rack, soundboard,
# output limiter and outputs. Same grid and stroke as ICON_NAMES.
STEP_ICON_NAMES = ("filter", "rack", "pads", "limiter", "speaker")

GRID = 24.0
STROKE = 2.0          # grid units: 2 px at 24 px, 1.33 px at 16 px
ICON_SIZES = (16, 20, 24, 32, 40, 48)


def _gear(cx: float, cy: float, r_out: float, r_in: float, teeth: int) -> list:
    """A gear outline: ``teeth`` flat-topped teeth between radii ``r_in`` and ``r_out``."""
    cmds = []
    step = 2 * math.pi / teeth
    half_top, half_root = step * 0.18, step * 0.30
    for i in range(teeth):
        a = i * step - math.pi / 2
        pts = ((r_in, a - half_root), (r_out, a - half_top), (r_out, a + half_top),
               (r_in, a + half_root))
        for j, (r, ang) in enumerate(pts):
            op = "M" if i == 0 and j == 0 else "L"
            cmds.append((op, cx + r * math.cos(ang), cy + r * math.sin(ang)))
    cmds.append(("Z",))
    return cmds


SHAPES: dict[str, tuple] = {
    "power": (("arc", 12, 13, 8, 60, -300),
              ("path", [("M", 12, 3), ("L", 12, 12)], False)),
    "mic": (("rect", 9, 3, 6, 11, 3, False),
            ("arc", 12, 11, 6.5, 180, 180),
            ("path", [("M", 12, 17.5), ("L", 12, 21), ("M", 8.5, 21), ("L", 15.5, 21)], False)),
    "monitor": (("arc", 12, 13, 8.5, 180, -180),
                ("rect", 3.5, 13, 4, 7, 1.5, False),
                ("rect", 16.5, 13, 4, 7, 1.5, False)),
    "panic": (("path", [("M", 12, 3), ("L", 22, 20.5), ("L", 2, 20.5), ("Z",)], False),
              ("path", [("M", 12, 9.5), ("L", 12, 14)], False),
              ("dot", 12, 17.25)),
    "settings": (("path", _gear(12, 12, 9.5, 7, 8), False),
                 ("circle", 12, 12, 3, False)),
    "help": (("circle", 12, 12, 9.5, False),
             ("path", [("M", 9.25, 9.5), ("C", 9.25, 7.75, 10.5, 6.75, 12, 6.75),
                       ("C", 13.6, 6.75, 14.75, 7.8, 14.75, 9.25),
                       ("C", 14.75, 11.25, 12, 11.5, 12, 13.75)], False),
             ("dot", 12, 17.25)),
    "plus": (("path", [("M", 12, 5), ("L", 12, 19), ("M", 5, 12), ("L", 19, 12)], False),),
    "menu": (("path", [("M", 4, 6.5), ("L", 20, 6.5), ("M", 4, 12), ("L", 20, 12),
                       ("M", 4, 17.5), ("L", 20, 17.5)], False),),
    "up": (("path", [("M", 12, 19.5), ("L", 12, 5), ("M", 6, 11), ("L", 12, 5),
                     ("L", 18, 11)], False),),
    "down": (("path", [("M", 12, 4.5), ("L", 12, 19), ("M", 6, 13), ("L", 12, 19),
                       ("L", 18, 13)], False),),
    "remove": (("path", [("M", 6.5, 6.5), ("L", 17.5, 17.5), ("M", 17.5, 6.5),
                         ("L", 6.5, 17.5)], False),),
    # Parameters on knobs: three faders with their caps at different heights.
    "map": (("path", [("M", 6, 4), ("L", 6, 20), ("M", 12, 4), ("L", 12, 20),
                      ("M", 18, 4), ("L", 18, 20)], False),
            ("path", [("M", 3.5, 15), ("L", 8.5, 15), ("M", 9.5, 8), ("L", 14.5, 8),
                      ("M", 15.5, 13), ("L", 20.5, 13)], False)),
    "open_window": (("path", [("M", 19, 13.5), ("L", 19, 19.5), ("L", 4.5, 19.5),
                              ("L", 4.5, 5), ("L", 10.5, 5)], False),
                    ("path", [("M", 11, 13), ("L", 19.5, 4.5), ("M", 14, 4.5), ("L", 19.5, 4.5),
                              ("L", 19.5, 10)], False)),
    "play": (("path", [("M", 7.5, 5), ("L", 19, 12), ("L", 7.5, 19), ("Z",)], True),),
    "stop": (("rect", 6.5, 6.5, 11, 11, 1.5, True),),
    "record": (("circle", 12, 12, 6, True),),
    "hotkey": (("rect", 2.5, 6, 19, 12, 2, False),
               ("dot", 6.5, 10), ("dot", 10, 10), ("dot", 13.5, 10), ("dot", 17.5, 10),
               ("path", [("M", 8, 14.25), ("L", 16, 14.25)], False)),
    "chevron_left": (("path", [("M", 15, 5.5), ("L", 8.5, 12), ("L", 15, 18.5)], False),),
    "chevron_right": (("path", [("M", 9, 5.5), ("L", 15.5, 12), ("L", 9, 18.5)], False),),
    "chevron_down": (("path", [("M", 5.5, 9), ("L", 12, 15.5), ("L", 18.5, 9)], False),),
    # --- signal-flow steps
    "filter": (("path", [("M", 3.5, 5), ("L", 20.5, 5), ("L", 14, 12.5), ("L", 14, 19.5),
                         ("L", 10, 17.5), ("L", 10, 12.5), ("Z",)], False),),
    "rack": (("rect", 3, 4, 18, 6.5, 1.5, False), ("rect", 3, 13.5, 18, 6.5, 1.5, False),
             ("dot", 7, 7.25), ("dot", 7, 16.75)),
    "pads": (("rect", 3.5, 3.5, 7, 7, 1.5, False), ("rect", 13.5, 3.5, 7, 7, 1.5, False),
             ("rect", 3.5, 13.5, 7, 7, 1.5, False), ("rect", 13.5, 13.5, 7, 7, 1.5, True)),
    # A ceiling line with a waveform held under it.
    "limiter": (("path", [("M", 3, 5), ("L", 21, 5)], False),
                ("path", [("M", 3, 14), ("L", 6.5, 9), ("L", 10, 19), ("L", 13.5, 9), ("L", 17, 19),
                          ("L", 21, 12)], False)),
    "speaker": (("path", [("M", 3.5, 9.5), ("L", 7.5, 9.5), ("L", 12.5, 5), ("L", 12.5, 19),
                          ("L", 7.5, 14.5), ("L", 3.5, 14.5), ("Z",)], False),
                ("arc", 13, 12, 4, 50, -100),
                ("arc", 13, 12, 8, 50, -100)),
}


def _path(cmds) -> QPainterPath:
    path = QPainterPath()
    for op, *v in cmds:
        if op == "M":
            path.moveTo(*v)
        elif op == "L":
            path.lineTo(*v)
        elif op == "C":
            path.cubicTo(QPointF(v[0], v[1]), QPointF(v[2], v[3]), QPointF(v[4], v[5]))
        elif op == "Z":
            path.closeSubpath()
    return path


def paint_icon(p: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Draw icon ``name`` scaled into ``rect`` (square) with ``color``."""
    shapes = SHAPES[name]
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.x(), rect.y())
    scale = min(rect.width(), rect.height()) / GRID
    p.scale(scale, scale)
    pen = QPen(color, STROKE, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    for shape in shapes:
        kind = shape[0]
        fill = False
        if kind == "path":
            path = _path(shape[1])
            fill = shape[2]
        elif kind == "circle":
            _, cx, cy, r, fill = shape
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy), r, r)
        elif kind == "rect":
            _, x, y, w, h, radius, fill = shape
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, y, w, h), radius, radius)
        elif kind == "arc":
            _, cx, cy, r, start, span = shape
            box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            path = QPainterPath()
            path.arcMoveTo(box, start)
            path.arcTo(box, start, span)
        elif kind == "dot":
            _, x, y = shape
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(x, y), STROKE * 0.65, STROKE * 0.65)
            continue
        else:  # pragma: no cover - table typo
            raise ValueError(f"unknown icon shape {kind!r} in {name!r}")
        p.setPen(pen)
        p.setBrush(color if fill else Qt.NoBrush)
        p.drawPath(path)
    p.restore()


def _check(name: str) -> None:
    if name not in SHAPES:
        raise KeyError(f"unknown icon {name!r}")


@lru_cache(maxsize=512)
def _pixmap(name: str, color: str, px: int, dpr: float) -> QPixmap:
    dev = max(1, round(px * dpr))
    img = QImage(dev, dev, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint_icon(p, name, QRectF(0, 0, dev, dev), QColor(color))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon_pixmap(name: str, color: str, px: int, dpr: float = 1.0) -> QPixmap:
    """Icon ``name`` as a ``px`` x ``px`` pixmap (logical pixels; ``dpr`` device pixels each)
    drawn in ``color`` (``#rrggbb``) on transparent. KeyError for an unknown name."""
    _check(name)
    return QPixmap(_pixmap(name, str(color), int(px), float(dpr)))


def icon(name: str, token: str = "text.primary") -> QIcon:
    """Icon ``name`` in the current look's ``token`` colour (``text.disabled`` when disabled),
    at the usual sizes. Re-call it (or use ``bind_button_icon``) after the look changes."""
    from .look import current_look

    _check(name)
    pal = current_look().palette
    normal, disabled = pal.color(token), pal.color("text.disabled")
    ic = QIcon()
    for px in ICON_SIZES:
        ic.addPixmap(_pixmap(name, normal, px, 1.0), QIcon.Normal)
        ic.addPixmap(_pixmap(name, disabled, px, 1.0), QIcon.Disabled)
    return ic


# Icon colour per button tier: the tier's text colour.
_TIER_TOKEN = {"primary": "text.on_accent", "secondary": "text.primary",
               "quiet": "text.primary", "danger": "status.danger"}
# Status states (flow steps, toggles) colour the icon like their text.
_STATE_TOKEN = {"on": "status.ok", "warn": "status.warn", "danger": "status.danger"}


def icon_token(tier: str | None, state: str | None = None) -> str:
    """The colour token for an icon on a button of ``tier`` in ``state``."""
    if state in _STATE_TOKEN:
        return _STATE_TOKEN[state]
    return _TIER_TOKEN.get(tier or "secondary", "text.primary")


class _IconBinding(QObject):
    """Re-applies an icon to its parent widget whenever the look changes."""

    def __init__(self, widget, apply):
        super().__init__(widget)
        self._apply = apply
        from .look import look_bus

        look_bus().lookChanged.connect(self.refresh)

    def refresh(self) -> None:
        self._apply()


def _binding(widget, apply) -> None:
    old = getattr(widget, "_icon_binding", None)
    if old is not None:
        old._apply = apply
    else:
        widget._icon_binding = _IconBinding(widget, apply)
    apply()


def bind_button_icon(button, name: str | None, token: str | None = None) -> None:
    """Show icon ``name`` on ``button`` in ``token`` (default: the button's tier colour) and
    keep it in the current look's colours. ``name=None`` removes the icon."""
    if name is not None:
        _check(name)
    button.setProperty("iconName", name or "")

    def apply():
        if name is None:
            button.setIcon(QIcon())
        else:
            button.setIcon(icon(name, token or icon_token(button.property("tier"),
                                                          button.property("state"))))

    _binding(button, apply)


def bind_label_icon(label, name: str, token: str = "text.secondary", px: int = 16) -> None:
    """Show icon ``name`` as ``label``'s pixmap (``px`` logical pixels) in the look's
    ``token`` colour, re-rendered when the look changes."""
    _check(name)
    label.setProperty("iconName", name)

    def apply():
        from .look import current_look

        dpr = label.devicePixelRatioF()
        label.setPixmap(icon_pixmap(name, current_look().palette.color(token), px, dpr))
        label.setMinimumSize(QSize(px, px))

    _binding(label, apply)
