"""The running app draws from the current Look: switching, persistence, delegation."""
from __future__ import annotations

import pytest
from _probe import LEDGER_MS, SWITCH_MS

from mandible.ui.look import (
    BUILTIN_PALETTES,
    BUILTIN_SKINS,
    Look,
    current_look,
    look_bus,
    set_look,
)


@pytest.fixture
def restore_look(qapp):
    before = current_look()
    yield
    set_look(before)


def _look(skin: str, theme: str) -> Look:
    return Look(BUILTIN_PALETTES[theme], BUILTIN_SKINS[skin])


# ------------------------------------------------------------- brief's three tests

def _opaque_colors(img) -> set[str]:
    from PySide6.QtGui import QImage

    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    seen = set()
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() == 255:
                seen.add(c.name())
    return seen


def _near_count(img, hex_color: str, tol: int = 10) -> int:
    """Pixels (any alpha above half) within ``tol`` per channel of ``hex_color``."""
    from PySide6.QtGui import QColor, QImage

    want = QColor(hex_color)
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 127 and all(abs(a - b) <= tol for a, b in (
                    (c.red(), want.red()), (c.green(), want.green()), (c.blue(), want.blue()))):
                n += 1
    return n


def test_overlay_and_tray_follow_accent(qapp, restore_look):
    from mandible import branding
    from mandible.overlay import VoiceOverlay

    amber = BUILTIN_PALETTES["amber"].color("accent")
    set_look(_look("skeuomorphic", "amber"))

    ov = VoiceOverlay()
    try:
        assert ov.active_color().name() == amber
        ov.update_status("robot", is_active=True)
        assert _near_count(ov.grab().toImage(), amber) >= 10   # LED and border in the accent
        ov.update_status("clean", is_active=False)
        assert _near_count(ov.grab().toImage(), amber) == 0
    finally:
        ov.deleteLater()

    assert branding.tray_color(True) == amber
    icon_img = branding.tray_icon(True).pixmap(64, 64).toImage()
    assert amber in _opaque_colors(icon_img)

    # Following the look, not a fixed colour
    set_look(_look("skeuomorphic", "cyan"))
    assert branding.tray_color(True) == BUILTIN_PALETTES["cyan"].color("accent")


class _RecordingEngine:
    """Forwards to the real engine and records every method call and attribute write."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "calls", [])

    def __getattr__(self, name):
        value = getattr(self._real, name)
        if callable(value):
            def record(*a, **kw):
                self.calls.append(name)
                return value(*a, **kw)
            return record
        return value

    def __setattr__(self, name, value):
        self.calls.append(f"set {name}")
        setattr(self._real, name, value)


def test_switch_look_is_engine_free_and_error_free(sample_core, restore_look):
    """Every Look in the skin x palette matrix switches on a live main window without an
    exception, without a single engine call or attribute write, and repaints the chassis.

    The 150 ms limit (spec 7.2) is not asserted here: after ~900 tests the process carries so
    much accumulated Qt state that in-process medians are 125-200 ms whatever the code does.
    It is asserted in a clean process by ``test_switch_look_under_150_ms_in_a_clean_process``.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from mandible.ui.app import apply_theme
    from mandible.ui.main_window import MainWindow

    app = QApplication.instance()
    apply_theme(app, _look("skeuomorphic", "scarlet"))
    engine = _RecordingEngine(sample_core.engine)
    sample_core.engine = engine
    win = MainWindow(sample_core)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    try:
        win.resize(1280, 720)
        win.show()
        app.processEvents()
        painted = []
        chassis_paint = win.chassis.paintEvent
        win.chassis.paintEvent = lambda ev: (painted.append(1), chassis_paint(ev))
        looks = [(s, t) for s in BUILTIN_SKINS for t in BUILTIN_PALETTES]
        for _ in range(2):
            for skin, theme in looks:
                engine.calls.clear()
                painted.clear()
                set_look(_look(skin, theme))
                app.sendPostedEvents()   # layout + repaint, but no timers
                assert engine.calls == [], (skin, theme, engine.calls)
                assert painted, (skin, theme, "the chassis repaints")
                assert current_look().skin.id == skin and current_look().palette.id == theme
    finally:
        win._quitting = True
        win.hide()
        win.tray.hide()
        win.deleteLater()
        sample_core.engine = engine._real
        app.processEvents()


MIN_SWITCH_SAMPLES = 24  # timed switches per skin, after the warm-up round


