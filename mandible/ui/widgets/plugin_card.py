"""Plugin rack card."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import plugins as P
from ...config import Chain, PluginSlot
from ...core import Core, inst, slot_error
from ...internal_dsp import is_internal_plugin
from .base import SpacedLayouts, _follow_look, reserve_text_width
from .buttons import StatusPill, make_button
from .knobs import PluginParamKnob
from .labels import ElidedLabel
from .meters import PluginPrePostMeter
from .switches import HardwareSwitch


MAX_CARD_KNOBS = 8


def map_label(mapped: int) -> str:
    """The map button's text: ``Map``, ``Map 1`` .. ``Map 8``, then ``Map 8+`` (a card shows
    at most ``MAX_CARD_KNOBS`` knobs, and the label's width is reserved for the widest text)."""
    if mapped <= 0:
        return "Map"
    if mapped > MAX_CARD_KNOBS:
        return f"Map {MAX_CARD_KNOBS}+"
    return f"Map {mapped}"


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

        self._spaced = SpacedLayouts()
        outer_lay = self._spaced.add(QVBoxLayout(self), spacing=1, margins=1)

        # ---- Top Row: 1U Module Faceplate Header
        lay = self._spaced.add(QHBoxLayout(), spacing=1, margins=0)

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
        info_col = self._spaced.add(QVBoxLayout(), spacing=1, margins=0)

        # The name elides (full text in the tooltip) instead of widening the card; badges
        # show only while the full name still fits beside them (their text joins the name's
        # tooltip), so a narrow card keeps the name rather than four stubs.
        self._name_row = name_row = self._spaced.add(QHBoxLayout(), spacing=1, margins=0)
        self.name_lbl = ElidedLabel(slot.display_name or slot.path, min_chars=4)
        self.name_lbl.setObjectName("rackPluginName")
        name_row.addWidget(self.name_lbl)
        self._badges: list[StatusPill] = []

        def badge(text: str, kind: str, tip: str = "", state: str = "off") -> StatusPill:
            b = StatusPill(text, state)
            b.setProperty("badge", kind)
            if tip:
                b.setToolTip(tip)
            b.setMinimumWidth(1)   # never part of the card's minimum width
            self._badges.append(b)
            name_row.addWidget(b)
            return b

        # Mandible's own effects are not VST3 plugins: they have no plugin window and say so.
        self.is_builtin = is_internal_plugin(slot.path)
        if self.is_builtin:
            badge("Built-in", "builtin", "Built into Mandible; not a VST3 plugin")
        else:
            badge("VST3", "format", "VST3 plugin")
        v_name = P.guess_vendor(slot.path) if hasattr(P, "guess_vendor") else ""
        if v_name:
            badge(v_name, "vendor")
        # Keep-awake badge (Serum 2 / persistent silence pump)
        is_serum = "serum" in (slot.display_name or slot.path).lower()
        if is_serum or getattr(core.cfg, "keep_chains_awake", False):
            badge("Kept awake", "awake", "A silent signal keeps this plugin from suspending", "on")
        self.name_lbl.setBaseToolTip(" · ".join([slot.path] + [b.text() for b in self._badges]))

        if err:
            err_lbl = ElidedLabel(f"ERROR: {err}", min_chars=5)
            err_lbl.setObjectName("rackSlotError")
            name_row.addWidget(err_lbl)

        name_row.addStretch()
        info_col.addLayout(name_row)

        sub_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)

        # Latency chip: the plugin's own reported latency, in ms and samples.
        lat_smp = P.get_slot_latency_samples(slot)
        sr = core.engine.samplerate or 48000
        lat_ms = lat_smp / sr * 1000.0
        lat_chip = ElidedLabel(f"{lat_ms:.1f} ms ({lat_smp} smp)", min_chars=3)
        lat_chip.setBaseToolTip(f"Plugin latency: {lat_ms:.1f} ms ({lat_smp} samples at {sr:g} Hz)")
        lat_chip.setObjectName("latencyChip")
        sub_row.addWidget(lat_chip)

        # Bypass Hotkey chip
        hk_txt = slot.bypass_hotkey.label if slot.bypass_hotkey.is_set() else "Bypass key"
        hk_btn = make_button(hk_txt, "quiet", icon="hotkey",
                             tooltip="Assign a hotkey to toggle/bypass this plugin")
        hk_btn.setProperty("small", "true")
        hk_btn.setObjectName("rackBypassKeyBtn")
        hk_btn.clicked.connect(self.hotkeyClicked.emit)
        sub_row.addWidget(hk_btn)

        sub_row.addStretch()
        info_col.addLayout(sub_row)
        lay.addLayout(info_col, 1)

        # 3. Calibrated Pre / Post Level Meter Module
        self.pre_post_meter = PluginPrePostMeter(enabled=slot.enabled, parent=self)
        lay.addWidget(self.pre_post_meter)

        # 4. Actions: a right-aligned cluster of fixed width (the same on every card, so the
        #    columns line up): knobs disclosure, map, open UI, move up/down, remove; all quiet.
        mapped_keys = P.resolve_slot_mapped_params(slot, core.cfg)
        is_collapsed = bool(getattr(slot, "macros_collapsed", False))

        self.actions = QWidget()
        self.actions.setObjectName("rackActions")
        btn_row = self._spaced.add(QHBoxLayout(self.actions), spacing=1, margins=0)

        # Disclosure chevron: right while the knobs are hidden, down while they show.
        self.knobs_btn = make_button(
            tier="quiet", icon="chevron_right" if is_collapsed else "chevron_down",
            tooltip=(f"Show the {len(mapped_keys)} macro knobs" if is_collapsed
                     else f"Hide the {len(mapped_keys)} macro knobs"))
        self.knobs_btn.clicked.connect(self._toggle_macros_collapsed)
        # Cards without mapped knobs keep the slot so every cluster has the same layout.
        policy = self.knobs_btn.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.knobs_btn.setSizePolicy(policy)
        self.knobs_btn.setVisible(bool(mapped_keys))
        btn_row.addWidget(self.knobs_btn)

        n_mapped = len(mapped_keys)
        if n_mapped > MAX_CARD_KNOBS:
            map_tip = (f"{n_mapped} parameters mapped; the first {MAX_CARD_KNOBS} show as knobs: "
                       "change the mapping")
        elif n_mapped:
            map_tip = f"{n_mapped} parameters on macro knobs: change the mapping"
        else:
            map_tip = "Map plugin parameters to macro knobs on this module"
        self.map_btn = make_button(map_label(n_mapped), "quiet", icon="map", tooltip=map_tip)
        self.map_btn.setProperty("small", "true")
        self.map_btn.setObjectName("rackMapBtn")
        self.map_btn.setProperty("mapped", "true" if mapped_keys else "false")
        self.map_btn.clicked.connect(self.mapClicked.emit)
        btn_row.addWidget(self.map_btn)

        self.ui_btn = make_button(tier="quiet", icon="open_window", tooltip="Open the plugin window")
        self.ui_btn.clicked.connect(self.editClicked.emit)
        # Built-in effects have no plugin window; the slot stays so every cluster lines up.
        policy = self.ui_btn.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.ui_btn.setSizePolicy(policy)
        has_custom_ui = bool(getattr(inst(slot), "has_custom_editor", False))
        if self.is_builtin and not has_custom_ui:
            self.ui_btn.setVisible(False)
        elif self.is_builtin and has_custom_ui:
            if slot.path == "internal:lfo":
                self.ui_btn.setToolTip("Open LFO modulation settings")
            else:
                self.ui_btn.setToolTip("Open AI voice model settings")
        elif inst(slot) is None:
            self.ui_btn.setEnabled(False)
            self.ui_btn.setToolTip("The plugin is not loaded, so it has no window to open")
        btn_row.addWidget(self.ui_btn)

        up_btn = make_button(tier="quiet", icon="up", tooltip="Move earlier in signal chain")
        up_btn.clicked.connect(self.moveUpClicked.emit)
        btn_row.addWidget(up_btn)

        dn_btn = make_button(tier="quiet", icon="down", tooltip="Move later in signal chain")
        dn_btn.clicked.connect(self.moveDownClicked.emit)
        btn_row.addWidget(dn_btn)

        rm_btn = make_button(tier="quiet", icon="remove", tooltip="Remove plugin from chain")
        rm_btn.clicked.connect(self.removeClicked.emit)
        btn_row.addWidget(rm_btn)

        lay.addWidget(self.actions)

        outer_lay.addLayout(lay)
        reserve_text_width(self.map_btn, map_label(MAX_CARD_KNOBS + 1))
        self._fix_actions_width()

        # ---- Bottom Row: Recessed Hardware Macro Knob Strip (when parameters are mapped & not collapsed)
        if mapped_keys and not is_collapsed:
            knob_bay = QFrame()
            knob_bay.setObjectName("pluginMacroBay")   # styled by the generated stylesheet
            kb_lay = self._spaced.add(QHBoxLayout(knob_bay), spacing=1, margins=(2, 1, 2, 1))

            self.bay_lbl = QLabel("MACROS")
            self.bay_lbl.setObjectName("rackBayLabel")
            self.bay_lbl.setToolTip("Plugin parameters mapped to knobs")
            kb_lay.addWidget(self.bay_lbl)

            vsep = QFrame()
            vsep.setFrameShape(QFrame.VLine)
            vsep.setObjectName("rackBaySeparator")
            kb_lay.addWidget(vsep)

            for pkey in mapped_keys[:MAX_CARD_KNOBS]:
                kn = PluginParamKnob(slot, pkey, core, knob_bay)
                self.param_knobs.append(kn)
                kb_lay.addWidget(kn)

            kb_lay.addStretch()
            outer_lay.addWidget(knob_bay)
        _follow_look(self)

    def _fit_badges(self) -> None:
        avail = self._name_row.geometry().width()
        if avail <= 0:
            return
        gap = self._name_row.spacing()
        used = self.name_lbl.sizeHint().width()
        err = [w for w in (self.findChild(QLabel, "rackSlotError"),) if w is not None]
        for w in err:
            used += gap + w.minimumSizeHint().width()
        for b in self._badges:
            w = gap + b.sizeHint().width()
            show = used + w <= avail
            if show:
                used += w
            if b.isHidden() == show:
                b.setVisible(show)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._fit_badges()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._fit_badges()

    def _fix_actions_width(self) -> None:
        self.actions.setMinimumWidth(0)
        self.actions.setMaximumWidth(16777215)
        self.actions.setFixedWidth(self.actions.sizeHint().width())

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._fix_actions_width()

    def _toggle_macros_collapsed(self):
        self.slot.macros_collapsed = not bool(getattr(self.slot, "macros_collapsed", False))
        self.core.save()
        self.macrosCollapseToggled.emit()

    def has_knobs(self) -> bool:
        return len(self.param_knobs) > 0

    def sync_knobs_from_plugin(self):
        for kn in self.param_knobs:
            kn.sync_from_plugin()
