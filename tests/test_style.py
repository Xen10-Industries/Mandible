"""The app style (mandible.ui.style.ScaleStyle): check-box and radio indicators are visible on
every surface in every built-in look, with distinct states."""
from __future__ import annotations

import pytest

from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look, current_look, set_look
from mandible.ui.palette_gen import UI_MIN, contrast_ratio

ALL_LOOKS = [Look(BUILTIN_PALETTES[p], BUILTIN_SKINS[s])
             for s in BUILTIN_SKINS for p in BUILTIN_PALETTES]
SURFACES = ("bg.panel", "bg.raised", "bg.inset")
# Where check boxes sit: the QSS surface property, and the soundboard's duck strip.
HOSTS = {"bg.panel": ("surface", "panel"), "bg.raised": ("surface", "raised"),
         "bg.inset": ("surface", "inset"), "duckStrip": ("objectName", "duckStrip")}


@pytest.fixture
def restore_look(qapp):
    before = current_look()
    yield
    set_look(before)


@pytest.mark.parametrize("pal_id", list(BUILTIN_PALETTES))
def test_indicator_tokens_contrast_on_every_surface(pal_id):
    """The unchecked outline and the checked fill reach 3:1 against every surface; the mark
    reaches 3:1 against the checked fill."""
    from mandible.ui.style import INDICATOR_TOKENS

    pal = BUILTIN_PALETTES[pal_id]
    for role in ("border", "on", "hover", "focus"):
        for surface in ("bg.window", *SURFACES):
            ratio = contrast_ratio(pal.color(INDICATOR_TOKENS[role]), pal.color(surface))
            assert ratio >= UI_MIN, (pal_id, role, surface, round(ratio, 2))
    for fill in ("on", "hover"):
        ratio = contrast_ratio(pal.color(INDICATOR_TOKENS["mark"]), pal.color(INDICATOR_TOKENS[fill]))
        assert ratio >= UI_MIN, (pal_id, fill, round(ratio, 2))


def _hex(img, x, y) -> str:
    return img.pixelColor(x, y).name()


def _render(qapp, host_kind, host_value, checked):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QCheckBox, QFrame, QStyle, QStyleOptionButton

    frame = QFrame()
    if host_kind == "surface":
        frame.setProperty("surface", host_value)
    else:
        frame.setObjectName(host_value)
    frame.setAttribute(Qt.WA_DontShowOnScreen)
    frame.resize(480, 48)
    box = QCheckBox("Duck microphone during playback", frame)
    box.setChecked(checked)
    box.move(12, 12)
    box.resize(box.sizeHint())
    frame.show()
    qapp.processEvents()
    img = frame.grab().toImage()
    opt = QStyleOptionButton()
    box.initStyleOption(opt)
    rect = box.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, box)
    rect.translate(box.mapTo(frame, QPoint(0, 0)))
    surface = _hex(img, frame.width() - 10, 24)
    frame.deleteLater()
    return img, rect, surface


@pytest.mark.parametrize("look", ALL_LOOKS, ids=lambda lk: f"{lk.skin.id}-{lk.palette.id}")
def test_checkbox_indicator_visible_on_every_surface(qapp, restore_look, look):
    """Rendered through the real style and stylesheet: each side of the unchecked box has a
    pixel at 3:1 against the surface it sits on; checked looks different (filled)."""
    from PySide6.QtCore import QCoreApplication, QEvent

    from mandible.ui.app import apply_theme

    apply_theme(qapp, look)
    for host, (kind, value) in HOSTS.items():
        img, rect, surface = _render(qapp, kind, value, checked=False)
        expected = look.palette.color("bg.inset" if host == "duckStrip" else host)
        if host != "bg.raised":   # raised is a vertical gradient: measured at the row itself
            assert surface == expected, (host, surface, expected)
        cx, cy = rect.center().x(), rect.center().y()
        sides = {
            "left": [(rect.left() + d, cy) for d in range(3)],
            "right": [(rect.right() - d, cy) for d in range(3)],
            "top": [(cx, rect.top() + d) for d in range(3)],
            "bottom": [(cx, rect.bottom() - d) for d in range(3)],
        }
        for side, points in sides.items():
            best = max(contrast_ratio(_hex(img, x, y), surface) for x, y in points)
            assert best >= UI_MIN, (look.palette.id, host, side, round(best, 2))


        img_on, rect_on, _ = _render(qapp, kind, value, checked=True)
        assert rect_on == rect
        # The checked box is filled with the accent (sampled off the tick, near a corner).
        fill = _hex(img_on, rect.left() + 3, rect.top() + 3)
        assert fill != _hex(img, rect.left() + 3, rect.top() + 3), host
        assert contrast_ratio(fill, surface) >= UI_MIN, (look.palette.id, host, fill)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_indicator_states_are_distinct(qapp, restore_look):
    """Unchecked, hover, checked, partial, focus and disabled each paint differently."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    from mandible.ui.app import apply_theme

    apply_theme(qapp, ALL_LOOKS[0])
    style = qapp.style()
    S = QStyle.StateFlag
    states = {
        "unchecked": S.State_Enabled | S.State_Off,
        "hover": S.State_Enabled | S.State_Off | S.State_MouseOver,
        "checked": S.State_Enabled | S.State_On,
        "partial": S.State_Enabled | S.State_NoChange,
        "focus": S.State_Enabled | S.State_Off | S.State_HasFocus,
        "disabled": S.State_Off,
        "disabled_checked": S.State_On,
    }
    seen = {}
    for name, state in states.items():
        img = QImage(20, 20, QImage.Format.Format_ARGB32)
        img.fill(0)
        opt = QStyleOptionButton()
        opt.rect = QRect(2, 2, 16, 16)
        opt.state = state
        p = QPainter(img)
        style.drawPrimitive(QStyle.PE_IndicatorCheckBox, opt, p, None)
        p.end()
        seen[name] = bytes(img.constBits())
    assert len(set(seen.values())) == len(states), [k for k in states]
