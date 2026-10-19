"""The Customize panel (spec 7.4): swap a skin's elements, edit its colours, save and share it.

A non-modal dock on the main window, so the real window is the live preview. What it edits is the
current Look: Elements change the skin, Colours the palette. Built-in skins and themes are never
overwritten: *Save* writes back only to user items, *Save as new* always makes a user skin (and a
user theme too when the colours changed). Unsaved changes are guarded by an inline banner (Save /
Discard / Keep editing), never an OS dialog. Nothing here touches the audio engine.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QColorDialog, QDockWidget, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QSizePolicy, QToolTip, QVBoxLayout, QWidget)

from .. import user_looks
from ..elements import registry
from ..elements.base import ElementState, tok
from ..look import (SKIN_SLOTS, Look, Palette, Skin, current_look, font_px, look_bus,
                    look_from_config, set_look, space, with_elements)
from ..palette_gen import CONTRAST_PAIRS, PALETTE_TOKENS, TINTS, contrast_ratio, derive_colors
from ..widgets.base import SpacedLayouts, _follow_look, set_style_property
from ..widgets.buttons import make_button, set_tier
from .parts import hint_label

__all__ = ["CustomizePanel", "VariantTile", "ColorSwatch", "TextLine", "TokenList", "render_thumbnail",
           "LIVE_EDIT_MS", "MIN_WIDTH", "DEFAULT_WIDTH", "ADJUSTED_TEXT"]

LIVE_EDIT_MS = 40          # live picker edits apply at most once per tick (R7)
MIN_WIDTH = 320            # the dock's narrowest width (content may ask for more)
DEFAULT_WIDTH = 380
THUMB_W, THUMB_H = 84, 44  # element thumbnails (logical px)
THUMB_CACHE = 240          # thumbnails kept: twelve looks' worth of the twenty tiles
ADJUSTED_TEXT = "Adjusted for readability"
DEFAULT_SKIN, DEFAULT_THEME = "skeuomorphic", "scarlet"
SLOT_TITLES = {"frame": "Frame", "switch": "Switches", "knob": "Knobs", "meter": "Meters",
               "panel": "Panels", "screws": "Screws", "density": "Density"}
TINT_CHIPS = (("neutral", "Neutral"), ("warm", "Warm"), ("cool", "Cool"))
_PAIRS: dict[str, list[tuple[str, float]]] = {}
for _token, _partner, _target in CONTRAST_PAIRS:
    _PAIRS.setdefault(_token, []).append((_partner, _target))


def _is_user(look_id: str) -> bool:
    return isinstance(look_id, str) and look_id.startswith("user:")


def _owner(look_id: str) -> str:
    return "your" if _is_user(look_id) else "built-in"


def _valid_hex(value: str) -> str | None:
    text = (value or "").strip().lower()
    if len(text) == 7 and text[0] == "#" and all(c in "0123456789abcdef" for c in text[1:]):
        return text
    return None


# ------------------------------------------------------------------ thumbnails

def render_thumbnail(slot: str, variant: str, look: Look, w: int = THUMB_W, h: int = THUMB_H,
                     dpr: float = 1.0) -> QPixmap:
    """A ``w`` x ``h`` picture of ``variant`` of ``slot`` painted in ``look`` (whose skin is
    taken as it is, with ``slot`` set to ``variant``). Every colour comes from the look's tokens."""
    pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_thumbnail(p, slot, variant, with_elements(look, **{slot: variant}), float(w), float(h))
    finally:
        p.end()
    return pm


def _ground(p: QPainter, look: Look, rect: QRectF, token: str = "bg.panel") -> None:
    radius = float(look.skin.shape.get("radius.control", 4))
    p.setPen(QPen(tok(look, "line.subtle"), 1.0))
    p.setBrush(tok(look, token))
    p.drawRoundedRect(rect, radius, radius)


def _paint_thumbnail(p: QPainter, slot: str, variant: str, look: Look, w: float, h: float) -> None:
    cls = registry.get(slot, variant)
    if slot == "frame":
        # Drawn at twice the size and scaled down, so the ears and rails keep their proportions.
        p.save()
        p.scale(0.5, 0.5)
        cls().paint(p, QRectF(0, 0, w * 2, h * 2), ElementState(), look)
        p.restore()
    elif slot == "switch":
        el = cls()
        hint = el.size_hint(look)
        s = min(1.0, (w - 8) / max(1, hint.width()), (h - 8) / max(1, hint.height()))
        sw, sh = hint.width() * s, hint.height() * s
        p.save()
        p.translate((w - sw) / 2, (h - sh) / 2)
        p.scale(s, s)
        el.paint(p, QRectF(0, 0, hint.width(), hint.height()), ElementState(active=True), look)
        p.restore()
    elif slot == "knob":
        from ..elements.knobs import KNOB_SIZE, TITLE_H

        kw, kh = KNOB_SIZE
        dial_y = TITLE_H + 16.0           # the dial centre inside the knob's box
        cls().paint(p, QRectF((w - kw) / 2, h / 2 - dial_y, kw, kh), ElementState(value=0.65), look)
    elif slot == "meter":
        el = cls.prepost() if hasattr(cls, "prepost") else cls()
        _ground(p, look, QRectF(2, h / 2 - 11, w - 4, 22), "bg.inset")
        el.paint(p, QRectF(8, h / 2 - 5, w - 16, 10), ElementState(value=0.72, peak=0.86), look)
    elif slot == "panel":
        cls().paint(p, QRectF(6, 4, w - 12, h - 8), ElementState(), look)
    elif slot == "screws":
        _ground(p, look, QRectF(6, 4, w - 12, h - 8), "bg.raised")
        el, px = cls(), 10.0
        for x in (8.0, w - 8.0 - px):
            for y in (6.0, h - 6.0 - px):
                el.paint(p, QRectF(x, y, px, px), ElementState(), look)
    elif slot == "density":
        gap = 4.0 if variant == "compact" else 8.0
        _ground(p, look, QRectF(6, 4, w - 12, h - 8), "bg.raised")
        bar_h = (h - 8 - 2 * gap - 2 * gap) / 3.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tok(look, "line.strong"))
        y = 4 + gap
        for frac in (0.8, 0.55, 0.7):
            p.drawRoundedRect(QRectF(6 + gap, y, (w - 12 - 2 * gap) * frac, bar_h), 1.5, 1.5)
            y += bar_h + gap


# ------------------------------------------------------------------ small widgets

def fit_hex_edit(edit: QLineEdit) -> None:
    """Size a hex field to exactly seven characters of its (monospace) font plus whatever the
    style adds around the text: frame, stylesheet padding and border."""
    from PySide6.QtWidgets import QStyle, QStyleOptionFrame

    edit.ensurePolished()
    fm = edit.fontMetrics()
    opt = QStyleOptionFrame()
    edit.initStyleOption(opt)
    margins = edit.textMargins()
    # a seven-character sample (any letters: every glyph of the monospace font is as wide)
    inner = QSize(fm.horizontalAdvance("#mmmmmm") + margins.left() + margins.right() + 4,
                  fm.height())
    edit.setFixedWidth(edit.style().sizeFromContents(QStyle.CT_LineEdit, opt, inner, edit).width())


