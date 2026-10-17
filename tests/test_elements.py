"""Element variants: every registered variant paints, switches reflect their state."""
from __future__ import annotations

import pytest

from mandible.ui import look as look_mod
from mandible.ui.elements import registry
from mandible.ui.elements.base import Element, ElementState

PAINTED_SLOTS = ("frame", "switch", "knob", "meter", "panel", "screws")
CASES = [(slot, variant) for slot in PAINTED_SLOTS for variant in registry.variants(slot)]
PALETTES = sorted(look_mod.BUILTIN_PALETTES)
SKIN = look_mod.BUILTIN_SKINS["skeuomorphic"]

# Paints nothing by design: the "no screws" variant.
EMPTY_BY_DESIGN = {("screws", "none")}


def render(slot, variant, palette_id, state, size=64):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    look = look_mod.Look(look_mod.BUILTIN_PALETTES[palette_id], SKIN)
    element = registry.get(slot, variant)()
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    element.paint(p, QRectF(0, 0, size, size), state, look)
    p.end()
    return img


def is_blank(img) -> bool:
    return all(img.pixel(x, y) >> 24 == 0 for x in range(img.width()) for y in range(img.height()))


def test_every_variant_id_has_a_class_and_label(qapp):
    assert CASES, "no variants registered"
    for slot, variant in CASES:
        cls = registry.get(slot, variant)
        assert issubclass(cls, Element), (slot, variant)
        assert registry.label(slot, variant)
    assert registry.label("meter", "led_segments") == "LED segments"


@pytest.mark.parametrize("palette_id", PALETTES)
@pytest.mark.parametrize("slot,variant", CASES)
@pytest.mark.parametrize("name,state", [
    ("off", ElementState(value=0.0)),
    ("on", ElementState(active=True, value=0.7, peak=0.9)),
    ("disabled", ElementState(enabled=False, value=0.5)),
])
def test_variant_paints_in_every_state(qapp, slot, variant, palette_id, name, state):
    img = render(slot, variant, palette_id, state)
    if (slot, variant) in EMPTY_BY_DESIGN:
        assert is_blank(img)
    else:
        assert not is_blank(img), f"{slot}/{variant}/{palette_id}/{name} painted nothing"


@pytest.mark.parametrize("palette_id", PALETTES)
@pytest.mark.parametrize("variant", registry.variants("switch"))
def test_switch_differs_between_off_and_on(qapp, variant, palette_id):
    off = render("switch", variant, palette_id, ElementState(active=False))
    on = render("switch", variant, palette_id, ElementState(active=True))
    assert off != on


@pytest.mark.parametrize("variant", registry.variants("knob"))
def test_knob_differs_with_value(qapp, variant):
    low = render("knob", variant, "scarlet", ElementState(value=0.1))
    high = render("knob", variant, "scarlet", ElementState(value=0.9))
    assert low != high


@pytest.mark.parametrize("variant", registry.variants("meter"))
def test_meter_differs_with_level(qapp, variant):
    low = render("meter", variant, "scarlet", ElementState(value=0.1))
    high = render("meter", variant, "scarlet", ElementState(value=0.9))
    assert low != high


def test_disabled_is_dimmer_than_enabled(qapp):
    on = render("switch", "bat_toggle", "scarlet", ElementState(active=True))
    off = render("switch", "bat_toggle", "scarlet", ElementState(active=True, enabled=False))
    assert on != off


def test_size_hints_match_todays_widgets(qapp):
    from mandible.ui.elements.knobs import Machined
    from mandible.ui.elements.switches import BatToggle, Pill, Rocker

    look = look_mod.current_look()
    assert BatToggle().size_hint(look).width() == 68 and BatToggle().size_hint(look).height() == 24
    assert BatToggle(compact=True).size_hint(look).width() == 50
    assert BatToggle(vertical=True).size_hint(look).width() == 46
    assert BatToggle(vertical=True).size_hint(look).height() == 28
    assert Rocker().size_hint(look).width() == 68
    assert Pill().size_hint(look).width() == 68
    assert (Machined().size_hint(look).width(), Machined().size_hint(look).height()) == (54, 62)
    assert (Machined(compact=True).size_hint(look).width(),
            Machined(compact=True).size_hint(look).height()) == (64, 58)


def test_density_placeholders_are_not_painted():
    assert registry.variants("density") == ["compact", "comfortable"]
    assert "density" not in PAINTED_SLOTS


def test_resolve_frame_follows_the_skin_unless_overridden():
    from mandible.ui.elements.frames import resolve_frame

    vintage = look_mod.Look(look_mod.BUILTIN_PALETTES["scarlet"], look_mod.BUILTIN_SKINS["vintage"])
    minimal = look_mod.Look(look_mod.BUILTIN_PALETTES["scarlet"], look_mod.BUILTIN_SKINS["minimal"])
    assert resolve_frame(vintage) == "wood_cheeks"
    assert resolve_frame(minimal, "auto") == "frameless"
    assert resolve_frame(look_mod.Look(look_mod.BUILTIN_PALETTES["scarlet"], SKIN)) == "metal_rack"
    assert resolve_frame(minimal, "metal_rack") == "metal_rack"
    assert resolve_frame(minimal, "bogus") == "frameless"


def test_frame_margins_match_the_old_chassis():
    from mandible.ui.elements.frames import Frameless, MetalRack, WoodCheeks

    look = look_mod.current_look()
    assert MetalRack().content_margins(look) == (28, 14, 28, 14)
    assert WoodCheeks().content_margins(look) == (28, 14, 28, 18)
    assert Frameless().content_margins(look) == (2, 2, 2, 2)


def test_flat_panel_is_one_flat_colour_and_brushed_is_not(qapp):
    flat = render("panel", "flat", "scarlet", ElementState())
    brushed = render("panel", "brushed", "scarlet", ElementState())
    inner = {flat.pixel(32, y) for y in range(8, 56)}
    assert len(inner) == 1
    assert len({brushed.pixel(32, y) for y in range(8, 56)}) > 1
    assert flat != brushed
