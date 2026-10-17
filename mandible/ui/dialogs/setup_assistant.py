"""Universal Audio Setup Assistant wizard for Mandible.
Guides any user (with or without Focusrite) through microphone detection,
virtual cable routing into Discord/OBS, and headphone monitoring.
"""
from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QPainter, QLinearGradient
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget, QMessageBox
)

from ... import devices as D
from ..widgets.base import _follow_look, look_color, set_style_property

if TYPE_CHECKING:
    from ...core import Core


class LiveVuBar(QWidget):
    """Simple high-performance LED peak meter for mic test."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self._peak = 0.0
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def set_peak(self, val: float):
        # Slower decay
        val = max(0.0, min(1.0, float(val)))
        if val > self._peak:
            self._peak = val
        else:
            self._peak = max(0.0, self._peak - 0.05)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background trough
        p.fillRect(0, 0, w, h, look_color("bg.inset"))
        p.setPen(look_color("line.subtle"))
        p.drawRect(0, 0, w - 1, h - 1)

        # Active LED bar
        fill_w = int(w * self._peak)
        if fill_w > 0:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, look_color("status.ok"))
            grad.setColorAt(0.70, look_color("status.warn"))
            grad.setColorAt(0.92, look_color("status.danger"))
            p.fillRect(1, 1, fill_w, h - 2, grad)

        # Scale markings
        p.setPen(look_color("text.secondary"))
        p.setFont(QFont("Consolas", 6))
        for frac, label in [(0.5, "-12dB"), (0.75, "-6dB"), (0.9, "0dB")]:
            x = int(w * frac)
            p.drawLine(x, 0, x, 3)
            p.drawLine(x, h - 3, x, h)


class SetupAssistantDialog(QDialog):
    """Multi-step setup wizard for universal Windows audio routing."""

    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("Mandible - Audio Setup Assistant")
        self.resize(680, 520)
        self.setObjectName("setupAssistant")

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(24, 20, 24, 20)
        main_lay.setSpacing(16)

        # Header
        head_box = QHBoxLayout()
        title_box = QVBoxLayout()
        self.step_lbl = QLabel("STEP 1 OF 4")
        self.step_lbl.setObjectName("wizardStep")
        self.main_title = QLabel("Select Your Microphone")
        self.main_title.setObjectName("wizardTitle")
        title_box.addWidget(self.step_lbl)
        title_box.addWidget(self.main_title)
        head_box.addLayout(title_box)
        head_box.addStretch()
        main_lay.addLayout(head_box)

        # Wizard pages
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_step1_mic())
        self.pages.addWidget(self._build_step2_cable())
        self.pages.addWidget(self._build_step3_monitor())
        self.pages.addWidget(self._build_step4_guide())
        main_lay.addWidget(self.pages, 1)

        # Bottom navigation
        nav_box = QHBoxLayout()
        self.back_btn = QPushButton("< BACK")
        self.back_btn.clicked.connect(self._prev_step)
        self.back_btn.setEnabled(False)
        nav_box.addWidget(self.back_btn)
        nav_box.addStretch()

        self.next_btn = QPushButton("NEXT: OUTPUT ROUTING >")
        self.next_btn.setObjectName("wizardNextBtn")
        self.next_btn.clicked.connect(self._next_step)
        nav_box.addWidget(self.next_btn)
        main_lay.addLayout(nav_box)

        # Timer for live mic test meter
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._poll_mic_meter)
        self._meter_timer.start(30)

        # Populate initial device states
        self._load_current_settings()

    def _load_current_settings(self):
        # Driver
        drivers = D.drivers()
        self.mic_drv.clear()
        for d in drivers:
            self.mic_drv.addItem(D.DRIVER_LABELS.get(d, d), d)
        
        cur_drv = self.core.cfg.audio.driver or (drivers[0] if drivers else "")
        idx = self.mic_drv.findData(cur_drv)
        if idx >= 0:
            self.mic_drv.setCurrentIndex(idx)
        self._on_driver_changed()

    # ------------------------------------------------------------- Step 1: Mic
    def _build_step1_mic(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)

        desc = QLabel(
            "Choose the microphone you speak into. If you have an audio interface (Focusrite, Motu, etc.), "
            "select ASIO or WASAPI. For USB mics (NexiGo, Blue Yeti, HyperX), select WASAPI."
        )
        desc.setWordWrap(True)
        desc.setObjectName("wizardDesc")
        lay.addWidget(desc)

        # Driver
        drv_box = QVBoxLayout()
        drv_lbl = QLabel("AUDIO DRIVER:")
        drv_lbl.setObjectName("wizardFieldLabel")
        self.mic_drv = QComboBox()
        self.mic_drv.currentIndexChanged.connect(self._on_driver_changed)
        drv_box.addWidget(drv_lbl)
        drv_box.addWidget(self.mic_drv)
        lay.addLayout(drv_box)

        # Input device
        dev_box = QVBoxLayout()
        dev_lbl = QLabel("INPUT MICROPHONE:")
        dev_lbl.setObjectName("wizardFieldLabel")
        self.mic_dev = QComboBox()
        self.mic_dev.currentIndexChanged.connect(self._on_mic_device_changed)
        dev_box.addWidget(dev_lbl)
        dev_box.addWidget(self.mic_dev)
        lay.addLayout(dev_box)

        # Input channel
        ch_box = QVBoxLayout()
        ch_lbl = QLabel("MIC INPUT CHANNEL:")
        ch_lbl.setObjectName("wizardFieldLabel")
        self.mic_ch = QComboBox()
        ch_box.addWidget(ch_lbl)
        ch_box.addWidget(self.mic_ch)
        lay.addLayout(ch_box)

        # Live VU meter
        meter_box = QVBoxLayout()
        m_head = QHBoxLayout()
        m_lbl = QLabel("LIVE MICROPHONE LEVEL (Speak to test):")
        m_lbl.setObjectName("wizardFieldLabel")
        self.mic_status_lbl = QLabel("Awaiting sound...")
        self.mic_status_lbl.setObjectName("wizardMicStatus")
        m_head.addWidget(m_lbl)
        m_head.addStretch()
        m_head.addWidget(self.mic_status_lbl)
        meter_box.addLayout(m_head)

        self.mic_vubar = LiveVuBar()
        meter_box.addWidget(self.mic_vubar)
        lay.addLayout(meter_box)

        lay.addStretch()
        return w

    def _on_driver_changed(self):
        drv = self.mic_drv.currentData()
        if not drv:
            return
        self.mic_dev.clear()
        ins = D.list_devices(drv, "input")
        for idx, name, chans in ins:
            self.mic_dev.addItem(name, name)
        cur_in = self.core.cfg.audio.input_device
        idx = self.mic_dev.findData(cur_in)
        if idx >= 0:
            self.mic_dev.setCurrentIndex(idx)
        self._on_mic_device_changed()

    def _on_mic_device_changed(self):
        drv = self.mic_drv.currentData()
        dev_name = self.mic_dev.currentData()
        self.mic_ch.clear()
        if not drv or not dev_name:
            return
        idx = D.find_device(drv, dev_name, "input")
        if idx is not None:
            names = D.channel_names(drv, idx, "input")
            for i, n in enumerate(names):
                self.mic_ch.addItem(f"CH {i+1}: {n}", i)
        cur_ch = self.core.cfg.audio.input_channel
        if 0 <= cur_ch < self.mic_ch.count():
            self.mic_ch.setCurrentIndex(cur_ch)

    def _poll_mic_meter(self):
        pk = self.core.engine.peak_in
        self.mic_vubar.set_peak(pk)
        if pk > 0.05:
            db = 20.0 * np.log10(max(1e-4, pk))
            self.mic_status_lbl.setText(f"SIGNAL OK: {db:.1f} dBFS")
            if not self.mic_status_lbl.property("ok"):
                set_style_property(self.mic_status_lbl, "ok", True)

    # ------------------------------------------------------------- Step 2: Cable
    def _build_step2_cable(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)

        desc = QLabel(
            "Mandible modifies your voice in real time, then sends the audio to a Virtual Audio Cable "
            "(or Focusrite Loopback). In Discord and OBS, you simply select that cable as your microphone!"
        )
        desc.setWordWrap(True)
        desc.setObjectName("wizardDesc")
        lay.addWidget(desc)

        # Status card
        self.cable_card = QFrame()
        self.cable_card.setObjectName("wizardCard")
        card_lay = QVBoxLayout(self.cable_card)
        self.cable_card_title = QLabel("DETECTING VIRTUAL AUDIO CABLES...")
        self.cable_card_title.setObjectName("wizardCardTitle")
        self.cable_card_desc = QLabel("Checking Windows for VB-Audio Virtual Cable and Focusrite Loopback...")
        self.cable_card_desc.setWordWrap(True)
        self.cable_card_desc.setObjectName("wizardCardDesc")
        card_lay.addWidget(self.cable_card_title)
        card_lay.addWidget(self.cable_card_desc)
        lay.addWidget(self.cable_card)

        # Download / Refresh buttons
        action_row = QHBoxLayout()
        self.download_cable_btn = QPushButton("DOWNLOAD FREE VB-AUDIO CABLE")
        self.download_cable_btn.setObjectName("wizardDownloadBtn")
        self.download_cable_btn.clicked.connect(lambda: webbrowser.open("https://vb-audio.com/Cable/"))
        action_row.addWidget(self.download_cable_btn)

        self.rescan_btn = QPushButton("REFRESH DEVICE LIST")
        self.rescan_btn.clicked.connect(self._rescan_cable_devices)
        action_row.addWidget(self.rescan_btn)
        lay.addLayout(action_row)

        # Output device selector
        out_box = QVBoxLayout()
        out_lbl = QLabel("SEND MANDIBLE OUTPUT TO (Cable / Loopback):")
        out_lbl.setObjectName("wizardFieldLabel")
        self.cable_dev_combo = QComboBox()
        out_box.addWidget(out_lbl)
        out_box.addWidget(self.cable_dev_combo)
        lay.addLayout(out_box)

        lay.addStretch()
        return w

    def _rescan_cable_devices(self):
        try:
            D.rescan()
        except Exception:
            pass
        self._refresh_cable_detection()

    def _set_cable_state(self, state: str):
        """``ok`` / ``warn`` on the card and its two labels (the stylesheet has no ancestor rule)."""
        for w in (self.cable_card, self.cable_card_title, self.cable_card_desc):
            set_style_property(w, "state", state)

    def _refresh_cable_detection(self):
        cables = D.detect_virtual_cables()
        self.cable_dev_combo.clear()

        # Also get all output devices for currently selected driver
        drv = self.mic_drv.currentData() or "Windows WASAPI"
        outs = D.list_devices(drv, "output")
        for idx, name, chans in outs:
            self.cable_dev_combo.addItem(name, (drv, name))

        if cables:
            best = cables[0]
            self._set_cable_state("ok")
            self.cable_card_title.setText(f"READY: {best['desc']} Detected")
            self.cable_card_desc.setText(f"Detected: {best['device']}. Mandible will stream processed voice here.")
            
            # Pre-select in combo
            idx = self.cable_dev_combo.findText(best["device"])
            if idx >= 0:
                self.cable_dev_combo.setCurrentIndex(idx)
        else:
            self._set_cable_state("warn")
            self.cable_card_title.setText("NOTE: No Virtual Audio Cable Detected")
            self.cable_card_desc.setText(
                "Windows doesn't have a virtual cable installed. Click 'Download Free VB-Audio Cable' below, "
                "run the installer, and click 'Refresh Device List'."
            )

    # ------------------------------------------------------------- Step 3: Monitor
    def _build_step3_monitor(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)

        desc = QLabel(
            "Select your headphones or speakers so you can monitor your voice in real time and audition "
            "pitch, soundboard clips, and effects without hearing an echo in Discord."
        )
        desc.setWordWrap(True)
        desc.setObjectName("wizardDesc")
        lay.addWidget(desc)

        mon_box = QVBoxLayout()
        mon_lbl = QLabel("HEADPHONE / MONITOR DEVICE:")
        mon_lbl.setObjectName("wizardFieldLabel")
        self.mon_dev_combo = QComboBox()
        mon_box.addWidget(mon_lbl)
        mon_box.addWidget(self.mon_dev_combo)
        lay.addLayout(mon_box)

        # Monitor feed mode
        feed_box = QVBoxLayout()
        feed_lbl = QLabel("WHAT DO YOU WANT TO HEAR IN HEADPHONES?:")
        feed_lbl.setObjectName("wizardFieldLabel")
        self.mon_feed_combo = QComboBox()
        self.mon_feed_combo.addItem("Processed Voice (hear your effects & soundboard)", "processed")
        self.mon_feed_combo.addItem("Clean Mic (zero-latency direct mic monitor)", "dry")
        self.mon_feed_combo.addItem("50/50 Mix (blend of both)", "mix")
        feed_box.addWidget(feed_lbl)
        feed_box.addWidget(self.mon_feed_combo)
        lay.addLayout(feed_box)

        # Test headphone monitor button
        test_box = QHBoxLayout()
        self.test_audio_btn = QPushButton("TEST HEADPHONES (PLAY AUDIO CHIME)")
        self.test_audio_btn.clicked.connect(self._test_headphones)
        test_box.addWidget(self.test_audio_btn)
        lay.addLayout(test_box)

        lay.addStretch()
        return w

    def _refresh_monitor_devices(self):
        drv = self.mic_drv.currentData() or "Windows WASAPI"
        outs = D.list_devices(drv, "output")
        self.mon_dev_combo.clear()
        self.mon_dev_combo.addItem("Disabled (No headphone monitor)", "")
        for idx, name, chans in outs:
            # Filter out cables from headphone list
            nl = name.lower()
            if "cable input" in nl:
                continue
            self.mon_dev_combo.addItem(name, name)
        
        cur_mon = self.core.cfg.audio.monitor_device
        idx = self.mon_dev_combo.findData(cur_mon)
        if idx >= 0:
            self.mon_dev_combo.setCurrentIndex(idx)

    def _test_headphones(self):
        try:
            import sounddevice as sd
            sr = 44100
            t = np.linspace(0, 0.4, int(sr * 0.4), endpoint=False)
            # Gentle chord chime: C5 + E5 + G5
            chord = 0.15 * (np.sin(2 * np.pi * 523.25 * t) + np.sin(2 * np.pi * 659.25 * t) + np.sin(2 * np.pi * 783.99 * t))
            env = np.exp(-t * 6.0)
            sig = (chord * env).astype(np.float32)
            stereo = np.column_stack([sig, sig])
            sd.play(stereo, sr)
        except Exception as exc:
            QMessageBox.information(self, "Headphone Test", f"Could not play test sound: {exc}")

    # ------------------------------------------------------------- Step 4: Discord / OBS Guide
    def _build_step4_guide(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)

        guide_card = QFrame()
        guide_card.setObjectName("wizardGuideCard")
        g_lay = QVBoxLayout(guide_card)
        g_lay.setSpacing(10)

        g_title = QLabel("CONNECTING TO DISCORD, OBS & GAMES:")
        g_title.setObjectName("wizardGuideTitle")
        g_lay.addWidget(g_title)

        steps = [
            ("1. Open Discord Settings", "Go to User Settings -> Voice & Video."),
            ("2. Set INPUT DEVICE", "Select 'CABLE Output (VB-Audio Virtual Cable)' or your Focusrite Loopback."),
            ("3. Set OUTPUT DEVICE", "Select your standard headphones or speakers."),
            ("4. Disable Discord Echo Cancellation", "Turn off Discord's 'Echo Cancellation' and 'Noise Suppression' (Mandible provides high-end studio noise gates and VSTs!)."),
            ("5. OBS / Streamlabs", "Add an 'Audio Input Capture' source and select 'CABLE Output' as the device."),
        ]
        for num, text in steps:
            row = QHBoxLayout()
            s_num = QLabel(num)
            s_num.setObjectName("wizardGuideNum")
            s_txt = QLabel(text)
            s_txt.setObjectName("wizardGuideText")
            row.addWidget(s_num)
            row.addWidget(s_txt, 1)
            g_lay.addLayout(row)

        lay.addWidget(guide_card)
        lay.addStretch()
        return w

    # ------------------------------------------------------------- Wizard Navigation
    def _prev_step(self):
        idx = self.pages.currentIndex()
        if idx > 0:
            self._go_to_step(idx - 1)

    def _next_step(self):
        idx = self.pages.currentIndex()
        if idx == 0:
            self._refresh_cable_detection()
            self._go_to_step(1)
        elif idx == 1:
            self._refresh_monitor_devices()
            self._go_to_step(2)
        elif idx == 2:
            self._go_to_step(3)
        elif idx == 3:
            self._finish_and_apply()

    def _go_to_step(self, idx: int):
        self.pages.setCurrentIndex(idx)
        self.step_lbl.setText(f"STEP {idx + 1} OF 4")
        self.back_btn.setEnabled(idx > 0)
        titles = [
            "Select Your Microphone",
            "Output & Virtual Cable Setup",
            "Headphone Monitoring",
            "Discord & OBS Quick Connection",
        ]
        self.main_title.setText(titles[idx])
        if idx == 3:
            self.next_btn.setText("FINISH & APPLY ROUTING")
            set_style_property(self.next_btn, "final", True)
        else:
            next_titles = ["OUTPUT ROUTING >", "HEADPHONE MONITOR >", "CONNECTION GUIDE >"]
            self.next_btn.setText(f"NEXT: {next_titles[idx]}")
            set_style_property(self.next_btn, "final", False)

    def _finish_and_apply(self):
        # Save audio configuration
        a = self.core.cfg.audio
        a.driver = self.mic_drv.currentData() or "Windows WASAPI"
        a.input_device = self.mic_dev.currentData() or ""
        a.input_channel = int(self.mic_ch.currentData() or 0)
        a.output_device = self.cable_dev_combo.currentText() or ""
        a.output_channels = [0, 1]
        
        mon_dev = self.mon_dev_combo.currentData() or ""
        a.monitor_device = mon_dev
        self.core.cfg.monitor_enabled = bool(mon_dev)
        self.core.cfg.headphone_monitor_mode = self.mon_feed_combo.currentData() or "processed"

        self.core.save()
        self._meter_timer.stop()

        # Start audio engine
        try:
            self.core.start_audio()
        except Exception as exc:
            QMessageBox.warning(self, "Audio Start", f"Could not start audio with new settings:\n{exc}")

        self.accept()
