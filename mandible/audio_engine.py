"""Real-time audio engine: mic in -> pre-fx -> active effects chain -> stereo out.

Design notes
------------
* Lock-free real-time audio callback reading atomically replaced runtimes and targets.
* Mic Pre-FX stage: High-pass rumble cut (80 Hz), AI noise suppression (RNNoise), and Noise Gate.
* Silent keep-alive pump for inactive chains: guarantees plugins (like Serum 2) never suspend,
  eliminating cold-start clicks and latency spikes without switching active voices.
* Soundboard engine: mixes sound clips into output and monitor streams.
* Output Limiter: prevents clipping before sending to Loopback / Discord / OBS.
* Monitor modes: processed / dry / mix for headphones.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from dataclasses import dataclass

import numpy as np
import pedalboard

from .config import AudioSettings, LimiterSettings, PreFXSettings
from .devices import default_samplerate, find_device, sd
from .prefx import PreFXProcessor
from .soundboard import SoundboardEngine

DRY_ID = "__dry__"


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


@dataclass
class ChainRuntime:
    id: str
    board: object | None      # pedalboard.Pedalboard, or None for a clean pass-through
    gain: float = 1.0
    tail_s: float = 2.0
    dry_wet: float = 1.0      # 0.0 = clean, 1.0 = fully wet
    latency_samples: int = 0
    error: str = ""
    slots: tuple = ()         # tuple of PluginSlot objects for per-plugin Pre/Post metering


class AudioEngine:
    def __init__(self):
        self.stream: sd.Stream | None = None
        self.mon_stream: sd.OutputStream | None = None
        self._mon_queue: queue.Queue | None = None
        self.samplerate = 48000
        self.blocksize = 128
        self.driver = ""
        self.latency_ms = 0.0

        self.in_gain = 1.0
        self.out_gain = 1.0
        self.monitor_enabled = False
        self.monitor_gain = 1.0
        self.monitor_mode = "processed"  # "processed" | "dry" | "mix"

        self.prefx = PreFXProcessor(PreFXSettings(), samplerate=self.samplerate)
        self.soundboard = SoundboardEngine()
        self.limiter: pedalboard.Limiter | None = pedalboard.Limiter(threshold_db=-0.5, release_ms=50.0)
        self.keep_awake = True
        self.crossfade_ms = 15.0
        self.ptt_muted = False  # Set to True when Push-to-Talk is inactive or Push-to-Mute is held

        # Mic Audition (5-second mic check / loopback audition)
        self.audition_state: str = "idle"  # "idle" | "recording" | "looping"
        self.audition_duration_s: float = 5.0
        self.audition_target_frames: int = 0
        self.audition_rec_frames: int = 0
        self._audition_chunks: list[np.ndarray] = []
        self.audition_buffer: np.ndarray | None = None
        self.audition_play_pos: int = 0

        # Soundboard Mic Ducking
        self.soundboard_ducking_enabled: bool = False
        self.soundboard_duck_db: float = -12.0
        self._duck_gain: float = 1.0

        # Output Loudness Normalizer
        self.normalizer_enabled: bool = False
        self.normalizer_target_db: float = -14.0
        self._norm_gain: float = 1.0

        self._runtimes: dict[str, ChainRuntime] = {
            DRY_ID: ChainRuntime(DRY_ID, None, 1.0, 0.0, 1.0, 0)
        }
        self._target: str | None = DRY_ID
        self._voices: dict[str, list] = {}   # audio-thread only: id -> [gain, tail_left]

        self._in_col = 0
        self._out_cols = (0, 1)
        self._mon_cols: tuple[int, int] | None = None

        # Stats read by GUI
        self.peak_in = 0.0
        self.peak_out = 0.0
        self.peak_mon = 0.0
        self.load = 0.0
        self.xruns = 0
        self.last_error = ""
        self.on_stopped = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- state API
    @property
    def running(self) -> bool:
        return self.stream is not None and self.stream.active

    def set_target(self, chain_id: str | None) -> None:
        self._target = chain_id

    def set_runtime(self, rt: ChainRuntime) -> None:
        with self._lock:
            new = dict(self._runtimes)
            new[rt.id] = rt
            self._runtimes = new

    def remove_runtime(self, chain_id: str) -> None:
        with self._lock:
            new = dict(self._runtimes)
            new.pop(chain_id, None)
            self._runtimes = new

    def runtime(self, chain_id: str) -> ChainRuntime | None:
        return self._runtimes.get(chain_id)

    def active_voices(self) -> list[str]:
        return list(self._voices.keys())

    def update_prefx(self, cfg: PreFXSettings):
        self.prefx.update_settings(cfg, samplerate=self.samplerate)

    def update_limiter(self, cfg: LimiterSettings):
        if cfg.enabled:
            self.limiter = pedalboard.Limiter(
                threshold_db=float(cfg.threshold_db),
                release_ms=float(cfg.release_ms),
            )
        else:
            self.limiter = None

    def start_mic_audition(self, duration_s: float = 5.0) -> None:
        """Begin recording a dry mic loop for auditioning chains and macro knobs."""
        self.audition_duration_s = max(1.0, min(30.0, float(duration_s)))
        self.audition_target_frames = int(self.audition_duration_s * (self.samplerate or 48000))
        self.audition_rec_frames = 0
        self._audition_chunks = []
        self.audition_state = "recording"

    def stop_mic_audition(self) -> None:
        """Stop audition recording or playback loop and return to live microphone."""
        self.audition_state = "idle"
        self._audition_chunks = []
        self.audition_rec_frames = 0
        self.audition_play_pos = 0

    def get_audition_status(self) -> tuple[str, float, float]:
        """Return (state, current_seconds, target_seconds)."""
        sr = float(self.samplerate or 48000)
        if self.audition_state == "recording":
            cur = self.audition_rec_frames / sr
        elif self.audition_state == "looping":
            cur = self.audition_play_pos / sr
        else:
            cur = 0.0
        return self.audition_state, cur, self.audition_duration_s

    # ------------------------------------------------------------- stream
    def start(self, a: AudioSettings) -> None:
        self.stop()
        if not a.driver:
            raise RuntimeError("No audio driver selected. Open Audio Settings first.")
        is_asio = a.driver == "ASIO"
        in_dev = find_device(a.driver, a.input_device, "input")
        if in_dev is None:
            raise RuntimeError(f"Input device not found: {a.input_device!r} ({a.driver})")
        if is_asio:
            out_dev = find_device(a.driver, a.input_device, "output")
        else:
            out_dev = find_device(a.driver, a.output_device, "output")
        if out_dev is None:
            raise RuntimeError(f"Output device not found: {a.output_device!r} ({a.driver})")

        sr = int(a.samplerate) or default_samplerate(out_dev)
        bs = int(a.blocksize) or 256
        out_l, out_r = (list(a.output_channels) + [0, 1])[:2]

        if is_asio:
            mon_l, mon_r = (list(a.monitor_channels) + [0, 1])[:2]
            channels = (1, 4)
            extra = (
                sd.AsioSettings(channel_selectors=[int(a.input_channel)]),
                sd.AsioSettings(channel_selectors=[int(out_l), int(out_r), int(mon_l), int(mon_r)]),
            )
            self._in_col = 0
            self._out_cols = (0, 1)
            self._mon_cols = (2, 3)
        else:
            n_out = max(out_l, out_r) + 1
            channels = (int(a.input_channel) + 1, n_out)
            self._in_col, self._out_cols = int(a.input_channel), (int(out_l), int(out_r))
            self._mon_cols = None
            if a.driver == "Windows WASAPI":
                ws = sd.WasapiSettings(
                    exclusive=bool(a.wasapi_exclusive),
                    auto_convert=not a.wasapi_exclusive,
                )
                extra = (ws, ws)
            else:
                extra = (None, None)

        self.samplerate, self.blocksize, self.driver = sr, bs, a.driver
        self.prefx.update_settings(self.prefx.cfg, samplerate=sr)
        self.soundboard.samplerate = sr
        self._voices = {}
        self._prewarm_all()

        if not is_asio and a.monitor_device and a.monitor_device != a.output_device:
            mon_dev = find_device(a.driver, a.monitor_device, "output")
            if mon_dev is not None:
                try:
                    self._mon_queue = queue.Queue(maxsize=16)
                    self.mon_stream = sd.OutputStream(
                        device=mon_dev,
                        samplerate=sr,
                        blocksize=bs,
                        channels=2,
                        dtype="float32",
                        latency="low",
                        extra_settings=ws if a.driver == "Windows WASAPI" else None,
                        callback=self._mon_callback,
                    )
                    self.mon_stream.start()
                except Exception as exc:
                    print(f"[Mandible] could not start secondary monitor stream: {exc}")
                    self.mon_stream = None
                    self._mon_queue = None

        stream = sd.Stream(
            device=(in_dev, out_dev),
            samplerate=sr,
            blocksize=bs,
            dtype="float32",
            channels=channels,
            latency="low",
            extra_settings=extra,
            callback=self._callback,
            finished_callback=self._finished,
        )
        stream.start()
        self.stream = stream
        lat = stream.latency
        self.latency_ms = (sum(lat) if isinstance(lat, (tuple, list)) else float(lat)) * 1000.0
        self.xruns = 0
        self.last_error = ""

    def stop(self) -> None:
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.abort(ignore_errors=True)
                s.close(ignore_errors=True)
            except Exception:
                pass
        ms, self.mon_stream = self.mon_stream, None
        if ms is not None:
            try:
                ms.abort(ignore_errors=True)
                ms.close(ignore_errors=True)
            except Exception:
                pass
        self._mon_queue = None

    def _mon_callback(self, outdata, frames, time_info, status):
        q = self._mon_queue
        if q is not None:
            try:
                data = q.get_nowait()
                outdata[:] = data
                return
            except queue.Empty:
                pass
        outdata.fill(0.0)

    def _finished(self):
        if self.on_stopped and self.stream is not None:
            try:
                self.on_stopped("Audio stream stopped")
            except Exception:
                pass

    # ------------------------------------------------------------- helpers
    def prewarm(self, plugin_or_board) -> None:
        try:
            z = np.zeros((2, self.blocksize), np.float32)
            plugin_or_board.process(z, self.samplerate, buffer_size=self.blocksize, reset=False)
        except Exception:
            pass

    def _prewarm_all(self) -> None:
        for rt in self._runtimes.values():
            if rt.board is not None:
                self.prewarm(rt.board)

    # ------------------------------------------------------------- real-time
    def _callback(self, indata, outdata, frames, time_info, status):
        t0 = time.perf_counter()
        if status:
            self.xruns += 1
        try:
            # 1. Mic input and gain
            raw_mono = indata[:, self._in_col] * np.float32(self.in_gain)

            # 2. Push-to-Talk / Mute check
            if self.ptt_muted:
                raw_mono = np.zeros_like(raw_mono)

            # 3. Mic Pre-FX: Highpass + AI RNNoise + Noise Gate
            mono = self.prefx.process(raw_mono)
            pin = float(np.max(np.abs(mono))) if frames else 0.0
            if pin > self.peak_in:
                self.peak_in = pin

            # 3b. Mic Audition (5-second mic check & loopback audition)
            if self.audition_state == "recording":
                self._audition_chunks.append(mono.copy())
                self.audition_rec_frames += frames
                if self.audition_rec_frames >= self.audition_target_frames:
                    if self._audition_chunks:
                        self.audition_buffer = np.concatenate(self._audition_chunks)
                    self.audition_state = "looping"
                    self.audition_play_pos = 0
                    self._audition_chunks.clear()
            elif self.audition_state == "looping" and self.audition_buffer is not None and len(self.audition_buffer) > 0:
                tot = len(self.audition_buffer)
                end = self.audition_play_pos + frames
                if end <= tot:
                    mono = self.audition_buffer[self.audition_play_pos:end]
                    self.audition_play_pos = end % tot
                else:
                    part1 = self.audition_buffer[self.audition_play_pos:]
                    rem = frames - len(part1)
                    part2 = self.audition_buffer[:rem]
                    mono = np.concatenate([part1, part2])
                    self.audition_play_pos = rem

            # 3c. Soundboard Mic Ducking
            if self.soundboard_ducking_enabled:
                is_ducking = self.soundboard.is_any_playing()
                target_duck = db_to_lin(self.soundboard_duck_db) if is_ducking else 1.0
                alpha = 0.08 if target_duck < self._duck_gain else 0.015
                self._duck_gain += (target_duck - self._duck_gain) * alpha
                if self._duck_gain < 0.999:
                    mono = mono * np.float32(self._duck_gain)

            # 4. Target voice & crossfading
            target = self._target
            runtimes = self._runtimes
            voices = self._voices
            if target is not None and target not in voices and target in runtimes:
                voices[target] = [0.0, 0]

            sr = self.samplerate
            step = frames / max(1.0, (self.crossfade_ms / 1000.0) * sr)
            mix = np.zeros((2, frames), np.float32)

            for vid in list(voices):
                rt = runtimes.get(vid)
                if rt is None:
                    del voices[vid]
                    continue
                v = voices[vid]
                g0 = v[0]
                g1 = min(1.0, g0 + step) if vid == target else max(0.0, g0 - step)
                v[0] = g1

                if g0 == 0.0 and g1 == 0.0:
                    # Switched off: let the tail ring out, then retire the voice.
                    if v[1] <= 0 or rt.board is None:
                        del voices[vid]
                        continue
                    v[1] -= frames
                    inp = np.zeros(frames, np.float32)
                else:
                    v[1] = int(rt.tail_s * sr)
                    if g0 == 1.0 and g1 == 1.0:
                        inp = mono
                    else:
                        env = np.linspace(g0, g1, frames, endpoint=False, dtype=np.float32)
                        inp = mono * env

                if rt.board is None and not rt.slots:
                    mix += inp * np.float32(rt.gain)
                    continue

                buf = np.empty((2, frames), np.float32)
                buf[0] = inp
                buf[1] = inp
                try:
                    if rt.slots:
                        cur = buf.copy()
                        for s in rt.slots:
                            pre_pk = float(np.max(np.abs(cur))) if frames else 0.0
                            if pre_pk > getattr(s, "_pre_peak", 0.0):
                                s._pre_peak = pre_pk
                            p_inst = getattr(s, "_instance", None)
                            if s.enabled and p_inst is not None:
                                y_s = p_inst.process(cur, sr, buffer_size=frames, reset=False)
                                if y_s.ndim == 1 or y_s.shape[0] == 1:
                                    y_1d = y_s.reshape(-1)[:frames]
                                    cur = np.empty((2, frames), np.float32)
                                    cur[0] = y_1d
                                    cur[1] = y_1d
                                else:
                                    cur = y_s[:2, :frames]
                                post_pk = float(np.max(np.abs(cur))) if frames else 0.0
                                if post_pk > getattr(s, "_post_peak", 0.0):
                                    s._post_peak = post_pk
                        y_stereo = cur
                    else:
                        y = rt.board.process(buf, sr, buffer_size=frames, reset=False)
                        if y.ndim == 1 or y.shape[0] == 1:
                            y_proc = y.reshape(-1)[:frames]
                            y_stereo = np.empty((2, frames), np.float32)
                            y_stereo[0] = y_proc
                            y_stereo[1] = y_proc
                        else:
                            y_stereo = y[:2, :frames]
                except Exception as exc:
                    rt.error = str(exc)
                    rt.board = None
                    mix += inp * np.float32(rt.gain)
                    continue


                # Dry / Wet blending per chain
                dw = np.float32(rt.dry_wet)
                if dw < 0.999:
                    wet_mix = (1.0 - dw) * buf + dw * y_stereo
                else:
                    wet_mix = y_stereo

                mix += wet_mix * np.float32(rt.gain)

            # 5. Keep inactive chains pre-warmed & awake with silence (prevents VST suspension)
            if self.keep_awake:
                for rid, rt in runtimes.items():
                    if rid not in voices and rt.board is not None:
                        try:
                            z = np.zeros((2, frames), dtype=np.float32)
                            rt.board.process(z, sr, buffer_size=frames, reset=False)
                        except Exception:
                            pass

            # 6. Soundboard audio mix
            sb_out, sb_mon = self.soundboard.mix(frames)
            mix += sb_out

            # 7. Master output volume
            mix *= np.float32(self.out_gain)

            # 7b. Output Loudness Normalizer
            if self.normalizer_enabled:
                rms = float(np.sqrt(np.mean(mix ** 2))) + 1e-6
                if rms > 0.005:  # active voice > -46 dB
                    target_lin = db_to_lin(self.normalizer_target_db) * 0.707
                    desired = float(np.clip(target_lin / rms, 0.25, 4.0))  # max +/- 12 dB correction
                    self._norm_gain += (desired - self._norm_gain) * 0.03
                mix *= np.float32(self._norm_gain)

            # 8. Output Limiter (prevents clipping/distortion to 0.0 dBFS)
            if self.limiter is not None:
                try:
                    mix = self.limiter.process(mix, sr, buffer_size=frames, reset=False)
                except Exception:
                    np.clip(mix, -1.0, 1.0, out=mix)
            else:
                np.clip(mix, -1.0, 1.0, out=mix)

            pout = float(np.max(np.abs(mix))) if frames else 0.0
            if pout > self.peak_out:
                self.peak_out = pout

            # 9. Write to main output (Playback 3-4 / loopback)
            outdata.fill(0.0)
            outdata[:, self._out_cols[0]] = mix[0]
            outdata[:, self._out_cols[1]] = mix[1]

            # 10. Headphone Monitor
            if self.monitor_enabled:
                mg = np.float32(self.monitor_gain)

                # Determine monitor blend
                if self.monitor_mode == "dry":
                    mon_feed = np.repeat(mono.reshape(1, -1), 2, axis=0) + sb_mon
                elif self.monitor_mode == "mix":
                    dry_stereo = np.repeat(mono.reshape(1, -1), 2, axis=0)
                    mon_feed = 0.5 * mix + 0.5 * dry_stereo + sb_mon
                else:  # "processed"
                    mon_feed = mix + sb_mon

                mon_feed = mon_feed * mg
                np.clip(mon_feed, -1.0, 1.0, out=mon_feed)

                pmon = float(np.max(np.abs(mon_feed))) if frames else 0.0
                if pmon > self.peak_mon:
                    self.peak_mon = pmon

                if self._mon_cols is not None:
                    outdata[:, self._mon_cols[0]] = mon_feed[0]
                    outdata[:, self._mon_cols[1]] = mon_feed[1]
                elif self._mon_queue is not None:
                    try:
                        m_buf = np.empty((frames, 2), dtype=np.float32)
                        m_buf[:, 0] = mon_feed[0]
                        m_buf[:, 1] = mon_feed[1]
                        self._mon_queue.put_nowait(m_buf)
                    except queue.Full:
                        pass
        except Exception:
            outdata.fill(0.0)
            self.last_error = traceback.format_exc(limit=3)

        dt = time.perf_counter() - t0
        self.load = 0.9 * self.load + 0.1 * (dt * self.samplerate / max(1, frames))
