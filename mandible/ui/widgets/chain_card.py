"""Chain (preset) card."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ...config import Chain
from .base import SpacedLayouts, _follow_look, set_style_property
from .labels import ElidedLabel
from .lamps import PilotLamp


class ChainCardWidget(QFrame):
    """Studio broadcast preset card with pilot lamp and monospace telemetry."""
    def __init__(self, chain: Chain, is_active: bool, parent=None):
        super().__init__(parent)
        self.chain = chain
        self.is_active = is_active
        self.is_selected = False
        self.setObjectName("chainCard")

        self._spaced = SpacedLayouts()
        lay = self._spaced.add(QVBoxLayout(self), spacing=1, margins=(3, 2, 3, 2))

        # Row 1: lamp + name + hotkey badge
        row1 = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        row1.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.lamp = PilotLamp(active=is_active, size=10)
        row1.addWidget(self.lamp)

        # Names keep the case the user typed (as in the header and tray).
        self.name_lbl = ElidedLabel(chain.name, min_chars=6)
        self.name_lbl.setObjectName("chainName")
        row1.addWidget(self.name_lbl, 1)

        self.hk_lbl = None
        if chain.hotkey.is_set():
            self.hk_lbl = QLabel(chain.hotkey.label)
            self.hk_lbl.setObjectName("cardHotkey")
            self.hk_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.hk_lbl.setFixedHeight(18)
            row1.addWidget(self.hk_lbl)
        lay.addLayout(row1)

        # Row 2: info subtitle
        row2 = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        row2.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        # The subtitle starts under the name: an empty column as wide as the lamp.
        row2.addSpacing(self.lamp.width())
        self.sub_lbl = ElidedLabel(min_chars=8)
        self.sub_lbl.setObjectName("chainSub")
        row2.addWidget(self.sub_lbl, 1)

        dw = int(round(getattr(chain, "dry_wet", 1.0) * 100))
        self.dw_lbl = QLabel(f"{dw}% WET")
        self.dw_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.dw_lbl.setObjectName("chainWet")
        row2.addWidget(self.dw_lbl)

        lay.addLayout(row2)
        self.set_active_state(is_active)
        _follow_look(self)

    def _on_look_changed(self):
        self._spaced.apply()

    def set_active_state(self, on: bool):
        self.is_active = on
        self.lamp.set_active(on)
        set_style_property(self, "active", "true" if on else "false")

        n = len(self.chain.plugins)
        plug_txt = f"{n} insert{'s' if n != 1 else ''}"
        status_txt = "Live on mic" if on else "Standby"
        self.sub_lbl.setText(f"{plug_txt} · {status_txt}")

        # The card's own ``active`` property styles the card; the labels carry it too so their
        # rules need no ancestor selectors.
        for w in (self.name_lbl, self.sub_lbl, self.dw_lbl, self.hk_lbl):
            if w is not None:
                set_style_property(w, "active", "true" if on else "false")

    def set_selected_state(self, sel: bool):
        self.is_selected = sel
        set_style_property(self, "selected", "true" if sel else "false")
