"""Review bugs (spec section 10, items 2-10): one regression test each."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QApplication, QDialog, QFrame,
                               QGroupBox, QLabel, QLineEdit, QWidget)

from mandible.config import PluginSlot
from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look, current_look, set_look


@pytest.fixture
def real_look(qapp):
    """The real stylesheet applied (padding and fonts change widget sizes)."""
    before = current_look()
    set_look(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    yield
    set_look(before)


def _flush_deletes():
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _shown(widget):
    widget.setAttribute(Qt.WA_DontShowOnScreen)
    widget.show()
    for _ in range(3):
        QApplication.processEvents()
    return widget


@pytest.fixture
def main_window(sample_core, real_look):
    from mandible.ui.main_window import MainWindow

    sample_core.cfg.close_to_tray = False
    made = []

    def make():
        win = MainWindow(sample_core, show_tray=False)
        win.resize(1280, 720)
        made.append(_shown(win))
        return win

    yield make
    for win in made:
        win.meter_timer.stop()
        win.status_timer.stop()
        win._quitting = True
        win.hide()
        win.deleteLater()
    _flush_deletes()


# ---------------------------------------------------------------- 2. pre-FX pill
def _set_prefx(core, hp, rnn, gate):
    p = core.cfg.prefx
    p.highpass_enabled, p.rnnoise_enabled, p.noise_gate_enabled = hp, rnn, gate


def test_prefx_pill_is_named_pre_fx_with_a_per_stage_tooltip(sample_core, real_look):
    from mandible.ui.widgets.flow_strip import SignalFlowStrip

    strip = SignalFlowStrip(sample_core)
    pill = strip.prefx_btn
    assert pill.text() == "Pre-FX"
    assert strip.step_state("prefx") == "on"       # the high-pass is on by default
    assert pill.property("state") == "on"
    tip = pill.toolTip()
    assert "High-pass" in tip and "RNNoise" not in tip and "Noise gate" not in tip

    _set_prefx(sample_core, True, True, True)
    strip.refresh(None, "CLEAN VOICE")
    tip = pill.toolTip()
    assert tip.index("High-pass") < tip.index("RNNoise") < tip.index("Noise gate")
    assert pill.text() == "Pre-FX"

    _set_prefx(sample_core, False, False, False)
    strip.refresh(None, "CLEAN VOICE")
    assert pill.text() == "Pre-FX"
    assert strip.step_state("prefx") == "off" and not pill.property("state")
    for stage in ("High-pass", "RNNoise", "Noise gate"):
        assert stage not in pill.toolTip()
    # the icon means the same thing as the full button
    icon = strip.step_button("prefx", "icons")
    assert icon.text() == "" and not icon.icon().isNull() and not icon.property("state")
    assert "all stages off" in icon.toolTip()
    strip.deleteLater()
    _flush_deletes()


# ------------------------------------------------------- 3 / 4. plugin card
def _card(core, slot, chain=None):
    from mandible.ui.widgets.plugin_card import PluginRackCard

    chain = chain or core.cfg.chains[0]
    card = PluginRackCard(slot, chain, core)
    return card


def _badge_texts(card):
    return [b.text() for b in _badges(card).values()]


def _badges(card):
    """The card's status-pill badges by kind (format, builtin, vendor, awake)."""
    from mandible.ui.widgets.buttons import StatusPill

    return {b.property("badge"): b for b in card.findChildren(StatusPill) if b.property("badge")}


def test_plugin_card_latency_uses_the_plugins_reported_latency(sample_core, real_look):
    from mandible import plugins as P

    chain = next(c for c in sample_core.cfg.chains
                 if any(s.path == "internal:pitch_formant" for s in c.plugins))
    slot = next(s for s in chain.plugins if s.path == "internal:pitch_formant")
    assert P.get_slot_latency_samples(slot) == 1024
    card = _card(sample_core, slot, chain)
    chip = card.findChild(QLabel, "latencyChip")
    assert chip.full_text() == "21.3 ms (1024 smp)"
    assert "1024" in chip.toolTip()
    # a plugin without latency still reads as a number
    other = next(s for s in chain.plugins if s.path == "internal:reverb")
    card2 = _card(sample_core, other, chain)
    assert card2.findChild(QLabel, "latencyChip").full_text() == "0.0 ms (0 smp)"
    card.deleteLater()
    card2.deleteLater()
    _flush_deletes()


class _FakeVst3:
    """Stands in for a loaded VST3 instance: just enough for the card."""
    reported_latency_samples = 0
    parameters: dict = {}

    def show_editor(self, event=None):
        pass


