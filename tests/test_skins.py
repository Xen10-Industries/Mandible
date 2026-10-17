"""Every built-in skin meets the spec's "same standard" checklist (section 9) in every built-in
palette, at 1024 x 640, 1280 x 720 and 1920 x 1080, in the main window and every dialog.

Parametrized by skin: Tasks 13 and 14 add ``vintage`` and ``minimal`` to ``SKINS``.

Measurements run ``tools/layout_probe.py --mode standard`` in a subprocess with real Windows
font metrics (see ``tests/_probe.py``); offscreen fonts measure wrongly, so elsewhere only the
font-independent checks are asserted. Checklist items 4-6 (alignment, decoration,
legibility) are also reviewed by eye on the gallery sheet (``tools/ui_gallery.py``).
"""
from __future__ import annotations

import statistics
import sys

import pytest
from _probe import run_probe

SKINS = ["skeuomorphic", "vintage"]
THEMES = ("scarlet", "cyan", "stealth", "amber")
SIZES = [(1024, 640), (1280, 720), (1920, 1080)]
WIN32 = sys.platform == "win32"
SWITCH_MS = 150


@pytest.fixture(scope="module", params=SKINS)
def standard(request, tmp_path_factory):
    skin = request.param
    proc, report = run_probe(tmp_path_factory.mktemp(f"standard-{skin}"), SIZES,
                             skins=[skin], mode="standard", themes=THEMES)
    assert report is not None and proc.returncode == 0, proc.stdout + proc.stderr
    assert report["skin"] == skin
    assert set(report["themes"]) == set(THEMES)
    return report


def _screens(report):
    for theme, entry in report["themes"].items():
        for screen, m in entry["screens"].items():
            yield theme, screen, m


def _failures(report, key):
    return {f"{theme} {screen}": m[key] for theme, screen, m in _screens(report) if m[key]}


def test_skin_meets_standard(standard):
    """Checklist items 1-3 and 7: no overflow, clipped or elided-without-tooltip text; every
    palette passes its contrast checks; every button is tiered; the live switch into the skin
    raises nothing and takes under 150 ms."""
    screens = {screen for _t, screen, _m in _screens(standard)}
    assert {f"main|{w}x{h}" for w, h in SIZES} <= screens
    assert {"settings", "prefx", "soundboard", "hotkey", "add_plugin", "param_map",
            "setup_assistant", "about"} <= screens
    for theme, entry in standard["themes"].items():
        assert entry["contrast"] == [], (theme, entry["contrast"])
    assert _failures(standard, "untiered_buttons") == {}
    if WIN32:
        assert _failures(standard, "overflow") == {}
        assert _failures(standard, "clipped_text") == {}
        assert _failures(standard, "elided_without_tooltip") == {}
        for theme, screen, m in _screens(standard):
            if screen.startswith("main|"):
                want = [int(v) for v in screen.split("|")[1].split("x")]
                assert m["size"] == want, (theme, screen, m["size"])
                assert m["min_size"][0] <= 1024 and m["min_size"][1] <= 640, (theme, m["min_size"])
    switch = standard["switch"]
    assert switch["errors"] == []
    assert len(switch["ms"]) >= len(THEMES)
    assert statistics.median(switch["ms"]) < SWITCH_MS, switch["ms"]


def test_skin_spacing_on_scale(standard):
    """Checklist item 4 (spacing): every layout's spacing and margins in the main window and
    every dialog come from the spacing scale (compact density: no 24)."""
    assert _failures(standard, "off_scale_spacing") == {}


def test_skin_painted_text_legible(standard):
    """Checklist item 6: knob titles and readouts, switch labels, meter scales (everything a
    skin element or custom widget paints itself) are at least 10 px."""
    assert _failures(standard, "small_painted_text") == {}
    main = [m for _t, screen, m in _screens(standard) if screen.startswith("main|")]
    assert all(m["painted_text_count"] > 0 for m in main)   # the check saw the painted text


