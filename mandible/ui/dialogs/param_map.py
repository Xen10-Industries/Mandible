"""Map a plugin's parameters to the hardware macro knobs of a rack module."""
from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem,
                               QMessageBox, QVBoxLayout)

from ... import plugins as P
from ...config import PluginSlot
from ...core import Core, inst
from ...internal_dsp import is_internal_plugin
from ..look import space
from ..widgets.buttons import make_button, tier_button_box


class PluginParamMapDialog(QDialog):
    """
    Studio dialog for mapping VST3 parameters to hardware macro knobs on a PluginRackCard.
    Mappings are persisted per plugin in AppConfig.plugin_param_mappings so adding the
    plugin to any preset in the future automatically loads the user's mapped knobs.
    """
    MAX_KNOBS = 8

    def __init__(self, slot: PluginSlot, core: Core, parent=None):
        super().__init__(parent)
        self.slot = slot
        self.core = core
        self.plugin = inst(slot)
        # Built-in effects are not VST3 plugins; only a real VST3 gets the format name.
        self.kind = "parameters" if is_internal_plugin(slot.path) else "VST3 parameters"
        self.setWindowTitle(f"Knob mapping — {slot.display_name or slot.path}")
        self.resize(680, 480)

        self.usable_params = P.get_usable_parameters(self.plugin) if self.plugin else []
        self.param_by_key = dict(self.usable_params)
        self.selected_keys: list[str] = list(P.resolve_slot_mapped_params(slot, core.cfg))[: self.MAX_KNOBS]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*(space(3),) * 4)
        lay.setSpacing(space(3))

        # Header
        hdr_row = QHBoxLayout()
        title_lbl = QLabel(f"KNOB MAPPING  //  {(slot.display_name or '').upper()}")
        title_lbl.setObjectName("paramMapTitle")
        hdr_row.addWidget(title_lbl, 1)

        self.count_badge = QLabel()
        self.count_badge.setObjectName("paramMapBadge")
        hdr_row.addWidget(self.count_badge)
        lay.addLayout(hdr_row)

        sub_lbl = QLabel(
            f"Select up to {self.MAX_KNOBS} {self.kind} to expose as hardware rotary knobs on this rack module. "
            "This mapping is saved globally for this plugin whenever you insert it into any voice preset."
        )
        sub_lbl.setWordWrap(True)
        sub_lbl.setObjectName("dialogInfo")
        lay.addWidget(sub_lbl)

        # Search filter bar + Quick action buttons
        filter_row = QHBoxLayout()
        filter_row.setSpacing(space(2))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(f"Search {len(self.usable_params)} parameters (e.g. Threshold, Mix, Macro, Gain, Decay)…")
        self.search_edit.textChanged.connect(self._populate_available)
        filter_row.addWidget(self.search_edit, 1)

        smart_btn = make_button("Smart auto-pick")
        smart_btn.setToolTip("Automatically pick up to 6 key studio controls for this plugin")
        smart_btn.setObjectName("paramMapSmartBtn")
        smart_btn.clicked.connect(self._smart_pick)
        filter_row.addWidget(smart_btn)

        clear_btn = make_button("Clear all")
        clear_btn.setToolTip("Unmap all knobs so this plugin displays as a compact 1U module without knobs")
        clear_btn.setObjectName("paramMapClearBtn")
        clear_btn.clicked.connect(self._clear_all)
        filter_row.addWidget(clear_btn)
        lay.addLayout(filter_row)

        # Two-column body: Available Parameters (left) | Mapped Module Knobs (right)
        cols = QHBoxLayout()
        cols.setSpacing(space(3))

        left_box = QGroupBox(f"Available {self.kind} ({len(self.usable_params)})")
        left_lay = QVBoxLayout(left_box)
        self.avail_list = QListWidget()
        self.avail_list.itemChanged.connect(self._on_avail_item_changed)
        left_lay.addWidget(self.avail_list, 1)
        cols.addWidget(left_box, 3)

        right_box = QGroupBox("Mapped module knobs (left to right)")
        right_lay = QVBoxLayout(right_box)
        self.mapped_list = QListWidget()
        right_lay.addWidget(self.mapped_list, 1)

        order_row = QHBoxLayout()
        order_row.setSpacing(space(2))
        btn_up = make_button("Move left", "quiet", icon="chevron_left",
                             tooltip="Move the selected knob one place left")
        btn_dn = make_button("Move right", "quiet", icon="chevron_right",
                             tooltip="Move the selected knob one place right")
        btn_rm = make_button("Remove", "quiet", icon="remove", tooltip="Unmap the selected knob")
        btn_up.clicked.connect(lambda: self._move_mapped(-1))
        btn_dn.clicked.connect(lambda: self._move_mapped(1))
        btn_rm.clicked.connect(self._remove_selected_mapped)
        for b in (btn_up, btn_dn, btn_rm):
            b.setObjectName("paramMapOrderBtn")
            order_row.addWidget(b)
        right_lay.addLayout(order_row)
        cols.addWidget(right_box, 2)

        lay.addLayout(cols, 1)

        # Dialog footer buttons
        bb = tier_button_box(QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel))
        bb.button(QDialogButtonBox.Save).setText("Save mapping")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self._populate_available()
        self._refresh_mapped_list()

    def _populate_available(self):
        query = self.search_edit.text().strip().lower()
        self.avail_list.blockSignals(True)
        self.avail_list.clear()
        for key, param in self.usable_params:
            pname = str(getattr(param, "name", key) or key).strip()
            if query and query not in pname.lower() and query not in key.lower():
                continue
            val_s = P.clean_param_string(param)
            it = QListWidgetItem(f"{pname}   [{val_s}]")
            it.setData(Qt.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if key in self.selected_keys else Qt.Unchecked)
            self.avail_list.addItem(it)
        self.avail_list.blockSignals(False)

    def _refresh_mapped_list(self):
        cur_row = self.mapped_list.currentRow()
        self.mapped_list.clear()
        for idx, key in enumerate(self.selected_keys):
            param = self.param_by_key.get(key)
            pname = str(getattr(param, "name", key) or key).strip() if param else key
            short = P.format_knob_title(pname, max_len=9)
            it = QListWidgetItem(f"KNOB {idx + 1:02d}:  {pname}  ({short})")
            it.setData(Qt.UserRole, key)
            self.mapped_list.addItem(it)
        if 0 <= cur_row < self.mapped_list.count():
            self.mapped_list.setCurrentRow(cur_row)
        self.count_badge.setText(f"MAPPED: {len(self.selected_keys)} / {self.MAX_KNOBS} KNOBS")

    def _on_avail_item_changed(self, item: QListWidgetItem):
        key = item.data(Qt.UserRole)
        if not key:
            return
        if item.checkState() == Qt.Checked:
            if key not in self.selected_keys:
                if len(self.selected_keys) >= self.MAX_KNOBS:
                    self.avail_list.blockSignals(True)
                    item.setCheckState(Qt.Unchecked)
                    self.avail_list.blockSignals(False)
                    QMessageBox.information(
                        self,
                        "Maximum Knobs Reached",
                        f"Up to {self.MAX_KNOBS} parameters can be mapped as hardware knobs on a single module.",
                    )
                    return
                self.selected_keys.append(key)
        else:
            if key in self.selected_keys:
                self.selected_keys.remove(key)
        self._refresh_mapped_list()

    def _move_mapped(self, delta: int):
        r = self.mapped_list.currentRow()
        if 0 <= r < len(self.selected_keys):
            nr = max(0, min(len(self.selected_keys) - 1, r + delta))
            if nr != r:
                self.selected_keys.insert(nr, self.selected_keys.pop(r))
                self._refresh_mapped_list()
                self.mapped_list.setCurrentRow(nr)

    def _remove_selected_mapped(self):
        r = self.mapped_list.currentRow()
        if 0 <= r < len(self.selected_keys):
            self.selected_keys.pop(r)
            self._populate_available()
            self._refresh_mapped_list()

    def _smart_pick(self):
        if self.plugin is not None:
            self.selected_keys = list(P.smart_pick_params(self.plugin, max_knobs=6))
            self._populate_available()
            self._refresh_mapped_list()

    def _clear_all(self):
        self.selected_keys.clear()
        self._populate_available()
        self._refresh_mapped_list()
