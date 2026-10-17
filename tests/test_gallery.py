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
