"""Measure the main window's layout at a set of window sizes and write a JSON report.

Usage::

    python tools/layout_probe.py --out FILE [--skins a,b] [--theme ID]
        [--sizes 1024x640,1280x720] [--scenario sample|long_names] [--strict]

Uses the gallery's machinery (``tools/ui_gallery.py``: isolated %APPDATA%, the sample setup,
a MainWindow that is never shown on the desktop, frozen timers) so layout tests can measure
with real Windows font metrics (``QT_QPA_PLATFORM=windows``) in a subprocess. The report::

    {"platform": "windows", "skins": {"<skin>": {"min_size": [w, h], "sizes": {"<WxH>": {
        "size": [w, h], "min_size": [w, h], "overflow": [...], "clipped_text": [...],
        "elided": [...], "elided_without_tooltip": [...],
        "flow_mode": "full|icons|hidden", "actions_folded": bool,
        "strips_collapsed": bool}}}}}

``--scenario long_names`` renames the first chain to 60 characters, gives its first plugin a
long display name and sets a non-Latin input device name before the window is built.
``--strict`` exits 1 when any size reports overflow, clipped text, an elided label without
its full text in the tooltip, or a window that could not shrink to the requested size.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
LONG_CHAIN_NAME = "A" * 60
LONG_PLUGIN_NAME = "Very Long Plugin Name With Many Words Version 3"
NON_LATIN_DEVICE = "Микрофон (USB Audio CODEC)"


def apply_scenario(core, scenario: str) -> None:
    if scenario == "long_names":
        chain = core.cfg.chains[0]
        chain.name = LONG_CHAIN_NAME
        chain.plugins[0].display_name = LONG_PLUGIN_NAME
        core.cfg.audio.input_device = NON_LATIN_DEVICE
    elif scenario != "sample":
        raise ValueError(f"unknown scenario {scenario!r}")


def _elided(win) -> tuple[list[str], list[str]]:
    from mandible.ui.widgets.labels import ElidedLabel

    elided, missing = [], []
    for lab in win.findChildren(ElidedLabel):
        if not (lab.isVisible() and lab.width() > 0) or not lab.is_elided():
            continue
        elided.append(lab.full_text())
        if lab.full_text() not in lab.toolTip():
            missing.append(f"{lab.objectName()} '{lab.full_text()[:40]}'")
    return elided, missing


def measure(win, app, w: int, h: int) -> dict:
    from mandible.ui import inspect as ins

    win.resize(w, h)
    for _ in range(3):
        app.processEvents()
    hint = win.minimumSizeHint().expandedTo(win.minimumSize())
    elided, missing = _elided(win)
    header = win.header
    return {
        "size": [win.width(), win.height()],
        "min_size": [hint.width(), hint.height()],
        "overflow": [dataclasses.asdict(o) for o in ins.find_overflow(win)],
        "clipped_text": ins.find_clipped_text(win),
        "elided": elided,
        "elided_without_tooltip": missing,
        "flow_mode": header.flow_mode(),
        "actions_folded": header.actions_folded(),
        "strips_collapsed": bool(win.faders_collapsed),
    }


def run(skins: list[str], theme: str, sizes: list[tuple[int, int]], scenario: str) -> dict:
    sys.path.insert(0, str(ROOT / "tools"))
    import ui_gallery as gallery
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from mandible.ui.sample_setup import build_sample_core

    app = QApplication.instance() or QApplication([])
    report = {"platform": QGuiApplication.platformName(), "skins": {}}
    core = build_sample_core()
    try:
        core.cfg.close_to_tray = False
        apply_scenario(core, scenario)
        for skin in skins:
            gallery._apply(app, skin, theme)
            win = gallery.build_main_window(core)
            try:
                if core.cfg.chains:
                    win.chain_list.setCurrentRow(0)
                    app.processEvents()
                hint = win.minimumSizeHint().expandedTo(win.minimumSize())
                entry = {"min_size": [hint.width(), hint.height()], "sizes": {}}
                for w, h in sizes:
                    entry["sizes"][f"{w}x{h}"] = measure(win, app, w, h)
                report["skins"][skin] = entry
            finally:
                gallery.dispose_main_window(win)
    finally:
        core.shutdown()
    return report


def problems(report: dict) -> list[str]:
    found = []
    for skin, entry in report["skins"].items():
        for size, m in entry["sizes"].items():
            want = [int(v) for v in size.split("x")]
            if m["size"] != want:
                found.append(f"{skin} {size}: window is {m['size']}")
            for name in ("overflow", "clipped_text", "elided_without_tooltip"):
                if m[name]:
                    found.append(f"{skin} {size}: {name} {m[name]}")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--skins", default="skeuomorphic,vintage,minimal")
    ap.add_argument("--theme", default="scarlet")
    ap.add_argument("--sizes", default="1024x640")
    ap.add_argument("--scenario", default="sample", choices=("sample", "long_names"))
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    appdata = tempfile.mkdtemp(prefix="mandible-probe-")
    os.environ["APPDATA"] = appdata
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    from ui_gallery import parse_sizes

    code = 1
    try:
        report = run(args.skins.split(","), args.theme, parse_sizes(args.sizes), args.scenario)
        pathlib.Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
        found = problems(report)
        for line in found:
            print(line)
        code = 1 if (args.strict and found) else 0
    finally:
        shutil.rmtree(appdata, ignore_errors=True)
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
