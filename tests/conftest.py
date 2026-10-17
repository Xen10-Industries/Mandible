"""Shared pytest fixtures for the Mandible test suite.

The environment is configured at import time, before any ``mandible`` module is imported:
``mandible.paths`` reads %APPDATA% when it is first imported, so tests must never see the real
user profile. Nothing here may touch the real desktop or the startup registry key.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import tempfile

import pytest

_APPDATA_DIR = pathlib.Path(tempfile.mkdtemp(prefix="mandible-test-appdata-"))
os.environ["APPDATA"] = str(_APPDATA_DIR)
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def appdata() -> pathlib.Path:
    """Temporary %APPDATA% (set before ``mandible`` is imported)."""
    yield _APPDATA_DIR
    shutil.rmtree(_APPDATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def qapp(appdata):
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


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
def sample_core(core):
    """``core`` plus four internal-DSP chains and three soundboard clips."""
    from mandible.config import SoundboardClipConfig

    layout = {
        "Robot Voice": ("toggle", ["internal:pitch_formant", "internal:gsm", "internal:reverb"]),
        "Deep Narrator": ("hold", ["internal:pitch_formant", "internal:reverb"]),
        "Walkie-Talkie": ("toggle", ["internal:gsm", "internal:filter"]),
        "Cave Echo": ("toggle", ["internal:reverb", "internal:delay"]),
    }
    for name, (mode, paths) in layout.items():
        chain = core.add_chain(name)
        chain.mode = mode
        for path in paths:
            core.add_plugin(chain, path)
    for clip_name in ("Airhorn", "Rimshot", "Sad trombone"):
        core.cfg.soundboard.append(SoundboardClipConfig(name=clip_name, path=""))
    return core
