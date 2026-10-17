"""tools/check_ui_tokens.py: no hex literals or setStyleSheet outside the allowed modules."""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_ui_tokens.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], cwd=ROOT,
                          capture_output=True, text=True)


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("check_ui_tokens", TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_ui_tokens"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_repo_passes_with_the_legacy_allowlist():
    proc = run()
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_legacy_allowlist_contents(tool):
    assert tool.ALLOWLIST_LEGACY == {
        "mandible/gui.py", "mandible/setup_assistant.py", "mandible/overlay.py",
        "mandible/waveform_widget.py", "mandible/about.py"}


def test_legacy_files_are_flagged_without_the_allowlist(tool):
    findings = tool.scan_file(ROOT / "mandible" / "gui.py", ROOT)
    assert findings, "gui.py still has literals; the allowlist is what keeps the lint green"
    # Paths are repo-relative with forward slashes.
    assert all(f.startswith("mandible/gui.py:") for f in findings)


def test_setstylesheet_call_and_hex_are_flagged(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('w.setStyleSheet("color:#fff")\n', encoding="utf-8")
    proc = run(str(bad))
    assert proc.returncode == 1
    lines = [ln for ln in proc.stdout.splitlines() if "bad.py:1" in ln]
    assert len(lines) == 2  # one for the call, one for the literal
    assert any("setStyleSheet" in ln for ln in lines)
    assert any("#fff" in ln for ln in lines)


@pytest.mark.parametrize("source,expected", [
    ('x = "#abc"\n', 1),
    ('x = "#a1b2c3"\n', 1),
    ("x = '#A1B2C3'\n", 1),
    ('x = f"border:1px solid #1e2330; {w}"\n', 1),
    ('x = "#12"\n', 0),
    ('x = "#abcd"\n', 0),
    ('# #fff in a comment\n', 0),
    ('# see #1\ny = 1\n', 0),
    ('x = f"{n:#06x} {m:#010b}"\n', 0),
    ('"""issue #123 is fixed"""\nx = 1\n', 0),
    ('def f():\n    """See #123."""\n    return 1\n', 0),
    ('x = "no colour here"\n', 0),
    ('x = "setStyleSheet(not a call)"\n', 0),
    ('w.setStyleSheet(qss)\n', 1),
    ('w.setStyleSheet (qss)\n', 1),
    ('def setStyleSheet(x):\n    pass\n', 0),
])
def test_scan_source_cases(tool, source, expected):
    assert len(tool.scan_source(source)) == expected


def test_allowed_modules_are_never_flagged(tool):
    for rel in ("mandible/ui/look.py", "mandible/ui/stylesheet.py",
                "mandible/ui/palette_gen.py", "mandible/branding.py"):
        assert tool.is_allowed(rel), rel
        proc = run(rel)
        assert proc.returncode == 0, rel + proc.stdout


def test_nonexistent_path_is_an_error():
    proc = run("does/not/exist.py")
    assert proc.returncode == 2
