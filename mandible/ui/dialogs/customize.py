"""The Customize panel (spec 7.4): swap a skin's elements, edit its colours, save and share it.

A non-modal dock on the main window, so the real window is the live preview. What it edits is the
current Look: Elements change the skin, Colours the palette. Built-in skins and themes are never
overwritten: *Save* writes back only to user items, *Save as new* always makes a user skin (and a
user theme too when the colours changed). Unsaved changes are guarded by an inline banner (Save /
Discard / Keep editing), never an OS dialog. Nothing here touches the audio engine.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QColorDialog, QDockWidget, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import user_looks
from ..elements import registry
from ..elements.base import ElementState, tok
from ..look import (SKIN_SLOTS, Look, Palette, Skin, current_look, font_px, look_from_config,
                    set_look, with_elements)
from ..palette_gen import CONTRAST_PAIRS, PALETTE_TOKENS, TINTS, contrast_ratio, derive_colors
from ..widgets.base import SpacedLayouts, _follow_look, set_style_property
from ..widgets.buttons import StatusPill, make_button, set_tier
from ..widgets.labels import ElidedLabel
from .parts import group_label, hint_label

__all__ = ["CustomizePanel", "VariantTile", "ColorSwatch", "TokenRow", "render_thumbnail",
           "LIVE_EDIT_MS", "MIN_WIDTH", "DEFAULT_WIDTH", "ADJUSTED_TEXT"]

LIVE_EDIT_MS = 40          # live picker edits apply at most once per tick (R7)
MIN_WIDTH = 320            # the dock's narrowest width (content may ask for more)
DEFAULT_WIDTH = 380
THUMB_W, THUMB_H = 84, 44  # element thumbnails (logical px)
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


class TokenRow(QWidget):
    """Advanced mode: one palette token with its swatch, hex value, contrast ratio against its
    partner surface (the worst of its CONTRAST_PAIRS) and a warning badge below target."""

    def __init__(self, panel: "CustomizePanel", token: str, spaced: SpacedLayouts):
        super().__init__()
        self.token = token
        lay = spaced.add(QHBoxLayout(self), spacing=2, margins=0)
        self.swatch = ColorSwatch(f"Colour {token}")
        self.swatch.clicked.connect(lambda: panel._pick_token(token))
        lay.addWidget(self.swatch)
        self.name_label = ElidedLabel(token, min_chars=6)
        self.name_label.setObjectName("tokenName")
        lay.addWidget(self.name_label, 1)
        self.hex_edit = QLineEdit()
        self.hex_edit.setObjectName("hexEdit")
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setAccessibleName(f"{token} hex value")
        self.hex_edit.editingFinished.connect(lambda: panel._hex_edited(token, self.hex_edit))
        lay.addWidget(self.hex_edit)
        self.ratio_label = QLabel("—")
        self.ratio_label.setObjectName("tokenRatio")
        self.ratio_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.ratio_label)
        self.badge = StatusPill("Low", "warn")
        keep = self.badge.sizePolicy()
        keep.setRetainSizeWhenHidden(True)
        self.badge.setSizePolicy(keep)
        self.badge.hide()
        lay.addWidget(self.badge)
        self.fit_columns()

    def fit_columns(self) -> None:
        """Fixed hex and ratio columns, so every row lines up."""
        fit_hex_edit(self.hex_edit)
        self.ratio_label.ensurePolished()
        self.ratio_label.setFixedWidth(self.ratio_label.fontMetrics().horizontalAdvance("21.0:1") + 2)

    def show_values(self, colors) -> None:
        hex_ = colors[self.token]
        self.swatch.set_color(hex_)
        if not self.hex_edit.hasFocus() and self.hex_edit.text() != hex_:
            self.hex_edit.setText(hex_)
        pairs = _PAIRS.get(self.token, [])
        if not pairs:
            self.ratio_label.setText("—")
            self.ratio_label.setToolTip("No contrast target for this colour")
            self.badge.hide()
            return
        results = [(partner, target, contrast_ratio(hex_, colors[partner])) for partner, target in pairs]
        worst = min(r for _p, _t, r in results)
        failing = [(p, t, r) for p, t, r in results if r < t]
        self.ratio_label.setText(f"{worst:.1f}:1")
        self.ratio_label.setToolTip("\n".join(f"On {p}: {r:.1f}:1 (target {t:g}:1)" for p, t, r in results))
        if failing:
            self.badge.setToolTip("Below the contrast target: " + "; ".join(
                f"{p} {r:.1f}:1, needs {t:g}:1" for p, t, r in failing))
        self.badge.setVisible(bool(failing))


# ------------------------------------------------------------------ the panel

class CustomizePanel(QDockWidget):
    """Docked Look editor. ``saved`` carries the id of what was written: the skin id, or the
    theme id when only a theme was saved."""

    saved = Signal(str)

    def __init__(self, core, parent=None):
        super().__init__("Customize", parent)
        self.core = core
        self.cfg = core.cfg
        self.setObjectName("customizePanel")
        self.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._spaced = SpacedLayouts()
        self._applying = False
        self._advanced = False
        self._banner_mode = ""
        self._thumbs: dict[tuple, QPixmap] = {}
        self._thumb_look: Look | None = None
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
        title = ElidedLabel("Customize", min_chars=6)
        title.setObjectName("customizeTitle")
        lay.addWidget(title, 1)
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

        self.banner = QFrame()
        self.banner.setObjectName("customizeBanner")
        self.banner.setProperty("state", "warn")
        b_lay = self._spaced.add(QVBoxLayout(self.banner), spacing=2, margins=2)
        self.banner_label = QLabel()
        self.banner_label.setObjectName("customizeBannerText")
        self.banner_label.setWordWrap(True)
        self.banner_label.setTextFormat(Qt.PlainText)
        b_lay.addWidget(self.banner_label)
        b_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.banner_save_btn = make_button("Save")
        self.banner_discard_btn = make_button("Discard", "danger")
        self.banner_delete_btn = make_button("Delete", "danger")
        self.banner_keep_btn = make_button("Keep editing")
        for btn in (self.banner_save_btn, self.banner_discard_btn, self.banner_delete_btn,
                    self.banner_keep_btn):
            b_row.addWidget(btn)
        b_row.addStretch(1)
        b_lay.addLayout(b_row)
        self.banner_save_btn.clicked.connect(self._banner_save)
        self.banner_discard_btn.clicked.connect(self._banner_discard)
        self.banner_delete_btn.clicked.connect(self._banner_delete)
        self.banner_keep_btn.clicked.connect(self._banner_keep)
        self.banner.hide()
        col.addWidget(self.banner)

    def _build_elements(self, col: QVBoxLayout) -> None:
        group_label(col, "Elements")
        self.tiles: dict[tuple[str, str], VariantTile] = {}
        for slot in SKIN_SLOTS:
            label = QLabel(SLOT_TITLES.get(slot, slot))
            label.setObjectName("customizeSlotLabel")
            col.addWidget(label)
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
        self.colours_label = group_label(col, "Colours")
        accent_lbl = QLabel("Accent")
        accent_lbl.setObjectName("customizeSlotLabel")
        col.addWidget(accent_lbl)
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

        tint_lbl = QLabel("Background tint")
        tint_lbl.setObjectName("customizeSlotLabel")
        col.addWidget(tint_lbl)
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
        self.advanced_box = QWidget()
        a_lay = self._spaced.add(QVBoxLayout(self.advanced_box), spacing=1, margins=0)
        self.contrast_label = QLabel()
        self.contrast_label.setObjectName("customizeMessage")
        self.contrast_label.setProperty("state", "warn")
        self.contrast_label.setWordWrap(True)
        a_lay.addWidget(self.contrast_label)
        self.token_rows: dict[str, TokenRow] = {}
        for token in PALETTE_TOKENS:
            row_w = TokenRow(self, token, self._spaced)
            self.token_rows[token] = row_w
            a_lay.addWidget(row_w)
        self.advanced_box.hide()
        col.addWidget(self.advanced_box)

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
        skin = self._base.skin
        return skin.name if _is_user(skin.id) else f"My {skin.name}"

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
        for row in self.token_rows.values():
            row.fit_columns()
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
        """The cached thumbnail of a variant in the current look (rendered once per look)."""
        look = current_look()
        if look != self._thumb_look:
            self._thumbs.clear()
            self._thumb_look = look
        key = (slot, variant, dpr)
        pm = self._thumbs.get(key)
        if pm is None:
            pm = render_thumbnail(slot, variant, look, THUMB_W, THUMB_H, dpr)
            self._thumbs[key] = pm
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
        self.advanced_box.setVisible(on)
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
        try:
            skin = user_looks.new_skin(name, self._elements, self._base.skin.shape)
            user_looks.save_skin(skin)
            if palette_changed:
                palette = user_looks.new_palette(name, self._base.palette.dark, self._colors, self._source)
                user_looks.save_palette(palette)
                theme_id = palette.id
        except (OSError, ValueError, user_looks.LookFileError) as exc:
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
                user_looks.export_palette(self._draft_palette(name or self._base.palette.name), path)
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
        start = str(Path.home() / f"{stem}{user_looks.SKIN_EXT}")
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
        self._banner_mode = mode
        base = self._base
        if mode == "delete":
            if _is_user(base.skin.id):
                what = f"the skin “{base.skin.name}”"
            elif _is_user(base.palette.id):
                what = f"the theme “{base.palette.name}”"
            else:
                return
            text = f"Delete {what}? This cannot be undone."
        elif mode == "external":
            text = "The look was changed elsewhere. Your changes here are not saved."
        else:
            text = "You have unsaved changes."
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
        self.banner.hide()

    def _banner_save(self) -> None:
        mode = self._banner_mode
        ok = self.save() if self._can_save() else self.save_as(self.name_edit.text())
        if ok is None:
            return
        self._hide_banner()
        if mode == "close":
            self.hide()

    def _banner_discard(self) -> None:
        mode = self._banner_mode
        self._hide_banner()
        if mode == "external":
            self._load(current_look())
            self._sync()
        else:
            self._discard_and_hide()

    def _banner_keep(self) -> None:
        mode = self._banner_mode
        self._hide_banner()
        if mode == "external":
            self._apply_draft()

    def _banner_delete(self) -> None:
        self._hide_banner()
        self.delete()

    def _discard_and_hide(self) -> None:
        """Drop unsaved changes (back to the saved look) and hide without asking."""
        self._live.stop()
        if self.is_dirty():
            self._load(self._base)
            self._apply_draft()
        self._hide_banner()
        self.hide()

    def closeEvent(self, ev) -> None:  # noqa: N802 - Qt naming
        if self.is_dirty():
            ev.ignore()
            self._show_banner("close")
            return
        self._hide_banner()
        super().closeEvent(ev)

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
        if self._advanced:
            for row in self.token_rows.values():
                row.show_values(self._colors)
            low = sum(1 for row in self.token_rows.values() if row.badge.isVisibleTo(self.advanced_box))
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
            self._scroll_to(self.token_rows[PALETTE_TOKENS[-1]])
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
