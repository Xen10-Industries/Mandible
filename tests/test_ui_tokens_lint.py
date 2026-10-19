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


def test_repo_passes_with_an_empty_legacy_allowlist(tool):
    assert tool.ALLOWLIST_LEGACY == set()
    proc = run()
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_former_legacy_modules_have_no_literals(tool):
    """Task 8c: gui.py (now a shim), the main window, the overlay and the waveform widget."""
    for rel in ("mandible/gui.py", "mandible/ui/main_window.py", "mandible/ui/app.py",
                "mandible/overlay.py", "mandible/waveform_widget.py"):
        assert not tool.is_allowed(rel), rel
        assert tool.scan_file(ROOT / rel, ROOT) == [], rel


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


def test_widget_modules_have_no_literals(tool):
    """Task 8a: the widgets under mandible/ui/widgets are never on the allowlist."""
    for path in sorted((ROOT / "mandible" / "ui" / "widgets").glob("*.py")):
        assert not tool.is_allowed(tool._relative(path, ROOT)), path
        assert tool.scan_file(path, ROOT) == [], path


def test_dialog_modules_have_no_literals(tool):
    """Task 8b: the dialogs under mandible/ui/dialogs are never on the allowlist."""
    paths = sorted((ROOT / "mandible" / "ui" / "dialogs").glob("*.py"))
    assert {p.stem for p in paths} >= {"param_map", "hotkey", "add_plugin", "prefx", "soundboard",
                                       "settings", "setup_assistant", "about"}
    for path in paths:
        assert not tool.is_allowed(tool._relative(path, ROOT)), path
        assert tool.scan_file(path, ROOT) == [], path
