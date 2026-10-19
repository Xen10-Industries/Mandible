"""Runs ``tools/layout_probe.py`` in a subprocess (shared by the layout and skin tests).

Size, overflow and clipped-text checks need real Windows font metrics, so on Windows the probe
runs on the ``windows`` platform (never shown on the desktop: WA_DontShowOnScreen, no tray
icon); elsewhere it runs offscreen, whose substitute fonts are wider.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WIN32 = sys.platform == "win32"

# Look-switch limits (spec 7.2: a live switch, layout and repaint included). 150 ms is the
# budget on a desktop PC; CI runners are ~2.3x slower, so ci.yml sets MANDIBLE_SWITCH_MS=350.
# The ledger median (Customize panel open or closed) stays at 90% of the limit.
SWITCH_MS = float(os.environ.get("MANDIBLE_SWITCH_MS", "150"))
LEDGER_MS = SWITCH_MS * 0.9


def run_probe(out_dir: pathlib.Path, sizes, scenario: str = "sample", scale: float | None = None,
              strict: bool = False, skins=("skeuomorphic", "vintage", "minimal"),
              mode: str = "layout", themes=None, dock: str | None = None):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "windows" if WIN32 else "offscreen"
    env.pop("QT_SCALE_FACTOR", None)
    if scale is not None:
        env["QT_SCALE_FACTOR"] = str(scale)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "probe.json"
    cmd = [sys.executable, str(ROOT / "tools" / "layout_probe.py"), "--out", str(out),
           "--skins", ",".join(skins), "--sizes", ",".join(f"{w}x{h}" for w, h in sizes),
           "--scenario", scenario, "--mode", mode]
    if themes:
        cmd += ["--themes", ",".join(themes)]
    if dock:
        cmd += ["--dock", dock]
    if strict:
        cmd.append("--strict")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=600)
    report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
    return proc, report