def test_built_in_cards_say_built_in_and_have_no_open_ui(sample_core, real_look):
    chain = sample_core.cfg.chains[0]
    for slot in chain.plugins:
        assert slot.path.startswith("internal:")
        card = _card(sample_core, slot, chain)
        badges = _badge_texts(card)
        assert "Built-in" in badges and "VST3" not in badges
        assert "format" not in _badges(card)
        assert _badges(card)["builtin"].text() == "Built-in"
        assert card.ui_btn.isHidden()          # no plugin window to open
        card.deleteLater()
    _flush_deletes()


def test_vst3_cards_say_vst3_and_have_open_ui(sample_core, real_look):
    chain = sample_core.cfg.chains[0]
    slot = PluginSlot(path=r"C:\VST3\Fake Plugin.vst3", display_name="Fake Plugin")
    slot._instance = _FakeVst3()
    card = _card(sample_core, slot, chain)
    badges = _badge_texts(card)
    assert "VST3" in badges and "Built-in" not in badges
    assert "builtin" not in _badges(card)
    assert not card.ui_btn.isHidden() and card.ui_btn.isEnabled()
    card.deleteLater()

    # a VST3 that failed to load still renders; there is no window to open
    broken = PluginSlot(path=r"C:\VST3\Missing.vst3", display_name="Missing")
    card = _card(sample_core, broken, chain)
    assert "VST3" in _badge_texts(card)
    assert card.ui_btn.isHidden() or not card.ui_btn.isEnabled()
    card.deleteLater()
    _flush_deletes()


# ---------------------------------------------------------------- 5. settings
def _visible_texts(root: QWidget):
    texts = []
    for w in root.findChildren(QWidget):
        if isinstance(w, (QAbstractButton, QLabel, QGroupBox)):
            texts.append(w.text() if not isinstance(w, QGroupBox) else w.title())
        if isinstance(w, QLineEdit):
            texts.append(w.placeholderText())
    return [t for t in texts if t]


def _lone_ampersand(text: str) -> bool:
    """True when Qt would swallow an ``&`` as a mnemonic marker."""
    return "&" in text.replace("&&", "")


def test_settings_labels_render_ampersands_and_have_no_stray_underscores(sample_core, real_look):
    from mandible.ui.dialogs.settings import SettingsDialog

    dlg = SettingsDialog(sample_core, False)
    try:
        titles = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
        shown = [t.replace("&&", "&") for t in titles]    # what Qt draws
        assert "Limiter & Normalizer" in shown
        assert not any(_lone_ampersand(t) for t in titles), titles
        assert not any("_" in t for t in shown), shown
        buttons = [w.text() for w in dlg.findChildren(QAbstractButton)]
        assert not any(_lone_ampersand(t) for t in buttons), buttons
    finally:
        dlg.deleteLater()
        _flush_deletes()


def test_setup_assistant_buttons_do_not_swallow_ampersands(sample_core, real_look):
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog

    dlg = SetupAssistantDialog(sample_core, None)
    try:
        for step in range(4):
            dlg._go_to_step(step)
            texts = [w.text() for w in dlg.findChildren(QAbstractButton)]
            assert not any(_lone_ampersand(t) for t in texts), (step, texts)
    finally:
        dlg._meter_timer.stop()
        dlg.deleteLater()
        _flush_deletes()


