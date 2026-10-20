"""Output safety limiter: transparent below the ceiling, never above it.

Below ``threshold_db`` the signal passes untouched (gain exactly 1). A sample that would exceed
the ceiling gets exactly enough gain reduction to sit on it (instant attack, no look-ahead, so
no added latency), and the reduction then relaxes exponentially over ``release_ms``. Stereo
channels share one gain so the image doesn't shift.

Unlike ``pedalboard.Limiter`` (JUCE's two-stage limiter, which adds about +4 dB of make-up gain
to quiet signals and compresses loud ones), this changes nothing that is already safe; that
louder character stays available as the "Loudness boost" option.
"""
from __future__ import annotations

import numpy as np

_MAX_CHUNK = 2048  # keeps k ** -n well inside float64 range for short release times


class SafetyLimiter:
    def __init__(self, threshold_db: float = -0.5, release_ms: float = 50.0):
        self.threshold = float(10.0 ** (float(threshold_db) / 20.0))
        self.release_s = max(0.001, float(release_ms) / 1000.0)
        self.reset()

    def reset(self) -> None:
        self.attenuation = 0.0  # 1 - gain at the end of the last sample processed

    def process(self, x: np.ndarray, sample_rate: float, buffer_size: int = 0,
                reset: bool = False) -> np.ndarray:
        """Limit ``x`` (channels x frames). Same call shape as a pedalboard plugin."""
        if reset:
            self.reset()
        x = np.asarray(x, dtype=np.float32)
        frames = x.shape[-1]
        if frames == 0:
            return x
        k = float(np.exp(-1.0 / (self.release_s * float(sample_rate))))
        out = np.empty_like(x)
        for start in range(0, frames, _MAX_CHUNK):
            seg = x[..., start:start + _MAX_CHUNK]
            out[..., start:start + _MAX_CHUNK] = self._process_chunk(seg, k)
        return out

    def _process_chunk(self, x: np.ndarray, k: float) -> np.ndarray:
        n = x.shape[-1]
        peak = np.abs(x).max(axis=0) if x.ndim == 2 else np.abs(x)
        needed = np.where(peak > self.threshold,
                          1.0 - self.threshold / np.maximum(peak, 1e-12), 0.0)
        # attenuation[i] = max(needed[i], attenuation[i-1] * k): a peak-hold that decays by k per
        # sample. Unrolled: max(prev * k^(i+1), max_{j<=i} needed[j] * k^(i-j)), computed with a
        # running maximum of needed[j] * k^-j instead of a per-sample Python loop.
        idx = np.arange(n, dtype=np.float64)
        k_pow = k ** idx
        held = np.maximum.accumulate(needed / k_pow) * k_pow
        attenuation = np.maximum(held, self.attenuation * k_pow * k)
        self.attenuation = float(attenuation[-1])
        if not attenuation.any():
            return x.copy()
        y = (x * (1.0 - attenuation)).astype(np.float32)
        np.clip(y, -self.threshold, self.threshold, out=y)  # float rounding only
        return y
