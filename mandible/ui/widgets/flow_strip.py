"""Signal flow strip: mic -> pre-FX -> plugin rack -> soundboard -> limiter -> outputs.

Three modes (spec 7.6): ``full`` (every step spelled out, arrows between them), ``icons``
(a short tag per step, full text in the tooltip) and ``hidden``. The header requests a mode
from the window width; the strip then falls back to the richest mode that actually fits the
width it was given, so it never overflows whatever the fonts, skin or scale.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ...audio_engine import DRY_ID
from ...core import Core
from .base import SpacedLayouts, _follow_look, set_style_property
from .labels import ElidedLabel

MODES = ("full", "icons", "hidden")

# step key -> (short tag shown in icons mode, what the step is)
_STEPS = {
    "mic": ("MIC", "Microphone input"),
    "prefx": ("NR", "Pre-FX noise suppression"),
    "rack": ("FX", "Active plugin rack"),
    "sb": ("SB", "Soundboard"),
    "lim": ("LIM", "Output limiter"),
    "out": ("OUT", "Outputs"),
}


class SignalFlowStrip(QFrame):
    """Status of each stage of the signal path; the pre-FX, soundboard and limiter steps are
    buttons."""
    prefxClicked = Signal()
    soundboardClicked = Signal()
    limiterClicked = Signal()
    modeChanged = Signal(str)

    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setObjectName("signalFlowStrip")
        self._requested = "full"
        # Width a neighbour gives back once the strip shows again (the header's MORE button,
        # shown only because the strip is hidden); without it a hidden strip could never
        # come back at widths where it fits.
        self.reclaimable_width = lambda: 0
        self._mode = ""
        self._spaced = SpacedLayouts()
        lay = self._spaced.add(QHBoxLayout(self), spacing=1, margins=(2, 1, 2, 1))
        # Never let the strip's contents set the header's minimum width; the mode logic
        # keeps the contents inside whatever width the strip gets.
        self.setMinimumWidth(1)

        self._full: dict[str, QLabel | QPushButton] = {}
        self._icons: dict[str, QLabel | QPushButton] = {}
        self._arrows: list[QLabel] = []

        clicks = {"prefx": self.prefxClicked, "sb": self.soundboardClicked,
                  "lim": self.limiterClicked}
        tips = {"prefx": "Click to configure Pre-FX RNNoise suppression and gate",
                "sb": "Soundboard audio playback clips",
                "lim": "Click to toggle Master Safety Limiter"}
        for i, key in enumerate(_STEPS):
            if i:
                arrow = QLabel("→")
                arrow.setObjectName("flowArrow")
                self._arrows.append(arrow)
                lay.addWidget(arrow)
            short, what = _STEPS[key]
            if key in clicks:
                full = QPushButton()
                full.setObjectName("flowBtn")
                full.setToolTip(tips[key])
                full.clicked.connect(clicks[key].emit)
                icon = QPushButton(short)
                icon.setObjectName("flowBtn")
                icon.clicked.connect(clicks[key].emit)
            else:
                full = ElidedLabel(min_chars=10)
                full.setObjectName("flowPill")
                full.setBaseToolTip(what)
                icon = QLabel(short)
                icon.setObjectName("flowPill")
            icon.setProperty("compact", "true")
            self._full[key], self._icons[key] = full, icon
            lay.addWidget(full)
            lay.addWidget(icon)
        lay.addStretch()

        # Backward-compatible names (the main window aliases some of them).
        self.mic_pill = self._full["mic"]
        self.prefx_btn = self._full["prefx"]
        self.chain_pill = self._full["rack"]
        self.sb_btn = self._full["sb"]
        self.lim_btn = self._full["lim"]
        self.out_pill = self._full["out"]

        self._set_texts(None, "CLEAN VOICE")
        self._show_mode("hidden")
        # width_for() measures hidden steps; polish them now, never from an event handler.
        for w in [*self._full.values(), *self._icons.values(), *self._arrows]:
            w.ensurePolished()
        _follow_look(self)

    # ------------------------------------------------------------------ modes
    def step_button(self, key: str, mode: str):
        """The clickable widget of step ``key`` in ``mode`` (None for status-only steps)."""
        table = self._full if mode == "full" else self._icons if mode == "icons" else {}
        w = table.get(key)
        return w if isinstance(w, QPushButton) else None

    def mode(self) -> str:
        return self._mode

    def requested_mode(self) -> str:
        return self._requested

    def set_requested_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown flow strip mode {mode!r}")
        if mode != self._requested:
            self._requested = mode
            self._fit()

    def width_for(self, mode: str) -> int:
        """The narrowest width at which ``mode`` shows without clipping (0 for hidden)."""
        if mode == "hidden":
            return 0
        widgets = list(self._full.values()) + self._arrows if mode == "full" else list(self._icons.values())
        lay = self.layout()
        m = lay.contentsMargins()
        fw = self.frameWidth() * 2
        total = m.left() + m.right() + fw + lay.spacing() * (len(widgets) - 1)
        for w in widgets:
            total += w.minimumSizeHint().width() if isinstance(w, ElidedLabel) else w.sizeHint().width()
        return total

    def _fit(self) -> None:
        avail = self.width() + (self.reclaimable_width() if self._mode == "hidden" else 0)
        order = MODES[MODES.index(self._requested):]
        chosen = next((m for m in order if self.width_for(m) <= avail), "hidden")
        self._show_mode(chosen)

    def _show_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        for w in self._full.values():
            w.setVisible(mode == "full")
        for w in self._arrows:
            w.setVisible(mode == "full")
        for w in self._icons.values():
            w.setVisible(mode == "icons")
        set_style_property(self, "mode", mode)
        self.modeChanged.emit(mode)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._fit()

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._fit()

    # ------------------------------------------------------------------ state
    def _set_texts(self, target_id: str | None, active_chain_name: str) -> None:
        cfg = self.core.cfg
        in_name = cfg.audio.input_device or "MIC IN"
        texts = {"mic": f"{in_name.upper()} (CH {cfg.audio.input_channel + 1})"}
        p = cfg.prefx
        p_on = bool(p.highpass_enabled or p.rnnoise_enabled or p.noise_gate_enabled)
        texts["prefx"] = f"RNNOISE: {'ON' if p_on else 'OFF'}"
        clean_name = active_chain_name.replace("●", "").strip().upper()
        texts["rack"] = f"PLUGIN RACK: {clean_name}"
        texts["sb"] = f"SOUNDBOARD ({len(cfg.soundboard)})"
        l_on = bool(cfg.limiter.enabled)
        texts["lim"] = f"LIMITER: {'ON' if l_on else 'OFF'}"
        out_ch = cfg.audio.output_channels
        ch_str = f"CH {out_ch[0] + 1}-{out_ch[1] + 1}" if len(out_ch) >= 2 else "CH 3-4"
        texts["out"] = f"V-MIC ({ch_str}) + PHONES"

        is_fx = target_id is not None and target_id != DRY_ID
        active = {"prefx": p_on, "rack": is_fx, "lim": l_on}
        for key, text in texts.items():
            full, icon = self._full[key], self._icons[key]
            full.setText(text)
            short, what = _STEPS[key]
            extra = f"\n{full.toolTip()}" if isinstance(full, QPushButton) and full.toolTip() else ""
            icon.setToolTip(f"{what}: {text}{extra}")
            if key in active:
                value = "true" if active[key] else "false"
                if full.property("active") != value:
                    set_style_property(full, "active", value)
                    set_style_property(icon, "active", value)

    def refresh(self, target_id: str | None, active_chain_name: str):
        self._set_texts(target_id, active_chain_name)
        if self._mode != "hidden" or self._requested != "hidden":
            self._fit()
