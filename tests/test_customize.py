"""The Customize panel (Task 19): elements, colours, save / save as / revert, export / import and
delete of user skins and themes, docked to the main window as the live preview."""
from __future__ import annotations

import json
import threading

import pytest

from mandible.ui import user_looks as UL
from mandible.ui.look import (BUILTIN_PALETTES, BUILTIN_SKINS, PALETTE_TOKENS, Look, current_look,
                              look_from_config, set_look)
from mandible.ui.palette_gen import CONTRAST_PAIRS, contrast_ratio


@pytest.fixture(autouse=True)
def looks_dirs(tmp_path, monkeypatch):
    """Per-test skins/themes folders and config file (never the real profile)."""
    from mandible import config

    monkeypatch.setattr(UL, "SKINS_DIR", tmp_path / "skins")
    monkeypatch.setattr(UL, "THEMES_DIR", tmp_path / "themes")
    monkeypatch.setattr(config, "APP_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "app" / "config.json"))
    (tmp_path / "app").mkdir()
    return tmp_path


@pytest.fixture
def scarlet(qapp):
    before = current_look()
    set_look(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    yield current_look()
    set_look(before)


@pytest.fixture
def panel(core, scarlet):
    """A Customize panel on the default look, shown off-screen (never on the desktop)."""
    from PySide6.QtCore import Qt

    from mandible.ui.dialogs.customize import CustomizePanel

    made = []

    def make():
        p = CustomizePanel(core, None)
        p.setAttribute(Qt.WA_DontShowOnScreen)
        p.show()
        made.append(p)
        return p

    yield make()
    for p in made:
        p._discard_and_hide()
        p.deleteLater()
    _flush_deletes()


def _flush_deletes():
    """Delete deleteLater()'d widgets now: no event loop runs between tests, and live leftovers
    would be restyled by every later look switch."""
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _settings(core):
    from mandible.ui.dialogs.settings import SettingsDialog

    return SettingsDialog(core, False, None, initial_section="appearance")


def _skin_ids(dlg) -> list[str]:
    return [dlg.skin_combo.itemData(i) for i in range(dlg.skin_combo.count())]


def _theme_ids(dlg) -> list[str]:
    return [dlg.theme_combo.itemData(i) for i in range(dlg.theme_combo.count())]


def _visible_primaries(panel) -> list[str]:
    from PySide6.QtWidgets import QPushButton

    return [b.text() for b in panel.findChildren(QPushButton)
            if b.property("tier") == "primary" and b.isVisible()]


# ------------------------------------------------------------------- elements

def test_select_variant_updates_current_look_immediately(panel):
    assert current_look().skin.elements["switch"] == "bat_toggle"
    panel.select_variant("switch", "rocker")
    assert current_look().skin.elements["switch"] == "rocker"
    assert current_look().skin.elements["knob"] == "machined"       # other slots untouched
    assert panel.is_dirty()
    assert panel.tiles[("switch", "rocker")].isChecked()
    assert not panel.tiles[("switch", "bat_toggle")].isChecked()


def test_every_slot_offers_every_registered_variant_as_a_tile(panel):
    from mandible.ui.elements import registry
    from mandible.ui.look import SKIN_SLOTS

    for slot in SKIN_SLOTS:
        for variant in registry.variants(slot):
            tile = panel.tiles[(slot, variant)]
            assert tile.text() == registry.label(slot, variant)
    with pytest.raises(ValueError):
        panel.select_variant("switch", "laser")


def test_tile_click_selects_the_variant(panel):
    panel.tiles[("meter", "smooth_bar")].click()
    assert current_look().skin.elements["meter"] == "smooth_bar"


def test_tile_thumbnails_render_once_per_look_change(panel, monkeypatch):
    """R7: thumbnails are cached per look, not rendered on every paint."""
    from mandible.ui.dialogs import customize as mod

    calls = []
    real = mod.render_thumbnail
    monkeypatch.setattr(mod, "render_thumbnail", lambda *a, **k: (calls.append(a[:2]), real(*a, **k))[1])
    panel.select_variant("knob", "flat_ring")            # a new look: the cache starts over
    for tile in panel.tiles.values():
        tile.grab()
    first = len(calls)
    assert first == len(panel.tiles)
    for _ in range(2):
        for tile in panel.tiles.values():
            tile.grab()
    assert len(calls) == first                           # repaints reuse the cache
    panel.select_variant("knob", "machined")
    for tile in panel.tiles.values():
        tile.grab()
    assert len(calls) == 2 * first


# ------------------------------------------------------------------- save / save as (R1)

def test_save_is_disabled_for_builtins_and_save_as_creates_a_user_skin(panel, core):
    got = []
    panel.saved.connect(got.append)
    panel.select_variant("switch", "rocker")
    assert not panel.save_btn.isEnabled()
    assert panel.save_as_btn.isEnabled()
    assert panel.save_as("Night") == "user:night"
    assert got == ["user:night"]
    assert core.cfg.ui_skin == "user:night"
    assert core.cfg.theme == "scarlet"                   # colours untouched: no theme written
    assert not UL.THEMES_DIR.exists() or not list(UL.THEMES_DIR.glob("*.json"))
    assert current_look().skin.id == "user:night"
    assert current_look().skin.elements["switch"] == "rocker"
    assert not panel.is_dirty()
    dlg = _settings(core)
    try:
        assert "user:night" in _skin_ids(dlg)
        assert dlg.skin_combo.currentData() == "user:night"
    finally:
        dlg.deleteLater()
        _flush_deletes()


def test_save_as_writes_a_theme_only_when_the_colours_changed(panel, core):
    panel.set_accent("#3366ff")
    skin_id = panel.save_as("Dusk")
    assert skin_id == "user:dusk"
    assert core.cfg.ui_skin == "user:dusk"
    assert core.cfg.theme.startswith("user:") and core.cfg.theme in UL.all_palettes()
    theme = UL.all_palettes()[core.cfg.theme]
    assert theme.name == "Dusk"
    assert dict(theme.colors) == dict(current_look().palette.colors)
    assert theme.source == {"accent": "#3366ff", "tint": "neutral"}


def test_save_overwrites_user_items_in_place(panel, core):
    got = []
    panel.select_variant("switch", "rocker")
    panel.save_as("Night")
    panel.saved.connect(got.append)
    assert not panel.save_btn.isEnabled()                # nothing changed yet
    panel.select_variant("knob", "flat_ring")
    assert panel.save_btn.isEnabled()
    panel.save()
    assert got == ["user:night"]
    on_disk = json.loads((UL.SKINS_DIR / "night.json").read_text(encoding="utf-8"))
    assert on_disk["name"] == "Night" and on_disk["elements"]["knob"] == "flat_ring"
    assert sorted(p.name for p in UL.SKINS_DIR.glob("*.json")) == ["night.json"]
    assert core.cfg.ui_skin == "user:night" and not panel.is_dirty()
    # a colour change would touch the built-in Scarlet theme: only Save as new is offered
    panel.set_accent("#22aa66")
    assert not panel.save_btn.isEnabled() and panel.save_as_btn.isEnabled()


def test_save_emits_the_theme_id_when_only_the_theme_changed(panel, core):
    panel.set_accent("#3366ff")
    panel.save_as("Dusk")
    theme_id = core.cfg.theme
    got = []
    panel.saved.connect(got.append)
    panel.set_tint("warm")
    assert panel.save_btn.isEnabled()
    panel.save()
    assert got == [theme_id]
    assert UL.all_palettes()[theme_id].source == {"accent": "#3366ff", "tint": "warm"}


def test_save_as_with_an_empty_name_shows_an_inline_error(panel, core):
    panel.select_variant("switch", "rocker")
    assert panel.save_as("   ") is None
    assert panel.message_label.isVisible() and panel.message_label.text()
    assert core.cfg.ui_skin == "skeuomorphic" and panel.is_dirty()


def test_revert_returns_to_the_last_saved_look(panel, scarlet):
    panel.select_variant("frame", "frameless")
    panel.set_accent("#22aa66")
    panel.revert()
    assert current_look() == scarlet and not panel.is_dirty()


def test_saved_look_is_current_after_a_restart(panel, core):
    from mandible.config import load_config

    panel.select_variant("switch", "rocker")
    panel.set_accent("#3366ff")
    panel.save_as("Night")
    saved = current_look()
    core.save_now()
    look = look_from_config(load_config())
    assert look.skin.id == "user:night" and look.palette.id == saved.palette.id
    assert dict(look.skin.elements) == dict(saved.skin.elements)
    assert dict(look.palette.colors) == dict(saved.palette.colors)


# ------------------------------------------------------------------- one primary (R6)

def test_exactly_one_primary_button_save_when_enabled_else_save_as(panel):
    assert _visible_primaries(panel) == ["Save as new"]
    panel.select_variant("switch", "rocker")
    assert _visible_primaries(panel) == ["Save as new"]
    panel.save_as("Night")
    assert _visible_primaries(panel) == ["Save as new"]
    panel.select_variant("knob", "flat_ring")
    assert _visible_primaries(panel) == ["Save"]
    panel.close()                                        # the unsaved-changes banner adds none
    assert panel.banner.isVisible()
    assert _visible_primaries(panel) == ["Save"]


# ------------------------------------------------------------------- colours (R9, C1, C2)

def test_black_accent_shows_adjusted_for_readability(panel):
    assert not panel.notice_label.isVisible()
    panel.set_accent("#000000")
    assert panel.notice_label.isVisible()
    assert panel.notice_label.text() == "Adjusted for readability"
    assert current_look().palette.color("accent") != "#000000"
    panel.set_accent("#e11d48")
    assert not panel.notice_label.isVisible()


def test_tints_derive_the_palette(panel):
    from mandible.ui.palette_gen import derive_colors

    panel.set_accent("#06b6d4")
    for tint in ("warm", "cool", "neutral", "#3366cc"):
        panel.set_tint(tint)
        assert dict(current_look().palette.colors) == derive_colors("#06b6d4", tint)[0]
    assert panel.tint_chips["custom"].isChecked() and not panel.tint_chips["neutral"].isChecked()
    panel.set_tint("neutral")
    assert panel.tint_chips["neutral"].isChecked() and not panel.tint_chips["custom"].isChecked()
    with pytest.raises(ValueError):
        panel.set_tint("sepia")


def test_accent_edits_reach_the_native_palette(panel):
    """C2: set_look refreshes the app QPalette, so QPalette-driven widgets (QColorDialog) follow."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QColorDialog

    panel.set_accent("#22aa66")
    accent = current_look().palette.color("accent")
    assert QApplication.palette().color(QPalette.Highlight).name() == accent
    dlg = QColorDialog()
    try:
        assert dlg.palette().color(QPalette.Highlight).name() == accent
    finally:
        dlg.deleteLater()
        _flush_deletes()


def test_advanced_mode_lists_every_token_with_its_contrast_ratio(panel):
    panel.set_advanced(True)
    assert list(panel.token_rows) == list(PALETTE_TOKENS)
    colors = current_look().palette.colors
    partnered = {t for t, _, _ in CONTRAST_PAIRS}
    for token, row in panel.token_rows.items():
        assert row.isVisible()
        assert row.hex_edit.text() == colors[token]
        if token in partnered:
            worst = min(contrast_ratio(colors[token], colors[p]) for t, p, _ in CONTRAST_PAIRS
                        if t == token)
            assert row.ratio_label.text() == f"{worst:.1f}:1", token
        else:
            assert row.ratio_label.text() == "—", token
        assert not row.badge.isVisible(), token          # Scarlet passes every pair
    panel.set_advanced(False)
    assert not any(r.isVisible() for r in panel.token_rows.values())


def test_contrast_pairs_cover_readout_and_accent_states():
    """C1: readout.text, accent.hover and accent.pressed now have partners."""
    pairs = {(t, p): target for t, p, target in CONTRAST_PAIRS}
    assert pairs[("readout.text", "bg.inset")] == 4.5
    assert pairs[("accent.hover", "bg.panel")] == 3.0
    assert pairs[("accent.pressed", "bg.panel")] == 3.0


def test_low_contrast_token_shows_a_warning_and_still_saves(panel, core):
    panel.set_advanced(True)
    panel.set_token("text.secondary", "#333333")
    row = panel.token_rows["text.secondary"]
    assert row.badge.isVisible()
    assert [t for t, r in panel.token_rows.items() if r.badge.isVisible()] == ["text.secondary"]
    assert current_look().palette.color("text.secondary") == "#333333"
    assert panel.save_as("Low") == "user:low"
    assert row.badge.isVisible()                         # the warning stays after saving
    theme = UL.all_palettes()[core.cfg.theme]
    assert theme.colors["text.secondary"] == "#333333" and theme.source is None


def test_set_token_rejects_a_bad_colour_inline(panel, scarlet):
    panel.set_advanced(True)
    panel.set_token("accent", "red")
    assert panel.message_label.isVisible()
    assert current_look() == scarlet


def test_gallery_states_fit_at_minimum_width_and_leave_the_panel_as_found(panel, scarlet):
    """Every captured state, the contrast-warning one included, fits the panel at its minimum
    width: no overflow, no clipped text, one primary button; afterwards nothing has changed."""
    from PySide6.QtWidgets import QApplication

    from mandible.ui import inspect as ins

    panel.resize(panel.minimumSizeHint().width(), 640)
    seen = []
    for suffix, _label in panel.gallery_states(warnings=True):
        QApplication.processEvents()
        seen.append(suffix)
        assert ins.find_overflow(panel) == [], suffix
        assert ins.find_clipped_text(panel) == [], suffix
        assert ins.untiered_buttons(panel) == [], suffix
        assert ins.extra_primary_buttons(panel) == [], suffix
        if suffix == "_warnings":
            assert panel.notice_label.isVisible()
            assert any(r.badge.isVisible() for r in panel.token_rows.values())
    assert seen == ["", "_colours", "_advanced", "_advanced_end", "_warnings", "_banner"]
    assert current_look() == scarlet and not panel.is_dirty() and not panel.banner.isVisible()
    assert not panel.advanced_box.isVisible()


def test_live_picker_edits_are_coalesced(panel, monkeypatch):
    """R7: dragging a picker previews through a short single-shot timer, so set_look runs at
    most once per tick however many colours arrive."""
    from PySide6.QtTest import QTest

    from mandible.ui.dialogs import customize as mod

    calls = []
    real = mod.set_look
    monkeypatch.setattr(mod, "set_look", lambda look, *a: (calls.append(look), real(look, *a)))
    for i in range(30):
        panel.preview_accent(f"#{20 + i:02x}66cc")
    assert calls == []
    QTest.qWait(mod.LIVE_EDIT_MS * 4)
    assert len(calls) == 1
    assert current_look().palette.color("accent") == calls[0].palette.color("accent")
    panel.set_advanced(True)
    for i in range(10):
        panel.preview_token("bg.panel", f"#1{i}1820")
    QTest.qWait(mod.LIVE_EDIT_MS * 4)
    assert len(calls) == 2 and current_look().palette.color("bg.panel") == "#191820"


# ------------------------------------------------------------------- unsaved changes (R8)

def test_closing_while_dirty_shows_the_banner_instead(panel, scarlet):
    panel.select_variant("switch", "rocker")
    assert panel.close() is False
    assert panel.isVisible() and panel.banner.isVisible()
    assert panel.banner_mode() == "close"
    panel.banner_keep_btn.click()                        # Keep editing
    assert not panel.banner.isVisible() and panel.isVisible() and panel.is_dirty()
    panel.close()
    panel.banner_discard_btn.click()                     # Discard: back to the saved look
    assert not panel.isVisible() and current_look() == scarlet and not panel.is_dirty()


def test_closing_a_clean_panel_just_closes(panel):
    assert panel.close() is True
    assert not panel.isVisible() and not panel.banner.isVisible()


def test_banner_save_saves_and_closes(panel, core):
    panel.select_variant("switch", "rocker")
    panel.name_edit.setText("Night")
    panel.close()
    panel.banner_save_btn.click()
    assert core.cfg.ui_skin == "user:night" and not panel.isVisible()


def test_switching_the_look_elsewhere_while_dirty_shows_the_banner(panel):
    panel.select_variant("switch", "rocker")
    draft = current_look()
    other = Look(BUILTIN_PALETTES["amber"], BUILTIN_SKINS["vintage"])
    set_look(other)                                      # e.g. Settings > Appearance
    assert panel.banner.isVisible() and panel.banner_mode() == "external"
    panel.banner_keep_btn.click()                        # Keep editing: the draft comes back
    assert current_look() == draft and panel.is_dirty()
    set_look(other)
    panel.banner_discard_btn.click()                     # Discard: adopt the new look
    assert current_look() == other and not panel.is_dirty()
    assert panel.tiles[("switch", "rocker")].isChecked()  # vintage's own switch


def test_switching_the_look_elsewhere_when_clean_follows_it(panel):
    other = Look(BUILTIN_PALETTES["cyan"], BUILTIN_SKINS["minimal"])
    set_look(other)
    assert not panel.banner.isVisible() and not panel.is_dirty()
    assert panel.tiles[("switch", "pill")].isChecked()
    panel.select_variant("switch", "rocker")
    panel.revert()
    assert current_look() == other


# ------------------------------------------------------------------- delete (R2)

def test_delete_is_for_user_items_only_and_confirms_inline(panel, core):
    assert not panel.delete_btn.isEnabled()
    panel.select_variant("switch", "rocker")
    panel.save_as("Night")
    assert panel.delete_btn.isEnabled()
    panel.delete_btn.click()                             # asks first, inline
    assert panel.banner.isVisible() and panel.banner_mode() == "delete"
    assert (UL.SKINS_DIR / "night.json").exists()
    panel.banner_delete_btn.click()
    assert not (UL.SKINS_DIR / "night.json").exists()
    assert core.cfg.ui_skin == "skeuomorphic"
    assert current_look().skin.id == "skeuomorphic" and not panel.delete_btn.isEnabled()


def test_delete_removes_the_user_theme_when_the_skin_is_built_in(panel, core):
    panel.set_accent("#3366ff")
    panel.save_as("Dusk")
    theme_id = core.cfg.theme
    panel.delete()                                       # the user skin goes first
    assert core.cfg.ui_skin == "skeuomorphic" and core.cfg.theme == theme_id
    panel.delete()                                       # then the theme
    assert core.cfg.theme == "scarlet" and theme_id not in UL.all_palettes()
    assert current_look().palette.id == "scarlet"


# ------------------------------------------------------------------- export / import (R3)

def test_export_and_import_round_trip(panel, core, tmp_path):
    panel.select_variant("knob", "flat_ring")
    panel.set_accent("#3366ff")
    draft = current_look()
    skin_file, theme_file = tmp_path / "out.mandibleskin", tmp_path / "out.mandibletheme"
    panel.export(skin_file)
    panel.export(theme_file)
    assert json.loads(skin_file.read_text(encoding="utf-8"))["format"] == "Mandible.Skin"
    assert json.loads(theme_file.read_text(encoding="utf-8"))["format"] == "Mandible.Theme"
    panel.revert()

    panel.import_file(skin_file)
    assert core.cfg.ui_skin.startswith("user:")
    assert current_look().skin.id == core.cfg.ui_skin
    assert dict(current_look().skin.elements) == dict(draft.skin.elements)
    panel.import_file(theme_file)
    assert core.cfg.theme.startswith("user:")
    assert dict(current_look().palette.colors) == dict(draft.palette.colors)
    assert not panel.is_dirty()


def test_import_errors_show_inline_and_change_nothing(panel, core, tmp_path, scarlet):
    bad = tmp_path / "broken.mandibleskin"
    bad.write_text("{ not json", encoding="utf-8")
    panel.import_file(bad)
    assert panel.message_label.isVisible()
    assert "not a valid JSON file" in panel.message_label.text()
    assert core.cfg.ui_skin == "skeuomorphic" and current_look() == scarlet
    assert not UL.SKINS_DIR.exists() or not list(UL.SKINS_DIR.glob("*.json"))
    wrong = tmp_path / "theme.mandibleskin"
    wrong.write_text(json.dumps({"format": "Mandible.Theme", "version": 1}), encoding="utf-8")
    panel.import_file(wrong)
    assert "not a Mandible skin file" in panel.message_label.text()


def test_import_dispatches_by_format_for_other_extensions(panel, core, tmp_path):
    src = tmp_path / "shared.json"
    UL.export_palette(BUILTIN_PALETTES["amber"], src)
    panel.import_file(src)
    assert core.cfg.theme.startswith("user:")
    assert dict(current_look().palette.colors) == dict(BUILTIN_PALETTES["amber"].colors)


def test_export_needs_a_known_extension(panel, tmp_path):
    panel.export(tmp_path / "look.txt")
    assert panel.message_label.isVisible() and ".mandibleskin" in panel.message_label.text()
    assert not (tmp_path / "look.txt").exists()


# ------------------------------------------------------------------- Settings (R4, R5, C6)

def test_settings_has_no_frame_or_switch_pickers_and_never_writes_them(core, scarlet):
    core.cfg.chassis_frame, core.cfg.switch_style = "wood_cheeks", "rocker"
    dlg = _settings(core)
    try:
        assert not hasattr(dlg, "frame_combo") and not hasattr(dlg, "switch_combo")
        dlg.skin_combo.setCurrentIndex(dlg.skin_combo.findData("minimal"))
        dlg.apply_all()
    finally:
        dlg.deleteLater()
        _flush_deletes()
    assert (core.cfg.chassis_frame, core.cfg.switch_style) == ("wood_cheeks", "rocker")
    assert not hasattr(core, "set_chassis_frame") and not hasattr(core, "set_switch_style")


def test_look_from_config_ignores_legacy_fields_after_migration():
    from mandible.config import AppConfig

    cfg = AppConfig()
    cfg.ui_skin, cfg.chassis_frame, cfg.switch_style = "skeuomorphic", "wood_cheeks", "rocker"
    legacy = look_from_config(cfg)                       # not migrated yet: still applied
    assert legacy.skin.elements["frame"] == "wood_cheeks"
    assert legacy.skin.elements["switch"] == "rocker"
    cfg.appearance_migrated = True
    assert look_from_config(cfg) == Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"])


def test_settings_pickers_refresh_after_save_import_and_delete(panel, core, tmp_path):
    """C6: an open Settings dialog re-reads the user skins and themes."""
    dlg = _settings(core)
    try:
        panel.select_variant("switch", "rocker")
        panel.set_accent("#3366ff")
        panel.save_as("Night")
        assert "user:night" in _skin_ids(dlg) and core.cfg.theme in _theme_ids(dlg)
        src = tmp_path / "x.mandibletheme"
        UL.export_palette(BUILTIN_PALETTES["cyan"], src)
        panel.import_file(src)
        assert core.cfg.theme in _theme_ids(dlg)
        panel.delete()
        assert "user:night" not in _skin_ids(dlg)
        assert dlg.skin_combo.currentData() in _skin_ids(dlg)
    finally:
        dlg.deleteLater()
        _flush_deletes()


def test_main_window_docks_the_panel_from_settings(core, scarlet, monkeypatch):
    """R4: Settings' Customize... applies Settings, closes it, and the main window shows the
    dock on the right (created once, reused)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from mandible.ui.dialogs.customize import CustomizePanel
    from mandible.ui.dialogs.settings import SettingsDialog
    from mandible.ui.main_window import MainWindow

    def fake_exec(dlg):
        dlg.skin_combo.setCurrentIndex(dlg.skin_combo.findData("vintage"))
        dlg.customize_btn.click()
        return dlg.result()

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    win = MainWindow(core, show_tray=False)
    win.setAttribute(Qt.WA_DontShowOnScreen)
    try:
        win.show()
        QApplication.processEvents()
        assert win.customize_panel is None               # built on first use only
        win._settings()
        dock = win.customize_panel
        assert isinstance(dock, CustomizePanel) and dock.isVisible()
        assert win.dockWidgetArea(dock) == Qt.RightDockWidgetArea
        assert core.cfg.ui_skin == "vintage"             # Settings was applied first
        assert dock.tiles[("frame", "wood_cheeks")].isChecked()
        dock.close()
        assert win.open_customize() is dock and dock.isVisible()
    finally:
        win._quitting = True
        win.meter_timer.stop()
        win.status_timer.stop()
        if win.customize_panel is not None:
            win.customize_panel._discard_and_hide()
        win.hide()
        win.deleteLater()
        QApplication.processEvents()
        _flush_deletes()


# ------------------------------------------------------------------- user look cache (C3)

def test_user_look_lists_are_cached_until_something_changes(monkeypatch, looks_dirs):
    from mandible.ui.look import Skin

    reads = []
    real = UL._read_doc
    monkeypatch.setattr(UL, "_read_doc", lambda *a: (reads.append(a[0]), real(*a))[1])
    skin = Skin("user:one", "One", dict(BUILTIN_SKINS["minimal"].elements),
                dict(BUILTIN_SKINS["minimal"].shape))
    UL.save_skin(skin)
    assert "user:one" in UL.all_skins()
    reads.clear()
    for _ in range(5):
        assert "user:one" in UL.all_skins()
    assert reads == []                                   # served from the cache
    UL.save_skin(Skin("user:two", "Two", dict(skin.elements), dict(skin.shape)))
    assert list(UL.all_skins())[-2:] == ["user:one", "user:two"]   # save invalidates
    UL.delete_user_look("user:one", "skin")
    assert "user:one" not in UL.all_skins()              # delete invalidates
    dropped = UL.SKINS_DIR / "three.json"                # a file copied in by hand
    doc = json.loads((UL.SKINS_DIR / "two.json").read_text(encoding="utf-8"))
    doc["name"] = "Three"
    dropped.write_text(json.dumps(doc), encoding="utf-8")
    assert "user:three" in UL.all_skins()                # the folder changed
    src = looks_dirs / "in.mandibletheme"
    UL.export_palette(BUILTIN_PALETTES["cyan"], src)
    imported, _ = UL.import_palette(src)
    assert imported.id in UL.all_palettes()              # import invalidates


# ------------------------------------------------------------------- Review Focus 5

class _RecordingEngine:
    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "calls", [])

    def __getattr__(self, name):
        self.calls.append(name)
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        self.calls.append(f"set {name}")
        setattr(self._real, name, value)


def test_element_swaps_during_audio_never_touch_the_engine(core, scarlet):
    """50 element swaps while a fake audio callback thread runs: no exception anywhere and not a
    single engine call or attribute access from the panel."""
    import numpy as np
    from PySide6.QtCore import Qt

    from mandible.ui.dialogs.customize import CustomizePanel

    errors: list[BaseException] = []
    stop = threading.Event()
    blocks = []

    def callback_thread():
        buf = np.zeros((256, 2), dtype=np.float32)
        try:
            while not stop.is_set():
                buf[:] = np.sin(np.arange(256, dtype=np.float32))[:, None] * 0.1
                blocks.append(float(np.abs(buf).max()))
                current_look()                           # the UI state may be read meanwhile
        except BaseException as exc:  # noqa: BLE001 - recorded
            errors.append(exc)

    real_engine = core.engine
    engine = _RecordingEngine(real_engine)
    core.engine = engine
    p = CustomizePanel(core, None)
    p.setAttribute(Qt.WA_DontShowOnScreen)
    p.show()
    t = threading.Thread(target=callback_thread, daemon=True)
    t.start()
    try:
        variants = ("rocker", "pill", "bat_toggle")
        for i in range(50):
            p.select_variant("switch", variants[i % 3])
            p.select_variant("meter", ("smooth_bar", "led_segments")[i % 2])
    except BaseException as exc:  # noqa: BLE001
        errors.append(exc)
    finally:
        stop.set()
        t.join(5)
        p._discard_and_hide()
        p.deleteLater()
        _flush_deletes()
        core.engine = real_engine
    assert errors == []
    assert blocks, "the callback thread ran"
    assert engine.calls == []
