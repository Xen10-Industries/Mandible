"""VST3 discovery, caching, loading, latency querying, and state persistence (via Spotify's pedalboard)."""
from __future__ import annotations

import base64
import json
import os

import pedalboard

from .config import APP_DIR, Chain, PluginSlot
from .internal_dsp import (InternalParameter, get_internal_plugin_catalog, is_internal_plugin,
                           load_internal_plugin)

CACHE_PATH = os.path.join(APP_DIR, "plugin_cache.json")


def default_vst3_dirs() -> list[str]:
    dirs = []
    cpf = os.environ.get("CommonProgramFiles")
    if cpf:
        dirs.append(os.path.join(cpf, "VST3"))
    lad = os.environ.get("LOCALAPPDATA")
    if lad:
        dirs.append(os.path.join(lad, "Programs", "Common", "VST3"))
    return dirs


def resolve_plugin_path(path: str) -> str:
    """If path is a VST3 bundle directory, resolve to the inner binary."""
    if os.path.isdir(path):
        candidate = os.path.join(path, "Contents", "x86_64-win", os.path.basename(path))
        if os.path.isfile(candidate):
            return candidate
        win_dir = os.path.join(path, "Contents", "x86_64-win")
        if os.path.isdir(win_dir):
            for f in os.listdir(win_dir):
                if f.lower().endswith(".vst3"):
                    return os.path.join(win_dir, f)
    return path


def scan_vst3(extra_dirs: list[str] | None = None) -> list[tuple[str, str]]:
    """Fast scan by filename only. Returns [(name, path)]."""
    found: dict[str, str] = {}
    for root_dir in default_vst3_dirs() + list(extra_dirs or []):
        if not os.path.isdir(root_dir):
            continue
        for root, dirnames, filenames in os.walk(root_dir):
            for d in list(dirnames):
                if d.lower().endswith(".vst3"):
                    found.setdefault(os.path.join(root, d).lower(), os.path.join(root, d))
                    dirnames.remove(d)  # don't descend into bundles
            for f in filenames:
                if f.lower().endswith(".vst3"):
                    p = os.path.join(root, f)
                    found.setdefault(p.lower(), p)
    items = [(os.path.splitext(os.path.basename(p))[0], p) for p in found.values()]
    items.sort(key=lambda t: t[0].lower())
    return items


def load_plugin_cache() -> dict[str, dict]:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {item["path"]: item for item in data}
    except Exception:
        return {}


def save_plugin_cache(items: list[dict]):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
    except Exception as exc:
        print(f"[Mandible] could not save plugin cache: {exc}")


def set_favorite(path: str, favorite: bool) -> bool:
    """Mark the cached plugin at ``path`` as a favorite (or not). False if it isn't cached."""
    items = list(load_plugin_cache().values())
    for item in items:
        if item["path"] == path:
            item["favorite"] = bool(favorite)
            save_plugin_cache(items)
            return True
    return False


def get_cached_plugins(extra_dirs: list[str] | None = None, force_rescan: bool = False) -> list[dict]:
    """Returns detailed plugin list with caching, vendor detection, and favorites.
    ``force_rescan`` re-reads every plugin's details but keeps the user's favorites."""
    existing_cache = load_plugin_cache()
    scanned = scan_vst3(extra_dirs)
    results = []

    # Built-in studio DSP effects appear at the top
    for item in get_internal_plugin_catalog():
        fav = existing_cache.get(item["path"], {}).get("favorite", item["favorite"])
        results.append({
            "name": item["name"],
            "path": item["path"],
            "vendor": item["vendor"],
            "favorite": fav,
        })

    for name, path in scanned:
        if path in existing_cache and not force_rescan:
            results.append(existing_cache[path])
        else:
            # Extract vendor from directory structure if possible (e.g. VST3/Vendor/Plugin.vst3)
            parts = os.path.normpath(path).split(os.sep)
            vendor = ""
            if len(parts) >= 3 and parts[-2].lower() != "vst3" and not parts[-2].lower().endswith(".vst3"):
                vendor = parts[-2]
            item = {
                "name": name,
                "path": path,
                "vendor": vendor,
                "favorite": existing_cache.get(path, {}).get("favorite", False),
            }
            results.append(item)

    save_plugin_cache(results)
    return results


def plugin_names_in_file(path: str) -> list[str]:
    try:
        return list(pedalboard.VST3Plugin.get_plugin_names_for_file(resolve_plugin_path(path)))
    except Exception:
        return []


