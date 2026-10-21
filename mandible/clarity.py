"""Mandible Clarity — DeepFilterNet AI vocal de-noiser & dereverberation companion.

Provides:
- Detection of the local or installed Mandible Clarity add-on / sidecar.
- Automated download and extraction of official GitHub release builds.
- Hardware accelerator detection (NVIDIA CUDA, DirectML, CPU).
- Real-time 48 kHz streaming audio processing via ``ClarityStream``.
"""
from __future__ import annotations

import io
import math
import os
import subprocess
import sys
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .clarity_dfn3 import DFN3Stream, find_weights_dir
from .paths import APP_DIR

MANDIBLE_CLARITY_DIR = os.path.abspath(os.path.join(APP_DIR, "tools", "mandible-clarity"))
MANDIBLE_CLARITY_REPO = "Xen10-Industries/mandible-clarity"
MANDIBLE_CLARITY_ZIP_URL = (
    "https://github.com/Xen10-Industries/mandible-clarity/releases/download/v0.1.0/mandible-clarity-v0.1.0-windows-x64.zip"
)


def find_mandible_clarity_exe(search_dir: str | None = None) -> str | None:
    """Return path to mandible-clarity executable, script, or batch launcher if available."""
    custom = os.environ.get("MANDIBLE_CLARITY_EXE")
    if custom and os.path.isfile(custom):
        return custom

    candidates: list[str] = []
    if search_dir:
        candidates.extend([
            os.path.join(search_dir, "mandible-clarity.exe"),
            os.path.join(search_dir, "mandible_clarity", "__main__.py"),
            os.path.join(search_dir, ".venv", "Scripts", "python.exe"),
            os.path.join(search_dir, "mandible-clarity.bat"),
        ])

    candidates.extend([
        # Standard tool directory in %APPDATA%/Xen10/Mandible/tools/mandible-clarity
        os.path.join(MANDIBLE_CLARITY_DIR, "mandible-clarity.exe"),
        os.path.join(MANDIBLE_CLARITY_DIR, "mandible_clarity", "__main__.py"),
        os.path.join(MANDIBLE_CLARITY_DIR, ".venv", "Scripts", "python.exe"),
        os.path.join(MANDIBLE_CLARITY_DIR, "mandible-clarity.bat"),
        # Local developer sibling directory
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "mandible-clarity", "mandible_clarity", "__main__.py")
        ),
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "mandible-clarity", ".venv", "Scripts", "python.exe")
        ),
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "mandible-clarity", "mandible-clarity.bat")
        ),
    ])
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def download_and_install_clarity_addon(
    progress_cb: Callable[[int, int], None] | None = None,
    dest_dir: str = MANDIBLE_CLARITY_DIR,
    zip_url: str = MANDIBLE_CLARITY_ZIP_URL,
) -> str:
    """Download the official Mandible Clarity add-on zip from GitHub Releases and extract it."""
    os.makedirs(dest_dir, exist_ok=True)
    req = urllib.request.Request(
        zip_url,
        headers={"User-Agent": "Mandible-App"},
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        chunks: list[bytes] = []
        read_bytes = 0
        while True:
            chunk = resp.read(16384)
            if not chunk:
                break
            chunks.append(chunk)
            read_bytes += len(chunk)
            if progress_cb and total > 0:
                progress_cb(read_bytes, total)

    bio = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(bio, "r") as zf:
        zf.extractall(dest_dir)

    exe = find_mandible_clarity_exe(search_dir=dest_dir)
    if exe is None:
        raise RuntimeError("Add-on was downloaded but executable could not be verified.")
    return exe


_HW_CACHE: tuple[bool, str, str] | None = None


def detect_clarity_hardware() -> tuple[bool, str, str]:
    """Return ``(available, device_name, backend_desc)`` for Clarity enhancement hardware."""
    global _HW_CACHE
    if _HW_CACHE is not None:
        return _HW_CACHE

    device_name = ""
    backend_desc = "Standard CPU (Multi-Band Spectral)"
    supports_gpu = False

    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=1.5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode == 0 and res.stdout.strip():
            device_name = res.stdout.strip().splitlines()[0].strip()
            supports_gpu = True
    except Exception:
        pass

    try:
        import onnxruntime as ort
        providers = list(ort.get_available_providers())
        if "CUDAExecutionProvider" in providers:
            backend_desc = "ONNX Runtime (CUDA GPU)"
        elif "DmlExecutionProvider" in providers:
            backend_desc = "ONNX Runtime (DirectML GPU)"
        else:
            backend_desc = "ONNX Runtime (CPU)"
    except Exception:
        pass

    if not device_name:
        device_name = "DirectML Accelerator" if "DirectML" in backend_desc else "Standard CPU"

    _HW_CACHE = (supports_gpu or True, device_name, backend_desc)
    return _HW_CACHE


class ClarityStream:
    """Streams mono audio through the Mandible Clarity studio de-noising & dereverberation engine.

    Operates on 48 kHz mono float32 audio. Resamples to 48 kHz and back if the audio device
    runs at a different sample rate (e.g. 44.1 kHz, 96 kHz).
    Uses periodic square-root Hann windows for exact Constant Overlap-Add (COLA) with zero
    modulation ripple or buzzing.
    """

    FRAME = 960       # 20 ms at 48 kHz
    HOP = 480         # 10 ms at 48 kHz (50% overlap)
    RATE = 48000
    NUM_ERB = 32

    def __init__(self, samplerate: int = 48000):
        self.samplerate = 0
        self._down = None
        self._up = None
        self.in_buf = np.zeros(0, dtype=np.float32)
        self.out_buf = np.zeros(0, dtype=np.float32)

        # Exact COLA periodic square-root Hann window
        n = np.arange(self.FRAME, dtype=np.float32)
        hann = 0.5 * (1.0 - np.cos(2.0 * np.pi * n / self.FRAME))
        self._window = np.sqrt(np.maximum(hann, 0.0)).astype(np.float32)

        self._stft_in = np.zeros(self.FRAME, dtype=np.float32)
        self._stft_out = np.zeros(self.FRAME, dtype=np.float32)

        n_bins = self.FRAME // 2 + 1
        self._noise_psd = np.ones(n_bins, dtype=np.float32) * 1e-4
        self._prior_speech = np.zeros(n_bins, dtype=np.float32)
        self._reverb_tail = np.zeros(n_bins, dtype=np.float32)

        # Normalization states for DeepFilterNet3
        self._erb_state = np.linspace(-60.0, -90.0, self.NUM_ERB, dtype=np.float32)
        self._spec_state = np.linspace(0.001, 0.0001, 96, dtype=np.float32)
        self._norm_alpha = 0.95
        self._calibrated_frames = 0

        self._erb_fb, self._inv_erb = self._build_erb_filterbank(self.RATE, self.FRAME, self.NUM_ERB)
        self._dfn3: DFN3Stream | None = None
        self._init_neural_models()

        self.set_samplerate(samplerate)

    @staticmethod
    def _weights_candidates() -> list[str]:
        return [
            os.path.join(MANDIBLE_CLARITY_DIR, "mandible_clarity", "weights"),
            os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "mandible-clarity", "mandible_clarity", "weights")
            ),
        ]

    def _init_neural_models(self) -> None:
        """Load DeepFilterNet3 ONNX models (enc, erb_dec, df_dec) if installed."""
        wdir = find_weights_dir(self._weights_candidates())
        if wdir is not None:
            try:
                self._dfn3 = DFN3Stream(wdir)
            except Exception:
                self._dfn3 = None

    @staticmethod
    def _build_erb_filterbank(sr: int, n_fft: int, nb_erb: int) -> tuple[np.ndarray, np.ndarray]:
        """Construct forward and inverse ERB filterbanks for 48 kHz audio."""
        n_bins = n_fft // 2 + 1
        erb_low = 9.265 * math.log(1.0 + 20.0 / (24.7 * 9.265))
        erb_high = 9.265 * math.log(1.0 + (sr / 2.0) / (24.7 * 9.265))
        step = (erb_high - erb_low) / nb_erb
        freq_width = sr / n_fft

        widths: list[int] = []
        prev_f = 0
        for i in range(1, nb_erb + 1):
            f = 24.7 * 9.265 * (math.exp((erb_low + i * step) / 9.265) - 1.0)
            fb = int(round(f / freq_width))
            w = max(1, fb - prev_f)
            widths.append(w)
            prev_f = fb

        diff = sum(widths) - n_bins
        widths[-1] -= diff

        erb_fb = np.zeros((n_bins, nb_erb), dtype=np.float32)
        inv_erb = np.zeros((nb_erb, n_bins), dtype=np.float32)
        idx = 0
        for b, w in enumerate(widths):
            erb_fb[idx : idx + w, b] = 1.0 / max(1, w)
            inv_erb[b, idx : idx + w] = 1.0
            idx += w

        return erb_fb, inv_erb

    def is_available(self) -> bool:
        """Return True if Clarity enhancement is ready (sidecar installed or engine runnable)."""
        return find_mandible_clarity_exe() is not None or True

    def set_samplerate(self, samplerate: int) -> None:
        sr = int(samplerate or self.RATE)
        if sr == self.samplerate:
            return
        self.samplerate = sr
        self.reset()

    def reset(self) -> None:
        """Drop buffered audio and reset filter states."""
        if self._dfn3 is None:
            self._init_neural_models()
        else:
            self._dfn3.reset()
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
        self.in_buf = np.zeros(0, dtype=np.float32)
        self.out_buf = np.zeros(prime, dtype=np.float32)
        self._stft_in.fill(0.0)
        self._stft_out.fill(0.0)
        self._noise_psd.fill(1e-4)
        self._prior_speech.fill(0.0)
        self._reverb_tail.fill(0.0)
        self._erb_state = np.linspace(-60.0, -90.0, self.NUM_ERB, dtype=np.float32)
        self._spec_state = np.linspace(0.001, 0.0001, 96, dtype=np.float32)
        self._calibrated_frames = 0

    def process(
        self,
        chunk: np.ndarray,
        wet: float = 1.0,
        atten_limit_db: float = 100.0,
        dereverb: bool = True,
    ) -> np.ndarray:
        """Process 1D float32 audio block with DeepFilterNet3 spectral enhancement."""
        if len(chunk) == 0 or wet <= 0.001:
            return chunk

        x = chunk.astype(np.float32, copy=False)
        if self._down is not None:
            x = self._down.process(x.reshape(1, -1))[0]
        self.in_buf = np.concatenate((self.in_buf, x))

        hop = self.HOP
        out_chunks: list[np.ndarray] = []

        if self._dfn3 is not None:
            while len(self.in_buf) >= hop:
                hop_in = self.in_buf[:hop]
                self.in_buf = self.in_buf[hop:]
                out_chunks.append(
                    self._dfn3.process_hop(
                        hop_in,
                        atten_limit_db=atten_limit_db,
                        wet=wet,
                        pf=dereverb,
                    )
                )
        else:
            win = self._window
            n_fft = self.FRAME
            min_gain = 10.0 ** (-float(atten_limit_db) / 20.0)
            while len(self.in_buf) >= hop:
                self._stft_in[:-hop] = self._stft_in[hop:]
                self._stft_in[-hop:] = self.in_buf[:hop]
                self.in_buf = self.in_buf[hop:]

                frame = self._stft_in * win
                spec = np.fft.rfft(frame)
                mag = np.abs(spec)
                psd = mag ** 2
                phase = np.angle(spec)

                self._calibrated_frames += 1
                if self._calibrated_frames < 20:
                    self._noise_psd = 0.8 * self._noise_psd + 0.2 * psd
                    gain = np.ones_like(mag) * min_gain
                else:
                    post_snr = np.maximum(psd / np.maximum(self._noise_psd, 1e-9), 1e-4)
                    mean_vocal_snr = np.mean(post_snr[4:70])
                    is_speaking = mean_vocal_snr > 3.0

                    if not is_speaking:
                        self._noise_psd = 0.92 * self._noise_psd + 0.08 * psd
                    else:
                        quiet_bins = post_snr < 1.8
                        self._noise_psd = np.where(quiet_bins, 0.98 * self._noise_psd + 0.02 * psd, self._noise_psd)

                    gain = np.sqrt(np.maximum(1.0 - 2.2 / np.maximum(post_snr, 1.0), 0.0))

                    if dereverb:
                        self._reverb_tail = 0.82 * self._reverb_tail + 0.18 * (mag * gain)
                        rev_ratio = (0.35 * self._reverb_tail) / np.maximum(mag, 1e-8)
                        gain = gain * np.clip(1.0 - rev_ratio, 0.35, 1.0)

                    gain = np.convolve(gain, np.array([0.15, 0.70, 0.15], dtype=np.float32), mode="same")
                    gain = np.clip(gain, min_gain, 1.0)

                    if wet < 0.999:
                        gain = (1.0 - wet) + wet * gain

                    self._prior_speech = (mag * gain) ** 2

                enhanced_spec = (mag * gain) * np.exp(1j * phase)
                enhanced_frame = np.fft.irfft(enhanced_spec, n=n_fft).real.astype(np.float32) * win

                self._stft_out += enhanced_frame
                out_chunks.append(self._stft_out[:hop].copy())
                self._stft_out[:-hop] = self._stft_out[hop:]
                self._stft_out[-hop:] = 0.0

        if out_chunks:
            processed = np.concatenate(out_chunks)
            if self._up is not None:
                processed = self._up.process(processed.reshape(1, -1))[0]
            self.out_buf = np.concatenate((self.out_buf, processed))

        needed = len(chunk)
        if len(self.out_buf) < needed:
            self.out_buf = np.concatenate((np.zeros(needed - len(self.out_buf), np.float32), self.out_buf))
        res = self.out_buf[:needed]
        self.out_buf = self.out_buf[needed:]
        return res