def test_icon_only_controls_have_accessible_names(standard):
    """Icon-only buttons and pixmap-only labels (icon-mode flow pills, the brand mark) carry
    an accessible name, so a screen reader can say what they are."""
    assert _failures(standard, "unnamed_icon_controls") == {}


@pytest.mark.parametrize("skin", SKINS)
def test_card_with_many_knobs_fits_at_1024(skin, tmp_path):
    """A plugin with more mapped parameters than a card has knobs: the card shows eight knobs
    and "Map 8+" without overflow or clipping at the 1024 x 640 minimum."""
    proc, report = run_probe(tmp_path, [(1024, 640), (1280, 720)], scenario="many_knobs",
                             skins=[skin], mode="standard", themes=["scarlet"])
    assert report is not None and proc.returncode == 0, proc.stdout + proc.stderr
    for size in ("1024x640", "1280x720"):
        m = report["themes"]["scarlet"]["screens"][f"main|{size}"]
        assert m["small_painted_text"] == [], m["small_painted_text"]
        if WIN32:
            assert m["overflow"] == [], (size, m["overflow"])
            assert m["clipped_text"] == [], (size, m["clipped_text"])
            assert m["min_size"][0] <= 1024 and m["min_size"][1] <= 640, m["min_size"]


# ------------------------------------------------------------------ in-process details

def _flush():
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def test_map_label_caps_at_eight_and_clusters_align(sample_core):
    """Cards reserve the widest map label, so action clusters have one width whatever the
    number of mapped parameters; more than eight reads "Map 8+"."""
    from mandible.ui.widgets.plugin_card import MAX_CARD_KNOBS, PluginRackCard, map_label

    assert map_label(0) == "Map"
    assert map_label(5) == "Map 5"
    assert map_label(MAX_CARD_KNOBS) == f"Map {MAX_CARD_KNOBS}"
    assert map_label(MAX_CARD_KNOBS + 1) == map_label(40) == f"Map {MAX_CARD_KNOBS}+"

    chain = sample_core.cfg.chains[0]
    slot = chain.plugins[0]
    few = PluginRackCard(slot, chain, sample_core)
    slot.mapped_params = [f"x{i}" for i in range(12)]
    saved = slot._instance
    slot._instance = None          # unfiltered keys: twelve mapped parameters
    try:
        many = PluginRackCard(slot, chain, sample_core)
        assert many.map_btn.text() == "Map 8+"
        assert len(many.param_knobs) == MAX_CARD_KNOBS
        assert many.actions.width() == few.actions.width()
    finally:
        slot._instance = saved
        slot.mapped_params = None
    for card in (few, many):
        card.deleteLater()
    _flush()


def test_chain_card_keeps_name_case_and_sentence_case_status(qapp):
    from mandible.config import Chain, Hotkey
    from mandible.ui.widgets.chain_card import ChainCardWidget

    chain = Chain(name="Robot Voice")
    chain.hotkey = Hotkey(scan_code=59, label="F1 + Ctrl")
    card = ChainCardWidget(chain, False)
    assert card.name_lbl.full_text() == "Robot Voice"
    assert card.hk_lbl.text() == "F1 + Ctrl"
    assert card.sub_lbl.full_text() == "0 inserts · Standby"
    card.set_active_state(True)
    assert card.sub_lbl.full_text() == "0 inserts · Live on mic"
    card.deleteLater()
    _flush()


def _icon_has(button, hex_color: str) -> bool:
    from PySide6.QtGui import QColor, QImage

    img = button.icon().pixmap(16, 16).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    want = QColor(hex_color)
    return any(img.pixelColor(x, y).alpha() > 200 and img.pixelColor(x, y).rgb() == want.rgb()
               for y in range(img.height()) for x in range(img.width()))


