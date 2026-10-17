"""Main window header: three zones (spec 7.6).

* **left** (fixed): rack screw, pilot lamp, power, a slot for the logo mark (Task 11) and the
  status zone: the DSP readout over the idle-mode dropdown and the hotkeys switch (whose menu
  sets the all-off key).
* **middle** (flexible): the signal-flow strip; its steps drop to short tags below
  ``FLOW_ICONS_BELOW`` and it hides below ``FLOW_HIDDEN_BELOW`` (window widths).
* **right** (fixed): Test mic, Monitor, Panic, Settings, Help; below
  ``ACTIONS_OVERFLOW_BELOW`` Test mic and Monitor fold into an overflow menu.

The header's minimum width is always the folded one, so the window can shrink to 1024 px
whatever state the header is in.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ...core import Core
from .base import SpacedLayouts, _follow_look, reserve_text_width
from .chassis import RackScrew
from .flow_strip import SignalFlowStrip
from .lamps import PilotLamp

FLOW_ICONS_BELOW = 1400
FLOW_HIDDEN_BELOW = 1100
ACTIONS_OVERFLOW_BELOW = 1180
STRIPS_COLLAPSE_BELOW_H = 800

AUDITION_IDLE_TEXT = "TEST MIC"


def flow_mode_for_width(width: int) -> str:
    if width < FLOW_HIDDEN_BELOW:
        return "hidden"
    if width < FLOW_ICONS_BELOW:
        return "icons"
    return "full"


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

        self.power = QPushButton("MASTER POWER")
        self.power.setCheckable(True)
        self.power.setObjectName("hardwareMasterToggle")
        self.power.setToolTip("Start or stop the audio engine")
        left.addWidget(self.power)

        # Task 11 puts the logo mark here.
        self.logo_slot = QHBoxLayout()
        self.logo_slot.setContentsMargins(0, 0, 0, 0)
        left.addLayout(self.logo_slot)

        status = QWidget()
        status.setObjectName("headerStatus")
        st = self._spaced.add(QVBoxLayout(status), spacing=1, margins=0)

        self.vfd_box = QFrame()
        self.vfd_box.setObjectName("telemetryDisplay")
        vfd = self._spaced.add(QHBoxLayout(self.vfd_box), spacing=2, margins=(2, 0, 2, 0))
        self.vfd_stat = QLabel("DSP: OFF")
        self.vfd_stat.setObjectName("vfdStat")
        self.vfd_sr = QLabel("-- kHz")
        self.vfd_sr.setObjectName("vfdValue")
        self.vfd_buf = QLabel("-- SMP")
        self.vfd_buf.setObjectName("vfdValue")
        self.vfd_lat = QLabel("-- ms")
        self.vfd_lat.setObjectName("vfdLatency")
        self.vfd_drv = QLabel("OFFLINE")
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
        self.hotkeys_toggle.setText("HOTKEYS")
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
        self.audition_btn = QPushButton(AUDITION_IDLE_TEXT)
        self.audition_btn.setObjectName("hardwareAuditionBtn")
        self.audition_btn.setToolTip(
            "Record 5 seconds of your dry voice and loop it through the active rack so you can "
            "audition knobs without speaking")
        fold.addWidget(self.audition_btn)
        self.monitor = QPushButton("MONITOR")
        self.monitor.setCheckable(True)
        self.monitor.setChecked(cfg.monitor_enabled)
        self.monitor.setObjectName("hardwareMonitorToggle")
        self.monitor.setToolTip("Listen to your output in your headphones")
        fold.addWidget(self.monitor)
        right.addWidget(self.fold_box)

        self.more_btn = QPushButton("MORE")
        self.more_btn.setObjectName("hardwareConfigBtn")
        self.more_btn.setToolTip("Test mic and Monitor")
        self.more_menu = QMenu(self.more_btn)
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

        self.panic_btn = QPushButton("PANIC")
        self.panic_btn.setObjectName("hardwarePanicCut")
        self.panic_btn.setToolTip("Turn all effect chains off immediately")
        right.addWidget(self.panic_btn)

        self.settings_btn = QPushButton("SETTINGS")
        self.settings_btn.setObjectName("hardwareConfigBtn")
        right.addWidget(self.settings_btn)

        self.help_btn = QPushButton("HELP")
        self.help_btn.setObjectName("hardwareConfigBtn")
        self.help_menu = QMenu(self.help_btn)
        self.help_btn.setMenu(self.help_menu)
        right.addWidget(self.help_btn)
        right.addWidget(RackScrew(16))
        top.addWidget(self.right)

        # Texts that change at run time must not move the zones around.
        reserve_text_width(self.power, "MASTER POWER", "AUDIO ACTIVE")
        reserve_text_width(self.vfd_stat, "DSP: OFF", "DSP: 100%")
        reserve_text_width(self.vfd_sr, "192 kHz")
        reserve_text_width(self.vfd_buf, "2048 SMP")
        reserve_text_width(self.vfd_lat, "999.9 ms")
        reserve_text_width(self.vfd_drv, "OFFLINE", "WASAPI", "ASIO", "MME")
        reserve_text_width(self.audition_btn, "REC 5.0s", "STOP LOOP")

        # Hidden widgets are not polished until shown; their size hints are needed before.
        # (Never polish from inside a size hint or an event handler: it re-enters the
        # stylesheet style.)
        self.more_btn.ensurePolished()
        self._folded: bool | None = None
        self.apply_window_width(FLOW_ICONS_BELOW)
        _follow_look(self)

    # ------------------------------------------------------------ breakpoints
    def apply_window_width(self, width: int) -> None:
        """Fold the right-zone actions and request a flow-strip mode for a window ``width``."""
        folded = width < ACTIONS_OVERFLOW_BELOW
        if folded != self._folded:
            self._folded = folded
            self.fold_box.setVisible(not folded)
            self.more_btn.setVisible(folded)
        self.flow_strip.set_requested_mode(flow_mode_for_width(width))

    def actions_folded(self) -> bool:
        return bool(self._folded)

    def flow_mode(self) -> str:
        return self.flow_strip.mode()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """Always the folded header's minimum (the folded width is reachable from any state)."""
        s = super().minimumSizeHint()
        if not self._folded:
            s.setWidth(s.width() - self.fold_box.sizeHint().width() + self.more_btn.sizeHint().width())
        return s

    def _sync_more_menu(self) -> None:
        self.act_audition.setText("Stop test mic" if self.audition_btn.text() != AUDITION_IDLE_TEXT
                                  else "Test mic (5 s)")
        self.act_monitor.setChecked(self.monitor.isChecked())

    def _on_look_changed(self) -> None:
        self._spaced.apply()
