"""Signal flow strip: mic -> pre-FX -> plugin rack -> soundboard -> limiter -> outputs.

Three modes (spec 7.6): ``full`` (every step spelled out, chevrons between them), ``icons``
(one icon per step, full text in the tooltip) and ``hidden``. Status-only steps are status
pills (no hover, never focusable); the pre-FX, soundboard and limiter steps are buttons.
The header requests a mode from the window width; the strip then falls back to the richest
mode that actually fits the width it was given, so it never overflows whatever the fonts,
skin or scale.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ...audio_engine import DRY_ID
from ...core import Core
from ..icons import bind_label_icon
from .base import SpacedLayouts, _follow_look, set_style_property
from .buttons import StatusPill, make_button, set_button_state

MODES = ("full", "icons", "hidden")

# step key -> (icon shown in icons mode, what the step is)
_STEPS = {
    "mic": ("mic", "Microphone input"),
    "prefx": ("filter", "Pre-FX (mic clean-up before the effects)"),
    "rack": ("rack", "Active plugin rack"),
    "sb": ("pads", "Soundboard"),
    "lim": ("limiter", "Output limiter"),
    "out": ("speaker", "Outputs"),
}
ICON_PX = 16
ARROW_PX = 12


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

        self._full: dict[str, StatusPill | QPushButton] = {}
        self._icons: dict[str, StatusPill | QPushButton] = {}
        self._arrows: list[QLabel] = []

        clicks = {"prefx": self.prefxClicked, "sb": self.soundboardClicked,
                  "lim": self.limiterClicked}
        self._tips = tips = {"prefx": "Click to configure the pre-FX stages",
                "sb": "Soundboard audio playback clips",
                "lim": "Click to turn the output limiter on or off"}
        for i, key in enumerate(_STEPS):
            if i:
                arrow = QLabel()
                arrow.setObjectName("flowArrow")
                arrow.setAccessibleName("then")   # read between steps: "Mic in, then Pre-FX"
                bind_label_icon(arrow, "chevron_right", "text.secondary", ARROW_PX)
                self._arrows.append(arrow)
                lay.addWidget(arrow)
            icon_name, what = _STEPS[key]
            if key in clicks:
                full = make_button(tooltip=tips[key])
                full.setProperty("small", "true")
                full.clicked.connect(clicks[key].emit)
                icon = make_button(tier="secondary", icon=icon_name, tooltip=what)
                icon.setProperty("small", "true")
                icon.clicked.connect(clicks[key].emit)
            else:
                full = StatusPill(elide=True, min_chars=10)
                full.setBaseToolTip(what)
                icon = StatusPill()
                icon.setProperty("iconOnly", "true")
                icon.setToolTip(what)
                icon.setAccessibleName(what)
                bind_label_icon(icon, icon_name, "text.secondary", ICON_PX)
            for w in (full, icon):
                w.setProperty("flowStep", key)
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

        self._set_texts(None, "Clean voice")
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
            hint = w.minimumSizeHint() if isinstance(w, StatusPill) else w.sizeHint()
            total += max(hint.width(), w.minimumWidth())
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
        in_name = cfg.audio.input_device or "Mic in"
        texts = {"mic": f"{in_name} (ch {cfg.audio.input_channel + 1})"}
        p = cfg.prefx
        stages = [name for name, on in (("High-pass", p.highpass_enabled),
                                        ("RNNoise", p.rnnoise_enabled),
                                        ("Noise gate", p.noise_gate_enabled)) if on]
        p_on = bool(stages)
        texts["prefx"] = "Pre-FX"
        clean_name = active_chain_name.replace("●", "").strip()
        texts["rack"] = f"Rack: {clean_name}"
        texts["sb"] = f"Soundboard ({len(cfg.soundboard)})"
        l_on = bool(cfg.limiter.enabled)
        texts["lim"] = f"Limiter {'on' if l_on else 'off'}"
        out_ch = cfg.audio.output_channels
        ch_str = f"ch {out_ch[0] + 1}-{out_ch[1] + 1}" if len(out_ch) >= 2 else "ch 3-4"
        texts["out"] = f"V-Mic ({ch_str}) + phones"

        is_fx = target_id is not None and target_id != DRY_ID
        active = {"prefx": p_on, "rack": is_fx, "lim": l_on}
        for key, text in texts.items():
            full, icon = self._full[key], self._icons[key]
            full.setText(text)
            icon_name, what = _STEPS[key]
            if key == "prefx":
                stage_txt = ", ".join(stages) if stages else "all stages off"
                full.setToolTip(f"Pre-FX: {stage_txt}\n{self._tips[key]}")
                icon.setToolTip(f"{what}: {stage_txt}\n{self._tips[key]}")
            else:
                extra = f"\n{full.toolTip()}" if isinstance(full, QPushButton) and full.toolTip() else ""
                icon.setToolTip(f"{what}: {text}{extra}")
            if isinstance(icon, StatusPill):
                # An icon-only pill says what it shows to a screen reader.
                icon.setAccessibleName(f"{what}: {text}")
            if key in active:
                self._set_step_state(key, "on" if active[key] else "off")

    def _set_step_state(self, key: str, value: str) -> None:
        """``on`` / ``off`` on both widgets of a step (pills: state; buttons: status tint)."""
        full, icon = self._full[key], self._icons[key]
        if full.property("stepState") == value:
            return
        for w in (full, icon):
            w.setProperty("stepState", value)
            if isinstance(w, StatusPill):
                w.set_state(value)
            else:
                set_button_state(w, "on" if value == "on" else "")
        if isinstance(icon, StatusPill):
            bind_label_icon(icon, _STEPS[key][0], "status.ok" if value == "on" else "text.secondary",
                            ICON_PX)

    def step_state(self, key: str) -> str:
        return self._full[key].property("stepState") or "off"

    def refresh(self, target_id: str | None, active_chain_name: str):
        self._set_texts(target_id, active_chain_name)
        if self._mode != "hidden" or self._requested != "hidden":
            self._fit()
