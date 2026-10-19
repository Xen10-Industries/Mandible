"""Text helpers for compact UI labels (no Qt dependency)."""
from __future__ import annotations

__all__ = ["abbreviate_title"]

# Whole-word abbreviations used on knob titles (applied before any length check, so
# "Threshold" reads THRESH even though it would fit).
_WORDS = {
    "threshold": "THRESH",
    "feedback": "FEEDBK",
    "frequency": "FREQ",
    "parameter": "PARAM",
    "semitones": "SEMI",
    "tolerance": "TOLER",
    "look-ahead": "LOOKAHD",
    "lookahead": "LOOKAHD",
    "resonance": "RESO",
}
_PHRASES = {"delay time": "DELAY"}


def abbreviate_title(name: str, max_len: int = 9) -> str:
    """Upper-case ``name`` and shorten it to ``max_len`` characters on word boundaries.

    Known long words are abbreviated (Threshold -> THRESH); a name that is still too long
    keeps its longest run of trailing words that fits (Radio Squelch -> SQUELCH, Stereo
    Width -> WIDTH); a single word that cannot fit is cut. Callers show the full name in
    a tooltip.
    """
    s = (name or "").strip()
    if ":" in s:
        # "GATE: Attack" -> "GA.ATTACK" when that fits, else the part after the colon.
        prefix, rest = (p.strip() for p in s.split(":", 1))
        short = f"{prefix[:2]}.{rest}" if prefix and len(prefix) <= 4 else ""
        s = short if short and len(short) <= max_len else (rest or prefix)
    if "(" in s:
        s = s.split("(", 1)[0].strip() or s
    if s.lower() in _PHRASES:
        return _PHRASES[s.lower()]
    words = [_WORDS.get(w.lower(), w.upper()) for w in s.split()]
    if not words:
        return ""
    for start in range(len(words)):
        candidate = " ".join(words[start:])
        if len(candidate) <= max_len:
            return candidate
    return words[-1][:max_len]
