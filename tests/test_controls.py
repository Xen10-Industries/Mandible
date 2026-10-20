"""Control system (spec 7.7): icons, button tiers, status pills, type scale, brand mark."""
from __future__ import annotations

import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (QAbstractButton, QApplication, QLabel, QPushButton, QWidget)

from mandible.config import MidiBinding
from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look, current_look, set_look

TYPED_ICON = re.compile(r"^[<>▲▼xX✕+]$|[←-⇿☀-➿\U0001F300-\U0001FAFF]")
# Words that are written in capitals anyway (sentence case allows them).
ACRONYMS = {"MIDI", "ASIO", "WASAPI", "HTTP", "REST", "VST3", "CABLE"}
DIALOGS = ("settings", "prefx", "soundboard", "hotkey", "add_plugin", "param_map",
           "setup_assistant", "about", "updater")


@pytest.fixture
def look(qapp):
    before = current_look()
    from mandible.ui.app import apply_theme

    apply_theme(qapp, Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    yield current_look()
    set_look(before)


def _flush():
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _shown(w):
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.show()
    for _ in range(3):
        QApplication.processEvents()
    return w


def _font_px(w) -> float:
    """The pixel size ``w`` draws its text at (QSS sizes are px or pt)."""
    f = w.font()
    if f.pixelSize() > 0:
        return f.pixelSize()
    return f.pointSizeF() * w.logicalDpiY() / 72.0


def _opaque(img: QImage) -> int:
    return sum(1 for y in range(img.height()) for x in range(img.width())
               if QColor.fromRgba(img.pixel(x, y)).alpha() > 0)


def _colours(img: QImage) -> set[str]:
    return {QColor(img.pixel(x, y)).name() for y in range(img.height()) for x in range(img.width())
            if QColor.fromRgba(img.pixel(x, y)).alpha() == 255}


# ----------------------------------------------------------------------- icons

def test_icon_names_are_the_spec_set():
    from mandible.ui.icons import ICON_NAMES

    assert ICON_NAMES == ("power", "mic", "monitor", "panic", "settings", "help", "plus", "menu",
                          "up", "down", "remove", "map", "open_window", "play", "stop", "record",
                          "hotkey", "chevron_left", "chevron_right", "chevron_down")


@pytest.mark.parametrize("px", [16, 24])
def test_every_icon_renders_non_empty(qapp, px):
    from mandible.ui.icons import ICON_NAMES, STEP_ICON_NAMES, icon_pixmap

    for name in ICON_NAMES + STEP_ICON_NAMES:
        pm = icon_pixmap(name, "#ffffff", px)
        assert (pm.width(), pm.height()) == (px, px), name
        img = pm.toImage()
        painted = _opaque(img)
        # something is drawn, and it is a glyph rather than a filled square
        assert px * px * 0.06 < painted < px * px * 0.8, (name, painted)


def test_unknown_icon_raises(qapp):
    from mandible.ui.icons import icon, icon_pixmap

    with pytest.raises(KeyError):
        icon_pixmap("nope", "#ffffff", 16)
    with pytest.raises(KeyError):
        icon("nope")


def test_icon_uses_text_primary_and_follows_the_look(look):
    from mandible.ui.icons import icon
    from mandible.ui.widgets.buttons import make_button

    primary = look.palette.color("text.primary")
    assert primary in _colours(icon("plus").pixmap(24, 24).toImage())
    btn = make_button(icon="plus", tooltip="Add")
    stealth = Look(BUILTIN_PALETTES["stealth"], look.skin)
    set_look(stealth)
    colours = _colours(btn.icon().pixmap(24, 24).toImage())
    assert stealth.palette.color("text.primary") in colours and primary not in colours
    btn.deleteLater()
    _flush()


# --------------------------------------------------------------------- buttons

def test_make_button_tiers_and_validation(qapp):
    from mandible.ui.widgets.buttons import TIERS, make_button

    assert TIERS == ("primary", "secondary", "quiet", "danger")
    for tier in TIERS:
        b = make_button("Go", tier)
        assert isinstance(b, QPushButton) and b.property("tier") == tier
        b.deleteLater()
    with pytest.raises(ValueError):
        make_button("Go", "loud")
    with pytest.raises(ValueError):
        make_button(icon="plus")            # icon-only needs a tooltip
    b = make_button(icon="plus", tooltip="Add")
    assert b.toolTip() == "Add" and not b.icon().isNull() and b.text() == ""
    b.deleteLater()
    _flush()


@pytest.mark.parametrize("tier", ["primary", "secondary", "quiet", "danger"])
def test_disabled_tiered_button_renders_differently(look, tier):
    """Tier rules carry :disabled; nothing (an ID rule) may out-rank them."""
    from mandible.ui.widgets.buttons import make_button

    host = QWidget()
    a = make_button("Back", tier, icon="chevron_left", parent=host)
    b = make_button("Back", tier, icon="chevron_left", parent=host)
    a.setGeometry(0, 0, 100, 30)
    b.setGeometry(0, 40, 100, 30)
    b.setEnabled(False)
    _shown(host)
    assert host.grab(a.geometry()).toImage() != host.grab(b.geometry()).toImage()
    host.deleteLater()
    _flush()


@pytest.mark.parametrize("tier", ["primary", "secondary", "quiet", "danger"])
def test_focused_tiered_button_shows_the_focus_ring(look, tier):
    from PySide6.QtTest import QTest

    from mandible.ui.widgets.buttons import make_button

    host = QWidget()
    btn = make_button("Next", tier, parent=host)
    other = make_button("Other", "secondary", parent=host)
    btn.setGeometry(10, 10, 100, 30)
    other.setGeometry(10, 50, 100, 30)
    host.resize(120, 90)
    host.show()
    host.activateWindow()
    QTest.qWaitForWindowActive(host)
    other.setFocus()
    QApplication.processEvents()
    # grab through the host: the ring's gap shows the surface behind the button
    plain = host.grab(btn.geometry()).toImage()
    btn.setFocus()
    QApplication.processEvents()
    assert btn.hasFocus()
    focused = host.grab(btn.geometry()).toImage()
    ring = look.palette.color("focus.ring")
    assert ring in _colours(focused)
    assert plain != focused
    host.close()
    host.deleteLater()
    _flush()


def test_setup_assistant_back_button_looks_disabled_on_the_first_page(core, look):
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog

    dlg = _shown(SetupAssistantDialog(core, None))
    try:
        assert not dlg.back_btn.isEnabled()
        disabled = dlg.back_btn.grab().toImage()
        dlg.back_btn.setEnabled(True)
        QApplication.processEvents()
        assert dlg.back_btn.grab().toImage() != disabled
        assert dlg.back_btn.property("tier") and dlg.next_btn.property("tier") == "primary"
    finally:
        dlg._meter_timer.stop()
        dlg.deleteLater()
        _flush()


# ----------------------------------------------------------------- status pills

def test_status_pill_states_and_focus(look):
    from mandible.ui.widgets.buttons import StatusPill

    pill = StatusPill("Limiter on")
    assert isinstance(pill, QLabel) and not isinstance(pill, QAbstractButton)
    assert pill.objectName() == "statusPill" and pill.focusPolicy() == Qt.NoFocus
    for state in ("off", "on", "warn", "danger"):
        pill.set_state(state)
        assert pill.property("state") == state
    with pytest.raises(ValueError):
        pill.set_state("blinking")
    pill.deleteLater()
    _flush()


# ------------------------------------------------------------ every view checks

def _views(sample_core):
    """(name, top-level widget) for the main window and every dialog, shown off-screen."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from mandible.ui.dialogs.about import AboutDialog
    from mandible.ui.dialogs.updater import UpdateDialog
    from mandible.ui.dialogs.add_plugin import AddPluginDialog
    from mandible.ui.dialogs.hotkey import HotkeyDialog
    from mandible.ui.dialogs.param_map import PluginParamMapDialog
    from mandible.ui.dialogs.prefx import PreFXDialog
    from mandible.ui.dialogs.settings import SettingsDialog
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog
    from mandible.ui.dialogs.soundboard import SoundboardDialog
    from mandible.ui.main_window import MainWindow

    sample_core.cfg.close_to_tray = False
    sample_core.cfg.midi_bindings.append(MidiBinding(event_type="note_on", note_or_cc=60,
                                                     channel=0, action="mute"))
    slot = sample_core.cfg.chains[0].plugins[0]
    builders = {
        "main": lambda: MainWindow(sample_core, show_tray=False),
        "settings": lambda: SettingsDialog(sample_core, False, None),
        "prefx": lambda: PreFXDialog(sample_core, None),
        "soundboard": lambda: SoundboardDialog(sample_core, None),
        "hotkey": lambda: HotkeyDialog(sample_core, None, "Set hotkey"),
        "add_plugin": lambda: AddPluginDialog([], None),
        "param_map": lambda: PluginParamMapDialog(slot, sample_core, None),
        "setup_assistant": lambda: SetupAssistantDialog(sample_core, None),
        "about": lambda: AboutDialog(None),
        "updater": lambda: UpdateDialog(sample_core, None, auto_check=False),
    }
    return builders


def _dispose(name, w):
    if name == "main":
        w.meter_timer.stop()
        w.status_timer.stop()
        w._quitting = True
        w.tray.hide()
    if hasattr(w, "_meter_timer"):
        w._meter_timer.stop()
    w.hide()
    w.deleteLater()
    _flush()


@pytest.fixture
def each_view(sample_core, look):
    builders = _views(sample_core)

    def run(check):
        problems = {}
        for name, build in builders.items():
            w = build()
            try:
                if name == "main":
                    w.resize(1280, 720)
                _shown(w)
                found = check(name, w)
                if found:
                    problems[name] = found
            finally:
                _dispose(name, w)
        return problems

    return run


def test_every_button_has_a_tier(each_view):
    from mandible.ui.inspect import untiered_buttons

    assert each_view(lambda name, w: untiered_buttons(w)) == {}


def test_at_most_one_primary_button_per_view(each_view):
    def primaries(name, w):
        found = [b.text() or b.toolTip() for b in w.findChildren(QPushButton)
                 if b.property("tier") == "primary"]
        return found if len(found) > 1 else []

    assert each_view(primaries) == {}


def test_no_typed_characters_as_icons(each_view):
    def typed(name, w):
        return [b.text() for b in w.findChildren(QAbstractButton) if TYPED_ICON.search(b.text())]

    assert each_view(typed) == {}


def test_buttons_use_sentence_case(each_view):
    def shouting(name, w):
        out = []
        for b in w.findChildren(QAbstractButton):
            words = re.findall(r"[A-Za-z][A-Za-z0-9-]*", b.text().replace("&", ""))
            if any(len(x) >= 4 and x.isupper() and x not in ACRONYMS for x in words):
                out.append(b.text())
        return out

    assert each_view(shouting) == {}


def test_no_text_below_10px(each_view):
    def small(name, w):
        out = []
        for c in w.findChildren(QWidget):
            if isinstance(c, (QLabel, QAbstractButton)):
                c.ensurePolished()
                px = _font_px(c)
                if px < 10:
                    out.append(f"{type(c).__name__}#{c.objectName()} '{c.text()[:20]}' {px}px")
        return out

    assert each_view(small) == {}


def test_status_pills_are_never_focusable(each_view):
    from mandible.ui.widgets.buttons import StatusPill

    def pills(name, w):
        found = w.findChildren(StatusPill)
        if name == "main":
            assert found, "the flow strip and plugin badges are status pills"
        return [p.text() for p in found if p.focusPolicy() != Qt.NoFocus]

    assert each_view(pills) == {}


def test_stylesheet_font_sizes_are_on_the_type_scale():
    from mandible.ui.stylesheet import build_qss

    for skin in BUILTIN_SKINS.values():
        qss = build_qss(Look(BUILTIN_PALETTES["scarlet"], skin))
        sizes = re.findall(r"font-size:\s*([0-9.]+)(\w+)", qss)
        assert sizes
        bad = [f"{v}{u}" for v, u in sizes if u != "px" or float(v) not in (11, 13, 16)]
        assert bad == [], bad


def test_buttons_have_no_letter_spacing():
    """Uppercase with letter-spacing is for section labels and readouts only."""
    from mandible.ui.stylesheet import build_qss

    qss = build_qss(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", qss):
        if "QPushButton" in m.group(1) or "QToolButton" in m.group(1):
            assert "letter-spacing" not in m.group(2), m.group(1).strip()


# ------------------------------------------------------------------ brand mark

def _mark_image(look_, px, dpr):
    from mandible import branding

    return branding.render_mark(round(px * dpr), look_.palette.color("text.primary")).convertToFormat(
        QImage.Format_ARGB32)


def test_header_left_zone_shows_the_brand_mark(sample_core, look):
    from mandible.ui.widgets.header import HeaderBar

    header = _shown(HeaderBar(sample_core))
    try:
        mark = header.left.findChild(QLabel, "brandMark")
        assert mark is not None and mark.isVisible()
        px, dpr = mark.mark_px, mark.devicePixelRatioF()
        assert mark.pixmap().toImage().convertToFormat(QImage.Format_ARGB32) == _mark_image(look, px, dpr)
        amber = Look(BUILTIN_PALETTES["amber"], look.skin)
        set_look(amber)
        assert mark.pixmap().toImage().convertToFormat(QImage.Format_ARGB32) == _mark_image(amber, px, dpr)
    finally:
        header.deleteLater()
        _flush()


# ----------------------------------------------------------------- breakpoints

def test_header_breakpoints_are_pinned():
    from mandible.ui.widgets import header as H

    assert (H.FLOW_HIDDEN_BELOW, H.FLOW_ICONS_BELOW, H.ACTIONS_OVERFLOW_BELOW) == (1100, 1400, 1180)
    assert H.flow_mode_for_width(H.FLOW_HIDDEN_BELOW - 1) == "hidden"
    assert H.flow_mode_for_width(H.FLOW_HIDDEN_BELOW) == "icons"
    assert H.flow_mode_for_width(H.FLOW_ICONS_BELOW - 1) == "icons"
    assert H.flow_mode_for_width(H.FLOW_ICONS_BELOW) == "full"


def test_flow_strip_icons_mode_shows_icons_with_tooltips(sample_core, look):
    from mandible.ui.widgets.flow_strip import SignalFlowStrip

    strip = SignalFlowStrip(sample_core)
    try:
        for key, w in strip._icons.items():
            assert w.toolTip(), key
            if isinstance(w, QPushButton):
                assert not w.icon().isNull() and w.text() == "", key
            else:
                assert not w.pixmap().isNull() and w.text() == "", key
        for arrow in strip._arrows:
            assert arrow.text() == "" and not arrow.pixmap().isNull()
    finally:
        strip.deleteLater()
        _flush()


def test_add_plugin_dialog_shows_built_ins_or_vst3_only(qapp, monkeypatch):
    from mandible import plugins as P
    from mandible.ui.dialogs.add_plugin import AddPluginDialog

    catalog = [
        {"name": "Lo-Fi Bitcrush", "path": "internal:bitcrush", "vendor": "Mandible DSP"},
        {"name": "Mandible Pitch & Formant", "path": "internal:pitch_formant", "vendor": "Mandible DSP"},
        {"name": "Some Reverb", "path": "C:/VST3/Some Reverb.vst3", "vendor": "Acme"},
    ]
    monkeypatch.setattr(P, "get_cached_plugins", lambda *_a, **_k: [dict(c) for c in catalog])
    dlg = AddPluginDialog([], None)
    try:
        def visible():
            return {dlg.list.item(i).data(Qt.UserRole) for i in range(dlg.list.count())
                    if not dlg.list.item(i).isHidden()}

        assert visible() == {c["path"] for c in catalog}
        dlg.show_source("builtin")
        assert visible() == {"internal:bitcrush", "internal:pitch_formant"}
        dlg.search.setText("pitch")
        assert visible() == {"internal:pitch_formant"}
        dlg.search.clear()
        dlg.show_source("vst3")
        assert visible() == {"C:/VST3/Some Reverb.vst3"}
    finally:
        dlg.deleteLater()


def test_favorites_toggle_from_the_menu_persist_and_survive_a_rescan(qapp, monkeypatch):
    from mandible import plugins as P
    from mandible.ui.dialogs.add_plugin import _FAVORITE_ROLE, AddPluginDialog

    reverb = "C:/VST3/Some Reverb.vst3"
    monkeypatch.setattr(P, "scan_vst3", lambda *_a, **_k: [("Some Reverb", reverb)])
    P.save_plugin_cache([])
    P.get_cached_plugins([])

    def rows(dlg):
        return [dlg.list.item(i) for i in range(dlg.list.count())]

    dlg = AddPluginDialog([], None)
    try:
        assert dlg.windowTitle() == "Insert plugin"
        item = next(it for it in rows(dlg) if it.data(Qt.UserRole) == reverb)
        assert not item.data(_FAVORITE_ROLE)
        assert not item.icon().isNull()                       # outline star
        assert "[FAV]" not in "".join(it.text() for it in rows(dlg))
        dlg.toggle_favorite(item)
        assert item.data(_FAVORITE_ROLE)
    finally:
        dlg.deleteLater()

    assert P.load_plugin_cache()[reverb]["favorite"] is True
    P.get_cached_plugins([], force_rescan=True)               # Rescan keeps favorites
    assert P.load_plugin_cache()[reverb]["favorite"] is True

    dlg = AddPluginDialog([], None)
    try:
        order = [(bool(it.data(_FAVORITE_ROLE)), it.data(Qt.UserRole)) for it in rows(dlg)]
        assert order == sorted(order, key=lambda r: not r[0])  # favorites first
        assert (True, reverb) in order
        dlg.toggle_favorite(next(it for it in rows(dlg) if it.data(Qt.UserRole) == reverb))
    finally:
        dlg.deleteLater()
    assert P.load_plugin_cache()[reverb]["favorite"] is False
