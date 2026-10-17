"""Built-in studio DSP effects engine for Mandible.
Provides true independent pitch and formant shifting, studio reverb, delay, chorus,
analog drive, lo-fi bitcrushing, tactical GSM, and Moog-style ladder filter.
No third-party VSTs required. Pitch & Formant reports ~21 ms of latency (fixed-hop formant STFT);
the other effects add none.
"""
from __future__ import annotations

import json
import math
from typing import Callable
import numpy as np
import pedalboard


class InternalParameter:
    """Emulates a VST3 parameter object with raw [0..1] and engineering values."""

    def __init__(
        self,
        key: str,
        name: str,
        min_val: float,
        max_val: float,
        default_val: float,
        unit: str = "",
        is_log: bool = False,
        step: float = 0.0,
        is_bool: bool = False,
        on_change: Callable[[float], None] | None = None,
    ):
        self.key = key
        self.name = name
        self.min_value = float(min_val)
        self.max_value = float(max_val)
        self.unit = unit
        self.is_log = is_log
        self.step = step
        self.is_bool = is_bool
        self.on_change = on_change
        self._val = float(default_val)

    @property
    def value(self) -> float:
        return self._val

    @value.setter
    def value(self, v: float):
        v = max(self.min_value, min(self.max_value, float(v)))
        if self.step > 0:
            v = round(v / self.step) * self.step
        self._val = v
        if self.on_change:
            self.on_change(self._val)

    @property
    def raw_value(self) -> float:
        if self.max_value == self.min_value:
            return 0.0
        if self.is_log:
            min_log = math.log(max(1e-4, self.min_value))
            max_log = math.log(max(1e-4, self.max_value))
            cur_log = math.log(max(1e-4, self._val))
            return max(0.0, min(1.0, (cur_log - min_log) / (max_log - min_log)))
        return max(0.0, min(1.0, (self._val - self.min_value) / (self.max_value - self.min_value)))

    @raw_value.setter
    def raw_value(self, r: float):
        r = max(0.0, min(1.0, float(r)))
        if self.is_log:
            min_log = math.log(max(1e-4, self.min_value))
            max_log = math.log(max(1e-4, self.max_value))
            v = math.exp(min_log + r * (max_log - min_log))
        else:
            v = self.min_value + r * (self.max_value - self.min_value)
        self.value = v

    @property
    def string_value(self) -> str:
        if self.is_bool:
            return "ON" if self._val >= 0.5 else "OFF"
        if abs(self._val) < 1e-4:
            val_str = "0"
        elif abs(self._val) >= 100:
            val_str = f"{int(round(self._val))}"
        elif abs(self._val) >= 10:
            val_str = f"{self._val:.1f}"
        else:
            val_str = f"{self._val:.2f}"

        if self.unit:
            return f"{val_str} {self.unit}"
        return val_str

    def __repr__(self) -> str:
        return f"<InternalParameter {self.name}={self.string_value}>"


class BaseInternalPlugin:
    """Base interface shared by all internal DSP effects."""

    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        self.parameters: dict[str, InternalParameter] = {}
        self.is_effect = True
        self.is_instrument = False

    def reset(self):
        pass

    def process(self, input_array: np.ndarray, sample_rate: float, buffer_size: int = 512, reset: bool = False) -> np.ndarray:
        raise NotImplementedError

    @property
    def raw_state(self) -> bytes:
        data = {k: p.value for k, p in self.parameters.items()}
        return json.dumps(data).encode("utf-8")

    @raw_state.setter
    def raw_state(self, state_bytes: bytes):
        try:
            data = json.loads(state_bytes.decode("utf-8"))
            for k, val in data.items():
                if k in self.parameters:
                    self.parameters[k].value = float(val)
        except Exception as exc:
            print(f"[InternalDSP] could not restore state: {exc}")


