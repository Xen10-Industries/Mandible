"""A representative Core for screenshots and layout checks (four chains, three clips).

Shared by ``tests/conftest.py`` and ``tools/ui_gallery.py`` so there is one definition.
Isolating %APPDATA% before importing ``mandible`` is the caller's job.
"""
from __future__ import annotations

from ..config import AppConfig, SoundboardClipConfig
from ..core import Core

SAMPLE_CHAINS: dict[str, tuple[str, list[str]]] = {
    "Robot Voice": ("toggle", ["internal:pitch_formant", "internal:gsm", "internal:reverb"]),
    "Deep Narrator": ("hold", ["internal:pitch_formant", "internal:reverb"]),
    "Walkie-Talkie": ("toggle", ["internal:gsm", "internal:filter"]),
    "Cave Echo": ("toggle", ["internal:reverb", "internal:delay"]),
}
SAMPLE_CLIPS = ("Airhorn", "Rimshot", "Sad trombone")


def build_sample_core(cfg: AppConfig | None = None) -> Core:
    """A Core (audio never auto-started) holding the sample chains and soundboard clips."""
    cfg = cfg if cfg is not None else AppConfig()
    cfg.autostart_audio = False
    core = Core(cfg)
    for name, (mode, paths) in SAMPLE_CHAINS.items():
        chain = core.add_chain(name)
        chain.mode = mode
        for path in paths:
            core.add_plugin(chain, path)
    for clip_name in SAMPLE_CLIPS:
        core.cfg.soundboard.append(SoundboardClipConfig(name=clip_name, path=""))
    return core
