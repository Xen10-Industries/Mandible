"""Mandible's mark (the "Tapered Jaw M") and every icon rendered from it.

This module is the single source of the logo geometry. The app/window icon, the tray icon and
the files in assets/icon/ plus Mandible.ico (written by tools/make_icons.py) all come from here.

Geometry is on a 64x64 grid. MARK is the master outline; MARK_SMALL is the hand-adjusted version
used at 24 px and below, with heavier legs and a deeper centre V so the shape survives a tray.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap

GRAPHITE = "#17181B"   # app tile
OFF_WHITE = "#F2F2EF"  # mark on the tile / tray on a dark taskbar
INK = "#17181B"        # tray on a light taskbar

MARK = [
    ("M", 8, 10), ("L", 8, 38), ("C", 8, 47, 13, 54, 24, 56), ("C", 17, 51, 15, 45, 15, 38),
    ("L", 15, 24), ("L", 32, 45), ("L", 49, 24), ("L", 49, 38), ("C", 49, 45, 47, 51, 40, 56),
    ("C", 51, 54, 56, 47, 56, 38), ("L", 56, 10), ("L", 32, 35), ("Z",),
]
MARK_SMALL = [
    ("M", 7, 9), ("L", 7, 38), ("C", 7, 48, 12, 55, 24, 57), ("C", 18, 52, 16, 46, 16, 38),
    ("L", 16, 26), ("L", 32, 46), ("L", 48, 26), ("L", 48, 38), ("C", 48, 46, 46, 52, 40, 57),
    ("C", 52, 55, 57, 48, 57, 38), ("L", 57, 9), ("L", 32, 34), ("Z",),
]
MARK_LEG, MARK_SMALL_LEG = 7, 9   # leg width in grid units (x 8-15 and 7-16)
SMALL_MAX_PX = 24       # sizes at or below this use MARK_SMALL
TILE_RADIUS = 14 / 64   # corner radius as a fraction of the tile
TILE_GLYPH = 0.70       # glyph width as a fraction of the tile (large sizes)
TILE_GLYPH_SMALL = 0.80 # small sizes give the glyph more of the tile

APP_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
TRAY_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64)


def outline(px: int) -> list:
    return MARK_SMALL if px <= SMALL_MAX_PX else MARK


def to_painter_path(cmds: list) -> QPainterPath:
    path = QPainterPath()
    for c in cmds:
        op, *v = c
        if op == "M":
            path.moveTo(*v)
        elif op == "L":
            path.lineTo(*v)
        elif op == "C":
            path.cubicTo(QPointF(v[0], v[1]), QPointF(v[2], v[3]), QPointF(v[4], v[5]))
        elif op == "Z":
            path.closeSubpath()
    return path


def to_svg_d(cmds: list) -> str:
    return " ".join(op + " " + " ".join(f"{n:g}" for n in v) if v else op for op, *v in cmds)


def _glyph_transform(cmds: list, box: QRectF, width_frac: float, snap_px: bool) -> tuple[float, float, float]:
    """Scale and offset that fit the glyph's width to width_frac of box, centred.

    With snap_px, the scale is chosen so the legs are a whole number of pixels wide and their
    outer edges land on pixel boundaries (manual hinting for 16-24 px)."""
    bb = to_painter_path(cmds).boundingRect()
    s = box.width() * width_frac / bb.width()
    if snap_px:
        leg = MARK_SMALL_LEG if cmds is MARK_SMALL else MARK_LEG
        s = max(2, round(leg * s)) / leg
    ox = box.center().x() - bb.center().x() * s
    oy = box.center().y() - bb.center().y() * s
    if snap_px:
        ox = round(ox + bb.left() * s) - bb.left() * s
        oy = round(oy + bb.top() * s) - bb.top() * s
    return s, ox, oy


def _paint_glyph(p: QPainter, cmds: list, s: float, ox: float, oy: float, color: str) -> None:
    p.save()
    p.translate(ox, oy)
    p.scale(s, s)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(to_painter_path(cmds))
    p.restore()


def _new_image(px: int) -> QImage:
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


def render_tile(px: int, glyph_color: str = OFF_WHITE, tile_color: str = GRAPHITE) -> QImage:
    """The app icon: the mark on a rounded graphite tile."""
    img = _new_image(px)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(tile_color))
    r = px * TILE_RADIUS
    p.drawRoundedRect(QRectF(0, 0, px, px), r, r)
    small = px <= SMALL_MAX_PX
    cmds = outline(px)
    s, ox, oy = _glyph_transform(cmds, QRectF(0, 0, px, px), TILE_GLYPH_SMALL if small else TILE_GLYPH, small)
    _paint_glyph(p, cmds, s, ox, oy, glyph_color)
    p.end()
    return img


def render_mark(px: int, color: str) -> QImage:
    """The bare mark (no tile), filling most of the square. Used for the tray."""
    img = _new_image(px)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    small = px <= SMALL_MAX_PX
    cmds = outline(px)
    s, ox, oy = _glyph_transform(cmds, QRectF(0, 0, px, px), 0.94, small)
    _paint_glyph(p, cmds, s, ox, oy, color)
    p.end()
    return img


def taskbar_is_light() -> bool:
    """True when Windows draws a light taskbar (tray icons should then be dark)."""
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except (OSError, ImportError):
        return False


_icon_cache: dict = {}


def app_icon() -> QIcon:
    """Window/taskbar icon: the graphite tile at every standard size."""
    if "app" not in _icon_cache:
        ico = QIcon()
        for px in APP_ICON_SIZES:
            ico.addPixmap(QPixmap.fromImage(render_tile(px)))
        _icon_cache["app"] = ico
    return _icon_cache["app"]


def tray_color(active: bool) -> str:
    """Tray mark colour: the current look's accent when active, else matching the taskbar."""
    if active:
        from .ui.look import current_look

        return current_look().palette.color("accent")
    return INK if taskbar_is_light() else OFF_WHITE


def tray_icon(active: bool, accent: str | None = None) -> QIcon:
    """Tray icon: the bare mark, matching the taskbar when idle and in the look's accent
    (or ``accent``, when given) when active."""
    color = (accent or tray_color(True)) if active else tray_color(False)
    key = ("tray", color)
    if key not in _icon_cache:
        ico = QIcon()
        for px in TRAY_ICON_SIZES:
            ico.addPixmap(QPixmap.fromImage(render_mark(px, color)))
        _icon_cache[key] = ico
    return _icon_cache[key]
