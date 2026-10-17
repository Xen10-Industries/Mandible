"""Render every Mandible screen off-screen and report layout problems.

Usage::

    python tools/ui_gallery.py --out DIR [--skins a,b] [--themes a,b]
        [--sizes 1024x640,1280x720,1920x1080] [--screens main,settings,...]
        [--user-looks DIR] [--strict]

Writes ``DIR/*.png`` (one per screen x skin x theme x size), ``DIR/index.html`` (a plain
page with the images and a table of report counts) and ``DIR/report.json``::

    {"<screen>|<skin>|<theme>|<WxH>": {"min_size": [w, h], "overflow": [...],
     "clipped_text": [...], "untiered_buttons": [...], "contrast": [...]}}

Screens are ``main`` plus one per dialog. Sizes apply to the main window, captured from the
largest down (so all but the first capture follow a shrink); dialogs are captured at their
default size. Nothing is ever shown on the desktop (WA_DontShowOnScreen),
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


def _apply(app, skin_id: str, theme_id: str, core=None) -> None:
    """Select a skin and theme: ``set_look`` (via ``apply_theme``, which also sets the app's
    Fusion style as ``main()`` does). With ``core``, its config follows (skin, theme, automatic
    frame), so Settings > Appearance shows the look that is actually being rendered."""
    from mandible.ui.app import apply_theme
    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look

    if core is not None:
        core.cfg.ui_skin, core.cfg.theme, core.cfg.chassis_frame = skin_id, theme_id, "auto"
    apply_theme(app, Look(BUILTIN_PALETTES[theme_id], BUILTIN_SKINS[skin_id]))


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
    """Yield ``(suffix, label)`` after switching the dialog to each section / tab / wizard
    page, starting from the first. Wizard pages are reached through the wizard's own
    navigation, so its step header is right."""
    from PySide6.QtWidgets import QTabWidget

    sections = getattr(dialog, "sections", None)
    if sections is not None and hasattr(dialog, "show_section"):
        ids = dialog.section_ids()
        dialog.show_section(ids[0])
        yield "", ""
        for i, sid in enumerate(ids[1:], 1):
            dialog.show_section(sid)
            yield f"_{sid}", sections.item(i).text()
        return
    if hasattr(dialog, "_go_to_step"):
        pages = getattr(dialog, "pages", None)
        dialog._go_to_step(0)
        yield "", ""
        for i in range(1, pages.count() if pages is not None else 1):
            dialog._go_to_step(i)
            yield f"_page{i}", f"step {i + 1}"
        return
    tabs = dialog.findChildren(QTabWidget)
    if tabs:
        tw = tabs[0]
        tw.setCurrentIndex(0)
        yield "", ""
        for i in range(1, tw.count()):
            tw.setCurrentIndex(i)
            yield f"_tab{i}", tw.tabText(i)
        return
    yield "", ""


def dialog_builders(core) -> dict:
    """``screen name -> zero-argument callable`` building that dialog on the sample core."""
    from mandible.ui.dialogs.about import AboutDialog
    from mandible.ui.dialogs.add_plugin import AddPluginDialog
    from mandible.ui.dialogs.hotkey import HotkeyDialog
    from mandible.ui.dialogs.param_map import PluginParamMapDialog
    from mandible.ui.dialogs.prefx import PreFXDialog
    from mandible.ui.dialogs.settings import SettingsDialog
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog
    from mandible.ui.dialogs.soundboard import SoundboardDialog

    slot = core.cfg.chains[0].plugins[0]
    return {
        "settings": lambda: SettingsDialog(core, False, None),
        "prefx": lambda: PreFXDialog(core, None),
        "soundboard": lambda: SoundboardDialog(core, None),
        "hotkey": lambda: HotkeyDialog(core, None, "Set hotkey"),
        "add_plugin": lambda: AddPluginDialog([], None),
        "param_map": lambda: PluginParamMapDialog(slot, core, None),
        "setup_assistant": lambda: SetupAssistantDialog(core, None),
        "about": lambda: AboutDialog(None),
    }


def build_main_window(core):
    """A MainWindow that never touches the desktop: shown with WA_DontShowOnScreen and with no
    system tray icon (``show_tray=False``; a shown tray icon ignores WA_DontShowOnScreen and
    would land on the taskbar)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from mandible.ui.main_window import MainWindow

    win = MainWindow(core, show_tray=False)
    win.tray.hide()
    win.setAttribute(Qt.WA_DontShowOnScreen)
    win.show()
    QApplication.instance().processEvents()
    freeze_main_window(win)
    return win


def freeze_main_window(win) -> None:
    """Make captures deterministic: stop the meter and status timers (a status tick landing
    between two captures changed the readout texts) and drive one status update by hand
    (the sample engine is stopped, so the readout says STOPPED / DSP: OFF)."""
    from PySide6.QtWidgets import QApplication

    for name in ("meter_timer", "status_timer"):
        timer = getattr(win, name, None)
        if timer is not None:
            timer.stop()
    win._update_status()
    QApplication.instance().processEvents()


def settle(win, passes: int = 3) -> None:
    """Let a resize finish: the header's breakpoints (folding, flow-strip mode, MORE) change
    widgets' visibility, which re-lays the window out over a few event-loop passes."""
    from PySide6.QtWidgets import QApplication

    for _ in range(passes):
        QApplication.instance().processEvents()


