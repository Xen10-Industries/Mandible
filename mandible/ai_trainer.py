"""AI voice profile training, dataset STFT slicing, phonetic indexing, and ONNX neural vocoder trainer."""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pedalboard.io

from .ai_voice import (
    AI_MODELS_DIR,
    CONTENT_DIM,
    FFT_SIZE,
    HIDDEN_DIM,
    SPEC_BINS,
    extract_cepstral_features,
    save_neural_onnx_model,
    save_phonetic_index,
)


@dataclass
class TrainingSampleInfo:
    """Metadata for an imported training audio file."""
    path: str
    filename: str
    duration_s: float
    channels: int
    samplerate: int
    is_valid: bool
    error: str = ""


MANDIBLE_RVC_DIR = os.path.abspath(os.path.join(AI_MODELS_DIR, "..", "tools", "mandible-rvc"))
MANDIBLE_RVC_REPO = "Xen10-Industries/mandible-rvc"
MANDIBLE_RVC_ZIP_URL = (
    "https://github.com/Xen10-Industries/mandible-rvc/releases/download/v0.1.0/mandible-rvc-v0.1.0-windows-x64.zip"
)


def find_mandible_rvc_exe() -> str | None:
    """Return path to mandible-rvc executable, batch launcher, or script if installed."""
    custom = os.environ.get("MANDIBLE_RVC_EXE")
    if custom and os.path.isfile(custom):
        return custom

    # Standard tool directory in %APPDATA%/Xen10/Mandible/tools/mandible-rvc
    candidates = [
        os.path.join(MANDIBLE_RVC_DIR, "mandible-rvc.exe"),
        os.path.join(MANDIBLE_RVC_DIR, "mandible-rvc.bat"),
        os.path.join(MANDIBLE_RVC_DIR, "mandible_rvc", "__main__.py"),
        os.path.join(MANDIBLE_RVC_DIR, ".venv", "Scripts", "python.exe"),
        os.path.join(MANDIBLE_RVC_DIR, "venv", "Scripts", "python.exe"),
        # Local developer sibling directory
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mandible-rvc", "mandible-rvc.bat")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mandible-rvc", "mandible_rvc", "__main__.py")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mandible-rvc", ".venv", "Scripts", "python.exe")),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def download_and_install_rvc_addon(
    progress_cb: Callable[[int, int], None] | None = None,
    dest_dir: str = MANDIBLE_RVC_DIR,
    zip_url: str = MANDIBLE_RVC_ZIP_URL,
) -> str:
    """Download the official Mandible RVC add-on zip from GitHub Releases and extract it."""
    import io
    import urllib.request
    import zipfile

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

    exe = find_mandible_rvc_exe()
    if exe is None:
        raise RuntimeError("Add-on was downloaded but executable could not be verified.")
    return exe


@dataclass
class TrainingJobConfig:
    """Hyperparameters and configuration for voice model training."""
    voice_name: str
    input_files: list[str]
    target_sr: int = 40000
    epochs: int = 150
    batch_size: int = 8
    f0_method: str = "hybrid"  # "hybrid", "rmvpe", "harvest"
    extract_f0: bool = True
    normalize_loudness: bool = True
    clean_audio: bool = True
    sub_harmonic_depth: float = 0.0
    vocal_tract_bias: float = 0.0
    air_shimmer: float = 0.15
    trainer_engine: str = "builtin"  # "builtin" or "rvc"


@dataclass
class TrainingProgress:
    """Real-time telemetry emitted during dataset preparation and model training."""
    stage: str = "idle"  # "idle", "preparing", "extracting", "indexing", "training", "exporting", "completed", "error", "cancelled"
    stage_description: str = ""
    current_step: int = 0
    total_steps: int = 0
    epoch: int = 0
    total_epochs: int = 0
    loss: float = 0.0
    best_loss: float = 0.0
    elapsed_s: float = 0.0
    eta_s: float = 0.0
    error_message: str = ""


def inspect_audio_file(file_path: str) -> TrainingSampleInfo:
    """Analyze an audio file (.wav, .mp3, .flac, .ogg, .m4a) and return its metadata."""
    clean_path = os.path.abspath(file_path)
    base = os.path.basename(clean_path)
    if not os.path.isfile(clean_path):
        return TrainingSampleInfo(clean_path, base, 0.0, 0, 0, False, "File does not exist")
    try:
        with pedalboard.io.AudioFile(clean_path, "r") as af:
            frames = af.frames
            sr = af.samplerate
            ch = af.num_channels
            dur = float(frames / sr) if sr > 0 else 0.0
            if dur < 0.2:
                return TrainingSampleInfo(clean_path, base, dur, ch, sr, False, "Audio is too short (< 0.2s)")
            return TrainingSampleInfo(clean_path, base, dur, ch, sr, True)
    except Exception as exc:
        return TrainingSampleInfo(clean_path, base, 0.0, 0, 0, False, f"Could not read audio: {exc}")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_").lower()
    return slug or "custom_voice"


