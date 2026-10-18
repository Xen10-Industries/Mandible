"""The immutable Look (Palette + Skin), built-in looks and the current-look bus.

A Palette is a flat set of colour tokens; a Skin chooses one element variant per
slot plus shape tokens. Widgets read ``current_look()`` and repaint on
``look_bus().lookChanged``. Nothing here touches the audio engine.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from .palette_gen import PALETTE_TOKENS

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

__all__ = [
    "PALETTE_TOKENS", "SKIN_SLOTS", "SHAPE_TOKENS", "Palette", "Skin", "Look",
    "BUILTIN_PALETTES", "BUILTIN_SKINS", "LookBus", "space", "font_px",
    "current_look", "set_look", "qpalette", "look_bus", "with_elements", "look_for", "look_from_config",
]

SKIN_SLOTS = ("frame", "switch", "knob", "meter", "panel", "screws", "density")
SHAPE_TOKENS = ("radius.control", "radius.panel", "border.width", "shadow.depth")


def _frozen(mapping: Mapping) -> Mapping:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class Palette:
    id: str
    name: str
    dark: bool
    colors: Mapping[str, str]
    source: dict | None = None  # {"accent", "tint"} for simple-mode palettes

    def __post_init__(self) -> None:
        object.__setattr__(self, "colors", _frozen(self.colors))

    def color(self, token: str) -> str:
        """``#rrggbb`` for ``token``; KeyError for an unknown token."""
        return self.colors[token]

    def __hash__(self) -> int:
        # Mapping fields are not hashable; ids are enough (equal palettes share an id).
        return hash(self.id)


@dataclass(frozen=True)
class Skin:
    id: str
    name: str
    elements: Mapping[str, str]
    shape: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "elements", _frozen(self.elements))
        object.__setattr__(self, "shape", _frozen(self.shape))

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass(frozen=True)
class Look:
    palette: Palette
    skin: Skin

    def __hash__(self) -> int:
        return hash((self.palette.id, self.skin.id))


# ------------------------------------------------------------ built-in palettes
# Ported from the old gui.THEMES: surfaces, text, accent, border and readout colours
# are the originals; the remaining tokens come from derive_colors(accent, tint=<panel>)
# with line.strong lifted so every pair clears the WCAG targets.

_SCARLET = {
    "bg.window": "#0e1017",
    "bg.panel": "#151822",
    "bg.raised": "#1c1f2c",
    "bg.inset": "#10121a",
    "bg.overlay": "#232630",
    "line.subtle": "#262a3a",
    "line.strong": "#656975",
    "focus.ring": "#e11d48",
    "text.primary": "#f1f5f9",
    "text.secondary": "#94a3b8",
    "text.disabled": "#5f636f",
    "text.on_accent": "#ffffff",
    "accent": "#e11d48",
    "accent.hover": "#f43f5e",
    "accent.pressed": "#cc003c",
    "accent.subtle": "#22151b",
    "status.ok": "#4ac06c",
    "status.ok.subtle": "#092c13",
    "status.warn": "#da950b",
    "status.warn.subtle": "#331f00",
    "status.danger": "#ff716b",
    "status.danger.subtle": "#3c1715",
    "meter.low": "#4ac06c",
    "meter.mid": "#da950b",
    "meter.high": "#ff716b",
    "meter.off": "#1c1f29",
    "readout.text": "#38bdf8",
}
_CYAN = {
    "bg.window": "#0b0f19",
    "bg.panel": "#111827",
    "bg.raised": "#1a2337",
    "bg.inset": "#0d1322",
    "bg.overlay": "#222630",
    "line.subtle": "#1f293d",
    "line.strong": "#646975",
    "focus.ring": "#06b6d4",
    "text.primary": "#f8fafc",
    "text.secondary": "#8592a6",
    "text.disabled": "#5e636f",
    "text.on_accent": "#060911",
    "accent": "#06b6d4",
    "accent.hover": "#22d3ee",
    "accent.pressed": "#00a5c1",
    "accent.subtle": "#12202e",
    "status.ok": "#4ac06c",
    "status.ok.subtle": "#092c13",
    "status.warn": "#da950b",
    "status.warn.subtle": "#331f00",
    "status.danger": "#ff716b",
    "status.danger.subtle": "#3c1715",
    "meter.low": "#4ac06c",
    "meter.mid": "#da950b",
    "meter.high": "#ff716b",
    "meter.off": "#1b1f29",
    "readout.text": "#67e8f9",
}
_STEALTH = {
    "bg.window": "#101114",
    "bg.panel": "#17181d",
    "bg.raised": "#20222a",
    "bg.inset": "#121317",
    "bg.overlay": "#242630",
    "line.subtle": "#282a33",
    "line.strong": "#666875",
    "focus.ring": "#10b981",
    "text.primary": "#ffffff",
    "text.secondary": "#8a8e99",
    "text.disabled": "#60626f",
    "text.on_accent": "#070811",
    "accent": "#10b981",
    "accent.hover": "#34d399",
    "accent.pressed": "#00a874",
    "accent.subtle": "#151e19",
    "status.ok": "#4ac06c",
    "status.ok.subtle": "#092c13",
    "status.warn": "#da950b",
    "status.warn.subtle": "#331f00",
    "status.danger": "#ff716b",
    "status.danger.subtle": "#3c1715",
    "meter.low": "#4ac06c",
    "meter.mid": "#da950b",
    "meter.high": "#ff716b",
    "meter.off": "#1d1f29",
    "readout.text": "#34d399",
}
_AMBER = {
    "bg.window": "#12100e",
    "bg.panel": "#1c1917",
    "bg.raised": "#26211e",
    "bg.inset": "#0f0d0c",
    "bg.overlay": "#2e241d",
    "line.subtle": "#38322e",
    "line.strong": "#766a60",
    "focus.ring": "#f59e0b",
    "text.primary": "#fafaf9",
    "text.secondary": "#a8a29e",
    "text.disabled": "#6d6158",
    "text.on_accent": "#0f0703",
    "accent": "#d97706",
    "accent.hover": "#f59e0b",
    "accent.pressed": "#c46a00",
    "accent.subtle": "#271c12",
    "status.ok": "#4ac06c",
    "status.ok.subtle": "#092c13",
    "status.warn": "#da950b",
    "status.warn.subtle": "#331f00",
    "status.danger": "#ff716b",
    "status.danger.subtle": "#3c1715",
    "meter.low": "#4ac06c",
    "meter.mid": "#da950b",
    "meter.high": "#ff716b",
    "meter.off": "#271d16",
    "readout.text": "#fbbf24",
}

