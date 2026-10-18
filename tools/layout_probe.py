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
        "strips_collapsed": bool, "header_left_width": int,
        "flow_entry_points": {"prefx": [...], "sb": [...], "lim": [...]},
        "rack_viewport_width": int, "plugin_cards": [{"width", "right", "actions_right"}],
        "cards_past_viewport": [...]}},
        "steps": [{"step": "<WxH>", ...same keys...}, ...]}}}

``--sizes`` are visited in the order given (repeats allowed), each measured after the layout
settles, so a descending list checks that the window also survives shrinking (Task 9b: cards
used to keep their old width). ``sizes`` keeps the last measurement per size; ``steps`` all of
them in order. ``cards_past_viewport`` lists plugin and chain cards (or a plugin card's action
cluster) whose right edge lies past their list's viewport.

``--scenario long_names`` renames the first chain to 60 characters, gives its first plugin a
long display name and sets a non-Latin input device name before the window is built.
``--scenario running`` fills the header with run-time texts after the window is built, as
if audio had started: the widest reserved readout texts (sample rate, buffer, latency, every
driver name) with the power button's on text and Stop loop, then oversize values that must elide.
``--scenario many_knobs`` maps twelve parameters onto the first chain's first plugin (a stub
instance with twelve parameters), so its card shows the most knobs a card can hold.
``--strict`` exits 1 when any size reports overflow, clipped text, an elided label without
its full text in the tooltip, or a window that could not shrink to the requested size.

``--mode standard`` measures one skin (the first of ``--skins``) against the spec's "same
standard" checklist instead: for every theme in ``--themes``, the main window at every size
and every dialog (each section / tab / wizard page, at its default size and again at its
minimum size), contrast, and the live switch into the skin::

    {"platform": ..., "skin": id, "themes": {"<theme>": {"contrast": [...],
        "screens": {"main|<WxH>" | "<dialog>": {"size", "min_size", "overflow",
            "clipped_text", "elided_without_tooltip", "untiered_buttons", "multiple_primaries",
            "off_scale_spacing",
            "unnamed_icon_controls", "small_painted_text", "painted_text_count"}}}},
     "switch": {"ms": [...], "errors": [...], "warmup_rounds": n, "median_ms": x, "max_ms": y}}

``--mode switch`` only times the live look switch into one skin (the first of ``--skins``)
in every theme in ``--themes``, in a fresh process. Run one process per skin: Qt state
accumulates, and the third skin measured in one process is ~35% slower than the first, which
is why the 150 ms limit is asserted on fresh processes::

    {"platform": ..., "skin": id, "switch": {"ms": [...], "errors": [...], "warmup_rounds": n,
                                             "median_ms": x, "max_ms": y}}
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


MANY_KNOBS = 12   # more parameters than a card shows knobs (plugin_card.MAX_CARD_KNOBS)


class _StubParam:
    def __init__(self, i: int):
        self.name = f"Parameter {i + 1}"
        self.raw_value = 0.5
        self.string_value = f"{i * 10} %"
        self.units = ""


class _StubPlugin:
    """Stands in for a loaded VST3 instance with ``MANY_KNOBS`` parameters (never processed:
    the probe's engine is stopped)."""

    reported_latency_samples = 0

    def __init__(self):
        self.parameters = {f"param_{i}": _StubParam(i) for i in range(MANY_KNOBS)}


def apply_scenario(core, scenario: str) -> None:
    if scenario == "long_names":
        chain = core.cfg.chains[0]
        chain.name = LONG_CHAIN_NAME
        chain.plugins[0].display_name = LONG_PLUGIN_NAME
        core.cfg.audio.input_device = NON_LATIN_DEVICE
    elif scenario == "many_knobs":
        slot = core.cfg.chains[0].plugins[0]
        stub = _StubPlugin()
        slot._instance = stub
        slot.mapped_params = list(stub.parameters)
    elif scenario not in ("sample", "running"):
        raise ValueError(f"unknown scenario {scenario!r}")


def _widest(widget, samples) -> str:
    fm = widget.fontMetrics()
    return max(samples, key=fm.horizontalAdvance)


def apply_window_scenario(win, scenario: str) -> None:
    """Scenarios that change the built window: ``running`` shows the widest run-time texts."""
    if scenario != "running":
        return
    from mandible.ui.widgets.base import set_style_property
    from mandible.ui.widgets.header import (AUDITION_TEXTS, POWER_ON_TEXT, READOUT_OVERSIZE,
                                            READOUT_SAMPLES)

    h = win.header
    fields = h.readout_fields()
    for key, label in fields.items():
        label.setText(_widest(label, READOUT_SAMPLES[key]))
        if label.is_elided():
            raise AssertionError(f"reserved readout text elides: {label.full_text()!r}")
    # Oversize values elide (with the full text in the tooltip) instead of growing the zone;
    # sample rate and buffer stay oversize for the measurements.
    for key in ("sr", "buf"):
        fields[key].setText(READOUT_OVERSIZE[key])
    set_style_property(h.vfd_stat, "running", True)
    # Texts and checked states only: no signal may reach the audio engine.
    for button in (win.power, win.monitor):
        button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(False)
    win.power.setText(POWER_ON_TEXT)
    win.audition_btn.setText(AUDITION_TEXTS[-1])


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


