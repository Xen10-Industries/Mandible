"""Level meters."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..elements.base import ElementState
from ..look import current_look
from .base import _follow_look, look_color, look_element


def _meter_frac(db: float) -> float:
    """dB -> 0..1 over the meters' -60..+6 dB scale."""
    return max(0.0, min(1.0, (db + 60.0) / 66.0))


class LevelMeter(QWidget):
    """Main channel meter: name, dB readout, the skin's ``meter`` bar and a dB scale."""
    def __init__(self, label: str):
        super().__init__()
        self.label = label
        self.level_db = -90.0
        self.peak_db = -90.0
        self.setMinimumSize(140, 50)
        self.setMaximumHeight(56)
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def push(self, peak_lin: float):
        before = (round(self.level_db, 1), round(self.peak_db, 1))
        db = 20 * math.log10(peak_lin) if peak_lin > 1e-6 else -90.0
        self.level_db = max(db, self.level_db - 1.5)
        self.peak_db = db if db > self.peak_db else max(-90.0, self.peak_db - 0.25)
        if (round(self.level_db, 1), round(self.peak_db, 1)) != before:
            self.update()

    def element(self):
        return look_element("meter", "main")

    def bar_state(self) -> ElementState:
        peak = _meter_frac(self.peak_db) if self.peak_db > -55.0 else None
        return ElementState(value=_meter_frac(self.level_db), peak=peak)

    def paintEvent(self, _):
        look = current_look()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()

        # Header row: channel name and dB readout
        p.setPen(look_color("text.secondary"))
        f = p.font()
        f.setFamily("Segoe UI")
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r.left(), 12, self.label)

        f.setFamily("Consolas")
        f.setBold(False)
        p.setFont(f)
        p.setPen(look_color("readout.text"))
        val_str = f"{self.level_db:+.1f} dB" if self.level_db > -79 else "-INF"
        p.drawText(QRectF(r.left(), 0, r.width(), 14), Qt.AlignRight | Qt.AlignVCenter, val_str)

        seg_y, seg_h = 18, 13
        total_w = float(r.width())
        self.element().paint(p, QRectF(r.left(), seg_y, total_w, seg_h), self.bar_state(), look)

        # Calibrated scale marks below the bar
        p.setPen(look_color("text.disabled"))
        f.setPointSize(7)
        p.setFont(f)
        scale_y = seg_y + seg_h + 3
        ticks = [(-60, "-60"), (-36, "-36"), (-18, "-18"), (-6, "-6"), (0, "0"), (6, "+6")]
        for db, txt in ticks:
            tx = r.left() + _meter_frac(db) * (total_w - 6.0)
            p.drawLine(QPointF(tx + 3.0, scale_y), QPointF(tx + 3.0, scale_y + 2))
            p.drawText(QRectF(tx - 12, scale_y + 2, 24, 10), Qt.AlignHCenter | Qt.AlignTop, txt)
        p.end()


