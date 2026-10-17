"""Regression tests pinning the behaviour fixed in the audit pass (commit b5871c0)."""
from __future__ import annotations

import http.client
import json
import socket

import numpy as np
import pytest


# ------------------------------------------------------------------ helpers

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_engine(engine, x: np.ndarray, bs: int = 128) -> np.ndarray:
    """Push mono ``x`` through the engine callback block by block; return the left output."""
    out = []
    for i in range(0, len(x) - bs + 1, bs):
        indata = x[i:i + bs].reshape(-1, 1).astype(np.float32)
        outdata = np.zeros((bs, 2), np.float32)
        engine._callback(indata, outdata, bs, None, None)
        out.append(outdata[:, 0].copy())
    return np.concatenate(out)


def _sine(freq: float, seconds: float, sr: int = 48000, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(sr * seconds), dtype=np.float32)
    return (amp * np.sin(2 * np.pi * freq * t / sr)).astype(np.float32)


# ------------------------------------------------------------------ GUI

def test_soundboard_dialog_opens_with_clips(sample_core):
    from mandible import gui

    dlg = gui.SoundboardDialog(sample_core, None)  # used to raise NameError
    assert dlg.table.rowCount() == 3
    dlg.deleteLater()


def test_meter_timer_pauses_when_hidden(sample_core):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from mandible import gui

    win = gui.MainWindow(sample_core)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    try:
        win.show()
        QApplication.processEvents()
        assert win.meter_timer.isActive()
        assert win.status_timer.interval() == 500

        win.showMinimized()
        QApplication.processEvents()
        assert not win.meter_timer.isActive()
        assert win.status_timer.interval() == 2000

        win.showNormal()
        QApplication.processEvents()
        assert win.meter_timer.isActive()

        win.hide()
        QApplication.processEvents()
        assert not win.meter_timer.isActive()
        assert win.status_timer.interval() == 2000
    finally:
        win.meter_timer.stop()
        win.status_timer.stop()
        win.tray.hide()
        win.deleteLater()


# ------------------------------------------------------------------ local web API

JSON = {"Content-Type": "application/json"}


@pytest.fixture
def api(core):
    from mandible.config import Chain

    core.cfg.idle_mode = "dry"
    robot = Chain(name="Robot")
    core.cfg.chains.append(robot)
    core.rebuild(robot)
    for _ in range(5):
        port = _free_port()
        if core.api.start(port):
            break
    else:
        pytest.skip("could not bind a free localhost port for the API")

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    request.port = port
    request.chain = robot
    return request


def test_api_rejects_browser_requests(api):
    status, headers, _ = api("GET", "/api/status")
    assert status == 200
    assert "access-control-allow-origin" not in headers

    assert api("POST", "/api/mute", "{}", {"Content-Type": "text/plain"})[0] == 415
    assert api("POST", "/api/mute", "{}", {**JSON, "Origin": "https://evil.example"})[0] == 403
    assert api("POST", "/api/mute", "{}", {**JSON, "Host": f"evil.example:{api.port}"})[0] == 403
    assert api("OPTIONS", "/api/mute")[0] == 405


def test_api_select_clean(api, core):
    from mandible.audio_engine import DRY_ID

    status, _, _ = api("POST", "/api/chains/select", json.dumps({"name": "Robot"}), JSON)
    assert status == 200
    assert core.target() == api.chain.id

    status, _, _ = api("POST", "/api/chains/select", json.dumps({"name": "clean"}), JSON)
    assert status == 200
    assert core.target() == DRY_ID
    _, _, body = api("GET", "/api/status")
    assert json.loads(body)["active_chain_name"] == "Clean"


# ------------------------------------------------------------------ DSP

def test_formant_level_independent_of_block_size():
    from mandible.internal_dsp import PitchFormantPlugin

    x = _sine(220, 2.0)
    stereo = np.vstack([x, x])
    levels = []
    for bs in (128, 256, 512, 1024):
        p = PitchFormantPlugin()
        p.p_pitch.value = 0.0
        p.p_formant.value = 4.0
        y = np.concatenate([p.process(stereo[:, i:i + bs], 48000, bs)[0]
                            for i in range(0, stereo.shape[1] - bs, bs)])
        seg = y[24000:]
        rms_in = float(np.sqrt(np.mean(x[24000:24000 + len(seg)] ** 2)))
        levels.append(20 * np.log10(float(np.sqrt(np.mean(seg ** 2))) / rms_in))
    assert max(levels) - min(levels) < 0.2, levels


@pytest.mark.parametrize("mix", [100.0, 50.0])
def test_formant_identity_latency_exact(mix):
    from mandible.internal_dsp import PitchFormantPlugin

    p = PitchFormantPlugin()
    p.p_pitch.value = 0.0
    p.p_formant.value = 0.0
    p.p_mix.value = mix
    latency = p.reported_latency_samples
    assert latency == 1024

    rng = np.random.default_rng(3)
    x = (rng.standard_normal(24000) * 0.1).astype(np.float32)
    stereo = np.vstack([x, x])
    bs = 128
    y = np.concatenate([p.process(stereo[:, i:i + bs], 48000, bs)[0]
                        for i in range(0, stereo.shape[1] - bs + 1, bs)])
    err = float(np.max(np.abs(y[latency:] - x[:len(y) - latency])))
    assert err < 1e-6, err


