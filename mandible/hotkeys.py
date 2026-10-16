"""Global (system-wide) hotkeys with press *and* release events, for toggle/hold modes.

Uses the `keyboard` package's low-level hook (no admin needed, keys are NOT
suppressed so games still receive them). The main key is matched by scan code
so Shift/layout changes don't alter it; modifiers are read with
GetAsyncKeyState so a missed key-up can never leave them "stuck".
"""
from __future__ import annotations

import ctypes
import threading
from dataclasses import dataclass
from typing import Callable

import keyboard

from .config import Hotkey

_user32 = ctypes.windll.user32
_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12}
_VK_LWIN, _VK_RWIN = 0x5B, 0x5C
MOD_ORDER = ["ctrl", "shift", "alt", "windows"]


def _mod_category(name: str) -> str | None:
    n = (name or "").lower()
    if "ctrl" in n:
        return "ctrl"
    if "shift" in n:
        return "shift"
    if "alt" in n:
        return "alt"
    if "windows" in n or n in ("cmd", "win"):
        return "windows"
    return None


def _mods_down() -> set[str]:
    down = set()
    for m, vk in _VK.items():
        if _user32.GetAsyncKeyState(vk) & 0x8000:
            down.add(m)
    if (_user32.GetAsyncKeyState(_VK_LWIN) | _user32.GetAsyncKeyState(_VK_RWIN)) & 0x8000:
        down.add("windows")
    return down


def _key_label(event) -> str:
    name = event.name or f"sc{event.scan_code}"
    if len(name) == 1:
        # With Shift held `keyboard` reports the shifted char ('!'); ask Windows for the key cap.
        buf = ctypes.create_unicode_buffer(32)
        if _user32.GetKeyNameTextW(event.scan_code << 16, buf, 32) > 0:
            name = buf.value
        name = name.upper()
    else:
        name = name.title()
    if event.is_keypad and not name.lower().startswith("num"):
        name = "Num " + name
    return name


@dataclass
class _Binding:
    hotkey: Hotkey
    on_down: Callable[[], None]
    on_up: Callable[[], None] | None


class HotkeyManager:
    def __init__(self):
        self.enabled = True
        self._bindings: list[_Binding] = []
        self._pressed: set[tuple[int, bool]] = set()
        self._held: dict[tuple[int, bool], _Binding] = {}
        self._capture: Callable[[Hotkey | None], None] | None = None
        self._lock = threading.Lock()
        self._hook = keyboard.hook(self._on_event)

    def close(self):
        try:
            keyboard.unhook(self._hook)
        except Exception:
            pass

    def set_bindings(self, bindings: list[tuple[Hotkey, Callable, Callable | None]]):
        with self._lock:
            self._bindings = [_Binding(h, d, u) for h, d, u in bindings if h and h.is_set()]

    def capture_next(self, callback: Callable[[Hotkey | None], None]):
        """Call ``callback`` (from the hook thread) with the next key combo; Esc cancels."""
        self._capture = callback

    def cancel_capture(self):
        self._capture = None

    # -------------------------------------------------------------- hook
    def _on_event(self, e):
        try:
            key = (e.scan_code, bool(e.is_keypad))
            if e.event_type == keyboard.KEY_DOWN:
                if key in self._pressed:
                    return            # auto-repeat
                self._pressed.add(key)
                if _mod_category(e.name):
                    return
                if self._capture is not None:
                    cb, self._capture = self._capture, None
                    mods = _mods_down()
                    if e.name == "esc" and not mods:
                        cb(None)
                        return
                    ordered = [m for m in MOD_ORDER if m in mods]
                    label = "+".join([m.title() for m in ordered] + [_key_label(e)])
                    cb(Hotkey(mods=ordered, scan_code=e.scan_code, keypad=bool(e.is_keypad), label=label))
                    return
                if not self.enabled:
                    return
                mods = _mods_down()
                with self._lock:
                    best, best_n = None, -1
                    for b in self._bindings:
                        h = b.hotkey
                        if h.scan_code == e.scan_code and h.keypad == key[1] and set(h.mods) <= mods:
                            if len(h.mods) > best_n:  # most specific combo wins
                                best, best_n = b, len(h.mods)
                if best is not None:
                    self._held[key] = best
                    best.on_down()
            elif e.event_type == keyboard.KEY_UP:
                self._pressed.discard(key)
                b = self._held.pop(key, None)
                if b is not None and b.on_up is not None:
                    b.on_up()
        except Exception as exc:  # never let an exception kill the hook thread
            print(f"[Mandible] hotkey error: {exc}")
