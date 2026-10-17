"""The main window: the chain editor and the rack/console window around it."""
from __future__ import annotations

import os
import threading
import time
from functools import partial

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QSplitter,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import branding
from .. import devices as D
from .. import plugins as P
from ..audio_engine import DRY_ID
from ..config import Chain, PluginSlot
from ..core import Core, inst, slot_error
from ..factory_presets import get_factory_presets, instantiate_factory_preset
from .dialogs.add_plugin import AddPluginDialog
from .dialogs.hotkey import HotkeyDialog
from .dialogs.param_map import PluginParamMapDialog
from .dialogs.prefx import PreFXDialog
from .dialogs.settings import SettingsDialog
from .dialogs.setup_assistant import SetupAssistantDialog
from .dialogs.soundboard import SoundboardDialog
from .look import look_bus, space
from .widgets.base import SpacedLayouts, _follow_look, reserve_text_width, set_style_property
from .widgets.buttons import make_button, set_button_icon, set_button_state
from .widgets.chain_card import ChainCardWidget
from .widgets.channel_strip import ChannelDot, ChannelStripCard
from .widgets.chassis import ChassisWrapperFrame
from .widgets.header import (AUDITION_IDLE_TEXT, POWER_OFF_TEXT, POWER_ON_TEXT,
                             STRIPS_COLLAPSE_BELOW_H, HeaderBar)
from .widgets.knobs import HardwareKnob
from .widgets.labels import ElidedLabel
from .widgets.lists import CardListWidget
from .widgets.meters import LevelMeter, ThinLevelMeter
from .widgets.plugin_card import PluginRackCard
from .widgets.sliders import GainSlider
from .widgets.switches import HardwareSwitch

LEFT_PANEL_MIN = 240
LEFT_PANEL_MAX = 420
# A rack list item's height beyond its card: the stylesheet's item padding (2 px a side)
# and margin-bottom (6 px).
RACK_ITEM_CHROME = 2 * 2 + 6
SET_KEY_TEXT = "Set key"
LIVE_OFF_TEXT = "Set live on mic"
LIVE_ON_TEXT = "Live on mic"
STANDBY_TEXT = "Standby"
FADERS_COLLAPSE_TEXT = "Collapse faders"
FADERS_EXPAND_TEXT = "Expand faders"
# Channel marker colours: identification only, so the output channel is neutral (a status
# colour there read as an error).
CHANNEL_TOKENS = {"in": "status.ok", "out": "text.primary", "mon": "readout.text"}