def load_slot(slot: PluginSlot):
    """Instantiate the plugin for a slot and restore its saved state."""
    if is_internal_plugin(slot.path):
        plugin = load_internal_plugin(slot.path)
        plugin._params_cache = plugin.parameters
        plugin._factory_defaults = {k: float(v.raw_value) for k, v in plugin.parameters.items()}
        if slot.state:
            try:
                plugin.raw_state = base64.b64decode(slot.state)
            except Exception as exc:
                print(f"[Mandible] could not restore internal state for {slot.display_name}: {exc}")
        if not slot.display_name:
            slot.display_name = getattr(plugin, "name", "")
        return plugin

    resolved = resolve_plugin_path(slot.path)
    plugin = pedalboard.load_plugin(resolved, plugin_name=slot.plugin_name or None)
    # Cache parameter dictionary wrapper on the plugin instance for <0.05ms lookups
    try:
        params_dict = plugin.parameters
        plugin._params_cache = params_dict
        # If compact plugin, snapshot factory default raw_values before restoring state
        if len(params_dict) <= 64:
            plugin._factory_defaults = {k: float(v.raw_value) for k, v in params_dict.items()}
        else:
            plugin._factory_defaults = {}
    except Exception:
        plugin._params_cache = {}
        plugin._factory_defaults = {}

    if slot.state:
        try:
            plugin.raw_state = base64.b64decode(slot.state)
        except Exception as exc:
            print(f"[Mandible] could not restore state for {slot.display_name}: {exc}")
    if not slot.display_name:
        slot.display_name = getattr(plugin, "name", "") or os.path.basename(slot.path)
    return plugin


def get_plugin_params_dict(plugin) -> dict:
    """Return cached parameters dict for a loaded VST3 plugin instance."""
    if plugin is None:
        return {}
    cached = getattr(plugin, "_params_cache", None)
    if cached is not None:
        return cached
    try:
        cached = plugin.parameters
        plugin._params_cache = cached
        return cached
    except Exception:
        return {}


def plugin_mapping_key(slot: PluginSlot) -> str:
    """Normalized key used to persist parameter knob mappings across all chains/presets."""
    norm_path = os.path.normcase(os.path.normpath(slot.path or ""))
    if slot.plugin_name:
        return f"{norm_path}::{slot.plugin_name.strip().lower()}"
    return norm_path


def is_usable_parameter(key: str, param) -> bool:
    """Filter out internal bypass or non-functional dummy MIDI parameters."""
    kl = key.strip().lower()
    nl = str(getattr(param, "name", "") or "").strip().lower()
    if kl == "bypass" or nl == "bypass":
        return False
    if kl == "midi" or nl == "midi":
        return False
    # Check for dummy empty string parameters with no numeric range
    if getattr(param, "min_value", None) is None and getattr(param, "max_value", None) is None:
        sv = str(getattr(param, "string_value", "") or "").strip()
        if sv == "":
            return False
    return True


def is_boolean_parameter(param) -> bool:
    """Return True if the parameter is a simple On/Off boolean toggle."""
    if getattr(param, "type", None) is bool:
        return True
    if isinstance(getattr(param, "min_value", None), bool):
        return True
    return False


def get_usable_parameters(plugin) -> list[tuple[str, object]]:
    """Return all user-controllable parameters as [(key, param_obj)]."""
    params = get_plugin_params_dict(plugin)
    return [(k, v) for k, v in params.items() if is_usable_parameter(k, v)]


def _score_parameter(key: str, param, index: int) -> float:
    """Heuristic score for selecting the most useful studio controls as macro knobs."""
    kl = key.lower()
    nl = str(getattr(param, "name", "") or "").lower()
    text = f"{kl} {nl}"
    score = 100.0 - index * 0.25  # preserve natural order as tie-breaker

    if is_boolean_parameter(param):
        score -= 60.0
    if "bypass" in text or "enable" in text or "solo" in text or "mute" in text:
        score -= 50.0
    if "denominator" in text or "steps" in text or "sync_mode" in text or "look_ahead" in text:
        score -= 30.0

    # High-priority vocal & studio FX controls
    priority_terms = [
        ("macro", 45.0),
        ("threshold", 40.0),
        ("thresh", 40.0),
        ("ratio", 38.0),
        ("mix", 38.0),
        ("dry_wet", 38.0),
        ("wet", 34.0),
        ("attack", 35.0),
        ("release", 35.0),
        ("decay", 35.0),
        ("size", 34.0),
        ("delay_time_seconds", 36.0),
        ("delay", 30.0),
        ("feedback", 34.0),
        ("makeup", 34.0),
        ("gain", 32.0),
        ("output", 28.0),
        ("level", 28.0),
        ("drive", 30.0),
        ("amount", 30.0),
        ("depth", 28.0),
        ("rate", 28.0),
        ("tone", 28.0),
        ("dampen", 28.0),
        ("width", 26.0),
        ("early", 24.0),
        ("hold", 26.0),
        ("range", 25.0),
        ("tolerance", 24.0),
        ("pan", 22.0),
        ("duck", 24.0),
        ("freq", 22.0),
        ("parameter_", 30.0),
    ]
    for term, boost in priority_terms:
        if term in text:
            score += boost
            break
    return score


