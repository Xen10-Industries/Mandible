"""Unit tests for Mandible Clarity sidecar detection, hardware acceleration, and audio streaming."""
from __future__ import annotations

import os
import numpy as np
import pytest

from mandible.clarity import (
    ClarityStream,
    detect_clarity_hardware,
    find_mandible_clarity_exe,
)
from mandible.prefx import PreFXProcessor, PreFXSettings


def test_find_mandible_clarity_exe_detects_sibling_or_env(monkeypatch, tmp_path):
    # Test environment variable override
    fake_exe = str(tmp_path / "custom_clarity.exe")
    with open(fake_exe, "w") as f:
        f.write("echo custom")

    monkeypatch.setenv("MANDIBLE_CLARITY_EXE", fake_exe)
    assert find_mandible_clarity_exe() == fake_exe

    # Test fallback detection without env var
    monkeypatch.delenv("MANDIBLE_CLARITY_EXE", raising=False)
    exe = find_mandible_clarity_exe()
    # If sibling repo exists on developer machine, exe is found
    if exe is not None:
        assert os.path.exists(exe)


def test_detect_clarity_hardware_returns_valid_info():
    available, device_name, backend_desc = detect_clarity_hardware()
    assert isinstance(available, bool)
    assert available is True
    assert isinstance(device_name, str) and len(device_name) > 0
    assert isinstance(backend_desc, str) and len(backend_desc) > 0


def test_clarity_stream_processes_48k_mono_audio():
    stream = ClarityStream(samplerate=48000)
    assert stream.is_available() is True

    # Generate 480-sample test tone (10ms)
    t = np.linspace(0, 0.01, 480, endpoint=False, dtype=np.float32)
    tone = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)

    out = stream.process(tone, wet=1.0, atten_limit_db=35.0, dereverb=True)
    assert out.shape == tone.shape
    assert out.dtype == np.float32
    assert not np.isnan(out).any()
    assert not np.isinf(out).any()


def test_clarity_stream_resampling_at_44k():
    stream = ClarityStream(samplerate=44100)
    tone = np.zeros(512, dtype=np.float32)

    out = stream.process(tone, wet=1.0)
    assert out.shape == tone.shape
    assert out.dtype == np.float32
    assert not np.isnan(out).any()


def test_prefx_processor_routes_to_clarity():
    cfg = PreFXSettings(
        highpass_enabled=False,
        rnnoise_enabled=True,
        noise_engine="clarity",
        clarity_atten_limit_db=30.0,
        clarity_dereverb=True,
        noise_gate_enabled=False,
    )
    proc = PreFXProcessor(cfg, samplerate=48000)
    audio = np.random.uniform(-0.1, 0.1, 480).astype(np.float32)

    cleaned = proc.process(audio)
    assert cleaned.shape == audio.shape
    assert not np.isnan(cleaned).any()

    # Switch engine to rnnoise and process again
    cfg.noise_engine = "rnnoise"
    proc.update_settings(cfg)
    cleaned_rnn = proc.process(audio)
    assert cleaned_rnn.shape == audio.shape
    proc.close()


def test_clarity_stream_suppresses_clicks_and_thumps():
    stream = ClarityStream(samplerate=48000)
    rng = np.random.default_rng(42)
    # 1 second of room noise + keyboard tap transients + 50 Hz mic bump
    n = 48000
    t = np.arange(n, dtype=np.float32) / 48000.0
    noise = (0.015 * rng.standard_normal(n)).astype(np.float32)
    # Add sharp keyboard clicks every 100 ms
    for idx in range(4800, n, 4800):
        decay = np.exp(-np.arange(240, dtype=np.float32) / 35.0)
        noise[idx : idx + 240] += 0.25 * decay * rng.standard_normal(240).astype(np.float32)
    # Add a 50 Hz mic bump at 0.5 s
    bump_len = 2400
    bump_t = np.arange(bump_len, dtype=np.float32) / 48000.0
    noise[24000 : 24000 + bump_len] += 0.35 * np.sin(2 * np.pi * 50.0 * bump_t) * np.exp(-bump_t * 25.0)

    out = stream.process(noise, wet=1.0, atten_limit_db=100.0, dereverb=True)
    # If weights are installed on this machine, test deep suppression;
    # otherwise verify that fallback spectral processing ran without exploding or NaNs.
    assert not np.isnan(out).any()
    assert not np.isinf(out).any()
    if stream._dfn3 is not None:
        in_rms = float(np.sqrt(np.mean(noise[9600:] ** 2)))
        out_rms = float(np.sqrt(np.mean(out[9600:] ** 2)))
        assert out_rms < in_rms * 0.25


def test_clarity_addon_dialog_instantiation(qapp):
    from mandible.ui.dialogs.clarity import ClarityAddonDialog

    dlg = ClarityAddonDialog()
    try:
        assert dlg.windowTitle() == "Mandible Clarity Add-on"
        assert dlg.download_btn is not None
        assert dlg.close_btn is not None
        assert dlg.folder_btn is not None
    finally:
        dlg.deleteLater()
