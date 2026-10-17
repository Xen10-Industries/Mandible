import re

import pytest

from mandible.ui.palette_gen import (
    CONTRAST_PAIRS,
    PALETTE_TOKENS,
    TEXT_MIN,
    TINTS,
    UI_MIN,
    ContrastIssue,
    check_colors,
    contrast_ratio,
    derive_colors,
    hex_to_oklch,
    oklch_to_hex,
)

ACCENTS = ["#e11d48", "#06b6d4", "#10b981", "#d97706", "#000000", "#ffffff",
           "#ffff00", "#0000ff", "#404040"]
HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def test_contrast_ratio_extremes():
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)


def test_oklch_round_trip():
    assert oklch_to_hex(*hex_to_oklch("#e11d48")) == "#e11d48"
    for h in ("#000000", "#ffffff", "#808080", "#06b6d4", "#0000ff", "#ffff00"):
        assert oklch_to_hex(*hex_to_oklch(h)) == h


def test_oklch_known_values():
    l, c, _ = hex_to_oklch("#ffffff")
    assert l == pytest.approx(1.0, abs=1e-3) and c == pytest.approx(0.0, abs=1e-3)
    l, c, _ = hex_to_oklch("#000000")
    assert l == pytest.approx(0.0, abs=1e-6)


def test_oklch_to_hex_reduces_chroma_out_of_gamut():
    out = oklch_to_hex(0.7, 0.5, 145.0)
    assert HEX_RE.match(out)
    l, c, h = hex_to_oklch(out)
    assert l == pytest.approx(0.7, abs=0.02)
    assert abs(h - 145.0) < 8.0


def test_invalid_hex_raises():
    with pytest.raises(ValueError):
        hex_to_oklch("not-a-colour")


def test_constants():
    assert TEXT_MIN == 4.5 and UI_MIN == 3.0
    assert TINTS == {"neutral": (None, 0.008), "warm": (60.0, 0.02), "cool": (250.0, 0.02)}


def test_palette_tokens():
    assert len(PALETTE_TOKENS) == 27 and len(set(PALETTE_TOKENS)) == 27
    assert PALETTE_TOKENS[0] == "bg.window" and PALETTE_TOKENS[-1] == "readout.text"
    assert PALETTE_TOKENS[11] == "text.on_accent" and PALETTE_TOKENS[12] == "accent"


def test_contrast_pairs_shape():
    assert ("text.primary", "bg.window", 4.5) in CONTRAST_PAIRS
    assert ("text.secondary", "bg.raised", 4.5) in CONTRAST_PAIRS
    assert ("text.on_accent", "accent", 4.5) in CONTRAST_PAIRS
    assert ("line.strong", "bg.panel", 3.0) in CONTRAST_PAIRS
    assert ("focus.ring", "bg.panel", 3.0) in CONTRAST_PAIRS
    assert ("status.danger", "bg.panel", 3.0) in CONTRAST_PAIRS
    assert all(t != "text.disabled" for t, _, _ in CONTRAST_PAIRS)
    for tok, partner, target in CONTRAST_PAIRS:
        assert tok in PALETTE_TOKENS and partner in PALETTE_TOKENS
        assert target in (TEXT_MIN, UI_MIN)


@pytest.mark.parametrize("dark", [True, False])
@pytest.mark.parametrize("tint", list(TINTS))
@pytest.mark.parametrize("accent", ACCENTS)
def test_derived_palettes_meet_contrast(accent, tint, dark):
    colors, _ = derive_colors(accent, tint, dark)
    assert check_colors(colors) == []


def test_derive_returns_every_token_lowercase_hex():
    colors, _ = derive_colors("#e11d48")
    assert set(colors) == set(PALETTE_TOKENS)
    assert all(HEX_RE.match(v) for v in colors.values())


def test_good_accent_is_kept_verbatim():
    colors, notes = derive_colors("#ffffff")
    assert colors["accent"] == "#ffffff"
    assert notes == []


def test_black_accent_is_adjusted_with_notice():
    colors, notes = derive_colors("#000000")
    assert "accent: adjusted for readability" in notes
    assert colors["accent"] != "#000000"


def test_light_accent_gets_dark_on_accent_text():
    colors, _ = derive_colors("#ffff00")
    assert contrast_ratio(colors["text.on_accent"], colors["accent"]) >= 4.5
    assert colors["text.on_accent"] < "#808080"


@pytest.mark.parametrize("accent", ACCENTS)
def test_danger_hue_is_fixed(accent):
    colors, _ = derive_colors(accent)
    h = hex_to_oklch(colors["status.danger"])[2]
    assert min(abs(h - 25.0), 360 - abs(h - 25.0)) <= 15.0


def test_status_hues_ok_and_warn():
    colors, _ = derive_colors("#0000ff")
    for tok, hue in (("status.ok", 150.0), ("status.warn", 75.0)):
        h = hex_to_oklch(colors[tok])[2]
        assert abs(h - hue) <= 15.0


def test_dark_surfaces_ordering():
    c, _ = derive_colors("#06b6d4")
    ls = {k: hex_to_oklch(c[k])[0] for k in ("bg.inset", "bg.window", "bg.panel", "bg.raised", "bg.overlay")}
    assert ls["bg.inset"] < ls["bg.window"] < ls["bg.panel"] < ls["bg.raised"] < ls["bg.overlay"]
    assert ls["bg.window"] == pytest.approx(0.16, abs=0.01)


def test_tint_warm_vs_cool_hue():
    warm = hex_to_oklch(derive_colors("#06b6d4", "warm")[0]["bg.panel"])[2]
    cool = hex_to_oklch(derive_colors("#06b6d4", "cool")[0]["bg.panel"])[2]
    assert abs(warm - 60.0) < 25.0
    assert abs(cool - 250.0) < 25.0


def test_hex_tint_uses_its_hue():
    colors, _ = derive_colors("#06b6d4", "#3366cc")
    assert check_colors(colors) == []
    h_target = hex_to_oklch("#3366cc")[2]
    h = hex_to_oklch(colors["bg.raised"])[2]
    assert abs(h - h_target) < 25.0


def test_bad_tint_raises():
    with pytest.raises(ValueError):
        derive_colors("#e11d48", "sepia")


def test_check_colors_reports_failures():
    colors, _ = derive_colors("#e11d48")
    colors["text.primary"] = colors["bg.window"]
    issues = check_colors(colors)
    assert issues and all(isinstance(i, ContrastIssue) for i in issues)
    bad = [i for i in issues if i.token == "text.primary" and i.partner == "bg.window"]
    assert bad and bad[0].target == 4.5 and bad[0].ratio == pytest.approx(1.0)
