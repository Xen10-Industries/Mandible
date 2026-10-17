"""Render every Mandible screen off-screen and report layout problems.

Usage::

    python tools/ui_gallery.py --out DIR [--skins a,b] [--themes a,b]
        [--sizes 1024x640,1280x720,1920x1080] [--user-looks DIR] [--strict]

Writes ``DIR/*.png`` (one per screen x skin x theme x size), ``DIR/index.html`` (a plain
page with the images and a table of report counts) and ``DIR/report.json``::

    {"<screen>|<skin>|<theme>|<WxH>": {"min_size": [w, h], "overflow": [...],
     "clipped_text": [...], "untiered_buttons": [...], "contrast": [...]}}

Screens are ``main`` plus one per dialog. Sizes apply to the main window; dialogs are
captured at their default size. Nothing is ever shown on the desktop (WA_DontShowOnScreen),
and %APPDATA% is pointed at a temp dir before ``mandible`` is imported. QT_QPA_PLATFORM
defaults to ``offscreen``; set it to ``windows`` on Windows for real font metrics (minimum
sizes differ between the two because the offscreen platform substitutes fonts). ``--strict`` exits 1
when any overflow, clipped-text or contrast list is non-empty.
"""
from __future__ import annotations

import argparse
import dataclasses
import html
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SKINS = "skeuomorphic,vintage,minimal"
DEFAULT_THEMES = "scarlet,cyan,stealth,amber"
DEFAULT_SIZES = "1024x640,1280x720,1920x1080"
DIALOGS = ("settings", "prefx", "soundboard", "hotkey", "add_plugin", "param_map",
           "setup_assistant", "about")
_LISTS = ("overflow", "clipped_text", "untiered_buttons", "contrast")


def parse_sizes(text: str) -> list[tuple[int, int]]:
    sizes = []
    for part in text.split(","):
        w, _, h = part.strip().lower().partition("x")
        sizes.append((int(w), int(h)))
    return sizes


def _apply(app, skin_id: str, theme_id: str) -> None:
    """Select a skin and theme. The one place that knows how (Task 7 swaps in ``set_look``)."""
    from mandible import gui

    gui.apply_theme(app, theme_id, skin_id, "auto")


def _contrast(theme_id: str) -> list[dict]:
    from mandible.ui.look import BUILTIN_PALETTES
    from mandible.ui.palette_gen import check_colors

    palette = BUILTIN_PALETTES.get(theme_id)
    if palette is None:
        return []
    return [dataclasses.asdict(i) for i in check_colors(palette.colors)]


def _inspect(widget, contrast: list[dict]) -> dict:
    from mandible.ui import inspect as ins

    return {
        "overflow": [dataclasses.asdict(o) for o in ins.find_overflow(widget)],
        "clipped_text": ins.find_clipped_text(widget),
        "untiered_buttons": ins.untiered_buttons(widget),
        "contrast": contrast,
    }


def _merge(into: dict, more: dict) -> None:
    for name in _LISTS:
        for item in more[name]:
            if item not in into[name]:
                into[name].append(item)


def _states(dialog):
    """Yield ``(suffix, label)`` after switching the dialog to each tab / wizard page."""
    from PySide6.QtWidgets import QStackedWidget, QTabWidget

    yield "", ""
    tabs = dialog.findChildren(QTabWidget)
    if tabs:
        tw = tabs[0]
        for i in range(1, tw.count()):
            tw.setCurrentIndex(i)
            yield f"_tab{i}", tw.tabText(i)
    elif type(dialog).__name__ == "SetupAssistantDialog":
        for sw in dialog.findChildren(QStackedWidget):
            if sw.count() > 1:
                for i in range(1, sw.count()):
                    sw.setCurrentIndex(i)
                    yield f"_page{i}", f"page {i}"
                break