BUILTIN_PALETTES: dict[str, Palette] = {
    "scarlet": Palette("scarlet", "Scarlet", True, _SCARLET),
    "cyan": Palette("cyan", "Cyan", True, _CYAN),
    "stealth": Palette("stealth", "Stealth", True, _STEALTH),
    "amber": Palette("amber", "Amber", True, _AMBER),
}

# --------------------------------------------------------------- built-in skins

# Shape tokens per skin (radius.control, radius.panel in px; shadow.depth 0-2).
_SHAPES: dict[str, dict[str, float]] = {
    "skeuomorphic": {"radius.control": 4, "radius.panel": 6, "border.width": 1, "shadow.depth": 2},
    # Vintage: tight 3 px corners (the old console character), not rounded-modern.
    "vintage": {"radius.control": 3, "radius.panel": 3, "border.width": 1, "shadow.depth": 1},
    "minimal": {"radius.control": 8, "radius.panel": 10, "border.width": 1, "shadow.depth": 0},
}

BUILTIN_SKINS: dict[str, Skin] = {
    "skeuomorphic": Skin("skeuomorphic", "Skeuomorphic", {
        "frame": "metal_rack", "switch": "bat_toggle", "knob": "machined",
        "meter": "led_segments", "panel": "brushed", "screws": "corners_only",
        "density": "comfortable"}, _SHAPES["skeuomorphic"]),
    "vintage": Skin("vintage", "Vintage", {
        "frame": "wood_cheeks", "switch": "rocker", "knob": "vintage_bakelite",
        "meter": "led_segments", "panel": "lacquer", "screws": "corners_only",
        "density": "comfortable"}, _SHAPES["vintage"]),
    "minimal": Skin("minimal", "Minimal", {
        "frame": "frameless", "switch": "pill", "knob": "flat_ring",
        "meter": "smooth_bar", "panel": "flat", "screws": "none",
        "density": "compact"}, _SHAPES["minimal"]),
}

# ---------------------------------------------------------- current look + bus

_DEFAULT_LOOK = Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"])
_current: Look = _DEFAULT_LOOK


class LookBus(QObject):
    """Carries ``lookChanged`` so custom-painted widgets can ``update()``."""

    lookChanged = Signal()


_bus: LookBus | None = None


def look_bus() -> LookBus:
    global _bus
    if _bus is None:
        _bus = LookBus()
    return _bus


def current_look() -> Look:
    return _current