def get_auto_mapped_params(plugin, max_auto_total: int = 12, max_knobs: int = 6) -> list[str]:
    """
    Automatically expose parameters as knobs ONLY if the plugin has <= max_auto_total
    usable parameters (e.g. compact compressors, gates, reverbs, delays, macro hosts).
    For complex plugins with dozens/hundreds of parameters, return [] by default so the
    rack stays clean until the user maps desired controls via the MAP button.
    """
    usable = get_usable_parameters(plugin)
    if not usable or len(usable) > max_auto_total:
        return []

    # If the plugin has <= 6 usable parameters (or <= 8 and all are named "parameter_N"),
    # expose all of them in their native plugin order!
    if len(usable) <= max_knobs:
        return [k for k, _ in usable]
    if len(usable) <= 8 and all(k.startswith("parameter_") for k, _ in usable):
        return [k for k, _ in usable]

    # Otherwise (7..12 parameters, like kHs Gate or kHs Delay), pick the top max_knobs
    # highest-scoring continuous parameters while preserving their natural left-to-right order!
    scored = sorted(
        [(idx, k, _score_parameter(k, v, idx)) for idx, (k, v) in enumerate(usable)],
        key=lambda t: t[2],
        reverse=True,
    )
    chosen_indices = sorted(idx for idx, _, _ in scored[:max_knobs])
    return [usable[idx][0] for idx in chosen_indices]


def smart_pick_params(plugin, max_knobs: int = 6) -> list[str]:
    """Smartly pick up to max_knobs key parameters for ANY plugin (even 800+ param suites)."""
    usable = get_usable_parameters(plugin)
    if not usable:
        return []
    scored = sorted(
        [(idx, k, _score_parameter(k, v, idx)) for idx, (k, v) in enumerate(usable[:400])],
        key=lambda t: t[2],
        reverse=True,
    )
    chosen_indices = sorted(idx for idx, _, _ in scored[:max_knobs])
    return [usable[idx][0] for idx in chosen_indices]


def resolve_slot_mapped_params(slot: PluginSlot, cfg) -> list[str]:
    """Return the active list of parameter keys to display as knobs on this slot's rack card."""
    plugin = getattr(slot, "_instance", None)
    params_dict = get_plugin_params_dict(plugin) if plugin is not None else None

    # 1. Explicit per-slot override
    if slot.mapped_params is not None:
        if params_dict is not None:
            return [k for k in slot.mapped_params if k in params_dict]
        return list(slot.mapped_params)

    # 2. Global saved mapping for this VST plugin
    mappings = getattr(cfg, "plugin_param_mappings", None) or {}
    mkey = plugin_mapping_key(slot)
    if mkey in mappings:
        if params_dict is not None:
            return [k for k in mappings[mkey] if k in params_dict]
        return list(mappings[mkey])

    # 3. Smart automatic exposure for compact plugins
    if plugin is not None:
        return get_auto_mapped_params(plugin)
    return []


def clean_param_string(param) -> str:
    """Format a VST3 parameter's live string_value cleanly for hardware display."""
    try:
        s = str(getattr(param, "string_value", "") or "")
        s = s.replace("\u2212", "-").replace("\u2013", "-").replace("\u202f", " ").replace("\xa0", " ").strip()
        u = str(getattr(param, "units", "") or "").replace("\u202f", " ").strip()
        if s and u and not s.lower().endswith(u.lower()) and u not in s:
            s = f"{s} {u}"
        if s:
            return s
        return f"{float(param.raw_value) * 100.0:.0f}%"
    except Exception:
        return "0%"


