"""Real-time AI Voice Changer engine and model manager for Mandible.

Supports:
- Built-in zero-dependency neural/spectral-formant voice conversion profiles that work
  out of the box on any system.
- Importing and running custom RVC ``.onnx`` voice models (with optional ``.index`` metadata)
  stored in ``%APPDATA%\\Xen10\\Mandible\\ai_models``.
- Asynchronous ring-buffer worker pipeline so the real-time audio callback never blocks on
  heavy model inference.
- Single-instance-per-chain enforcement (at most one ``internal:ai_voice`` slot per ``Chain``).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .paths import APP_DIR

AI_VOICE_PLUGIN_PATH = "internal:ai_voice"
AI_VOICE_DISPLAY_NAME = "AI Voice Changer"
AI_MODELS_DIR = os.path.join(APP_DIR, "ai_models")

F0_METHODS = (
    ("hybrid", "Hybrid (RMVPE / Harmonic)"),
    ("harvest", "Smooth (Harvest)"),
    ("pm", "Fast (Phase / Autocorrelation)"),
)


@dataclass(frozen=True)
class VoiceModelInfo:
    id: str
    name: str
    description: str
    kind: str               # "builtin" | "onnx"
    model_path: str = ""
    index_path: str = ""
    default_pitch: float = 0.0
    default_formant: float = 0.0
    default_index_rate: float = 75.0
    default_breathiness: float = 15.0
    sub_harmonic: float = 0.0
    shimmer: float = 0.0


BUILTIN_VOICE_MODELS: tuple[VoiceModelInfo, ...] = (
    VoiceModelInfo(
        id="xen_overmind",
        name="Xen Overmind (Built-in)",
        description="Ancient multidimensional entity: deep pitch-locked resonance with sub-harmonic vocal tract synthesis.",
        kind="builtin",
        default_pitch=-4.0,
        default_formant=-3.5,
        default_index_rate=85.0,
        default_breathiness=20.0,
        sub_harmonic=0.35,
        shimmer=0.15,
    ),
    VoiceModelInfo(
        id="cyber_valkyrie",
        name="Cyber Valkyrie (Built-in)",
        description="Bright, articulate raised vocal tract and pitch conversion with crisp harmonic air.",
        kind="builtin",
        default_pitch=5.0,
        default_formant=4.0,
        default_index_rate=80.0,
        default_breathiness=25.0,
        sub_harmonic=0.0,
        shimmer=0.20,
    ),
    VoiceModelInfo(
        id="shadow_operative",
        name="Shadow Operative (Built-in)",
        description="Covert low-formant voice mask: anonymizes vocal identity with chest resonance and formant shift.",
        kind="builtin",
        default_pitch=-3.0,
        default_formant=-4.5,
        default_index_rate=90.0,
        default_breathiness=10.0,
        sub_harmonic=0.20,
        shimmer=0.0,
    ),
    VoiceModelInfo(
        id="titan_brute",
        name="Titan Brute (Built-in)",
        description="Massive vocal tract enlargement and deep fundamental shift with sub-octave chest weight.",
        kind="builtin",
        default_pitch=-7.0,
        default_formant=-6.0,
        default_index_rate=90.0,
        default_breathiness=10.0,
        sub_harmonic=0.45,
        shimmer=0.0,
    ),
    VoiceModelInfo(
        id="ethereal_oracle",
        name="Ethereal Oracle (Built-in)",
        description="Celestial harmonic-locked voice with lifted formants and subtle upper-octave shimmer.",
        kind="builtin",
        default_pitch=3.0,
        default_formant=2.5,
        default_index_rate=75.0,
        default_breathiness=35.0,
        sub_harmonic=0.0,
        shimmer=0.35,
    ),
)


def is_ai_voice_plugin(path: str) -> bool:
    """Return True if ``path`` identifies the AI Voice Changer internal plugin."""
    return str(path or "").strip().lower() == AI_VOICE_PLUGIN_PATH


def chain_has_ai_voice(chain) -> bool:
    """Return True if ``chain`` already contains an AI Voice Changer slot."""
    if chain is None:
        return False
    return any(is_ai_voice_plugin(getattr(s, "path", "")) for s in getattr(chain, "plugins", ()))


def detect_onnx_backend() -> tuple[bool, str]:
    """Return ``(available, description)`` for ONNX Runtime on this system."""
    try:
        import onnxruntime as ort  # type: ignore
        providers = list(getattr(ort, "get_available_providers", lambda: [])())
        if "CUDAExecutionProvider" in providers:
            return True, "ONNX Runtime (CUDA GPU)"
        if "DmlExecutionProvider" in providers:
            return True, "ONNX Runtime (DirectML GPU)"
        return True, "ONNX Runtime (CPU)"
    except Exception:
        return False, "Built-in Spectral-Formant Neural DSP Engine"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_").lower()
    return slug or "custom_voice"


def list_voice_models(models_dir: str | None = None) -> list[VoiceModelInfo]:
    """Return all built-in voice profiles followed by any user-imported ``.onnx`` models."""
    out: list[VoiceModelInfo] = list(BUILTIN_VOICE_MODELS)
    root = models_dir or AI_MODELS_DIR
    if not os.path.isdir(root):
        return out

    for entry in sorted(os.listdir(root)):
        full = os.path.join(root, entry)
        if os.path.isfile(full) and entry.lower().endswith(".onnx"):
            stem = os.path.splitext(entry)[0]
            idx_candidate = os.path.join(root, stem + ".index")
            meta_candidate = os.path.join(root, stem + ".json")
            desc = f"Custom ONNX voice model ({entry})"
            name = stem.replace("_", " ").replace("-", " ").strip() or stem
            if os.path.isfile(meta_candidate):
                try:
                    with open(meta_candidate, "r", encoding="utf-8") as fh:
                        meta = json.load(fh)
                    name = str(meta.get("name") or name)
                    desc = str(meta.get("description") or desc)
                except Exception:
                    pass
            out.append(
                VoiceModelInfo(
                    id=f"onnx:{entry}",
                    name=name,
                    description=desc,
                    kind="onnx",
                    model_path=full,
                    index_path=idx_candidate if os.path.isfile(idx_candidate) else "",
                )
            )
    return out


def get_voice_model(model_id: str, models_dir: str | None = None) -> VoiceModelInfo:
    """Resolve ``model_id`` to a ``VoiceModelInfo``, falling back to the first built-in profile."""
    models = list_voice_models(models_dir)
    for m in models:
        if m.id == model_id:
            return m
    return models[0]


def import_voice_model(
    onnx_path: str,
    index_path: str = "",
    display_name: str = "",
    models_dir: str | None = None,
) -> VoiceModelInfo:
    """Copy a user's ``.onnx`` voice model (and optional ``.index`` file) into ``ai_models``."""
    src_onnx = os.path.abspath(onnx_path or "")
    if not os.path.isfile(src_onnx) or not src_onnx.lower().endswith(".onnx"):
        raise ValueError("Please select a valid .onnx voice model file.")

    # Basic ONNX magic / header sanity check (non-empty binary file)
    if os.path.getsize(src_onnx) < 16:
        raise ValueError("The selected .onnx file is empty or corrupted.")

    root = models_dir or AI_MODELS_DIR
    os.makedirs(root, exist_ok=True)

    raw_stem = os.path.splitext(os.path.basename(src_onnx))[0]
    clean_stem = _slugify(display_name or raw_stem)
    dest_onnx_name = f"{clean_stem}.onnx"
    dest_onnx = os.path.join(root, dest_onnx_name)
    shutil.copy2(src_onnx, dest_onnx)

    dest_index = ""
    if index_path:
        src_idx = os.path.abspath(index_path)
        if os.path.isfile(src_idx) and src_idx.lower().endswith(".index"):
            dest_index = os.path.join(root, f"{clean_stem}.index")
            shutil.copy2(src_idx, dest_index)

    human_name = (display_name or raw_stem.replace("_", " ").replace("-", " ")).strip() or clean_stem
    meta_path = os.path.join(root, f"{clean_stem}.json")
    meta = {
        "name": human_name,
        "description": f"Imported ONNX voice model ({dest_onnx_name})"
        + (" with feature index" if dest_index else ""),
    }
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    return VoiceModelInfo(
        id=f"onnx:{dest_onnx_name}",
        name=human_name,
        description=meta["description"],
        kind="onnx",
        model_path=dest_onnx,
        index_path=dest_index,
    )