@pytest.mark.parametrize("skin", list(BUILTIN_SKINS))
def test_switch_look_under_150_ms_in_a_clean_process(skin, tmp_path):
    """The look-switch time, measured by ``tools/layout_probe.py --mode switch`` in a fresh
    process per skin (real Windows font metrics on win32; never shown on the desktop): the
    sample setup in a 1280 x 720 main window, switching into ``skin`` in every palette from
    every other skin. A warm-up round is excluded, there are >= 24 timed switches, and their
    median must stay under the limit (the max is printed: a lone slow switch is not a failure).
    One process per skin because Qt state accumulates: the third skin timed in one process runs
    ~35% slower than the first."""
    from _probe import run_probe

    proc, report = run_probe(tmp_path, [(1280, 720)], mode="switch", skins=[skin],
                             themes=list(BUILTIN_PALETTES))
    assert report is not None and proc.returncode == 0, proc.stdout + proc.stderr
    assert report["skin"] == skin
    res = report["switch"]
    assert res["errors"] == [], res["errors"]
    assert res["warmup_rounds"] >= 1
    assert len(res["ms"]) >= MIN_SWITCH_SAMPLES, len(res["ms"])
    print(f"switch into {skin}: median {res['median_ms']} ms, max {res['max_ms']} ms "
          f"over {len(res['ms'])} switches")
    assert res["median_ms"] < SWITCH_MS, res["ms"]




@pytest.mark.parametrize("skin,dock", [
    ("skeuomorphic", "simple"), ("vintage", "simple"), ("minimal", "simple"),
    ("skeuomorphic", "advanced"), ("skeuomorphic", "closed"),
])
def test_switch_look_with_the_customize_panel_in_a_clean_process(skin, dock, tmp_path):
    """The look-switch time with the Customize panel open in Simple mode, open with Advanced on,
    and opened then closed (its deletion processed), each in a fresh process like the test above.
    Every case stays under the 150 ms limit; Simple mode and the closed panel also keep the
    ledger median (<= 135 ms): a live panel must not slow every later switch down."""
    from _probe import run_probe

    proc, report = run_probe(tmp_path, [(1280, 720)], mode="switch", skins=[skin],
                             themes=list(BUILTIN_PALETTES), dock=dock)
    assert report is not None and proc.returncode == 0, proc.stdout + proc.stderr
    res = report["switch"]
    assert res["dock"] == dock and res["errors"] == [], res["errors"]
    assert len(res["ms"]) >= MIN_SWITCH_SAMPLES, len(res["ms"])
    print(f"switch into {skin} with the panel {dock}: median {res['median_ms']} ms, "
          f"max {res['max_ms']} ms over {len(res['ms'])} switches")
    assert res["median_ms"] < SWITCH_MS, res["ms"]
    if dock in ("simple", "closed"):
        assert res["median_ms"] <= LEDGER_MS, res["ms"]


def test_look_persists(core, restore_look):
    from mandible.config import load_config
    from mandible.ui.look import look_from_config

    core.set_ui_skin("minimal")
    core.set_theme("amber")
    assert current_look().skin.id == "minimal" and current_look().palette.id == "amber"
    core.save_now()
    look = look_from_config(load_config())
    assert (look.skin.id, look.palette.id) == ("minimal", "amber")


# ------------------------------------------------------------- config ids -> Look

def test_look_from_config_unknown_ids_fall_back():
    from mandible.config import AppConfig
    from mandible.ui.look import look_from_config

    cfg = AppConfig()
    cfg.ui_skin, cfg.theme = "hologram", "plaid"
    look = look_from_config(cfg)
    assert look == _look("skeuomorphic", "scarlet")


def test_frame_and_switch_overrides_keep_skin_id():
    from mandible.ui.look import look_for

    base = look_for("cyan", "vintage")
    assert base == _look("vintage", "cyan")
    framed = look_for("cyan", "vintage", frame="metal_rack")
    assert framed.skin.id == "vintage" and framed.skin.elements["frame"] == "metal_rack"
    assert framed.skin.elements["knob"] == "vintage_bakelite"
    assert look_for("cyan", "vintage", frame="auto") == base
    assert look_for("cyan", "vintage", frame="laser") == base
    # The old switch-style setting only ever applied to the skeuomorphic skin.
    rocker = look_for("cyan", "skeuomorphic", switch_style="rocker")
    assert rocker.skin.id == "skeuomorphic" and rocker.skin.elements["switch"] == "rocker"
    assert look_for("cyan", "minimal", switch_style="bat_toggle").skin.elements["switch"] == "pill"
    assert look_for("cyan", "vintage", switch_style="bat_toggle").skin.elements["switch"] == "rocker"


