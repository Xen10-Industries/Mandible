"""Look model: built-in palettes/skins, element registry, spacing and set_look."""
from __future__ import annotations

import dataclasses

import pytest

from mandible.ui import look as look_mod
from mandible.ui.elements import registry
from mandible.ui.look import (
    BUILTIN_PALETTES,
    BUILTIN_SKINS,
    PALETTE_TOKENS,
    SHAPE_TOKENS,
    SKIN_SLOTS,
    Look,
    Skin,
    current_look,
    font_px,
    look_bus,
    set_look,
    space,
)
from mandible.ui import palette_gen


@pytest.fixture
def restore_look():
    before = current_look()
    yield
    set_look(before)


def test_palette_tokens_are_the_palette_gen_tuple():
    assert PALETTE_TOKENS is palette_gen.PALETTE_TOKENS
    assert len(PALETTE_TOKENS) == 27


def test_builtin_palettes_ids_names_and_contrast():
    assert list(BUILTIN_PALETTES) == ["scarlet", "cyan", "stealth", "amber"]
    assert [p.name for p in BUILTIN_PALETTES.values()] == ["Scarlet", "Cyan", "Stealth", "Amber"]
    for pid, p in BUILTIN_PALETTES.items():
        assert p.id == pid
        assert "Focusrite" not in p.name
        assert set(p.colors) == set(PALETTE_TOKENS)
        assert palette_gen.check_colors(p.colors) == [], pid


def test_palette_color_lookup():
    p = BUILTIN_PALETTES["scarlet"]
    assert p.color("accent") == p.colors["accent"]
    with pytest.raises(KeyError):
        p.color("accent.bogus")


