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


def test_setup_assistant_next_button_turns_green_on_the_last_step(core, scarlet_look):
    from mandible.ui.dialogs.setup_assistant import SetupAssistantDialog

    dlg = SetupAssistantDialog(core, None)
    try:
        dlg.show()
        dlg.next_btn.setAttribute(dlg.next_btn.testAttribute.__self__.__class__.WA_DontShowOnScreen, False) \
            if False else None
        assert not dlg.next_btn.property("final")
        accent = scarlet_look.palette.color("accent")
        assert _pixel(dlg.next_btn, dlg.next_btn.width() // 2, 4).lower() == accent.lower()
        dlg._go_to_step(3)
        assert dlg.next_btn.property("final") is True
        ok = scarlet_look.palette.color("status.ok")
        assert _pixel(dlg.next_btn, dlg.next_btn.width() // 2, 4).lower() == ok.lower()
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
