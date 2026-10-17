"""The running app draws from the current Look: switching, persistence, delegation."""
from __future__ import annotations

import statistics
import time

import pytest

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


def test_switch_look_fast_and_engine_free(sample_core, restore_look):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication
    from mandible import gui

    app = QApplication.instance()
    # Measure the sample setup alone: earlier tests leave dialogs/windows alive, and an
    # app-wide stylesheet change restyles every live widget.
    for w in app.topLevelWidgets():
        if w is not sample_core.overlay:
            w.hide()
            w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gui.apply_theme(app, _look("skeuomorphic", "scarlet"))
    engine = _RecordingEngine(sample_core.engine)
    sample_core.engine = engine
    win = gui.MainWindow(sample_core)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    timings: dict[tuple[str, str], list[float]] = {}
    try:
        win.resize(1280, 720)
        win.show()
        app.processEvents()
        painted = []
        chassis_paint = win.chassis.paintEvent
        win.chassis.paintEvent = lambda ev: (painted.append(1), chassis_paint(ev))
        looks = [(s, t) for s in BUILTIN_SKINS for t in BUILTIN_PALETTES]
        for _ in range(3):
            for skin, theme in looks:
                engine.calls.clear()
                painted.clear()
                t0 = time.perf_counter()
                set_look(_look(skin, theme))
                app.sendPostedEvents()   # layout + repaint, but no timers
                timings.setdefault((skin, theme), []).append(time.perf_counter() - t0)
                assert engine.calls == [], (skin, theme, engine.calls)
                assert painted, "the timed window includes the repaint"
                assert current_look().skin.id == skin and current_look().palette.id == theme
    finally:
        win._quitting = True
        win.hide()
        win.tray.hide()
        win.deleteLater()
        sample_core.engine = engine._real
        app.processEvents()
    medians = {k: statistics.median(v) * 1000 for k, v in timings.items()}
    print("set_look median ms:", {f"{s}/{t}": round(ms, 1) for (s, t), ms in medians.items()})
    slow = {k: ms for k, ms in medians.items() if ms >= 150}
    assert not slow, slow


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


def test_core_frame_and_switch_setters_apply_look(core, restore_look):
    core.set_ui_skin("skeuomorphic")
    core.set_chassis_frame("wood_cheeks")
    core.set_switch_style("rocker")
    look = current_look()
    assert look.skin.id == "skeuomorphic"
    assert look.skin.elements["frame"] == "wood_cheeks"
    assert look.skin.elements["switch"] == "rocker"
    assert core.cfg.chassis_frame == "wood_cheeks" and core.cfg.switch_style == "rocker"


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
        dlg.frame_combo.setCurrentIndex(dlg.frame_combo.findData("frameless"))
        assert current_look().skin.id == "skeuomorphic"
        assert current_look().skin.elements["frame"] == "frameless"
        dlg.switch_combo.setCurrentIndex(dlg.switch_combo.findData("rocker"))
        assert current_look().skin.elements["switch"] == "rocker"

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
        dlg.frame_combo.setCurrentIndex(dlg.frame_combo.findData("wood_cheeks"))
        dlg.apply_all()
    finally:
        dlg.deleteLater()
    assert (core.cfg.ui_skin, core.cfg.theme, core.cfg.chassis_frame) == ("minimal", "stealth", "wood_cheeks")
    look = current_look()
    assert (look.skin.id, look.palette.id, look.skin.elements["frame"]) == ("minimal", "stealth", "wood_cheeks")


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
        assert frame.layout().contentsMargins().left() == 28
        set_look(_look("minimal", "scarlet"))   # lookChanged updates the margins
        m = frame.layout().contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (2, 2, 2, 2)
        set_look(_look("vintage", "scarlet"))
        assert frame.layout().contentsMargins().bottom() == 18
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
