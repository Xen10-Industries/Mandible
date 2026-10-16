"""Audio device enumeration helpers (PortAudio via sounddevice, with ASIO enabled)."""
from __future__ import annotations

import ctypes
import os

os.environ.setdefault("SD_ENABLE_ASIO", "1")  # must be set before sounddevice is imported
import sounddevice as sd  # noqa: E402

DRIVER_LABELS = {
    "ASIO": "ASIO (lowest latency)",
    "Windows WASAPI": "WASAPI",
    "Windows DirectSound": "DirectSound",
    "MME": "MME",
    "Windows WDM-KS": "WDM-KS",
}
PREFERRED_DRIVERS = ["ASIO", "Windows WASAPI", "Windows DirectSound", "MME"]

_lib = None


def _pa_lib():
    global _lib
    if _lib is None:
        try:
            _lib = ctypes.CDLL(sd._libname)
            for fn in ("PaAsio_GetInputChannelName", "PaAsio_GetOutputChannelName"):
                f = getattr(_lib, fn)
                f.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
                f.restype = ctypes.c_int
            _lib.PaAsio_ShowControlPanel.argtypes = [ctypes.c_int, ctypes.c_void_p]
            _lib.PaAsio_ShowControlPanel.restype = ctypes.c_int
        except Exception:
            _lib = False
    return _lib


def show_asio_panel(device_name: str, hwnd: int) -> str:
    """Open the ASIO driver's control panel. Returns an error string ('' on success)."""
    lib = _pa_lib()
    idx = find_device("ASIO", device_name, "input")
    if not lib or idx is None:
        return "ASIO device not found"
    err = lib.PaAsio_ShowControlPanel(idx, ctypes.c_void_p(hwnd))
    return "" if err == 0 else sd._lib.Pa_GetErrorText(err) and sd._ffi.string(sd._lib.Pa_GetErrorText(err)).decode()


def rescan() -> None:
    """Re-initialise PortAudio so newly connected devices show up (stream must be stopped)."""
    try:
        sd._terminate()
    finally:
        sd._initialize()


def drivers() -> list[str]:
    names = [h["name"] for h in sd.query_hostapis()]
    ordered = [d for d in PREFERRED_DRIVERS if d in names]
    return ordered + [n for n in names if n not in ordered]


def hostapi_index(driver: str) -> int | None:
    for i, h in enumerate(sd.query_hostapis()):
        if h["name"] == driver:
            return i
    return None


def list_devices(driver: str, kind: str) -> list[tuple[int, str, int]]:
    """Return [(index, name, channel_count)] for 'input' or 'output' devices of a driver."""
    api = hostapi_index(driver)
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] == api and d[key] > 0:
            out.append((i, d["name"], d[key]))
    return out


def find_device(driver: str, name: str, kind: str) -> int | None:
    for idx, dev_name, _ in list_devices(driver, kind):
        if dev_name == name:
            return idx
    return None


def channel_names(driver: str, dev_index: int, kind: str) -> list[str]:
    d = sd.query_devices(dev_index)
    n = d["max_input_channels"] if kind == "input" else d["max_output_channels"]
    names = [f"Channel {i + 1}" for i in range(n)]
    lib = _pa_lib()
    if driver == "ASIO" and lib:
        fn = lib.PaAsio_GetInputChannelName if kind == "input" else lib.PaAsio_GetOutputChannelName
        for i in range(n):
            s = ctypes.c_char_p()
            if fn(dev_index, i, ctypes.byref(s)) == 0 and s.value:
                names[i] = s.value.decode(errors="replace")
    return names


def default_samplerate(dev_index: int) -> int:
    return int(sd.query_devices(dev_index)["default_samplerate"])


def guess_focusrite_setup():
    """Best-effort defaults for a Focusrite interface: mic on input 1 -> Playback 3-4."""
    from .config import AudioSettings
    a = AudioSettings()
    all_drivers = drivers()
    if "ASIO" in all_drivers:
        for _, name, _n in list_devices("ASIO", "input"):
            if "focusrite" in name.lower():
                a.driver, a.input_device, a.output_device = "ASIO", name, name
                a.input_channel, a.output_channels = 0, [2, 3]
                a.monitor_channels = [0, 1]
                return a
    if "Windows WASAPI" in all_drivers:
        ins = list_devices("Windows WASAPI", "input")
        outs = list_devices("Windows WASAPI", "output")
        mic = next((n for _, n, _c in ins if "focusrite" in n.lower() and "1" in n), None)
        pb = next((n for _, n, _c in outs if "playback 3" in n.lower()), None)
        spk = next((n for _, n, _c in outs if "speakers" in n.lower()), "")
        if mic and pb:
            a.driver, a.input_device, a.output_device = "Windows WASAPI", mic, pb
            a.input_channel, a.output_channels = 0, [0, 1]
            a.monitor_device = spk
            a.blocksize = 256
            return a
    # Fallback: system defaults on the first available driver
    a.driver = all_drivers[0] if all_drivers else ""
    try:
        a.input_device = sd.query_devices(kind="input")["name"]
        a.output_device = sd.query_devices(kind="output")["name"]
    except Exception:
        pass
    a.output_channels = [0, 1]
    return a


def detect_virtual_cables() -> list[dict]:
    """Detect virtual audio cable devices and Focusrite loopback across all drivers."""
    found = []
    seen = set()
    for driver in ["Windows WASAPI", "ASIO", "Windows DirectSound", "MME"]:
        try:
            for idx, name, chans in list_devices(driver, "output"):
                nl = name.lower()
                key = (driver, name)
                if key in seen:
                    continue
                if "cable input" in nl or "vb-audio" in nl or "cable-a" in nl or "cable-b" in nl or "virtual audio" in nl:
                    seen.add(key)
                    found.append({
                        "type": "vbcable",
                        "driver": driver,
                        "device": name,
                        "label": f"{name} ({driver})",
                        "desc": "VB-Audio Virtual Cable (Ideal for Discord & OBS)",
                    })
                elif "playback 3" in nl or "loopback" in nl or ("focusrite" in nl and "3" in nl):
                    seen.add(key)
                    found.append({
                        "type": "focusrite",
                        "driver": driver,
                        "device": name,
                        "label": f"{name} ({driver})",
                        "desc": "Focusrite USB Audio Loopback (Hardware Loopback)",
                    })
        except Exception:
            pass
    return found