def format_knob_title(name: str, max_len: int = 9) -> str:
    """Abbreviate parameter names cleanly for compact studio knob headers."""
    s = (name or "").strip()
    if ":" in s:
        # e.g. "GATE: Attack" -> "G.ATTACK" or take suffix if prefix is long
        parts = [p.strip() for p in s.split(":", 1)]
        if len(parts[0]) <= 4:
            s = f"{parts[0][:2]}.{parts[1]}"
        else:
            s = parts[1]
    # Remove parenthesized unit hints like "Delay Time (seconds)" -> "Delay Time"
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    replacements = [
        ("Threshold", "THRESH"),
        ("threshold", "THRESH"),
        ("Feedback", "FEEDBK"),
        ("feedback", "FEEDBK"),
        ("Release", "RELEASE"),
        ("Attack", "ATTACK"),
        ("Makeup", "MAKEUP"),
        ("Tolerance", "TOLER"),
        ("Frequency", "FREQ"),
        ("Parameter ", "PARAM "),
        ("Delay Time", "DELAY"),
        ("Look-ahead", "LOOKAHD"),
        ("Semitones", "SEMI"),
    ]
    for old, new in replacements:
        if s.lower() == old.lower():
            return new
    s_up = s.upper()
    if len(s_up) > max_len:
        return s_up[:max_len]
    return s_up


def _extract_first_float(text: str) -> float | None:
    import re
    s = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u202f", " ").strip().lower()
    if not s:
        return None
    if "-inf" in s or "inf" == s:
        return -1e9
    if "+inf" in s:
        return 1e9
    m = re.search(r"[-+]?(?:\d*\.?\d+|\d+)", s)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


def _text_at_raw(param, raw: float) -> str:
    """The plugin's display text for a raw value, without changing the live parameter if possible."""
    getter = getattr(param, "get_text_for_raw_value", None)
    if getter is not None:
        try:
            text = getter(raw)
            if text:
                return str(text)
        except Exception:
            pass
    # Some plugins only format their current value: probe it, then restore.
    orig = float(param.raw_value)
    try:
        param.raw_value = raw
        return clean_param_string(param)
    finally:
        param.raw_value = orig


def set_param_from_text(param, user_text: str) -> bool:
    """
    Set a parameter from user-typed text (e.g. '-18.5', '25 ms', '4:1', '50%').

    Order of attempts, so the audio never hears intermediate values:
    1. Mandible's internal DSP parameters take engineering values directly.
    2. The plugin's own text parser (pedalboard ``get_raw_value_for``).
    3. A binary search over raw values against the plugin's formatter, then a single final set.
    4. Fallback: treat the number as normalized 0..1 or a 0..100 percentage.
    """
    target = _extract_first_float(user_text)
    if target is None:
        return False

    if isinstance(param, InternalParameter):
        param.value = target
        return True

    lo_v, hi_v = getattr(param, "min_value", None), getattr(param, "max_value", None)
    if isinstance(lo_v, (int, float)) and isinstance(hi_v, (int, float)) and not isinstance(lo_v, bool):
        target = max(float(lo_v), min(float(hi_v), target))
    try:
        param.raw_value = float(param.get_raw_value_for(target))
        return True
    except Exception:
        pass

    try:
        v0 = _extract_first_float(_text_at_raw(param, 0.0))
        v1 = _extract_first_float(_text_at_raw(param, 1.0))
        if v0 is not None and v1 is not None and abs(v1 - v0) > 1e-9:
            inc = v1 >= v0
            lo, hi = 0.0, 1.0
            if target <= min(v0, v1):
                lo = hi = 0.0 if inc else 1.0
            elif target >= max(v0, v1):
                lo = hi = 1.0 if inc else 0.0
            else:
                for _ in range(14):
                    mid = 0.5 * (lo + hi)
                    vm = _extract_first_float(_text_at_raw(param, mid))
                    if vm is None:
                        break
                    if (vm < target) == inc:
                        lo = mid
                    else:
                        hi = mid
            param.raw_value = max(0.0, min(1.0, 0.5 * (lo + hi)))
            return True

        if 0.0 <= target <= 1.0:
            param.raw_value = target
            return True
        if 0.0 <= target <= 100.0:
            param.raw_value = target / 100.0
            return True
    except Exception:
        pass
    return False


def capture_state(plugin) -> str:
    try:
        return base64.b64encode(plugin.raw_state).decode("ascii")
    except Exception:
        return ""


def get_slot_latency_samples(slot: PluginSlot) -> int:
    p = getattr(slot, "_instance", None)
    if p is not None and hasattr(p, "reported_latency_samples"):
        try:
            return int(p.reported_latency_samples)
        except Exception:
            return 0
    return 0


def get_chain_latency_samples(chain: Chain) -> int:
    return sum(get_slot_latency_samples(s) for s in chain.plugins if s.enabled)


def make_board(plugins: list):
    try:
        # If any plugin in the list is an internal Python DSP plugin, pedalboard cannot wrap it
        for p in plugins:
            if is_internal_plugin(getattr(p, "path", "")):
                return None
        return pedalboard.Pedalboard(list(plugins)) if plugins else None
    except Exception:
        return None