# =============================================================== chain editor
class ChainEditor(QWidget):
    chainEdited = Signal()          # name/hotkey/mode changed -> refresh list
    openEditor = Signal(object)     # PluginSlot

    def __init__(self, core: Core):
        super().__init__()
        self.core = core
        self.chain: Chain | None = None
        self._spaced = SpacedLayouts()
        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=0)

        # Rack Bay Outer Container
        rack_bay = QFrame()
        rack_bay.setObjectName("modularBay")
        rb_lay = self._spaced.add(QVBoxLayout(rack_bay), spacing=2, margins=(3, 2, 3, 2))

        # Rack Bay Header
        rb_hdr = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.hdr_static = QLabel("EFFECTS RACK  //  BUS:")
        self.hdr_static.setObjectName("rackBusLabel")
        rb_hdr.addWidget(self.hdr_static)

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("rackBusNameEdit")
        self.name_edit.setPlaceholderText("PRESET NAME")
        self.name_edit.setToolTip("Click to rename this voice preset bus")
        self.name_edit.setMinimumWidth(120)
        self.name_edit.setMaximumWidth(280)

        self.name = self.name_edit  # backward compatibility alias
        rb_hdr.addWidget(self.name_edit, 1)
        rb_hdr.addStretch()

        self.add_btn = make_button("Insert plugin", "primary", icon="plus",
                                   tooltip="Add a VST3 plugin or built-in effect to this preset")
        self.add_btn.setObjectName("rackInsertBtn")
        rb_hdr.addWidget(self.add_btn)
        rb_lay.addLayout(rb_hdr)

        # One-row inspector: each caption sits above its control so the row stays narrow.
        insp_box = QFrame()
        insp_box.setObjectName("inspectorBox")
        insp_lay = self._spaced.add(QHBoxLayout(insp_box), spacing=2, margins=(2, 1, 2, 1))

        def captioned(caption: str, widget: QWidget) -> QVBoxLayout:
            col = self._spaced.add(QVBoxLayout(), spacing=1, margins=0)
            lbl = QLabel(caption)
            lbl.setObjectName("rackInspLabel")
            col.addStretch()
            col.addWidget(lbl)
            col.addWidget(widget)
            col.addStretch()
            return col

        # Hotkey section
        self.hk_btn = make_button(SET_KEY_TEXT, "secondary", icon="hotkey",
                                  tooltip="Hotkey that turns this preset on")
        self.hk_btn.setProperty("small", "true")
        self.hk_btn.setObjectName("rackHotkeyBtn")
        self.hk_label = QLabel("—")
        self.hk_label.setVisible(False)
        insp_lay.addLayout(captioned("HOTKEY", self.hk_btn))

        # Mode section
        self.mode = QComboBox()
        self.mode.addItem("Toggle", "toggle")
        self.mode.addItem("Hold", "hold")
        insp_lay.addLayout(captioned("TRIGGER", self.mode))

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setObjectName("inspectorSeparator")
        insp_lay.addWidget(sep1)

        # Rotary Knobs
        self.knob_gain = HardwareKnob("GAIN", min_val=-60.0, max_val=12.0, default_val=0.0, suffix=" dB", decimals=1)
        self.knob_wet = HardwareKnob("DRY/WET", min_val=0.0, max_val=100.0, default_val=100.0, suffix="%", decimals=0)
        self.knob_tail = HardwareKnob("TAIL", min_val=0.0, max_val=10.0, default_val=0.0, suffix=" s", decimals=1)

        insp_lay.addWidget(self.knob_gain)
        insp_lay.addWidget(self.knob_wet)
        insp_lay.addWidget(self.knob_tail)

        # Proxies for backward compatibility
        class _SpinProxy:
            def __init__(self, knob, scale=1.0):
                self._k = knob
                self._scale = scale
            def value(self):
                return self._k.value() * self._scale
            def setValue(self, v):
                self._k.setValue(v / self._scale, emit=False)
        self.gain = _SpinProxy(self.knob_gain)
        self.dry_wet = _SpinProxy(self.knob_wet, scale=1.0)
        self.tail = _SpinProxy(self.knob_tail)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setObjectName("inspectorSeparator")
        insp_lay.addWidget(sep2)

        # DSP Latency chip
        self.lat_lbl = ElidedLabel("0.0 ms (0 smp)", min_chars=6)
        self.lat_lbl.setObjectName("rackLatency")
        self.lat_lbl.setBaseToolTip("Total plugin latency of this chain")
        insp_lay.addLayout(captioned("LATENCY", self.lat_lbl), 1)

        # Live on Mic Toggle Button
        self.live_btn = make_button(LIVE_OFF_TEXT, "secondary", icon="record",
                                    tooltip="Click to toggle this preset live on your microphone output")
        self.live_btn.setObjectName("rackLiveToggle")
        insp_lay.addWidget(self.live_btn)
        self.test_btn = self.live_btn  # backward compatibility alias

        rb_lay.addWidget(insp_box)

        # The 1U Modular Effects Rack List
        # Cards re-fit whenever the viewport width changes, in both directions (Task 9b).
        self.plugins = CardListWidget()
        self.plugins.setObjectName("rackList")
        self.plugins.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rb_lay.addWidget(self.plugins, 1)

        lay.addWidget(rack_bay, 1)
        reserve_text_width(self.live_btn, LIVE_OFF_TEXT, LIVE_ON_TEXT, STANDBY_TEXT)
        _follow_look(self)

        self.name_edit.editingFinished.connect(self._rename)
        self.hk_btn.clicked.connect(self._set_hotkey)
        self.mode.currentIndexChanged.connect(self._mode)
        self.knob_gain.valueChanged.connect(self._params)
        self.knob_wet.valueChanged.connect(self._params)
        self.knob_tail.valueChanged.connect(self._params)
        self.add_btn.clicked.connect(self._add)
        self.live_btn.clicked.connect(self._toggle_live)

    def _on_look_changed(self):
        self._spaced.apply()
        self._fit_rack_width()

    def _fit_rack_width(self):
        """The rack list is as wide as its widest card needs, so the splitter squeezes the
        preset panel (down to its minimum) before it squeezes the cards."""
        need = 0
        for i in range(self.plugins.count()):
            card = self.plugins.itemWidget(self.plugins.item(i))
            if card is not None:
                card.ensurePolished()
                need = max(need, card.minimumSizeHint().width())
        if need:
            # frame + scroll bar + the list's and items' stylesheet padding (4 px and 2 px a side)
            need += (2 * self.plugins.frameWidth() + self.plugins.verticalScrollBar().sizeHint().width()
                     + 2 * (4 + 2))
        self.plugins.setMinimumWidth(need)

    def _toggle_live(self):
        if self.chain:
            self.core.press(self.chain.id)

    def set_chain(self, chain: Chain | None):
        self.chain = chain
        self.setEnabled(chain is not None)
        if chain is None:
            self.name_edit.setText("")
            self.hk_btn.setText(SET_KEY_TEXT)
            self.plugins.clear()
            self.lat_lbl.setText("0.0 ms (0 smp)")
            self.live_btn.setText(STANDBY_TEXT)
            return
        self.name_edit.setText(chain.name)
        self.hk_btn.setText(chain.hotkey.label if chain.hotkey.is_set() else SET_KEY_TEXT)
        self.mode.setCurrentIndex(max(0, self.mode.findData(chain.mode)))
        self.knob_gain.setValue(chain.gain_db, emit=False)
        self.knob_wet.setValue(getattr(chain, "dry_wet", 1.0) * 100.0, emit=False)
        self.knob_tail.setValue(chain.tail_s, emit=False)
        self.refresh_plugins()

    def refresh_plugins(self, select_row: int | None = None):
        self.plugins.blockSignals(True)
        self.plugins.clear()
        if self.chain:
            sr = self.core.engine.samplerate or 48000
            tot_samples = P.get_chain_latency_samples(self.chain)
            ms = (tot_samples / sr) * 1000.0
            self.lat_lbl.setText(f"{ms:.1f} ms ({tot_samples} smp)")

            for idx, s in enumerate(self.chain.plugins):
                card = PluginRackCard(s, self.chain, self.core, self)
                card.powerToggled.connect(lambda en, slot=s: self._toggle_slot(slot, en))
                card.editClicked.connect(lambda slot=s: self.openEditor.emit(slot))
                card.mapClicked.connect(lambda slot=s: self._map_slot_params(slot))
                card.hotkeyClicked.connect(lambda slot=s: self._set_slot_bypass_hotkey_for(slot))
                card.moveUpClicked.connect(lambda slot=s: self._move_slot(slot, -1))
                card.moveDownClicked.connect(lambda slot=s: self._move_slot(slot, 1))
                card.removeClicked.connect(lambda slot=s: self._remove_slot(slot))
                card.macrosCollapseToggled.connect(lambda r=idx: self.refresh_plugins(select_row=r))

                it = QListWidgetItem()
                card_h = 132 if card.has_knobs() else 58
                card.ensurePolished()
                need = card.minimumSizeHint().height() + RACK_ITEM_CHROME
                it.setSizeHint(QSize(1, max(card_h, need)))
                self.plugins.addItem(it)
                self.plugins.setItemWidget(it, card)

        self.plugins.blockSignals(False)
        self._fit_rack_width()
        if select_row is not None and self.chain and 0 <= select_row < len(self.chain.plugins):
            self.plugins.setCurrentRow(select_row)

    def _map_slot_params(self, slot: PluginSlot):
        if inst(slot) is None:
            QMessageBox.warning(self, "Plugin not loaded", slot_error(slot) or "This plugin is not loaded.")
            return
        dlg = PluginParamMapDialog(slot, self.core, self)
        if dlg.exec():
            self.core.save_plugin_param_mapping(slot, dlg.selected_keys)
            if self.chain and slot in self.chain.plugins:
                self.refresh_plugins(select_row=self.chain.plugins.index(slot))

    def tick_plugin_meters(self, running: bool, sync_knobs: bool = False):
        for i in range(self.plugins.count()):
            it = self.plugins.item(i)
            card = self.plugins.itemWidget(it) if it is not None else None
            if isinstance(card, PluginRackCard):
                s = card.slot
                pre_pk = float(getattr(s, "_pre_peak", 0.0)) if running else 0.0
                post_pk = float(getattr(s, "_post_peak", 0.0)) if (running and s.enabled) else 0.0
                s._pre_peak = 0.0
                s._post_peak = 0.0
                card.pre_post_meter.push(pre_pk, post_pk, enabled=s.enabled)
                if sync_knobs:
                    card.sync_knobs_from_plugin()

    def _toggle_slot(self, slot: PluginSlot, enabled: bool):
        if self.chain and slot in self.chain.plugins:
            self.core.set_plugin_enabled(self.chain, slot, enabled)
            self.refresh_plugins(select_row=self.chain.plugins.index(slot))

    def _move_slot(self, slot: PluginSlot, d: int):
        if self.chain and slot in self.chain.plugins:
            self.core.move_plugin(self.chain, slot, d)
            self.refresh_plugins(select_row=self.chain.plugins.index(slot))

    def _remove_slot(self, slot: PluginSlot):
        if self.chain and slot in self.chain.plugins:
            self.core.remove_plugin(self.chain, slot)
            self.refresh_plugins()

    def _set_slot_bypass_hotkey_for(self, slot: PluginSlot):
        dlg = HotkeyDialog(self.core, self, f"Bypass Hotkey for “{slot.display_name}”")
        if dlg.exec() and dlg.result_hotkey is not None:
            hk = dlg.result_hotkey
            if hk.is_set():
                clash = self.core.find_hotkey_conflict(hk, exclude=slot.bypass_hotkey)
                if clash:
                    QMessageBox.warning(self, "Hotkey in use", f"{hk.label} is already used by {clash}.")
                    return
            slot.bypass_hotkey = hk
            self.core.rebind_hotkeys()
            self.core.save()
            if self.chain and slot in self.chain.plugins:
                self.refresh_plugins(select_row=self.chain.plugins.index(slot))



    def _slot(self) -> PluginSlot | None:
        r = self.plugins.currentRow()
        if self.chain and 0 <= r < len(self.chain.plugins):
            return self.chain.plugins[r]
        return None

    def _rename(self):
        if self.chain and self.name.text().strip() and self.name.text() != self.chain.name:
            self.chain.name = self.name.text().strip()
            self.core.save()
            self.chainEdited.emit()

    def _set_hotkey(self):
        if not self.chain:
            return
        dlg = HotkeyDialog(self.core, self, f"Hotkey for “{self.chain.name}”")
        if dlg.exec() and dlg.result_hotkey is not None:
            hk = dlg.result_hotkey
            if hk.is_set():
                clash = self.core.find_hotkey_conflict(hk, exclude=self.chain.hotkey)
                if clash:
                    QMessageBox.warning(self, "Hotkey in use", f"{hk.label} is already used by {clash}.")
                    return
            self.core.release(self.chain.id)
            self.chain.hotkey = hk
            self.core.rebind_hotkeys()
            self.core.save()
            self.set_chain(self.chain)
            self.chainEdited.emit()

    def _mode(self):
        if self.chain:
            self.chain.mode = self.mode.currentData()
            self.core.clear_chain_state(self.chain.id)
            self.core.save()
            self.chainEdited.emit()

    def _params(self):
        if self.chain:
            self.chain.gain_db = self.gain.value()
            self.chain.dry_wet = self.dry_wet.value() / 100.0
            self.chain.tail_s = self.tail.value()
            self.core.update_chain_params(self.chain)

    def _add(self):
        if not self.chain:
            return
        dlg = AddPluginDialog(self.core.cfg.extra_plugin_dirs, self)
        if not dlg.exec() or not dlg.path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            names = P.plugin_names_in_file(dlg.path)
        finally:
            QApplication.restoreOverrideCursor()
        plugin_name = ""
        if len(names) > 1:
            plugin_name, ok = QInputDialog.getItem(self, "Choose plugin",
                                                   "This file contains several plugins:", names, 0, False)
            if not ok:
                return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            slot = self.core.add_plugin(self.chain, dlg.path, plugin_name)
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_plugins(select_row=len(self.chain.plugins) - 1)
        if slot_error(slot):
            QMessageBox.warning(self, "Plugin failed to load", f"{dlg.path}\n\n{slot_error(slot)}")

