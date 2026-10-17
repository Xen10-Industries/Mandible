"""The UI gallery tool renders every screen off-screen and writes a layout report."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_gallery_reports_main_window_minimum_width(tmp_path):
    env = dict(os.environ)
    # The 2033 px figure was measured with real Windows font metrics; the offscreen platform
    # substitutes different fonts. WA_DontShowOnScreen keeps the windows platform invisible.
    env["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
    out = tmp_path / "gallery"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ui_gallery.py"), "--out", str(out),
         "--skins", "skeuomorphic", "--themes", "scarlet", "--sizes", "1280x720"],
        capture_output=True, text=True, env=env, timeout=240)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    assert (out / "index.html").is_file()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    key = "main|skeuomorphic|scarlet|1280x720"
    assert key in report
    entry = report[key]
    assert set(entry) == {"min_size", "overflow", "clipped_text", "untiered_buttons", "contrast"}
    # The main window shrinks to the 1024 x 640 minimum (spec 7.6; it used to need 2033 px).
    # Offscreen substitutes wider fonts, so only a looser bound holds there.
    if sys.platform == "win32":
        assert entry["min_size"][0] <= 1024
        assert entry["min_size"][1] <= 640
    else:
        assert entry["min_size"][0] <= 1536

    for screen in ("settings", "prefx", "soundboard", "hotkey", "add_plugin", "param_map",
                   "setup_assistant", "about"):
        dialog_keys = [k for k in report if k.startswith(screen + "|skeuomorphic|scarlet|")]
        assert len(dialog_keys) == 1, screen
    for png in out.glob("*.png"):
        assert png.stat().st_size > 0
    assert any(out.glob("main__*.png"))


def _gallery_main_entry(out: pathlib.Path) -> dict:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ui_gallery.py"), "--out", str(out),
         "--screens", "main", "--skins", "skeuomorphic", "--themes", "scarlet",
         "--sizes", "1024x640,1920x1080"],
        capture_output=True, text=True, env=env, timeout=240)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert set(report) == {"main|skeuomorphic|scarlet|1024x640",
                           "main|skeuomorphic|scarlet|1920x1080"}
    return report


def test_gallery_main_window_report_is_deterministic(tmp_path):
    """Timers are stopped and the status readout driven once before capture, so two runs
    report the same thing (a first-render status race once made clipped_text flake)."""
    first = _gallery_main_entry(tmp_path / "a")
    second = _gallery_main_entry(tmp_path / "b")
    assert first == second


def test_gallery_freezes_status_before_capture(sample_core):
    gallery = _load_gallery()
    sample_core.cfg.close_to_tray = False
    win = gallery.build_main_window(sample_core)
    try:
        assert not win.meter_timer.isActive() and not win.status_timer.isActive()
        assert win.status.text() == "STOPPED"
        assert win.vfd_stat.text() == "DSP: OFF"
    finally:
        gallery.dispose_main_window(win)


def _load_gallery():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ui_gallery", ROOT / "tools" / "ui_gallery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gallery_main_window_never_shows_tray_or_toast(sample_core, monkeypatch):
    """MainWindow.__init__ calls tray.show() and closeEvent hides to the tray with a toast;
    the gallery must trigger neither on the user's desktop."""
    from PySide6.QtWidgets import QSystemTrayIcon

    shown, messages = [], []
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: shown.append(self))
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, *a, **k: messages.append(a))
    gallery = _load_gallery()

    sample_core.cfg.close_to_tray = False
    win = gallery.build_main_window(sample_core)
    assert not win.tray.isVisible()
    assert win.isVisible()
    gallery.dispose_main_window(win)

    assert shown == []
    assert messages == []
    assert sample_core.cfg.chains  # the shared core survives (no quit())


def test_gallery_run_records_screen_errors_and_continues(qapp, tmp_path, monkeypatch):
    import mandible.ui.dialogs.about as about_module

    def boom(*_a, **_k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(about_module, "AboutDialog", boom)
    gallery = _load_gallery()
    out = tmp_path / "gallery"
    out.mkdir()
    report = gallery.run_gallery(out, ["skeuomorphic"], ["scarlet"], [(1280, 720)])

    errors = {k: v for k, v in report.items() if "error" in v}
    assert list(errors) == ["about|skeuomorphic|scarlet|error"]
    assert "synthetic failure" in errors["about|skeuomorphic|scarlet|error"]["error"]
    assert "main|skeuomorphic|scarlet|1280x720" in report  # other screens still captured
    on_disk = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert on_disk.keys() == report.keys()
    assert "ERROR" in (out / "index.html").read_text(encoding="utf-8")


def test_main_window_show_tray_flag(sample_core, monkeypatch):
    """show_tray=False builds the tray icon but never shows it; the default shows it."""
    from PySide6.QtWidgets import QSystemTrayIcon

    from mandible.ui.main_window import MainWindow

    shown = []
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: shown.append(self))
    quiet = MainWindow(sample_core, show_tray=False)
    assert shown == [] and quiet.tray is not None
    quiet.meter_timer.stop()
    quiet.status_timer.stop()
    loud = MainWindow(sample_core)
    assert shown == [loud.tray]
    loud.meter_timer.stop()
    loud.status_timer.stop()
    quiet.deleteLater()
    loud.deleteLater()


def test_gui_shim_only_exposes_main():
    import importlib

    importlib.import_module("mandible.__main__")  # imports cleanly, does not start the app
    from mandible import gui
    from mandible.ui.app import main

    assert gui.main is main
    assert [n for n in vars(gui) if not n.startswith("_") and n != "main"] == []


def test_gallery_looks_set_the_config_the_appearance_section_reads(qapp, sample_core):
    from mandible.ui.dialogs.settings import SettingsDialog
    from mandible.ui.look import current_look, set_look

    before = current_look()
    gallery = _load_gallery()
    try:
        gallery._apply(qapp, "minimal", "amber", sample_core)
        assert (sample_core.cfg.ui_skin, sample_core.cfg.theme) == ("minimal", "amber")
        dlg = SettingsDialog(sample_core, False, None)
        try:
            assert dlg.skin_combo.currentData() == "minimal"
            assert dlg.theme_combo.currentData() == "amber"
        finally:
            dlg.deleteLater()
    finally:
        set_look(before)


def test_gallery_states_visit_every_settings_section_and_wizard_step(sample_core):
    from mandible.ui.dialogs.settings import SettingsDialog
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog

    gallery = _load_gallery()
    dlg = SettingsDialog(sample_core, False, None)
    try:
        seen = [(dlg.current_section(), label) for _suffix, label in gallery._states(dlg)]
        assert [s for s, _ in seen] == dlg.section_ids()
        assert [label for _, label in seen][1:] == [
            dlg.sections.item(i).text() for i in range(1, dlg.sections.count())]
    finally:
        dlg.deleteLater()

    wiz = SetupAssistantDialog(sample_core, None)
    try:
        for suffix, _label in gallery._states(wiz):
            idx = wiz.pages.currentIndex()
            assert wiz.step_lbl.text() == f"STEP {idx + 1} OF 4", suffix
    finally:
        wiz._meter_timer.stop()
        wiz.deleteLater()
