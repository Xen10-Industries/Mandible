"""Token lint: no hex colour literals and no ``setStyleSheet(`` outside the UI core.

Colours come from the Look (``mandible/ui/look.py`` palettes) and styling from the one
generated stylesheet (``mandible/ui/stylesheet.py``); widgets use object names and dynamic
properties instead of inline styles.

Usage: ``python tools/check_ui_tokens.py [paths...]`` (default: the ``mandible/`` package).
Prints ``file:line: message`` for each finding and exits 1 if there are any (2 for a bad
path). Only the string-literal contents of hex colours are checked (via ``tokenize``), so
comments, ``#1`` in prose and f-string format specs such as ``{n:#06x}`` are not flagged.
"""
from __future__ import annotations

import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Modules that define the look and may hold colour literals / build stylesheets.
ALLOWED_MODULES = {
    "mandible/ui/look.py",
    "mandible/ui/stylesheet.py",
    "mandible/ui/palette_gen.py",
    "mandible/branding.py",
}
# Files not yet migrated; Task 8c empties this set.
ALLOWLIST_LEGACY: set[str] = {
    "mandible/gui.py",
    "mandible/setup_assistant.py",
    "mandible/overlay.py",
    "mandible/waveform_widget.py",
    "mandible/about.py",
}

# #rgb, #rrggbb and #rrggbbaa, not part of a longer word (so "#abcd" and "#12" pass).
HEX_RE = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_])")

_SKIP_TYPES = {tokenize.NL, tokenize.COMMENT}
_STRING_TYPES = {tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", tokenize.STRING)}
_STATEMENT_START = {None, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING}


def is_allowed(rel: str) -> bool:
    return rel in ALLOWED_MODULES or rel in ALLOWLIST_LEGACY


def scan_source(source: str) -> list[tuple[int, str]]:
    """Return ``(line, message)`` findings for Python ``source`` text."""
    findings: list[tuple[int, str]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        return [(1, f"cannot tokenize: {exc}")]
    significant = [t for t in tokens if t.type not in _SKIP_TYPES]
    prev_type = None
    for i, tok in enumerate(significant):
        nxt = significant[i + 1] if i + 1 < len(significant) else None
        if tok.type == tokenize.NAME and tok.string == "setStyleSheet":
            before = significant[i - 1] if i else None
            is_def = before is not None and before.type == tokenize.NAME and before.string == "def"
            if not is_def and nxt is not None and nxt.type == tokenize.OP and nxt.string == "(":
                findings.append((tok.start[0], "setStyleSheet( call; use objectName/properties"))
        elif tok.type in _STRING_TYPES:
            # A bare string statement (docstring) cannot style anything; skip it.
            bare = (tok.type == tokenize.STRING and prev_type in _STATEMENT_START
                    and (nxt is None or nxt.type in (tokenize.NEWLINE, tokenize.ENDMARKER)))
            if not bare:
                for m in HEX_RE.finditer(tok.string):
                    line = tok.start[0] + tok.string.count("\n", 0, m.start())
                    findings.append((line, f"hex colour literal {m.group(0)}; use a palette token"))
        prev_type = tok.type
    return sorted(findings)


def _relative(path: pathlib.Path, root: pathlib.Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def scan_file(path: pathlib.Path, root: pathlib.Path = ROOT) -> list[str]:
    """Findings for one file as ``rel/path.py:line: message`` (allow-list is not applied)."""
    rel = _relative(path, root)
    source = path.read_text(encoding="utf-8", errors="replace")
    return [f"{rel}:{line}: {msg}" for line, msg in scan_source(source)]


def iter_python_files(paths: list[pathlib.Path]):
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*.py")):
                if "__pycache__" not in f.parts:
                    yield f
        else:
            yield p


def main(argv: list[str]) -> int:
    targets = [pathlib.Path(a) for a in argv] or [ROOT / "mandible"]
    missing = [str(p) for p in targets if not p.exists()]
    if missing:
        print("check_ui_tokens: no such path: " + ", ".join(missing), file=sys.stderr)
        return 2
    findings: list[str] = []
    for f in iter_python_files(targets):
        if is_allowed(_relative(f, ROOT)):
            continue
        findings.extend(scan_file(f, ROOT))
    if findings:
        print("\n".join(findings))
        print(f"check_ui_tokens: {len(findings)} finding(s); colours and styles belong in "
              "mandible/ui/look.py and mandible/ui/stylesheet.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