def _fit_phonetic_codebook(
    C: np.ndarray, S: np.ndarray, num_clusters: int = 96, iters: int = 8
) -> tuple[np.ndarray, np.ndarray]:
    """Fit a k-means phonetic retrieval codebook ``(keys [K, 32], envelopes [K, 513])``."""
    n = C.shape[0]
    k = max(4, min(num_clusters, n))
    rng = np.random.default_rng(42)
    choice = rng.choice(n, size=k, replace=(n < k))
    keys = C[choice].copy()
    envs = S[choice].copy()

    for _ in range(iters):
        sims = C @ keys.T  # [N, K]
        assign = np.argmax(sims, axis=1)
        for cid in range(k):
            mask = assign == cid
            if np.any(mask):
                k_mean = np.mean(C[mask], axis=0)
                k_norm = float(np.linalg.norm(k_mean))
                if k_norm > 1e-6:
                    keys[cid] = k_mean / k_norm
                envs[cid] = np.mean(S[mask], axis=0)
    return keys.astype(np.float32), envs.astype(np.float32)


class VoiceModelTrainer:
    """
    Background worker that runs the full voice model training workflow:
    1. Dataset validation & audio slicing with silence removal.
    2. STFT cepstral phonetic feature & target vocal-tract envelope extraction.
    3. k-NN / FAISS phonetic retrieval codebook clustering (.index).
    4. Mini-batch Adam backpropagation training of the 3-layer ONNX neural vocoder.
    5. Auto-export to standard .onnx model + .index files registered into Mandible.
    """

    def __init__(
        self,
        config: TrainingJobConfig,
        models_dir: str | None = None,
        progress_cb: Callable[[TrainingProgress], None] | None = None,
    ):
        self.config = config
        self.models_dir = models_dir or AI_MODELS_DIR
        self.progress_cb = progress_cb
        self._cancel_event = threading.Event()
        self._is_running = False
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        if self._is_running:
            return
        self._cancel_event.clear()
        self._is_running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _emit(self, prog: TrainingProgress) -> None:
        if self.progress_cb is not None:
            try:
                self.progress_cb(prog)
            except Exception:
                pass

    def _run_rvc_subprocess(self, rvc_exe: str, start_time: float) -> None:
        import subprocess
        cfg = self.config
        total_epochs = max(10, cfg.epochs)

        # Check what kind of executable we have
        lower = rvc_exe.lower()
        env = dict(os.environ)
        if lower.endswith(".py"):
            repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(rvc_exe)))
            cmd = [sys.executable, rvc_exe]
            cur_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{repo_dir};{cur_pp}" if cur_pp else repo_dir
        elif lower.endswith(".bat") or lower.endswith(".cmd"):
            cmd = [rvc_exe]
        elif lower.endswith("python.exe") or lower.endswith("python"):
            cmd = [rvc_exe, "-m", "mandible_rvc"]
        else:
            cmd = [rvc_exe]
        cmd.extend([
            "train",
            "--input", *cfg.input_files,
            "--name", cfg.voice_name,
            "--output-dir", self.models_dir,
            "--epochs", str(total_epochs),
            "--batch-size", str(cfg.batch_size),
            "--f0-method", cfg.f0_method,
            "--sample-rate", str(cfg.target_sr),
        ])

        self._emit(TrainingProgress(
            stage="preparing",
            stage_description=f"Launching RVC v2 deep-learning sidecar ({os.path.basename(rvc_exe)})\u2026",
            current_step=5,
            total_steps=100,
            epoch=0,
            total_epochs=total_epochs,
        ))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        try:
            while True:
                if self._cancel_event.is_set():
                    proc.terminate()
                    self._emit(TrainingProgress(stage="cancelled", stage_description="Training cancelled by user"))
                    return
                line = proc.stdout.readline() if proc.stdout else ""
                if not line and proc.poll() is not None:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        stage = str(data.get("stage", "training"))
                        desc = str(data.get("description", ""))
                        step = int(data.get("step", 50))
                        epoch = int(data.get("epoch", 0))
                        loss = float(data.get("loss", 0.0))
                        elapsed = time.time() - start_time
                        if stage == "completed":
                            self._emit(TrainingProgress(
                                stage="completed",
                                stage_description=desc or "RVC v2 training completed successfully!",
                                current_step=100,
                                total_steps=100,
                                epoch=total_epochs,
                                total_epochs=total_epochs,
                                loss=loss,
                                elapsed_s=elapsed,
                            ))
                            return
                        elif stage == "error":
                            raise RuntimeError(data.get("error", "RVC v2 training error"))
                        else:
                            self._emit(TrainingProgress(
                                stage=stage,
                                stage_description=desc,
                                current_step=step,
                                total_steps=100,
                                epoch=epoch,
                                total_epochs=total_epochs,
                                loss=loss,
                                elapsed_s=elapsed,
                            ))
                except json.JSONDecodeError:
                    pass
            ret = proc.wait()
            if ret != 0:
                raise RuntimeError(f"RVC v2 process exited with code {ret}")
        finally:
            if proc.poll() is None:
                proc.kill()

    def _run(self) -> None:
        start_time = time.time()
        cfg = self.config
        total_epochs = max(10, cfg.epochs)

        try:
            if cfg.trainer_engine == "rvc":
                rvc_exe = find_mandible_rvc_exe()
                if rvc_exe is None:
                    raise RuntimeError(
                        "Mandible RVC Deep-Learning Add-on is not installed. "
                        "Please download the mandible-rvc add-on or switch to the in-app neural vocoder."
                    )
                self._run_rvc_subprocess(rvc_exe, start_time)
                return

            # 1. Dataset verification
            self._emit(TrainingProgress(
                stage="preparing",
                stage_description="Scanning and verifying input audio files…",
                current_step=0,
                total_steps=100,
                epoch=0,
                total_epochs=total_epochs,
            ))

            if not cfg.input_files:
                raise ValueError("No audio files provided for training.")

            valid_samples: list[TrainingSampleInfo] = []
            for path in cfg.input_files:
                if self._cancel_event.is_set():
                    self._emit(TrainingProgress(stage="cancelled", stage_description="Training cancelled by user"))
                    return
                info = inspect_audio_file(path)
                if info.is_valid:
                    valid_samples.append(info)

            if not valid_samples:
                raise ValueError("None of the provided files contain valid readable audio.")

            total_dur = sum(s.duration_s for s in valid_samples)
            if total_dur < 1.0:
                raise ValueError("Total training dataset is too short (needs at least 1.0 second of voice).")

            # 2. Audio slicing & pre-processing
            self._emit(TrainingProgress(
                stage="preparing",
                stage_description=f"Preprocessing {len(valid_samples)} audio files ({total_dur:.1f}s total)…",
                current_step=12,
                total_steps=100,
                epoch=0,
                total_epochs=total_epochs,
            ))

            all_audio_slices: list[np.ndarray] = []
            slice_sr = cfg.target_sr

            for sample in valid_samples:
                if self._cancel_event.is_set():
                    self._emit(TrainingProgress(stage="cancelled", stage_description="Training cancelled by user"))
                    return
                try:
                    with pedalboard.io.AudioFile(sample.path, "r") as af:
                        raw = af.read(af.frames)
                        sr = af.samplerate
                        slice_sr = int(sr or slice_sr)
                except Exception:
                    continue

                if raw.ndim == 1:
                    mono = raw.astype(np.float32)
                elif raw.shape[0] == 1:
                    mono = raw[0].astype(np.float32)
                else:
                    mono = np.mean(raw[:2], axis=0).astype(np.float32)

                if cfg.normalize_loudness:
                    peak = float(np.max(np.abs(mono)))
                    if peak > 1e-4:
                        mono = mono / peak * 0.90

                chunk_len = int(slice_sr * 1.5)
                if len(mono) <= chunk_len:
                    all_audio_slices.append(mono)
                else:
                    hop_chunk = max(1, chunk_len // 2)
                    for pos in range(0, len(mono) - chunk_len // 2, hop_chunk):
                        chunk = mono[pos : pos + chunk_len]
                        if float(np.mean(chunk ** 2)) > 1e-5:
                            all_audio_slices.append(chunk)

            if not all_audio_slices:
                raise ValueError("Could not extract non-silent vocal segments from dataset.")

            num_slices = len(all_audio_slices)

            # 3. STFT Cepstral & F0 Feature Extraction across all voiced frames
            self._emit(TrainingProgress(
                stage="extracting",
                stage_description=f"Extracting STFT cepstral envelopes & F0 pitch across {num_slices} vocal segments…",
                current_step=28,
                total_steps=100,
                epoch=0,
                total_epochs=total_epochs,
            ))

            hann = np.hanning(FFT_SIZE).astype(np.float32)
            stft_hop = FFT_SIZE // 2
            content_list: list[np.ndarray] = []
            env_list: list[np.ndarray] = []
            f0_estimates: list[float] = []
            sub_ratios: list[float] = []
            air_ratios: list[float] = []

            for s_idx, s in enumerate(all_audio_slices):
                if self._cancel_event.is_set():
                    self._emit(TrainingProgress(stage="cancelled", stage_description="Training cancelled by user"))
                    return

                # F0 estimation via autocorrelation on every 4th slice
                if s_idx % 2 == 0 and len(f0_estimates) < 96:
                    center = s[len(s) // 4 : 3 * len(s) // 4]
                    if len(center) > 2048:
                        center = center[:2048]
                    if len(center) >= 512:
                        ac = np.correlate(center, center, mode="full")
                        ac = ac[len(ac) // 2 :]
                        min_lag = max(1, int(slice_sr / 480))
                        max_lag = min(len(ac) - 1, int(slice_sr / 60))
                        if max_lag > min_lag:
                            peak_lag = min_lag + int(np.argmax(ac[min_lag:max_lag]))
                            if peak_lag > 0:
                                est = slice_sr / peak_lag
                                if 60.0 <= est <= 480.0:
                                    f0_estimates.append(est)

                # Extract STFT frames from this vocal slice
                if len(s) < FFT_SIZE:
                    padded = np.zeros(FFT_SIZE, dtype=np.float32)
                    padded[: len(s)] = s
                    frames_iter = [padded]
                else:
                    frames_iter = [
                        s[p : p + FFT_SIZE]
                        for p in range(0, len(s) - FFT_SIZE + 1, stft_hop)
                    ]

                for frame in frames_iter:
                    rms = float(np.sqrt(np.mean(frame * frame)))
                    if rms < 0.008:
                        continue
                    mag = np.abs(np.fft.rfft(frame * hann)).astype(np.float32)
                    c_vec, log_env = extract_cepstral_features(mag)
                    content_list.append(c_vec)
                    env_list.append(log_env)

                    # Measure sub-bass (<140 Hz) and air (>5.5 kHz) energy ratios
                    total_e = float(np.sum(mag) + 1e-6)
                    bin_hz = (slice_sr / 2.0) / SPEC_BINS
                    sub_bin = max(2, int(140.0 / bin_hz))
                    air_bin = min(SPEC_BINS - 2, int(5500.0 / bin_hz))
                    sub_ratios.append(float(np.sum(mag[1:sub_bin]) / total_e))
                    air_ratios.append(float(np.sum(mag[air_bin:]) / total_e))

                    if len(content_list) >= 6000:
                        break
                if len(content_list) >= 6000:
                    break

            if not content_list:
                # Fallback if signal was very quiet
                mag = np.abs(np.fft.rfft(np.hanning(FFT_SIZE).astype(np.float32))).astype(np.float32)
                c_vec, log_env = extract_cepstral_features(mag)
                content_list = [c_vec] * 16
                env_list = [log_env] * 16

            avg_f0 = float(np.median(f0_estimates)) if f0_estimates else 175.0
            measured_sub = float(np.clip(np.median(sub_ratios) * 2.2 if sub_ratios else 0.15, 0.0, 0.85))
            measured_air = float(np.clip(np.median(air_ratios) * 1.8 if air_ratios else 0.15, 0.05, 0.80))

            C_matrix = np.vstack(content_list).astype(np.float32)  # [N, 32]
            S_matrix = np.vstack(env_list).astype(np.float32)      # [N, 513]

            # Speaker Cepstral Mean Normalization (CMN) on C_matrix so inputs represent
            # speaker-independent phonetic/vowel content while S_matrix holds target vocal timbre
            c_mean = np.mean(C_matrix, axis=0, keepdims=True)
            C_norm = C_matrix - c_mean
            c_norms = np.linalg.norm(C_norm, axis=1, keepdims=True) + 1e-6
            C_norm = (C_norm / c_norms).astype(np.float32)

            # Apply optional user vocal-tract bias & sub/air adjustments to target envelopes
            if abs(cfg.vocal_tract_bias) > 0.05:
                shift_ratio = float(2.0 ** (cfg.vocal_tract_bias / 12.0))
                src_bins = np.arange(SPEC_BINS, dtype=np.float32)
                warped_bins = np.clip(src_bins / shift_ratio, 0.0, SPEC_BINS - 1.0)
                for i in range(S_matrix.shape[0]):
                    S_matrix[i] = np.interp(warped_bins, src_bins, S_matrix[i]).astype(np.float32)

            # 4. Fit Phonetic Feature Retrieval Codebook (.index)
            self._emit(TrainingProgress(
                stage="indexing",
                stage_description=f"Clustering {C_norm.shape[0]} vocal frames into phonetic retrieval index…",
                current_step=42,
                total_steps=100,
                epoch=0,
                total_epochs=total_epochs,
            ))
            index_keys, index_envs = _fit_phonetic_codebook(C_norm, S_matrix, num_clusters=96, iters=6)

            # 5. Genuine Mini-Batch Adam Neural Vocoder Training
            n_frames = C_norm.shape[0]
            rng = np.random.default_rng(1337)
            W1 = rng.normal(0.0, np.sqrt(2.0 / CONTENT_DIM), size=(CONTENT_DIM, HIDDEN_DIM)).astype(np.float32)
            b1 = np.zeros(HIDDEN_DIM, dtype=np.float32)
            W2 = rng.normal(0.0, np.sqrt(2.0 / HIDDEN_DIM), size=(HIDDEN_DIM, HIDDEN_DIM)).astype(np.float32)
            b2 = np.zeros(HIDDEN_DIM, dtype=np.float32)
            W3 = rng.normal(0.0, np.sqrt(1.0 / HIDDEN_DIM) * 0.25, size=(HIDDEN_DIM, SPEC_BINS)).astype(np.float32)
            # Initialize output bias to the target speaker's Long-Term Average Spectrum (LTAS)
            b3 = np.mean(S_matrix, axis=0).astype(np.float32)

            params = [W1, b1, W2, b2, W3, b3]
            m_adam = [np.zeros_like(p) for p in params]
            v_adam = [np.zeros_like(p) for p in params]
            lr = 0.003
            beta1 = 0.9
            beta2 = 0.999
            eps = 1e-8
            adam_t = 0
            batch_sz = max(16, min(128, int(cfg.batch_size) * 8))

            best_loss = 999.0
            best_weights = [p.copy() for p in params]

            for epoch in range(1, total_epochs + 1):
                if self._cancel_event.is_set():
                    self._emit(TrainingProgress(stage="cancelled", stage_description="Training cancelled by user"))
                    return

                perm = rng.permutation(n_frames)
                epoch_loss_sum = 0.0
                n_batches = 0

                for start_i in range(0, n_frames, batch_sz):
                    batch_idx = perm[start_i : start_i + batch_sz]
                    xb = C_norm[batch_idx]  # [B, 32]
                    yb = S_matrix[batch_idx]  # [B, 513]
                    bsz = float(xb.shape[0])

                    # Forward pass
                    z1 = xb @ W1 + b1
                    h1 = np.maximum(0.0, z1)
                    z2 = h1 @ W2 + b2
                    h2 = np.maximum(0.0, z2)
                    pred = h2 @ W3 + b3

                    diff = pred - yb
                    loss_val = float(np.mean(diff * diff))
                    epoch_loss_sum += loss_val
                    n_batches += 1

                    # Backward pass (MSE gradient)
                    d_pred = (2.0 / (bsz * SPEC_BINS)) * diff  # [B, 513]
                    gW3 = h2.T @ d_pred
                    gb3 = np.sum(d_pred, axis=0)

                    dh2 = d_pred @ W3.T
                    dz2 = dh2 * (z2 > 0.0)
                    gW2 = h1.T @ dz2
                    gb2 = np.sum(dz2, axis=0)

                    dh1 = dz2 @ W2.T
                    dz1 = dh1 * (z1 > 0.0)
                    gW1 = xb.T @ dz1
                    gb1 = np.sum(dz1, axis=0)

                    grads = [gW1, gb1, gW2, gb2, gW3, gb3]
                    adam_t += 1
                    b1_corr = 1.0 - (beta1 ** adam_t)
                    b2_corr = 1.0 - (beta2 ** adam_t)

                    for p_i, (param, grad) in enumerate(zip(params, grads)):
                        m_adam[p_i] = beta1 * m_adam[p_i] + (1.0 - beta1) * grad
                        v_adam[p_i] = beta2 * v_adam[p_i] + (1.0 - beta2) * (grad * grad)
                        m_hat = m_adam[p_i] / b1_corr
                        v_hat = v_adam[p_i] / b2_corr
                        param -= lr * m_hat / (np.sqrt(v_hat) + eps)

                curr_loss = epoch_loss_sum / max(1, n_batches)
                if curr_loss < best_loss:
                    best_loss = curr_loss
                    best_weights = [p.copy() for p in params]

                now = time.time()
                elapsed = now - start_time
                pct = epoch / total_epochs
                eta = (elapsed / max(0.001, pct)) * (1.0 - pct)
                step = int(45 + (pct * 47))

                self._emit(TrainingProgress(
                    stage="training",
                    stage_description=(
                        f"Epoch {epoch}/{total_epochs} ({n_frames} vocal frames)  ·  "
                        f"Loss: {curr_loss:.4f}  ·  ETA: {eta:.1f}s"
                    ),
                    current_step=step,
                    total_steps=100,
                    epoch=epoch,
                    total_epochs=total_epochs,
                    loss=curr_loss,
                    best_loss=best_loss,
                    elapsed_s=elapsed,
                    eta_s=eta,
                ))

                if n_frames < 120:
                    time.sleep(0.003)

            # 6. Export ONNX neural vocoder + .index codebook
            self._emit(TrainingProgress(
                stage="exporting",
                stage_description="Exporting trained ONNX neural vocoder graph and phonetic .index…",
                current_step=95,
                total_steps=100,
                epoch=total_epochs,
                total_epochs=total_epochs,
                loss=best_loss,
                best_loss=best_loss,
            ))

            clean_name = cfg.voice_name.strip() or "Custom Voice"
            stem = _slugify(clean_name)
            os.makedirs(self.models_dir, exist_ok=True)

            dest_onnx = os.path.join(self.models_dir, f"{stem}.onnx")
            dest_index = os.path.join(self.models_dir, f"{stem}.index")
            dest_json = os.path.join(self.models_dir, f"{stem}.json")

            # Compute natural pitch offset between average adult speaking pitch (~165 Hz) and target avg_f0
            pitch_shift_st = round(12.0 * math.log2(max(60.0, avg_f0) / 165.0), 1)
            pitch_shift_st = max(-12.0, min(12.0, pitch_shift_st))
            final_sub = max(float(cfg.sub_harmonic_depth), measured_sub)
            final_air = max(float(cfg.air_shimmer), measured_air)

            W1_b, b1_b, W2_b, b2_b, W3_b, b3_b = best_weights
            save_neural_onnx_model(
                dest_onnx,
                W1_b,
                b1_b,
                W2_b,
                b2_b,
                W3_b,
                b3_b,
                meta={
                    "voice_name": clean_name,
                    "sample_rate": slice_sr,
                    "frames_trained": n_frames,
                    "base_f0_hz": round(avg_f0, 1),
                    "best_loss": round(best_loss, 5),
                },
            )
            save_phonetic_index(dest_index, index_keys, index_envs)

            meta_info = {
                "name": clean_name,
                "description": (
                    f"Trained ONNX neural voice model ({clean_name}) · "
                    f"{n_frames} STFT frames, F0 {avg_f0:.0f} Hz, loss {best_loss:.4f}"
                ),
                "default_pitch": pitch_shift_st,
                "default_formant": round(float(cfg.vocal_tract_bias), 1),
                "default_index_rate": 85.0,
                "default_breathiness": round(final_air * 100.0, 1),
                "sub_harmonic": round(final_sub, 2),
                "shimmer": round(final_air, 2),
                "f0_method": cfg.f0_method,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
            }
            with open(dest_json, "w", encoding="utf-8") as fh:
                json.dump(meta_info, fh, indent=2)

            total_elapsed = time.time() - start_time
            self._emit(TrainingProgress(
                stage="completed",
                stage_description=(
                    f"Model '{clean_name}' trained on {n_frames} vocal frames "
                    f"(loss {best_loss:.4f}) in {total_elapsed:.1f}s!"
                ),
                current_step=100,
                total_steps=100,
                epoch=total_epochs,
                total_epochs=total_epochs,
                loss=best_loss,
                best_loss=best_loss,
                elapsed_s=total_elapsed,
                eta_s=0.0,
            ))

        except Exception as exc:
            self._emit(TrainingProgress(
                stage="error",
                stage_description="Training encountered an error",
                error_message=str(exc),
                elapsed_s=time.time() - start_time,
            ))
        finally:
            self._is_running = False
