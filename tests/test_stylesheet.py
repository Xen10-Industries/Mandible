"""Generated application stylesheet: every Look builds, no residue, token-only colours."""
from __future__ import annotations

import itertools
import re

import pytest

from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look, current_look, set_look
from mandible.ui.stylesheet import build_qss

ALL_LOOKS = [
    pytest.param(Look(p, s), id=f"{p.id}-{s.id}")
    for p, s in itertools.product(BUILTIN_PALETTES.values(), BUILTIN_SKINS.values())
]
SCARLET_SKEUO = Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"])


def rule_blocks(qss: str, selector: str) -> list[str]:
    """Bodies of every rule whose selector list contains exactly ``selector``."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", qss):
        selectors = [s.strip() for s in m.group(1).split(",")]
        if selector in selectors:
            out.append(m.group(2))
    return out


@pytest.fixture
def restore_look():
    before = current_look()
    yield
    set_look(before)


@pytest.mark.parametrize("look", ALL_LOOKS)
def test_build_qss_for_every_builtin_look(look):
    qss = build_qss(look)
    assert qss.strip()
    # Braces balance and no f-string / template residue is left behind.
    assert qss.count("{") == qss.count("}")
    assert "{{" not in qss and "}}" not in qss
    assert not re.search(r"\{[A-Za-z_.]+\}", qss)
    assert "None" not in qss and "nan" not in qss.lower()


@pytest.mark.parametrize("look", ALL_LOOKS)
def test_every_colour_in_the_qss_is_a_palette_token(look):
    qss = build_qss(look)
    palette_hexes = {v.lower() for v in look.palette.colors.values()}
    used = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", qss)}
    assert used, "stylesheet should use palette colours"
    assert used <= palette_hexes, f"non-token colours: {sorted(used - palette_hexes)}"
    assert not re.search(r"\b(white|black)\b", qss)


def test_build_qss_is_deterministic():
    assert build_qss(SCARLET_SKEUO) == build_qss(SCARLET_SKEUO)
    rebuilt = Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"])
    assert build_qss(rebuilt) == build_qss(SCARLET_SKEUO)


def test_build_qss_is_cached_per_look():
    build_qss.cache_clear()
    first = build_qss(SCARLET_SKEUO)
    second = build_qss(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    assert first is second
    info = build_qss.cache_info()
    assert info.hits == 1 and info.misses == 1


def test_palette_and_skin_change_the_output():
    cyan = Look(BUILTIN_PALETTES["cyan"], BUILTIN_SKINS["skeuomorphic"])
    minimal = Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["minimal"])
    base = build_qss(SCARLET_SKEUO)
    assert build_qss(cyan) != base
    assert build_qss(minimal) != base


def test_primary_tier_uses_accent_and_danger_tier_uses_danger_status():
    pal = SCARLET_SKEUO.palette
    qss = build_qss(SCARLET_SKEUO)
    primary = rule_blocks(qss, 'QPushButton[tier="primary"]')
    assert primary and pal.color("accent") in primary[0]
    assert pal.color("text.on_accent") in primary[0]
    danger = rule_blocks(qss, 'QPushButton[tier="danger"]')
    assert danger and pal.color("status.danger") in danger[0]
    for tier in ("secondary", "quiet"):
        assert rule_blocks(qss, f'QPushButton[tier="{tier}"]')


@pytest.mark.parametrize("tier", ["primary", "secondary", "quiet", "danger"])
def test_each_tier_has_all_five_states(tier):
    qss = build_qss(SCARLET_SKEUO)
    base = f'QPushButton[tier="{tier}"]'
    for suffix in (":hover", ":pressed", ":focus", ":disabled", ":checked"):
        assert rule_blocks(qss, base + suffix), f"{base}{suffix} missing"


def test_focus_state_uses_the_focus_ring_token():
    pal = SCARLET_SKEUO.palette
    qss = build_qss(SCARLET_SKEUO)
    for tier in ("secondary", "quiet", "danger"):
        body = rule_blocks(qss, f'QPushButton[tier="{tier}"]:focus')[0]
        assert pal.color("focus.ring") in body


@pytest.mark.parametrize("state,fg,bg", [
    ("off", "text.secondary", "bg.inset"),
    ("on", "status.ok", "status.ok.subtle"),
    ("warn", "status.warn", "status.warn.subtle"),
    ("danger", "status.danger", "status.danger.subtle"),
])
def test_status_pill_states(state, fg, bg):
    pal = SCARLET_SKEUO.palette
    qss = build_qss(SCARLET_SKEUO)
    body = rule_blocks(qss, f'QLabel#statusPill[state="{state}"]')
    assert body, f"statusPill state={state} missing"
    assert pal.color(fg) in body[0] and pal.color(bg) in body[0]


def test_status_pill_never_looks_clickable():
    qss = build_qss(SCARLET_SKEUO)
    assert rule_blocks(qss, "QLabel#statusPill")
    selectors = re.findall(r"([^{}]*statusPill[^{}]*)\{", qss)
    assert selectors and not any(":hover" in s for s in selectors)


@pytest.mark.parametrize("surface,token", [
    ("panel", "bg.panel"), ("raised", "bg.raised"), ("inset", "bg.inset")])
def test_surface_property_rules(surface, token):
    pal = SCARLET_SKEUO.palette
    body = rule_blocks(build_qss(SCARLET_SKEUO), f'QFrame[surface="{surface}"]')
    assert body and pal.color(token) in body[0]


def test_legacy_object_names_and_new_hooks_are_present():
    qss = build_qss(SCARLET_SKEUO)
    for name in ("rackChassis", "masterHeadStrip", "modularBay", "pluginRackCard",
                 "channelStrip", "statusPill", "chainCard", "flowPill", "rackList"):
        assert f"#{name}" in qss, name


def test_shape_tokens_drive_radius_and_flat_panel():
    skeuo = build_qss(SCARLET_SKEUO)
    minimal = build_qss(Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["minimal"]))
    pal = SCARLET_SKEUO.palette
    bay_s = rule_blocks(skeuo, "QFrame#modularBay")[0]
    bay_m = rule_blocks(minimal, "QFrame#modularBay")[0]
    assert "border-radius: 6px" in bay_s and "border-radius: 10px" in bay_m
    # flat panel skin: modular bay sits on the panel colour, head strip has no gradient.
    assert pal.color("bg.window") in bay_s and pal.color("bg.panel") in bay_m
    assert "qlineargradient" in rule_blocks(skeuo, "QFrame#masterHeadStrip")[0]
    assert "qlineargradient" not in rule_blocks(minimal, "QFrame#masterHeadStrip")[0]


def _qt_parse_messages(qss: str) -> list[str]:
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QPushButton, QWidget

    messages: list[str] = []
    qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    try:
        host = QWidget()
        btn = QPushButton("x", host)
        btn.setProperty("tier", "primary")
        host.setStyleSheet(qss)
        host.ensurePolished()
        btn.ensurePolished()
    finally:
        qInstallMessageHandler(None)
    return [m for m in messages if "parse" in m.lower()]


def test_parse_check_detects_a_broken_sheet(qapp):
    assert _qt_parse_messages("QPushButton { color: red ")


@pytest.mark.parametrize("look", ALL_LOOKS)
def test_stylesheet_parses_cleanly_in_qt(qapp, look):
    assert _qt_parse_messages(build_qss(look)) == []


def test_set_look_applies_the_real_stylesheet(qapp, restore_look):
    look = Look(BUILTIN_PALETTES["cyan"], BUILTIN_SKINS["vintage"])
    set_look(look)
    assert qapp.styleSheet() == build_qss(look)