def test_checked_toggles_recolour_their_icons(qapp):
    """Power and Monitor are checkable secondary buttons: checked, their icon turns the
    checked text colour (status.ok) along with the label."""
    from mandible.ui.look import current_look
    from mandible.ui.widgets.buttons import make_button

    pal = current_look().palette
    btn = make_button("Monitor", "secondary", icon="monitor", tooltip="Monitor")
    btn.setCheckable(True)
    assert _icon_has(btn, pal.color("text.primary"))
    btn.setChecked(True)
    assert _icon_has(btn, pal.color("status.ok"))
    assert not _icon_has(btn, pal.color("text.primary"))
    btn.setChecked(False)
    assert _icon_has(btn, pal.color("text.primary"))
    btn.deleteLater()
    _flush()


def test_waveform_handle_labels_legible(qapp):
    """The soundboard trim handles' S / E labels are painted at 10 px or more."""
    from PySide6.QtCore import Qt

    from mandible.ui.inspect import MIN_TEXT_PX, painted_text_sizes
    from mandible.waveform_widget import WaveformCanvas

    canvas = WaveformCanvas()
    canvas.setAttribute(Qt.WA_DontShowOnScreen)
    canvas.resize(400, 80)
    canvas.set_audio_data([0.2, 0.6, 0.4] * 20, 2.0, 0.5, 1.5)
    canvas.show()
    qapp.processEvents()
    sizes = {text: px for _cls, text, px in painted_text_sizes(canvas)}
    assert {"S", "E"} <= set(sizes)
    assert min(sizes.values()) >= MIN_TEXT_PX, sizes
    canvas.deleteLater()
    _flush()