def test_unmigrated_legacy_frame_and_switch_still_apply_through_the_config(core, restore_look):
    """Before migration the old fields still shape the look (spec 7.5); Customize owns them now,
    so the core no longer has setters for them."""
    core.cfg.chassis_frame, core.cfg.switch_style = "wood_cheeks", "rocker"
    core.set_ui_skin("skeuomorphic")
    look = current_look()
    assert look.skin.id == "skeuomorphic"
    assert look.skin.elements["frame"] == "wood_cheeks"
    assert look.skin.elements["switch"] == "rocker"
    assert not hasattr(core, "set_chassis_frame") and not hasattr(core, "set_switch_style")


# ------------------------------------------------------------- old theming is gone

def test_old_theme_api_removed():
    from mandible import gui

    for name in ("THEMES", "_UI_STATE", "current_skin", "get_theme_dict", "build_stylesheet",
                 "resolve_chassis_frame", "_draw_themed_rotary_dial"):
        assert not hasattr(gui, name), name


def test_settings_pickers_show_palette_names_and_preview(core, restore_look):
    from mandible.ui.dialogs.settings import SettingsDialog

    set_look(_look("skeuomorphic", "scarlet"))
    dlg = SettingsDialog(core, False, None)
    try:
        names = [dlg.theme_combo.itemText(i) for i in range(dlg.theme_combo.count())]
        assert names == ["Scarlet", "Cyan", "Stealth", "Amber"]
        skins = [dlg.skin_combo.itemText(i) for i in range(dlg.skin_combo.count())]
        assert skins == [s.name for s in BUILTIN_SKINS.values()]

        dlg.theme_combo.setCurrentIndex(dlg.theme_combo.findData("amber"))
        assert current_look().palette.id == "amber"
        dlg.skin_combo.setCurrentIndex(dlg.skin_combo.findData("vintage"))
        assert current_look().skin.id == "vintage"
        assert current_look().skin.elements["frame"] == "wood_cheeks"

        dlg.reject()
        assert current_look() == _look("skeuomorphic", "scarlet")
    finally:
        dlg.deleteLater()


def test_settings_apply_persists_look(core, restore_look):
    from mandible.ui.dialogs.settings import SettingsDialog

    set_look(_look("skeuomorphic", "scarlet"))
    dlg = SettingsDialog(core, False, None)
    try:
        dlg.skin_combo.setCurrentIndex(dlg.skin_combo.findData("minimal"))
        dlg.theme_combo.setCurrentIndex(dlg.theme_combo.findData("stealth"))
        dlg.apply_all()
    finally:
        dlg.deleteLater()
    assert (core.cfg.ui_skin, core.cfg.theme, core.cfg.chassis_frame) == ("minimal", "stealth", "auto")
    look = current_look()
    assert (look.skin.id, look.palette.id, look.skin.elements["frame"]) == ("minimal", "stealth", "frameless")


# ------------------------------------------------------------- widgets delegate to elements

def test_widgets_take_variants_from_the_look(qapp, restore_look):
    import dataclasses

    from mandible.ui.elements import knobs, meters, screws, switches
    from mandible.ui.widgets.chassis import RackScrew
    from mandible.ui.widgets.knobs import HardwareKnob
    from mandible.ui.widgets.meters import LevelMeter, PluginPrePostMeter, ThinLevelMeter
    from mandible.ui.widgets.switches import HardwareSwitch

    main, thin, prepost = LevelMeter("CH"), ThinLevelMeter(), PluginPrePostMeter()
    knob = HardwareKnob("GAIN", -60.0, 12.0)
    sw_v = HardwareSwitch(active=True, compact=True, vertical=True)
    sw = HardwareSwitch(active=True)
    screw = RackScrew(12)
    try:
        set_look(_look("skeuomorphic", "scarlet"))
        assert isinstance(main.element(), meters.LedSegments) and main.element().segments == 26
        assert thin.element().segments == 18 and prepost.element().segments == 14
        assert isinstance(knob.element(), knobs.Machined) and not knob.element().compact
        assert isinstance(sw.element(), switches.BatToggle)
        assert sw_v.element().compact and sw_v.element().vertical
        assert isinstance(screw.element(), screws.CornersOnly)

        set_look(_look("minimal", "scarlet"))
        for m in (main, thin, prepost):
            assert isinstance(m.element(), meters.SmoothBar)
        assert isinstance(knob.element(), knobs.FlatRing)
        assert isinstance(sw.element(), switches.Pill)
        assert isinstance(screw.element(), screws.NoScrews)

        skin = BUILTIN_SKINS["minimal"]
        odd = dataclasses.replace(skin, elements={**skin.elements, "meter": "led_segments",
                                                   "switch": "rocker"})
        set_look(Look(BUILTIN_PALETTES["scarlet"], odd))
        assert main.element().segments == 26 and isinstance(sw.element(), switches.Rocker)
    finally:
        for w in (main, thin, prepost, knob, sw_v, sw, screw):
            w.deleteLater()


