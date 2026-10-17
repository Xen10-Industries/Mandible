"""Responsive main-window layout (spec 7.6): 1024 x 640 minimum, no overflow or clipped text
at any supported window size, scale 125 / 150 %, long and non-Latin names, header
breakpoints, collapsing channel strips and the persisted preset-panel splitter.

Size, overflow and clipped-text checks need real Windows font metrics, so on Windows they run
``tools/layout_probe.py`` in a subprocess on the ``windows`` platform (the window is never
shown on the desktop: WA_DontShowOnScreen, no tray icon). Elsewhere the probe runs offscreen,
whose substitute fonts are wider, and only looser checks apply.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from mandible.ui.text import abbreviate_title

ROOT = pathlib.Path(__file__).resolve().parents[1]
WIN32 = sys.platform == "win32"
WIDTHS = (1024, 1280, 1600, 1920, 2560)
HEIGHTS = (640, 720, 900, 1080)
SIZES = [(w, h) for w in WIDTHS for h in HEIGHTS]
SKINS = ("skeuomorphic", "vintage", "minimal")
# Offscreen substitutes fonts that measure up to ~1.5x wider than Segoe UI.
LOOSE = 1.5


def run_probe(out_dir: pathlib.Path, sizes, scenario: str = "sample", scale: float | None = None,
              strict: bool = False, skins=SKINS):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "windows" if WIN32 else "offscreen"
    env.pop("QT_SCALE_FACTOR", None)
    if scale is not None:
        env["QT_SCALE_FACTOR"] = str(scale)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "probe.json"
    cmd = [sys.executable, str(ROOT / "tools" / "layout_probe.py"), "--out", str(out),
           "--skins", ",".join(skins), "--sizes", ",".join(f"{w}x{h}" for w, h in sizes),
           "--scenario", scenario]
    if strict:
        cmd.append("--strict")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=600)
    report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    return proc, report


@pytest.fixture(scope="module")
def sweep(tmp_path_factory):
    proc, report = run_probe(tmp_path_factory.mktemp("sweep"), SIZES)
    assert report is not None and proc.returncode == 0, proc.stdout + proc.stderr
    assert report["platform"] == ("windows" if WIN32 else "offscreen")
    return report


# ------------------------------------------------------------------ real-metric checks

def test_minimum_size(sweep):
    for skin in SKINS:
        entry = sweep["skins"][skin]
        # The hint right after construction and after every resize (header, strip and
        # splitter states change with the window size; none may raise the minimum).
        hints = [entry["min_size"]] + [m["min_size"] for m in entry["sizes"].values()]
        for w, h in hints:
            if WIN32:
                assert w <= 1024 and h <= 640, (skin, hints)
            else:
                assert w <= 1024 * LOOSE and h <= 640 * LOOSE, (skin, hints)


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_no_overflow(sweep, size):
    w, h = size
    for skin in SKINS:
        m = sweep["skins"][skin]["sizes"][f"{w}x{h}"]
        if WIN32:
            assert m["size"] == [w, h], (skin, m["size"])
            assert m["overflow"] == [], (skin, m["overflow"])
            assert m["clipped_text"] == [], (skin, m["clipped_text"])
            assert m["elided_without_tooltip"] == [], (skin, m["elided_without_tooltip"])
        else:
            assert m["size"][0] >= w and m["size"][1] >= h
            assert isinstance(m["overflow"], list) and isinstance(m["clipped_text"], list)


def test_header_breakpoints_and_strip_collapse(sweep):
    """Flow strip: full >= 1400, icons >= 1100, hidden below (and degraded further when the
    middle zone is too narrow); Test mic / Monitor fold below 1180; strips collapse < 800."""
    for skin in SKINS:
        sizes = sweep["skins"][skin]["sizes"]
        for (w, h) in SIZES:
            m = sizes[f"{w}x{h}"]
            assert m["actions_folded"] == (w < 1180), (skin, w, h)
            assert m["strips_collapsed"] == (h < 800), (skin, w, h)
            if w < 1100:
                assert m["flow_mode"] == "hidden", (skin, w, m["flow_mode"])
            elif w < 1400:
                assert m["flow_mode"] in ("icons", "hidden"), (skin, w, m["flow_mode"])
            if WIN32:
                expected = {1024: "hidden", 1280: "icons", 1920: "full", 2560: "full"}
                if w in expected:
                    assert m["flow_mode"] == expected[w], (skin, w, m["flow_mode"])


def _probe_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("layout_probe", ROOT / "tools" / "layout_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_long_and_non_latin_names(tmp_path):
    probe = _probe_module()
    assert probe.LONG_CHAIN_NAME == "A" * 60
    assert probe.LONG_PLUGIN_NAME == "Very Long Plugin Name With Many Words Version 3"
    assert probe.NON_LATIN_DEVICE == "Микрофон (USB Audio CODEC)"

    proc, report = run_probe(tmp_path, [(1024, 640)], scenario="long_names")
    assert report is not None and proc.returncode == 0, proc.stdout + proc.stderr
    for skin in SKINS:
        m = report["skins"][skin]["sizes"]["1024x640"]
        assert m["elided_without_tooltip"] == [], (skin, m)
        elided = " | ".join(m["elided"])
        assert probe.LONG_CHAIN_NAME in elided, (skin, m["elided"])
        assert probe.LONG_PLUGIN_NAME in elided, (skin, m["elided"])
        if WIN32:
            assert m["size"] == [1024, 640]
            assert m["overflow"] == [], (skin, m["overflow"])
            assert m["clipped_text"] == [], (skin, m["clipped_text"])


def _check_scaled(tmp_path, scale):
    proc, report = run_probe(tmp_path, [(1024, 640)], scale=scale, strict=WIN32)
    assert report is not None, proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_scale_150(tmp_path):
    """Review focus 4: at 150 % the 1024 x 640 window has no overflow or clipped text."""
    _check_scaled(tmp_path, 1.5)


def test_scale_125(tmp_path):
    _check_scaled(tmp_path, 1.25)


# ------------------------------------------------------------------ pure / in-process

def _flush_deletes():
    """Delete ``deleteLater``-ed widgets now, on the main thread, while the core they point
    at is still alive (left to the garbage collector, a window in a reference cycle can be
    destroyed at a random point, even from the keyboard hook's thread)."""
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()



def test_abbreviate_title():
    assert abbreviate_title("Radio Squelch") == "SQUELCH"
    assert abbreviate_title("Stereo Width") == "WIDTH"
    assert abbreviate_title("Threshold") == "THRESH"
    assert abbreviate_title("Mix") == "MIX"
    assert abbreviate_title("Room Size") == "ROOM SIZE"
    assert abbreviate_title("Delay Time (seconds)") == "DELAY"
    assert abbreviate_title("Oversampling Factor") == "FACTOR"
    assert abbreviate_title("Supercalifragilistic") == "SUPERCALI"
    assert abbreviate_title("") == ""
    for name in ("Radio Squelch", "Very Long Plugin Name With Many Words Version 3"):
        assert len(abbreviate_title(name)) <= 9


def test_plugin_knob_titles_abbreviate_with_full_name_in_tooltip(sample_core):
    from mandible.ui.widgets.plugin_card import PluginRackCard

    chain = sample_core.cfg.chains[0]
    for slot in chain.plugins:
        card = PluginRackCard(slot, chain, sample_core)
        for knob in card.param_knobs:
            assert len(knob.title) <= 9
            assert knob.title == abbreviate_title(knob.full_name)
            assert knob.full_name in knob.toolTip()
        card.deleteLater()
    _flush_deletes()   # before the fixture shuts the core (and its plugins) down


def test_elided_label_tooltip_and_hints(qapp):
    from PySide6.QtCore import Qt

    from mandible.ui.widgets.labels import ElidedLabel

    lab = ElidedLabel("Very Long Plugin Name With Many Words Version 3")
    lab.setBaseToolTip("Plugin name")
    lab.setAttribute(Qt.WA_DontShowOnScreen)
    lab.show()
    assert lab.minimumSizeHint().width() < lab.sizeHint().width()
    lab.resize(60, lab.height())
    qapp.processEvents()
    assert lab.is_elided() and lab.text().endswith("…")
    assert lab.full_text() in lab.toolTip() and "Plugin name" in lab.toolTip()
    lab.resize(lab.sizeHint().width() + 10, lab.height())
    qapp.processEvents()
    assert not lab.is_elided() and lab.toolTip() == "Plugin name"
    lab.deleteLater()
    _flush_deletes()


@pytest.fixture
def main_window(sample_core):
    from PySide6.QtCore import Qt

    from mandible.ui.main_window import MainWindow

    sample_core.cfg.close_to_tray = False
    windows = []

    def make():
        win = MainWindow(sample_core, show_tray=False)
        win.setAttribute(Qt.WA_DontShowOnScreen)
        windows.append(win)
        return win

    yield make
    for win in windows:
        win.meter_timer.stop()
        win.status_timer.stop()
        win._quitting = True
        win.hide()
        win.deleteLater()
    _flush_deletes()
    windows.clear()


def _resize(qapp, win, w, h):
    win.resize(w, h)
    for _ in range(3):
        qapp.processEvents()


def test_strips_collapse_below_800(qapp, main_window):
    from mandible.ui.main_window import STRIPS_COLLAPSE_BELOW_H

    assert STRIPS_COLLAPSE_BELOW_H == 800
    win = main_window()
    win.show()
    _resize(qapp, win, 1600, 720)
    assert win.faders_collapsed
    assert win.condensed_faders_widget.isVisible() and not win.full_faders_widget.isVisible()
    _resize(qapp, win, 1600, 900)
    assert not win.faders_collapsed
    assert win.full_faders_widget.isVisible()

    # The user's toggle wins over the automatic rule, in both directions.
    win.collapse_faders_btn.click()
    assert win.faders_collapsed
    _resize(qapp, win, 1600, 1000)
    assert win.faders_collapsed
    _resize(qapp, win, 1600, 720)
    win.collapse_faders_btn.click()
    assert not win.faders_collapsed
    _resize(qapp, win, 1600, 700)
    assert not win.faders_collapsed


def test_splitter_width_persisted(qapp, main_window, sample_core):
    from mandible.ui.main_window import LEFT_PANEL_MAX, LEFT_PANEL_MIN

    assert (LEFT_PANEL_MIN, LEFT_PANEL_MAX) == (240, 420)
    assert sample_core.cfg.left_panel_width == 300

    sample_core.cfg.left_panel_width = 350
    win = main_window()
    win.resize(1920, 1000)
    win.show()
    qapp.processEvents()
    assert win.splitter.sizes()[0] == 350
    assert win.left_panel.minimumWidth() == 240 and win.left_panel.maximumWidth() == 420

    saved = []
    sample_core.save = lambda: saved.append(sample_core.cfg.left_panel_width)
    total = sum(win.splitter.sizes())
    win.splitter.setSizes([400, total - 400])
    win.splitter.splitterMoved.emit(400, 1)
    assert sample_core.cfg.left_panel_width == 400
    win.flush_pending_save()
    assert saved and saved[-1] == 400

    for stored, expected in ((1000, 420), (10, 240)):
        sample_core.cfg.left_panel_width = stored
        other = main_window()
        other.resize(1920, 1000)
        other.show()
        qapp.processEvents()
        assert other.splitter.sizes()[0] == expected


def test_status_zone_controls_and_settings_stay_in_sync(qapp, main_window, sample_core):
    """The old bottom row (idle mode, hotkeys, all-off key) lives in the header status zone and
    in Settings > General."""
    from mandible.config import Hotkey
    from mandible.ui.dialogs.settings import SettingsDialog

    win = main_window()
    header = win.header
    assert win.idle is header.idle_combo and win.hk_enabled is header.hotkeys_toggle
    assert win.idle.findData("mute") >= 0
    assert win.idle.findData(sample_core.cfg.chains[0].id) >= 0

    win.idle.setCurrentIndex(win.idle.findData("mute"))
    assert sample_core.cfg.idle_mode == "mute"
    win.hk_enabled.setChecked(False)
    assert sample_core.cfg.hotkeys_enabled is False
    assert sample_core.hotkeys.enabled is False

    dlg = SettingsDialog(sample_core, False, None)
    assert dlg.idle_combo.currentData() == "mute"
    assert dlg.hotkeys_check.isChecked() is False
    dlg.idle_combo.setCurrentIndex(dlg.idle_combo.findData("dry"))
    dlg.hotkeys_check.setChecked(True)
    dlg._panic_hotkey_work = Hotkey(scan_code=88, label="F12")
    dlg.apply_all()
    assert sample_core.cfg.idle_mode == "dry"
    assert sample_core.cfg.hotkeys_enabled is True
    assert sample_core.cfg.panic_hotkey.label == "F12"
    dlg.deleteLater()
    _flush_deletes()

    win.sync_status_controls()
    assert win.idle.currentData() == "dry"
    assert win.hk_enabled.isChecked()
    assert "F12" in win.panic_key_action.text()