def _monitor_and_center_plugin_window(plugin_title: str, parent_hwnd: int | None = None):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    my_pid = os.getpid()

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    for _ in range(80):
        found_hwnd = None

        def enum_cb(hwnd, _lparam):
            nonlocal found_hwnd
            if user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == my_pid:
                    buf = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, buf, 512)
                    if buf.value == "Pedalboard":
                        found_hwnd = hwnd
                        return False
            return True

        cb = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum_cb)
        user32.EnumWindows(cb, 0)

        if found_hwnd:
            user32.SetWindowTextW(found_hwnd, plugin_title)
            rect = wintypes.RECT()
            user32.GetWindowRect(found_hwnd, ctypes.byref(rect))
            w = max(100, rect.right - rect.left)
            h = max(100, rect.bottom - rect.top)

            ref_hwnd = parent_hwnd if (parent_hwnd and user32.IsWindow(parent_hwnd)) else found_hwnd
            hmon = user32.MonitorFromWindow(ref_hwnd, 2)

            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(hmon, ctypes.byref(mi))

            work_left = mi.rcWork.left
            work_top = mi.rcWork.top
            work_w = mi.rcWork.right - mi.rcWork.left
            work_h = mi.rcWork.bottom - mi.rcWork.top

            new_x = work_left + max(0, (work_w - w) // 2)
            new_y = work_top + max(0, (work_h - h) // 2)

            SWP_NOZORDER = 0x0004
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(found_hwnd, 0, new_x, new_y, w, h, SWP_NOZORDER | SWP_SHOWWINDOW)
            user32.BringWindowToTop(found_hwnd)
            user32.SetForegroundWindow(found_hwnd)
            break

        time.sleep(0.02)


# =============================================================== main window
class MainWindow(QMainWindow):
    def __init__(self, core: Core, show_tray: bool = True):
        """``show_tray=False`` builds the tray icon (the rest of the window updates it) but never shows it."""
        super().__init__()
        self.core = core
        self.cfg = core.cfg
        self._editor_event: threading.Event | None = None
        self._quitting = False
        self.setWindowTitle("Mandible")
        self.setWindowIcon(branding.app_icon())
        self.resize(1280, 820)
        self._spaced = SpacedLayouts()

        central = QWidget()
        root = self._spaced.add(QVBoxLayout(central), spacing=0, margins=2)
        self.setCentralWidget(central)

        # Outer 19" Rack Chassis
        self.chassis = ChassisWrapperFrame()
        self.chassis.setObjectName("rackChassis")
        ch_lay = QVBoxLayout(self.chassis)
        self.chassis.update_frame_margins()
        ch_lay.setSpacing(0)
        root.addWidget(self.chassis, 1)

        # ---- Header: left (power, logo, status) | middle (signal flow) | right (actions)
        self.header = HeaderBar(core, self)
        ch_lay.addWidget(self.header)
        h = self.header
        self.pilot_lamp = h.pilot_lamp
        self.power = h.power
        self.vfd_box = h.vfd_box
        self.vfd_stat, self.vfd_sr, self.vfd_buf = h.vfd_stat, h.vfd_sr, h.vfd_buf
        self.vfd_lat, self.vfd_drv = h.vfd_lat, h.vfd_drv
        self.flow_strip = h.flow_strip
        self.audition_btn = h.audition_btn
        self.audition_btn.clicked.connect(self._toggle_mic_audition)
        self.monitor = h.monitor
        self.panic_top_btn = h.panic_btn
        settings_btn = h.settings_btn
        h.help_menu.addAction("About Mandible…").triggered.connect(lambda: self._open_about(0))
        h.help_menu.addAction("Licenses…").triggered.connect(lambda: self._open_about(1))
        # The old bottom row (idle mode, hotkeys, all-off key) lives in the status zone.
        self.idle = h.idle_combo
        self.hk_enabled = h.hotkeys_toggle
        self.panic_key_action = h.panic_key_action

        # Retain aliases for backward compatibility
        self.clean_mic_btn = self.flow_strip.prefx_btn
        self.soundboard_btn = self.flow_strip.sb_btn
        self.status = QLabel("Stopped")
        self.status.setVisible(False)
        self.active_lbl = QLabel()
        self.active_lbl.setVisible(False)

        # ---- Body: Voice Presets Bank (left) | Effects Rack (right), split by a handle
        body_widget = QWidget()
        body_lay = self._spaced.add(QHBoxLayout(body_widget), spacing=0, margins=3)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("bodySplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(space(3))
        body_lay.addWidget(self.splitter)

        left = QFrame()
        left.setObjectName("sideRackBay")
        left.setMinimumWidth(LEFT_PANEL_MIN)
        left.setMaximumWidth(LEFT_PANEL_MAX)
        self.left_panel = left
        ll = self._spaced.add(QVBoxLayout(left), spacing=2, margins=0)

        # 1. Top: PRE-FX NOISE GATE Hardware Unit
        self.prefx_strip = QFrame()
        self.prefx_strip.setObjectName("prefxModule")
        self.prefx_strip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prefx_strip.setFixedHeight(36)
        pfx_lay = self._spaced.add(QHBoxLayout(self.prefx_strip), spacing=2, margins=(3, 0, 2, 0))

        # Name label (redundant left lamp removed; switch has its own jewel pilot light)
        pfx_lbl = ElidedLabel("PRE-FX NOISE GATE", min_chars=6)
        pfx_lbl.setObjectName("moduleTitle")
        pfx_lay.addWidget(pfx_lbl)

        pfx_lay.addStretch()

        pfx_active = bool(self.cfg.prefx.rnnoise_enabled or self.cfg.prefx.noise_gate_enabled)
        self.prefx_switch = HardwareSwitch(active=pfx_active, compact=False)
        self.prefx_switch.toggled.connect(lambda on: self._toggle_prefx_quick(on))
        pfx_lay.addWidget(self.prefx_switch)

        def on_pfx_click(e):
            if e.button() == Qt.MouseButton.RightButton:
                self._toggle_prefx_quick()
            else:
                self._open_prefx()
        self.prefx_strip.mousePressEvent = on_pfx_click
        self.prefx_strip.setToolTip("Left-click: Configure Pre-FX  ·  Right-click: Quick Toggle ON/BYPASS")
        ll.addWidget(self.prefx_strip)

        # 2. Middle: VOICE PRESET BANK (Recessed / Inset 500-Series Modular Bay)
        self.preset_bay = QFrame()
        self.preset_bay.setObjectName("presetModularBay")
        # 12 px inset, like the module strips above and below, so the three titles line up.
        pb_lay = self._spaced.add(QVBoxLayout(self.preset_bay), spacing=2, margins=3)

        # Title on its own row; factory / import / export share one menu button below it.
        chain_head = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        chain_title = ElidedLabel("VOICE PRESET BANK", min_chars=6)
        chain_title.setObjectName("bankTitle")
        chain_head.addWidget(chain_title, 1)
        pb_lay.addLayout(chain_head)

        self.library_btn = make_button("Library", "secondary", tooltip="Factory presets, import and export")
        self.library_btn.setProperty("small", "true")
        self.library_btn.setObjectName("presetBankBtn")
        self.library_menu = QMenu(self.library_btn)
        self.factory_menu = self.library_menu.addMenu("Factory presets (built-in effects)")
        for p_def in get_factory_presets():
            a = self.factory_menu.addAction(f"{p_def['name']}  ·  {p_def['desc']}")
            a.triggered.connect(partial(self._load_factory_preset, p_def))
        self.library_menu.addSeparator()
        act_imp = self.library_menu.addAction("Import preset (.mandible)…")
        act_exp = self.library_menu.addAction("Export selected preset (.mandible)…")
        self.library_btn.setMenu(self.library_menu)
        lib_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        lib_row.addWidget(self.library_btn)
        lib_row.addStretch()
        pb_lay.addLayout(lib_row)

        self.chain_list = CardListWidget()   # chain cards track the panel width
        self.chain_list.setObjectName("chainList")
        self.chain_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chain_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chain_list.customContextMenuRequested.connect(self._chain_context_menu)
        pb_lay.addWidget(self.chain_list, 1)

        # Presets toolbar: [+] [Duplicate] [Delete] [up] [down]
        cb = self._spaced.add(QHBoxLayout(), spacing=1, margins=0)
        add_c = make_button(tier="quiet", icon="plus", tooltip="New voice preset")
        dup_c = make_button("Duplicate", "secondary", tooltip="Duplicate the selected preset")
        del_c = make_button("Delete", "danger", tooltip="Delete the selected preset")
        for b in (dup_c, del_c):
            b.setProperty("small", "true")
        up_c = make_button(tier="quiet", icon="up", tooltip="Move preset earlier in bank")
        dn_c = make_button(tier="quiet", icon="down", tooltip="Move preset later in bank")
        for b in (add_c, dup_c, del_c, up_c, dn_c):
            cb.addWidget(b)
        cb.addStretch()
        pb_lay.addLayout(cb)
        ll.addWidget(self.preset_bay, 1)

        # 3. Bottom: output limiter unit (below toolbar)
        self.limiter_strip = QFrame()
        self.limiter_strip.setObjectName("limiterModule")
        self.limiter_strip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.limiter_strip.setFixedHeight(36)
        lim_lay = self._spaced.add(QHBoxLayout(self.limiter_strip), spacing=2, margins=(3, 0, 2, 0))

        # Name label (redundant left lamp removed; switch has its own jewel pilot light)
        lim_lbl = ElidedLabel("OUTPUT LIMITER", min_chars=6)
        lim_lbl.setObjectName("moduleTitle")
        lim_lay.addWidget(lim_lbl)

        lim_lay.addStretch()

        self.limiter_thresh_lbl = QLabel(f"{self.cfg.limiter.threshold_db:+.1f} dB")
        self.limiter_thresh_lbl.setObjectName("limiterThreshold")
        reserve_text_width(self.limiter_thresh_lbl, "-12.0 dB")
        lim_lay.addWidget(self.limiter_thresh_lbl)

        lim_active = bool(self.cfg.limiter.enabled)
        self.limiter_switch = HardwareSwitch(active=lim_active, compact=False)
        self.limiter_switch.toggled.connect(lambda on: self._toggle_limiter_quick(on))
        lim_lay.addWidget(self.limiter_switch)

        def on_lim_click(e):
            if e.button() == Qt.MouseButton.RightButton:
                self._open_limiter_settings()
            else:
                self._toggle_limiter_quick()
        self.limiter_strip.mousePressEvent = on_lim_click
        self.limiter_strip.setToolTip("Click to turn the output limiter on or off  ·  Right-click for its ceiling setting")
        ll.addWidget(self.limiter_strip)

        self.splitter.addWidget(left)
        self.editor = ChainEditor(core)
        self.splitter.addWidget(self.editor)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self._splitter_save = QTimer(self)
        self._splitter_save.setSingleShot(True)
        self._splitter_save.setInterval(500)
        self._splitter_save.timeout.connect(self.core.save)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self._restore_left_panel_width()
        ch_lay.addWidget(body_widget, 1)

        # ---- bottom calibrated meters & gain sliders (collapse to thin meters below 800 px tall)
        self.console_frame = QFrame()
        self.console_frame.setObjectName("consoleFrame")
        cf_lay = self._spaced.add(QVBoxLayout(self.console_frame), spacing=2, margins=(3, 1, 3, 2))

        cf_head = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        c_title = ElidedLabel("HARDWARE I/O CHANNEL STRIPS", min_chars=8)
        c_title.setObjectName("moduleTitle")
        cf_head.addWidget(c_title, 1)

        self.faders_collapsed = False
        self._faders_override: bool | None = None   # the user's choice beats the height rule
        self.collapse_faders_btn = make_button(FADERS_COLLAPSE_TEXT, "quiet", icon="chevron_down",
                                               tooltip="Show the channel strips as thin meters")
        self.collapse_faders_btn.setProperty("small", "true")
        self.collapse_faders_btn.setObjectName("collapseFadersBtn")

        self.collapse_faders_btn.clicked.connect(self._toggle_faders_collapse)
        cf_head.addWidget(self.collapse_faders_btn)
        cf_lay.addLayout(cf_head)

        # 1. Full Faders View (Meters + Faders)
        self.full_faders_widget = QWidget()
        # Same 12 px gutter as between the body columns (the splitter handle).
        meters = self._spaced.add(QHBoxLayout(self.full_faders_widget), spacing=3, margins=0)

        self.m_in = LevelMeter("CH 01  PRE-FX MIC IN")
        self.m_out = LevelMeter("CH 02  POST-FX BROADCAST")
        self.m_mon = LevelMeter("CH 03  HEADPHONE MONITOR")

        self.g_in = GainSlider("Trim", self.cfg.input_gain_db)
        self.g_out = GainSlider("Master", self.cfg.output_gain_db)
        self.g_mon = GainSlider("Phones", self.cfg.monitor_gain_db)

        in_name = self.cfg.audio.input_device or "No input"
        strip_in = ChannelStripCard(f"CH 01  MIC IN ({in_name})", CHANNEL_TOKENS["in"], self.m_in, self.g_in)
        strip_out = ChannelStripCard("CH 02  MAIN OUT (DISCORD / LOOPBACK)", CHANNEL_TOKENS["out"], self.m_out,
                                     self.g_out)
        strip_mon = ChannelStripCard("CH 03  HEADPHONES (MONITOR)", CHANNEL_TOKENS["mon"], self.m_mon, self.g_mon)

        meters.addWidget(strip_in, 1)
        meters.addWidget(strip_out, 1)
        meters.addWidget(strip_mon, 1)
        cf_lay.addWidget(self.full_faders_widget)

        # 2. Condensed Meter View (Thin level meters)
        self.condensed_faders_widget = QWidget()
        self.condensed_faders_widget.setVisible(False)
        cond_lay = self._spaced.add(QHBoxLayout(self.condensed_faders_widget), spacing=3, margins=0)

        def _make_condensed_strip(name: str, dot_token: str):
            box = QFrame()
            box.setObjectName("condensedStrip")
            b_lay = self._spaced.add(QHBoxLayout(box), spacing=2, margins=(2, 1, 2, 1))

            b_lay.addWidget(ChannelDot(dot_token, diameter=6))

            lbl = ElidedLabel(name, min_chars=6)
            lbl.setObjectName("condensedLabel")
            b_lay.addWidget(lbl)

            tm = ThinLevelMeter()
            b_lay.addWidget(tm, 1)
            return box, tm

        c_box_in, self.thin_m_in = _make_condensed_strip(f"CH 01 MIC ({in_name})", CHANNEL_TOKENS["in"])
        c_box_out, self.thin_m_out = _make_condensed_strip("CH 02 MAIN OUT", CHANNEL_TOKENS["out"])
        c_box_mon, self.thin_m_mon = _make_condensed_strip("CH 03 PHONES", CHANNEL_TOKENS["mon"])

        cond_lay.addWidget(c_box_in, 1)
        cond_lay.addWidget(c_box_out, 1)
        cond_lay.addWidget(c_box_mon, 1)
        cf_lay.addWidget(self.condensed_faders_widget)

        ch_lay.addWidget(self.console_frame)

        # ---- tray
        self._tray_on = False
        self._tray_light = branding.taskbar_is_light()
        self.tray = QSystemTrayIcon(branding.tray_icon(False), self)
        look_bus().lookChanged.connect(self._on_look_changed)
        menu = QMenu()
        act_show = QAction("Show Mandible", self)
        act_wizard = QAction("Audio Setup Assistant…", self)
        self.act_mon = QAction("Monitor output (Phones)", self, checkable=True)
        self.act_mon.setChecked(self.cfg.monitor_enabled)
        act_off = QAction("All chains off", self)
        act_about = QAction("About / Licenses…", self)
        act_quit = QAction("Quit", self)
        menu.addAction(act_show)
        menu.addAction(act_wizard)
        menu.addAction(self.act_mon)
        menu.addAction(act_off)
        menu.addSeparator()
        menu.addAction(act_about)
        act_about.triggered.connect(lambda: self._open_about(0))
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        act_show.triggered.connect(self.show_normal)
        act_wizard.triggered.connect(self._open_setup_assistant)
        self.act_mon.toggled.connect(self._tray_monitor_toggled)
        act_off.triggered.connect(core.panic)
        act_quit.triggered.connect(self.quit)
        if show_tray:
            self.tray.show()

        # ---- wiring
        self.power.toggled.connect(self._power)
        self.monitor.toggled.connect(self._monitor_toggled)
        self.panic_top_btn.clicked.connect(core.panic)
        settings_btn.clicked.connect(self._settings)

        self.flow_strip.prefxClicked.connect(self._open_prefx)
        self.flow_strip.soundboardClicked.connect(self._open_soundboard)
        self.flow_strip.limiterClicked.connect(self._toggle_limiter_quick)

        add_c.clicked.connect(self._add_chain)
        dup_c.clicked.connect(self._dup_chain)
        del_c.clicked.connect(self._del_chain)
        up_c.clicked.connect(lambda: self._move_chain(-1))
        dn_c.clicked.connect(lambda: self._move_chain(1))
        act_imp.triggered.connect(self._import_chain)
        act_exp.triggered.connect(self._export_chain)
        self.chain_list.currentRowChanged.connect(self._select_chain)
        self.chain_list.itemDoubleClicked.connect(self._chain_double_clicked)
        self.editor.chainEdited.connect(self.refresh_chains)
        self.editor.openEditor.connect(self.open_plugin_editor)
        self.g_in.changed.connect(core.set_input_gain)
        self.g_out.changed.connect(core.set_output_gain)
        self.g_mon.changed.connect(core.set_monitor_gain)
        self.idle.currentIndexChanged.connect(self._idle_changed)
        self.hk_enabled.toggled.connect(self._hk_toggled)
        self.panic_key_action.triggered.connect(self._set_panic)
        core.activeChanged.connect(self.refresh_active)
        core.pluginBypassChanged.connect(self._on_plugin_bypass_changed)
        core.gainsChanged.connect(self._on_gains_changed)
        core.engineStopped.connect(self._engine_stopped)
        core.auditionProgress.connect(self._on_audition_progress)

        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._tick)
        self.meter_timer.start(33)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(500)

        self._update_panic_label()
        self._apply_breakpoints()
        self._update_prefx_button_style()
        self.refresh_chains()
        self._update_limiter_ui()
        if self.cfg.chains:
            self.chain_list.setCurrentRow(0)

    # ------------------------------------------------------------ responsive layout
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._apply_breakpoints()

    def _apply_breakpoints(self):
        """Header zones follow the window width, the channel strips its height (spec 7.6)."""
        self.header.apply_window_width(self.width())
        self._apply_strip_collapse()
        self._restore_left_panel_width()

    def _apply_strip_collapse(self):
        if self._faders_override is not None:
            collapsed = self._faders_override
        else:
            collapsed = self.height() < STRIPS_COLLAPSE_BELOW_H
        if collapsed == self.faders_collapsed and self.condensed_faders_widget.isHidden() != collapsed:
            return
        self.faders_collapsed = collapsed
        self.full_faders_widget.setVisible(not collapsed)
        self.condensed_faders_widget.setVisible(collapsed)
        # Disclosure chevron: right while collapsed, down while expanded.
        self.collapse_faders_btn.setText(FADERS_EXPAND_TEXT if collapsed else FADERS_COLLAPSE_TEXT)
        set_button_icon(self.collapse_faders_btn, "chevron_right" if collapsed else "chevron_down")
        self.collapse_faders_btn.setToolTip("Show the full channel strips" if collapsed
                                            else "Show the channel strips as thin meters")

    def _toggle_faders_collapse(self):
        self._faders_override = not self.faders_collapsed
        self._apply_strip_collapse()

    def _left_panel_target(self) -> int:
        return max(LEFT_PANEL_MIN, min(LEFT_PANEL_MAX, int(self.cfg.left_panel_width or 0)))

    def _restore_left_panel_width(self):
        """Give the preset panel its remembered width (the splitter may have had to squeeze it
        while the window was narrow)."""
        want = self._left_panel_target()
        sizes = self.splitter.sizes()
        if len(sizes) == 2 and sizes[0] != want:
            total = sum(sizes) if sum(sizes) > 0 else want + 1000
            self.splitter.setSizes([want, max(1, total - want)])

    def _on_splitter_moved(self, _pos: int, _index: int):
        self.cfg.left_panel_width = max(LEFT_PANEL_MIN, min(LEFT_PANEL_MAX, self.splitter.sizes()[0]))
        self._splitter_save.start()

    def flush_pending_save(self):
        """Write a pending splitter-width save now (also done on quit)."""
        if self._splitter_save.isActive():
            self._splitter_save.stop()
            self.core.save()

    def _toggle_limiter_quick(self, target_state: bool | None = None):
        if target_state is not None:
            self.cfg.limiter.enabled = bool(target_state)
        else:
            self.cfg.limiter.enabled = not self.cfg.limiter.enabled
        self.core.set_limiter(self.cfg.limiter)
        self.core.save()
        self._update_limiter_ui()

    def _open_limiter_settings(self):
        dlg = SettingsDialog(self.core, self.core.engine.running, self, initial_tab=2)
        if dlg.exec():
            dlg.apply_all()
            self.cfg.audio = dlg.result_settings()
            self.core.save()
            if self.core.engine.running or self.cfg.autostart_audio:
                self.start_audio()
            self._update_limiter_ui()
            self.sync_status_controls()

    def _update_limiter_ui(self):
        l_on = bool(self.cfg.limiter.enabled)
        if hasattr(self, "limiter_switch"):
            self.limiter_switch.set_active(l_on)
        if hasattr(self, "limiter_strip"):
            set_style_property(self.limiter_strip, "active", "true" if l_on else "false")
        if hasattr(self, "limiter_thresh_lbl"):
            self.limiter_thresh_lbl.setText(f"{self.cfg.limiter.threshold_db:+.1f} dB")
            set_style_property(self.limiter_thresh_lbl, "active", "true" if l_on else "false")
        if hasattr(self, "flow_strip"):
            target = self.core.target()
            active_text = self.active_lbl.text() if hasattr(self, "active_lbl") else ""
            self.flow_strip.refresh(target, active_text)

    # ------------------------------------------------------------ chains list
    def refresh_chains(self):
        row = self.chain_list.currentRow()
        target = self.core.target()
        self.chain_list.blockSignals(True)
        self.chain_list.clear()
        for c in self.cfg.chains:
            is_active = (c.id == target)
            it = QListWidgetItem()
            it.setSizeHint(QSize(1, 68))
            self.chain_list.addItem(it)
            card = ChainCardWidget(c, is_active, self)
            self.chain_list.setItemWidget(it, card)

        self.chain_list.blockSignals(False)
        if self.cfg.chains:
            self.chain_list.setCurrentRow(max(0, min(row, len(self.cfg.chains) - 1)))
        self._fill_idle()
        self.refresh_active()
        self._update_limiter_ui()

    def _fill_idle(self):
        self.idle.blockSignals(True)
        self.idle.clear()
        self.idle.addItem("Clean voice (pass-through)", "dry")
        self.idle.addItem("Mute", "mute")
        for c in self.cfg.chains:
            self.idle.addItem(f"Chain: {c.name}", c.id)
        i = self.idle.findData(self.cfg.idle_mode)
        self.idle.setCurrentIndex(i if i >= 0 else 0)
        self.idle.blockSignals(False)

    def refresh_active(self):
        target = self.core.target()
        cur_row = self.chain_list.currentRow()
        for i, c in enumerate(self.cfg.chains):
            it = self.chain_list.item(i)
            if it is None:
                continue
            on = (c.id == target)
            is_sel = (i == cur_row)
            card = self.chain_list.itemWidget(it)
            if isinstance(card, ChainCardWidget):
                card.set_active_state(on)
                card.set_selected_state(is_sel)

        if target is None:
            text, on = "Muted", False
        elif target == DRY_ID:
            text, on = "Clean voice", False
        else:
            c = self.core.chain_by_id(target)
            text, on = (c.name if c else "?"), True

        self.active_lbl.setText(text)
        self.active_lbl.setProperty("on", on)
        self.active_lbl.style().unpolish(self.active_lbl)
        self.active_lbl.style().polish(self.active_lbl)

        if hasattr(self, "flow_strip"):
            self.flow_strip.refresh(target, text)

        self._tray_on = on
        self.tray.setIcon(branding.tray_icon(on))
        self.tray.setToolTip(f"Mandible — {text}")
        if self.editor.chain is not None:
            is_live = (self.editor.chain.id == target)
            self.editor.live_btn.setText(LIVE_ON_TEXT if is_live else LIVE_OFF_TEXT)
            self.editor.live_btn.setProperty("live", is_live)
            set_button_state(self.editor.live_btn, "on" if is_live else "")

        if hasattr(self, "power"):
            self.power.setChecked(self.core.engine.running)
            self.power.setText(POWER_ON_TEXT if self.core.engine.running else POWER_OFF_TEXT)

        if hasattr(self, "pilot_lamp"):
            self.pilot_lamp.set_active(self.core.engine.running)

        if hasattr(self, "monitor"):
            self.monitor.setChecked(self.core.engine.monitor_enabled)


    def _current_chain(self) -> Chain | None:
        r = self.chain_list.currentRow()
        return self.cfg.chains[r] if 0 <= r < len(self.cfg.chains) else None

    def _select_chain(self, _row):
        self.editor.set_chain(self._current_chain())
        self.refresh_active()

    def _chain_double_clicked(self, _it):
        c = self._current_chain()
        if c and c.mode == "toggle":
            self.core.press(c.id)

    def _add_chain(self):
        name, ok = QInputDialog.getText(self, "New chain", "Name:", text=f"Voice {len(self.cfg.chains) + 1}")
        if ok and name.strip():
            self.core.add_chain(name.strip())
            self.refresh_chains()
            self.chain_list.setCurrentRow(len(self.cfg.chains) - 1)

    def _dup_chain(self):
        c = self._current_chain()
        if c:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.core.duplicate_chain(c)
            finally:
                QApplication.restoreOverrideCursor()
            self.refresh_chains()
            self.chain_list.setCurrentRow(len(self.cfg.chains) - 1)

    def _del_chain(self):
        c = self._current_chain()
        if c and QMessageBox.question(self, "Delete chain", f"Delete “{c.name}”?") == QMessageBox.Yes:
            self.core.delete_chain(c)
            self.refresh_chains()
            self.editor.set_chain(self._current_chain())

    def _move_chain(self, d):
        c = self._current_chain()
        if c:
            self.core.move_chain(c, d)
            self.refresh_chains()
            self.chain_list.setCurrentRow(self.cfg.chains.index(c))

    def _export_chain(self):
        c = self._current_chain()
        if not c:
            return
        safe_name = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in c.name).strip() or "Preset"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Voice Preset",
            f"{safe_name}.mandible",
            "Mandible Preset (*.mandible);;JSON Files (*.json)"
        )
        if not path:
            return
        try:
            self.core.export_chain(c, path)
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not export preset:\n{exc}")

    def _import_chain(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Voice Preset",
            "",
            "Mandible Preset (*.mandible *.vfxpreset *.json);;All Files (*)"
        )
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.core.import_chain(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Import Failed", f"Could not import preset:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_chains()
        self.chain_list.setCurrentRow(len(self.cfg.chains) - 1)

    def _chain_context_menu(self, pos):
        it = self.chain_list.itemAt(pos)
        if it is not None:
            row = self.chain_list.row(it)
            self.chain_list.setCurrentRow(row)
        c = self._current_chain()
        menu = QMenu(self)
        if c is not None:
            act_live = menu.addAction("Set Live on Mic" if self.core.target() != c.id else "Turn Off (Standby)")
            act_live.triggered.connect(lambda: self.core.activate_chain_from_ui(c.id))
            menu.addSeparator()
            act_dup = menu.addAction("Duplicate Preset")
            act_dup.triggered.connect(self._dup_chain)
            act_exp = menu.addAction("Export Preset (.mandible)…")
            act_exp.triggered.connect(self._export_chain)
            act_del = menu.addAction("Delete Preset")
            act_del.triggered.connect(self._del_chain)
            menu.addSeparator()
        act_factory = menu.addMenu("Factory Presets (Built-in FX)")
        for p_def in get_factory_presets():
            a = act_factory.addAction(f"{p_def['name']}  ·  {p_def['desc']}")
            a.triggered.connect(partial(self._load_factory_preset, p_def))

        act_imp = menu.addAction("Import Preset (.mandible)…")
        act_imp.triggered.connect(self._import_chain)
        act_new = menu.addAction("New Voice Preset…")
        act_new.triggered.connect(self._add_chain)
        menu.exec(self.chain_list.viewport().mapToGlobal(pos))

    def _load_factory_preset(self, preset_dict: dict):
        chain = instantiate_factory_preset(preset_dict)
        self.cfg.chains.append(chain)
        for s in chain.plugins:
            self.core._load(s)
        self.core.rebuild(chain)
        self.core.rebind_hotkeys()
        self.core.save()
        self.refresh_chains()
        self.chain_list.setCurrentRow(len(self.cfg.chains) - 1)
        self.editor.set_chain(chain)

    def _toggle_mic_audition(self):
        state, _, _ = self.core.get_audition_status()
        if state in ("recording", "looping"):
            self.core.stop_mic_audition()
            self.audition_btn.setText(AUDITION_IDLE_TEXT)
            self._set_audition_style("")
        else:
            if not self.core.engine.running:
                try:
                    self.core.start_audio()
                except Exception as exc:
                    QMessageBox.warning(self, "Audio Error", f"Could not start audio engine: {exc}")
                    return
            self.core.start_mic_audition(5.0)
            self.audition_btn.setText("Rec 0.0 s")
            self._set_audition_style("rec")
            if not self.cfg.monitor_enabled:
                self.monitor.setChecked(True)
                self.core.set_monitor_enabled(True)

    def _set_audition_style(self, value: str):
        """Tint the Test mic button for ``"rec"`` / ``"loop"`` (``""`` = idle); progress ticks
        arrive often, so nothing is restyled unless the value changes."""
        if (self.audition_btn.property("audition") or "") == value:
            return
        self.audition_btn.setProperty("audition", value)
        set_button_state(self.audition_btn, {"rec": "danger", "loop": "on"}.get(value, ""))
        set_button_icon(self.audition_btn, {"rec": "record", "loop": "stop"}.get(value, "mic"))

    def _on_audition_progress(self, state: str, cur_s: float, tot_s: float):
        if state == "recording":
            self.audition_btn.setText(f"Rec {cur_s:.1f} s")
            self._set_audition_style("rec")
        elif state == "looping":
            self.audition_btn.setText("Stop loop")
            self._set_audition_style("loop")
        elif state == "idle":
            self.audition_btn.setText(AUDITION_IDLE_TEXT)
            self._set_audition_style("")

    def _on_plugin_bypass_changed(self):
        if hasattr(self, "editor") and self.editor.chain is not None:
            self.editor.refresh_plugins()

    def _on_gains_changed(self):
        self.g_in.set_value_quiet(self.cfg.input_gain_db)
        self.g_out.set_value_quiet(self.cfg.output_gain_db)
        self.g_mon.set_value_quiet(self.cfg.monitor_gain_db)

    # ------------------------------------------------------------ plugin editor
    def open_plugin_editor(self, slot):
        p = inst(slot)
        if p is None:
            QMessageBox.warning(self, "Plugin not loaded", slot_error(slot) or "This plugin is not loaded.")
            return
        if self._editor_event is not None:
            QMessageBox.information(self, "Mandible", "Close the plugin window that is already open first.")
            return
        ev = threading.Event()
        self._editor_event = ev
        title = f"{slot.display_name or p.name} - Mandible"
        parent_hwnd = int(self.winId()) if self.isVisible() else None
        threading.Thread(
            target=_monitor_and_center_plugin_window,
            args=(title, parent_hwnd),
            daemon=True,
        ).start()

        # If audio is not running, run a silent keep-alive pump so plugins like Serum 2
        # stay functional and never display "DAW suspended processing" when editing offline.
        stop_pump = threading.Event()
        pump_thread = None
        if not self.core.engine.running:
            def _keepalive_pump():
                sr = 44100
                bs = 256
                z = np.zeros((2, bs), dtype=np.float32)
                interval = bs / sr
                while not stop_pump.is_set():
                    try:
                        p.process(z, sr, buffer_size=bs, reset=False)
                    except Exception:
                        pass
                    stop_pump.wait(interval)

            pump_thread = threading.Thread(target=_keepalive_pump, daemon=True)
            pump_thread.start()

        try:
            p.show_editor(ev)
        except Exception as exc:
            QMessageBox.warning(self, "Plugin UI", f"Could not open the plugin UI:\n{exc}")
        finally:
            stop_pump.set()
            if pump_thread is not None:
                pump_thread.join(timeout=0.2)
            self._editor_event = None
            st = P.capture_state(p)
            if st:
                slot.state = st
                self.core.save()
            if hasattr(self, "editor"):
                self.editor.tick_plugin_meters(self.core.engine.running, sync_knobs=True)


    # ------------------------------------------------------------ audio & pre-fx
    def _open_prefx(self):
        dlg = PreFXDialog(self.core, self)
        dlg.exec()
        self._update_prefx_button_style()

    def _toggle_prefx_quick(self, target_state: bool | None = None):
        p = self.cfg.prefx
        currently_on = bool(p.rnnoise_enabled or p.noise_gate_enabled)
        new_state = bool(target_state) if target_state is not None else not currently_on
        p.rnnoise_enabled = new_state
        p.noise_gate_enabled = new_state
        self.core.set_prefx(p)
        self.core.save()
        self._update_prefx_button_style()

    def _open_soundboard(self):
        dlg = SoundboardDialog(self.core, self)
        dlg.exec()

    def _update_prefx_button_style(self):
        p = self.cfg.prefx
        active = bool(p.rnnoise_enabled or p.noise_gate_enabled)
        if hasattr(self, "prefx_switch"):
            self.prefx_switch.set_active(active)
        if hasattr(self, "prefx_strip"):
            set_style_property(self.prefx_strip, "active", "true" if active else "false")
        if hasattr(self, "flow_strip"):
            target = self.core.target()
            active_text = self.active_lbl.text() if hasattr(self, "active_lbl") else ""
            self.flow_strip.refresh(target, active_text)

    def start_audio(self):
        try:
            self.core.start_audio()
        except Exception as exc:
            self.power.blockSignals(True)
            self.power.setChecked(False)
            self.power.blockSignals(False)
            self.power.setText(POWER_OFF_TEXT)
            if hasattr(self, "pilot_lamp"):
                self.pilot_lamp.set_active(False)
            self.status.setText(f"[ERR] {exc}")
            self._update_status()
            return False
        self.power.blockSignals(True)
        self.power.setChecked(True)
        self.power.blockSignals(False)
        self.power.setText(POWER_ON_TEXT)
        if hasattr(self, "pilot_lamp"):
            self.pilot_lamp.set_active(True)
        self._update_status()
        return True

    def _power(self, on):
        if on:
            if not self.start_audio():
                QMessageBox.warning(self, "Audio", self.status.text())
        else:
            self.core.stop_audio()
            self.power.setText(POWER_OFF_TEXT)
            if hasattr(self, "pilot_lamp"):
                self.pilot_lamp.set_active(False)
            self._update_status()

    def _engine_stopped(self, reason):
        if self.core.engine.running:
            return
        self.power.blockSignals(True)
        self.power.setChecked(False)
        self.power.blockSignals(False)
        self.power.setText(POWER_OFF_TEXT)
        if hasattr(self, "pilot_lamp"):
            self.pilot_lamp.set_active(False)
        self.core.engine.stream = None
        self.status.setText(f"[OFFLINE] {reason}")
        self._update_status()

    def _on_look_changed(self):
        """Look switched: the tray follows the accent (widgets repaint themselves) and the
        spacing follows the skin's density."""
        self._spaced.apply()
        self.splitter.setHandleWidth(space(3))
        if hasattr(self, "tray"):
            self.tray.setIcon(branding.tray_icon(self._tray_on))

    def _settings(self):
        dlg = SettingsDialog(self.core, self.core.engine.running, self)
        if dlg.exec():
            dlg.apply_all()
            self.cfg.audio = dlg.result_settings()
            self.core.save()
            if self.core.engine.running or self.cfg.autostart_audio:
                self.start_audio()
            self._update_limiter_ui()
            self.sync_status_controls()

    def _update_status(self):
        e = self.core.engine
        light = branding.taskbar_is_light()
        if light != getattr(self, "_tray_light", light) and hasattr(self, "tray"):
            self._tray_light = light
            self.tray.setIcon(branding.tray_icon(self._tray_on))
        state_changed = getattr(self, "_status_running", None) != e.running
        self._status_running = e.running
        if hasattr(self, "pilot_lamp"):
            self.pilot_lamp.set_active(e.running)

        if e.running:
            drv = D.DRIVER_LABELS.get(e.driver, e.driver).split(" (")[0]
            self.status.setText(f"ONLINE | {drv} | {e.samplerate / 1000:g} kHz | {e.blocksize} smp | ~{e.latency_ms:.1f} ms")
            self.status.setProperty("on", True)
            if hasattr(self, "vfd_stat"):
                self.vfd_stat.setText(f"DSP: {e.load * 100:2.0f}%")
                if state_changed:
                    set_style_property(self.vfd_stat, "running", True)
            if hasattr(self, "vfd_sr"):
                self.vfd_sr.setText(f"{e.samplerate / 1000:g} kHz")
            if hasattr(self, "vfd_buf"):
                self.vfd_buf.setText(f"{e.blocksize} SMP")
            if hasattr(self, "vfd_lat"):
                self.vfd_lat.setText(f"{e.latency_ms:.1f} ms")
            if hasattr(self, "vfd_drv"):
                self.vfd_drv.setText(drv.upper())
        else:
            if not self.status.text().startswith("[ERR]"):
                self.status.setText("STOPPED")
            self.status.setProperty("on", False)
            if hasattr(self, "vfd_stat"):
                self.vfd_stat.setText("DSP: OFF")
                if state_changed:
                    set_style_property(self.vfd_stat, "running", False)
            if hasattr(self, "vfd_sr"):
                self.vfd_sr.setText("-- kHz")
            if hasattr(self, "vfd_buf"):
                self.vfd_buf.setText("-- SMP")
            if hasattr(self, "vfd_lat"):
                self.vfd_lat.setText("-- ms")
            if hasattr(self, "vfd_drv"):
                self.vfd_drv.setText("OFFLINE")

        if state_changed:
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        tip = (f"{self.status.text()}\nDSP load {e.load * 100:.0f}%, dropouts {e.xruns}"
               if e.running else f"Audio engine: {self.status.text()}")
        if self.vfd_box.toolTip() != tip:
            self.vfd_box.setToolTip(tip)
        if e.last_error:
            print("[Mandible] audio error:", e.last_error)
            e.last_error = ""

    def _tick(self):
        e = self.core.engine
        pi, po, pm = e.peak_in, e.peak_out, e.peak_mon
        e.peak_in = e.peak_out = e.peak_mon = 0.0
        if not e.running:
            pi = po = pm = 0.0
        self.m_in.push(pi)
        self.m_out.push(po)
        self.m_mon.push(pm)
        if hasattr(self, "thin_m_in"):
            self.thin_m_in.push(pi)
            self.thin_m_out.push(po)
            self.thin_m_mon.push(pm)
        if hasattr(self, "editor"):
            self._tick_count = getattr(self, "_tick_count", 0) + 1
            sync_knobs = (self._tick_count % 12 == 0)
            self.editor.tick_plugin_meters(e.running, sync_knobs=sync_knobs)


    def _monitor_toggled(self, on: bool):
        self.core.set_monitor_enabled(on)
        self.act_mon.blockSignals(True)
        self.act_mon.setChecked(on)
        self.act_mon.blockSignals(False)

    def _tray_monitor_toggled(self, on: bool):
        self.monitor.setChecked(on)

    # ------------------------------------------------------------ misc settings
    def _idle_changed(self, _):
        self.cfg.idle_mode = self.idle.currentData() or "dry"
        self.core.save()
        self.core._apply()

    def _hk_toggled(self, on):
        self.cfg.hotkeys_enabled = on
        self.core.hotkeys.enabled = on
        self.core.save()

    def _update_panic_label(self):
        hk = self.cfg.panic_hotkey
        self.panic_key_action.setText(f"All-off key: {hk.label if hk.is_set() else 'not set'}…")
        self.panic_top_btn.setToolTip("Turn all effect chains off immediately"
                                      + (f" (all-off key: {hk.label})" if hk.is_set() else ""))

    def sync_status_controls(self):
        """Re-read idle mode, hotkeys and the all-off key from the config (after Settings)."""
        self._fill_idle()
        self.hk_enabled.blockSignals(True)
        self.hk_enabled.setChecked(bool(self.cfg.hotkeys_enabled))
        self.hk_enabled.blockSignals(False)
        self._update_panic_label()

    def _set_panic(self):
        dlg = HotkeyDialog(self.core, self, "All-off hotkey")
        if dlg.exec() and dlg.result_hotkey is not None:
            hk = dlg.result_hotkey
            if hk.is_set():
                clash = self.core.find_hotkey_conflict(hk, exclude=self.cfg.panic_hotkey)
                if clash:
                    QMessageBox.warning(self, "Hotkey in use", f"{hk.label} is already used by {clash}.")
                    return
            self.cfg.panic_hotkey = hk
            self.core.rebind_hotkeys()
            self.core.save()
            self._update_panic_label()

    def _open_about(self, start_tab: int = 0):
        from .dialogs.about import AboutDialog
        AboutDialog(self, start_tab).exec()

    def _open_setup_assistant(self):
        dlg = SetupAssistantDialog(self.core, self)
        if dlg.exec():
            if not self.core.engine.running:
                self.start_audio()

    # ------------------------------------------------------------ window / tray
    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_normal()

    def show_normal(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def _sync_timers(self):
        """Run the 30 Hz meter timer only while the window is actually on screen."""
        if not hasattr(self, "meter_timer"):
            return
        on_screen = self.isVisible() and not self.isMinimized()
        if on_screen and not self.meter_timer.isActive():
            self.meter_timer.start(33)
            self.status_timer.setInterval(500)
            self._update_status()
        elif not on_screen and self.meter_timer.isActive():
            self.meter_timer.stop()
            self.status_timer.setInterval(2000)  # still logs audio errors while hidden

    def showEvent(self, ev):
        super().showEvent(ev)
        self._sync_timers()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._sync_timers()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == ev.Type.WindowStateChange:
            self._sync_timers()

    def closeEvent(self, ev):
        if self.cfg.close_to_tray and not self._quitting:
            ev.ignore()
            self.hide()
            if not getattr(self, "_tray_hint_shown", False):
                self._tray_hint_shown = True
                self.tray.showMessage("Mandible is still running",
                                      "Hotkeys stay active. Right-click the tray icon to quit.",
                                      branding.app_icon(), 2500)
            return
        self.quit()
        ev.accept()

    def quit(self):
        self._quitting = True
        if self._editor_event is not None:
            self._editor_event.set()
            QTimer.singleShot(150, self.quit)
            return
        self.meter_timer.stop()
        self.status_timer.stop()
        self.flush_pending_save()
        self.core.shutdown()
        self.tray.hide()
        QApplication.quit()
