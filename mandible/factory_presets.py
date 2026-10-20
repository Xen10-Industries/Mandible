"""Factory preset chains using built-in Mandible studio DSP effects.
These work out-of-the-box on any computer without any third-party plugins.
"""
from __future__ import annotations

import base64
import json
from .config import Chain, PluginSlot, _new_id


def _create_slot(path: str, display_name: str, params: dict[str, object]) -> PluginSlot:
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
            "name": "Broadcast Studio Polish",
            "desc": "Pristine parametric EQ curve, punchy optical compressor leveling, and subtle room ambiance.",
            "plugins": [
                ("internal:eq", "Parametric EQ", {"low_gain_db": 1.5, "mid_freq_hz": 800.0, "mid_gain_db": -1.5, "high_gain_db": 2.0}),
                ("internal:compressor", "Studio Compressor", {"threshold_db": -18.0, "ratio": 3.0, "attack_ms": 20.0, "release_ms": 120.0}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.15, "damping": 0.80, "wet_level": 0.08, "dry_level": 1.0, "width": 0.7}),
            ],
            "gain_db": 1.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_xen_overmind",
            "name": "Xen Overmind",
            "desc": "Ancient multidimensional entity: -4st pitch & -3.5st formant shift, sub-octave chest synthesizer, harmonic air exciter, and cosmic reverb.",
            "plugins": [
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": -4.0, "formant": -3.5, "preserve_formants": 1.0, "mix": 100.0}),
                ("internal:sub_exciter", "Sub-Harmonic & Exciter", {"sub_level": 35.0, "sub_freq_hz": 85.0, "air_exciter": 20.0, "mix": 100.0}),
                ("internal:distortion", "Tube Drive", {"drive_db": 4.5}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.65, "damping": 0.45, "wet_level": 0.22, "dry_level": 1.0, "width": 1.0}),
            ],
            "gain_db": 1.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_cyber_valkyrie",
            "name": "Cyber Valkyrie",
            "desc": "Bright, articulate raised vocal tract (+5st pitch / +4st formant) with high-frequency harmonic air exciter and optical leveling.",
            "plugins": [
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": 5.0, "formant": 4.0, "preserve_formants": 1.0, "mix": 100.0}),
                ("internal:sub_exciter", "Sub-Harmonic & Exciter", {"sub_level": 0.0, "sub_freq_hz": 85.0, "air_exciter": 30.0, "mix": 100.0}),
                ("internal:compressor", "Studio Compressor", {"threshold_db": -16.0, "ratio": 3.0, "attack_ms": 12.0, "release_ms": 90.0}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.25, "damping": 0.70, "wet_level": 0.12, "dry_level": 1.0, "width": 0.85}),
            ],
            "gain_db": 0.5,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_shadow_operative",
            "name": "Shadow Operative",
            "desc": "Covert low-formant voice mask (-3st pitch / -4.5st formant) with chest sub-harmonics and warm saturation for vocal anonymity.",
            "plugins": [
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": -3.0, "formant": -4.5, "preserve_formants": 1.0, "mix": 100.0}),
                ("internal:sub_exciter", "Sub-Harmonic & Exciter", {"sub_level": 22.0, "sub_freq_hz": 80.0, "air_exciter": 10.0, "mix": 100.0}),
                ("internal:eq", "Parametric EQ", {"low_gain_db": 2.5, "mid_freq_hz": 1200.0, "mid_gain_db": -2.0, "high_gain_db": 1.5}),
                ("internal:compressor", "Studio Compressor", {"threshold_db": -17.0, "ratio": 4.0, "attack_ms": 10.0, "release_ms": 100.0}),
            ],
            "gain_db": 1.5,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_titan_brute",
            "name": "Titan Brute",
            "desc": "Massive vocal tract enlargement (-7st pitch / -6st formant) with heavy sub-octave chest weight and gritty tube drive.",
            "plugins": [
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": -7.0, "formant": -6.0, "preserve_formants": 1.0, "mix": 100.0}),
                ("internal:sub_exciter", "Sub-Harmonic & Exciter", {"sub_level": 50.0, "sub_freq_hz": 72.0, "air_exciter": 12.0, "mix": 100.0}),
                ("internal:distortion", "Tube Drive", {"drive_db": 8.0}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.70, "damping": 0.40, "wet_level": 0.25, "dry_level": 1.0, "width": 1.0}),
            ],
            "gain_db": 0.5,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_ethereal_oracle",
            "name": "Ethereal Oracle",
            "desc": "Celestial harmonic-locked voice (+3st pitch / +2.5st formant) with airy shimmer exciter, LFO filter movement, and lush hall reverb.",
            "plugins": [
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": 3.0, "formant": 2.5, "preserve_formants": 1.0, "mix": 100.0}),
                ("internal:sub_exciter", "Sub-Harmonic & Exciter", {"sub_level": 0.0, "sub_freq_hz": 85.0, "air_exciter": 40.0, "mix": 100.0}),
                ("internal:chorus", "Vintage Chorus", {"rate_hz": 1.1, "depth": 0.55, "mix": 0.35}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.88, "damping": 0.25, "wet_level": 0.38, "dry_level": 1.0, "width": 1.0}),
            ],
            "gain_db": 0.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_radio_deep",
            "name": "Deep Radio Host",
            "desc": "Subtle -2st pitch drop with deepened chest formants, warm tube drive, and studio compressor leveling.",
            "plugins": [
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": -2.0, "formant": -3.0, "preserve_formants": 1.0, "mix": 100.0}),
                ("internal:compressor", "Studio Compressor", {"threshold_db": -16.0, "ratio": 3.5, "attack_ms": 15.0, "release_ms": 90.0}),
                ("internal:distortion", "Tube Drive", {"drive_db": 3.0}),
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
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": -8.0, "formant": -7.0, "preserve_formants": 0.0, "mix": 100.0}),
                ("internal:distortion", "Tube Drive", {"drive_db": 14.0}),
                ("internal:chorus", "Vintage Chorus", {"rate_hz": 0.8, "depth": 0.60, "mix": 0.40}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.85, "damping": 0.35, "wet_level": 0.40, "dry_level": 1.0, "width": 1.0}),
            ],
            "gain_db": 0.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_cyborg",
            "name": "Cybernetic Android",
            "desc": "Robotic metallic ring modulation with space phaser sweeps and lo-fi quantization.",
            "plugins": [
                ("internal:ring_mod", "Ring Modulator", {"freq_hz": 65.0, "depth": 0.85, "mix": 80.0}),
                ("internal:phaser", "Space Phaser", {"rate_hz": 0.8, "depth": 0.70, "feedback": 0.40, "mix": 0.45}),
                ("internal:bitcrush", "Lo-Fi Bitcrush", {"bit_depth": 10.0, "sample_rate": 24000.0, "mix": 70.0}),
            ],
            "gain_db": 1.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_anime_chipmunk",
            "name": "Anime / Chipmunk",
            "desc": "High pitch transposition with miniature vocal tract resonance, leveling, and light slapback delay.",
            "plugins": [
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": 7.0, "formant": 6.0, "preserve_formants": 0.0, "mix": 100.0}),
                ("internal:compressor", "Studio Compressor", {"threshold_db": -14.0, "ratio": 3.0, "attack_ms": 10.0, "release_ms": 80.0}),
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
                ("internal:bitcrush", "Lo-Fi Bitcrush", {"bit_depth": 6.0, "sample_rate": 16000.0, "mix": 100.0}),
            ],
            "gain_db": 2.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_interstellar_transmission",
            "name": "Interstellar Transmission",
            "desc": "Hypnotic space phaser, optical amplitude flutter, stereo tape delay, and cosmic space reflections.",
            "plugins": [
                ("internal:phaser", "Space Phaser", {"rate_hz": 0.5, "depth": 0.85, "feedback": 0.50, "mix": 0.60}),
                ("internal:tremolo", "Optical Tremolo", {"rate_hz": 5.2, "depth": 0.50}),
                ("internal:delay", "Stereo Delay", {"delay_seconds": 0.38, "feedback": 0.50, "mix": 0.35}),
                ("internal:reverb", "Studio Reverb", {"room_size": 0.88, "damping": 0.30, "wet_level": 0.38, "dry_level": 1.0, "width": 1.0}),
            ],
            "gain_db": 0.0,
            "dry_wet": 1.0,
        },
        {
            "id": "factory_space_vocaloid",
            "name": "Space Shimmer Vocal",
            "desc": "Octave shimmer with natural formant preservation, lush stereo chorus, and cosmic space reflections.",
            "plugins": [
                ("internal:pitch_formant", "Pitch & Formant", {"pitch": 12.0, "formant": 0.0, "preserve_formants": 1.0, "mix": 50.0}),
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