def test_plugin_knob_is_compact(sample_core, restore_look):
    from mandible.ui.widgets.knobs import PluginParamKnob

    set_look(_look("vintage", "amber"))
    chain = sample_core.cfg.chains[0]
    kn = PluginParamKnob(chain.plugins[0], "missing_param", sample_core)
    try:
        assert kn.element().compact
        assert type(kn.element()).__name__ == "VintageBakelite"
    finally:
        kn.deleteLater()


def _render(widget):
    widget.resize(widget.sizeHint().expandedTo(widget.minimumSize()))
    return widget.grab().toImage()


def test_widget_paint_equals_element_paint(qapp, restore_look):
    """A delegating widget draws exactly what its element draws for the widget's state."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter

    from mandible.ui.elements.base import ElementState
    from mandible.ui.widgets.switches import HardwareSwitch

    for skin in BUILTIN_SKINS:
        set_look(_look(skin, "cyan"))
        sw = HardwareSwitch(active=True, compact=True)
        sw.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        try:
            got = sw.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            want = QImage(got.size(), QImage.Format.Format_ARGB32_Premultiplied)
            want.setDevicePixelRatio(got.devicePixelRatio())
            want.fill(Qt.GlobalColor.transparent)
            p = QPainter(want)
            sw.element().paint(p, QRectF(0, 0, sw.width(), sw.height()),
                               ElementState(active=True), current_look())
            p.end()
            assert got == want, skin
        finally:
            sw.deleteLater()


def test_meter_states_hide_low_peaks(qapp):
    from mandible.ui.widgets.meters import LevelMeter, PluginPrePostMeter, ThinLevelMeter

    m = LevelMeter("CH")
    t = ThinLevelMeter()
    pp = PluginPrePostMeter(enabled=True)
    try:
        m.level_db, m.peak_db = -20.0, -54.0
        st = m.bar_state()
        assert st.value == pytest.approx(40 / 66) and st.peak == pytest.approx(6 / 66)
        m.peak_db = -55.0
        assert m.bar_state().peak is None

        t.level_db, t.peak_db = -6.0, -55.0
        assert t.bar_state().peak is None and t.bar_state().value == pytest.approx(54 / 66)

        pp.pre_db = pp.pre_peak_db = -30.0
        pp.post_db, pp.post_peak_db = -12.0, -56.0
        (pre_lbl, pre), (post_lbl, post) = pp.row_states()
        assert (pre_lbl, post_lbl) == ("PRE", "POST")
        assert pre.enabled and pre.peak == pytest.approx(30 / 66)
        assert post.enabled and post.peak is None and post.value == pytest.approx(48 / 66)

        pp.slot_enabled = False
        (_, pre), (_, post) = pp.row_states()
        assert pre.enabled and not post.enabled
    finally:
        for w in (m, t, pp):
            w.deleteLater()


def test_chassis_margins_follow_frame(qapp, restore_look):
    from PySide6.QtWidgets import QVBoxLayout

    from mandible.ui.widgets.chassis import ChassisWrapperFrame

    frame = ChassisWrapperFrame()
    QVBoxLayout(frame)
    try:
        set_look(_look("skeuomorphic", "scarlet"))
        frame.update_frame_margins()
        assert frame.layout().contentsMargins().left() == 24
        set_look(_look("minimal", "scarlet"))   # lookChanged updates the margins
        m = frame.layout().contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (0, 0, 0, 0)
        set_look(_look("vintage", "scarlet"))
        m = frame.layout().contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (24, 12, 24, 16)
    finally:
        frame.deleteLater()


def test_look_change_repaints_listeners(qapp, restore_look):
    from mandible.ui.widgets.switches import HardwareSwitch

    sw = HardwareSwitch(active=True)
    hits = []
    sw.update = lambda *a: hits.append(1)   # instance attribute shadows QWidget.update
    try:
        set_look(_look("minimal", "amber"))
        assert hits
    finally:
        sw.deleteLater()
    assert look_bus() is look_bus()
