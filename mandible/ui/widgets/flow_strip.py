"""Signal flow strip."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ...audio_engine import DRY_ID
from ...core import Core
from .base import set_style_property


class SignalFlowStrip(QFrame):
    """Illuminated hardware signal routing bus (zero emojis)."""
    prefxClicked = Signal()
    soundboardClicked = Signal()
    limiterClicked = Signal()

    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setObjectName("signalFlowStrip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)

        lbl = QLabel("BUS:")
        lbl.setObjectName("flowBusLabel")
        lay.addWidget(lbl)

        # Stage 1: Mic In
        in_name = core.cfg.audio.input_device or "MIC IN"
        if len(in_name) > 18:
            in_name = in_name[:16] + "…"
        self.mic_pill = QLabel(f"{in_name.upper()} (CH {core.cfg.audio.input_channel + 1})")
        self.mic_pill.setObjectName("flowPill")
        lay.addWidget(self.mic_pill)

        lay.addWidget(self._arrow())

        # Stage 2: Pre-FX
        self.prefx_btn = QPushButton("RNNOISE")
        self.prefx_btn.setObjectName("flowBtn")
        self.prefx_btn.setToolTip("Click to configure Pre-FX RNNoise suppression and gate")
        self.prefx_btn.clicked.connect(self.prefxClicked.emit)
        lay.addWidget(self.prefx_btn)

        lay.addWidget(self._arrow())

        # Stage 3: Active Chain
        self.chain_pill = QLabel("PLUGIN RACK: CLEAN")
        self.chain_pill.setObjectName("flowPill")
        lay.addWidget(self.chain_pill)

        lay.addWidget(self._arrow())

        # Stage 4: Soundboard
        self.sb_btn = QPushButton("SOUNDBOARD")
        self.sb_btn.setObjectName("flowBtn")
        self.sb_btn.setToolTip("Soundboard audio playback clips")
        self.sb_btn.clicked.connect(self.soundboardClicked.emit)
        lay.addWidget(self.sb_btn)

        lay.addWidget(self._arrow())

        # Stage 5: Limiter
        self.lim_btn = QPushButton("LIMITER: ON")
        self.lim_btn.setObjectName("flowBtn")
        self.lim_btn.setToolTip("Click to toggle Master Safety Limiter")
        self.lim_btn.clicked.connect(self.limiterClicked.emit)
        lay.addWidget(self.lim_btn)

        lay.addWidget(self._arrow())

        # Stage 6: Outputs
        out_ch = core.cfg.audio.output_channels
        ch_str = f"CH {out_ch[0]+1}-{out_ch[1]+1}" if len(out_ch) >= 2 else "CH 3-4"
        self.out_pill = QLabel(f"V-MIC ({ch_str}) + PHONES")
        self.out_pill.setObjectName("flowPill")
        lay.addWidget(self.out_pill)

        lay.addStretch()

    def _arrow(self):
        a = QLabel("→")
        a.setObjectName("flowArrow")
        return a

    def refresh(self, target_id: str | None, active_chain_name: str):
        # 1. Update Pre-FX state
        p = self.core.cfg.prefx
        p_on = p.highpass_enabled or p.rnnoise_enabled or p.noise_gate_enabled
        self.prefx_btn.setText(f"RNNOISE: {'ON' if p_on else 'OFF'}")
        set_style_property(self.prefx_btn, "active", "true" if p_on else "false")

        # 2. Update Active Chain state
        is_fx = target_id is not None and target_id != DRY_ID
        clean_name = active_chain_name.replace("●", "").strip().upper()
        self.chain_pill.setText(f"PLUGIN RACK: {clean_name}")
        set_style_property(self.chain_pill, "active", "true" if is_fx else "false")

        # 3. Update Soundboard state
        n_clips = len(self.core.cfg.soundboard)
        self.sb_btn.setText(f"SOUNDBOARD ({n_clips})")

        # 4. Update Limiter state
        l_on = self.core.cfg.limiter.enabled
        self.lim_btn.setText(f"LIMITER: {'ON' if l_on else 'OFF'}")
        set_style_property(self.lim_btn, "active", "true" if l_on else "false")
