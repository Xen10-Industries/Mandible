"""Main window header: three zones (spec 7.6).

* **left** (fixed): rack screw, pilot lamp, power, the brand mark (``branding.render_mark``
  in the look's ``text.primary``) and the status zone: the DSP readout over the idle-mode
  dropdown and the hotkeys switch (whose menu sets the all-off key).
* **middle** (flexible): the signal-flow strip; its steps drop to icons below
  ``FLOW_ICONS_BELOW`` and it hides below ``FLOW_HIDDEN_BELOW`` (window widths).
* **right** (fixed): Test mic, Monitor, Panic, Settings, Help; below
  ``ACTIONS_OVERFLOW_BELOW`` Test mic and Monitor fold into an overflow menu.

The header's minimum width is always the folded one, so the window can shrink to 1024 px
whatever state the header is in.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from ... import branding
from ... import devices as D
from ...core import Core
from ..look import current_look
from .base import SpacedLayouts, _follow_look, reserve_text_width
from .buttons import make_button
from .chassis import RackScrew
from .flow_strip import SignalFlowStrip
from .labels import ElidedLabel
from .lamps import PilotLamp

FLOW_ICONS_BELOW = 1400
FLOW_HIDDEN_BELOW = 1100
ACTIONS_OVERFLOW_BELOW = 1180
STRIPS_COLLAPSE_BELOW_H = 800

AUDITION_IDLE_TEXT = "Test mic"
AUDITION_TEXTS = ("Rec 5.0 s", "Stop loop")   # while recording (counts up) / looping
POWER_OFF_TEXT = "Start audio"
POWER_ON_TEXT = "Audio on"
MARK_PX = 22

# The texts the DSP readout shows (MainWindow._update_status formats them). Each field is
# fixed to the widest of its list, so starting audio never resizes the header's fixed left
# zone. Anything wider still (an 11.025 kHz device, 8192+ sample buffers, a driver outside
# DRIVER_LABELS) elides with the full text in the tooltip rather than moving the header.
READOUT_SAMPLES = {
    "stat": ("DSP: OFF", "DSP: 0%", "DSP: 100%"),
    "sr": ("-- kHz", "8 kHz", "22.05 kHz", "44.1 kHz", "48 kHz", "88.2 kHz", "96 kHz",
           "176.4 kHz", "192 kHz", "352.8 kHz", "384 kHz"),
    "buf": ("-- SMP", "32 SMP", "128 SMP", "1024 SMP", "4096 SMP"),
    "lat": ("-- ms", "0.0 ms", "88.8 ms", "999.9 ms"),
    "drv": ("OFFLINE", *sorted({v.split(" (")[0].upper() for v in D.DRIVER_LABELS.values()})),
}
# Run-time texts past the reserved widths (used by the layout probe's "running" scenario).
READOUT_OVERSIZE = {"sr": "11.025 kHz", "buf": "16384 SMP", "lat": "2048.0 ms",
                    "stat": "DSP: 1000%", "drv": "WINDOWS WDM-KS EXTENDED"}


def flow_mode_for_width(width: int) -> str:
    if width < FLOW_HIDDEN_BELOW:
        return "hidden"
    if width < FLOW_ICONS_BELOW:
        return "icons"
    return "full"


class BrandMark(QLabel):
    """Mandible's mark in the header: ``branding.render_mark`` drawn in the look's
    ``text.primary``, re-rendered when the look (or the screen's pixel ratio) changes."""

    def __init__(self, px: int = MARK_PX, parent=None):
        super().__init__(parent)
        self.mark_px = px
        self._dpr = 0.0
        self.setObjectName("brandMark")
        self.setFixedSize(px, px)
        self.setToolTip("Mandible")
        self._render()
        _follow_look(self)

    def _render(self) -> None:
        dpr = self.devicePixelRatioF()
        self._dpr = dpr
        img = branding.render_mark(round(self.mark_px * dpr), current_look().palette.color("text.primary"))
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        self.setPixmap(pm)

    def _on_look_changed(self) -> None:
        self._render()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self.devicePixelRatioF() != self._dpr:
            self._render()


def _zone(name: str) -> QWidget:
    w = QWidget()
    w.setObjectName(name)
    w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    return w


class HeaderBar(QFrame):
    """The window's top strip. Owns its widgets; ``MainWindow`` wires their signals."""

    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        cfg = core.cfg
        self.setObjectName("masterHeadStrip")
        self._spaced = SpacedLayouts()
        top = self._spaced.add(QHBoxLayout(self), spacing=3, margins=(3, 2, 3, 2))

        # ------------------------------------------------------------ left zone
        self.left = _zone("headerLeft")
        left = self._spaced.add(QHBoxLayout(self.left), spacing=2, margins=0)
        left.addWidget(RackScrew(16))
        self.pilot_lamp = PilotLamp(active=False, size=18)
        left.addWidget(self.pilot_lamp)

        self.power = make_button(POWER_OFF_TEXT, "secondary", icon="power",
                                 tooltip="Start or stop the audio engine")
        self.power.setCheckable(True)
        self.power.setObjectName("hardwareMasterToggle")
        left.addWidget(self.power)

        self.logo_slot = QHBoxLayout()
        self.logo_slot.setContentsMargins(0, 0, 0, 0)
        self.brand_mark = BrandMark()
        self.logo_slot.addWidget(self.brand_mark)
        left.addLayout(self.logo_slot)

        status = QWidget()
        status.setObjectName("headerStatus")
        st = self._spaced.add(QVBoxLayout(status), spacing=1, margins=0)

        self.vfd_box = QFrame()
        self.vfd_box.setObjectName("telemetryDisplay")
        vfd = self._spaced.add(QHBoxLayout(self.vfd_box), spacing=1, margins=(1, 0, 1, 0))
        self.vfd_stat = ElidedLabel("DSP: OFF", min_chars=3)
        self.vfd_stat.setObjectName("vfdStat")
        self.vfd_sr = ElidedLabel("-- kHz", min_chars=3)
        self.vfd_sr.setObjectName("vfdValue")
        self.vfd_buf = ElidedLabel("-- SMP", min_chars=3)
        self.vfd_buf.setObjectName("vfdValue")
        self.vfd_lat = ElidedLabel("-- ms", min_chars=3)
        self.vfd_lat.setObjectName("vfdLatency")
        self.vfd_drv = ElidedLabel("OFFLINE", min_chars=3)
        self.vfd_drv.setObjectName("vfdDriver")
        for w in (self.vfd_stat, self.vfd_sr, self.vfd_buf, self.vfd_lat, self.vfd_drv):
            vfd.addWidget(w)
        vfd.addStretch()
        st.addWidget(self.vfd_box)

        controls = QHBoxLayout()
        self._spaced.add(controls, spacing=1, margins=0)
        self.idle_combo = QComboBox()
        self.idle_combo.setObjectName("idleCombo")
        self.idle_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.idle_combo.setMinimumContentsLength(10)
        self.idle_combo.setToolTip("What your microphone sends when no chain is active")
        controls.addWidget(self.idle_combo, 1)

        self.hotkeys_toggle = QToolButton()
        self.hotkeys_toggle.setObjectName("hotkeysToggle")
        self.hotkeys_toggle.setText("Hotkeys")
        self.hotkeys_toggle.setCheckable(True)
        self.hotkeys_toggle.setChecked(cfg.hotkeys_enabled)
        self.hotkeys_toggle.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.hotkeys_toggle.setPopupMode(QToolButton.MenuButtonPopup)
        self.hotkeys_toggle.setToolTip("Global hotkeys on / off (arrow: all-off key)")
        self.hotkeys_menu = QMenu(self.hotkeys_toggle)
        self.panic_key_action = self.hotkeys_menu.addAction("All-off key: not set…")
        self.hotkeys_toggle.setMenu(self.hotkeys_menu)
        controls.addWidget(self.hotkeys_toggle)
        st.addLayout(controls)
        left.addWidget(status)
        top.addWidget(self.left)

        # ---------------------------------------------------------- middle zone
        self.flow_strip = SignalFlowStrip(core, self)
        top.addWidget(self.flow_strip, 1)

        # ----------------------------------------------------------- right zone
        self.right = _zone("headerRight")
        right = self._spaced.add(QHBoxLayout(self.right), spacing=2, margins=0)

        self.fold_box = QWidget()
        self.fold_box.setObjectName("headerFoldable")
        fold = self._spaced.add(QHBoxLayout(self.fold_box), spacing=2, margins=0)
        self.audition_btn = make_button(
            AUDITION_IDLE_TEXT, "secondary", icon="mic",
            tooltip="Record 5 seconds of your dry voice and loop it through the active rack so "
                    "you can audition knobs without speaking")
        self.audition_btn.setObjectName("hardwareAuditionBtn")
        fold.addWidget(self.audition_btn)
        self.monitor = make_button("Monitor", "secondary", icon="monitor",
                                   tooltip="Listen to your output in your headphones")
        self.monitor.setCheckable(True)
        self.monitor.setChecked(cfg.monitor_enabled)
        self.monitor.setObjectName("hardwareMonitorToggle")
        fold.addWidget(self.monitor)
        right.addWidget(self.fold_box)

        self.more_btn = make_button("More", "secondary", icon="menu",
                                    tooltip="Signal-flow steps and actions that do not fit the header")
        self.more_btn.setObjectName("headerMoreBtn")
        self.more_menu = QMenu(self.more_btn)
        # The flow strip's actions, for when the strip is hidden (spec 7.6: below ~1100 px).
        self.act_prefx = self.more_menu.addAction("Mic cleanup (Pre-FX)…")
        self.act_prefx.triggered.connect(self.flow_strip.prefxClicked.emit)
        self.act_soundboard = self.more_menu.addAction("Soundboard…")
        self.act_soundboard.triggered.connect(self.flow_strip.soundboardClicked.emit)
        self.act_limiter = self.more_menu.addAction("Output limiter")
        self.act_limiter.setCheckable(True)
        self.act_limiter.triggered.connect(self._limiter_from_menu)
        self._flow_sep = self.more_menu.addSeparator()
        # Test mic and Monitor, for when the right-zone actions are folded (below 1180 px).
        self.act_audition = self.more_menu.addAction("Test mic (5 s)")
        self.act_audition.triggered.connect(self.audition_btn.click)
        self.act_monitor = self.more_menu.addAction("Monitor output (Phones)")
        self.act_monitor.setCheckable(True)
        self.act_monitor.setChecked(self.monitor.isChecked())
        self.act_monitor.triggered.connect(self.monitor.setChecked)
        self.monitor.toggled.connect(self.act_monitor.setChecked)
        self.more_menu.aboutToShow.connect(self._sync_more_menu)
        self.more_btn.setMenu(self.more_menu)
        self.more_btn.setVisible(False)
        right.addWidget(self.more_btn)

        self.panic_btn = make_button("Panic", "danger", icon="panic",
                                     tooltip="Turn all effect chains off immediately")
        self.panic_btn.setObjectName("hardwarePanicCut")
        right.addWidget(self.panic_btn)

        self.settings_btn = make_button(tier="quiet", icon="settings", tooltip="Settings")
        self.settings_btn.setObjectName("headerSettingsBtn")
        right.addWidget(self.settings_btn)

        self.help_btn = make_button(tier="quiet", icon="help", tooltip="Help, about and licences")
        self.help_btn.setObjectName("headerHelpBtn")
        self.help_menu = QMenu(self.help_btn)
        self.help_btn.setMenu(self.help_menu)
        right.addWidget(self.help_btn)
        self._right_screw = RackScrew(16)
        right.addWidget(self._right_screw)
        top.addWidget(self.right)

        # Header actions use the small type size (the zones are tight at 1024 px).
        for b in (self.power, self.audition_btn, self.monitor, self.more_btn, self.panic_btn):
            b.setProperty("small", "true")
        # Texts that change at run time must not move the zones around.
        reserve_text_width(self.power, POWER_OFF_TEXT, POWER_ON_TEXT)
        # The readout shows these at run time (see MainWindow._update_status); reserve the
        # widest of each so the fixed left zone never grows when audio starts.
        for key, label in self.readout_fields().items():
            reserve_text_width(label, *READOUT_SAMPLES[key])
            label.setFixedWidth(label.minimumWidth())
        reserve_text_width(self.audition_btn, *AUDITION_TEXTS)

        # Hidden widgets are not polished until shown; their size hints are needed before.
        # (Never polish from inside a size hint or an event handler: it re-enters the
        # stylesheet style.)
        self.more_btn.ensurePolished()
        self._folded: bool | None = None
        self._syncing_more = self._resync_more = False
        self.flow_strip.modeChanged.connect(self._sync_more_button)
        self.flow_strip.reclaimable_width = self._more_width_if_only_for_flow
        self.apply_window_width(FLOW_ICONS_BELOW)
        _follow_look(self)

    def readout_fields(self) -> dict:
        return {"stat": self.vfd_stat, "sr": self.vfd_sr, "buf": self.vfd_buf,
                "lat": self.vfd_lat, "drv": self.vfd_drv}

    # ------------------------------------------------------------ breakpoints
    def apply_window_width(self, width: int) -> None:
        """Fold the right-zone actions and request a flow-strip mode for a window ``width``."""
        folded = width < ACTIONS_OVERFLOW_BELOW
        if folded != self._folded:
            self._folded = folded
            self.fold_box.setVisible(not folded)
        self.flow_strip.set_requested_mode(flow_mode_for_width(width))
        self._sync_more_button()

    def _sync_more_button(self, _mode: str | None = None) -> None:
        """MORE shows while anything lives only in its menu: folded actions or a hidden
        flow strip. Each menu item shows only while its own control is not on screen.

        Showing or hiding MORE resizes the strip, which may change its mode and call back
        in here; such nested calls are folded into another pass of the outer call, so the
        final state always matches the strip's final mode."""
        if self._syncing_more:
            self._resync_more = True
            return
        self._syncing_more = True
        try:
            for _ in range(4):
                self._resync_more = False
                self._apply_more_state()
                if not self._resync_more:
                    break
        finally:
            self._syncing_more = False

    def _apply_more_state(self) -> None:
        flow_hidden = self.flow_strip.mode() == "hidden"
        folded = bool(self._folded)
        for act in (self.act_prefx, self.act_soundboard, self.act_limiter):
            act.setVisible(flow_hidden)
        for act in (self.act_audition, self.act_monitor):
            act.setVisible(folded)
        self._flow_sep.setVisible(flow_hidden and folded)
        show = folded or flow_hidden
        if self.more_btn.isHidden() == show:
            self.more_btn.setVisible(show)

    def _more_width_if_only_for_flow(self) -> int:
        """MORE's width while it is shown only for the hidden strip's actions."""
        if self._folded or self.more_btn.isHidden():
            return 0
        return self.more_btn.width() + self.right.layout().spacing()

    def _limiter_from_menu(self, _checked: bool = False) -> None:
        self.flow_strip.limiterClicked.emit()

    def flow_entry_points(self) -> dict[str, list[str]]:
        """For each flow-strip action, the controls currently on screen that trigger it
        (a strip button, or the MORE menu item while MORE is shown)."""
        strip = self.flow_strip
        mode = strip.mode()
        steps = {"prefx": self.act_prefx, "sb": self.act_soundboard, "lim": self.act_limiter}
        found: dict[str, list[str]] = {}
        for key, act in steps.items():
            where = []
            button = strip.step_button(key, mode)
            if button is not None and button.isVisible():
                where.append(f"strip-{mode}:{key}")
            if self.more_btn.isVisible() and act.isVisible():
                where.append(f"more:{act.text()}")
            found[key] = where
        return found

    def actions_folded(self) -> bool:
        return bool(self._folded)

    def flow_mode(self) -> str:
        return self.flow_strip.mode()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """Always the folded header's minimum: left zone + 1 px of flow strip + the folded
        right zone (MORE, Panic, Settings, Help). Computed from size hints, never from what
        is visible right now, so it does not change when the header folds or the strip
        hides (the window's minimum would otherwise depend on, and lag behind, its width)."""
        s = super().minimumSizeHint()
        top = self.layout()
        m = top.contentsMargins()
        right = self.right.layout()
        rm = right.contentsMargins()
        folded = (self.more_btn, self.panic_btn, self.settings_btn, self.help_btn,
                  self._right_screw)
        right_w = (rm.left() + rm.right() + right.spacing() * (len(folded) - 1)
                   + sum(max(w.sizeHint().width(), w.minimumWidth()) for w in folded))
        s.setWidth(m.left() + m.right() + 2 * top.spacing()
                   + self.left.sizeHint().width() + 1 + right_w)
        return s

    def _sync_more_menu(self) -> None:
        self.act_audition.setText("Stop test mic" if self.audition_btn.text() != AUDITION_IDLE_TEXT
                                  else "Test mic (5 s)")
        self.act_monitor.setChecked(self.monitor.isChecked())
        self.act_limiter.setChecked(bool(self.core.cfg.limiter.enabled))

    def _on_look_changed(self) -> None:
        self._spaced.apply()