def run_gallery(out: pathlib.Path, skins: list[str], themes: list[str],
                sizes: list[tuple[int, int]]) -> dict:
    """Render the gallery into ``out`` and return the report. Needs a QApplication."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from mandible import gui
    from mandible.about import AboutDialog
    from mandible.setup_assistant import SetupAssistantDialog
    from mandible.ui.sample_setup import build_sample_core

    app = QApplication.instance() or QApplication([])
    core = build_sample_core()
    slot = core.cfg.chains[0].plugins[0]
    report: dict[str, dict] = {}
    images: dict[str, list[str]] = {}

    def snap(widget, name: str) -> str:
        app.processEvents()
        fname = name.replace("|", "__") + ".png"
        widget.grab().save(str(out / fname))
        return fname

    def show_offscreen(widget) -> None:
        widget.setAttribute(Qt.WA_DontShowOnScreen)
        widget.show()
        app.processEvents()

    builders = {
        "settings": lambda: gui.SettingsDialog(core, False, None),
        "prefx": lambda: gui.PreFXDialog(core, None),
        "soundboard": lambda: gui.SoundboardDialog(core, None),
        "hotkey": lambda: gui.HotkeyDialog(core, None, "Set hotkey"),
        "add_plugin": lambda: gui.AddPluginDialog([], None),
        "param_map": lambda: gui.PluginParamMapDialog(slot, core, None),
        "setup_assistant": lambda: SetupAssistantDialog(core, None),
        "about": lambda: AboutDialog(None),
    }

    for skin in skins:
        for theme in themes:
            _apply(app, skin, theme)
            contrast = _contrast(theme)

            win = gui.MainWindow(core)
            show_offscreen(win)
            if core.cfg.chains and getattr(win, "chain_list", None) is not None:
                win.chain_list.setCurrentRow(0)
                app.processEvents()
            hint = win.minimumSizeHint().expandedTo(win.minimumSize())
            for w, h in sizes:
                win.resize(w, h)
                app.processEvents()
                key = f"main|{skin}|{theme}|{w}x{h}"
                entry = {"min_size": [hint.width(), hint.height()]}
                entry.update(_inspect(win, contrast))
                report[key] = entry
                images[key] = [snap(win, key)]
            win.close()
            win.deleteLater()

            for screen in DIALOGS:
                dlg = builders[screen]()
                show_offscreen(dlg)
                key = f"{screen}|{skin}|{theme}|{dlg.width()}x{dlg.height()}"
                hint = dlg.minimumSizeHint().expandedTo(dlg.minimumSize())
                entry = {"min_size": [hint.width(), hint.height()],
                         "overflow": [], "clipped_text": [], "untiered_buttons": [],
                         "contrast": contrast}
                images[key] = []
                for suffix, _label in _states(dlg):
                    app.processEvents()
                    _merge(entry, _inspect(dlg, contrast))
                    images[key].append(snap(dlg, key + suffix))
                report[key] = entry
                dlg.close()
                dlg.deleteLater()
            app.processEvents()

    core.shutdown()
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (out / "index.html").write_text(render_index(report, images), encoding="utf-8")
    return report


def render_index(report: dict, images: dict) -> str:
    rows = []
    for key, entry in report.items():
        counts = "".join(f"<td>{len(entry[n])}</td>" for n in _LISTS)
        rows.append(f"<tr><td>{html.escape(key)}</td>"
                    f"<td>{entry['min_size'][0]}x{entry['min_size'][1]}</td>{counts}</tr>")
    cards = []
    for key, files in images.items():
        imgs = "".join(f'<a href="{f}"><img src="{f}" loading="lazy"></a>' for f in files)
        cards.append(f"<figure><figcaption>{html.escape(key)}</figcaption>{imgs}</figure>")
    head = "".join(f"<th>{n}</th>" for n in _LISTS)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Mandible UI gallery</title>"
        "<style>body{font-family:sans-serif;margin:16px}table{border-collapse:collapse}"
        "td,th{border:1px solid #999;padding:2px 8px;text-align:left}"
        "figure{display:inline-block;vertical-align:top;margin:8px;max-width:520px}"
        "figure img{max-width:500px;display:block;margin-bottom:4px;border:1px solid #999}"
        "</style></head><body><h1>Mandible UI gallery</h1>"
        f"<table><tr><th>screen|skin|theme|size</th><th>min size</th>{head}</tr>{''.join(rows)}</table>"
        f"<h2>Screens</h2>{''.join(cards)}</body></html>")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--skins", default=DEFAULT_SKINS)
    ap.add_argument("--themes", default=DEFAULT_THEMES)
    ap.add_argument("--sizes", default=DEFAULT_SIZES)
    ap.add_argument("--user-looks", default=None,
                    help="directory of user looks (ignored until the Look loader lands)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any overflow, clipped-text or contrast list is non-empty")
    args = ap.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    appdata = tempfile.mkdtemp(prefix="mandible-gallery-")
    os.environ["APPDATA"] = appdata
    sys.path.insert(0, str(ROOT))
    if args.user_looks:
        print("warning: --user-looks is ignored (no user-look loader yet)", file=sys.stderr)

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    report = run_gallery(out, args.skins.split(","), args.themes.split(","),
                         parse_sizes(args.sizes))
    problems = {n: sum(len(e[n]) for e in report.values()) for n in _LISTS}
    print(f"{len(report)} screens in {time.perf_counter() - started:.1f}s -> {out}")
    print("totals: " + ", ".join(f"{n}={c}" for n, c in problems.items()))
    shutil.rmtree(appdata, ignore_errors=True)
    code = 1 if args.strict and (problems["overflow"] or problems["clipped_text"]
                                 or problems["contrast"]) else 0
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
