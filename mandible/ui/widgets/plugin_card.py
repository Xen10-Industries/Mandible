"""Plugin rack card."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ... import plugins as P
from ...config import Chain, PluginSlot
from ...core import Core, inst, slot_error
from .buttons import RackToolButton
from .chassis import RackScrew
from .knobs import PluginParamKnob
from .meters import PluginPrePostMeter
from .switches import HardwareSwitch


class PluginRackCard(QFrame):
    """1U/2U modular rack unit faceplate with vertical bypass switch, Pre/Post level meters,
    collapsible mappable VST3 parameter macro knobs, and skin-aware styling."""
    powerToggled = Signal(bool)
    editClicked = Signal()
    mapClicked = Signal()
    macrosCollapseToggled = Signal()
    hotkeyClicked = Signal()
    moveUpClicked = Signal()
    moveDownClicked = Signal()
    removeClicked = Signal()

    def __init__(self, slot: PluginSlot, chain: Chain, core: Core, parent=None):
        super().__init__(parent)
        self.slot = slot
        self.chain = chain
        self.core = core
        self.param_knobs: list[PluginParamKnob] = []
        self.setObjectName("pluginRackCard")
        if not slot.enabled:
            self.setProperty("bypassed", "true")

        err = slot_error(slot)
        if err:
            self.setProperty("error", "true")

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(10, 7, 10, 7)
        outer_lay.setSpacing(6)

        # ---- Top Row: 1U Module Faceplate Header
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # Left Rack Screw
        lay.addWidget(RackScrew(12))

        # Slot index label
        idx = chain.plugins.index(slot) + 1 if slot in chain.plugins else 1
        slot_lbl = QLabel(f"{idx:02d}")
        slot_lbl.setObjectName("rackSlotIndex")
        lay.addWidget(slot_lbl)

        # 1. Tactile Physical Hardware Bypass Switch (Vertical throw in Effects Rack)
        self.pwr_switch = HardwareSwitch(active=slot.enabled, compact=True, vertical=True)
        self.pwr_switch.setToolTip("Click to toggle enable / bypass (UP=Active, DOWN=Bypass)")
        self.pwr_switch.toggled.connect(self.powerToggled.emit)
        lay.addWidget(self.pwr_switch)

        # 2. Plugin Info Column
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_lbl = QLabel(slot.display_name or slot.path)
        f = name_lbl.font()
        f.setBold(True)
        f.setPointSize(9.5)
        name_lbl.setFont(f)
        name_row.addWidget(name_lbl)

        # Vendor name
        v_name = P.guess_vendor(slot.path) if hasattr(P, "guess_vendor") else ""
        if v_name:
            v_badge = QLabel(v_name)
            v_badge.setObjectName("vendorBadge")
            name_row.addWidget(v_badge)

        # VST Format Badge
        fmt_badge = QLabel("VST3")
        fmt_badge.setObjectName("formatBadge")
        name_row.addWidget(fmt_badge)

        # Keep-Awake Badge (Serum 2 / persistent silence pump)
        is_serum = "serum" in (slot.display_name or slot.path).lower()
        if is_serum or getattr(core.cfg, "keep_chains_awake", False):
            awake_badge = QLabel("KEEP-AWAKE ACTIVE")
            awake_badge.setObjectName("awakeBadge")
            name_row.addWidget(awake_badge)

        if err:
            err_lbl = QLabel(f"ERROR: {err}")
            err_lbl.setObjectName("rackSlotError")
            name_row.addWidget(err_lbl)

        name_row.addStretch()
        info_col.addLayout(name_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)

        # Latency chip (zero emojis)
        inst_p = inst(slot)
        lat_smp = getattr(inst_p, "latency_samples", 0) if inst_p else 0
        sr = core.engine.samplerate or 48000
        lat_ms = (lat_smp / sr) * 1000.0 if sr else 0.0
        lat_txt = f"{lat_ms:.1f} ms ({lat_smp} smp)" if lat_smp > 0 else "0.0 ms (0 smp)"
        lat_chip = QLabel(f"LATENCY: {lat_txt}")
        lat_chip.setObjectName("latencyChip")
        sub_row.addWidget(lat_chip)

        # Bypass Hotkey chip
        hk_txt = f"KEY: [{slot.bypass_hotkey.label.upper()}]" if slot.bypass_hotkey.is_set() else "+ BYPASS KEY"
        hk_btn = QPushButton(hk_txt)
        hk_btn.setObjectName("rackHotkeyBtn")
        hk_btn.setToolTip("Assign a hotkey to toggle/bypass this plugin")
        hk_btn.clicked.connect(self.hotkeyClicked.emit)
        sub_row.addWidget(hk_btn)

        sub_row.addStretch()
        info_col.addLayout(sub_row)
        lay.addLayout(info_col, 1)

        # 3. Calibrated Pre / Post Level Meter Module
        self.pre_post_meter = PluginPrePostMeter(enabled=slot.enabled, parent=self)
        lay.addWidget(self.pre_post_meter)

        # 4. Actions: Collapse Macros (1U/2U), MAP, OPEN UI, Up, Down, Remove
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        mapped_keys = P.resolve_slot_mapped_params(slot, core.cfg)
        is_collapsed = bool(getattr(slot, "macros_collapsed", False))

        if mapped_keys:
            arrow = "▼" if is_collapsed else "▲"
            col_btn = QPushButton(f"{arrow} KNOBS ({len(mapped_keys)})")
            col_btn.setObjectName("rackKnobsBtn")
            col_btn.setToolTip(
                "Expand VST macro knobs (2U view)"
                if is_collapsed
                else "Collapse VST macro knobs to compact 1U display"
            )
            col_btn.clicked.connect(self._toggle_macros_collapsed)
            btn_row.addWidget(col_btn)

        map_txt = f"MAP ({len(mapped_keys)})" if mapped_keys else "MAP"
        self.map_btn = QPushButton(map_txt)
        self.map_btn.setObjectName("rackMapBtn")
        self.map_btn.setProperty("mapped", "true" if mapped_keys else "false")
        self.map_btn.setToolTip("Map VST plugin parameters to hardware macro knobs on this module")
        self.map_btn.clicked.connect(self.mapClicked.emit)
        btn_row.addWidget(self.map_btn)

        ui_btn = QPushButton("OPEN UI")
        ui_btn.setObjectName("rackUiBtn")
        ui_btn.setToolTip("Open the VST plugin window")
        ui_btn.clicked.connect(self.editClicked.emit)
        btn_row.addWidget(ui_btn)

        up_btn = RackToolButton("up", "Move earlier in signal chain")
        up_btn.clicked.connect(self.moveUpClicked.emit)
        btn_row.addWidget(up_btn)

        dn_btn = RackToolButton("down", "Move later in signal chain")
        dn_btn.clicked.connect(self.moveDownClicked.emit)
        btn_row.addWidget(dn_btn)

        rm_btn = RackToolButton("remove", "Remove plugin from chain")
        rm_btn.clicked.connect(self.removeClicked.emit)
        btn_row.addWidget(rm_btn)

        lay.addLayout(btn_row)

        # Right Rack Screw
        lay.addWidget(RackScrew(12))
        outer_lay.addLayout(lay)

        # ---- Bottom Row: Recessed Hardware Macro Knob Strip (when parameters are mapped & not collapsed)
        if mapped_keys and not is_collapsed:
            knob_bay = QFrame()
            knob_bay.setObjectName("pluginMacroBay")   # styled by the generated stylesheet
            kb_lay = QHBoxLayout(knob_bay)
            kb_lay.setContentsMargins(10, 4, 10, 4)
            kb_lay.setSpacing(8)

            bay_lbl = QLabel("PLUGIN\nMACROS")
            bay_lbl.setObjectName("rackBayLabel")
            kb_lay.addWidget(bay_lbl)

            vsep = QFrame()
            vsep.setFrameShape(QFrame.VLine)
            vsep.setObjectName("rackBaySeparator")
            kb_lay.addWidget(vsep)

            for pkey in mapped_keys[:8]:
                kn = PluginParamKnob(slot, pkey, core, knob_bay)
                self.param_knobs.append(kn)
                kb_lay.addWidget(kn)

            kb_lay.addStretch()
            outer_lay.addWidget(knob_bay)

    def _toggle_macros_collapsed(self):
        self.slot.macros_collapsed = not bool(getattr(self.slot, "macros_collapsed", False))
        self.core.save()
        self.macrosCollapseToggled.emit()

    def has_knobs(self) -> bool:
        return len(self.param_knobs) > 0

    def sync_knobs_from_plugin(self):
        for kn in self.param_knobs:
            kn.sync_from_plugin()