def test_look_objects_are_immutable():
    p = BUILTIN_PALETTES["scarlet"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.name = "x"
    with pytest.raises(TypeError):
        p.colors["accent"] = "#000000"
    s = BUILTIN_SKINS["minimal"]
    with pytest.raises(TypeError):
        s.elements["knob"] = "machined"


def test_builtin_skins_match_spec_table():
    assert list(BUILTIN_SKINS) == ["skeuomorphic", "vintage", "minimal"]
    assert dict(BUILTIN_SKINS["skeuomorphic"].elements) == {
        "frame": "metal_rack", "switch": "bat_toggle", "knob": "machined",
        "meter": "led_segments", "panel": "brushed", "screws": "corners_only",
        "density": "comfortable"}
    assert dict(BUILTIN_SKINS["vintage"].elements) == {
        "frame": "wood_cheeks", "switch": "rocker", "knob": "vintage_bakelite",
        "meter": "led_segments", "panel": "lacquer", "screws": "corners_only",
        "density": "comfortable"}
    assert dict(BUILTIN_SKINS["minimal"].elements) == {
        "frame": "frameless", "switch": "pill", "knob": "flat_ring",
        "meter": "smooth_bar", "panel": "flat", "screws": "none",
        "density": "compact"}


def test_builtin_skins_use_registered_variants_and_have_shape_tokens():
    for skin in BUILTIN_SKINS.values():
        assert tuple(skin.elements) == SKIN_SLOTS
        assert set(skin.shape) == set(SHAPE_TOKENS)
        for slot, variant in skin.elements.items():
            assert variant in registry.variants(slot)
            assert registry.get(slot, variant) is not None
        resolved, notices = registry.resolve(skin.elements)
        assert resolved == dict(skin.elements) and notices == []


def test_registry_covers_every_spec_variant():
    expected = {
        "frame": ["metal_rack", "wood_cheeks", "frameless"],
        "switch": ["bat_toggle", "rocker", "pill"],
        "knob": ["machined", "vintage_bakelite", "flat_ring"],
        "meter": ["led_segments", "smooth_bar"],
        "panel": ["brushed", "lacquer", "flat"],
        "screws": ["corners_only", "none"],
        "density": ["compact", "comfortable"],
    }
    for slot, ids in expected.items():
        assert registry.variants(slot) == ids
    assert registry.label("frame", "wood_cheeks") == "Wood cheeks"
    assert registry.label("switch", "bat_toggle") == "Bat toggle"
    assert registry.DEFAULTS == {
        "frame": "metal_rack", "switch": "bat_toggle", "knob": "machined",
        "meter": "led_segments", "panel": "brushed", "screws": "corners_only",
        "density": "comfortable"}


def test_register_adds_a_variant_to_the_slot():
    class Dummy:
        pass

    registry.register("screws", "test_only", Dummy, "Test only")
    try:
        assert "test_only" in registry.variants("screws")
        assert registry.get("screws", "test_only") is Dummy
        assert registry.label("screws", "test_only") == "Test only"
    finally:
        registry._VARIANTS["screws"].pop("test_only")


def test_resolve_unknown_variant_falls_back_with_notice():
    resolved, notices = registry.resolve({**BUILTIN_SKINS["vintage"].elements, "switch": "laser"})
    assert resolved["switch"] == registry.DEFAULTS["switch"]
    assert resolved["knob"] == "vintage_bakelite"
    assert notices == ["switch: 'laser' not available, using bat_toggle"]


def test_resolve_partial_and_unknown_slot():
    resolved, notices = registry.resolve({"switch": "laser"})
    assert resolved == {**registry.DEFAULTS}
    assert len(notices) == 1 and "laser" in notices[0]
    resolved, notices = registry.resolve({"hologram": "x"})
    assert resolved == registry.DEFAULTS
    assert len(notices) == 1 and "hologram" in notices[0]


def test_get_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        registry.get("switch", "laser")


def _look(density: str) -> Look:
    skin = BUILTIN_SKINS["skeuomorphic"]
    elements = {**skin.elements, "density": density}
    return Look(BUILTIN_PALETTES["scarlet"], dataclasses.replace(skin, elements=elements))


def test_space_scale_and_density(qapp, restore_look):
    set_look(_look("comfortable"))
    assert [space(i) for i in range(1, 6)] == [4, 8, 12, 16, 24]
    set_look(_look("compact"))
    assert [space(i) for i in range(1, 6)] == [4, 8, 12, 12, 16]
    with pytest.raises(ValueError):
        space(0)
    with pytest.raises(ValueError):
        space(6)


def test_font_px_roles():
    assert [font_px(r) for r in ("small", "body", "title", "readout")] == [11, 13, 16, 11]
    with pytest.raises(KeyError):
        font_px("huge")


def test_default_look_is_skeuomorphic_scarlet():
    look = look_mod._DEFAULT_LOOK
    assert look.palette.id == "scarlet" and look.skin.id == "skeuomorphic"


def test_set_look_emits_once_and_applies_stylesheet(qapp, restore_look, monkeypatch):
    calls = []
    monkeypatch.setattr("mandible.ui.stylesheet.build_qss",
                        lambda look: calls.append(look) or "/* qss */")
    seen = []

    def on_change():
        seen.append(current_look())

    look_bus().lookChanged.connect(on_change)
    try:
        new = Look(BUILTIN_PALETTES["amber"], BUILTIN_SKINS["vintage"])
        set_look(new)
        assert current_look() is new
        assert seen == [new]
        assert calls == [new]
        assert qapp.styleSheet() == "/* qss */"
    finally:
        look_bus().lookChanged.disconnect(on_change)


@pytest.mark.parametrize("palette_id", ["scarlet", "cyan", "stealth", "amber"])
def test_set_look_alone_syncs_the_native_palette(qapp, restore_look, palette_id):
    """No entry point can bypass the QPalette sync: set_look itself sets it (no apply_theme)."""
    from PySide6.QtGui import QPalette

    look = Look(BUILTIN_PALETTES[palette_id], BUILTIN_SKINS["minimal"])
    set_look(look)
    pal = qapp.palette()
    c = look.palette.color
    assert pal.color(QPalette.Window).name() == c("bg.window")
    assert pal.color(QPalette.WindowText).name() == c("text.primary")
    assert pal.color(QPalette.Text).name() == c("text.primary")
    assert pal.color(QPalette.Highlight).name() == c("accent")
    assert pal.color(QPalette.HighlightedText).name() == c("text.on_accent")
    assert pal.color(QPalette.Base).name() == c("bg.inset")


def test_set_look_keeps_the_native_palette_following_later_looks(qapp, restore_look):
    from PySide6.QtGui import QPalette

    set_look(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["minimal"]))
    first = qapp.palette().color(QPalette.Window).name()
    set_look(Look(BUILTIN_PALETTES["cyan"], BUILTIN_SKINS["minimal"]))
    assert qapp.palette().color(QPalette.Window).name() == BUILTIN_PALETTES["cyan"].color("bg.window")
    assert first == BUILTIN_PALETTES["scarlet"].color("bg.window") != qapp.palette().color(QPalette.Window).name()