class VariantTile(QAbstractButton):
    """One element variant: its thumbnail over its name. Checked = the variant in use."""

    PAD = 4

    def __init__(self, panel: "CustomizePanel", slot: str, variant: str, label: str):
        super().__init__()
        self._panel = panel
        self.slot, self.variant = slot, variant
        self.setObjectName("variantTile")
        self.setText(label)
        self.setToolTip(label)
        self.setAccessibleName(f"{SLOT_TITLES.get(slot, slot)}: {label}")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_Hover, True)

    def _label_font(self):
        f = self.font()
        f.setPixelSize(font_px("small"))
        return f

    def _label_h(self) -> int:
        from PySide6.QtGui import QFontMetrics

        return QFontMetrics(self._label_font()).height()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(THUMB_W + 2 * self.PAD, THUMB_H + self._label_h() + 3 * self.PAD)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(64, self.sizeHint().height())

    def paintEvent(self, _ev) -> None:  # noqa: N802
        look = current_look()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = float(look.skin.shape.get("radius.control", 4))
        body = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        checked, hover = self.isChecked(), self.underMouse()
        if checked:
            fill, edge, width = tok(look, "accent.subtle"), tok(look, "accent"), 2.0
        else:
            fill = tok(look, "bg.raised") if hover else tok(look, "bg.inset")
            edge, width = tok(look, "line.strong" if hover else "line.subtle"), 1.0
        if self.hasFocus():
            edge, width = tok(look, "focus.ring"), 2.0
        p.setPen(QPen(edge, width))
        p.setBrush(fill)
        p.drawRoundedRect(body, radius, radius)

        dpr = self.devicePixelRatioF()
        pm = self._panel.thumbnail(self.slot, self.variant, dpr)
        avail = QRectF(self.PAD, self.PAD, self.width() - 2 * self.PAD, THUMB_H)
        s = min(1.0, avail.width() / THUMB_W)
        tw, th = THUMB_W * s, THUMB_H * s
        p.drawPixmap(QRectF(avail.x() + (avail.width() - tw) / 2, avail.y() + (avail.height() - th) / 2,
                            tw, th), pm, QRectF(0, 0, pm.width(), pm.height()))

        p.setFont(self._label_font())
        p.setPen(tok(look, "text.primary" if checked else "text.secondary"))
        text_rect = QRectF(self.PAD, self.PAD * 2 + THUMB_H, self.width() - 2 * self.PAD, self._label_h())
        shown = p.fontMetrics().elidedText(self.text(), Qt.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, shown)
        p.end()


class ColorSwatch(QAbstractButton):
    """A clickable colour chip (opens a picker). Paints the colour it holds, never a literal."""

    SIZE = 22

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._color = QColor()
        self.setObjectName("colorSwatch")
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    def set_color(self, hex_: str) -> None:
        color = QColor(hex_)
        if color != self._color:
            self._color = color
            self.update()

    def color(self) -> QColor:
        return QColor(self._color)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.SIZE, self.SIZE)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        look = current_look()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        edge = tok(look, "focus.ring" if self.hasFocus() else "line.strong")
        p.setPen(QPen(edge, 2.0 if self.hasFocus() else 1.0))
        p.setBrush(self._color)
        radius = min(4.0, float(look.skin.shape.get("radius.control", 4)))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), radius, radius)
        p.end()


class TextLine(QWidget):
    """A one-line painted label (the panel's title, section and field captions).

    The panel stays cheap to restyle: every QLabel is matched against all of the stylesheet's
    ``QLabel#...`` rules on each look switch, while a plain QWidget subclass meets only a few.
    The text elides to the width it gets (full text in the tooltip) and paints in palette tokens.
    """

    # role -> (type role, weight, token, uppercase with letter spacing, top padding step)
    ROLES = {"title": ("title", 700, "text.primary", False, 0),
             "group": ("small", 800, "text.secondary", True, 3),
             "slot": ("small", 600, "text.secondary", False, 0),
             "notice": ("small", 600, "status.warn", False, 0)}

    def __init__(self, text: str, role: str = "slot", parent=None, first: bool = False):
        super().__init__(parent)
        self._text = text
        self._role = role
        self._first = first            # a group label at the very top gets no top padding
        self.setAccessibleName(text)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        if text != self._text:
            self._text = text
            self.setAccessibleName(text)
            self.updateGeometry()
            self.update()

    def _spec(self):
        return self.ROLES[self._role]

    def _font(self):
        size, weight, _token, upper, _pad = self._spec()
        f = self.font()
        f.setFamily("Segoe UI")
        f.setPixelSize(font_px(size))
        f.setWeight(QFont.Weight(weight))
        if upper:
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        return f

    def _shown(self) -> str:
        return self._text.upper() if self._spec()[3] else self._text

    def _top(self) -> int:
        step = self._spec()[4]
        return 0 if (self._first or not step) else space(step)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self._font())
        return QSize(fm.horizontalAdvance(self._shown()) + 2, fm.height() + self._top())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self._font())
        shown = self._shown()
        short = shown[:6] + "…" if len(shown) > 6 else shown
        return QSize(min(fm.horizontalAdvance(short), fm.horizontalAdvance(shown)) + 2,
                     fm.height() + self._top())

    def refresh(self) -> None:
        """The look changed: the density may move the top padding."""
        self.updateGeometry()
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setFont(self._font())
        p.setPen(tok(current_look(), self._spec()[2]))
        rect = QRectF(0, self._top(), self.width(), self.height() - self._top())
        shown = self._shown()
        elided = p.fontMetrics().elidedText(shown, Qt.ElideRight, max(0, self.width() - 1))
        tip = self._text if elided != shown else ""
        if self.toolTip() != tip:
            self.setToolTip(tip)
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, elided)
        p.end()


class TokenRowView:
    """What Advanced mode shows for one token (a row of ``TokenList``; not a widget)."""

    def __init__(self, token_list: "TokenList", token: str):
        self._list = token_list
        self.token = token
        self.hex = ""
        self.ratio = "—"
        self.warning = ""
        self.tip = ""

    def hex_text(self) -> str:
        return self.hex

    def ratio_text(self) -> str:
        return self.ratio

    def has_warning(self) -> bool:
        return bool(self.warning)

    def isVisible(self) -> bool:  # noqa: N802 - mirrors QWidget
        return self._list.isVisible()


