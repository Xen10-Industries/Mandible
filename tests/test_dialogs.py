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
            for w in (dlg.cable_card, dlg.cable_card_title, dlg.cable_card_desc):
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


def test_appearance_groups_frame_and_switch_under_skin_elements(settings):
    from PySide6.QtWidgets import QLabel

    dlg = settings()
    page = dlg.pages.widget(SECTION_IDS.index("appearance"))
    labels = [w.text().lower() for w in page.findChildren(QLabel, "settingsGroupLabel")]
    assert "skin elements" in labels
    assert page.isAncestorOf(dlg.frame_combo) and page.isAncestorOf(dlg.switch_combo)


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


def _not_sentence_case(text: str) -> bool:
    """Words after the first that start upper-case and are neither acronyms nor proper nouns."""
    words = [w.strip("():,.…") for w in text.split()[1:]]
    return any(w[:1].isupper() and not w.isupper() and w not in _PROPER for w in words if w)


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