class ThinLevelMeter(QWidget):
    """Compact 8px horizontal level meter for condensed console strip (skin-aware)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setMinimumWidth(80)
        self.level_db = -80.0
        self.peak_db = -80.0
        _follow_look(self)

    def push(self, peak_linear: float):
        before = (round(self.level_db, 1), round(self.peak_db, 1))
        if peak_linear < 1e-4:
            db = -80.0
        else:
            db = 20.0 * math.log10(min(peak_linear, 2.0))
        if db >= self.level_db:
            self.level_db = db
        else:
            self.level_db = max(-80.0, self.level_db - 2.8)

        if db >= self.peak_db:
            self.peak_db = db
        else:
            self.peak_db = max(-80.0, self.peak_db - 0.6)
        if (round(self.level_db, 1), round(self.peak_db, 1)) != before:
            self.update()

    def _on_look_changed(self):
        self.update()

    def element(self):
        return look_element("meter", "thin")

    def bar_state(self) -> ElementState:
        peak = _meter_frac(self.peak_db) if self.peak_db > -55.0 else None
        return ElementState(value=_meter_frac(self.level_db), peak=peak)

    def paintEvent(self, _):
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()), self.bar_state(), current_look())
        p.end()


class PluginPrePostMeter(QWidget):
    """
    Calibrated Pre / Post (IN / OUT) level meter for 1U/2U plugin rack modules (skin-aware).
    Shows real-time signal level entering and leaving an individual VST3 insert slot.
    """
    def __init__(self, enabled: bool = True, parent=None):
        super().__init__(parent)
        self.slot_enabled = bool(enabled)
        self.pre_db = -85.0
        self.post_db = -85.0
        self.pre_peak_db = -85.0
        self.post_peak_db = -85.0
        self.setFixedSize(112, 34)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._update_tooltip()
        _follow_look(self)

    def _update_tooltip(self):
        pre_s = f"{self.pre_db:+.1f} dB" if self.pre_db > -78.0 else "-INF"
        if not self.slot_enabled:
            post_s = "BYPASSED"
        else:
            post_s = f"{self.post_db:+.1f} dB" if self.post_db > -78.0 else "-INF"
        self.setToolTip(f"Plugin Signal Meter  ·  PRE (In): {pre_s}  |  POST (Out): {post_s}")

    def push(self, pre_lin: float, post_lin: float, enabled: bool = True):
        before = (self.slot_enabled, round(self.pre_db, 1), round(self.post_db, 1),
                  round(self.pre_peak_db, 1), round(self.post_peak_db, 1))
        self.slot_enabled = bool(enabled)
        target_pre = 20.0 * math.log10(min(pre_lin, 2.5)) if pre_lin > 1e-4 else -85.0
        target_post = 20.0 * math.log10(min(post_lin, 2.5)) if (enabled and post_lin > 1e-4) else -85.0

        self.pre_db = target_pre if target_pre >= self.pre_db else max(-85.0, self.pre_db - 2.4)
        self.post_db = target_post if target_post >= self.post_db else max(-85.0, self.post_db - 2.4)

        self.pre_peak_db = target_pre if target_pre >= self.pre_peak_db else max(-85.0, self.pre_peak_db - 0.5)
        self.post_peak_db = target_post if target_post >= self.post_peak_db else max(-85.0, self.post_peak_db - 0.5)
        after = (self.slot_enabled, round(self.pre_db, 1), round(self.post_db, 1),
                 round(self.pre_peak_db, 1), round(self.post_peak_db, 1))
        if after != before:
            self.update()

    def _on_look_changed(self):
        self.update()

    def element(self):
        return look_element("meter", "prepost")

    def row_states(self) -> list[tuple[str, ElementState]]:
        """PRE and POST bar states; a bypassed slot's POST row is inactive (unlit)."""
        rows = []
        for lbl, lvl_db, pk_db, active in (("PRE", self.pre_db, self.pre_peak_db, True),
                                           ("POST", self.post_db, self.post_peak_db, self.slot_enabled)):
            peak = _meter_frac(pk_db) if pk_db > -56.0 else None
            rows.append((lbl, ElementState(enabled=active, value=_meter_frac(lvl_db), peak=peak)))
        return rows

    def paintEvent(self, _):
        look = current_look()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())

        # Recessed bezel housing, darker than the bar tracks so empty rows stay visible
        bw = float(look.skin.shape.get("border.width", 1))
        radius = min(4.0, float(look.skin.shape.get("radius.control", 4)))
        p.setPen(QPen(look_color("line.subtle"), bw))
        p.setBrush(look_color("bg.inset").darker(150))
        p.drawRoundedRect(QRectF(bw / 2.0, bw / 2.0, w - bw, h - bw), radius, radius)

        f = p.font()
        f.setFamily("Consolas")
        f.setPointSize(6)
        f.setBold(True)
        p.setFont(f)

        label_w = 26.0
        bar_x = label_w + 3.0
        bar_w = w - bar_x - 5.0
        row_h = 9.0
        meter = self.element()
        bar_h = min(row_h, float(meter.size_hint(look).height()))
        for (lbl, state), ry in zip(self.row_states(), (5.0, 19.0)):
            p.setPen(look_color("text.secondary" if state.enabled else "text.disabled"))
            p.drawText(QRectF(4.0, ry - 0.5, label_w, row_h + 1.0), Qt.AlignLeft | Qt.AlignVCenter, lbl)
            meter.paint(p, QRectF(bar_x, ry + (row_h - bar_h) / 2.0, bar_w, bar_h), state, look)
        p.end()
