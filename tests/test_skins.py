"""Every built-in skin meets the spec's "same standard" checklist (section 9) in every built-in
palette, at 1024 x 640, 1280 x 720 and 1920 x 1080, in the main window and every dialog.

Parametrized by skin: Tasks 13 and 14 add ``vintage`` and ``minimal`` to ``SKINS``.

Measurements run ``tools/layout_probe.py --mode standard`` in a subprocess with real Windows
font metrics (see ``tests/_probe.py``); offscreen fonts measure wrongly, so elsewhere only the
font-independent checks are asserted. Checklist items 4-6 (alignment, decoration,
legibility) are also reviewed by eye on the gallery sheet (``tools/ui_gallery.py``).
"""
from __future__ import annotations

import math
import statistics
import sys

import pytest
from _probe import SWITCH_MS, run_probe

SKINS = ["skeuomorphic", "vintage", "minimal"]
THEMES = ("scarlet", "cyan", "stealth", "amber")
SIZES = [(1024, 640), (1280, 720), (1920, 1080)]
WIN32 = sys.platform == "win32"


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
    assert _failures(standard, "multiple_primaries") == {}
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


# ------------------------------------------------------------------ minimal details

def _minimal_look(palette_id: str = "scarlet"):
    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look

    return Look(BUILTIN_PALETTES[palette_id], BUILTIN_SKINS["minimal"])


def _close(a, b, tol: int = 24) -> bool:
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) <= tol


def _paint_element(element, w: int, h: int, state, look, scale: int = 1, background=None):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    img = QImage(w * scale, h * scale, QImage.Format.Format_ARGB32)
    img.fill(background if background is not None else 0)
    p = QPainter(img)
    p.scale(scale, scale)
    element.paint(p, QRectF(0, 0, w, h), state, look)
    p.end()
    return img


@pytest.fixture
def minimal_window(qapp, sample_core):
    """A main window (never shown on screen) under the minimal look; the previous look comes
    back afterwards."""
    from PySide6.QtCore import Qt

    from mandible.ui.look import current_look, set_look
    from mandible.ui.main_window import MainWindow

    before = current_look()
    sample_core.cfg.close_to_tray = False
    win = MainWindow(sample_core, show_tray=False)
    win.setAttribute(Qt.WA_DontShowOnScreen)
    set_look(_minimal_look())
    win.resize(1280, 720)
    win.show()
    for _ in range(3):
        qapp.processEvents()
    yield win
    win.meter_timer.stop()
    win.status_timer.stop()
    win._quitting = True
    win.hide()
    win.deleteLater()
    _flush()
    set_look(before)