def _cards_fit(win) -> dict:
    """Card geometry relative to the rack and chain lists' viewports."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QWidget

    out = {"rack_viewport_width": 0, "plugin_cards": [], "cards_past_viewport": []}
    for list_name, view in (("rack", win.editor.plugins), ("chains", win.chain_list)):
        vp = view.viewport()
        vw = vp.width()
        if list_name == "rack":
            out["rack_viewport_width"] = vw
        for i in range(view.count()):
            card = view.itemWidget(view.item(i))
            if card is None:
                continue
            right = card.geometry().right()
            entry = {"width": card.width(), "right": right}
            actions = getattr(card, "actions", None)   # PluginRackCard's action cluster
            if isinstance(actions, QWidget) and actions.isVisible():
                entry["actions_right"] = actions.mapTo(vp, QPoint(actions.width() - 1, 0)).x()
            if list_name == "rack":
                out["plugin_cards"].append(entry)
            limit = vw - 1
            if right > limit or entry.get("actions_right", 0) > limit:
                out["cards_past_viewport"].append(
                    f"{list_name}[{i}] right={right} actions_right={entry.get('actions_right')}"
                    f" viewport_width={vw}")
    return out


def measure(win, app, w: int, h: int) -> dict:
    from mandible.ui import inspect as ins

    win.resize(w, h)
    sys.path.insert(0, str(ROOT / "tools"))
    from ui_gallery import settle

    settle(win)
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
        "header_left_width": header.left.width(),
        "flow_entry_points": header.flow_entry_points(),
        **_cards_fit(win),
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
            gallery._apply(app, skin, theme, core)
            win = gallery.build_main_window(core)
            try:
                if core.cfg.chains:
                    win.chain_list.setCurrentRow(0)
                    app.processEvents()
                apply_window_scenario(win, scenario)
                app.processEvents()
                hint = win.minimumSizeHint().expandedTo(win.minimumSize())
                entry = {"min_size": [hint.width(), hint.height()], "sizes": {}, "steps": []}
                for w, h in sizes:
                    m = measure(win, app, w, h)
                    entry["sizes"][f"{w}x{h}"] = m
                    entry["steps"].append({"step": f"{w}x{h}", **m})
                report["skins"][skin] = entry
            finally:
                gallery.dispose_main_window(win)
    finally:
        core.shutdown()
    return report


def _standard_lists(widget, allowed) -> dict:
    from mandible.ui import inspect as ins

    _elided_texts, missing = _elided(widget)
    painted = ins.painted_text_sizes(widget)
    return {
        "overflow": [dataclasses.asdict(o) for o in ins.find_overflow(widget)],
        "clipped_text": ins.find_clipped_text(widget),
        "elided_without_tooltip": missing,
        "untiered_buttons": ins.untiered_buttons(widget),
        "multiple_primaries": ins.extra_primary_buttons(widget),
        "off_scale_spacing": ins.off_scale_spacing(widget, allowed),
        "unnamed_icon_controls": ins.unnamed_icon_controls(widget),
        "small_painted_text": sorted({f"{cls} {text!r} {px:g}px" for cls, text, px in painted
                                      if px < ins.MIN_TEXT_PX}),
        "painted_text_count": len(painted),
    }


def _merge_lists(into: dict, more: dict) -> None:
    for key, value in more.items():
        if isinstance(value, list):
            have = into.setdefault(key, [])
            have.extend(v for v in value if v not in have)
        elif key == "painted_text_count":
            into[key] = into.get(key, 0) + value


def _time_switch(app, core, gallery, skin: str, themes: list[str], rounds: int = 3,
                 warmup: int = 1) -> dict:
    """Switch live into ``skin`` from every other built-in skin, in every theme, on a shown
    main window: milliseconds per switch, layout and repaint included. ``warmup`` untimed
    rounds come first (style and font caches, first-paint costs); then ``rounds`` timed ones.
    ``median_ms`` and ``max_ms`` summarise the timed switches."""
    import statistics
    import time

    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look, set_look

    result: dict = {"ms": [], "errors": [], "warmup_rounds": warmup}
    win = gallery.build_main_window(core)
    try:
        win.resize(1280, 720)
        gallery.settle(win)
        others = [s for s in BUILTIN_SKINS if s != skin] or [skin]
        for rnd in range(warmup + rounds):
            timed = rnd >= warmup
            for theme in themes:
                for other in others:
                    try:
                        set_look(Look(BUILTIN_PALETTES[theme], BUILTIN_SKINS[other]))
                        app.sendPostedEvents()
                        t0 = time.perf_counter()
                        set_look(Look(BUILTIN_PALETTES[theme], BUILTIN_SKINS[skin]))
                        app.sendPostedEvents()   # layout + repaint, no timers
                        if timed:
                            result["ms"].append(round((time.perf_counter() - t0) * 1000.0, 2))
                    except Exception as exc:  # noqa: BLE001 - reported
                        result["errors"].append(
                            f"{other}->{skin} ({theme}): {type(exc).__name__}: {exc}")
    finally:
        gallery.dispose_main_window(win)
    if result["ms"]:
        result["median_ms"] = round(statistics.median(result["ms"]), 2)
        result["max_ms"] = max(result["ms"])
    return result


def run_switch(skin: str, themes: list[str]) -> dict:
    sys.path.insert(0, str(ROOT / "tools"))
    import ui_gallery as gallery
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from mandible.ui.sample_setup import build_sample_core

    app = QApplication.instance() or QApplication([])
    report: dict = {"platform": QGuiApplication.platformName(), "skin": skin}
    core = build_sample_core()
    try:
        core.cfg.close_to_tray = False
        gallery._apply(app, skin, themes[0], core)
        report["switch"] = _time_switch(app, core, gallery, skin, themes)
    finally:
        core.shutdown()
    return report


def run_standard(skin: str, themes: list[str], sizes: list[tuple[int, int]],
                 scenario: str) -> dict:
    sys.path.insert(0, str(ROOT / "tools"))
    import ui_gallery as gallery
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from mandible.ui import inspect as ins
    from mandible.ui.look import BUILTIN_SKINS
    from mandible.ui.sample_setup import build_sample_core

    compact = BUILTIN_SKINS[skin].elements.get("density") == "compact"
    allowed = ins.COMPACT_SPACING_SCALE if compact else ins.SPACING_SCALE
    app = QApplication.instance() or QApplication([])
    report: dict = {"platform": QGuiApplication.platformName(), "skin": skin, "themes": {}}
    core = build_sample_core()
    try:
        core.cfg.close_to_tray = False
        apply_scenario(core, scenario)
        for theme in themes:
            gallery._apply(app, skin, theme, core)
            entry: dict = {"contrast": gallery._contrast(theme), "screens": {}}
            win = gallery.build_main_window(core)
            try:
                if core.cfg.chains:
                    win.chain_list.setCurrentRow(0)
                    app.processEvents()
                for w, h in sizes:
                    win.resize(w, h)
                    gallery.settle(win)
                    hint = win.minimumSizeHint().expandedTo(win.minimumSize())
                    m = {"size": [win.width(), win.height()],
                         "min_size": [hint.width(), hint.height()]}
                    m.update(_standard_lists(win, allowed))
                    entry["screens"][f"main|{w}x{h}"] = m
            finally:
                gallery.dispose_main_window(win)
            for name, build in gallery.dialog_builders(core).items():
                dlg = build()
                try:
                    dlg.setAttribute(Qt.WA_DontShowOnScreen)
                    dlg.show()
                    app.processEvents()
                    hint = dlg.minimumSizeHint().expandedTo(dlg.minimumSize())
                    m = {"size": [dlg.width(), dlg.height()],
                         "min_size": [hint.width(), hint.height()]}
                    for _suffix, _label in gallery._states(dlg, review=True):
                        app.processEvents()
                        _merge_lists(m, _standard_lists(dlg, allowed))
                    # Again at the smallest size the dialog allows: pages must scroll, not clip.
                    dlg.resize(hint)
                    for _suffix, _label in gallery._states(dlg, review=True):
                        app.processEvents()
                        _merge_lists(m, _standard_lists(dlg, allowed))
                    entry["screens"][name] = m
                finally:
                    dlg.close()
                    dlg.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            report["themes"][theme] = entry
        report["switch"] = _time_switch(app, core, gallery, skin, themes)
    finally:
        core.shutdown()
    return report


def problems(report: dict) -> list[str]:
    found = []
    for skin, entry in report["skins"].items():
        for m in entry["steps"]:
            size = m["step"]
            want = [int(v) for v in size.split("x")]
            if m["size"] != want:
                found.append(f"{skin} {size}: window is {m['size']}")
            for name in ("overflow", "clipped_text", "elided_without_tooltip",
                         "cards_past_viewport"):
                if m[name]:
                    found.append(f"{skin} {size}: {name} {m[name]}")
            for key, where in m["flow_entry_points"].items():
                if not where:
                    found.append(f"{skin} {size}: flow action {key!r} has no visible entry point")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--skins", default="skeuomorphic,vintage,minimal")
    ap.add_argument("--theme", default="scarlet")
    ap.add_argument("--sizes", default="1024x640")
    ap.add_argument("--scenario", default="sample",
                    choices=("sample", "long_names", "running", "many_knobs"))
    ap.add_argument("--mode", default="layout", choices=("layout", "standard", "switch"))
    ap.add_argument("--themes", default="scarlet,cyan,stealth,amber",
                    help="--mode standard/switch: the themes to measure")
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
        if args.mode == "standard":
            report = run_standard(args.skins.split(",")[0], args.themes.split(","),
                                  parse_sizes(args.sizes), args.scenario)
            found = []
        elif args.mode == "switch":
            report = run_switch(args.skins.split(",")[0], args.themes.split(","))
            found = []
        else:
            report = run(args.skins.split(","), args.theme, parse_sizes(args.sizes), args.scenario)
            found = problems(report)
        pathlib.Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
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