class _IdentityLib:
    """RNNoise stand-in that leaves audio untouched, isolating the Python FIFO/resampling."""

    def rnnoise_process_frame(self, state, out, inp):
        return 1.0


@pytest.mark.parametrize("sr, latency", [(44100, 563), (48000, 480), (96000, 1152)])
@pytest.mark.parametrize("bs", [64, 128, 441, 512])
def test_rnnoise_fifo_no_gaps(sr, bs, latency):
    from mandible import prefx

    s = prefx.RNNoiseStream.__new__(prefx.RNNoiseStream)
    s.lib, s.state, s.last_speech_prob, s.samplerate = _IdentityLib(), 1, 1.0, 0
    s.set_samplerate(sr)

    # Two incommensurate tones, so exactly one delay lines the output up with the input.
    t = np.arange(sr * 2, dtype=np.float64) / sr
    x = (0.25 * (np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 613.7 * t))).astype(np.float32)
    y = np.concatenate([s.process(x[i:i + bs]) for i in range(0, len(x) - bs + 1, bs)])

    # Latency: the delay that best matches the output against the delayed input.
    a = sr // 2
    best = min(range(0, 3000),
               key=lambda d: float(np.mean(np.abs(y[a:a + 2048] - x[a - d:a - d + 2048]))))
    assert best == latency

    seg = y[a:]
    ref = x[a - best:a - best + len(seg)]
    # The resampler delay is fractional at 44.1 kHz, so allow a small sub-sample alignment error.
    assert float(np.max(np.abs(seg[:len(ref)] - ref))) < 0.03

    body = y[best + 10:-10]
    zero_runs = int(np.sum((np.abs(body[1:]) < 1e-6) & (np.abs(body[:-1]) < 1e-6)))
    assert zero_runs == 0


# ------------------------------------------------------------------ audio engine

def test_chain_dry_wet_phase_aligned(core):
    core.cfg.limiter.enabled = False
    core.cfg.prefx.highpass_enabled = False
    core.engine.update_limiter(core.cfg.limiter)
    core.engine.update_prefx(core.cfg.prefx)
    core.engine.samplerate, core.engine.blocksize = 48000, 128

    chain = core.add_chain("PF")
    chain.mode, chain.dry_wet = "hold", 0.5
    core.add_plugin(chain, "internal:pitch_formant")  # identity, 1024-sample latency
    core.update_chain_params(chain)
    rt = core.engine.runtime(chain.id)
    assert rt.latency_samples == 1024

    rng = np.random.default_rng(3)
    x = (rng.standard_normal(48000) * 0.1).astype(np.float32)
    core.press(chain.id)
    y = _run_engine(core.engine, x)

    lat, a = rt.latency_samples, 24000
    err = float(np.max(np.abs(y[a:a + 8000] - x[a - lat:a - lat + 8000])))
    assert err < 1e-6, err


def test_keep_awake_round_robin(core):
    from mandible.audio_engine import ChainRuntime

    class FakeBoard:
        def __init__(self):
            self.calls = 0

        def process(self, audio, sr, buffer_size, reset):
            self.calls += 1
            return audio

    boards = [FakeBoard() for _ in range(3)]
    for i, board in enumerate(boards):
        core.engine.set_runtime(ChainRuntime(f"idle{i}", board, 1.0, 0.0, 1.0, 0))
    core.engine.keep_awake = True
    _run_engine(core.engine, np.zeros(128 * 30, np.float32))
    assert [b.calls for b in boards] == [10, 10, 10]


# ------------------------------------------------------------------ MIDI

def test_midi_cc_midpoint_edges(core):
    from mandible.audio_engine import DRY_ID
    from mandible.config import Chain, MidiBinding

    chain = Chain(name="Hold", mode="hold")
    core.cfg.chains.append(chain)
    core.rebuild(chain)
    core.cfg.midi_bindings = [
        MidiBinding(event_type="cc", note_or_cc=7, action=f"chain:{chain.id}"),
        MidiBinding(event_type="note_on", note_or_cc=60, action=f"chain:{chain.id}"),
    ]
    events: list[str] = []
    press, release = core.press, core.release
    core.press = lambda cid: (events.append("press"), press(cid))
    core.release = lambda cid: (events.append("release"), release(cid))

    for value in (10, 40, 70, 90, 127, 100, 50, 20, 80):  # sweep crosses 64 three times
        core._handle_midi_msg(0xB0, 7, value)
    assert events == ["press", "release", "press"]

    core.release(chain.id)
    events.clear()
    core._handle_midi_msg(0x90, 60, 100)
    assert events == ["press"]
    assert core.target() == chain.id
    core._handle_midi_msg(0x80, 60, 0)
    assert events == ["press", "release"]
    assert core.target() == DRY_ID
