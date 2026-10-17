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
def sample_core(qapp):
    """A Core with four internal-DSP chains and three soundboard clips, shut down after the test."""
    from mandible.ui.sample_setup import build_sample_core

    c = build_sample_core()
    yield c
    c.shutdown()