_PALETTE_ROLES = (
    ("Window", "bg.window"), ("WindowText", "text.primary"), ("Base", "bg.inset"),
    ("AlternateBase", "bg.panel"), ("Text", "text.primary"), ("Button", "bg.panel"),
    ("ButtonText", "text.primary"), ("Highlight", "accent"),
    ("HighlightedText", "text.on_accent"), ("ToolTipBase", "bg.raised"),
    ("ToolTipText", "text.primary"), ("PlaceholderText", "text.disabled"),
)


def qpalette(look: Look):
    """The native ``QPalette`` for ``look`` (what Fusion paints with where no QSS rule applies)."""
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    for role, token in _PALETTE_ROLES:
        pal.setColor(getattr(QPalette, role), QColor(look.palette.color(token)))
    return pal


def set_look(look: Look, app: "QApplication | None" = None) -> None:
    """Make ``look`` current, apply its stylesheet and native palette to the app, then
    emit ``lookChanged``.

    The stylesheet is built before anything changes, so a failing build leaves the
    previous look, stylesheet and listeners untouched.
    """
    global _current
    from PySide6.QtWidgets import QApplication

    from .stylesheet import build_qss

    qss = build_qss(look)
    _current = look
    app = app or QApplication.instance()
    if app is not None:
        app.setStyleSheet(qss)
        app.setPalette(qpalette(look))
    look_bus().lookChanged.emit()


# ------------------------------------------------------ config ids -> Look

def with_elements(look: Look, **overrides: str) -> Look:
    """``look`` with some skin element slots replaced; the skin keeps its id and name."""
    if all(look.skin.elements.get(slot) == variant for slot, variant in overrides.items()):
        return look
    skin = dataclasses.replace(look.skin, elements={**look.skin.elements, **overrides})
    return Look(look.palette, skin)


def look_for(theme: str, skin: str, frame: str = "auto", switch_style: str | None = None) -> Look:
    """The Look for config ids: a built-in id or a ``user:`` id of a saved user theme/skin.
    Unknown ids fall back to ``scarlet`` / ``skeuomorphic``.

    ``frame`` and ``switch_style`` are the old ``chassis_frame`` / ``switch_style`` settings
    (Task 18 migrates them into user skins): a frame other than ``"auto"`` overrides the
    skin's frame; the switch style only ever applied to the skeuomorphic skin, so it
    overrides the switch there and is ignored elsewhere, as before.
    """
    from .elements import registry

    palette = BUILTIN_PALETTES.get(theme)
    if palette is None and isinstance(theme, str) and theme.startswith("user:"):
        from . import user_looks

        palette = user_looks.all_palettes().get(theme)
    base = BUILTIN_SKINS.get(skin)
    if base is None and isinstance(skin, str) and skin.startswith("user:"):
        from . import user_looks

        base = user_looks.all_skins().get(skin)
    palette = palette or BUILTIN_PALETTES["scarlet"]
    base = base or BUILTIN_SKINS["skeuomorphic"]
    overrides: dict[str, str] = {}
    if frame in registry.variants("frame"):
        overrides["frame"] = frame
    if base.id == "skeuomorphic" and switch_style in registry.variants("switch"):
        overrides["switch"] = switch_style
    return with_elements(Look(palette, base), **overrides)


def look_from_config(cfg) -> Look:
    """The Look an ``AppConfig`` selects (``theme``, ``ui_skin``, ``chassis_frame``, ``switch_style``)."""
    return look_for(getattr(cfg, "theme", "scarlet"), getattr(cfg, "ui_skin", "skeuomorphic"),
                    getattr(cfg, "chassis_frame", "auto"), getattr(cfg, "switch_style", None))


# ------------------------------------------------------------- spacing and type

_SPACE = (4, 8, 12, 16, 24)
_COMPACT = {16: 12, 24: 16}
_FONT_PX = {"small": 11, "body": 13, "title": 16, "readout": 11}


def space(step: int) -> int:
    """Spacing scale step 1..5 -> 4/8/12/16/24 px (compact density: 16 -> 12, 24 -> 16)."""
    if not 1 <= step <= len(_SPACE):
        raise ValueError(f"space step must be 1..{len(_SPACE)}, got {step!r}")
    px = _SPACE[step - 1]
    if _current.skin.elements.get("density") == "compact":
        px = _COMPACT.get(px, px)
    return px


def font_px(role: str) -> int:
    """Pixel size for a type role (small, body, title, readout) at 100 % scale."""
    return _FONT_PX[role]
