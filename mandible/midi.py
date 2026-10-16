"""Native Windows MIDI input support via winmm.dll (no external dependencies).
Supports mapping MIDI Note On and CC knobs/sliders to:
- Activating effect chains
- Triggering soundboard clips
- Mute / Panic / PTT
- Output / Monitor volume adjustment
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

_winmm = ctypes.windll.winmm

MIM_DATA = 0x3C3
CALLBACK_FUNCTION = 0x30000


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * 32),
        ("wSupport", wintypes.DWORD),
    ]


MIDI_CALLBACK_TYPE = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
)


def list_midi_inputs() -> list[tuple[int, str]]:
    """Return [(device_index, name)] of all connected MIDI input devices."""
    num = _winmm.midiInGetNumDevs()
    devs = []
    caps = MIDIINCAPSW()
    for i in range(num):
        if _winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            devs.append((i, caps.szPname))
    return devs


class MidiManager:
    def __init__(self):
        self._handle = None
        self._current_dev_name = ""
        self._cb_holder = None
        self._on_message: Callable[[int, int, int], None] | None = None  # (status, data1, data2)
        self.enabled = True

    def open_device(self, name_or_index: str | int, on_msg: Callable[[int, int, int], None]):
        self.close()
        self._on_message = on_msg
        dev_idx = None
        devs = list_midi_inputs()
        if isinstance(name_or_index, int):
            dev_idx = name_or_index if 0 <= name_or_index < len(devs) else None
        else:
            for idx, dname in devs:
                if dname.lower() == str(name_or_index).lower():
                    dev_idx = idx
                    break

        if dev_idx is None:
            return False

        h_in = wintypes.HANDLE()

        def _native_cb(_h, msg, _inst, p1, _p2):
            if msg == MIM_DATA and self.enabled and self._on_message:
                status = p1 & 0xFF
                d1 = (p1 >> 8) & 0xFF
                d2 = (p1 >> 16) & 0xFF
                try:
                    self._on_message(status, d1, d2)
                except Exception as exc:
                    print(f"[Mandible] midi callback error: {exc}")

        self._cb_holder = MIDI_CALLBACK_TYPE(_native_cb)
        err = _winmm.midiInOpen(
            ctypes.byref(h_in),
            dev_idx,
            self._cb_holder,
            None,
            CALLBACK_FUNCTION,
        )
        if err != 0:
            return False

        _winmm.midiInStart(h_in)
        self._handle = h_in
        self._current_dev_name = devs[dev_idx][1]
        return True

    def close(self):
        if self._handle:
            try:
                _winmm.midiInStop(self._handle)
                _winmm.midiInClose(self._handle)
            except Exception:
                pass
            self._handle = None
            self._cb_holder = None
            self._current_dev_name = ""