# -------------------------------------------------------------- 6. soundboard
def test_soundboard_rows_fit_their_cell_widgets_and_start_unselected(sample_core, real_look, tmp_path):
    from mandible.ui.dialogs.soundboard import SoundboardDialog

    # a larger system font (and the stylesheet's padding) makes the buttons taller than
    # the table's stock row height
    font = QApplication.font()
    big = QFont(font)
    big.setPointSizeF(font.pointSizeF() * 1.5)
    QApplication.setFont(big)
    import wave

    for clip in sample_core.cfg.soundboard:        # real (silent) files so the clips can be shown
        clip.path = str(tmp_path / f"{clip.name}.wav")
        with wave.open(clip.path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(bytes(1600))
    dlg = SoundboardDialog(sample_core)
    try:
        _shown(dlg)
        table = dlg.table
        assert table.rowCount() == len(sample_core.cfg.soundboard) > 0
        for row in range(table.rowCount()):
            h = table.rowHeight(row)
            for col in range(1, table.columnCount()):
                w = table.cellWidget(row, col)
                assert w is not None
                assert w.height() <= h, (row, col)
                # not clipped: the cell gives the widget the height it asks for
                assert w.height() >= w.sizeHint().height(), (row, col, w.height(), w.sizeHint())
        assert not table.selectionModel().hasSelection()
        assert dlg.waveform_widget.clip_name_lbl.text() == "No clip selected"
        # choosing a row shows its clip; clearing the selection goes back to the empty state
        table.selectRow(1)
        assert dlg.waveform_widget.clip_name_lbl.text() == sample_core.cfg.soundboard[1].name.upper()
        table.clearSelection()
        assert dlg.waveform_widget.clip_name_lbl.text() == "No clip selected"
        # a refresh (e.g. after playing a clip) keeps the user's selection, and adds none
        table.selectRow(2)
        dlg._refresh_rows()
        assert [i.row() for i in table.selectionModel().selectedRows()] == [2]
        table.clearSelection()
        dlg._refresh_rows()
        assert not table.selectionModel().hasSelection()
    finally:
        QApplication.setFont(font)
        dlg.deleteLater()
        _flush_deletes()


# ---------------------------------------------------------- 7. channel strip
def test_channel_strip_without_an_input_device_says_no_input(sample_core, main_window):
    sample_core.cfg.audio.input_device = ""
    win = main_window()
    titles = [w.full_text() for w in win.findChildren(QLabel)
              if hasattr(w, "full_text") and w.objectName() in ("channelTitle", "condensedLabel")]
    mic = [t for t in titles if "MIC" in t]
    assert len(mic) == 2                              # the full strip and the condensed one
    assert all("No input" in t for t in mic), mic
    assert not any("Focusrite" in t for t in titles)


def test_channel_strip_names_the_configured_input(sample_core, main_window):
    sample_core.cfg.audio.input_device = "USB Mic"
    win = main_window()
    titles = [w.full_text() for w in win.findChildren(QLabel)
              if hasattr(w, "full_text") and w.objectName() in ("channelTitle", "condensedLabel")]
    assert any("USB Mic" in t for t in titles) and not any("No input" in t for t in titles)


# ---------------------------------------------------------- 8. chain header
def test_chain_header_has_no_empty_framed_widgets(sample_core, main_window):
    win = main_window()
    editor = win.editor
    editor.set_chain(sample_core.cfg.chains[0])
    for _ in range(3):
        QApplication.processEvents()
    empties = []
    for frame in editor.findChildren(QFrame):
        if not frame.isVisible():
            continue
        if isinstance(frame, (QLabel, QAbstractScrollArea)):
            continue                                   # not boxes meant to hold widgets
        if frame.frameShape() in (QFrame.Shape.VLine, QFrame.Shape.HLine):
            continue                                   # separators are lines, not boxes
        if not any(c.isVisible() for c in frame.findChildren(QWidget)
                   if c.parent() is frame):
            empties.append((frame.objectName(), type(frame).__name__))
    # the plugin cards are framed too, and have children; anything listed here is hollow
    assert not empties, empties
    # the chain's gain and dry/wet knobs are shown in that header
    assert editor.knob_gain.isVisible() and editor.knob_wet.isVisible()


# ------------------------------------------------------------ 10. knob mapping
def _dialog_texts(dlg: QDialog):
    texts = [dlg.windowTitle()] + _visible_texts(dlg)
    texts += [w.toolTip() for w in dlg.findChildren(QWidget)]
    return [t for t in texts if t]


def test_knob_mapping_dialog_does_not_call_built_in_parameters_vst(sample_core, real_look):
    from mandible.ui.dialogs.param_map import PluginParamMapDialog

    slot = sample_core.cfg.chains[0].plugins[0]
    assert slot.path.startswith("internal:")
    dlg = PluginParamMapDialog(slot, sample_core)
    try:
        texts = _dialog_texts(dlg)
        assert any("parameters" in t.lower() for t in texts)
        assert not [t for t in texts if "VST" in t.upper()], texts
    finally:
        dlg.deleteLater()
        _flush_deletes()


def test_knob_mapping_dialog_calls_real_vst3_parameters_vst3(sample_core, real_look):
    from mandible.ui.dialogs.param_map import PluginParamMapDialog

    slot = PluginSlot(path=r"C:\VST3\Fake Plugin.vst3", display_name="Fake Plugin")
    slot._instance = _FakeVst3()
    dlg = PluginParamMapDialog(slot, sample_core)
    try:
        assert any("VST3 parameters" in t for t in _dialog_texts(dlg))
    finally:
        dlg.deleteLater()
        _flush_deletes()


# ---------------------------------------------------------------- 9. knob titles
def test_knob_titles_that_are_shortened_keep_the_full_name_in_the_tooltip(sample_core, real_look):
    chain = sample_core.cfg.chains[0]
    seen = 0
    for slot in chain.plugins:
        card = _card(sample_core, slot, chain)
        for knob in card.param_knobs:
            seen += 1
            assert len(knob.title) <= 9 and knob.full_name in knob.toolTip()
        card.deleteLater()
    assert seen
    _flush_deletes()