class TokenList(QWidget):
    """Advanced mode: every palette token in one painted widget, one row each: swatch, token name,
    hex value, contrast ratio against its partner surface (the worst of its CONTRAST_PAIRS, "—"
    when it has none) and a "Low" badge below target.

    Two widgets in all (the list and one shared hex editor shown over the row being edited):
    every live widget is re-polished by each look switch. Keyboard: Up / Down pick a row, Enter
    or F2 edits its hex value, Space opens the colour picker; the mouse does the same on the hex
    field and the swatch."""

    SWATCH = 20
    BADGE_TEXT = "Low"
    RATIO_SAMPLE = "21.0:1"
    HEX_SAMPLE = "#mmmmmm"   # seven characters of the monospace font (any letters, same width)

    def __init__(self, panel: "CustomizePanel"):
        super().__init__()
        self._panel = panel
        self.setObjectName("tokenList")
        self.setAccessibleName("Colour tokens")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.rows: dict[str, TokenRowView] = {t: TokenRowView(self, t) for t in PALETTE_TOKENS}
        self._order = list(PALETTE_TOKENS)
        self._current = 0
        self._metrics: tuple | None = None
        self.editor = QLineEdit(self)
        self.editor.setObjectName("hexEdit")
        self.editor.setMaxLength(7)
        self.editor.hide()
        self.editor.editingFinished.connect(self._commit)
        self.editor.installEventFilter(self)
        self._editing: str | None = None

    # -------------------------------------------------------------- geometry
    def _font(self, mono: bool = True, bold: bool = False):
        f = self.font()
        if mono:
            f.setFamilies(["Consolas", "Cascadia Mono"])
        else:
            f.setFamily("Segoe UI")
        f.setPixelSize(font_px("small"))
        f.setBold(bold)
        return f

    def refresh_metrics(self) -> None:
        """Column widths and row height for the current look (fonts, density)."""
        mono = QFontMetrics(self._font())
        badge = QFontMetrics(self._font(False, True))
        self.editor.ensurePolished()
        edit_h = self.editor.sizeHint().height()
        hex_w = mono.horizontalAdvance(self.HEX_SAMPLE) + 2 * space(2)
        self._metrics = (max(self.SWATCH + 4, edit_h), hex_w,
                         mono.horizontalAdvance(self.RATIO_SAMPLE) + 2,
                         badge.horizontalAdvance(self.BADGE_TEXT) + 18,
                         max(mono.horizontalAdvance(t) for t in self._order),
                         mono.horizontalAdvance("bg.win…"))
        self.updateGeometry()
        self._place_editor()
        self.update()

    def _m(self) -> tuple:
        if self._metrics is None:
            self.refresh_metrics()
        return self._metrics

    def _gap(self) -> int:
        return space(1)

    def sizeHint(self) -> QSize:  # noqa: N802
        row_h, hex_w, ratio_w, badge_w, name_w, _ = self._m()
        g = space(2)
        n = len(self._order)
        return QSize(self.SWATCH + name_w + hex_w + ratio_w + badge_w + 4 * g,
                     n * row_h + (n - 1) * self._gap())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = self.sizeHint()
        _row_h, _hex_w, _ratio_w, _badge_w, name_w, name_min = self._m()
        return QSize(hint.width() - name_w + min(name_w, name_min), hint.height())

    def row_rect(self, index: int) -> QRectF:
        row_h = self._m()[0]
        return QRectF(0, index * (row_h + self._gap()), self.width(), row_h)

    def _columns(self, row: QRectF) -> dict[str, QRectF]:
        row_h, hex_w, ratio_w, badge_w, _name_w, _ = self._m()
        g = space(2)
        w, y, h = row.width(), row.y(), row.height()
        badge_x = w - badge_w
        ratio_x = badge_x - g - ratio_w
        hex_x = ratio_x - g - hex_w
        name_x = self.SWATCH + g
        return {"swatch": QRectF(0, y + (h - self.SWATCH) / 2, self.SWATCH, self.SWATCH),
                "name": QRectF(name_x, y, max(0, hex_x - g - name_x), h),
                "hex": QRectF(hex_x, y, hex_w, h),
                "ratio": QRectF(ratio_x, y, ratio_w, h),
                "badge": QRectF(badge_x, y + (h - 20) / 2, badge_w, 20)}

    def _index_at(self, pos) -> int:
        pos = QPointF(pos)
        row_h = self._m()[0]
        index = int(pos.y() // (row_h + self._gap()))
        return index if 0 <= index < len(self._order) and self.row_rect(index).contains(pos) else -1

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._place_editor()

    # -------------------------------------------------------------- values
    def show_values(self, colors) -> None:
        for token, row in self.rows.items():
            hex_ = colors[token]
            pairs = _PAIRS.get(token, [])
            if not pairs:
                ratio, warning, tip = "—", "", "No contrast target for this colour"
            else:
                results = [(p, t, contrast_ratio(hex_, colors[p])) for p, t in pairs]
                failing = [(p, t, r) for p, t, r in results if r < t]
                ratio = f"{min(r for _p, _t, r in results):.1f}:1"
                warning = ("Below the contrast target: " + "; ".join(
                    f"{p} {r:.1f}:1, needs {t:g}:1" for p, t, r in failing)) if failing else ""
                tip = "\n".join(f"On {p}: {r:.1f}:1 (target {t:g}:1)" for p, t, r in results)
            row.hex, row.ratio, row.warning = hex_, ratio, warning
            row.tip = f"{token}: {hex_}\n{tip}" + (f"\n{warning}" if warning else "")
        self._describe()
        self.update()

    def low_count(self) -> int:
        return sum(1 for row in self.rows.values() if row.warning)

    def _describe(self) -> None:
        row = self.rows[self._order[self._current]]
        self.setAccessibleDescription(row.tip)

    # -------------------------------------------------------------- editing
    def edit(self, token: str) -> None:
        """Show the hex editor over ``token``'s row."""
        self._current = self._order.index(token)
        self._editing = token
        self.editor.setText(self.rows[token].hex)
        self.editor.setAccessibleName(f"{token} hex value")
        self._place_editor()
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def _place_editor(self) -> None:
        if self._editing is None or self._metrics is None:
            return
        col = self._columns(self.row_rect(self._order.index(self._editing)))["hex"]
        eh = min(self.editor.sizeHint().height(), int(col.height()))
        self.editor.setGeometry(int(col.x()), int(col.y() + (col.height() - eh) / 2),
                                int(col.width()), eh)

    def _commit(self) -> None:
        token, self._editing = self._editing, None
        self.editor.hide()
        if token is not None:
            self._panel._hex_edited(token, self.editor)
        self.setFocus()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is self.editor and ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_Escape:
                self._editing = None
                self.editor.hide()
                self.setFocus()
                return True
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._commit()        # consumed: it would otherwise reach the list and re-open
                return True
        return super().eventFilter(obj, ev)

    # -------------------------------------------------------------- input
    def mousePressEvent(self, ev) -> None:  # noqa: N802
        index = self._index_at(ev.position())
        if ev.button() != Qt.LeftButton or index < 0:
            return super().mousePressEvent(ev)
        self._current = index
        token = self._order[index]
        cols = self._columns(self.row_rect(index))
        if cols["swatch"].contains(ev.position()):
            self._panel._pick_token(token)
        elif cols["hex"].contains(ev.position()):
            self.edit(token)
        self._describe()
        self.update()

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        key = ev.key()
        if key in (Qt.Key_Up, Qt.Key_Down):
            step = -1 if key == Qt.Key_Up else 1
            self._current = max(0, min(len(self._order) - 1, self._current + step))
            self._describe()
            self._panel._scroll_into_view(self, self.row_rect(self._current))
            self.update()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2):
            self.edit(self._order[self._current])
        elif key == Qt.Key_Space:
            self._panel._pick_token(self._order[self._current])
        else:
            super().keyPressEvent(ev)

    def event(self, ev) -> bool:
        if ev.type() == QEvent.ToolTip:
            index = self._index_at(ev.pos())
            if index >= 0:
                QToolTip.showText(ev.globalPos(), self.rows[self._order[index]].tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    # -------------------------------------------------------------- paint
    def paintEvent(self, _ev) -> None:  # noqa: N802
        look = current_look()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = min(4.0, float(look.skin.shape.get("radius.control", 4)))
        mono, badge_font = self._font(), self._font(False, True)
        fm = QFontMetrics(mono)
        for index, token in enumerate(self._order):
            row = self.rows[token]
            rect = self.row_rect(index)
            cols = self._columns(rect)
            if index == self._current and self.hasFocus():
                p.setPen(QPen(tok(look, "focus.ring"), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)
            p.setPen(QPen(tok(look, "line.strong"), 1.0))
            p.setBrush(QColor(row.hex) if row.hex else Qt.NoBrush)
            p.drawRoundedRect(cols["swatch"].adjusted(1, 1, -1, -1), radius, radius)
            p.setFont(mono)
            p.setPen(tok(look, "text.primary"))
            name = cols["name"]
            p.drawText(name, Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(token, Qt.ElideRight, int(name.width())))
            if token != self._editing:
                field = cols["hex"].adjusted(0, 2, 0, -2)
                p.setPen(QPen(tok(look, "line.subtle"), 1.0))
                p.setBrush(tok(look, "bg.inset"))
                p.drawRoundedRect(field, radius, radius)
                p.setPen(tok(look, "text.primary"))
                p.drawText(field.adjusted(space(1), 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, row.hex)
            p.setPen(tok(look, "text.secondary"))
            p.drawText(cols["ratio"], Qt.AlignRight | Qt.AlignVCenter, row.ratio)
            if row.warning:
                badge = cols["badge"]
                p.setPen(Qt.NoPen)
                p.setBrush(tok(look, "status.warn.subtle"))
                p.drawRoundedRect(badge, badge.height() / 2, badge.height() / 2)
                p.setFont(badge_font)
                p.setPen(tok(look, "status.warn"))
                p.drawText(badge, Qt.AlignCenter, self.BADGE_TEXT)
        p.end()


# ------------------------------------------------------------------ the panel

class CustomizePanel(QDockWidget):
    """Docked Look editor. ``saved`` carries the id of what was written: the skin id, or the
    theme id when only a theme was saved."""

    saved = Signal(str)
    closed = Signal()        # closed for good: the panel deletes itself (WA_DeleteOnClose)

    def __init__(self, core, parent=None):
        super().__init__("Customize", parent)
        self.core = core
        self.cfg = core.cfg
        self.setObjectName("customizePanel")
        # Created on open, deleted on close: a live panel (even hidden) would be re-polished by
        # every later look switch.
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._spaced = SpacedLayouts()
        self._captions: list[TextLine] = []
        self._applying = False
        self._advanced = False
        self._banner_mode = ""
        self._thumbs: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._thumb_look: Look | None = None
        self._thumb_base: tuple = ()
        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(LIVE_EDIT_MS)
        self._live.timeout.connect(self._apply_draft)
        self._load(current_look())

        self._build_title_bar()
        body = QWidget()
        body.setObjectName("customizeBody")
        outer = self._spaced.add(QVBoxLayout(body), spacing=0, margins=0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("customizeScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        self.content = QWidget()
        self.content.setObjectName("customizeBody")
        self.scroll.setWidget(self.content)
        col = self._spaced.add(QVBoxLayout(self.content), spacing=2, margins=3)
        self._build_header(col)
        self._build_elements(col)
        self._build_colours(col)
        col.addStretch(1)
        self.setWidget(body)

        self.name_edit.setText(self._suggested_name())
        _follow_look(self)
        self.resize(DEFAULT_WIDTH, 640)
        self._sync()
        self._sync_min_width()

    # ------------------------------------------------------------ building
    def _build_title_bar(self) -> None:
        bar = QWidget()
        bar.setObjectName("customizeTitleBar")
        lay = self._spaced.add(QHBoxLayout(bar), spacing=2, margins=(3, 1, 1, 1))
        lay.addWidget(TextLine("Customize", "title"), 1)
        self.close_btn = make_button(tier="quiet", icon="remove", tooltip="Close the Customize panel")
        self.close_btn.clicked.connect(self.close)
        lay.addWidget(self.close_btn)
        self.setTitleBarWidget(bar)

    def _build_header(self, col: QVBoxLayout) -> None:
        self.base_label = hint_label("")
        col.addWidget(self.base_label)

        name_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        name_lbl = QLabel("Name")
        name_row.addWidget(name_lbl)
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(60)
        self.name_edit.setAccessibleName("Name for a new look")
        self.name_edit.setPlaceholderText("Name for Save as new")
        name_lbl.setBuddy(self.name_edit)
        name_row.addWidget(self.name_edit, 1)
        col.addLayout(name_row)

        grid = self._spaced.add(QGridLayout(), spacing=2, margins=0)
        self.save_btn = make_button("Save", tooltip="Write the changes back to this user skin or theme")
        self.save_as_btn = make_button("Save as new", "primary",
                                       tooltip="Save the changes as a new user skin (and theme)")
        self.revert_btn = make_button("Revert", tooltip="Go back to the last saved look")
        self.export_btn = make_button("Export…", tooltip="Share the skin or theme as a file")
        self.import_btn = make_button("Import…", tooltip="Add a skin or theme from a file")
        self.delete_btn = make_button("Delete", "danger", tooltip="Delete this user skin or theme")
        for i, btn in enumerate((self.save_btn, self.save_as_btn, self.revert_btn,
                                 self.export_btn, self.import_btn, self.delete_btn)):
            grid.addWidget(btn, i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        col.addLayout(grid)
        self.save_btn.clicked.connect(self.save)
        self.save_as_btn.clicked.connect(lambda: self.save_as(self.name_edit.text()))
        self.revert_btn.clicked.connect(self.revert)
        self.export_btn.clicked.connect(self._choose_export)
        self.import_btn.clicked.connect(self._choose_import)
        self.delete_btn.clicked.connect(lambda: self._show_banner("delete"))

        self.message_label = QLabel()
        self.message_label.setObjectName("customizeMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setTextFormat(Qt.PlainText)
        self.message_label.hide()
        col.addWidget(self.message_label)

        # The banner is built when it is shown and deleted when it goes (see _ensure_banner).
        self._header_col = col
        self._banner: QFrame | None = None
        self._banner_parts: dict = {}

    def _ensure_banner(self) -> QFrame:
        if self._banner is not None:
            return self._banner
        banner = QFrame()
        banner.setObjectName("customizeBanner")
        banner.setProperty("state", "warn")
        b_lay = QVBoxLayout(banner)
        b_lay.setSpacing(space(2))
        b_lay.setContentsMargins(*(space(2),) * 4)
        label = QLabel()
        label.setObjectName("customizeBannerText")
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        b_lay.addWidget(label)
        b_row = QHBoxLayout()
        b_row.setSpacing(space(2))
        b_row.setContentsMargins(0, 0, 0, 0)
        parts = {"label": label, "save": make_button("Save"),
                 "discard": make_button("Discard", "danger"),
                 "delete": make_button("Delete", "danger"), "keep": make_button("Keep editing")}
        for key in ("save", "discard", "delete", "keep"):
            b_row.addWidget(parts[key])
        b_row.addStretch(1)
        b_lay.addLayout(b_row)
        parts["save"].clicked.connect(self._banner_save)
        parts["discard"].clicked.connect(self._banner_discard)
        parts["delete"].clicked.connect(self._banner_delete)
        parts["keep"].clicked.connect(self._banner_keep)
        banner.hide()
        self._header_col.insertWidget(self._header_col.indexOf(self.message_label) + 1, banner)
        self._banner, self._banner_parts = banner, parts
        return banner

    @property
    def banner(self) -> QFrame:
        return self._ensure_banner()

    @property
    def banner_label(self) -> QLabel:
        self._ensure_banner()
        return self._banner_parts["label"]

    @property
    def banner_save_btn(self):
        self._ensure_banner()
        return self._banner_parts["save"]

    @property
    def banner_discard_btn(self):
        self._ensure_banner()
        return self._banner_parts["discard"]

    @property
    def banner_delete_btn(self):
        self._ensure_banner()
        return self._banner_parts["delete"]

    @property
    def banner_keep_btn(self):
        self._ensure_banner()
        return self._banner_parts["keep"]

    def _caption(self, col: QVBoxLayout, text: str, role: str = "slot") -> TextLine:
        line = TextLine(text, role)
        self._captions.append(line)
        col.addWidget(line)
        return line

    def _build_elements(self, col: QVBoxLayout) -> None:
        self._caption(col, "Elements", "group")
        self.tiles: dict[tuple[str, str], VariantTile] = {}
        for slot in SKIN_SLOTS:
            self._caption(col, SLOT_TITLES.get(slot, slot))
            grid = self._spaced.add(QGridLayout(), spacing=2, margins=0)
            for i, variant in enumerate(registry.variants(slot)):
                tile = VariantTile(self, slot, variant, registry.label(slot, variant))
                tile.clicked.connect(lambda _=False, s=slot, v=variant: self.select_variant(s, v))
                self.tiles[(slot, variant)] = tile
                grid.addWidget(tile, i // 3, i % 3)
            for c in range(3):
                grid.setColumnStretch(c, 1)
            col.addLayout(grid)

    def _build_colours(self, col: QVBoxLayout) -> None:
        self.colours_label = self._caption(col, "Colours", "group")
        self._caption(col, "Accent")
        row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.accent_swatch = ColorSwatch("Accent colour")
        self.accent_swatch.clicked.connect(self._pick_accent)
        row.addWidget(self.accent_swatch)
        self.accent_edit = QLineEdit()
        self.accent_edit.setObjectName("hexEdit")
        self.accent_edit.setMaxLength(7)
        self.accent_edit.setAccessibleName("Accent hex value")
        self.accent_edit.editingFinished.connect(self._accent_edited)
        fit_hex_edit(self.accent_edit)
        row.addWidget(self.accent_edit)
        self.pick_accent_btn = make_button("Pick…", tooltip="Choose the accent colour")
        self.pick_accent_btn.clicked.connect(self._pick_accent)
        row.addWidget(self.pick_accent_btn)
        row.addStretch(1)
        col.addLayout(row)
        self.notice_label = QLabel(ADJUSTED_TEXT)
        self.notice_label.setObjectName("customizeNotice")
        self.notice_label.setToolTip("The accent was made lighter so it stays visible on the panels")
        self.notice_label.hide()
        col.addWidget(self.notice_label)

        self._caption(col, "Background tint")
        chips = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.tint_chips: dict[str, QAbstractButton] = {}
        for tint, text in (*TINT_CHIPS, ("custom", "Custom…")):
            chip = make_button(text, tooltip=("Pick a hue for the surfaces" if tint == "custom"
                                              else f"{text} surfaces"))
            chip.setProperty("chip", "true")
            chip.setCheckable(True)
            if tint == "custom":
                chip.clicked.connect(self._pick_tint)
            else:
                chip.clicked.connect(lambda _=False, t=tint: self.set_tint(t))
            self.tint_chips[tint] = chip
            chips.addWidget(chip)
        chips.addStretch(1)
        col.addLayout(chips)

        self.advanced_check = QCheckBox("Advanced: edit every colour")
        self.advanced_check.toggled.connect(self.set_advanced)
        col.addWidget(self.advanced_check)
        # The token list exists only while Advanced is on (_build_advanced / _drop_advanced):
        # every widget alive is re-polished by each look switch, hidden or not.
        self._colours_col = col
        self._advanced_at = col.count()
        self.token_list: TokenList | None = None
        self.contrast_label: QLabel | None = None

    @property
    def token_rows(self) -> dict[str, TokenRowView]:
        """Advanced mode's rows by token (empty while Advanced is off)."""
        return self.token_list.rows if self.token_list is not None else {}

    @property
    def advanced_box(self) -> TokenList | None:
        return self.token_list

    def _build_advanced(self) -> None:
        self.contrast_label = QLabel()
        self.contrast_label.setObjectName("customizeMessage")
        self.contrast_label.setProperty("state", "warn")
        self.contrast_label.setWordWrap(True)
        self.contrast_label.hide()
        self.token_list = TokenList(self)
        self._colours_col.insertWidget(self._advanced_at, self.contrast_label)
        self._colours_col.insertWidget(self._advanced_at + 1, self.token_list)
        self.token_list.show()

    def _drop_advanced(self) -> None:
        for w in (self.contrast_label, self.token_list):
            if w is not None:
                w.hide()
                self._colours_col.removeWidget(w)
                w.deleteLater()
        self.token_list = None
        self.contrast_label = None

    # ------------------------------------------------------------ state
    def _load(self, look: Look) -> None:
        """Make ``look`` the saved state the draft starts from (and Discard / Revert return to)."""
        self._base = look
        self._elements = dict(look.skin.elements)
        self._colors = dict(look.palette.colors)
        self._source = dict(look.palette.source) if look.palette.source else None
        self._adjusted = False
        if hasattr(self, "name_edit"):
            self.name_edit.setText(self._suggested_name())

    def _suggested_name(self) -> str:
        """A name for Save as new that no skin uses yet ("My Vintage", "Night copy")."""
        skin = self._base.skin
        base = f"{skin.name} copy" if _is_user(skin.id) else f"My {skin.name}"
        try:
            taken = {s.name.casefold() for s in user_looks.all_skins().values()}
        except OSError:
            return base
        name, n = base, 1
        while name.casefold() in taken:
            n += 1
            name = f"{base} ({n})"
        return name

    def _skin_changed(self) -> bool:
        return self._elements != dict(self._base.skin.elements)

    def _palette_changed(self) -> bool:
        base = self._base.palette
        return self._colors != dict(base.colors) or self._source != (dict(base.source) if base.source else None)

    def is_dirty(self) -> bool:
        return self._skin_changed() or self._palette_changed()

    def _can_save(self) -> bool:
        skin, palette = self._skin_changed(), self._palette_changed()
        return ((skin or palette) and (not skin or _is_user(self._base.skin.id))
                and (not palette or _is_user(self._base.palette.id)))

    def _draft_skin(self, name: str | None = None) -> Skin:
        base = self._base.skin
        if name is None and not self._skin_changed():
            return base
        return Skin(base.id, name or base.name, self._elements, base.shape)

    def _draft_palette(self, name: str | None = None) -> Palette:
        base = self._base.palette
        if name is None and not self._palette_changed():
            return base
        return Palette(base.id, name or base.name, base.dark, self._colors, self._source)

    def draft_look(self) -> Look:
        """The look being edited (the saved look when nothing changed)."""
        skin, palette = self._draft_skin(), self._draft_palette()
        if skin is self._base.skin and palette is self._base.palette:
            return self._base
        return Look(palette, skin)

    def banner_mode(self) -> str:
        """``""`` (no banner), ``"close"``, ``"external"`` or ``"delete"``."""
        return self._banner_mode

    # ------------------------------------------------------------ applying
    def _apply_draft(self) -> None:
        """Make the draft the current look (once; live picker edits come through the timer)."""
        self._live.stop()
        look = self.draft_look()
        if look != current_look():
            self._applying = True
            try:
                set_look(look)
            finally:
                self._applying = False
        if self._banner_mode == "external":
            self._hide_banner()
        self._sync()

    def _schedule_apply(self) -> None:
        if not self._live.isActive():
            self._live.start()

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        if self.token_list is not None:
            self.token_list.refresh_metrics()
        for line in self._captions:
            line.refresh()
        fit_hex_edit(self.accent_edit)
        for tile in self.tiles.values():
            tile.update()
        self._sync_min_width()
        if self._applying:
            return
        current = current_look()
        if current == self.draft_look():
            if self._banner_mode == "external":
                self._hide_banner()
        elif self.is_dirty():
            self._show_banner("external")
        else:
            self._load(current)
        self._sync()

    def reload(self) -> None:
        """Start over from the current look unless there are unsaved changes."""
        if not self.is_dirty():
            self._load(current_look())
        self._sync()

    def thumbnail(self, slot: str, variant: str, dpr: float = 1.0) -> QPixmap:
        """The thumbnail of a variant in the current look, rendered once and cached by what it
        depends on: the palette's colours, the shape tokens and, for a frame, the screws it
        bolts on. Swapping elements or switching skins in one theme renders nothing again; the
        last few looks' thumbnails are kept, so switching back is free too."""
        look = current_look()
        if look != self._thumb_look:
            self._thumb_look = look
            self._thumb_base = (tuple(sorted(look.palette.colors.items())),
                                tuple(sorted(look.skin.shape.items())))
        extra = registry.resolve(look.skin.elements)[0]["screws"] if slot == "frame" else ""
        key = (slot, variant, dpr, extra, self._thumb_base)
        pm = self._thumbs.get(key)
        if pm is None:
            pm = render_thumbnail(slot, variant, look, THUMB_W, THUMB_H, dpr)
            self._thumbs[key] = pm
            while len(self._thumbs) > THUMB_CACHE:
                self._thumbs.popitem(last=False)
        else:
            self._thumbs.move_to_end(key)
        return pm

    # ------------------------------------------------------------ elements
    def select_variant(self, slot: str, variant: str) -> None:
        if slot not in SKIN_SLOTS or variant not in registry.variants(slot):
            raise ValueError(f"unknown element {slot!r} / {variant!r}")
        self._elements[slot] = variant
        self._clear_message()
        self._apply_draft()

    # ------------------------------------------------------------ colours
    def _derive(self, accent: str, tint: str) -> None:
        colors, notes = derive_colors(accent, tint, self._base.palette.dark)
        self._colors = colors
        self._source = {"accent": accent, "tint": tint}
        self._adjusted = any(n.startswith("accent:") for n in notes)

    def _current_tint(self) -> str:
        return (self._source or {}).get("tint", "neutral")

    def set_accent(self, hex_: str) -> None:
        accent = _valid_hex(hex_)
        if accent is None:
            self._show_message(f"{hex_!r} is not a colour: use #rrggbb", "danger")
            self._sync()
            return
        self._derive(accent, self._current_tint())
        self._clear_message()
        self._apply_draft()

    def preview_accent(self, hex_: str) -> None:
        """Live accent while a picker is dragged: coalesced to one ``set_look`` per tick."""
        accent = _valid_hex(hex_)
        if accent is not None:
            self._derive(accent, self._current_tint())
            self._schedule_apply()

    def set_tint(self, tint: str) -> None:
        if tint not in TINTS and _valid_hex(tint) is None:
            raise ValueError(f"unknown tint {tint!r}; use one of {sorted(TINTS)} or #rrggbb")
        tint = tint if tint in TINTS else _valid_hex(tint)
        accent = (self._source or {}).get("accent") or self._colors["accent"]
        self._derive(accent, tint)
        self._clear_message()
        self._apply_draft()

    def set_advanced(self, on: bool) -> None:
        on = bool(on)
        self._advanced = on
        if self.advanced_check.isChecked() != on:
            self.advanced_check.blockSignals(True)
            self.advanced_check.setChecked(on)
            self.advanced_check.blockSignals(False)
        if on and self.advanced_box is None:
            self._build_advanced()
        elif not on and self.advanced_box is not None:
            self._drop_advanced()
        self._sync()
        self._sync_min_width()

    def set_token(self, token: str, hex_: str) -> None:
        if token not in PALETTE_TOKENS:
            raise ValueError(f"unknown colour token {token!r}")
        value = _valid_hex(hex_)
        if value is None:
            self._show_message(f"{token}: {hex_!r} is not a colour: use #rrggbb", "danger")
            self._sync()
            return
        self._set_token(token, value)
        self._clear_message()
        self._apply_draft()

    def preview_token(self, token: str, hex_: str) -> None:
        value = _valid_hex(hex_)
        if token in PALETTE_TOKENS and value is not None:
            self._set_token(token, value)
            self._schedule_apply()

    def _set_token(self, token: str, value: str) -> None:
        if self._colors.get(token) != value:
            self._colors[token] = value
            self._source = None          # hand-edited: no longer derived from accent + tint
            if token == "accent":        # the notice is about the accent the derivation nudged
                self._adjusted = False

    # ------------------------------------------------------------ saving
    def _select(self, skin_id: str, theme_id: str, apply: bool = True) -> None:
        """Select these ids in the config, persist it and start over from the look it gives."""
        self.cfg.ui_skin, self.cfg.theme = skin_id, theme_id
        self.core.save()
        self._load(look_from_config(self.cfg))
        if apply:
            self._apply_draft()

    def save(self) -> str | None:
        """Overwrite the user skin and/or theme in place (only when every changed part is a
        user item). Returns the id ``saved`` carries, or None."""
        if not self._can_save():
            return None
        skin_changed, palette_changed = self._skin_changed(), self._palette_changed()
        base = self._base
        try:
            if skin_changed:
                user_looks.save_skin(self._draft_skin())
            if palette_changed:
                user_looks.save_palette(self._draft_palette())
        except (OSError, ValueError, user_looks.LookFileError) as exc:
            if skin_changed and palette_changed:
                # the skin may be on disk already: keep the editor in step with the files
                fresh = user_looks.all_skins().get(base.skin.id)
                if fresh is not None and dict(fresh.elements) == self._elements:
                    self._base = Look(base.palette, fresh)
                    self._sync()
            self._show_message(f"Could not save: {exc}", "danger")
            return None
        self._select(base.skin.id, base.palette.id)
        saved_id = base.skin.id if skin_changed else base.palette.id
        self._show_message(f"Saved “{base.skin.name if skin_changed else base.palette.name}”.")
        self.saved.emit(saved_id)
        return saved_id

    def save_as(self, name: str) -> str | None:
        """Save the draft as a new user skin called ``name`` (plus a user theme of the same name
        when the colours changed), select it and return the skin id; None on failure."""
        name = " ".join(str(name or "").split())
        if not name:
            self._show_message("Enter a name for the new look first.", "danger")
            return None
        palette_changed = self._palette_changed()
        theme_id = self._base.palette.id
        skin = None
        try:
            skin = user_looks.new_skin(name, self._elements, self._base.skin.shape)
            user_looks.save_skin(skin)
            if palette_changed:
                palette = user_looks.new_palette(name, self._base.palette.dark, self._colors, self._source)
                user_looks.save_palette(palette)
                theme_id = palette.id
        except (OSError, ValueError, user_looks.LookFileError) as exc:
            if skin is not None and palette_changed:   # no orphan skin without its theme
                try:
                    user_looks.delete_user_look(skin.id, "skin")
                except (OSError, ValueError):
                    pass
            self._show_message(f"Could not save: {exc}", "danger")
            return None
        self._select(skin.id, theme_id)
        self._show_message(f"Saved “{skin.name}”.")
        self.saved.emit(skin.id)
        return skin.id

    def revert(self) -> None:
        """Back to the last saved look."""
        self._load(self._base)
        self._clear_message()
        if self._banner_mode in ("close", "external"):
            self._hide_banner()
        self._apply_draft()

    def delete(self) -> bool:
        """Delete the current user skin, or (with a built-in skin) the current user theme, and fall
        back to the built-in default for it. Built-ins cannot be deleted (returns False)."""
        base = self._base
        if _is_user(base.skin.id):
            kind, look = "skin", base.skin
        elif _is_user(base.palette.id):
            kind, look = "theme", base.palette
        else:
            return False
        try:
            user_looks.delete_user_look(look.id, kind)
        except (OSError, ValueError) as exc:
            self._show_message(f"Could not delete: {exc}", "danger")
            return False
        if kind == "skin":
            self._select(DEFAULT_SKIN, base.palette.id)
        else:
            self._select(base.skin.id, DEFAULT_THEME)
        self._show_message(f"Deleted the {kind} “{look.name}”.")
        return True

    # ------------------------------------------------------------ sharing
    def export(self, path) -> bool:
        """Write the skin (``.mandibleskin``) or the palette (``.mandibletheme``) being edited."""
        path = Path(path)
        ext = path.suffix.lower()
        name = " ".join(self.name_edit.text().split()) or None
        try:
            if ext == user_looks.SKIN_EXT:
                user_looks.export_skin(self._draft_skin(name or self._base.skin.name), path)
            elif ext == user_looks.THEME_EXT:
                if name is None or name == self._suggested_name():   # not typed: the theme's own
                    palette = self._base.palette
                    name = palette.name if _is_user(palette.id) else f"My {palette.name}"
                user_looks.export_palette(self._draft_palette(name), path)
            else:
                self._show_message(f"Export to a {user_looks.SKIN_EXT} (skin) or "
                                   f"{user_looks.THEME_EXT} (theme) file.", "danger")
                return False
        except (OSError, ValueError, user_looks.LookFileError) as exc:
            self._show_message(f"Could not export: {exc}", "danger")
            return False
        self._show_message(f"Exported {path.name}.")
        return True

    def import_file(self, path) -> str | None:
        """Import a skin or theme file and select it. Errors show inline; nothing changes."""
        path = Path(path)
        skin_edits = dict(self._elements) if self._skin_changed() else None
        colour_edits = (dict(self._colors), self._source) if self._palette_changed() else None
        try:
            kind, look, notices = user_looks.import_look(path)
        except user_looks.LookFileError as exc:
            self._show_message(f"Could not import {path.name}: {exc}", "danger")
            return None
        except OSError as exc:            # writing the imported copy failed (disk full, ...)
            self._show_message(f"Could not import {path.name}: "
                               f"{exc.strerror or type(exc).__name__}", "danger")
            return None
        if kind == "skin":
            self._select(look.id, self._base.palette.id, apply=False)
            if colour_edits is not None:          # unsaved colour edits survive a skin import
                self._colors, self._source = colour_edits[0], colour_edits[1]
        else:
            self._select(self._base.skin.id, look.id, apply=False)
            if skin_edits is not None:            # and unsaved element edits a theme import
                self._elements = skin_edits
        self._apply_draft()
        text = f"Imported the {kind} “{look.name}”."
        if notices:
            text += " " + " ".join(notices[:3])
        self._show_message(text, "warn" if notices else "")
        return look.id

    def _choose_export(self) -> None:
        from ..user_looks import slugify

        stem = slugify(self.name_edit.text() or self._base.skin.name)
        start = str(Path.home() / stem)
        skin_filter = f"Mandible skin (*{user_looks.SKIN_EXT})"
        theme_filter = f"Mandible theme (*{user_looks.THEME_EXT})"
        path, chosen = QFileDialog.getSaveFileName(self, "Export look", start,
                                                   f"{skin_filter};;{theme_filter}")
        if not path:
            return
        if Path(path).suffix.lower() not in (user_looks.SKIN_EXT, user_looks.THEME_EXT):
            path += user_looks.THEME_EXT if chosen == theme_filter else user_looks.SKIN_EXT
        self.export(path)

    def _choose_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import look", str(Path.home()),
            f"Mandible looks (*{user_looks.SKIN_EXT} *{user_looks.THEME_EXT});;All files (*)")
        if path:
            self.import_file(path)

    # ------------------------------------------------------------ pickers
    def _run_picker(self, title: str, start: str, preview, commit) -> None:
        """A colour dialog whose drag previews live (coalesced); Cancel restores the draft."""
        before = (dict(self._colors), self._source, self._adjusted)
        dlg = QColorDialog(QColor(start), self)
        dlg.setWindowTitle(title)
        dlg.currentColorChanged.connect(lambda c: preview(c.name()))
        try:
            if dlg.exec():
                commit(dlg.selectedColor().name())
            else:
                self._colors, self._source, self._adjusted = before
                self._apply_draft()
        finally:
            dlg.deleteLater()

    def _pick_accent(self) -> None:
        self._run_picker("Accent colour", self._colors["accent"], self.preview_accent, self.set_accent)

    def _pick_token(self, token: str) -> None:
        self._run_picker(token, self._colors[token], lambda h: self.preview_token(token, h),
                         lambda h: self.set_token(token, h))

    def _pick_tint(self) -> None:
        self._sync()                      # the chip's own toggle is undone; the picker decides
        start = self._current_tint() if _valid_hex(self._current_tint()) else self._colors["bg.panel"]
        color = QColorDialog.getColor(QColor(start), self, "Background tint")
        if color.isValid():
            self.set_tint(color.name())

    def _accent_edited(self) -> None:
        text = self.accent_edit.text()
        shown = (self._source or {}).get("accent") or self._colors["accent"]
        if text.strip().lower() != shown:
            self.set_accent(text)

    def _hex_edited(self, token: str, edit: QLineEdit) -> None:
        if edit.text().strip().lower() != self._colors[token]:
            self.set_token(token, edit.text())

    # ------------------------------------------------------------ banner and messages
    def _show_message(self, text: str, state: str = "") -> None:
        if self.message_label.property("state") != state:
            set_style_property(self.message_label, "state", state)
        self.message_label.setText(text)
        self.message_label.show()

    def _clear_message(self) -> None:
        self.message_label.hide()
        self.message_label.clear()

    def _show_banner(self, mode: str) -> None:
        base = self._base
        if mode == "delete":
            if _is_user(base.skin.id):
                what = f"the skin “{base.skin.name}”"
            elif _is_user(base.palette.id):
                what = f"the theme “{base.palette.name}”"
            else:
                return
            text = f"Delete {what}? This cannot be undone."
            if self.is_dirty():
                text += " Your unsaved changes will be lost too."
        elif mode == "external":
            text = "The look was changed elsewhere. Your changes here are not saved."
        else:
            text = "You have unsaved changes."
        self._banner_mode = mode
        self.banner_label.setText(text)
        set_style_property(self.banner, "state", "danger" if mode == "delete" else "warn")
        self.banner_save_btn.setVisible(mode != "delete")
        self.banner_discard_btn.setVisible(mode != "delete")
        self.banner_delete_btn.setVisible(mode == "delete")
        self.banner_keep_btn.setText("Cancel" if mode == "delete" else "Keep editing")
        self.banner.show()
        self.scroll.ensureWidgetVisible(self.banner)

    def _hide_banner(self) -> None:
        self._banner_mode = ""
        banner, self._banner, self._banner_parts = self._banner, None, {}
        if banner is not None:
            banner.hide()
            self._header_col.removeWidget(banner)
            banner.deleteLater()

    def _banner_save(self) -> None:
        mode = self._banner_mode
        ok = self.save() if self._can_save() else self.save_as(self.name_edit.text())
        if ok is None:
            return
        self._hide_banner()
        if mode == "close":
            self.close()

    def _banner_discard(self) -> None:
        mode = self._banner_mode
        self._hide_banner()
        if mode == "external":
            self._load(current_look())
            self._sync()
        else:
            self.discard_and_close()

    def _banner_keep(self) -> None:
        mode = self._banner_mode
        self._hide_banner()
        if mode == "external":
            self._apply_draft()

    def _banner_delete(self) -> None:
        self._hide_banner()
        self.delete()

    def discard_and_close(self) -> None:
        """Drop unsaved changes (back to the saved look) and close without asking."""
        self._live.stop()
        if self.is_dirty():
            self._load(self._base)
            self._apply_draft()
        self._hide_banner()
        self.close()

    def closeEvent(self, ev) -> None:  # noqa: N802 - Qt naming
        if self.is_dirty():
            ev.ignore()
            self._show_banner("close")
            return
        self._hide_banner()
        self._live.stop()
        try:                      # no more look-switch work while the deletion is pending
            look_bus().lookChanged.disconnect(self._on_look_changed)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(ev)
        self.closed.emit()

    # ------------------------------------------------------------ syncing the controls
    def _sync(self) -> None:
        base = self._base
        for (slot, variant), tile in self.tiles.items():
            on = self._elements.get(slot) == variant
            if tile.isChecked() != on:
                tile.setChecked(on)
        can_save, dirty = self._can_save(), self.is_dirty()
        self.save_btn.setEnabled(can_save)
        set_tier(self.save_btn, "primary" if can_save else "secondary")
        set_tier(self.save_as_btn, "secondary" if can_save else "primary")
        self.revert_btn.setEnabled(dirty)
        self.delete_btn.setEnabled(_is_user(base.skin.id) or _is_user(base.palette.id))
        if _is_user(base.skin.id):
            self.delete_btn.setToolTip(f"Delete the user skin “{base.skin.name}”")
        elif _is_user(base.palette.id):
            self.delete_btn.setToolTip(f"Delete the user theme “{base.palette.name}”")
        else:
            self.delete_btn.setToolTip("Built-in skins and themes cannot be deleted")
        text = (f"Editing the {_owner(base.skin.id)} skin “{base.skin.name}” and the "
                f"{_owner(base.palette.id)} theme “{base.palette.name}”.")
        if dirty and not can_save:
            text += " Built-in looks are kept as they are: save your changes as a new look."
        self.base_label.setText(text)

        accent = self._colors["accent"]
        self.accent_swatch.set_color(accent)
        shown = (self._source or {}).get("accent") or accent
        if not self.accent_edit.hasFocus() and self.accent_edit.text() != shown:
            self.accent_edit.setText(shown)
        self.notice_label.setVisible(self._adjusted)
        tint = self._current_tint() if self._source else None
        for name, chip in self.tint_chips.items():
            on = (tint == name) if name != "custom" else (tint is not None and tint not in TINTS)
            if chip.isChecked() != on:
                chip.setChecked(on)
        if self._advanced and self.token_list is not None:
            self.token_list.show_values(self._colors)
            low = self.token_list.low_count()
            self.contrast_label.setText(f"{low} colour{'s' if low != 1 else ''} below the contrast "
                                        "target. You can still save; the warning stays." if low else "")
            self.contrast_label.setVisible(bool(low))

    def _sync_min_width(self) -> None:
        """The dock is never narrower than its content (the content never scrolls sideways)."""
        need = self.content.minimumSizeHint().width() + self.scroll.verticalScrollBar().sizeHint().width()
        self.scroll.setMinimumWidth(max(MIN_WIDTH, need))

    # ------------------------------------------------------------ gallery
    def _scroll_to(self, widget: QWidget | None) -> None:
        """Scroll so ``widget`` is at the top (None: the very top)."""
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()          # the content's new height first
        bar = self.scroll.verticalScrollBar()
        bar.setValue(0 if widget is None else widget.mapTo(self.content, widget.rect().topLeft()).y())

    def _scroll_to_end(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _scroll_into_view(self, widget: QWidget, rect: QRectF) -> None:
        """Keep ``rect`` (in ``widget``'s coordinates) visible in the scroll area."""
        centre = widget.mapTo(self.content, rect.center().toPoint())
        self.scroll.ensureVisible(centre.x(), centre.y(), 0, int(rect.height()))

    def gallery_states(self, warnings: bool = False):
        """``(suffix, label)`` per state the UI gallery captures, each scrolled into view: the
        header and elements, the simple colours, the advanced token list (top and end) and the
        unsaved-changes banner. ``warnings`` adds a state with the contrast badge and the
        "Adjusted for readability" notice (it changes the live look twice, then reverts). Leaves
        the panel as it found it."""
        advanced = self._advanced
        try:
            self.set_advanced(False)
            self._scroll_to(None)
            yield "", ""
            self._scroll_to(self.colours_label)
            yield "_colours", "colours"
            self.set_advanced(True)
            self._scroll_to(self.colours_label)
            yield "_advanced", "advanced colours"
            self._scroll_to_end()
            yield "_advanced_end", "advanced colours (end)"
            if warnings and not self.is_dirty():
                # An accent as dark as the panel (nudged: the notice shows), then a secondary text
                # as dark as a line (below target: the badge shows). Reverted afterwards.
                self.set_accent(self._colors["bg.panel"])
                self.set_token("text.secondary", self._colors["line.subtle"])
                self._scroll_to(self.colours_label)
                yield "_warnings", "contrast warnings"
                self.revert()
            self.set_advanced(False)
            self._show_banner("close")
            self._scroll_to(None)
            yield "_banner", "unsaved changes"
        finally:
            self._hide_banner()
            self.set_advanced(advanced)
            self._scroll_to(None)