def dispose_main_window(win) -> None:
    """Tear a gallery MainWindow down without ``close()`` (its closeEvent would hide to the
    tray and raise a toast) and without ``quit()`` (which shuts the shared core down)."""
    from PySide6.QtCore import QCoreApplication, QEvent

    for name in ("meter_timer", "status_timer"):
        timer = getattr(win, name, None)
        if timer is not None:
            timer.stop()
    win.tray.hide()
    win.hide()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _error_entry(exc: BaseException) -> dict:
    return {"error": f"{type(exc).__name__}: {exc}"}


def run_gallery(out: pathlib.Path, skins: list[str], themes: list[str],
                sizes: list[tuple[int, int]], screens: list[str] | None = None) -> dict:
    """Render the gallery into ``out`` and return the report. Needs a QApplication.

    A screen that raises is recorded as ``{"error": ...}`` and the run continues; the report
    and index are written even then. ``screens`` limits the run (default: ``main`` and every
    dialog).
    """
    screens = list(screens) if screens else ["main", *DIALOGS]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from mandible.ui.sample_setup import build_sample_core

    app = QApplication.instance() or QApplication([])
    report: dict[str, dict] = {}
    images: dict[str, list[str]] = {}
    core = build_sample_core()
    try:
        # Closing the main window must never hide to the tray and raise a toast.
        core.cfg.close_to_tray = False
        builders = dialog_builders(core)

        def snap(widget, name: str) -> str:
            app.processEvents()
            fname = name.replace("|", "__") + ".png"
            widget.grab().save(str(out / fname))
            return fname

        def show_offscreen(widget) -> None:
            widget.setAttribute(Qt.WA_DontShowOnScreen)
            widget.show()
            app.processEvents()

        def capture_main(skin: str, theme: str, contrast: list[dict]) -> None:
            win = build_main_window(core)
            try:
                if core.cfg.chains and getattr(win, "chain_list", None) is not None:
                    win.chain_list.setCurrentRow(0)
                    app.processEvents()
                hint = win.minimumSizeHint().expandedTo(win.minimumSize())
                # Largest first, so every later capture comes after a shrink: layouts that only
                # re-fit when growing (Task 9b: plugin cards kept their old width) show up.
                for w, h in sorted(sizes, key=lambda s: (s[0] * s[1], s), reverse=True):
                    win.resize(w, h)
                    settle(win)
                    key = f"main|{skin}|{theme}|{w}x{h}"
                    entry = {"min_size": [hint.width(), hint.height()]}
                    entry.update(_inspect(win, contrast))
                    report[key] = entry
                    images[key] = [snap(win, key)]
            finally:
                dispose_main_window(win)

        def capture_dialog(screen: str, skin: str, theme: str, contrast: list[dict]) -> None:
            dlg = builders[screen]()
            try:
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
            finally:
                dlg.close()
                dlg.deleteLater()

        for skin in skins:
            for theme in themes:
                try:
                    _apply(app, skin, theme, core)
                    contrast = _contrast(theme)
                except Exception as exc:  # noqa: BLE001 - report and keep going
                    report[f"main|{skin}|{theme}|all"] = _error_entry(exc)
                    continue
                if "main" in screens:
                    try:
                        capture_main(skin, theme, contrast)
                    except Exception as exc:  # noqa: BLE001
                        report[f"main|{skin}|{theme}|error"] = _error_entry(exc)
                for screen in (s for s in DIALOGS if s in screens):
                    try:
                        capture_dialog(screen, skin, theme, contrast)
                    except Exception as exc:  # noqa: BLE001
                        report[f"{screen}|{skin}|{theme}|error"] = _error_entry(exc)
                app.processEvents()
    finally:
        try:
            core.shutdown()
        finally:
            (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
            (out / "index.html").write_text(render_index(report, images), encoding="utf-8")
    return report


def render_index(report: dict, images: dict) -> str:
    rows = []
    for key, entry in report.items():
        if "error" in entry:
            span = len(_LISTS) + 1
            rows.append(f'<tr><td>{html.escape(key)}</td>'
                        f'<td colspan="{span}">ERROR: {html.escape(entry["error"])}</td></tr>')
            continue
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
    ap.add_argument("--screens", default=None,
                    help="comma-separated subset of: main," + ",".join(DIALOGS))
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
    code = 1
    try:
        report = run_gallery(out, args.skins.split(","), args.themes.split(","),
                             parse_sizes(args.sizes),
                             args.screens.split(",") if args.screens else None)
        problems = {n: sum(len(e.get(n, [])) for e in report.values()) for n in _LISTS}
        problems["errors"] = sum(1 for e in report.values() if "error" in e)
        print(f"{len(report)} screens in {time.perf_counter() - started:.1f}s -> {out}")
        print("totals: " + ", ".join(f"{n}={c}" for n, c in problems.items()))
        failing = (problems["overflow"] or problems["clipped_text"]
                   or problems["contrast"] or problems["errors"])
        code = 1 if args.strict and failing else 0
    finally:
        shutil.rmtree(appdata, ignore_errors=True)
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
