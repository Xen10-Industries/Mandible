"""Noise gate that fades: attack, hold and release ramp the gain, so it never clicks.

``pedalboard.NoiseGate`` (JUCE's) smooths only its level detector; speech is far above a
typical threshold, so the detector crosses it at once and the gain jumps from closed to open in
under a millisecond whatever its attack, which clicks. This gate decides open/closed every
``CHUNK`` samples from the key signal's peak and moves the gain linearly toward that state:
up over ``attack_ms``, held open for ``hold_ms`` after the last peak, down over ``release_ms``,
along an S-curve. The gain is interpolated per sample, has no look-ahead (no added latency) and does not depend
on the host buffer size beyond the chunk grid.
"""
from __future__ import annotations

import numpy as np


class Gate:
    CHUNK = 32  # samples per open/closed decision (0.67 ms at 48 kHz)

    def __init__(self, threshold_db: float, attack_ms: float = 5.0, hold_ms: float = 50.0,
                 release_ms: float = 100.0, start_open: bool = False):
        self.threshold_db = float(threshold_db)
        self.attack_ms = float(attack_ms)
        self.hold_ms = float(hold_ms)
        self.release_ms = float(release_ms)
        self.reset(start_open)

    def reset(self, start_open: bool = False) -> None:
        self.gain = 1.0 if start_open else 0.0
        self.hold_left = 0

    def gains(self, key: np.ndarray, sample_rate: float) -> np.ndarray:
        """Per-sample gain (float32, one per frame) for ``key`` (frames, or channels x frames)."""
        key = np.abs(np.asarray(key, dtype=np.float32))
        level = key.max(axis=0) if key.ndim == 2 else key
        frames = level.shape[0]
        if frames == 0:
            return np.zeros(0, dtype=np.float32)
        c = self.CHUNK
        n = -(-frames // c)
        padded = np.zeros(n * c, dtype=np.float32)
        padded[:frames] = level
        peaks = padded.reshape(n, c).max(axis=1)
        thr = 10.0 ** (self.threshold_db / 20.0)
        up = c / max(1e-4, self.attack_ms / 1000.0 * sample_rate)
        down = c / max(1e-4, self.release_ms / 1000.0 * sample_rate)
        hold = int(self.hold_ms / 1000.0 * sample_rate / c)
        g, held, ends = self.gain, self.hold_left, np.empty(n, dtype=np.float32)
        for k in range(n):
            if peaks[k] >= thr:
                held = hold
                g = min(1.0, g + up)
            elif held > 0:
                held -= 1
                g = min(1.0, g + up)
            else:
                g = max(0.0, g - down)
            ends[k] = g
        knots = np.minimum(np.arange(1, n + 1) * c, frames) - 1
        ramp = np.interp(np.arange(frames), np.concatenate(([-1], knots)),
                         np.concatenate(([self.gain], ends)))
        self.gain, self.hold_left = g, held
        # S-curve (smoothstep): the fade starts and ends with zero slope, so neither end of a
        # ramp puts a corner (a click) into the signal. 0 and 1 map to exactly 0 and 1.
        return (ramp * ramp * (3.0 - 2.0 * ramp)).astype(np.float32)

    def process(self, x: np.ndarray, sample_rate: float) -> np.ndarray:
        """``x`` gated by its own level."""
        return (np.asarray(x, dtype=np.float32) * self.gains(x, sample_rate)).astype(np.float32)
