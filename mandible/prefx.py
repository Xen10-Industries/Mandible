"""Microphone pre-processing stage (runs before effect chains):
- High-pass / Rumble Filter (80 Hz cut)
- AI Noise Suppression (RNNoise neural network via bundled rnnoise.dll)
- Noise Gate (Pedalboard expander with threshold, attack, release)
"""
from __future__ import annotations

import ctypes
import os
import threading
from dataclasses import dataclass

import numpy as np
import pedalboard

from .gate import Gate


@dataclass
class PreFXSettings:
    highpass_enabled: bool = True
    highpass_cutoff_hz: float = 80.0
    noise_gate_enabled: bool = False
    noise_gate_threshold_db: float = -42.0
    # Fade-in when the gate opens. (The old noise_gate_attack_ms key was never editable and
    # tuned a detector, not the fade; saved values of it are ignored.)
    noise_gate_open_ms: float = 5.0
    noise_gate_release_ms: float = 100.0
    rnnoise_enabled: bool = False
    rnnoise_wet: float = 1.0  # 0.0 (bypass) to 1.0 (full suppression)


def _resolve_rnnoise_path() -> str:
    import sys
    candidates = [
        os.path.join(os.path.dirname(__file__), "lib", "rnnoise.dll"),
    ]
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.insert(0, os.path.join(meipass, "mandible", "lib", "rnnoise.dll"))
            candidates.insert(1, os.path.join(meipass, "lib", "rnnoise.dll"))
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "mandible", "lib", "rnnoise.dll"))
        candidates.append(os.path.join(exe_dir, "_internal", "mandible", "lib", "rnnoise.dll"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[0]


_LIB_PATH = _resolve_rnnoise_path()
_rnnoise_lib = None
_rnnoise_lock = threading.Lock()


def _get_rnnoise_lib():
    global _rnnoise_lib
    with _rnnoise_lock:
        if _rnnoise_lib is None:
            dll_path = _resolve_rnnoise_path()
            if os.path.isfile(dll_path):
                try:
                    lib = ctypes.CDLL(dll_path)

                    lib.rnnoise_create.argtypes = [ctypes.c_void_p]
                    lib.rnnoise_create.restype = ctypes.c_void_p
                    lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
                    lib.rnnoise_process_frame.argtypes = [
                        ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_float),
                        ctypes.POINTER(ctypes.c_float),
                    ]
                    lib.rnnoise_process_frame.restype = ctypes.c_float
                    _rnnoise_lib = lib
                except Exception as exc:
                    print(f"[Mandible] could not load rnnoise.dll: {exc}")
                    _rnnoise_lib = False
            else:
                _rnnoise_lib = False
        return _rnnoise_lib if _rnnoise_lib is not False else None


class RNNoiseStream:
    """Streams mono audio through RNNoise.

    RNNoise only works on 48 kHz audio in 480-sample frames. Other device rates are resampled to
    48 kHz and back with pedalboard's streaming resampler. The output FIFO is primed with silence
    so a whole RNNoise frame (plus resampler delay) is always buffered: the latency is constant
    (~10 ms at 48 kHz) and the stream never has to pad gaps into the audio.
    """

    FRAME = 480
    RATE = 48000

    def __init__(self, samplerate: int = 48000):
        self.lib = _get_rnnoise_lib()
        self.state = self.lib.rnnoise_create(None) if self.lib else None
        self.last_speech_prob = 1.0
        self.samplerate = 0
        self.set_samplerate(samplerate)

    def set_samplerate(self, samplerate: int) -> None:
        samplerate = int(samplerate or self.RATE)
        if samplerate == self.samplerate:
            return
        self.samplerate = samplerate
        self.reset()

    def reset(self) -> None:
        """Drop buffered audio (call when the stream (re)starts or suppression is switched on)."""
        sr = self.samplerate
        if sr != self.RATE:
            from pedalboard.io import StreamResampler
            self._down = StreamResampler(sr, self.RATE, 1)
            self._up = StreamResampler(self.RATE, sr, 1)
            resampler_delay = self._down.input_latency + self._up.input_latency * sr / self.RATE
        else:
            self._down = self._up = None
            resampler_delay = 0
        prime = int(np.ceil(self.FRAME * sr / self.RATE + resampler_delay))
        self.in_buf = np.zeros(0, dtype=np.float32)      # 48 kHz samples waiting for a full frame
        self.out_buf = np.zeros(prime, dtype=np.float32)  # device-rate samples ready to return

    def close(self):
        if self.state and self.lib:
            try:
                self.lib.rnnoise_destroy(self.state)
            except Exception:
                pass
            self.state = None

    def process(self, chunk: np.ndarray, wet: float = 1.0) -> np.ndarray:
        if not self.state or not self.lib or wet <= 0.001:
            return chunk

        x = chunk.astype(np.float32, copy=False)
        if self._down is not None:
            x = self._down.process(x.reshape(1, -1))[0]
        self.in_buf = np.concatenate((self.in_buf, x))

        out_chunks = []
        n_frames = len(self.in_buf) // self.FRAME
        for k in range(n_frames):
            frame = self.in_buf[k * self.FRAME:(k + 1) * self.FRAME]
            # RNNoise expects 16-bit-scaled float samples
            scaled = (frame * 32767.0).astype(np.float32)
            c_ptr = scaled.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            self.last_speech_prob = float(self.lib.rnnoise_process_frame(self.state, c_ptr, c_ptr))
            clean = scaled * np.float32(1.0 / 32767.0)
            if wet < 0.999:
                clean = (1.0 - wet) * frame + wet * clean
            out_chunks.append(clean)
        if n_frames:
            self.in_buf = self.in_buf[n_frames * self.FRAME:]
            processed = np.concatenate(out_chunks)
            if self._up is not None:
                processed = self._up.process(processed.reshape(1, -1))[0]
            self.out_buf = np.concatenate((self.out_buf, processed))

        needed = len(chunk)
        if len(self.out_buf) < needed:
            # Should not happen after priming; pad at the front rather than glitch the stream.
            self.out_buf = np.concatenate((np.zeros(needed - len(self.out_buf), np.float32), self.out_buf))
        res = self.out_buf[:needed]
        self.out_buf = self.out_buf[needed:]
        return res


class PreFXProcessor:
    """Pre-processing engine executed on mono mic input before any effect chains."""

    GATE_HOLD_MS = 50.0  # keeps the gate open across short gaps between syllables

    def __init__(self, cfg: PreFXSettings, samplerate: int = 48000):
        self.cfg = cfg
        self.samplerate = samplerate
        self.rnnoise = RNNoiseStream(samplerate)
        self._rnnoise_was_on = False
        self._hp_filter = None
        self._gate = None
        self._rebuild_filters()

    def update_settings(self, cfg: PreFXSettings, samplerate: int | None = None):
        self.cfg = cfg
        if samplerate:
            self.samplerate = samplerate
            self.rnnoise.set_samplerate(samplerate)
        self._rebuild_filters()

    def _rebuild_filters(self):
        # Highpass filter
        if self.cfg.highpass_enabled and self.cfg.highpass_cutoff_hz > 10:
            self._hp_filter = pedalboard.HighpassFilter(cutoff_frequency_hz=float(self.cfg.highpass_cutoff_hz))
        else:
            self._hp_filter = None

        # Noise Gate
        if self.cfg.noise_gate_enabled:
            self._gate = Gate(
                threshold_db=float(self.cfg.noise_gate_threshold_db),
                attack_ms=float(self.cfg.noise_gate_open_ms),
                hold_ms=self.GATE_HOLD_MS,
                release_ms=float(self.cfg.noise_gate_release_ms),
            )
        else:
            self._gate = None

    def process(self, mono: np.ndarray) -> np.ndarray:
        """Processes 1D float32 mono audio array in-place or returns processed array."""
        if len(mono) == 0:
            return mono

        out = mono

        # 1. High-pass filter (rumble removal)
        if self._hp_filter is not None:
            buf = out.reshape(1, -1)
            try:
                buf = self._hp_filter.process(buf, self.samplerate, buffer_size=len(mono), reset=False)
                out = buf[0]
            except Exception:
                pass

        # 2. AI RNNoise suppression (flush stale buffered audio when it is switched back on)
        if self.cfg.rnnoise_enabled:
            if not self._rnnoise_was_on:
                self.rnnoise.reset()
            out = self.rnnoise.process(out, wet=self.cfg.rnnoise_wet)
        self._rnnoise_was_on = self.cfg.rnnoise_enabled

        # 3. Noise gate
        if self._gate is not None:
            out = self._gate.process(out, self.samplerate)

        return out

    def close(self):
        self.rnnoise.close()