def test_meters_read_calm_at_the_quiet_end():
    """Meter bars start in meter.low (never the accent, which reads as a warning in red
    palettes); the CH 02 marker is neutral, not a status colour."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from mandible.ui.elements.base import ElementState
    from mandible.ui.elements.meters import LedSegments, SmoothBar
    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look

    look = Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"])
    low = QColor(look.palette.color("meter.low"))
    for element in (SmoothBar.main(), LedSegments.main()):
        img = QImage(140, 13, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        element.paint(p, QRectF(0, 0, 140, 13), ElementState(value=0.5), look)
        p.end()
        c = img.pixelColor(2, 6)   # inside the first LED segment / the bar start
        assert max(abs(c.red() - low.red()), abs(c.green() - low.green()),
                   abs(c.blue() - low.blue())) <= 24, (type(element).__name__, c.name())

    from mandible.ui.main_window import CHANNEL_TOKENS

    assert not any(t.startswith("status.") for k, t in CHANNEL_TOKENS.items() if k != "in")


def test_status_pills_never_look_like_buttons():
    """Status pills are filled and borderless, fully rounded; buttons are outlined boxes."""
    import re

    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look
    from mandible.ui.stylesheet import build_qss

    qss = build_qss(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    pill = re.search(r"QLabel#statusPill \{([^}]*)\}", qss).group(1)
    assert "border: none" in pill
    for state in ("off", "on", "warn", "danger"):
        rule = re.search(r'QLabel#statusPill\[state="%s"\] \{([^}]*)\}' % state, qss).group(1)
        assert "border-color" not in rule and "border:" not in rule, state


# ------------------------------------------------------------------ vintage details

def _oklab_delta(a: str, b: str) -> float:
    """Euclidean distance in OKLab (perceptual; ~0.02 is a just-noticeable difference)."""
    import math

    from mandible.ui.palette_gen import hex_to_oklch

    def lab(hex_):
        light, chroma, hue = hex_to_oklch(hex_)
        return (light, chroma * math.cos(math.radians(hue)), chroma * math.sin(math.radians(hue)))

    return math.dist(lab(a), lab(b))


@pytest.mark.parametrize("palette_id", THEMES)
def test_vintage_wood_and_bakelite_stay_distinct_from_the_accent(palette_id):
    """Walnut and bakelite come from status.warn's hue at fixed low lightness, never from the
    accent, so the accent (active / primary states) stays distinguishable from them, Amber's
    orange accent included."""
    from mandible.ui.elements.base import wood
    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look

    look = Look(BUILTIN_PALETTES[palette_id], BUILTIN_SKINS["vintage"])
    accent = look.palette.color("accent")
    wd = wood(look)
    for name in ("light", "mid", "dark", "deep", "bakelite"):
        colour = getattr(wd, name).name()
        assert _oklab_delta(colour, accent) >= 0.2, (palette_id, name, colour, accent)
    # Same skin, same wood, whatever the accent: the derivation never reads it.
    other = Look(BUILTIN_PALETTES["cyan" if palette_id != "cyan" else "amber"], look.skin)
    assert wood(other).light.name() == wd.light.name()


def test_vintage_shape_is_tight_not_rounded_modern():
    import re

    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look
    from mandible.ui.stylesheet import build_qss

    shape = BUILTIN_SKINS["vintage"].shape
    assert shape["radius.panel"] <= 3 and shape["radius.control"] <= 3
    qss = build_qss(Look(BUILTIN_PALETTES["amber"], BUILTIN_SKINS["vintage"]))
    bay = re.search(r"QFrame#modularBay[^{]*\{([^}]*)\}", qss).group(1)
    assert "border-radius: 3px" in bay


@pytest.mark.parametrize("palette_id", THEMES)
def test_lacquer_panels_are_their_own_material_and_keep_text_readable(palette_id):
    """Vintage (lacquer) raised surfaces differ from skeuomorphic (brushed) ones: a thin gloss
    band on top. Every gradient stop is a palette surface on which body text keeps 4.5:1."""
    import re

    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look
    from mandible.ui.palette_gen import contrast_ratio
    from mandible.ui.stylesheet import build_qss

    pal = BUILTIN_PALETTES[palette_id]
    vintage = build_qss(Look(pal, BUILTIN_SKINS["vintage"]))
    skeuo = build_qss(Look(pal, BUILTIN_SKINS["skeuomorphic"]))
    for selector in (r'QFrame\[surface="raised"\]', r"QFrame#pluginRackCard",
                     r"QFrame#masterHeadStrip"):
        lac = re.search(selector + r" \{([^}]*)\}", vintage).group(1)
        brushed = re.search(selector + r" \{([^}]*)\}", skeuo).group(1)
        assert lac != brushed, selector
        assert pal.color("bg.overlay") in lac, selector
        stops = re.findall(r"stop:[0-9.]+ (#[0-9a-fA-F]{6})", lac)
        assert len(stops) >= 3, selector
        for colour in stops:
            for text in ("text.primary", "text.secondary"):
                ratio = contrast_ratio(pal.color(text), colour)
                assert ratio >= 4.5, (selector, text, colour, round(ratio, 2))


@pytest.mark.parametrize("palette_id", THEMES)
def test_rocker_cap_is_lacquer_from_the_surfaces(qapp, palette_id):
    """The rocker's lifted cap is a dark lacquer face from the palette surfaces: no bright
    readout-coloured (amber in Amber) cap edge and no accent, on or off."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from mandible.ui.elements.base import ElementState
    from mandible.ui.elements.switches import Rocker
    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look

    look = Look(BUILTIN_PALETTES[palette_id], BUILTIN_SKINS["vintage"])
    banned = [QColor(look.palette.color(t)) for t in ("readout.text", "accent")]
    for element in (Rocker(), Rocker(compact=True), Rocker(vertical=True)):
        size = element.size_hint(look)
        for active in (True, False):
            img = QImage(size.width() * 4, size.height() * 4, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            p.scale(4, 4)
            element.paint(p, QRectF(0, 0, size.width(), size.height()),
                          ElementState(active=active), look)
            p.end()
            for y in range(img.height()):
                for x in range(img.width()):
                    c = img.pixelColor(x, y)
                    if c.alpha() < 200:
                        continue
                    for b in banned:
                        assert max(abs(c.red() - b.red()), abs(c.green() - b.green()),
                                   abs(c.blue() - b.blue())) > 24, (
                            element.vertical, element.compact, active, x, y, c.name(), b.name())
