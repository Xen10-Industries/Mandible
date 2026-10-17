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
    # Pins today's bug (the main window cannot shrink below 2033 px wide); Task 9 flips this
    # assertion to <= 1024.
    if sys.platform == "win32":
        assert entry["min_size"][0] == 2033
    else:
        assert entry["min_size"][0] > 1024

    for screen in ("settings", "prefx", "soundboard", "hotkey", "add_plugin", "param_map",
                   "setup_assistant", "about"):
        dialog_keys = [k for k in report if k.startswith(screen + "|skeuomorphic|scarlet|")]
        assert len(dialog_keys) == 1, screen
    for png in out.glob("*.png"):
        assert png.stat().st_size > 0
    assert any(out.glob("main__*.png"))


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
