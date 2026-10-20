"""LFO Modulator configuration dialog: select target plugin & parameter knob, wave shape, rate, depth, and center."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ... import plugins as P
from ...config import Chain, PluginSlot
from ...core import Core, inst
from ...internal_dsp import LFO_SHAPES
from ..widgets.base import SpacedLayouts, _follow_look, reserve_text_width, set_style_property
from ..widgets.buttons import make_button
from .parts import group_label, hint_label, keep_wrapped_text_visible


class LFOModulatorDialog(QDialog):
    """Configure an ``internal:lfo`` slot's modulation target and oscillator parameters."""

    def __init__(self, slot: PluginSlot, chain: Chain | None, core: Core, parent=None):
        super().__init__(parent)
        self.slot = slot
        self.chain = chain
        self.core = core
        self.plugin = inst(slot)
        self._spaced = SpacedLayouts()
        _follow_look(self)

        self.setWindowTitle("LFO Modulator — Target & Wave")
        self.setMinimumWidth(560)
        self.resize(640, 480)

        lay = self._spaced.add(QVBoxLayout(self), spacing=2, margins=4)

        self.status_card = QFrame()
        self.status_card.setObjectName("wizardCard")
        set_style_property(self.status_card, "state", "ok")
        card_lay = self._spaced.add(QVBoxLayout(self.status_card), spacing=1, margins=3)

        self.status_title = QLabel("LFO Modulator active")
        self.status_title.setObjectName("wizardCardTitle")
        set_style_property(self.status_title, "state", "ok")
        self.status_title.setWordWrap(True)
        card_lay.addWidget(self.status_title)

        self.status_desc = QLabel(
            "Modulates any parameter knob in this chain in real time with selectable wave shapes."
        )
        self.status_desc.setObjectName("wizardCardDesc")
        self.status_desc.setWordWrap(True)
        card_lay.addWidget(self.status_desc)
        lay.addWidget(self.status_card)

        # Target routing
        group_label(lay, "Modulation target")
        target_form_w = QWidget()
        target_form = self._spaced.add(QFormLayout(target_form_w), spacing=2, margins=0)

        self.slot_combo = QComboBox()
        self.slot_combo.setAccessibleName("Target module")
        target_form.addRow("Target module", self.slot_combo)

        self.param_combo = QComboBox()
        self.param_combo.setAccessibleName("Target parameter")
        target_form.addRow("Target parameter", self.param_combo)

        lay.addWidget(target_form_w)
        self.target_hint = hint_label(
            "Select another module in this chain and choose which parameter knob the LFO sweeps."
        )
        lay.addWidget(self.target_hint)

        # Oscillator parameters
        group_label(lay, "Oscillator settings")
        osc_form_w = QWidget()
        osc_form = self._spaced.add(QFormLayout(osc_form_w), spacing=2, margins=0)

        self.shape_combo = QComboBox()
        for val, label in LFO_SHAPES:
            self.shape_combo.addItem(label, int(round(val)))
        osc_form.addRow("Wave shape", self.shape_combo)

        self._slider_pairs: list[tuple[QSlider, QDoubleSpinBox, int]] = []
        self.rate_slider, self.rate_spin = self._slider_spin(
            min_v=0.05, max_v=20.0, step=0.05, suffix=" Hz", decimals=2
        )
        osc_form.addRow("Rate", self._pair_row(self.rate_slider, self.rate_spin))

        self.depth_slider, self.depth_spin = self._slider_spin(
            min_v=0.0, max_v=100.0, step=1.0, suffix=" %", decimals=0
        )
        osc_form.addRow("Depth", self._pair_row(self.depth_slider, self.depth_spin))

        self.center_slider, self.center_spin = self._slider_spin(
            min_v=0.0, max_v=100.0, step=1.0, suffix=" %", decimals=0
        )
        osc_form.addRow("Center value", self._pair_row(self.center_slider, self.center_spin))

        lay.addWidget(osc_form_w)
        lay.addStretch(1)

        close_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        close_row.addStretch(1)
        self.close_btn = make_button("Close", "secondary")
        self.close_btn.clicked.connect(self.accept)
        close_row.addWidget(self.close_btn)
        lay.addLayout(close_row)

        self._reserve_button_widths()
        self._populate_targets()
        self._load_from_plugin()

        self.slot_combo.currentIndexChanged.connect(self._on_slot_changed)
        self.param_combo.currentIndexChanged.connect(self._on_param_changed)
        self.shape_combo.currentIndexChanged.connect(self._on_shape_changed)

        keep_wrapped_text_visible(self)

    def _on_look_changed(self) -> None:
        self._spaced.apply()
        self._reserve_button_widths()

    def _reserve_button_widths(self) -> None:
        reserve_text_width(self.close_btn, self.close_btn.text())

    def _slider_spin(
        self, *, min_v: float, max_v: float, step: float, suffix: str, decimals: int
    ) -> tuple[QSlider, QDoubleSpinBox]:
        scale = int(round(1.0 / step)) if step > 0 else 1
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(round(min_v * scale)), int(round(max_v * scale)))

        spin = QDoubleSpinBox()
        spin.setRange(min_v, max_v)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)

        self._slider_pairs.append((slider, spin, scale))
        slider.valueChanged.connect(self._on_any_slider_changed)
        spin.valueChanged.connect(self._on_any_spin_changed)
        return slider, spin

    def _on_any_slider_changed(self, _val: int) -> None:
        sender = self.sender()
        for slider, spin, scale in self._slider_pairs:
            if sender is slider:
                fval = slider.value() / scale
                spin.blockSignals(True)
                spin.setValue(fval)
                spin.blockSignals(False)
                break
        self._sync_to_plugin()

    def _on_any_spin_changed(self, _fval: float) -> None:
        sender = self.sender()
        for slider, spin, scale in self._slider_pairs:
            if sender is spin:
                slider.blockSignals(True)
                slider.setValue(int(round(spin.value() * scale)))
                slider.blockSignals(False)
                break
        self._sync_to_plugin()

    def _pair_row(self, slider: QSlider, spin: QDoubleSpinBox) -> QWidget:
        w = QWidget()
        row = self._spaced.add(QHBoxLayout(w), spacing=2, margins=0)
        row.addWidget(slider, 1)
        row.addWidget(spin)
        return w

    def _populate_targets(self) -> None:
        self.slot_combo.blockSignals(True)
        self.slot_combo.clear()
        self.slot_combo.addItem("None (unassigned)", -1)
        if self.chain is not None:
            for idx, s in enumerate(self.chain.plugins):
                if s is self.slot or getattr(s, "path", "") == "internal:lfo":
                    continue
                name = s.display_name or s.path
                self.slot_combo.addItem(f"Slot {idx + 1:02d} — {name}", idx)
        cur_idx = getattr(self.plugin, "target_slot_index", -1) if self.plugin is not None else -1
        combo_i = max(0, self.slot_combo.findData(cur_idx))
        self.slot_combo.setCurrentIndex(combo_i)
        self.slot_combo.blockSignals(False)
        self._populate_params(select_key=getattr(self.plugin, "target_param_key", "") if self.plugin else "")

    def _populate_params(self, select_key: str = "") -> None:
        self.param_combo.blockSignals(True)
        self.param_combo.clear()
        slot_idx = self.slot_combo.currentData()
        if (
            self.chain is not None
            and isinstance(slot_idx, int)
            and 0 <= slot_idx < len(self.chain.plugins)
        ):
            target_slot = self.chain.plugins[slot_idx]
            target_inst = inst(target_slot)
            for key, param in P.get_usable_parameters(target_inst):
                pname = str(getattr(param, "name", "") or key)
                self.param_combo.addItem(pname, key)
        if self.param_combo.count() == 0:
            self.param_combo.addItem("No target parameter", "")
            self.param_combo.setEnabled(False)
        else:
            self.param_combo.setEnabled(True)
            idx = max(0, self.param_combo.findData(select_key))
            self.param_combo.setCurrentIndex(idx)
        self.param_combo.blockSignals(False)
        self._update_status_banner()

    def _update_status_banner(self) -> None:
        slot_idx = self.slot_combo.currentData()
        param_key = self.param_combo.currentData() or ""
        if isinstance(slot_idx, int) and slot_idx >= 0 and param_key:
            self.status_title.setText(
                f"Modulating: {self.slot_combo.currentText()} → {self.param_combo.currentText()}"
            )
        else:
            self.status_title.setText("LFO Modulator ready (choose a target module & parameter)")

    def _load_from_plugin(self) -> None:
        if self.plugin is None:
            return
        params = getattr(self.plugin, "parameters", {})
        shape_p = params.get("shape")
        if shape_p is not None:
            self.shape_combo.blockSignals(True)
            self.shape_combo.setCurrentIndex(max(0, self.shape_combo.findData(int(round(shape_p.value)))))
            self.shape_combo.blockSignals(False)

        for key, slider, spin, scale in (
            ("rate_hz", self.rate_slider, self.rate_spin, 20),
            ("depth", self.depth_slider, self.depth_spin, 1),
            ("center", self.center_slider, self.center_spin, 1),
        ):
            p = params.get(key)
            if p is not None:
                val = float(p.value)
                slider.blockSignals(True)
                spin.blockSignals(True)
                spin.setValue(val)
                slider.setValue(int(round(val * scale)))
                slider.blockSignals(False)
                spin.blockSignals(False)

    def _sync_to_plugin(self) -> None:
        if self.plugin is None:
            return
        params = getattr(self.plugin, "parameters", {})
        for key, spin in (
            ("rate_hz", self.rate_spin),
            ("depth", self.depth_spin),
            ("center", self.center_spin),
        ):
            if key in params:
                params[key].value = float(spin.value())
        self._persist_state()

    def _on_slot_changed(self, _idx: int) -> None:
        self._populate_params()
        if self.plugin is not None:
            self.plugin.target_slot_index = int(self.slot_combo.currentData() or -1)
            self.plugin.target_param_key = str(self.param_combo.currentData() or "")
            self._persist_state()

    def _on_param_changed(self, _idx: int) -> None:
        self._update_status_banner()
        if self.plugin is not None:
            self.plugin.target_slot_index = int(self.slot_combo.currentData() or -1)
            self.plugin.target_param_key = str(self.param_combo.currentData() or "")
            self._persist_state()

    def _on_shape_changed(self, _idx: int) -> None:
        if self.plugin is not None:
            params = getattr(self.plugin, "parameters", {})
            if "shape" in params:
                params["shape"].value = float(self.shape_combo.currentData() or 0)
            self._persist_state()

    def _persist_state(self) -> None:
        if self.plugin is None:
            return
        st = P.capture_state(self.plugin)
        if st:
            self.slot.state = st
            if self.core is not None:
                self.core.save()
