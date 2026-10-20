"""Shared pytest fixtures for the Mandible test suite.

The environment is configured at import time, before any ``mandible`` module is imported:
``mandible.paths`` reads %APPDATA% when it is first imported, so tests must never see the real
user profile. Nothing here may touch the real desktop or the startup registry key.
"""
from __future__ import annotations

import gc
import os
import pathlib
import shutil
import tempfile

import pytest

_APPDATA_DIR = pathlib.Path(tempfile.mkdtemp(prefix="mandible-test-appdata-"))
os.environ["APPDATA"] = str(_APPDATA_DIR)
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(autouse=True)
def _collect_garbage_on_gui_thread():
    """Collect reference cycles left by a test on the main (GUI) thread.

    A Qt widget whose Python wrapper sits in a reference cycle (lambdas connected to its
    own signals) is only freed by the cyclic garbage collector, which runs in whichever
    thread happens to allocate next: e.g. the reader threads ``subprocess.run`` starts.
    Destroying a widget there corrupts Qt's state and crashes a later test.
    """
    yield
    gc.collect()


class FakeStartupRegistry:
    """In-memory stand-in for the HKCU ``Run`` key helpers in ``mandible.config``."""

    def __init__(self):
        self.enabled = False
        self.calls: list[tuple[bool, bool]] = []

    def is_startup_enabled(self) -> bool:
        return self.enabled

    def set_startup_enabled(self, enabled: bool, start_minimized: bool = False) -> bool:
        self.calls.append((bool(enabled), bool(start_minimized)))
        self.enabled = bool(enabled)
        return True


STARTUP_FUNCTIONS = ("is_startup_enabled", "set_startup_enabled")
# Modules that import the helpers by name (``from ...config import set_startup_enabled``);
# imported up front so their bindings exist to be replaced.
STARTUP_IMPORTERS = ("mandible.config", "mandible.ui.dialogs.settings")


@pytest.fixture(autouse=True)
def startup_registry(appdata):
    """Tests never read or write the real ``HKCU\\...\\Run`` key: every loaded ``mandible``
    module's ``is_startup_enabled`` / ``set_startup_enabled`` is swapped for a fake.

    Uses its own MonkeyPatch (not the ``monkeypatch`` fixture), so being autouse does not
    change when other tests' ``monkeypatch`` undo runs relative to their own fixtures."""
    import importlib
    import sys

    for name in STARTUP_IMPORTERS:
        importlib.import_module(name)
    config = sys.modules["mandible.config"]
    real = {fn: getattr(config, fn) for fn in STARTUP_FUNCTIONS}
    fake = FakeStartupRegistry()
    fake.real = real
    patch = pytest.MonkeyPatch()
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not (mod_name == "mandible" or mod_name.startswith("mandible.")):
            continue
        for fn in STARTUP_FUNCTIONS:
            bound = getattr(mod, fn, None)
            if bound is real[fn] or isinstance(getattr(bound, "__self__", None), FakeStartupRegistry):
                patch.setattr(mod, fn, getattr(fake, fn))
    try:
        yield fake
    finally:
        patch.undo()


@pytest.fixture(scope="session")
def appdata() -> pathlib.Path:
    """Temporary %APPDATA% (set before ``mandible`` is imported)."""
    yield _APPDATA_DIR
    shutil.rmtree(_APPDATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def qapp(appdata):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    for w in list(app.topLevelWidgets()):
        try:
            w.hide()
            w.deleteLater()
        except RuntimeError:
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
    gc.collect()


@pytest.fixture
def core(qapp):
    """A Core on a fresh AppConfig (no audio stream), shut down after the test."""
    from mandible.config import AppConfig
    from mandible.core import Core

    cfg = AppConfig()
    cfg.autostart_audio = False
    c = Core(cfg)
    yield c
    c.shutdown()


@pytest.fixture
def sample_core(qapp):
    """A Core with four internal-DSP chains and three soundboard clips, shut down after the test."""
    from mandible.ui.sample_setup import build_sample_core

    c = build_sample_core()
    yield c
    c.shutdown()