def test_minimal_frame_is_flush_on_the_compact_scale_with_one_outline(qapp, minimal_window):
    """Carry 1: the frameless frame's margins are on the compact scale (0: content flush with
    its hairline). The chassis strokes the outline over the header and console strips that
    cover the edge, so the window reads as one outlined panel all the way round, and the
    header, body and console content share one left edge (no strip border shifts it)."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QFrame

    from mandible.ui.elements.frames import Frameless
    from mandible.ui.inspect import COMPACT_SPACING_SCALE

    look = _minimal_look()
    margins = Frameless().content_margins(look)
    assert margins == (0, 0, 0, 0) and set(margins) <= COMPACT_SPACING_SCALE

    chassis = minimal_window.chassis
    m = chassis.layout().contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == margins
    img = chassis.grab().toImage()
    w, h = img.width(), img.height()
    line = QColor(look.palette.color("line.subtle"))
    header = minimal_window.header.geometry()
    console = minimal_window.console_frame.geometry()
    body_y = (header.bottom() + console.top()) // 2
    for y in (header.center().y(), body_y, console.center().y()):   # left and right edges
        for x in (0, w - 1):
            assert _close(img.pixelColor(x, y), line, 12), (x, y, img.pixelColor(x, y).name())
    for x in (w // 4, w // 2):                                       # top and bottom edges
        for y in (0, h - 1):
            assert _close(img.pixelColor(x, y), line, 12), (x, y, img.pixelColor(x, y).name())

    from PySide6.QtCore import QPoint

    win = minimal_window
    left = win.left_panel.mapTo(win, QPoint(0, 0)).x()
    header_first = win.header.left.mapTo(win, QPoint(0, 0)).x()
    strips = [c for c in win.console_frame.findChildren(QFrame) if c.isVisible()
              and c.objectName() in ("condensedStrip", "channelStrip", "channelStripCard")]
    assert strips
    console_first = min(c.mapTo(win, QPoint(0, 0)).x() for c in strips)
    assert header_first == left == console_first, (header_first, left, console_first)


def test_compact_minimal_is_tighter_at_the_window_gutters(qapp, minimal_window):
    """Carry 2: compact density with the frameless frame brings the content closer to the
    window edge than the comfortable skins, whose frames need 24 px. Card padding (8 / 12 px)
    is the same in both densities: spec 7.7 maps only 16 and 24. Clipping at every size is
    covered by ``test_skin_meets_standard[minimal]``."""
    from PySide6.QtCore import QPoint

    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look, set_look

    win = minimal_window
    gutters = {}
    for skin in ("skeuomorphic", "vintage", "minimal"):
        set_look(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS[skin]))
        for _ in range(3):
            qapp.processEvents()
        left = win.left_panel.mapTo(win, QPoint(0, 0)).x()
        rack = win.splitter.widget(1)
        right = win.width() - (rack.mapTo(win, QPoint(0, 0)).x() + rack.width())
        top = win.header.mapTo(win, QPoint(0, 0)).y()
        gutters[skin] = (left, right, top)
    for skin in ("skeuomorphic", "vintage"):
        assert all(a < b for a, b in zip(gutters["minimal"], gutters[skin])), gutters
    assert gutters["minimal"][0] == gutters["minimal"][1], gutters      # symmetric


def test_minimal_elements_paint_legible_text_and_the_pill_none(qapp):
    """Carry 3: the pill paints no text; the flat ring's title and value and the meters'
    labels are at least 10 px (11 px: the type scale's small / readout sizes)."""
    from mandible.ui.inspect import MIN_TEXT_PX, painted_text_sizes
    from mandible.ui.look import current_look, set_look
    from mandible.ui.widgets.knobs import HardwareKnob
    from mandible.ui.widgets.meters import LevelMeter, PluginPrePostMeter, ThinLevelMeter
    from mandible.ui.widgets.switches import HardwareSwitch

    before = current_look()
    set_look(_minimal_look())
    widgets = []
    try:
        switches = [HardwareSwitch(active=a, compact=c, vertical=v)
                    for a in (True, False) for c, v in ((False, False), (True, False), (True, True))]
        knob = HardwareKnob("DRY/WET", min_val=0.0, max_val=100.0, default_val=50.0, suffix="%")
        meters = [LevelMeter("CH 01"), ThinLevelMeter(), PluginPrePostMeter()]
        widgets = [*switches, knob, *meters]
        for sw in switches:
            assert painted_text_sizes(sw) == [], (sw.compact, sw.vertical)
        knob_text = painted_text_sizes(knob)       # title and value (offscreen fonts may elide)
        assert len(knob_text) == 2 and min(px for _c, _t, px in knob_text) >= 11, knob_text
        for meter in meters:
            assert all(px >= MIN_TEXT_PX for _c, _t, px in painted_text_sizes(meter)), meter
    finally:
        for wdg in widgets:
            wdg.deleteLater()
        _flush()
        set_look(before)


@pytest.mark.parametrize("palette_id", THEMES)
def test_pill_reads_on_and_off_by_position_and_fill(qapp, palette_id):
    """Carry 4: the pill is a finished drawing. On: a solid accent track, thumb at the right.
    Off: a hollow track outlined in a hairline that clears 3:1 on every surface, thumb at the
    left. The thumb clears 3:1 on its track in both states. Crisp: the track is snapped to
    the pixel grid, so at 1x its outline is one full-colour pixel row; 2x draws the same."""
    from PySide6.QtGui import QColor

    from mandible.ui.elements.base import ElementState
    from mandible.ui.elements.switches import Pill
    from mandible.ui.palette_gen import contrast_ratio
    from mandible.ui.style import INDICATOR_TOKENS as ind

    look = _minimal_look(palette_id)
    c = look.palette.color
    for surface in ("bg.window", "bg.panel", "bg.raised", "bg.inset"):
        assert contrast_ratio(c(ind["on"]), c(surface)) >= 3.0, surface
        assert contrast_ratio(c(ind["border"]), c(surface)) >= 3.0, surface
    assert contrast_ratio(c(ind["mark"]), c(ind["on"])) >= 3.0
    assert contrast_ratio(c(ind["border"]), c(ind["fill"])) >= 3.0

    on_fill, mark = QColor(c(ind["on"])), QColor(c(ind["mark"]))
    outline, well = QColor(c(ind["border"])), QColor(c(ind["fill"]))
    for pill in (Pill(), Pill(compact=True), Pill(compact=True, vertical=True)):
        size = pill.size_hint(look)
        w, h = size.width(), size.height()
        track = pill.track_rect(w, h)
        assert track.x() == int(track.x()) and track.y() == int(track.y())   # on the grid
        right, left = pill.thumb_centre(w, h, True), pill.thumb_centre(w, h, False)
        mid_x = track.center().x()
        for scale in (1, 2):
            on = _paint_element(pill, w, h, ElementState(active=True), look, scale)
            off = _paint_element(pill, w, h, ElementState(active=False), look, scale)

            def at(img, x, y):
                return img.pixelColor(int(x * scale), int(y * scale))

            assert _close(at(on, right.x(), right.y()), mark)
            assert _close(at(on, left.x(), left.y()), on_fill)
            assert _close(at(off, left.x(), left.y()), outline)
            assert _close(at(off, right.x(), right.y()), well)
            top = int(track.top() * scale)
            col = int(mid_x * scale)
            assert _close(off.pixelColor(col, top), outline, 8), (pill.compact, scale)
            assert off.pixelColor(col, top - 1).alpha() == 0
            if scale == 1:
                assert _close(off.pixelColor(col, top + 1), well, 8)    # one row, not a blur


@pytest.mark.parametrize("palette_id", THEMES)
def test_flat_ring_is_finished_and_legible(qapp, palette_id):
    """Carry 4: the flat ring is a flat drawing (track, value arc, disc and indicator; no
    gradient) with a visible track on the inset strips knobs sit on, the value arc in the
    accent and the value in text.primary."""
    from PySide6.QtGui import QColor

    from mandible.ui.elements.base import ElementState
    from mandible.ui.elements.knobs import READOUT_H, FlatRing
    from mandible.ui.palette_gen import contrast_ratio

    look = _minimal_look(palette_id)
    c = look.palette.color
    assert contrast_ratio(c("line.subtle"), c("bg.inset")) >= 1.2      # the track shows
    assert contrast_ratio(c("text.primary"), c("bg.inset")) >= 4.5     # the value reads
    inset = QColor(c("bg.inset"))
    accent, line, primary = (QColor(c(t)) for t in ("accent", "line.subtle", "text.primary"))

    def has(img, colour):
        return any(_close(img.pixelColor(x, y), colour, 6)
                   for y in range(img.height()) for x in range(img.width()))

    for knob in (FlatRing(), FlatRing(compact=True)):
        size = knob.size_hint(look)
        w, h = size.width(), size.height()
        zero = _paint_element(knob, w, h, ElementState(value=0.0, label="MIX", readout="0 %"),
                              look, 2, inset)
        most = _paint_element(knob, w, h, ElementState(value=0.75, label="MIX", readout="75 %"),
                              look, 2, inset)
        assert has(most, accent) and not has(zero, accent)
        assert has(zero, line) and has(most, primary)
        # Flat: the disc away from the indicator (which points up-right at 0.75) is one colour.
        cx, cy, radius = knob._geometry(w)
        for deg in (180.0, 202.5, 247.5, 270.0):
            r = (radius - 2.5) * 0.55
            x = cx + r * math.cos(math.radians(deg))
            y = cy - r * math.sin(math.radians(deg))
            assert _close(most.pixelColor(int(x * 2), int(y * 2)), line, 2), deg
        readout_row = most.copy(0, int((h - READOUT_H) * 2), most.width(), int(READOUT_H * 2))
        assert has(readout_row, primary)


@pytest.mark.parametrize("palette_id", THEMES)
def test_smooth_bar_track_shows_on_its_surfaces(qapp, palette_id):
    """Carry 4: an idle smooth bar is still visibly a meter on the surface each preset sits
    on (main: channel card; thin: console strip; prepost: the pre/post bezel), and a signal
    starts in meter.low."""
    from PySide6.QtGui import QColor

    from mandible.ui.elements.base import ElementState
    from mandible.ui.elements.meters import SmoothBar

    look = _minimal_look(palette_id)
    c = look.palette.color
    hosts = {"main": QColor(c("bg.panel")), "thin": QColor(c("bg.inset")),
             "prepost": QColor(c("bg.inset")).darker(150)}
    low = QColor(c("meter.low"))
    for preset, surface in hosts.items():
        bar = getattr(SmoothBar, preset)()
        size = bar.size_hint(look)
        w, h = size.width(), size.height()
        idle = _paint_element(bar, w, h, ElementState(value=0.0), look, 1, surface)
        mid = idle.pixelColor(w // 2, h // 2)
        assert not _close(mid, surface, 5), (preset, mid.name(), surface.name())
        lit = _paint_element(bar, w, h, ElementState(value=0.5), look, 1, surface)
        assert _close(lit.pixelColor(4, h // 2), low), preset


def test_minimal_has_structure_and_no_screws(qapp, minimal_window, monkeypatch):
    """Carry 5: flat panels stay separated by 1 px line.subtle borders (no gradients), and
    nothing in the minimal main window paints a screw."""
    import re

    from mandible.ui.elements import screws
    from mandible.ui.stylesheet import build_qss
    from mandible.ui.widgets.chassis import RackScrew

    look = _minimal_look()
    qss = build_qss(look)
    hairline = f"border: 1px solid {look.palette.color('line.subtle')}"
    for selector in (r"QFrame#modularBay, QFrame#presetModularBay",
                     r"QFrame#prefxModule, QFrame#limiterModule", r"QFrame#pluginRackCard",
                     r"QFrame#pluginMacroBay", r"QFrame#channelStripCard, QFrame#channelStrip",
                     r"QFrame#inspectorBox", r'QFrame\[surface="panel"\]',
                     r'QFrame\[surface="raised"\]', r'QFrame\[surface="inset"\]'):
        body = re.search(selector + r" \{([^}]*)\}", qss).group(1)
        assert hairline in body, selector
        assert "gradient" not in body, selector
    for selector, edge in (("QFrame#masterHeadStrip", "border-bottom"),
                           ("QFrame#consoleFrame", "border-top")):    # the window's zones
        body = re.search(selector + r" \{([^}]*)\}", qss).group(1)
        assert f"{edge}: " in body and look.palette.color("line.subtle") in body, selector
        assert "gradient" not in body, selector

    painted = []
    real = screws.CornersOnly.draw
    monkeypatch.setattr(screws.CornersOnly, "draw",
                        lambda self, *a: painted.append(1) or real(self, *a))
    minimal_window.grab()
    assert painted == []
    assert not [s for s in minimal_window.findChildren(RackScrew) if s.isVisible()]


def test_flat_pilot_lamps_read_on_and_off(qapp):
    """Gallery fix: in the flat skin the chain-card lamp was a 3 px smudge. Flat lamps are a
    solid status dot when on and a hollow text.secondary ring when off, 6 px or more across."""
    from PySide6.QtGui import QColor

    from mandible.ui.look import current_look, set_look
    from mandible.ui.palette_gen import contrast_ratio
    from mandible.ui.widgets.lamps import PilotLamp

    before = current_look()
    look = _minimal_look()
    set_look(look)
    lamps = []
    try:
        for size in (10, 18):
            on, off = PilotLamp(active=True, size=size), PilotLamp(active=False, size=size)
            lamps += [on, off]
            on_img, off_img = on.grab().toImage(), off.grab().toImage()
            centre = size // 2
            ok = QColor(look.palette.color("status.ok"))
            row_on = [x for x in range(size) if _close(on_img.pixelColor(x, centre), ok, 16)]
            assert len(row_on) >= 5, (size, row_on)                         # a solid dot
            bg = off_img.pixelColor(0, 0)
            assert _close(off_img.pixelColor(centre, centre), bg, 4)        # hollow ...
            ring = max(contrast_ratio(off_img.pixelColor(x, centre).name(), bg.name())
                       for x in range(size // 2))
            assert ring >= 2.0, (size, ring)                                 # ... ring
    finally:
        for lamp in lamps:
            lamp.deleteLater()
        _flush()
        set_look(before)
