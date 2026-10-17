"""Palette derivation in OKLCH with WCAG 2.x contrast enforcement.

Pure Python, no Qt. Colour maths follows Bjorn Ottosson's published sRGB <->
OKLab matrices; contrast uses WCAG 2.x relative luminance.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

TEXT_MIN = 4.5
UI_MIN = 3.0

# tint name -> (hue degrees or None, chroma). A None hue means "follow the
# accent's hue", so neutral surfaces carry only a whisper of the accent.
TINTS: dict[str, tuple[float | None, float]] = {
    "neutral": (None, 0.008),
    "warm": (60.0, 0.02),
    "cool": (250.0, 0.02),
}

PALETTE_TOKENS: tuple[str, ...] = (
    "bg.window", "bg.panel", "bg.raised", "bg.inset", "bg.overlay",
    "line.subtle", "line.strong", "focus.ring",
    "text.primary", "text.secondary", "text.disabled", "text.on_accent",
    "accent", "accent.hover", "accent.pressed", "accent.subtle",
    "status.ok", "status.ok.subtle", "status.warn", "status.warn.subtle",
    "status.danger", "status.danger.subtle",
    "meter.low", "meter.mid", "meter.high", "meter.off",
    "readout.text",
)

# (token, partner token, minimum ratio). text.on_accent is checked against the
# accent only (it sits on the accent fill, never on a surface).
CONTRAST_PAIRS: tuple[tuple[str, str, float], ...] = (
    *((t, bg, TEXT_MIN)
      for t in ("text.primary", "text.secondary")
      for bg in ("bg.window", "bg.panel", "bg.raised")),
    ("text.on_accent", "accent", TEXT_MIN),
    *((t, "bg.panel", UI_MIN)
      for t in ("accent", "focus.ring", "line.strong",
                "status.ok", "status.warn", "status.danger")),
)


@dataclass(frozen=True)
class ContrastIssue:
    token: str
    partner: str
    ratio: float
    target: float


# --------------------------------------------------------------- colour maths

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_GAMUT_EPS = 1e-4


def _parse_hex(hex_: str) -> tuple[int, int, int]:
    if not isinstance(hex_, str) or not _HEX_RE.match(hex_):
        raise ValueError(f"expected #rrggbb colour, got {hex_!r}")
    return int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16)


def _to_linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _from_linear(v: float) -> float:
    if v <= 0.0:
        return 12.92 * v  # keep the sign so gamut checks see negatives
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def hex_to_oklch(hex_: str) -> tuple[float, float, float]:
    """``#rrggbb`` -> (L 0..1, C, h degrees 0..360). Achromatic colours get h=0."""
    r, g, b = (_to_linear(c / 255.0) for c in _parse_hex(hex_))
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    lab_l = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    lab_a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    lab_b = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    chroma = math.hypot(lab_a, lab_b)
    hue = math.degrees(math.atan2(lab_b, lab_a)) % 360.0 if chroma > 1e-4 else 0.0
    return lab_l, chroma, hue


def _encode(l: float, c: float, h: float) -> tuple[bool, tuple[float, float, float]]:
    """OKLCH -> gamma-encoded sRGB floats plus whether they sit inside the gamut."""
    hr = math.radians(h)
    a, b = c * math.cos(hr), c * math.sin(hr)
    l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (l - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
           -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
           -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)
    enc = (_from_linear(lin[0]), _from_linear(lin[1]), _from_linear(lin[2]))
    return all(-_GAMUT_EPS <= v <= 1.0 + _GAMUT_EPS for v in enc), enc


def oklch_to_hex(l: float, c: float, h: float) -> str:
    """OKLCH -> lowercase ``#rrggbb``. Out-of-gamut colours lose chroma (hue and
    lightness kept) until they fit sRGB."""
    l = min(max(l, 0.0), 1.0)
    c = max(c, 0.0)
    ok, enc = _encode(l, c, h)
    if not ok:
        lo, hi = 0.0, c
        for _ in range(30):
            mid = (lo + hi) / 2
            if _encode(l, mid, h)[0]:
                lo = mid
            else:
                hi = mid
        enc = _encode(l, lo, h)[1]
    r, g, b = (round(min(max(v, 0.0), 1.0) * 255) for v in enc)
    return f"#{r:02x}{g:02x}{b:02x}"


