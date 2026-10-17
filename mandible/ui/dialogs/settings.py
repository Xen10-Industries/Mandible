"""Tabbed application settings."""
from __future__ import annotations

import copy
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QSlider,
                               QSpinBox, QTabWidget, QTableWidget,
                               QVBoxLayout, QWidget)

from ... import devices as D
from ...config import APP_DIR, MidiBinding, is_startup_enabled, set_startup_enabled
from ...core import Core
from ...midi import list_midi_inputs
from ..look import (BUILTIN_PALETTES, BUILTIN_SKINS, Look, current_look, look_for, set_look)
from .hotkey import HotkeyDialog
from .setup_assistant import SetupAssistantDialog


class SettingsDialog(QDialog):
    """Tabbed settings: Audio, Push-to-Talk, Limiter, MIDI, Overlay, and General."""
    def __init__(self, core: Core, running: bool, parent=None, initial_tab: int = 0):
        super().__init__(parent)
        self.core = core
        self.cfg = core.cfg
        self.running = running
        self._orig_look = current_look()   # restored when the dialog is cancelled
        self.setWindowTitle("Settings")
        self.resize(740, 500)
        lay = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(False)
        tabs = self.tabs
        lay.addWidget(tabs, 1)

        # ---------------- Audio Tab
        tab_audio = QWidget()
        form = QFormLayout(tab_audio)
        self.driver = QComboBox()
        self.in_dev = QComboBox()
        self.in_ch = QComboBox()
        self.out_dev = QComboBox()
        self.out_ch = QComboBox()
        self.mon_dev = QComboBox()
        self.mon_ch = QComboBox()
        self.mon_mode = QComboBox()
        self.mon_mode.addItem("Processed voice (standard effect)", "processed")
        self.mon_mode.addItem("Clean microphone (zero-latency dry voice)", "dry")
        self.mon_mode.addItem("50/50 Blend (processed + dry mic)", "mix")
        self.mon_mode.setCurrentIndex(max(0, self.mon_mode.findData(self.cfg.headphone_monitor_mode)))

        self.sr = QComboBox()
        self.bs = QComboBox()
        self.excl = QCheckBox("WASAPI exclusive mode (lower latency, locks the device)")

        form.addRow("Driver", self.driver)
        form.addRow("Input device", self.in_dev)
        form.addRow("Mic input channel", self.in_ch)
        self.out_dev_label = QLabel("Output device")
        form.addRow(self.out_dev_label, self.out_dev)
        form.addRow("Output channels", self.out_ch)
        self.mon_dev_label = QLabel("Monitor device")
        form.addRow(self.mon_dev_label, self.mon_dev)
        self.mon_ch_label = QLabel("Monitor channels")
        form.addRow(self.mon_ch_label, self.mon_ch)
        form.addRow("Headphones feed", self.mon_mode)
        form.addRow("Sample rate", self.sr)
        form.addRow("Buffer size", self.bs)
        form.addRow("", self.excl)

        self.asio_panel_btn = QPushButton("Focusrite / ASIO Control Panel…")
        self.asio_panel_btn.clicked.connect(self._open_asio_panel)
        form.addRow("", self.asio_panel_btn)

        wizard_btn = QPushButton("RUN AUDIO SETUP ASSISTANT (UNIVERSAL WIZARD)...")
        wizard_btn.setObjectName("audioWizardBtn")
        wizard_btn.clicked.connect(self._launch_setup_assistant)
        form.addRow("", wizard_btn)

        rescan = QPushButton("Rescan devices")
        rescan.setEnabled(not running)
        form.addRow("", rescan)
        tabs.addTab(tab_audio, "Audio Routing")

        # ---------------- Push to Talk Tab
        tab_ptt = QWidget()
        ptt_lay = QFormLayout(tab_ptt)
        self.ptt_mode = QComboBox()
        self.ptt_mode.addItem("Disabled (mic always active)", "disabled")
        self.ptt_mode.addItem("Push-to-Talk (unmute mic while key is held)", "push_to_talk")
        self.ptt_mode.addItem("Push-to-Mute (mute mic while key is held)", "push_to_mute")
        self.ptt_mode.setCurrentIndex(max(0, self.ptt_mode.findData(self.cfg.ptt.mode)))

        ptt_hk_row = QHBoxLayout()
        self.ptt_hk_lbl = QLabel(self.cfg.ptt.hotkey.label if self.cfg.ptt.hotkey.is_set() else "Not set")
        self.ptt_hk_btn = QPushButton("Set PTT Key…")
        self.ptt_hk_btn.clicked.connect(self._set_ptt_hotkey)
        ptt_hk_row.addWidget(self.ptt_hk_lbl, 1)
        ptt_hk_row.addWidget(self.ptt_hk_btn)

        ptt_lay.addRow("Microphone Mode", self.ptt_mode)
        ptt_lay.addRow("PTT Hotkey", ptt_hk_row)
        tabs.addTab(tab_ptt, "Push-to-Talk")

        # ---------------- Limiter & Normalizer Tab
        tab_lim = QWidget()
        lim_lay = QFormLayout(tab_lim)
        self.lim_en = QCheckBox("Enable Master Brickwall Limiter (prevents clipping into Discord/OBS)")
        self.lim_en.setChecked(self.cfg.limiter.enabled)
        self.lim_thresh = QDoubleSpinBox()
        self.lim_thresh.setRange(-12.0, 0.0)
        self.lim_thresh.setSingleStep(0.5)
        self.lim_thresh.setValue(self.cfg.limiter.threshold_db)
        self.lim_thresh.setSuffix(" dB")
        lim_lay.addRow("", self.lim_en)
        lim_lay.addRow("Limiter Ceiling", self.lim_thresh)

        lim_sep = QFrame()
        lim_sep.setFrameShape(QFrame.HLine)
        lim_sep.setObjectName("settingsSeparator")
        lim_lay.addRow(lim_sep)

        self.norm_en = QCheckBox("Enable Output Loudness Normalizer (auto-levels volume between presets)")
        self.norm_en.setChecked(getattr(self.cfg, "normalizer_enabled", False))
        self.norm_target = QDoubleSpinBox()
        self.norm_target.setRange(-30.0, -6.0)
        self.norm_target.setSingleStep(0.5)
        self.norm_target.setValue(getattr(self.cfg, "normalizer_target_db", -14.0))
        self.norm_target.setSuffix(" dBFS")
        lim_lay.addRow("", self.norm_en)
        lim_lay.addRow("Target Loudness", self.norm_target)
        tabs.addTab(tab_lim, "Limiter && Normalizer")   # && draws one literal ampersand

        # ---------------- MIDI Tab
        tab_midi = QWidget()
        midi_lay = QVBoxLayout(tab_midi)
        m_top = QHBoxLayout()
        m_top.addWidget(QLabel("MIDI Input Device:"))
        self.midi_dev = QComboBox()
        self.midi_dev.addItem("None", "")
        for idx, mname in list_midi_inputs():
            self.midi_dev.addItem(mname, mname)
        self.midi_dev.setCurrentIndex(max(0, self.midi_dev.findText(self.cfg.midi_device)))
        self.midi_dev.currentIndexChanged.connect(self._on_midi_dev_preview)
        m_top.addWidget(self.midi_dev, 1)

        midi_rescan_btn = QPushButton("Rescan MIDI")
        midi_rescan_btn.clicked.connect(self._rescan_midi)
        m_top.addWidget(midi_rescan_btn)
        midi_lay.addLayout(m_top)

        midi_info = QLabel("Map incoming MIDI pads/keys (Note-On) and rotary knobs/faders (CC) to presets, soundboard clips, and studio controls.")
        midi_info.setWordWrap(True)
        midi_info.setObjectName("dialogInfo")
        midi_lay.addWidget(midi_info)

        self._midi_bindings_work: list[MidiBinding] = [copy.copy(b) for b in self.cfg.midi_bindings]
        self._midi_learning_row: int | None = None

        self.midi_table = QTableWidget(0, 5)
        self.midi_table.setHorizontalHeaderLabels(["Event Type", "Note / CC #", "Channel", "Target Action", ""])
        mh = self.midi_table.horizontalHeader()
        mh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        mh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        mh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        mh.setSectionResizeMode(3, QHeaderView.Stretch)
        mh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.midi_table.verticalHeader().setVisible(False)
        midi_lay.addWidget(self.midi_table, 1)

        midi_btn_row = QHBoxLayout()
        add_midi_btn = QPushButton("+ Add MIDI Binding")
        add_midi_btn.clicked.connect(self._add_midi_binding)
        midi_btn_row.addWidget(add_midi_btn)

        self.midi_learn_btn = QPushButton("MIDI Learn (New Binding)…")
        self.midi_learn_btn.setObjectName("midiLearnBtn")
        self.midi_learn_btn.clicked.connect(self._start_midi_learn_new)
        midi_btn_row.addWidget(self.midi_learn_btn)
        midi_btn_row.addStretch()
        midi_lay.addLayout(midi_btn_row)

        self._refresh_midi_table()
        self.core.midiMessageReceived.connect(self._on_midi_learned)
        tabs.addTab(tab_midi, "MIDI Controllers")

        # ---------------- Overlay Tab
        tab_ov = QWidget()
        ov_lay = QFormLayout(tab_ov)
        self.ov_en = QCheckBox("Enable in-game HUD overlay (click-through badge on top of games)")
        self.ov_en.setChecked(self.cfg.overlay.enabled)
        self.ov_pos = QComboBox()
        self.ov_pos.addItem("Top-Right", "top-right")
        self.ov_pos.addItem("Top-Left", "top-left")
        self.ov_pos.addItem("Bottom-Right", "bottom-right")
        self.ov_pos.addItem("Bottom-Left", "bottom-left")
        self.ov_pos.setCurrentIndex(max(0, self.ov_pos.findData(self.cfg.overlay.position)))

        ov_op_row = QHBoxLayout()
        self.ov_opacity = QSlider(Qt.Horizontal)
        self.ov_opacity.setRange(25, 100)
        self.ov_opacity.setValue(int(round(getattr(self.cfg.overlay, "opacity", 0.85) * 100)))
        self.ov_op_lbl = QLabel(f"{self.ov_opacity.value()}%")
        self.ov_op_lbl.setFixedWidth(40)
        self.ov_opacity.valueChanged.connect(lambda v: self.ov_op_lbl.setText(f"{v}%"))
        ov_op_row.addWidget(self.ov_opacity, 1)
        ov_op_row.addWidget(self.ov_op_lbl)

        self.ov_hide_clean = QCheckBox("Hide badge when clean voice is active")
        self.ov_hide_clean.setChecked(self.cfg.overlay.hide_when_clean)
        ov_lay.addRow("", self.ov_en)
        ov_lay.addRow("Position", self.ov_pos)
        ov_lay.addRow("HUD Opacity", ov_op_row)
        ov_lay.addRow("", self.ov_hide_clean)
        tabs.addTab(tab_ov, "In-Game Overlay")

        # ---------------- General Tab
        tab_gen = QWidget()
        gl = QVBoxLayout(tab_gen)

        theme_box = QGroupBox("Interface Appearance")
        theme_lay = QVBoxLayout(theme_box)
        theme_lay.setSpacing(8)

        # 1. UI Skin / Style
        skin_row = QHBoxLayout()
        skin_row.addWidget(QLabel("UI Skin / Style:"))
        self.skin_combo = QComboBox()
        for skin in BUILTIN_SKINS.values():
            self.skin_combo.addItem(skin.name, skin.id)
        cur_skin = getattr(self.cfg, "ui_skin", "skeuomorphic")
        self.skin_combo.setCurrentIndex(max(0, self.skin_combo.findData(cur_skin)))
        self.skin_combo.currentIndexChanged.connect(self._on_appearance_preview_changed)
        skin_row.addWidget(self.skin_combo, 1)
        theme_lay.addLayout(skin_row)

        # 2. Outer Chassis Frame
        frame_row = QHBoxLayout()
        frame_row.addWidget(QLabel("Outer Chassis Frame:"))
        self.frame_combo = QComboBox()
        self.frame_combo.addItem("Auto (Matched to UI Style)", "auto")
        self.frame_combo.addItem("19\" Brushed Steel Rack Ears", "metal_rack")
        self.frame_combo.addItem("Sculpted Walnut Wood Cheek Blocks", "wood_cheeks")
        self.frame_combo.addItem("Frameless Matte Border", "frameless")
        cur_frame = getattr(self.cfg, "chassis_frame", "auto")
        self.frame_combo.setCurrentIndex(max(0, self.frame_combo.findData(cur_frame)))
        self.frame_combo.currentIndexChanged.connect(self._on_appearance_preview_changed)
        frame_row.addWidget(self.frame_combo, 1)
        theme_lay.addLayout(frame_row)

        # 3. Color Theme
        t_row = QHBoxLayout()
        t_row.addWidget(QLabel("Color Theme:"))
        self.theme_combo = QComboBox()
        for palette in BUILTIN_PALETTES.values():
            self.theme_combo.addItem(palette.name, palette.id)
        cur_t = getattr(self.cfg, "theme", "scarlet")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(cur_t)))
        self.theme_combo.currentIndexChanged.connect(self._on_appearance_preview_changed)
        t_row.addWidget(self.theme_combo, 1)
        theme_lay.addLayout(t_row)

        # 4. Hardware Switch Style
        sw_row = QHBoxLayout()
        sw_row.addWidget(QLabel("Hardware Switch Style:"))
        self.switch_combo = QComboBox()
        self.switch_combo.addItem("Bat-Handle Metal Toggle (Classic Studio)", "bat_toggle")
        self.switch_combo.addItem("Studio Beveled Rocker (80s/90s Rackmount)", "rocker")
        cur_sw = getattr(self.cfg, "switch_style", "bat_toggle")
        self.switch_combo.setCurrentIndex(max(0, self.switch_combo.findData(cur_sw)))
        self.switch_combo.currentIndexChanged.connect(self._on_appearance_preview_changed)
        sw_row.addWidget(self.switch_combo, 1)
        theme_lay.addLayout(sw_row)

        gl.addWidget(theme_box)

        gl.addSpacing(6)
        self.launch_startup = QCheckBox("Launch Mandible automatically when Windows starts")
        self.autostart = QCheckBox("Start audio automatically when Mandible opens")
        self.tray = QCheckBox("Closing the window keeps Mandible running in the tray")
        self.minimized = QCheckBox("Start minimized to tray")
        self.keep_awake = QCheckBox("Keep inactive chains awake with silence (prevents VST suspension)")

        self.launch_startup.setChecked(is_startup_enabled() or bool(getattr(self.cfg, "launch_at_startup", False)))
        self.autostart.setChecked(self.cfg.autostart_audio)
        self.tray.setChecked(self.cfg.close_to_tray)
        self.minimized.setChecked(self.cfg.start_minimized)
        self.keep_awake.setChecked(self.cfg.keep_chains_awake)

        for w in (self.launch_startup, self.autostart, self.tray, self.minimized, self.keep_awake):
            gl.addWidget(w)

        # Idle mode, hotkeys and the all-off key (also in the main window's header status zone)
        hk_box = QGroupBox("Hotkeys and idle")
        hk_form = QFormLayout(hk_box)
        self.idle_combo = QComboBox()
        self.idle_combo.addItem("Clean voice (pass-through)", "dry")
        self.idle_combo.addItem("Mute", "mute")
        for c in self.cfg.chains:
            self.idle_combo.addItem(f"Chain: {c.name}", c.id)
        i = self.idle_combo.findData(self.cfg.idle_mode)
        self.idle_combo.setCurrentIndex(i if i >= 0 else 0)
        hk_form.addRow("When no chain is active", self.idle_combo)
        self.hotkeys_check = QCheckBox("Global hotkeys enabled")
        self.hotkeys_check.setChecked(bool(self.cfg.hotkeys_enabled))
        hk_form.addRow("", self.hotkeys_check)
        self._panic_hotkey_work = copy.deepcopy(self.cfg.panic_hotkey)
        self.panic_key_btn = QPushButton()
        self.panic_key_btn.setToolTip("Global hotkey that turns every chain off")
        self.panic_key_btn.clicked.connect(self._pick_panic_hotkey)
        self._update_panic_key_btn()
        hk_form.addRow("All-off key", self.panic_key_btn)
        gl.addWidget(hk_box)

        gl.addSpacing(8)
        diag_row = QHBoxLayout()
        open_appdata_btn = QPushButton("Open Config && Logs Folder…")
        open_appdata_btn.setToolTip(f"Open {APP_DIR} in Windows Explorer")
        open_appdata_btn.clicked.connect(lambda: os.startfile(APP_DIR) if os.path.isdir(APP_DIR) else None)
        diag_row.addWidget(open_appdata_btn)
        diag_row.addStretch()
        gl.addLayout(diag_row)

        gl.addStretch()
        tabs.addTab(tab_gen, "General")

        # ---------------- Remote API Tab
        import webbrowser
        tab_api = QWidget()
        api_lay = QFormLayout(tab_api)
        self.api_en = QCheckBox("Enable Local HTTP/REST API (for Stream Deck, OBS, && Webhooks)")
        self.api_en.setChecked(getattr(self.cfg, "api_enabled", False))
        self.api_port_spin = QSpinBox()
        self.api_port_spin.setRange(1024, 65535)
        self.api_port_spin.setValue(getattr(self.cfg, "api_port", 38420))

        api_lay.addRow("", self.api_en)
        api_lay.addRow("API Port", self.api_port_spin)

        api_info = QLabel("Allows Elgato Stream Deck, OBS browser docks, and local apps to switch presets, play soundboard clips, and mute over HTTP.")
        api_info.setWordWrap(True)
        api_info.setObjectName("dialogInfo")
        api_lay.addRow("", api_info)

        self.api_test_btn = QPushButton("Test API in Web Browser (http://localhost:38420/api/status)")
        self.api_test_btn.clicked.connect(lambda: webbrowser.open(f"http://127.0.0.1:{self.api_port_spin.value()}/api/status"))
        api_lay.addRow("", self.api_test_btn)
        tabs.addTab(tab_api, "Local API")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        lay.addWidget(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        # Populate drivers & audio devices
        a = self.cfg.audio
        for sr in (0, 44100, 48000, 88200, 96000):
            self.sr.addItem("Device default" if sr == 0 else f"{sr} Hz", sr)
        self.sr.setCurrentIndex(max(0, self.sr.findData(a.samplerate)))
        for bs in (32, 64, 128, 256, 512, 1024):
            self.bs.addItem(f"{bs} samples", bs)
        self.bs.setCurrentIndex(max(0, self.bs.findData(a.blocksize)))
        self.excl.setChecked(a.wasapi_exclusive)

        self._fill_drivers(a)
        self.driver.currentIndexChanged.connect(lambda _: self._driver_changed(None))
        self.in_dev.currentIndexChanged.connect(lambda _: self._in_changed(None))
        self.out_dev.currentIndexChanged.connect(lambda _: self._out_changed(None))
        rescan.clicked.connect(self._rescan)
        if 0 <= initial_tab < tabs.count():
            tabs.setCurrentIndex(initial_tab)

    def _midi_action_options(self) -> list[tuple[str, str]]:
        opts = [
            ("Toggle Mic Mute", "mute"),
            ("Panic Cut (All Chains Off)", "panic"),
            ("Master Output Volume (CC Fader)", "out_vol"),
            ("Headphone Monitor Volume (CC Fader)", "monitor_vol"),
            ("Mic Input Trim (CC Fader)", "in_vol"),
        ]
        for c in self.cfg.chains:
            opts.append((f"Preset: {c.name}", f"chain:{c.id}"))
        for s in self.cfg.soundboard:
            opts.append((f"Soundboard: {s.name}", f"soundboard:{s.id}"))
        return opts

    def _refresh_midi_table(self):
        self.midi_table.setRowCount(len(self._midi_bindings_work))
        action_opts = self._midi_action_options()
        for row, b in enumerate(self._midi_bindings_work):
            # 0: Event Type
            type_cb = QComboBox()
            type_cb.addItem("Note On (Pad/Key)", "note_on")
            type_cb.addItem("Control Change (CC)", "cc")
            type_cb.setCurrentIndex(max(0, type_cb.findData(b.event_type)))
            type_cb.currentIndexChanged.connect(lambda _, r=row, cb=type_cb: setattr(self._midi_bindings_work[r], "event_type", cb.currentData()))
            self.midi_table.setCellWidget(row, 0, type_cb)

            # 1: Note / CC #
            num_sp = QSpinBox()
            num_sp.setRange(0, 127)
            num_sp.setValue(int(b.note_or_cc))
            num_sp.valueChanged.connect(lambda val, r=row: setattr(self._midi_bindings_work[r], "note_or_cc", int(val)))
            self.midi_table.setCellWidget(row, 1, num_sp)

            # 2: Channel (0 = Omni)
            ch_sp = QSpinBox()
            ch_sp.setRange(0, 16)
            ch_sp.setSpecialValueText("All (Omni)")
            ch_sp.setValue(int(b.channel))
            ch_sp.valueChanged.connect(lambda val, r=row: setattr(self._midi_bindings_work[r], "channel", int(val)))
            self.midi_table.setCellWidget(row, 2, ch_sp)

            # 3: Action
            act_cb = QComboBox()
            for lbl, act_data in action_opts:
                act_cb.addItem(lbl, act_data)
            idx = act_cb.findData(b.action)
            if idx >= 0:
                act_cb.setCurrentIndex(idx)
            elif action_opts:
                b.action = action_opts[0][1]
            act_cb.currentIndexChanged.connect(lambda _, r=row, cb=act_cb: setattr(self._midi_bindings_work[r], "action", cb.currentData()))
            self.midi_table.setCellWidget(row, 3, act_cb)

            # 4: Remove
            rm_btn = QPushButton("✕")
            rm_btn.setFixedWidth(28)
            rm_btn.clicked.connect(lambda _, r=row: self._remove_midi_binding(r))
            self.midi_table.setCellWidget(row, 4, rm_btn)

    def _add_midi_binding(self):
        opts = self._midi_action_options()
        default_act = opts[0][1] if opts else "mute"
        self._midi_bindings_work.append(MidiBinding(device_name=self.midi_dev.currentText(), event_type="note_on", note_or_cc=60, channel=0, action=default_act))
        self._refresh_midi_table()

    def _remove_midi_binding(self, row: int):
        if 0 <= row < len(self._midi_bindings_work):
            self._midi_bindings_work.pop(row)
            self._refresh_midi_table()

    def _rescan_midi(self):
        cur = self.midi_dev.currentText()
        self.midi_dev.blockSignals(True)
        self.midi_dev.clear()
        self.midi_dev.addItem("None", "")
        for idx, mname in list_midi_inputs():
            self.midi_dev.addItem(mname, mname)
        self.midi_dev.setCurrentIndex(max(0, self.midi_dev.findText(cur)))
        self.midi_dev.blockSignals(False)
        self._on_midi_dev_preview()

    def _on_midi_dev_preview(self):
        mdev = self.midi_dev.currentText()
        if mdev == "None":
            mdev = ""
        self.core.set_midi_device(mdev)

    def _start_midi_learn_new(self):
        mdev = self.midi_dev.currentText()
        if not mdev or mdev == "None":
            QMessageBox.information(self, "MIDI Learn", "Select a MIDI Input Device at the top of the tab first.")
            return
        self._on_midi_dev_preview()
        if self._midi_learning_row is not None:
            self._midi_learning_row = None
            self.midi_learn_btn.setText("MIDI Learn (New Binding)…")
            return
        self._midi_learning_row = -1
        self.midi_learn_btn.setText("Listening for MIDI Input… (Click to cancel)")

    def _on_midi_learned(self, event_type: str, note_or_cc: int, channel: int):
        if self._midi_learning_row is None:
            return
        self._midi_learning_row = None
        self.midi_learn_btn.setText("MIDI Learn (New Binding)…")
        opts = self._midi_action_options()
        default_act = "out_vol" if event_type == "cc" else (f"chain:{self.cfg.chains[0].id}" if self.cfg.chains else (opts[0][1] if opts else "mute"))
        self._midi_bindings_work.append(
            MidiBinding(
                device_name=self.midi_dev.currentText(),
                event_type=event_type,
                note_or_cc=note_or_cc,
                channel=channel,
                action=default_act,
            )
        )
        self._refresh_midi_table()

    def _set_ptt_hotkey(self):
        dlg = HotkeyDialog(self.core, self, "Push-to-Talk Hotkey")
        if dlg.exec() and dlg.result_hotkey is not None:
            self.cfg.ptt.hotkey = dlg.result_hotkey
            self.ptt_hk_lbl.setText(dlg.result_hotkey.label or "Not set")

    def _open_asio_panel(self):
        dev = self.in_dev.currentText()
        if not dev:
            return
        err = D.show_asio_panel(dev, int(self.winId()))
        if err:
            QMessageBox.warning(self, "ASIO Control Panel", f"Could not open ASIO control panel:\n{err}")

    def _fill_drivers(self, a):
        self.driver.blockSignals(True)
        self.driver.clear()
        for d in D.drivers():
            self.driver.addItem(D.DRIVER_LABELS.get(d, d), d)
        self.driver.setCurrentIndex(max(0, self.driver.findData(a.driver)))
        self.driver.blockSignals(False)
        self._driver_changed(a)

    def _driver_changed(self, a):
        drv = self.driver.currentData()
        asio = drv == "ASIO"
        self.out_dev.setVisible(not asio)
        self.out_dev_label.setVisible(not asio)
        self.mon_dev.setVisible(not asio)
        self.mon_dev_label.setVisible(not asio)
        self.mon_ch.setVisible(asio)
        self.mon_ch_label.setVisible(asio)
        self.excl.setVisible(drv == "Windows WASAPI")
        self.asio_panel_btn.setVisible(asio)
        for combo, kind, want in ((self.in_dev, "input", a.input_device if a else None),
                                  (self.out_dev, "output", a.output_device if a else None)):
            combo.blockSignals(True)
            combo.clear()
            for idx, name, n in D.list_devices(drv, kind):
                combo.addItem(name, idx)
            i = combo.findText(want) if want else -1
            if i < 0:
                i = next((k for k in range(combo.count()) if "focusrite" in combo.itemText(k).lower()), 0)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)

        self.mon_dev.blockSignals(True)
        self.mon_dev.clear()
        self.mon_dev.addItem("None", "")
        for idx, name, n in D.list_devices(drv, "output"):
            self.mon_dev.addItem(name, name)
        want_mon = a.monitor_device if a else ""
        i_mon = self.mon_dev.findData(want_mon)
        if i_mon < 0 and want_mon:
            i_mon = self.mon_dev.findText(want_mon)
        if i_mon < 0:
            i_mon = next((k for k in range(self.mon_dev.count()) if "speaker" in self.mon_dev.itemText(k).lower()), 0)
        self.mon_dev.setCurrentIndex(max(0, i_mon))
        self.mon_dev.blockSignals(False)

        self._in_changed(a)
        self._out_changed(a)

    def _in_changed(self, a):
        drv = self.driver.currentData()
        self.in_ch.clear()
        idx = self.in_dev.currentData()
        if idx is not None:
            for i, n in enumerate(D.channel_names(drv, idx, "input")):
                self.in_ch.addItem(f"{i + 1}: {n}" if not n.startswith("Channel") else n, i)
        want = a.input_channel if a else 0
        self.in_ch.setCurrentIndex(max(0, self.in_ch.findData(want)))
        if drv == "ASIO":
            self._out_changed(a)

    def _out_changed(self, a):
        drv = self.driver.currentData()
        self.out_ch.clear()
        self.mon_ch.clear()
        idx = self.in_dev.currentData() if drv == "ASIO" else self.out_dev.currentData()
        if drv == "ASIO" and idx is not None:
            idx = D.find_device(drv, self.in_dev.currentText(), "output")
        if idx is None:
            return
        names = D.channel_names(drv, idx, "output")
        for l in range(0, len(names) - 1, 2):
            text = f"{l + 1}-{l + 2}  ({names[l]} / {names[l + 1]})"
            self.out_ch.addItem(text, [l, l + 1])
            self.mon_ch.addItem(text, [l, l + 1])
        if len(names) == 1:
            self.out_ch.addItem(f"1 ({names[0]}) mono", [0, 0])
            self.mon_ch.addItem(f"1 ({names[0]}) mono", [0, 0])
        want = list(a.output_channels) if a else ([2, 3] if drv == "ASIO" else [0, 1])
        i = next((k for k in range(self.out_ch.count()) if self.out_ch.itemData(k) == want), 0)
        self.out_ch.setCurrentIndex(i)

        want_mon = list(a.monitor_channels) if a else ([0, 1] if drv == "ASIO" else [0, 1])
        i_mon = next((k for k in range(self.mon_ch.count()) if self.mon_ch.itemData(k) == want_mon), 0)
        self.mon_ch.setCurrentIndex(i_mon)

    def _rescan(self):
        D.rescan()
        self._fill_drivers(self.result_settings())

    def result_settings(self):
        from .config import AudioSettings
        a = AudioSettings()
        a.driver = self.driver.currentData() or ""
        a.input_device = self.in_dev.currentText()
        a.output_device = self.in_dev.currentText() if a.driver == "ASIO" else self.out_dev.currentText()
        a.input_channel = int(self.in_ch.currentData() or 0)
        a.output_channels = list(self.out_ch.currentData() or [0, 1])
        a.monitor_channels = list(self.mon_ch.currentData() or [0, 1])
        a.monitor_device = str(self.mon_dev.currentData() or "") if a.driver != "ASIO" else ""
        a.samplerate = int(self.sr.currentData() or 0)
        a.blocksize = int(self.bs.currentData() or 128)
        a.wasapi_exclusive = self.excl.isChecked()
        return a

    def _update_panic_key_btn(self):
        hk = self._panic_hotkey_work
        self.panic_key_btn.setText(hk.label if hk.is_set() else "Not set")

    def _pick_panic_hotkey(self):
        dlg = HotkeyDialog(self.core, self, "All-off hotkey")
        if dlg.exec() and dlg.result_hotkey is not None:
            hk = dlg.result_hotkey
            if hk.is_set():
                clash = self.core.find_hotkey_conflict(hk, exclude=self.cfg.panic_hotkey)
                if clash:
                    QMessageBox.warning(self, "Hotkey in use", f"{hk.label} is already used by {clash}.")
                    return
            self._panic_hotkey_work = hk
            self._update_panic_key_btn()

    def apply_all(self):
        # Idle mode, hotkeys, all-off key
        self.cfg.idle_mode = self.idle_combo.currentData() or "dry"
        self.cfg.hotkeys_enabled = self.hotkeys_check.isChecked()
        self.core.hotkeys.enabled = self.cfg.hotkeys_enabled
        self.cfg.panic_hotkey = copy.deepcopy(self._panic_hotkey_work)
        self.core.rebind_hotkeys()
        self.core._apply()

        self.cfg.launch_at_startup = self.launch_startup.isChecked()
        set_startup_enabled(self.launch_startup.isChecked(), start_minimized=self.minimized.isChecked())

        self.cfg.autostart_audio = self.autostart.isChecked()
        self.cfg.close_to_tray = self.tray.isChecked()
        self.cfg.start_minimized = self.minimized.isChecked()
        self.cfg.keep_chains_awake = self.keep_awake.isChecked()
        self.core.engine.keep_awake = self.keep_awake.isChecked()

        # Limiter
        self.cfg.limiter.enabled = self.lim_en.isChecked()
        self.cfg.limiter.threshold_db = float(self.lim_thresh.value())
        self.core.set_limiter(self.cfg.limiter)

        # PTT
        self.core.update_ptt_mode(self.ptt_mode.currentData())

        # MIDI
        mdev = self.midi_dev.currentText()
        if mdev == "None":
            mdev = ""
        self.cfg.midi_bindings = list(self._midi_bindings_work)
        self.core.set_midi_device(mdev)

        # Overlay
        self.cfg.overlay.enabled = self.ov_en.isChecked()
        self.cfg.overlay.position = self.ov_pos.currentData()
        self.cfg.overlay.opacity = float(self.ov_opacity.value()) / 100.0
        self.cfg.overlay.hide_when_clean = self.ov_hide_clean.isChecked()
        self.core._sync_overlay()

        # Monitor Mode
        self.core.set_monitor_mode(self.mon_mode.currentData())

        # Appearance: store every id first so the core setters apply the final look once
        new_skin = self.skin_combo.currentData() or self.cfg.ui_skin
        new_frame = self.frame_combo.currentData() or self.cfg.chassis_frame
        new_theme = self.theme_combo.currentData() or self.cfg.theme
        new_switch_style = self.switch_combo.currentData() or self.cfg.switch_style
        self.cfg.ui_skin, self.cfg.chassis_frame = new_skin, new_frame
        self.cfg.theme, self.cfg.switch_style = new_theme, new_switch_style
        self.core.set_ui_skin(new_skin)
        self.core.set_chassis_frame(new_frame)
        self.core.set_theme(new_theme)
        self.core.set_switch_style(new_switch_style)

        # Normalizer
        if hasattr(self, "norm_en"):
            self.core.set_normalizer(self.norm_en.isChecked(), float(self.norm_target.value()))

        # Local API
        if hasattr(self, "api_en"):
            self.core.set_api_enabled(self.api_en.isChecked(), int(self.api_port_spin.value()))

    def _launch_setup_assistant(self):
        dlg = SetupAssistantDialog(self.core, self)
        if dlg.exec():
            # Refresh audio controls if wizard updated devices
            self._fill_drivers(self.cfg.audio)

    def _preview_look(self) -> Look:
        return look_for(self.theme_combo.currentData() or "scarlet",
                        self.skin_combo.currentData() or "skeuomorphic",
                        self.frame_combo.currentData() or "auto",
                        self.switch_combo.currentData() if hasattr(self, "switch_combo") else None)

    def _on_appearance_preview_changed(self, _=None):
        look = self._preview_look()
        if look != current_look():
            set_look(look)

    def reject(self):
        if current_look() != self._orig_look:
            set_look(self._orig_look)
        super().reject()
