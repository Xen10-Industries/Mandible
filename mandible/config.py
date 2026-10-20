"""Configuration model and JSON persistence for Mandible."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, fields

from .prefx import PreFXSettings

from .paths import APP_DIR

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_APP_NAME = "Mandible"
PRESET_FORMAT = "Mandible.Preset"
PRESET_EXT = ".mandible"
LEGACY_PRESET_EXT = ".vfxpreset"  # presets exported by pre-release VoiceFX builds; still importable


def resource_path(*parts: str) -> str:
    """Resolve bundled resource paths for both source checkouts and frozen PyInstaller builds."""
    import sys
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(meipass, *parts))
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, *parts))
        candidates.append(os.path.join(exe_dir, "_internal", *parts))
    # Package parent directory (repo root) and package directory itself
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(pkg_dir)
    candidates.append(os.path.join(repo_dir, *parts))
    candidates.append(os.path.join(pkg_dir, *parts))
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0] if candidates else os.path.join(*parts)


def is_startup_enabled() -> bool:
    """Check whether Mandible is registered in HKCU Run at Windows startup."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, STARTUP_APP_NAME)
            return bool(val)
    except Exception:
        return False


def set_startup_enabled(enabled: bool, start_minimized: bool = False) -> bool:
    """Add or remove Mandible from HKCU Run at Windows startup."""
    try:
        import sys
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                    interp = pyw if os.path.isfile(pyw) else sys.executable
                    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    cmd = f'"{interp}" -m mandible'
                    # If launched via Mandible.bat in repo root, prefer that for non-frozen dev
                    bat = os.path.join(repo_dir, "Mandible.bat")
                    if os.path.isfile(bat):
                        cmd = f'"{bat}"'
                if start_minimized:
                    cmd += " --minimized"
                winreg.SetValueEx(key, STARTUP_APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as exc:
        print(f"[Mandible] could not update Windows startup registry: {exc}")
        return False


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Hotkey:
    """A global hotkey: optional modifiers + one main key identified by scan code."""
    mods: list[str] = field(default_factory=list)   # subset of ctrl/shift/alt/windows
    scan_code: int = 0
    keypad: bool = False
    label: str = ""

    def is_set(self) -> bool:
        return self.scan_code > 0


@dataclass
class PluginSlot:
    path: str = ""
    plugin_name: str = ""      # needed for multi-plugin files such as WaveShell
    display_name: str = ""
    enabled: bool = True
    state: str = ""            # base64 of the plugin's raw VST3 state
    bypass_hotkey: Hotkey = field(default_factory=Hotkey)
    mapped_params: list[str] | None = None  # optional per-slot override; None uses global plugin mapping or auto-map
    macros_collapsed: bool = False          # if True, hides the 2U macro knob drawer and stays compact 1U


@dataclass
class Chain:
    name: str = "New Chain"
    hotkey: Hotkey = field(default_factory=Hotkey)
    mode: str = "toggle"       # "toggle" | "hold"
    gain_db: float = 0.0
    tail_s: float = 2.0        # how long the chain keeps ringing after it is switched off
    dry_wet: float = 1.0       # 0.0 (100% dry) to 1.0 (100% wet)
    stackable: bool = False    # if True, this chain can be active simultaneously with other chains
    plugins: list[PluginSlot] = field(default_factory=list)
    id: str = field(default_factory=_new_id)


@dataclass
class AudioSettings:
    driver: str = ""           # PortAudio host API name, e.g. "ASIO" / "Windows WASAPI"
    input_device: str = ""
    output_device: str = ""    # ignored for ASIO (same device is used for in/out)
    input_channel: int = 0     # 0-based
    output_channels: list[int] = field(default_factory=lambda: [2, 3])  # 0-based L/R
    monitor_channels: list[int] = field(default_factory=lambda: [0, 1]) # 0-based L/R (e.g. Headphones / Output 1-2)
    monitor_device: str = ""   # used for WASAPI if separate device
    samplerate: int = 0        # 0 = device default
    blocksize: int = 128
    wasapi_exclusive: bool = False


@dataclass
class LimiterSettings:
    enabled: bool = True
    threshold_db: float = -0.5
    release_ms: float = 50.0
    # False: transparent safety limiter (mandible.limiter). True: the louder pedalboard/JUCE
    # limiter (about +4 dB on quiet speech, compresses loud speech), the pre-0.1.2 behaviour.
    boost: bool = False


@dataclass
class PushToTalkSettings:
    mode: str = "disabled"     # "disabled" | "push_to_talk" | "push_to_mute"
    hotkey: Hotkey = field(default_factory=Hotkey)


@dataclass
class MidiBinding:
    device_name: str = ""
    event_type: str = "note_on"  # "note_on" | "cc"
    note_or_cc: int = 0
    channel: int = 0             # 0-15 (0 = omni/all)
    action: str = ""             # "chain:<id>" | "soundboard:<id>" | "panic" | "mute" | "monitor_vol" | "out_vol" | "in_vol"


@dataclass
class SoundboardClipConfig:
    id: str = field(default_factory=_new_id)
    name: str = "Sound Clip"
    path: str = ""
    hotkey: Hotkey = field(default_factory=Hotkey)
    volume_db: float = 0.0
    loop: bool = False
    route_output: bool = True
    route_monitor: bool = True
    trim_start_s: float = 0.0
    trim_end_s: float = 0.0  # 0.0 means full clip length


@dataclass
class OverlaySettings:
    enabled: bool = False
    position: str = "top-right"  # "top-left" | "top-right" | "bottom-left" | "bottom-right"
    opacity: float = 0.85
    hide_when_clean: bool = False


@dataclass
class AppConfig:
    audio: AudioSettings = field(default_factory=AudioSettings)
    prefx: PreFXSettings = field(default_factory=PreFXSettings)
    limiter: LimiterSettings = field(default_factory=LimiterSettings)
    ptt: PushToTalkSettings = field(default_factory=PushToTalkSettings)
    soundboard: list[SoundboardClipConfig] = field(default_factory=list)
    midi_device: str = ""
    midi_bindings: list[MidiBinding] = field(default_factory=list)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    chains: list[Chain] = field(default_factory=list)
    input_gain_db: float = 0.0
    output_gain_db: float = 0.0
    monitor_enabled: bool = False
    monitor_gain_db: float = 0.0
    headphone_monitor_mode: str = "processed"  # "processed" | "dry" | "mix"
    keep_chains_awake: bool = True             # pre-warm inactive chains with silence to prevent VST suspension
    crossfade_ms: float = 15.0                 # transition ramp between chains
    idle_mode: str = "dry"                     # "dry" | "mute" | <chain id>
    panic_hotkey: Hotkey = field(default_factory=Hotkey)
    hotkeys_enabled: bool = True
    autostart_audio: bool = True
    close_to_tray: bool = True
    start_minimized: bool = False
    launch_at_startup: bool = False
    ui_skin: str = "skeuomorphic"              # "skeuomorphic" | "vintage" | "minimal"
    chassis_frame: str = "auto"                # "auto" | "metal_rack" | "wood_cheeks" | "frameless"
    theme: str = "scarlet"                     # "scarlet" | "cyan" | "stealth" | "amber"
    switch_style: str = "bat_toggle"           # "bat_toggle" | "rocker"
    appearance_migrated: bool = False          # old frame/switch settings already baked into a user skin
    soundboard_ducking_enabled: bool = False   # duck mic input when soundboard plays
    soundboard_duck_db: float = -12.0          # dB attenuation during soundboard playback
    normalizer_enabled: bool = False           # output loudness normalizer
    normalizer_target_db: float = -14.0        # target RMS level for normalizer
    api_enabled: bool = False                  # local HTTP API for Stream Deck / OBS
    api_port: int = 38420                      # local API port
    extra_plugin_dirs: list[str] = field(default_factory=list)
    plugin_param_mappings: dict[str, list[str]] = field(default_factory=dict)
    left_panel_width: int = 300                # main window preset panel (splitter), 240..420 px
    auto_check_updates: bool = True            # background GitHub Releases check on startup
    check_prereleases: bool = True             # include pre-release tags in update checks
    last_update_check: float = 0.0             # epoch timestamp of last background check


# ---------------------------------------------------------------- (de)serialisation

def _to_dict(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {f.name: _to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]
    return obj


def _from_dict(cls, data):
    if not isinstance(data, dict):
        return cls()
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        v = data[f.name]
        if f.name in ("hotkey", "panic_hotkey", "bypass_hotkey"):
            v = _from_dict(Hotkey, v)
        elif f.name == "audio":
            v = _from_dict(AudioSettings, v)
        elif f.name == "prefx":
            v = _from_dict(PreFXSettings, v)
        elif f.name == "limiter":
            v = _from_dict(LimiterSettings, v)
        elif f.name == "ptt":
            v = _from_dict(PushToTalkSettings, v)
        elif f.name == "overlay":
            v = _from_dict(OverlaySettings, v)
        elif f.name == "chains":
            v = [_from_dict(Chain, c) for c in (v or [])]
        elif f.name == "plugins":
            raw_slots = [_from_dict(PluginSlot, p) for p in (v or [])]
            seen_ai = False
            v = []
            for s in raw_slots:
                if str(s.path or "").strip().lower() == "internal:ai_voice":
                    if seen_ai:
                        continue
                    seen_ai = True
                v.append(s)
        elif f.name == "soundboard":
            v = [_from_dict(SoundboardClipConfig, s) for s in (v or [])]
        elif f.name == "midi_bindings":
            v = [_from_dict(MidiBinding, m) for m in (v or [])]
        elif f.name == "plugin_param_mappings":
            v = dict(v) if isinstance(v, dict) else {}
        kwargs[f.name] = v
    return cls(**kwargs)


def export_chain_preset(chain: Chain, cfg: AppConfig, file_path: str) -> None:
    """Export a single voice preset chain (including VST states and mapped macro knobs) to JSON."""
    from . import plugins as P
    mappings = {}
    for s in chain.plugins:
        mkey = P.plugin_mapping_key(s)
        if cfg.plugin_param_mappings and mkey in cfg.plugin_param_mappings:
            mappings[mkey] = cfg.plugin_param_mappings[mkey]
    payload = {
        "format": PRESET_FORMAT,
        "version": 1,
        "chain": _to_dict(chain),
        "plugin_param_mappings": mappings,
    }
    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def import_chain_preset(file_path: str, cfg: AppConfig) -> Chain:
    """Import a voice preset chain from a .mandible (or legacy .vfxpreset) JSON file and merge its macro mappings."""
    with open(file_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    chain_data = data.get("chain", data) if isinstance(data, dict) else {}
    chain = _from_dict(Chain, chain_data)
    chain.id = _new_id()
    # Clear hotkeys if they conflict or let Core check conflicts
    mappings = data.get("plugin_param_mappings", {}) if isinstance(data, dict) else {}
    if isinstance(mappings, dict):
        if cfg.plugin_param_mappings is None:
            cfg.plugin_param_mappings = {}
        for k, v in mappings.items():
            if isinstance(v, list) and k not in cfg.plugin_param_mappings:
                cfg.plugin_param_mappings[k] = [str(x) for x in v]
    return chain


def load_config() -> AppConfig:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return _from_dict(AppConfig, json.load(fh))
    except FileNotFoundError:
        return AppConfig()
    except Exception as exc:  # corrupt file: keep a backup and start fresh
        try:
            os.replace(CONFIG_PATH, CONFIG_PATH + ".broken")
        except OSError:
            pass
        print(f"[Mandible] could not read config ({exc}); starting with defaults")
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_to_dict(cfg), fh, indent=2)
    os.replace(tmp, CONFIG_PATH)