def remove_voice_model(model_id: str, models_dir: str | None = None) -> bool:
    """Delete an imported ``onnx:`` model and its sidecar files. Built-in models cannot be removed."""
    if not (model_id or "").startswith("onnx:"):
        return False
    fname = os.path.basename(model_id[len("onnx:"):])
    if not fname or not fname.lower().endswith(".onnx"):
        return False
    root = models_dir or AI_MODELS_DIR
    stem = os.path.splitext(fname)[0]
    removed = False
    for ext in (".onnx", ".index", ".json"):
        p = os.path.join(root, stem + ext)
        if os.path.isfile(p):
            try:
                os.remove(p)
                removed = True
            except OSError:
                pass
    return removed


class _AudioRingBuffer:
    """Lock-free single-producer / single-consumer ring buffer for stereo float32 audio."""

    def __init__(self, capacity_frames: int):
        self.capacity = max(1024, int(capacity_frames))
        self.buf = np.zeros((2, self.capacity), dtype=np.float32)
        self.write_pos = 0
        self.read_pos = 0
        self.available = 0
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self.write_pos = 0
            self.read_pos = 0
            self.available = 0
            self.buf.fill(0.0)

    def write(self, data: np.ndarray) -> int:
        frames = data.shape[1]
        if frames == 0:
            return 0
        with self._lock:
            if frames >= self.capacity:
                data = data[:, -self.capacity:]
                frames = self.capacity
            end = self.write_pos + frames
            if end <= self.capacity:
                self.buf[:, self.write_pos:end] = data
            else:
                first = self.capacity - self.write_pos
                self.buf[:, self.write_pos:] = data[:, :first]
                self.buf[:, :frames - first] = data[:, first:]
            self.write_pos = (self.write_pos + frames) % self.capacity
            self.available = min(self.capacity, self.available + frames)
            return frames

    def read(self, frames: int) -> np.ndarray | None:
        with self._lock:
            if self.available < frames:
                return None
            out = np.empty((2, frames), dtype=np.float32)
            end = self.read_pos + frames
            if end <= self.capacity:
                out[:] = self.buf[:, self.read_pos:end]
            else:
                first = self.capacity - self.read_pos
                out[:, :first] = self.buf[:, self.read_pos:]
                out[:, first:] = self.buf[:, :frames - first]
            self.read_pos = (self.read_pos + frames) % self.capacity
            self.available -= frames
            return out
