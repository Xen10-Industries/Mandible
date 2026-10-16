"""Factory preset chains using built-in Mandible studio DSP effects.
These work out-of-the-box on any computer without any third-party plugins.
"""
from __future__ import annotations

import base64
import json
from .config import Chain, PluginSlot, _new_id


def _create_slot(path: str, display_name: str, params: dict[str, float]) -> PluginSlot:
    state_json = json.dumps(params).encode("utf-8")
    state_b64 = base64.b64encode(state_json).decode("ascii")
    return PluginSlot(
        path=path,
        display_name=display_name,
        enabled=True,
        state=state_b64,
    )


def get_factory_presets() -> list[dict]:
    """Returns metadata for all available factory preset voice chains."""
    return [
        {
            "id": "factory_broadcast",
            "name": "Broadcast Polish",
            "desc": "Studio vocal warmth, gentle presence filtering, and subtle room ambiance.",
            "plugins": [
                ("internal:filter", "Ladder Filter", {"cutoff_hz": 8500.0, "resonance": 0.08, "drive": 1.2}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.18, "damping": 0.75, "wet_level": 0.10, "dry_level": 1.0, "width": 0.8}),
            ],
            "gain_db": 1.5,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_radio_deep",
            "name": "Deep Radio Host",
            "desc": "Subtle -2st pitch drop with deepened chest formants, warm tube drive, and studio space.",
            "plugins": [
                ("internal:pitch_formant", "Mandible Pitch & Formant", {"pitch": -2.0, "formant": -3.0, "preserve_formants": 1.0, "mix": 100.0}),
                ("internal:distortion", "Tube Drive", {"drive_db": 4.0}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.25, "damping": 0.65, "wet_level": 0.12, "dry_level": 1.0, "width": 0.9}),
            ],
            "gain_db": 2.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_demon_monster",
            "name": "Demon / Monster",
            "desc": "Heavy octaved downshift, demonic vocal tract enlargement, gritty tube drive, and dark cave reverb.",
            "plugins": [
                ("internal:pitch_formant", "Mandible Pitch & Formant", {"pitch": -8.0, "formant": -7.0, "preserve_formants": 0.0, "mix": 100.0}),
                ("internal:distortion", "Tube Drive", {"drive_db": 14.0}),
                ("internal:chorus", "Vintage Chorus", {"rate_hz": 0.8, "depth": 0.60, "mix": 0.40}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.85, "damping": 0.35, "wet_level": 0.40, "dry_level": 1.0, "width": 1.0}),
            ],
            "gain_db": 0.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_anime_chipmunk",
            "name": "Anime / Chipmunk",
            "desc": "High pitch transposition with miniature vocal tract resonance and light slapback delay.",
            "plugins": [
                ("internal:pitch_formant", "Mandible Pitch & Formant", {"pitch": 7.0, "formant": 6.0, "preserve_formants": 0.0, "mix": 100.0}),
                ("internal:delay", "Stereo Delay", {"delay_seconds": 0.16, "feedback": 0.25, "mix": 0.22}),
            ],
            "gain_db": -1.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_walkie_talkie",
            "name": "Tactical Walkie-Talkie",
            "desc": "Authentic military cellular/radio codec, steep bandpass filtering, and gritty 6-bit quantization.",
            "plugins": [
                ("internal:gsm", "Tactical GSM Radio", {}),
                ("internal:filter", "Ladder Filter", {"cutoff_hz": 2600.0, "resonance": 0.45, "drive": 2.5}),
                ("internal:bitcrush", "Lo-Fi Bitcrush", {"bit_depth": 6.0}),
            ],
            "gain_db": 2.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_space_vocaloid",
            "name": "Space Shimmer Vocal",
            "desc": "Octave shimmer with natural formant preservation, lush stereo chorus, and cosmic space reflections.",
            "plugins": [
                ("internal:pitch_formant", "Mandible Pitch & Formant", {"pitch": 12.0, "formant": 0.0, "preserve_formants": 1.0, "mix": 50.0}),
                ("internal:chorus", "Vintage Chorus", {"rate_hz": 1.4, "depth": 0.70, "mix": 0.45}),
                ("internal:delay", "Stereo Delay", {"delay_seconds": 0.32, "feedback": 0.45, "mix": 0.30}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.90, "damping": 0.25, "wet_level": 0.45, "dry_level": 1.0, "width": 1.0}),
            ],
            "gain_db": 0.0,
            "dry_wet": 1.0,
        },
    ]


def instantiate_factory_preset(preset_dict: dict) -> Chain:
    """Instantiate a new Chain object from a factory preset definition."""
    slots = []
    for path, name, params in preset_dict["plugins"]:
        slots.append(_create_slot(path, name, params))

    return Chain(
        id=_new_id(),
        name=preset_dict["name"],
        mode="toggle",
        gain_db=float(preset_dict.get("gain_db", 0.0)),
        dry_wet=float(preset_dict.get("dry_wet", 1.0)),
        plugins=slots,
    )