class _FormantStage:
    """Streaming liftered-cepstrum formant shifter for one channel.

    Runs a fixed-hop STFT (n_fft=1024, hop=256, periodic Hann analysis and synthesis windows)
    with its own input/output FIFOs, so the result does not depend on the host buffer size.
    Output latency is constant (``LATENCY`` samples) whether or not a shift is applied.
    """

    N_FFT = 1024
    HOP = 256
    LATENCY = N_FFT  # measured: (N_FFT - HOP) through the window + HOP of output priming

    _window = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)
    _ola_scale = np.float32(1.0 / 1.5)  # sum of Hann^2 at 75% overlap is 1.5
    _lifter_cutoff = 26
    _lifter = np.zeros(N_FFT, dtype=np.float32)
    _lifter[:_lifter_cutoff] = 1.0
    _ramp = 0.5 * (1.0 + np.cos(np.pi * np.arange(_lifter_cutoff) / _lifter_cutoff))
    _lifter[_lifter_cutoff:_lifter_cutoff * 2] = _ramp
    _lifter[-_lifter_cutoff * 2:-_lifter_cutoff] = _ramp[::-1]
    _lifter[-_lifter_cutoff:] = 1.0
    _bins = np.arange(N_FFT // 2 + 1, dtype=np.float32)

    def __init__(self):
        self.reset()

    def reset(self):
        self.frame = np.zeros(self.N_FFT, dtype=np.float32)
        self.ola = np.zeros(self.N_FFT, dtype=np.float32)
        self.in_fifo = np.zeros(0, dtype=np.float32)
        self.out_fifo = np.zeros(self.HOP, dtype=np.float32)  # priming keeps output always available

    def copy_state_from(self, other: "_FormantStage"):
        self.frame[:] = other.frame
        self.ola[:] = other.ola
        self.in_fifo = other.in_fifo.copy()
        self.out_fifo = other.out_fifo.copy()

    def _transform(self, alpha: float) -> np.ndarray:
        x_win = self.frame * self._window
        if abs(alpha - 1.0) < 0.01:
            return x_win  # identity: keeps latency constant without the FFT cost
        X = np.fft.rfft(x_win)
        log_mag = np.log(np.abs(X) + 1e-7)
        env = np.exp(np.fft.rfft(np.fft.irfft(log_mag) * self._lifter).real)
        warped = np.interp(self._bins / alpha, self._bins, env, left=env[0], right=env[-1])
        H = np.clip(warped / env, 0.1, 4.0)
        return np.fft.irfft(X * H, n=self.N_FFT).astype(np.float32)

    def process(self, chunk: np.ndarray, alpha: float) -> np.ndarray:
        hop = self.HOP
        self.in_fifo = np.concatenate((self.in_fifo, chunk.astype(np.float32, copy=False)))
        produced = []
        while len(self.in_fifo) >= hop:
            self.frame[:-hop] = self.frame[hop:]
            self.frame[-hop:] = self.in_fifo[:hop]
            self.in_fifo = self.in_fifo[hop:]
            self.ola += self._transform(alpha) * self._window * self._ola_scale
            produced.append(self.ola[:hop].copy())
            self.ola[:-hop] = self.ola[hop:]
            self.ola[-hop:] = 0.0
        if produced:
            self.out_fifo = np.concatenate([self.out_fifo, *produced])
        n = len(chunk)
        out = self.out_fifo[:n]
        self.out_fifo = self.out_fifo[n:]
        return out


class PitchFormantPlugin(BaseInternalPlugin):
    """
    Real-time independent Pitch & Formant Shifter.
    Pitch: time-domain dual rotating delay-line interpolation (no added latency).
    Formant: streaming liftered-cepstrum spectral envelope warping on a fixed 256-sample hop,
    adding a constant ``reported_latency_samples`` (1024 samples, ~21 ms at 48 kHz) of delay.
    The dry signal used by the Mix control is delayed by the same amount so blends don't phase.
    """

    reported_latency_samples = _FormantStage.LATENCY

    def __init__(self, samplerate: int = 48000):
        super().__init__("Mandible Pitch & Formant", "internal:pitch_formant")
        self.sr = samplerate

        # Delay buffer for pitch shifting
        self.max_delay_ms = 40.0
        self.max_delay_samples = int((self.max_delay_ms / 1000.0) * samplerate)
        self.buffer_len = self.max_delay_samples * 8
        self.buffer_l = np.zeros(self.buffer_len, dtype=np.float32)
        self.buffer_r = np.zeros(self.buffer_len, dtype=np.float32)
        self.write_pos = 0
        self.phase = 0.0
        self.window_size = float(self.max_delay_samples)

        self.formant_l = _FormantStage()
        self.formant_r = _FormantStage()
        self.dry_fifo = np.zeros((2, self.reported_latency_samples), dtype=np.float32)

        # Define parameters
        self.p_pitch = InternalParameter("pitch", "Pitch", -24.0, 24.0, 0.0, unit="st", step=0.1)
        self.p_formant = InternalParameter("formant", "Formant", -12.0, 12.0, 0.0, unit="st", step=0.1)
        self.p_preserve = InternalParameter("preserve_formants", "Preserve Formants", 0.0, 1.0, 1.0, is_bool=True)
        self.p_mix = InternalParameter("mix", "Mix", 0.0, 100.0, 100.0, unit="%", step=1.0)

        self.parameters = {
            "pitch": self.p_pitch,
            "formant": self.p_formant,
            "preserve_formants": self.p_preserve,
            "mix": self.p_mix,
        }

    def reset(self):
        self.buffer_l.fill(0.0)
        self.buffer_r.fill(0.0)
        self.write_pos = 0
        self.phase = 0.0
        self.formant_l.reset()
        self.formant_r.reset()
        self.dry_fifo = np.zeros((2, self.reported_latency_samples), dtype=np.float32)

    def _shift_pitch_mono(self, chunk: np.ndarray, buf: np.ndarray, pitch_st: float) -> np.ndarray:
        frames = len(chunk)
        ratio = 2.0 ** (pitch_st / 12.0)
        rate = (1.0 - ratio) / self.window_size

        blen = self.buffer_len
        w_pos = self.write_pos
        indices = (w_pos + np.arange(frames)) % blen
        buf[indices] = chunk

        phases = (self.phase + np.arange(frames) * rate) % 1.0

        d1 = phases * self.window_size
        r1 = (indices - d1) % blen
        r1_idx = r1.astype(np.int32)
        frac1 = (r1 - r1_idx).astype(np.float32)
        s1 = (1.0 - frac1) * buf[r1_idx] + frac1 * buf[(r1_idx + 1) % blen]

        phases2 = (phases + 0.5) % 1.0
        d2 = phases2 * self.window_size
        r2 = (indices - d2) % blen
        r2_idx = r2.astype(np.int32)
        frac2 = (r2 - r2_idx).astype(np.float32)
        s2 = (1.0 - frac2) * buf[r2_idx] + frac2 * buf[(r2_idx + 1) % blen]

        w1 = 0.5 * (1.0 + np.cos(2.0 * np.pi * phases)).astype(np.float32)
        w2 = 1.0 - w1
        return (w1 * s1 + w2 * s2).astype(np.float32)

    def process(self, input_array: np.ndarray, sample_rate: float, buffer_size: int = 512, reset: bool = False) -> np.ndarray:
        if reset:
            self.reset()

        if input_array.ndim == 1:
            in_2d = np.repeat(input_array.reshape(1, -1), 2, axis=0)
        else:
            in_2d = input_array[:2]

        frames = in_2d.shape[1]
        if frames == 0:
            return in_2d

        pitch_st = self.p_pitch.value
        formant_st = self.p_formant.value
        preserve = self.p_preserve.value >= 0.5
        mix = self.p_mix.value / 100.0

        pitch_ratio = 2.0 ** (pitch_st / 12.0)
        target_formant_ratio = 2.0 ** (formant_st / 12.0)
        if preserve and abs(pitch_st) > 0.05:
            alpha = target_formant_ratio / pitch_ratio
        else:
            alpha = target_formant_ratio

        # Fast path for mono mic on stereo buffer
        is_mono = np.array_equal(in_2d[0], in_2d[1])

        if abs(pitch_st) > 0.05:
            pitched_l = self._shift_pitch_mono(in_2d[0], self.buffer_l, pitch_st)
            if is_mono:
                pitched_r = pitched_l
            else:
                pitched_r = self._shift_pitch_mono(in_2d[1], self.buffer_r, pitch_st)

            # Advance pitch phase and write position once per block
            rate = (1.0 - pitch_ratio) / self.window_size
            self.write_pos = (self.write_pos + frames) % self.buffer_len
            self.phase = (self.phase + frames * rate) % 1.0
        else:
            pitched_l = in_2d[0]
            pitched_r = in_2d[1]

        # Formant stage always runs (identity when alpha ~ 1) so latency stays constant.
        out_l = self.formant_l.process(pitched_l, alpha)
        if is_mono:
            out_r = out_l
            self.formant_r.copy_state_from(self.formant_l)
        else:
            out_r = self.formant_r.process(pitched_r, alpha)

        # Latency-matched dry path for the Mix control.
        self.dry_fifo = np.concatenate((self.dry_fifo, in_2d.astype(np.float32, copy=False)), axis=1)
        dry = self.dry_fifo[:, :frames]
        self.dry_fifo = self.dry_fifo[:, frames:]

        out = np.empty((2, frames), dtype=np.float32)
        if mix < 0.999:
            out[0] = (1.0 - mix) * dry[0] + mix * out_l
            out[1] = (1.0 - mix) * dry[1] + mix * out_r
        else:
            out[0] = out_l
            out[1] = out_r
        return out


class PedalboardWrapper(BaseInternalPlugin):
    """Wraps native pedalboard C++ DSP effects with standard parameter binding."""

    def __init__(self, name: str, path: str, native_plugin, params: list[InternalParameter]):
        super().__init__(name, path)
        self.native = native_plugin
        self.parameters = {p.key: p for p in params}

    def reset(self):
        try:
            self.native.reset()
        except Exception:
            pass

    def process(self, input_array: np.ndarray, sample_rate: float, buffer_size: int = 512, reset: bool = False) -> np.ndarray:
        frames = input_array.shape[-1]
        out = self.native.process(input_array, sample_rate, buffer_size=buffer_size, reset=reset)
        if out.shape[-1] < frames:
            padded = np.zeros_like(input_array)
            if out.shape[-1] > 0:
                padded[:, -out.shape[-1]:] = out
            return padded
        return out[:, :frames] if out.shape[-1] > frames else out


class TacticalRadioPlugin(BaseInternalPlugin):
    """
    Real-time tactical walkie-talkie / military radio codec.
    Applies mu-law non-linear companding, telephone speech bandwidth shaping,
    diode clipping distortion, and squelch noise.
    """

    def __init__(self):
        super().__init__("Tactical GSM Radio", "internal:gsm")
        self.p_drive = InternalParameter("drive", "Drive", 1.0, 5.0, 2.0, unit="", step=0.1)
        self.p_bits = InternalParameter("bits", "Crush", 4.0, 12.0, 7.0, unit="bits", step=0.5)
        self.p_noise = InternalParameter("noise", "Radio Squelch", 0.0, 0.20, 0.02, unit="", step=0.01)
        self.parameters = {
            "drive": self.p_drive,
            "bits": self.p_bits,
            "noise": self.p_noise,
        }

    def process(self, input_array: np.ndarray, sample_rate: float, buffer_size: int = 512, reset: bool = False) -> np.ndarray:
        if input_array.ndim == 1:
            in_2d = np.repeat(input_array.reshape(1, -1), 2, axis=0)
        else:
            in_2d = input_array[:2]

        frames = in_2d.shape[1]
        if frames == 0:
            return in_2d

        drive = self.p_drive.value
        bits = self.p_bits.value
        noise_lvl = self.p_noise.value

        # 1. Drive & Soft Saturation
        x = in_2d * np.float32(drive)

        # 2. Mu-law non-linear speech companding & quantization
        mu = 255.0
        sgn = np.sign(x)
        comp = sgn * np.log1p(mu * np.abs(x)) / np.log1p(mu)
        levels = 2.0 ** (bits - 1.0)
        quant = np.round(comp * levels) / levels
        exp = sgn * (1.0 / mu) * ((1.0 + mu) ** np.abs(quant) - 1.0)

        # 3. Soft clipping
        clipped = np.tanh(exp)

        # 4. Radio noise
        if noise_lvl > 0.001:
            noise = np.random.randn(*in_2d.shape).astype(np.float32) * (noise_lvl * 0.1)
            clipped += noise

        return clipped


def create_studio_reverb() -> PedalboardWrapper:
    fx = pedalboard.Reverb()
    p_room = InternalParameter("room_size", "Room Size", 0.0, 1.0, 0.45, unit="", step=0.01,
                               on_change=lambda v: setattr(fx, "room_size", v))
    p_damp = InternalParameter("damping", "Damping", 0.0, 1.0, 0.5, unit="", step=0.01,
                               on_change=lambda v: setattr(fx, "damping", v))
    p_wet = InternalParameter("wet_level", "Wet Mix", 0.0, 1.0, 0.30, unit="", step=0.01,
                              on_change=lambda v: setattr(fx, "wet_level", v))
    p_dry = InternalParameter("dry_level", "Dry Level", 0.0, 1.0, 1.0, unit="", step=0.01,
                              on_change=lambda v: setattr(fx, "dry_level", v))
    p_width = InternalParameter("width", "Stereo Width", 0.0, 1.0, 1.0, unit="", step=0.01,
                                on_change=lambda v: setattr(fx, "width", v))
    return PedalboardWrapper("Studio Reverb", "internal:reverb", fx, [p_room, p_damp, p_wet, p_dry, p_width])


def create_stereo_delay() -> PedalboardWrapper:
    fx = pedalboard.Delay()
    p_time = InternalParameter("delay_seconds", "Delay Time", 0.02, 1.5, 0.25, unit="s", step=0.01,
                               on_change=lambda v: setattr(fx, "delay_seconds", v))
    p_fb = InternalParameter("feedback", "Feedback", 0.0, 0.90, 0.35, unit="", step=0.01,
                             on_change=lambda v: setattr(fx, "feedback", v))
    p_mix = InternalParameter("mix", "Mix", 0.0, 1.0, 0.35, unit="", step=0.01,
                              on_change=lambda v: setattr(fx, "mix", v))
    return PedalboardWrapper("Stereo Delay", "internal:delay", fx, [p_time, p_fb, p_mix])


def create_vintage_chorus() -> PedalboardWrapper:
    fx = pedalboard.Chorus()
    p_rate = InternalParameter("rate_hz", "Rate", 0.1, 8.0, 1.2, unit="Hz", step=0.1,
                               on_change=lambda v: setattr(fx, "rate_hz", v))
    p_depth = InternalParameter("depth", "Depth", 0.0, 1.0, 0.5, unit="", step=0.01,
                                on_change=lambda v: setattr(fx, "depth", v))
    p_mix = InternalParameter("mix", "Mix", 0.0, 1.0, 0.40, unit="", step=0.01,
                              on_change=lambda v: setattr(fx, "mix", v))
    return PedalboardWrapper("Vintage Chorus", "internal:chorus", fx, [p_rate, p_depth, p_mix])


def create_tube_drive() -> PedalboardWrapper:
    fx = pedalboard.Distortion()
    p_drive = InternalParameter("drive_db", "Drive", 0.0, 36.0, 12.0, unit="dB", step=0.5,
                                on_change=lambda v: setattr(fx, "drive_db", v))
    return PedalboardWrapper("Tube Drive", "internal:distortion", fx, [p_drive])


def create_lofi_bitcrush() -> PedalboardWrapper:
    fx = pedalboard.Bitcrush()
    p_bits = InternalParameter("bit_depth", "Bit Depth", 2.0, 16.0, 8.0, unit="bits", step=0.5,
                               on_change=lambda v: setattr(fx, "bit_depth", v))
    return PedalboardWrapper("Lo-Fi Bitcrush", "internal:bitcrush", fx, [p_bits])


def create_tactical_gsm() -> BaseInternalPlugin:
    return TacticalRadioPlugin()


def create_ladder_filter() -> PedalboardWrapper:
    fx = pedalboard.LadderFilter()
    p_cutoff = InternalParameter("cutoff_hz", "Cutoff", 50.0, 12000.0, 1800.0, unit="Hz", is_log=True, step=10.0,
                                 on_change=lambda v: setattr(fx, "cutoff_hz", v))
    p_res = InternalParameter("resonance", "Resonance", 0.0, 0.90, 0.30, unit="", step=0.01,
                              on_change=lambda v: setattr(fx, "resonance", v))
    p_drive = InternalParameter("drive", "Drive", 1.0, 6.0, 1.0, unit="", step=0.1,
                                on_change=lambda v: setattr(fx, "drive", v))
    return PedalboardWrapper("Ladder Filter", "internal:filter", fx, [p_cutoff, p_res, p_drive])


INTERNAL_FACTORIES: dict[str, Callable[[], BaseInternalPlugin]] = {
    "internal:pitch_formant": lambda: PitchFormantPlugin(),
    "internal:reverb": create_studio_reverb,
    "internal:delay": create_stereo_delay,
    "internal:chorus": create_vintage_chorus,
    "internal:distortion": create_tube_drive,
    "internal:bitcrush": create_lofi_bitcrush,
    "internal:gsm": create_tactical_gsm,
    "internal:filter": create_ladder_filter,
}

INTERNAL_DESCRIPTIONS = [
    {"name": "Mandible Pitch & Formant", "path": "internal:pitch_formant", "vendor": "Mandible DSP", "favorite": True},
    {"name": "Studio Reverb", "path": "internal:reverb", "vendor": "Mandible DSP", "favorite": True},
    {"name": "Stereo Delay", "path": "internal:delay", "vendor": "Mandible DSP", "favorite": False},
    {"name": "Vintage Chorus", "path": "internal:chorus", "vendor": "Mandible DSP", "favorite": False},
    {"name": "Tube Drive", "path": "internal:distortion", "vendor": "Mandible DSP", "favorite": False},
    {"name": "Lo-Fi Bitcrush", "path": "internal:bitcrush", "vendor": "Mandible DSP", "favorite": False},
    {"name": "Tactical GSM Radio", "path": "internal:gsm", "vendor": "Mandible DSP", "favorite": False},
    {"name": "Ladder Filter", "path": "internal:filter", "vendor": "Mandible DSP", "favorite": False},
]


def is_internal_plugin(path: str) -> bool:
    return str(path).startswith("internal:")


def load_internal_plugin(path: str) -> BaseInternalPlugin:
    factory = INTERNAL_FACTORIES.get(path)
    if factory is None:
        raise ValueError(f"Unknown internal DSP plugin: {path}")
    return factory()


def get_internal_plugin_catalog() -> list[dict]:
    return list(INTERNAL_DESCRIPTIONS)
