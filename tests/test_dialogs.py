"""Dialog modules under mandible/ui/dialogs: styling comes from the stylesheet (Task 8b)."""
from __future__ import annotations

import pytest

from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look, current_look, set_look


@pytest.fixture
def scarlet_look(qapp):
    before = current_look()
    set_look(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    yield current_look()
    set_look(before)


def _pixel(widget, x: int, y: int) -> str:
    return widget.grab().toImage().pixelColor(x, y).name()


def _near(got: str, want: str, tol: int = 12) -> bool:
    return all(abs(int(got[i:i + 2], 16) - int(want[i:i + 2], 16)) <= tol for i in (1, 3, 5))


def test_setup_assistant_next_button_is_primary_on_every_step(core, scarlet_look):
    """Next (Finish on the last step) is the wizard's one primary button: accent fill."""
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog

    dlg = SetupAssistantDialog(core, None)
    try:
        dlg.show()
        accent = scarlet_look.palette.color("accent")
        assert not dlg.next_btn.property("final")
        assert dlg.next_btn.property("tier") == "primary"
        assert _pixel(dlg.next_btn, dlg.next_btn.width() // 2, 4).lower() == accent.lower()
        dlg._go_to_step(3)
        assert dlg.next_btn.property("final") is True
        assert dlg.next_btn.text().startswith("Finish")
        assert _pixel(dlg.next_btn, dlg.next_btn.width() // 2, 4).lower() == accent.lower()
        dlg._go_to_step(0)
        assert dlg.next_btn.property("final") is False
    finally:
        dlg._meter_timer.stop()
        dlg.deleteLater()


def test_setup_assistant_cable_card_states_follow_tokens(core, scarlet_look):
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog

    dlg = SetupAssistantDialog(core, None)
    try:
        dlg.show()
        dlg._go_to_step(1)
        for state, token in (("ok", "status.ok.subtle"), ("warn", "status.warn.subtle")):
            dlg._set_cable_state(state)
            for w in (dlg.cable_card, dlg.cable_card_title):
                assert w.property("state") == state
            # the card interior (inside border and radius) is painted with the state's token
            assert _pixel(dlg.cable_card, 8, dlg.cable_card.height() // 2).lower() == \
                scarlet_look.palette.color(token).lower()
    finally:
        dlg._meter_timer.stop()
        dlg.deleteLater()


def test_live_vu_bar_paints_with_look_tokens(qapp, scarlet_look):
    from mandible.ui.dialogs.setup_assistant import LiveVuBar

    bar = LiveVuBar()
    bar.resize(200, 18)
    # idle: the trough is bg.inset inside the line.subtle border
    assert _pixel(bar, 100, 9).lower() == scarlet_look.palette.color("bg.inset").lower()
    bar.set_peak(1.0)
    assert _near(_pixel(bar, 2, 9), scarlet_look.palette.color("status.ok"))
    bar.deleteLater()


# ------------------------------------------------------------------ Settings (Task 15)
SECTION_IDS = ["audio", "ptt", "output_safety", "midi", "overlay", "appearance", "general", "api"]
SECTION_TITLES = ["Audio", "Push-to-talk", "Limiter & Normalizer", "MIDI", "Overlay",
                  "Appearance", "General", "Local API"]


@pytest.fixture
def settings(core, scarlet_look):
    from mandible.ui.dialogs.settings import SettingsDialog

    made = []

    def make(**kwargs):
        dlg = SettingsDialog(core, False, None, **kwargs)
        made.append(dlg)
        return dlg

    yield make
    for dlg in made:
        dlg.hide()
        dlg.deleteLater()


def test_settings_has_the_section_list_in_order(settings):
    dlg = settings()
    assert dlg.section_ids() == SECTION_IDS
    assert [dlg.sections.item(i).text() for i in range(dlg.sections.count())] == SECTION_TITLES
    assert dlg.pages.count() == len(SECTION_IDS)
    assert dlg.current_section() == "audio"
    assert not hasattr(dlg, "tabs")


@pytest.mark.parametrize("section", SECTION_IDS)
def test_settings_initial_section_selects_that_page(settings, section):
    dlg = settings(initial_section=section)
    assert dlg.current_section() == section
    assert dlg.pages.currentIndex() == SECTION_IDS.index(section)


def test_settings_unknown_initial_section_falls_back_to_audio(settings):
    assert settings(initial_section="nope").current_section() == "audio"


def test_settings_section_list_is_keyboard_navigable(settings):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg = settings()
    dlg.show()
    dlg.sections.setFocus()
    QTest.keyClick(dlg.sections, Qt.Key_Down)
    assert dlg.current_section() == "ptt"
    assert dlg.pages.currentWidget().isVisibleTo(dlg)
    QTest.keyClick(dlg.sections, Qt.Key_Down)
    QTest.keyClick(dlg.sections, Qt.Key_Up)
    assert dlg.current_section() == "ptt"
    assert dlg.sections.focusPolicy() != Qt.NoFocus


def test_settings_pages_scroll_when_taller_than_the_dialog(settings):
    from PySide6.QtWidgets import QScrollArea

    dlg = settings()
    for i in range(dlg.pages.count()):
        page = dlg.pages.widget(i)
        assert isinstance(page, QScrollArea), i
        assert page.widgetResizable()
        assert page.minimumSizeHint().height() < 200, (SECTION_IDS[i], page.minimumSizeHint())
    assert dlg.minimumHeight() > 0 and dlg.minimumWidth() > 0


def test_appearance_pickers_list_skins_and_palettes(settings):
    from mandible.ui.dialogs.settings import appearance_palettes, appearance_skins

    dlg = settings()
    assert [dlg.skin_combo.itemData(i) for i in range(dlg.skin_combo.count())] == \
        [s.id for s in appearance_skins()] == list(BUILTIN_SKINS)
    assert [dlg.theme_combo.itemText(i) for i in range(dlg.theme_combo.count())] == \
        [p.name for p in appearance_palettes()]


def test_appearance_skin_applies_live_persists_on_ok_and_reverts_on_cancel(settings, core):
    dlg = settings(initial_section="appearance")
    before = current_look()
    dlg.skin_combo.setCurrentIndex(dlg.skin_combo.findData("minimal"))
    assert current_look().skin.id == "minimal"            # live
    assert core.cfg.ui_skin != "minimal"                   # not persisted yet
    dlg.reject()
    assert current_look() == before                        # Cancel restores

    dlg2 = settings(initial_section="appearance")
    dlg2.skin_combo.setCurrentIndex(dlg2.skin_combo.findData("vintage"))
    dlg2.theme_combo.setCurrentIndex(dlg2.theme_combo.findData("amber"))
    dlg2.apply_all()                                       # OK
    assert (core.cfg.ui_skin, core.cfg.theme) == ("vintage", "amber")
    assert (current_look().skin.id, current_look().palette.id) == ("vintage", "amber")


def test_appearance_customize_button_emits_signal(settings):
    from PySide6.QtWidgets import QPushButton

    dlg = settings(initial_section="appearance")
    btn = dlg.customize_btn
    assert isinstance(btn, QPushButton) and btn.text() == "Customize…"
    assert btn.property("tier") == "secondary" and btn.isEnabled()
    got = []
    dlg.customizeRequested.connect(lambda: got.append(1))
    btn.click()
    assert got == [1]


def test_appearance_leaves_frame_and_switch_to_customize(settings):
    """R5: the old frame / switch pickers are gone from Appearance (Customize swaps elements)."""
    from PySide6.QtWidgets import QComboBox, QLabel

    dlg = settings()
    page = dlg.pages.widget(SECTION_IDS.index("appearance"))
    labels = [w.text().lower() for w in page.findChildren(QLabel, "settingsGroupLabel")]
    assert "skin elements" not in labels
    assert page.findChildren(QComboBox) == [dlg.skin_combo, dlg.theme_combo]
    assert not hasattr(dlg, "frame_combo") and not hasattr(dlg, "switch_combo")


def test_appearance_customize_applies_and_closes_settings(settings, core):
    from PySide6.QtWidgets import QDialog

    dlg = settings(initial_section="appearance")
    dlg.show()
    asked = []
    dlg.customizeRequested.connect(lambda: asked.append(dlg.isVisible()))
    dlg.customize_btn.click()
    assert asked == [True] and dlg.result() == QDialog.Accepted and not dlg.isVisible()


@pytest.fixture
def fake_drivers(monkeypatch):
    from mandible.ui.dialogs import settings as mod

    monkeypatch.setattr(mod.D, "drivers", lambda: ["ASIO", "Windows WASAPI"])
    monkeypatch.setattr(mod.D, "list_devices", lambda drv, kind: [(0, "Interface", 2)])
    monkeypatch.setattr(mod.D, "channel_names", lambda drv, idx, kind: ["A", "B"])
    monkeypatch.setattr(mod.D, "find_device", lambda drv, name, kind: 0)


def test_asio_button_is_named_and_only_visible_for_asio(settings, core, fake_drivers):
    core.cfg.audio.driver = "Windows WASAPI"
    dlg = settings()
    btn = dlg.asio_panel_btn
    assert btn.text() == "ASIO driver settings…"
    assert not btn.isVisibleTo(dlg)
    dlg.driver.setCurrentIndex(dlg.driver.findData("ASIO"))
    assert btn.isVisibleTo(dlg)
    dlg.driver.setCurrentIndex(dlg.driver.findData("Windows WASAPI"))
    assert not btn.isVisibleTo(dlg)


def test_setup_assistant_button_is_secondary(settings):
    from PySide6.QtWidgets import QPushButton

    btn = settings().findChild(QPushButton, "audioWizardBtn")
    assert btn is not None and btn.property("tier") == "secondary"


def test_midi_learn_button_text_stays_sentence_case(settings):
    from mandible.ui.dialogs.settings import MIDI_LEARN_TEXT

    dlg = settings()
    dlg._midi_learning_row = -1
    dlg._on_midi_learned("note_on", 60, 1)
    assert dlg.midi_learn_btn.text() == MIDI_LEARN_TEXT == "MIDI learn (new binding)…"


_PROPER = {"Mandible", "Windows", "Discord", "OBS", "Stream", "Deck", "Elgato"}
# Product and menu names the setup assistant's copy mentions.
_PROPER_WIZARD = _PROPER | {"User", "Settings", "Voice", "Video", "Echo", "Cancellation", "Noise",
                            "Suppression", "Streamlabs", "Focusrite", "Loopback", "Virtual", "Cable",
                            "Audio", "Input", "Capture", "Output", "Motu", "NexiGo", "Blue", "Yeti",
                            "HyperX", "VB-Audio", "VST", "Discord's"}


def _not_sentence_case(text: str, proper=None) -> bool:
    """Words after the first that start upper-case and are neither acronyms nor proper nouns."""
    proper = _PROPER if proper is None else proper
    raw = text.split()
    words = [w.strip("():,.…'") for i, w in enumerate(raw)
             if i and not raw[i - 1].endswith((".", "!", "?"))]     # a new sentence may start upper-case
    return any(w[:1].isupper() and not w.isupper() and w not in proper for w in words if w)


def test_settings_copy_is_sentence_case(settings):
    from PySide6.QtWidgets import QAbstractButton, QFormLayout, QLabel

    dlg = settings()
    texts = [w.text() for w in dlg.findChildren(QAbstractButton)]
    for i in range(dlg.pages.count()):
        for form in dlg.pages.widget(i).findChildren(QFormLayout):
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.LabelRole)
                if item is not None and isinstance(item.widget(), QLabel):
                    texts.append(item.widget().text())
    texts += [dlg.midi_table.horizontalHeaderItem(c).text() for c in range(4)]
    assert [t for t in texts if _not_sentence_case(t)] == []
    assert len(texts) > 20


def test_settings_field_columns_align_within_every_section(settings):
    """One form per page (group headings are rows), so every field starts at the same x."""
    from PySide6.QtWidgets import QFormLayout

    dlg = settings()
    dlg.resize(780, 560)
    dlg.show()
    for i, sid in enumerate(SECTION_IDS):
        dlg.show_section(sid)
        page = dlg.pages.widget(i)
        forms = page.findChildren(QFormLayout)
        assert len(forms) <= 1, sid
        xs = set()
        for form in forms:
            for row in range(form.rowCount()):
                if form.itemAt(row, QFormLayout.SpanningRole) is not None:
                    continue          # check boxes, hints and buttons span the whole row
                item = form.itemAt(row, QFormLayout.FieldRole)
                if item is not None and not item.isEmpty():
                    xs.add(item.geometry().x())
        assert len(xs) <= 1, (sid, xs)


def test_result_settings_returns_audio_settings(settings):
    from mandible.config import AudioSettings

    assert isinstance(settings().result_settings(), AudioSettings)


def test_hotkey_prompt_is_the_dialogs_title_text(core, scarlet_look):
    from PySide6.QtWidgets import QLabel

    from mandible.ui.dialogs.hotkey import HotkeyDialog

    dlg = HotkeyDialog(core, None, "Set hotkey")
    try:
        dlg.show()
        prompt = dlg.findChild(QLabel, "hotkeyPrompt")
        assert prompt is not None and prompt.text().startswith("Press")
        others = [w for w in dlg.findChildren(QLabel) if w is not prompt]
        assert others, "the dialog has a smaller hint under the prompt"
        assert all(prompt.font().pixelSize() > w.font().pixelSize() for w in others), \
            (prompt.font().pixelSize(), [w.font().pixelSize() for w in others])
    finally:
        dlg.hide()
        dlg.deleteLater()


# ------------------------------------------------------------------ Remaining dialogs (Task 16)
import pathlib  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKINS = ("skeuomorphic", "vintage", "minimal")
THEMES = ("scarlet", "cyan", "stealth", "amber")


def _gallery():
    sys.path.insert(0, str(ROOT / "tools"))
    import ui_gallery

    return ui_gallery


def _dialog_problems(dlg) -> dict:
    """Overflow, clipped text, untiered buttons and a second primary button, over every
    section / tab / page of ``dlg`` at its current size."""
    from PySide6.QtWidgets import QApplication

    from mandible.ui import inspect as ins

    gallery = _gallery()
    found: dict[str, list] = {"overflow": [], "clipped_text": [], "untiered": [], "primaries": []}
    for _suffix, _label in gallery._states(dlg):
        QApplication.processEvents()
        found["overflow"] += [str(o) for o in ins.find_overflow(dlg)]
        found["clipped_text"] += ins.find_clipped_text(dlg)
        found["untiered"] += ins.untiered_buttons(dlg)
        found["primaries"] += ins.extra_primary_buttons(dlg)
    return {k: v for k, v in found.items() if v}


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("skin", SKINS)
def test_every_dialog_meets_the_standard_at_default_and_minimum_size(qapp, sample_core, skin, theme):
    """No overflow, no clipped text, no untiered buttons and at most one primary button, in
    every dialog, at its default size and at the smallest size it allows (font-dependent
    findings are re-checked with real Windows metrics by tests/test_skins.py)."""
    from PySide6.QtCore import QCoreApplication, QEvent, Qt

    gallery = _gallery()
    gallery._apply(qapp, skin, theme, sample_core)
    failures = {}
    for name, build in gallery.dialog_builders(sample_core).items():
        if name == "settings":      # Task 15's; covered per section by tests/test_skins.py
            continue
        dlg = build()
        try:
            dlg.setAttribute(Qt.WA_DontShowOnScreen)
            dlg.show()
            qapp.processEvents()
            default = _dialog_problems(dlg)
            if default:
                failures[f"{name} default"] = default
            dlg.resize(dlg.minimumSizeHint().expandedTo(dlg.minimumSize()))
            qapp.processEvents()
            smallest = _dialog_problems(dlg)
            if smallest:
                failures[f"{name} minimum"] = smallest
        finally:
            dlg.close()
            dlg.deleteLater()
            # delete it now: a leftover would be restyled by every later look switch
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert failures == {}


def test_extra_primary_buttons_reports_every_primary_when_there_are_two(qapp):
    from PySide6.QtWidgets import QWidget

    from mandible.ui import inspect as ins
    from mandible.ui.widgets.buttons import make_button

    root = QWidget()
    one = make_button("OK", "primary", parent=root)
    root.show()
    assert ins.extra_primary_buttons(root) == []
    two = make_button("Save", "primary", parent=root)
    two.move(0, 40)
    two.show()
    assert len(ins.extra_primary_buttons(root)) == 2
    one.hide()
    assert ins.extra_primary_buttons(root) == []     # hidden buttons do not count
    root.deleteLater()


def test_prefx_dialog_is_mic_cleanup_with_explanations_in_hint_labels(core, scarlet_look):
    from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel

    from mandible.ui.dialogs.prefx import PreFXDialog

    dlg = PreFXDialog(core, None)
    try:
        assert dlg.windowTitle() == "Mic cleanup"
        dlg.show()
        boxes = dlg.findChildren(QCheckBox)
        assert len(boxes) == 3
        # a check box is a short label; what it does is a muted hint label
        assert all(len(b.text()) <= 32 and "(" not in b.text() for b in boxes), [b.text() for b in boxes]
        hints = [w for w in dlg.findChildren(QLabel) if w.objectName() == "hint"]
        assert len(hints) >= 3
        assert all(h.wordWrap() for h in hints)
        # group headings are section labels, not accent-coloured group boxes
        assert dlg.findChildren(QGroupBox) == []
        headings = [w.text() for w in dlg.findChildren(QLabel) if w.objectName() == "settingsGroupLabel"]
        assert headings == ["RUMBLE FILTER", "NOISE SUPPRESSION", "NOISE GATE"]
    finally:
        dlg.hide()
        dlg.deleteLater()


def test_prefx_dialog_still_saves_every_field(core, scarlet_look):
    from mandible.ui.dialogs.prefx import PreFXDialog

    dlg = PreFXDialog(core, None)
    try:
        dlg.hp_en.setChecked(True)
        dlg.hp_freq.setValue(120)
        dlg.rnn_en.setChecked(True)
        dlg.rnn_wet.setValue(60)
        dlg.gate_en.setChecked(True)
        dlg.gate_thresh.setValue(-50)
        dlg.gate_rel.setValue(250)
        dlg._save()
        p = core.cfg.prefx
        assert (p.highpass_enabled, p.highpass_cutoff_hz) == (True, 120.0)
        assert (p.rnnoise_enabled, round(p.rnnoise_wet, 2)) == (True, 0.6)
        assert (p.noise_gate_enabled, p.noise_gate_threshold_db, p.noise_gate_release_ms) == (True, -50.0, 250.0)
    finally:
        dlg.deleteLater()


def test_setup_assistant_back_is_disabled_on_step_one_only(core, scarlet_look):
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog

    dlg = SetupAssistantDialog(core, None)
    try:
        dlg.show()
        assert not dlg.back_btn.isEnabled()
        assert dlg.back_btn.property("tier") == "secondary"
        dlg._go_to_step(1)
        assert dlg.back_btn.isEnabled()
        dlg._prev_step()
        assert dlg.pages.currentIndex() == 0 and not dlg.back_btn.isEnabled()
    finally:
        dlg._meter_timer.stop()
        dlg.deleteLater()


def test_setup_assistant_copy_is_sentence_case(core, scarlet_look):
    from PySide6.QtWidgets import QAbstractButton, QLabel

    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog

    dlg = SetupAssistantDialog(core, None)
    try:
        texts = [w.text() for w in dlg.findChildren(QAbstractButton)]
        for i in range(dlg.pages.count()):
            dlg._go_to_step(i)
            texts.append(dlg.main_title.text())
        for label in dlg.findChildren(QLabel):
            # "STEP n OF 4" and the live readouts are the dialog's only uppercase text
            if label.objectName() in ("wizardStep", "wizardMicStatus") or not label.text():
                continue
            texts.append(label.text())
        loud = [t for t in texts if len(t) > 3 and t.upper() == t]
        assert loud == []
        assert [t for t in texts if _not_sentence_case(t, _PROPER_WIZARD)] == []
    finally:
        dlg._meter_timer.stop()
        dlg.deleteLater()


def test_param_map_keeps_the_plugin_name_in_its_own_case(sample_core, scarlet_look):
    from PySide6.QtWidgets import QLabel

    from mandible.ui.dialogs.param_map import PluginParamMapDialog

    slot = sample_core.cfg.chains[0].plugins[0]
    name = slot.display_name
    assert name and name != name.upper()
    dlg = PluginParamMapDialog(slot, sample_core, None)
    try:
        assert name in dlg.windowTitle()
        title = dlg.findChild(QLabel, "paramMapTitle")
        assert name in title.text(), title.text()
        assert name.upper() not in title.text()
        assert "KNOB MAPPING" not in title.text()
    finally:
        dlg.deleteLater()


def test_param_map_lists_show_long_names_without_a_horizontal_scroll_bar(
        sample_core, scarlet_look, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from mandible import plugins as P
    from mandible.ui.dialogs.param_map import PluginParamMapDialog

    names = ["Output stage saturation drive amount (pre-filter)", "Side-chain filter cutoff frequency",
             "Dry and wet signal balance for the whole module"]
    params = [(f"k{i}", SimpleNamespace(name=n)) for i, n in enumerate(names)]
    monkeypatch.setattr(P, "get_usable_parameters", lambda plugin: params)
    monkeypatch.setattr(P, "resolve_slot_mapped_params", lambda slot, cfg: [k for k, _ in params])
    monkeypatch.setattr(P, "clean_param_string", lambda p: "100 %")
    slot = sample_core.cfg.chains[0].plugins[0]
    dlg = PluginParamMapDialog(slot, sample_core, None)
    try:
        dlg.show()
        for _ in range(3):
            QApplication.processEvents()
        for lst in (dlg.avail_list, dlg.mapped_list):
            assert lst.count() == 3
            assert not lst.horizontalScrollBar().isVisible()
            assert lst.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            for i, n in enumerate(names):
                assert n in lst.item(i).text()      # the full name, wrapped rather than cut
        assert lst.wordWrap()
    finally:
        dlg.hide()
        dlg.deleteLater()


@pytest.fixture
def board(core, scarlet_look, tmp_path):
    """A soundboard dialog on a core with one real clip, one missing file and one empty path."""
    import wave

    from mandible.config import SoundboardClipConfig
    from mandible.ui.dialogs.soundboard import SoundboardDialog

    good = tmp_path / "tone.wav"
    with wave.open(str(good), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x10\x20" * 4000)
    core.cfg.soundboard = [SoundboardClipConfig(name="Tone", path=str(good)),
                           SoundboardClipConfig(name="Airhorn", path=str(tmp_path / "gone.wav")),
                           SoundboardClipConfig(name="Blank", path="")]
    dlg = SoundboardDialog(core, None)
    dlg.show()
    yield dlg
    dlg.hide()
    dlg.deleteLater()


def test_soundboard_distinguishes_no_selection_from_a_missing_file(board):
    wf = board.waveform_widget
    assert wf.clip_name_lbl.text() == "No clip selected"
    board.table.selectRow(0)
    assert wf.clip_name_lbl.text() == "Tone"
    assert wf.play_btn.isEnabled() and wf.reset_btn.isEnabled()
    board.table.selectRow(1)
    assert wf.clip_name_lbl.text() == "File not found: Airhorn"
    assert "gone.wav" in wf.clip_name_lbl.toolTip()
    assert not wf.play_btn.isEnabled() and not wf.reset_btn.isEnabled() and not wf.stop_btn.isEnabled()
    board.table.selectRow(2)
    assert wf.clip_name_lbl.text() == "File not found: Blank"
    assert not wf.play_btn.isEnabled()
    board.table.clearSelection()
    assert wf.clip_name_lbl.text() == "No clip selected"
    assert wf.clip_name_lbl.toolTip() == ""


def test_soundboard_table_shows_full_button_text(board):
    """Hotkey and action columns are as wide as their buttons: "Set key…" is not truncated."""
    table = board.table
    for col in (1, 5):
        btn = table.cellWidget(0, col)
        assert table.columnWidth(col) >= btn.sizeHint().width(), (col, table.columnWidth(col))
    assert not table.horizontalScrollBar().isVisible()


def test_no_cascade_rules_are_left_in_the_stylesheet():
    """Dialog widgets are styled by their own rules: no ancestor rule boxes, pads or recolours
    the children that other widgets also use (the 8b cascade)."""
    from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look
    from mandible.ui.stylesheet import build_qss

    qss = build_qss(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    for needle in ("duckStrip QCheckBox", "duckStrip QLabel", "wizardGuideCard QLabel",
                   "QDialog#setupAssistant", "legacy_cascade"):
        assert needle not in qss, needle
    for selector in ("QLabel#wizardCardTitle", "QLabel#wizardCardDesc", "QLabel#wizardGuideText",
                     "QLabel#wizardGuideNum"):
        body = " ".join(re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", qss))
        assert "border" not in body and "padding" not in body and "background" not in body, selector


@pytest.mark.parametrize("name", ["prefx", "about", "param_map", "setup_assistant", "hotkey"])
def test_wrapped_text_is_not_clipped_when_the_dialog_is_made_as_small_as_it_goes(
        qapp, sample_core, scarlet_look, name):
    """Word-wrapped labels keep the height their text needs at the width the dialog is shrunk to
    (the label check in find_clipped_text skips wrapped labels, so this looks at them)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    dlg = _gallery().dialog_builders(sample_core)[name]()
    try:
        dlg.setAttribute(Qt.WA_DontShowOnScreen)
        dlg.show()
        QApplication.processEvents()
        for _suffix, _label in _gallery()._states(dlg):
            dlg.resize(1, 1)
            for _ in range(3):
                QApplication.processEvents()
            squeezed = [(w.objectName(), w.text()[:30], w.height(), w.heightForWidth(w.width()))
                        for w in dlg.findChildren(QLabel)
                        if w.isVisible() and w.wordWrap() and w.height() < w.heightForWidth(w.width())]
            assert squeezed == [], (name, dlg.size().toTuple(), squeezed)
    finally:
        if hasattr(dlg, "_meter_timer"):
            dlg._meter_timer.stop()
        dlg.close()
        dlg.deleteLater()