def _luminance(hex_: str) -> float:
    r, g, b = (_to_linear(c / 255.0) for c in _parse_hex(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio, 1.0 .. 21.0."""
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def check_colors(colors: Mapping[str, str]) -> list[ContrastIssue]:
    """Every CONTRAST_PAIRS entry (with both tokens present) below its target."""
    issues: list[ContrastIssue] = []
    for token, partner, target in CONTRAST_PAIRS:
        if token not in colors or partner not in colors:
            continue
        ratio = contrast_ratio(colors[token], colors[partner])
        if ratio < target:
            issues.append(ContrastIssue(token, partner, ratio, target))
    return issues


# ----------------------------------------------------------------- derivation

_DARK = {"surf": (0.16, 0.19, 0.23, 0.14, 0.27),   # window, panel, raised, inset, overlay
         "text": (0.95, 0.75, 0.50),               # primary, secondary, disabled
         "line": (0.30, 0.50), "meter_off": 0.24,
         "accent_subtle": 0.28, "status_l": 0.72, "status_subtle": 0.26}
_LIGHT = {"surf": (0.96, 0.93, 0.99, 0.90, 0.99),
          "text": (0.20, 0.42, 0.65),
          "line": (0.86, 0.60), "meter_off": 0.86,
          "accent_subtle": 0.92, "status_l": 0.50, "status_subtle": 0.93}
# status name -> (hue degrees, base chroma); only lightness adapts to surfaces
_STATUS = {"ok": (150.0, 0.16), "warn": (75.0, 0.15), "danger": (25.0, 0.19)}


def _tint_hue_chroma(tint: str, accent_hue: float) -> tuple[float, float]:
    if tint in TINTS:
        hue, chroma = TINTS[tint]
        return (accent_hue if hue is None else hue), chroma
    if isinstance(tint, str) and _HEX_RE.match(tint):
        # A picked colour contributes its hue only, at the same low chroma as warm/cool.
        return hex_to_oklch(tint)[2], TINTS["warm"][1]
    raise ValueError(f"unknown tint {tint!r}; use one of {sorted(TINTS)} or #rrggbb")


def _nudge(l: float, c: float, h: float, bg: str, target: float,
           step: float) -> tuple[str, float, bool]:
    """Move lightness by 0.01 * step until contrast vs ``bg`` reaches target
    (or the L range ends). Returns (hex, final L, changed)."""
    hx = oklch_to_hex(l, c, h)
    changed = False
    while contrast_ratio(hx, bg) < target and 0.0 <= l + 0.01 * step <= 1.0:
        l += 0.01 * step
        hx = oklch_to_hex(l, c, h)
        changed = True
    return hx, l, changed


def derive_colors(accent: str, tint: str = "neutral",
                  dark: bool = True) -> tuple[dict[str, str], list[str]]:
    """Derive every PALETTE_TOKENS colour from an accent and a surface tint.

    Returns (colors, notices). Notices are human-readable adjustments, e.g.
    ``"accent: adjusted for readability"``.
    """
    spec = _DARK if dark else _LIGHT
    step = 1.0 if dark else -1.0  # lightness direction that raises contrast vs the panel
    al, ac, ah = hex_to_oklch(accent)
    th, tc = _tint_hue_chroma(tint, ah)
    notes: list[str] = []
    out: dict[str, str] = {}

    win, pan, raised, inset, overlay = spec["surf"]
    for key, l in (("bg.window", win), ("bg.panel", pan), ("bg.raised", raised),
                   ("bg.inset", inset), ("bg.overlay", overlay)):
        out[key] = oklch_to_hex(l, tc, th)
    panel = out["bg.panel"]

    t1, t2, t3 = spec["text"]
    for key, l in (("text.primary", t1), ("text.secondary", t2)):
        for bg in ("bg.window", "bg.panel", "bg.raised"):  # clear the worst surface
            hx, l, _ = _nudge(l, tc, th, out[bg], TEXT_MIN, step)
        out[key] = hx
    out["text.disabled"] = oklch_to_hex(t3, tc, th)

    line_subtle, line_strong = spec["line"]
    out["line.subtle"] = oklch_to_hex(line_subtle, tc, th)
    out["line.strong"], _, _ = _nudge(line_strong, tc, th, panel, UI_MIN, step)

    # Accent: keep the picked colour unless it fails 3:1 against the panel.
    out["accent"], cl, changed = _nudge(al, ac, ah, panel, UI_MIN, step)
    if changed:
        notes.append("accent: adjusted for readability")
    cc = min(ac, hex_to_oklch(out["accent"])[1])  # chroma after any gamut reduction
    out["accent.hover"] = oklch_to_hex(cl + 0.05 * step, cc, ah)
    out["accent.pressed"] = oklch_to_hex(cl - 0.05 * step, cc, ah)
    out["accent.subtle"] = oklch_to_hex(spec["accent_subtle"], min(cc, 0.07), ah)
    out["focus.ring"], _, _ = _nudge(cl + 0.12 * step, cc, ah, panel, UI_MIN, step)

    # text.on_accent: near-white or near-black (tinted); pure white/black as a
    # last resort, which always reaches 4.5 on any fill.
    near_white, near_black = oklch_to_hex(0.985, tc, th), oklch_to_hex(0.14, tc, th)
    for cand in (near_white, near_black, "#ffffff", "#000000"):
        if contrast_ratio(cand, out["accent"]) >= TEXT_MIN:
            out["text.on_accent"] = cand
            break

    for name, (hue, chroma) in _STATUS.items():
        out[f"status.{name}"], _, _ = _nudge(spec["status_l"], chroma, hue, panel, UI_MIN, step)
        out[f"status.{name}.subtle"] = oklch_to_hex(spec["status_subtle"], 0.06, hue)
    out["meter.low"], out["meter.mid"], out["meter.high"] = (
        out["status.ok"], out["status.warn"], out["status.danger"])
    out["meter.off"] = oklch_to_hex(spec["meter_off"], tc, th)

    out["readout.text"] = oklch_to_hex(max(cl, 0.80) if dark else min(cl, 0.45), cc, ah)

    return {k: out[k] for k in PALETTE_TOKENS}, notes
