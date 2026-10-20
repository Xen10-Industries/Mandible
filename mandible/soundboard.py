"""Soundboard audio engine: plays audio clips (.wav, .mp3, .ogg, .flac)
with global hotkeys, routed to output (Discord/OBS) and monitor (headphones).
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import numpy as np
import pedalboard.io


@dataclass
class SoundboardClip:
    id: str
    name: str
    path: str
    volume_db: float = 0.0
    loop: bool = False
    route_output: bool = True
    route_monitor: bool = True
    trim_start_s: float = 0.0
    trim_end_s: float = 0.0


class _ActiveVoice:
    def __init__(self, clip_id: str, audio: np.ndarray, volume_lin: float, loop: bool, to_out: bool, to_mon: bool):
        self.clip_id = clip_id
        self.audio = audio  # (2, N) float32
        self.pos = 0
        self.volume_lin = volume_lin
        self.loop = loop
        self.to_out = to_out
        self.to_mon = to_mon


class SoundboardEngine:
    def __init__(self):
        self._cache: dict[str, tuple[np.ndarray, int]] = {}  # path -> (stereo_audio, samplerate)
        self._waveform_cache: dict[str, tuple[list[float], float]] = {}  # path -> (peaks, duration_s)
        self._voices: list[_ActiveVoice] = []
        self._lock = threading.Lock()
        self.samplerate = 48000

    def preload(self, path: str, target_sr: int = 48000) -> np.ndarray | None:
        if not path or not os.path.isfile(path):
            return None
        key = f"{path}@{target_sr}"
        if key in self._cache:
            return self._cache[key][0]
        try:
            with pedalboard.io.AudioFile(path) as f:
                sr = f.samplerate
                audio = f.read(f.frames)
            # Ensure stereo
            if audio.shape[0] == 1:
                audio = np.repeat(audio, 2, axis=0)
            elif audio.shape[0] > 2:
                audio = audio[:2]
            # Resample if needed
            if sr != target_sr:
                resampler = pedalboard.Resample(target_sample_rate=target_sr)
                audio = resampler.process(audio, sr)
            self._cache[key] = (audio.astype(np.float32), target_sr)
            return self._cache[key][0]
        except Exception as exc:
            print(f"[Mandible] error loading soundboard clip {path}: {exc}")
            return None

    _GLOBAL_WAVEFORM_CACHE: dict[str, tuple[list[float], float]] = {}

    @classmethod
    def extract_waveform(cls, path: str, num_points: int = 120) -> tuple[list[float], float]:
        """Return (normalized_peaks_list, duration_seconds) for a clip."""
        if not path or not os.path.isfile(path):
            return [0.0] * num_points, 0.0
        if path in cls._GLOBAL_WAVEFORM_CACHE:
            return cls._GLOBAL_WAVEFORM_CACHE[path]
        try:
            with pedalboard.io.AudioFile(path) as f:
                sr = f.samplerate
                frames = f.frames
                duration = frames / max(1.0, float(sr))
                raw = f.read(frames)
            # Downmix to mono abs
            mono = np.max(np.abs(raw), axis=0) if raw.ndim > 1 else np.abs(raw)
            if len(mono) == 0:
                peaks = [0.0] * num_points
            else:
                chunk_len = max(1, len(mono) // num_points)
                peaks = []
                for i in range(num_points):
                    st = i * chunk_len
                    en = min(len(mono), st + chunk_len)
                    pk = float(np.max(mono[st:en])) if st < len(mono) else 0.0
                    peaks.append(pk)
                max_pk = max(1e-4, max(peaks))
                peaks = [min(1.0, p / max_pk) for p in peaks]
            cls._GLOBAL_WAVEFORM_CACHE[path] = (peaks, duration)
            return peaks, duration
        except Exception:
            return [0.0] * num_points, 0.0

    def play(self, clip: SoundboardClip, target_sr: int = 48000):
        audio = self.preload(clip.path, target_sr)
        if audio is None or audio.shape[1] == 0:
            return
        # Apply trim bounds if configured
        total_samples = audio.shape[1]
        start_sample = 0
        end_sample = total_samples
        if getattr(clip, "trim_start_s", 0.0) > 0.0:
            start_sample = min(total_samples - 1, int(clip.trim_start_s * target_sr))
        if getattr(clip, "trim_end_s", 0.0) > 0.0 and clip.trim_end_s > getattr(clip, "trim_start_s", 0.0):
            end_sample = min(total_samples, int(clip.trim_end_s * target_sr))
        if start_sample < end_sample:
            audio = audio[:, start_sample:end_sample]

        vol = float(10.0 ** (clip.volume_db / 20.0))
        voice = _ActiveVoice(clip.id, audio, vol, clip.loop, clip.route_output, clip.route_monitor)
        with self._lock:
            # Stop existing instance if playing
            self._voices = [v for v in self._voices if v.clip_id != clip.id]
            self._voices.append(voice)

    def stop(self, clip_id: str):
        with self._lock:
            self._voices = [v for v in self._voices if v.clip_id != clip_id]

    def stop_all(self):
        with self._lock:
            self._voices.clear()

    def is_playing(self, clip_id: str) -> bool:
        with self._lock:
            return any(v.clip_id == clip_id for v in self._voices)

    def is_any_playing(self) -> bool:
        with self._lock:
            return bool(self._voices)

    def mix(self, frames: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns ``(out, mon, shared)`` stereo arrays shaped (2, frames): clips routed to the
        main output, clips routed to the monitor, and the clips routed to both (included in
        ``out`` and ``mon`` alike), so a monitor feed built from the output can avoid adding
        them twice."""
        out_mix = np.zeros((2, frames), dtype=np.float32)
        mon_mix = np.zeros((2, frames), dtype=np.float32)
        shared_mix = np.zeros((2, frames), dtype=np.float32)

        with self._lock:
            if not self._voices:
                return out_mix, mon_mix, shared_mix

            remaining_voices = []
            for v in self._voices:
                total_len = v.audio.shape[1]
                end_pos = v.pos + frames

                if end_pos <= total_len:
                    chunk = v.audio[:, v.pos : end_pos] * v.volume_lin
                    v.pos = end_pos
                    if v.loop and v.pos >= total_len:
                        v.pos = 0
                        remaining_voices.append(v)
                    elif v.pos < total_len:
                        remaining_voices.append(v)
                else:
                    # Partial chunk / loop wrap
                    chunk = np.zeros((2, frames), dtype=np.float32)
                    first_part = v.audio[:, v.pos :] * v.volume_lin
                    first_len = total_len - v.pos
                    chunk[:, :first_len] = first_part
                    if v.loop:
                        v.pos = 0
                        second_needed = frames - first_len
                        second_len = min(second_needed, total_len)
                        chunk[:, first_len : first_len + second_len] = (
                            v.audio[:, :second_len] * v.volume_lin
                        )
                        v.pos = second_len
                        remaining_voices.append(v)

                if v.to_out:
                    out_mix += chunk
                if v.to_mon:
                    mon_mix += chunk
                if v.to_out and v.to_mon:
                    shared_mix += chunk

            self._voices = remaining_voices

        return out_mix, mon_mix, shared_mix
