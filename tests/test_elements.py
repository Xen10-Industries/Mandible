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


def render(slot, variant, palette_id, state, size=64, element=None, width=None):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    look = look_mod.Look(look_mod.BUILTIN_PALETTES[palette_id], SKIN)
    element = element if element is not None else registry.get(slot, variant)()
    img = QImage(width or size, size, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    element.paint(p, QRectF(0, 0, width or size, size), state, look)
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
    assert BatToggle().size_hint(look).width() == 72 and BatToggle().size_hint(look).height() == 24
    assert BatToggle(compact=True).size_hint(look).width() == 50
    assert BatToggle(vertical=True).size_hint(look).width() == 46
    assert BatToggle(vertical=True).size_hint(look).height() == 28
    assert Rocker().size_hint(look).width() == 72
    assert Pill().size_hint(look).width() == 72
    assert (Machined().size_hint(look).width(), Machined().size_hint(look).height()) == (56, 64)
    assert (Machined(compact=True).size_hint(look).width(),
            Machined(compact=True).size_hint(look).height()) == (64, 62)


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
    """The metal rack's (Task 12), wood cheeks' (Task 13) and frameless (Task 14) margins sit
    on the spacing scale; frameless content is flush with its hairline outline."""
    from mandible.ui.elements.frames import Frameless, MetalRack, WoodCheeks

    look = look_mod.current_look()
    assert MetalRack().content_margins(look) == (24, 12, 24, 12)
    assert WoodCheeks().content_margins(look) == (24, 12, 24, 16)
    assert Frameless().content_margins(look) == (0, 0, 0, 0)


def test_flat_panel_is_one_flat_colour_and_brushed_is_not(qapp):
    flat = render("panel", "flat", "scarlet", ElementState())
    brushed = render("panel", "brushed", "scarlet", ElementState())
    inner = {flat.pixel(32, y) for y in range(8, 56)}
    assert len(inner) == 1
    assert len({brushed.pixel(32, y) for y in range(8, 56)}) > 1
    assert flat != brushed


# ----------------------------------------------- ctor variants Task 7 will construct

def _ctor_cases():
    from mandible.ui.elements.knobs import FlatRing, Machined, VintageBakelite
    from mandible.ui.elements.meters import LedSegments, SmoothBar
    from mandible.ui.elements.switches import BatToggle, Pill, Rocker

    cases = []
    for cls in (BatToggle, Rocker, Pill):
        for kw in ({"compact": True}, {"vertical": True}, {"compact": True, "vertical": True}):
            cases.append(("switch", f"{cls.__name__}{kw}", lambda cls=cls, kw=kw: cls(**kw)))
    for cls in (Machined, VintageBakelite, FlatRing):
        cases.append(("knob", f"{cls.__name__}(compact)", lambda cls=cls: cls(compact=True)))
    cases += [
        ("meter", "LedSegments.main", LedSegments.main),
        ("meter", "LedSegments.thin", LedSegments.thin),
        ("meter", "LedSegments.prepost", LedSegments.prepost),
        ("meter", "SmoothBar(thin)", lambda: SmoothBar(corner=2.5, size=(80, 8))),
    ]
    return cases


CTOR_CASES = _ctor_cases()
CTOR_IDS = [c[1] for c in CTOR_CASES]


@pytest.mark.parametrize("slot,name,factory", CTOR_CASES, ids=CTOR_IDS)
@pytest.mark.parametrize("state", [
    ElementState(value=0.0),
    ElementState(active=True, value=0.7, peak=0.9, label="Gain", readout="+3 dB"),
    ElementState(enabled=False, value=0.5),
], ids=["off", "on", "disabled"])
def test_ctor_variants_paint(qapp, slot, name, factory, state):
    size, width = (30, 80) if slot == "meter" else (64, None)
    img = render(slot, None, "scarlet", state, size=size, element=factory(), width=width)
    assert not is_blank(img), name


@pytest.mark.parametrize("slot,name,factory",
                         [c for c in CTOR_CASES if c[0] == "switch"], ids=lambda v: v if isinstance(v, str) else "")
def test_ctor_switches_differ_between_off_and_on(qapp, slot, name, factory):
    off = render(slot, None, "scarlet", ElementState(active=False), element=factory())
    on = render(slot, None, "scarlet", ElementState(active=True), element=factory())
    assert off != on, name


@pytest.mark.parametrize("slot,name,factory",
                         [c for c in CTOR_CASES if c[0] in ("knob", "meter")], ids=lambda v: v if isinstance(v, str) else "")
def test_ctor_knobs_and_meters_differ_with_value(qapp, slot, name, factory):
    size, width = (30, 80) if slot == "meter" else (64, None)
    low = render(slot, None, "scarlet", ElementState(value=0.1), size=size, element=factory(), width=width)
    high = render(slot, None, "scarlet", ElementState(value=0.9), size=size, element=factory(), width=width)
    assert low != high, name


@pytest.mark.parametrize("variant", registry.variants("knob"))
@pytest.mark.parametrize("compact", [False, True])
def test_knob_label_and_readout_are_painted(qapp, variant, compact):
    cls = registry.get("knob", variant)
    bare = render("knob", variant, "scarlet", ElementState(value=0.5), element=cls(compact=compact))
    label = render("knob", variant, "scarlet", ElementState(value=0.5, label="Gain"),
                   element=cls(compact=compact))
    readout = render("knob", variant, "scarlet", ElementState(value=0.5, readout="+3.0 dB"),
                     element=cls(compact=compact))
    both = render("knob", variant, "scarlet",
                  ElementState(value=0.5, label="Gain", readout="+3.0 dB"), element=cls(compact=compact))
    assert bare != label and bare != readout and label != both and readout != both


def test_machined_readout_draws_an_lcd_box(qapp):
    from mandible.ui.elements.knobs import Machined

    bare = render("knob", None, "scarlet", ElementState(value=0.5), element=Machined())
    with_box = render("knob", None, "scarlet", ElementState(value=0.5, readout=" "), element=Machined())
    assert bare != with_box


def _lit_segments(img, meter, look):
    """Indices of segments whose centre pixel is the peak-marker colour (text.primary)."""
    from PySide6.QtGui import QColor

    n = meter.segments
    w, h = img.width(), img.height()
    seg_w = max(meter.min_seg_w, (w - (n - 1) * meter.gap) / n)
    want = QColor(look.palette.color("text.primary")).rgb()
    out = []
    for i in range(n):
        x = int(i * (seg_w + meter.gap) + seg_w / 2)
        if img.pixelColor(x, h // 2).rgb() == want:
            out.append(i)
    return out


def _paint_meter(meter, peak, width=200, height=13):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    look = look_mod.Look(look_mod.BUILTIN_PALETTES["scarlet"], SKIN)
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    meter.paint(p, QRectF(0, 0, width, height), ElementState(value=0.0, peak=peak), look)
    p.end()
    return img, look


@pytest.mark.parametrize("preset,segments,offset,tiny_lit", [
    ("main", 26, 0, [0]),       # source LevelMeter: round(pk * n), no -1
    ("thin", 18, -1, []),       # source ThinLevelMeter / PluginPrePostMeter: round(pk * n) - 1
    ("prepost", 14, -1, []),
])
def test_led_peak_marker_matches_each_source_meter(qapp, preset, segments, offset, tiny_lit):
    from mandible.ui.elements.meters import LedSegments

    meter = getattr(LedSegments, preset)()
    assert (meter.segments, meter.peak_offset) == (segments, offset)
    for peak in (0.25, 0.5, 0.9):
        img, look = _paint_meter(meter, peak)
        expected = round(peak * segments) + offset
        assert _lit_segments(img, meter, look) == [expected], (preset, peak)
    # A tiny peak: the main meter lights segment 0, the others draw nothing.
    img, look = _paint_meter(meter, 0.01)
    assert _lit_segments(img, meter, look) == tiny_lit
    # Full scale: the main meter's offset 0 puts the marker past the ladder; the others hit the top.
    img, look = _paint_meter(meter, 1.0)
    assert _lit_segments(img, meter, look) == ([] if offset == 0 else [segments - 1])
    # No peak: no marker.
    img, look = _paint_meter(meter, None)
    assert _lit_segments(img, meter, look) == []


def test_smooth_bar_peak_marker_position(qapp):
    from mandible.ui.elements.meters import SmoothBar

    img, look = _paint_meter(SmoothBar(), 0.5, width=200, height=13)
    from PySide6.QtGui import QColor
    want = QColor(look.palette.color("text.primary")).rgb()
    assert img.pixelColor(101, 6).rgb() == want        # marker is 2 px wide at w * 0.5
    assert img.pixelColor(60, 6).rgb() != want
    none_img, _ = _paint_meter(SmoothBar(), None, width=200, height=13)
    assert none_img.pixelColor(101, 6).rgb() != want


# ----------------------------------------------- meter presets and inactive rows (Task 7)

@pytest.mark.parametrize("variant", registry.variants("meter"))
def test_every_meter_variant_offers_the_three_presets(qapp, variant):
    cls = registry.get("meter", variant)
    look = look_mod.current_look()
    sizes = {name: getattr(cls, name)().size_hint(look) for name in ("main", "thin", "prepost")}
    assert sizes["main"].height() == 13 and sizes["thin"].height() == 8
    for name in ("main", "thin", "prepost"):
        assert isinstance(getattr(cls, name)(), cls)


def _segment_centres(meter, img):
    n = meter.segments
    w, h = img.width(), img.height()
    seg_w = max(meter.min_seg_w, (w - (n - 1) * meter.gap) / n)
    return [img.pixelColor(int(i * (seg_w + meter.gap) + seg_w / 2), h // 2) for i in range(n)]


def test_inactive_led_row_is_unlit_meter_off(qapp):
    """A disabled row (a bypassed plugin's POST meter) shows flat meter.off, no level, no peak."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from mandible.ui.elements.meters import LedSegments

    meter = LedSegments.prepost()
    look = look_mod.Look(look_mod.BUILTIN_PALETTES["scarlet"], SKIN)

    def paint(state):
        img = QImage(200, 9, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        meter.paint(p, QRectF(0, 0, 200, 9), state, look)
        p.end()
        return _segment_centres(meter, img)

    off = QColor(look.palette.color("meter.off"))
    disabled = paint(ElementState(enabled=False, value=1.0, peak=0.5))
    assert len({c.rgb() for c in disabled}) == 1          # one flat colour, no zones/level/peak
    c = disabled[0]
    assert abs(c.red() - off.red()) <= 2 and abs(c.green() - off.green()) <= 2
    assert abs(c.blue() - off.blue()) <= 2
    enabled_idle = paint(ElementState(value=0.0))
    assert len({c.rgb() for c in enabled_idle}) == 3      # dim green / amber / red zone tints


def test_inactive_smooth_bar_row_draws_only_the_track(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from mandible.ui.elements.meters import SmoothBar

    look = look_mod.Look(look_mod.BUILTIN_PALETTES["scarlet"], SKIN)

    def paint(state):
        img = QImage(200, 7, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        SmoothBar.prepost().paint(p, QRectF(0, 0, 200, 7), state, look)
        p.end()
        return img

    assert paint(ElementState(enabled=False, value=0.9, peak=0.5)) == \
        paint(ElementState(enabled=False, value=0.0))
    assert paint(ElementState(value=0.9)) != paint(ElementState(value=0.0))


def test_metal_rack_keeps_only_its_four_corner_screws(qapp, monkeypatch):
    """The skeuomorphic frame paints exactly four screws, through the skin's screws element
    (one per corner, none with ``screws: none``)."""
    from mandible.ui.elements import screws
    from mandible.ui.elements.frames import MetalRack

    painted = []
    real = screws.CornersOnly.draw
    monkeypatch.setattr(screws.CornersOnly, "draw",
                        lambda self, p, w, h, st, lk: (painted.append((w, h)), real(self, p, w, h, st, lk)))
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(0)
    frame = MetalRack()
    for skin, want in (("skeuomorphic", 4), ("minimal", 0)):
        painted.clear()
        look = look_mod.Look(look_mod.BUILTIN_PALETTES["scarlet"], look_mod.BUILTIN_SKINS[skin])
        p = QPainter(img)
        frame.paint(p, QRectF(0, 0, 400, 300), ElementState(), look)
        p.end()
        assert len(painted) == want, skin
    corners = frame.corner_screws(400, 300)
    assert len(corners) == 4
    assert {round(c.x()) for c in corners} == {12, 388} and {round(c.y()) for c in corners} == {24, 276}


def test_wood_cheeks_keep_only_their_four_corner_screws(qapp, monkeypatch):
    """The vintage frame paints exactly four screws, through the skin's screws element (one
    per cheek corner, none with ``screws: none``), all on the cheeks, clear of the content."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from mandible.ui.elements import screws
    from mandible.ui.elements.frames import WoodCheeks

    painted = []
    real = screws.CornersOnly.draw
    monkeypatch.setattr(screws.CornersOnly, "draw",
                        lambda self, p, w, h, st, lk: (painted.append((w, h)), real(self, p, w, h, st, lk)))
    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(0)
    frame = WoodCheeks()
    vintage = look_mod.Look(look_mod.BUILTIN_PALETTES["amber"], look_mod.BUILTIN_SKINS["vintage"])
    for look, want in ((vintage, 4), (look_mod.with_elements(vintage, screws="none"), 0)):
        painted.clear()
        p = QPainter(img)
        frame.paint(p, QRectF(0, 0, 400, 300), ElementState(), look)
        p.end()
        assert len(painted) == want, look.skin.elements["screws"]
    corners = frame.corner_screws(400, 300)
    assert len(corners) == 4
    assert {round(c.y()) for c in corners} == {24, 276}
    left, _top, right, _bottom = frame.content_margins(vintage)
    half = frame.SCREW_PX / 2
    for c in corners:   # every screw sits on a cheek, outside the content rect
        assert c.x() + half <= left or c.x() - half >= 400 - right, c