def test_set_look_without_app_does_not_fail(qapp, restore_look, monkeypatch):
    # Explicit app=None path with no QApplication instance must still swap + emit.
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
    seen = []

    def on_change():
        seen.append(1)

    look_bus().lookChanged.connect(on_change)
    try:
        set_look(Look(BUILTIN_PALETTES["cyan"], BUILTIN_SKINS["minimal"]))
        assert seen == [1] and current_look().palette.id == "cyan"
    finally:
        look_bus().lookChanged.disconnect(on_change)


def test_skin_dataclass_shape():
    s = Skin("x", "X", {"frame": "metal_rack"}, {"radius.control": 4.0})
    assert s.id == "x"


def test_palette_skin_look_are_hashable_by_id():
    pal, skin = BUILTIN_PALETTES["amber"], BUILTIN_SKINS["vintage"]
    look = Look(pal, skin)
    assert hash(pal) == hash(BUILTIN_PALETTES["amber"])
    assert hash(skin) == hash(BUILTIN_SKINS["vintage"])
    assert hash(look) == hash(Look(pal, skin)) == hash((pal.id, skin.id))
    assert len({look, Look(pal, skin)}) == 1
    assert {pal: 1}[BUILTIN_PALETTES["amber"]] == 1
    # Same id but different content: still distinct keys (hash collides, eq separates).
    edited = dataclasses.replace(pal, colors={**pal.colors, "accent": "#123456"})
    assert hash(edited) == hash(pal) and edited != pal
    assert len({pal, edited}) == 2


def test_set_look_is_exception_safe(qapp, restore_look, monkeypatch):
    good = Look(BUILTIN_PALETTES["cyan"], BUILTIN_SKINS["minimal"])
    set_look(good)
    sheet_before = qapp.styleSheet()
    seen = []

    def on_change():
        seen.append(1)

    def boom(look):
        raise RuntimeError("bad look")

    look_bus().lookChanged.connect(on_change)
    try:
        monkeypatch.setattr("mandible.ui.stylesheet.build_qss", boom)
        with pytest.raises(RuntimeError):
            set_look(Look(BUILTIN_PALETTES["amber"], BUILTIN_SKINS["vintage"]))
        assert current_look() is good
        assert qapp.styleSheet() == sheet_before
        assert seen == []
    finally:
        look_bus().lookChanged.disconnect(on_change)


@pytest.mark.parametrize("bad", [["laser"], {"a": 1}, 3, None, 1.5])
def test_resolve_never_raises_for_non_string_variants(bad):
    # A hostile JSON file can put an unhashable value (list/dict) where a variant id goes.
    resolved, notices = registry.resolve({"switch": bad})
    assert resolved == registry.DEFAULTS
    assert len(notices) == 1 and notices[0].startswith("switch:")
