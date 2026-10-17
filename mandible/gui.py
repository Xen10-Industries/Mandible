"""PySide6 user interface for Mandible."""
from __future__ import annotations

import copy
import math
import os
import re
import sys
import threading
import time
from functools import lru_cache, partial

import numpy as np
from PySide6.QtCore import QLockFile, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QLinearGradient,
                            QPainter, QPainterPath, QPalette, QPen, QRadialGradient)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QProgressDialog, QPushButton, QSlider, QSpinBox,
                               QStackedWidget, QSystemTrayIcon, QTabWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import devices as D
from . import plugins as P
from . import branding
from .audio_engine import DRY_ID
from .config import (APP_DIR, Chain, Hotkey, MidiBinding, PluginSlot,
                     SoundboardClipConfig, is_startup_enabled, load_config, set_startup_enabled)
from .core import Core, inst, slot_error
from .midi import list_midi_inputs
from .setup_assistant import SetupAssistantDialog
from .waveform_widget import SoundboardWaveformWidget
from .factory_presets import get_factory_presets, instantiate_factory_preset
from .ui.elements import registry as _registry
from .ui.elements.base import ElementState, metal, mix
from .ui.look import (BUILTIN_PALETTES, BUILTIN_SKINS, Look, current_look, look_bus, look_for,
                      look_from_config, set_look)


# =============================================================== look: palette + skin
# Colours come from ``current_look().palette`` and skin-dependent drawing from the element
# registry (``mandible.ui.elements``); widgets repaint on ``look_bus().lookChanged``.

@lru_cache(maxsize=16)
def _resolved_elements(look: Look) -> dict[str, str]:
    return _registry.resolve(look.skin.elements)[0]


def look_element(slot: str, preset: str | None = None, **ctor):
    """The current skin's element for ``slot``: ``cls.<preset>()`` or ``cls(**ctor)``."""
    cls = _registry.get(slot, _resolved_elements(current_look())[slot])
    return getattr(cls, preset)() if preset else cls(**ctor)


def look_color(token: str) -> QColor:
    """A palette token of the current look as a QColor."""
    return QColor(current_look().palette.color(token))


def _follow_look(widget: QWidget) -> None:
    """Call ``widget._on_look_changed`` (default: repaint) whenever the look changes.

    The connection goes away with the widget (the slot is a method of the QObject).
    """
    look_bus().lookChanged.connect(widget._on_look_changed)


def _qpalette(look: Look) -> QPalette:
    c = look.palette.color
    pal = QPalette()
    for role, token in ((QPalette.Window, "bg.window"), (QPalette.WindowText, "text.primary"),
                        (QPalette.Base, "bg.inset"), (QPalette.AlternateBase, "bg.panel"),
                        (QPalette.Text, "text.primary"), (QPalette.Button, "bg.panel"),
                        (QPalette.ButtonText, "text.primary"), (QPalette.Highlight, "accent"),
                        (QPalette.HighlightedText, "text.on_accent"),
                        (QPalette.ToolTipBase, "bg.raised"), (QPalette.ToolTipText, "text.primary"),
                        (QPalette.PlaceholderText, "text.disabled")):
        pal.setColor(role, QColor(c(token)))
    return pal


_palette_synced_apps: set[int] = set()


def apply_theme(app: QApplication, look: Look | None = None) -> None:
    """Fusion style and the app icon, then ``set_look`` (stylesheet once + ``lookChanged``).

    The application QPalette follows every later look change too (``core.set_theme`` etc.).
    """
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    if id(app) not in _palette_synced_apps:
        _palette_synced_apps.add(id(app))
        look_bus().lookChanged.connect(lambda: app.setPalette(_qpalette(current_look())))
    app.setWindowIcon(branding.app_icon())
    set_look(look or current_look(), app)


class ChassisWrapperFrame(QFrame):
    """Full-window outer chassis; the skin's ``frame`` element paints it and sets the margins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rackChassis")
        _follow_look(self)

    def element(self):
        return look_element("frame")

    def update_frame_margins(self):
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(*self.element().content_margins(current_look()))

    def _on_look_changed(self):
        self.update_frame_margins()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()), ElementState(), current_look())
        p.end()

# =============================================================== small widgets
class RackScrew(QWidget):
    """Hardware rack screw: the skin's ``screws`` element (nothing in the minimal skin)."""
    def __init__(self, size=14, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def element(self):
        return look_element("screws")

    def paintEvent(self, _):
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()), ElementState(), current_look())
        p.end()


class PilotLamp(QWidget):
    """Faceted pilot lamp / jewel indicator; a plain dot in skins without depth."""
    def __init__(self, active=True, token="status.ok", size=18, parent=None):
        super().__init__(parent)
        self.active = active
        self.token = token
        self.setFixedSize(size, size)
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def set_active(self, on: bool):
        if self.active != on:
            self.active = on
            self.update()

    def paintEvent(self, _):
        look = current_look()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect().adjusted(1, 1, -1, -1))
        jr = r.adjusted(2.5, 2.5, -2.5, -2.5)
        on = look_color(self.token)

        if look.skin.shape.get("shadow.depth", 1) == 0:
            p.setPen(Qt.NoPen)
            p.setBrush(on if self.active else look_color("line.subtle"))
            p.drawEllipse(jr)
            p.end()
            return

        # Chrome bezel ring
        m = metal(look)
        bg = QLinearGradient(0, 0, r.width(), r.height())
        bg.setColorAt(0.0, mix(m.hi, m.light, 0.5))
        bg.setColorAt(0.5, mix(m.dark, m.mid, 0.5))
        bg.setColorAt(1.0, m.mid)
        p.setPen(QPen(m.black, 1))
        p.setBrush(QBrush(bg))
        p.drawEllipse(r)

        # Glass jewel
        if self.active:
            jg = QRadialGradient(jr.center(), jr.width() / 2)
            jg.setColorAt(0.0, m.hi)
            jg.setColorAt(0.35, on)
            jg.setColorAt(1.0, on.darker(180))
            p.setBrush(QBrush(jg))
            p.setPen(QPen(on.lighter(140), 1))
        else:
            p.setBrush(look_color("bg.raised"))
            p.setPen(QPen(look_color("line.subtle"), 1))
        p.drawEllipse(jr)
        p.end()


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


def parse_audio_value(text: str, default: float, min_val: float, max_val: float) -> float:
    """Parses a numeric value from text input, handling dB, %, s, +/-, and -inf."""
    text = text.strip().lower()
    if not text:
        return default
    if "inf" in text:
        return min_val
    m = re.search(r"[-+]?(?:\d*\.?\d+|\d+)", text)
    if m:
        try:
            val = float(m.group(0))
            return max(min_val, min(max_val, val))
        except ValueError:
            pass
    return default


class InlineValueEdit(QLineEdit):
    """Sleek studio inline value editor with Enter-commit and Escape-cancel."""
    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "background-color: #0b0e14; border: 1.5px solid #38bdf8; border-radius: 3px; "
            "color: #f8fafc; font-family: Consolas, monospace; font-size: 8pt; font-weight: bold; "
            "padding: 0px 2px; selection-background-color: #0284c7;"
        )
        self._committing = False

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.cancelled.emit()
            ev.accept()
            return
        elif ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if self.isVisible() and not self._committing:
            self._commit()

    def _commit(self):
        if self._committing or not self.isVisible():
            return
        self._committing = True
        try:
            self.committed.emit(self.text())
        finally:
            self._committing = False


class GainSlider(QWidget):
    changed = Signal(float)

    def __init__(self, label: str, value_db: float):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 8.5pt; color: #94a3b8;")
        lay.addWidget(lbl)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(-600, 240)  # tenths of dB
        self.slider.setValue(int(round(value_db * 10)))
        self.slider.setMinimumWidth(90)
        self.slider.setToolTip("Drag or scroll to adjust · Double-click to reset (0.0 dB)")
        self.slider.mouseDoubleClickEvent = lambda e: self.slider.setValue(0)
        lay.addWidget(self.slider, 1)

        self.val_stack = QStackedWidget()
        self.val_stack.setMinimumWidth(62)
        self.val_stack.setFixedHeight(22)

        self.val = QLabel()
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.val.setStyleSheet("font-family: Consolas, monospace; font-size: 8.5pt; color: #cbd5e1;")
        self.val.setCursor(Qt.IBeamCursor)
        self.val.setToolTip("Double-click to type custom value")
        self.val.mouseDoubleClickEvent = self._start_val_edit

        self.val_edit = InlineValueEdit()
        self.val_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.val_edit.setStyleSheet(
            "background-color: #0b0e14; border: 1.5px solid #38bdf8; border-radius: 3px; "
            "color: #f8fafc; font-family: Consolas, monospace; font-size: 8.5pt; font-weight: bold; "
            "padding: 0px 3px; selection-background-color: #0284c7;"
        )
        self.val_edit.committed.connect(self._commit_val_edit)
        self.val_edit.cancelled.connect(lambda: self.val_stack.setCurrentIndex(0))

        self.val_stack.addWidget(self.val)
        self.val_stack.addWidget(self.val_edit)
        self.val_stack.setCurrentIndex(0)
        lay.addWidget(self.val_stack)

        self.slider.valueChanged.connect(self._on)
        self._on(self.slider.value(), emit=False)

    def _start_val_edit(self, ev=None):
        cur_v = self.slider.value() / 10.0
        self.val_edit.setText(f"{cur_v:+.1f}")
        self.val_stack.setCurrentIndex(1)
        self.val_edit.selectAll()
        self.val_edit.setFocus()

    def _commit_val_edit(self, txt: str):
        if self.val_stack.currentIndex() != 1:
            return
        self.val_stack.setCurrentIndex(0)
        cur_v = self.slider.value() / 10.0
        new_v = parse_audio_value(txt, default=cur_v, min_val=-60.0, max_val=24.0)
        self.slider.setValue(int(round(new_v * 10)))

    def _on(self, v, emit=True):
        self.val.setText(f"{v / 10:+.1f} dB")
        if emit:
            self.changed.emit(v / 10)

    def set_value_quiet(self, value_db: float):
        v = max(-600, min(240, int(round(value_db * 10))))
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.val.setText(f"{v / 10:+.1f} dB")


class ChannelStripCard(QFrame):
    """Studio Console Channel Strip containing meter + gain slider."""
    def __init__(self, title: str, dot_color: str, meter: LevelMeter, slider: GainSlider, parent=None):
        super().__init__(parent)
        self.setObjectName("channelStripCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background: {dot_color}; border-radius: 4px;")
        head.addWidget(dot)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("font-weight: bold; font-size: 8pt; color: #94a3b8; letter-spacing: 0.5px;")
        head.addWidget(t_lbl, 1)
        lay.addLayout(head)

        lay.addWidget(meter)
        lay.addWidget(slider)


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


class HardwareKnob(QWidget):
    """Milled aluminum studio rotary knob with graduation arc, pointer notch, drag controls,
    and inline custom value editing on double-click."""
    valueChanged = Signal(float)

    def __init__(self, title: str, min_val: float, max_val: float, default_val: float = 0.0,
                 suffix: str = "", decimals: int = 1, parent=None):
        super().__init__(parent)
        self.title = title
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.default_val = float(default_val)
        self.val = float(default_val)
        self.suffix = suffix
        self.decimals = decimals

        self.setFixedSize(54, 62)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._dragging = False
        self._drag_y = 0.0
        self._drag_val = self.val
        self._update_tooltip()

        # Inline value editor for typing custom values
        self.edit = InlineValueEdit(self)
        self.edit.setGeometry(1, 43, 52, 18)
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.hide()
        self.edit.committed.connect(self._commit_edit)
        self.edit.cancelled.connect(self._cancel_edit)
        _follow_look(self)

    def _update_tooltip(self, over_value: bool = False):
        if over_value:
            self.setToolTip(f"{self.title}: {self.val_str()} (Double-click to type custom value)")
        else:
            self.setToolTip(f"{self.title}: {self.val_str()} (Drag up/down, scroll, or double-click to reset)")

    def value(self) -> float:
        return self.val

    def setValue(self, v: float, emit: bool = True):
        clamped = max(self.min_val, min(self.max_val, float(v)))
        if clamped != self.val:
            self.val = clamped
            self._update_tooltip()
            self.update()
            if emit:
                self.valueChanged.emit(self.val)

    def val_str(self) -> str:
        if self.decimals == 0:
            return f"{int(round(self.val))}{self.suffix}"
        if "+" in self.suffix or "dB" in self.suffix:
            return f"{self.val:+.{self.decimals}f}{self.suffix}"
        return f"{self.val:.{self.decimals}f}{self.suffix}"

    def mousePressEvent(self, ev):
        if self.edit.isVisible():
            self._commit_edit(self.edit.text())
        if ev.button() == Qt.LeftButton:
            pos_y = ev.position().y() if hasattr(ev, "position") else ev.pos().y()
            if pos_y < 42:
                self._dragging = True
                pos = ev.globalPosition() if hasattr(ev, "globalPosition") else ev.globalPos()
                self._drag_y = float(pos.y())
                self._drag_val = self.val

    def mouseMoveEvent(self, ev):
        if self._dragging:
            pos = ev.globalPosition() if hasattr(ev, "globalPosition") else ev.globalPos()
            dy = self._drag_y - float(pos.y())
            span = self.max_val - self.min_val
            new_val = self._drag_val + (dy / 140.0) * span
            self.setValue(new_val)
        else:
            pos_y = ev.position().y() if hasattr(ev, "position") else ev.pos().y()
            if pos_y >= 42 and not self.edit.isVisible():
                self.setCursor(Qt.IBeamCursor)
                self._update_tooltip(over_value=True)
            else:
                self.setCursor(Qt.PointingHandCursor)
                self._update_tooltip(over_value=False)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = False

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        step = (self.max_val - self.min_val) / 60.0
        self.setValue(self.val + (1.0 if delta > 0 else -1.0) * step)

    def mouseDoubleClickEvent(self, ev):
        pos_y = ev.position().y() if hasattr(ev, "position") else ev.pos().y()
        if pos_y >= 42:
            self._start_edit()
        else:
            self.setValue(self.default_val)

    def _start_edit(self):
        if self.decimals == 0:
            txt = f"{int(round(self.val))}"
        else:
            txt = f"{self.val:.{self.decimals}f}"
        self.edit.setText(txt)
        self.edit.show()
        self.edit.selectAll()
        self.edit.setFocus()
        self.update()

    def _commit_edit(self, txt: str):
        self.edit.hide()
        new_v = parse_audio_value(txt, default=self.val, min_val=self.min_val, max_val=self.max_val)
        self.setValue(new_v)
        self.update()

    def _cancel_edit(self):
        self.edit.hide()
        self.update()

    def _on_look_changed(self):
        self.update()

    def element(self):
        return look_element("knob", compact=False)

    def paintEvent(self, _):
        frac = (self.val - self.min_val) / max(1e-5, (self.max_val - self.min_val))
        state = ElementState(value=frac, label=self.title,
                             readout="" if self.edit.isVisible() else self.val_str())
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()), state, current_look())
        p.end()


class RackToolButton(QPushButton):
    """Hardware button with custom antialiased vector iconography and balanced borders."""
    def __init__(self, kind: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(26, 26)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0.5, 0.5, w - 1.0, h - 1.0)

        is_hover = self.underMouse()
        is_down = self.isDown()

        if self.kind == "remove":
            danger = look_color("status.danger")
            danger_bg = look_color("status.danger.subtle")
            if is_down:
                bg = mix(danger_bg, danger, 0.3)
            elif is_hover:
                bg = mix(danger_bg, danger, 0.15)
            else:
                bg = danger_bg
            border = danger if is_hover else mix(danger_bg, danger, 0.45)
            icon_color = look_color("text.primary") if is_hover else danger
        else:
            if is_down:
                bg = look_color("bg.window")
            elif is_hover:
                bg = look_color("bg.raised")
            else:
                bg = look_color("bg.panel")
            border = look_color("line.strong" if is_hover else "line.subtle")
            icon_color = (look_color("text.primary") if is_hover
                          else mix(look_color("text.secondary"), look_color("text.primary"), 0.5))

        p.setPen(QPen(border, 1.0))
        p.setBrush(bg)
        radius = min(4.0, float(current_look().skin.shape.get("radius.control", 4)))
        p.drawRoundedRect(r, radius, radius)

        cx, cy = w / 2.0, h / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(icon_color)

        if self.kind == "up":
            path = QPainterPath()
            path.moveTo(cx, cy - 3.2)
            path.lineTo(cx - 4.5, cy + 2.5)
            path.lineTo(cx + 4.5, cy + 2.5)
            path.closeSubpath()
            p.drawPath(path)
        elif self.kind == "down":
            path = QPainterPath()
            path.moveTo(cx, cy + 3.2)
            path.lineTo(cx - 4.5, cy - 2.5)
            path.lineTo(cx + 4.5, cy - 2.5)
            path.closeSubpath()
            p.drawPath(path)
        elif self.kind == "remove":
            pen = QPen(icon_color, 1.6, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            d = 3.6
            p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
            p.drawLine(QPointF(cx + d, cy - d), QPointF(cx - d, cy + d))
        elif self.kind == "plus":
            pen = QPen(icon_color, 1.6, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            d = 4.0
            p.drawLine(QPointF(cx - d, cy), QPointF(cx + d, cy))
            p.drawLine(QPointF(cx, cy - d), QPointF(cx, cy + d))

        p.end()


class ChainCardWidget(QFrame):
    """Studio broadcast preset card with pilot lamp and monospace telemetry."""
    def __init__(self, chain: Chain, is_active: bool, parent=None):
        super().__init__(parent)
        self.chain = chain
        self.is_active = is_active
        self.is_selected = False
        self.setObjectName("chainCard")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(7)

        # Row 1: lamp + name + hotkey badge
        row1 = QHBoxLayout()
        row1.setSpacing(7)
        row1.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.lamp = PilotLamp(active=is_active, size=10)
        row1.addWidget(self.lamp)

        self.name_lbl = QLabel(chain.name.upper())
        f = self.name_lbl.font()
        f.setBold(True)
        f.setPointSize(8.5)
        self.name_lbl.setFont(f)
        row1.addWidget(self.name_lbl, 1)

        self.hk_lbl = None
        if chain.hotkey.is_set():
            self.hk_lbl = QLabel(chain.hotkey.label.upper())
            self.hk_lbl.setObjectName("cardHotkey")
            self.hk_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.hk_lbl.setFixedHeight(18)
            row1.addWidget(self.hk_lbl)
        lay.addLayout(row1)

        # Row 2: info subtitle
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.sub_lbl = QLabel()
        row2.addWidget(self.sub_lbl, 1)

        dw = int(round(getattr(chain, "dry_wet", 1.0) * 100))
        self.dw_lbl = QLabel(f"{dw}% WET")
        self.dw_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.dw_lbl.setFixedHeight(14)
        self.dw_lbl.setStyleSheet("font-size: 7.5pt; font-weight: bold; font-family: Consolas, monospace; margin: 0px; padding: 0px;")
        row2.addWidget(self.dw_lbl)

        lay.addLayout(row2)
        self.set_active_state(is_active)

    def set_active_state(self, on: bool):
        self.is_active = on
        self.lamp.set_active(on)
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

        n = len(self.chain.plugins)
        plug_txt = f"{n} Insert{'s' if n != 1 else ''}"
        status_txt = "LIVE ON MIC" if on else "STANDBY"
        self.sub_lbl.setText(f"{plug_txt} · {status_txt}")

        if on:
            self.name_lbl.setStyleSheet("color: #ffffff; font-weight: 800;")
            self.sub_lbl.setStyleSheet("color: #10b981; font-weight: bold; font-size: 7.5pt; padding-left: 17px;")
            self.dw_lbl.setStyleSheet("color: #34d399; font-size: 7.5pt; font-weight: bold; font-family: Consolas, monospace; margin: 0px; padding: 0px;")
            if self.hk_lbl:
                self.hk_lbl.setStyleSheet("background-color: #0b1712; border: 1px solid #10b981; color: #6ee7b7; font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; border-radius: 4px; padding: 0px 6px;")
        else:
            self.name_lbl.setStyleSheet("color: #cbd5e1; font-weight: bold;")
            self.sub_lbl.setStyleSheet("color: #64748b; font-size: 7.5pt; padding-left: 17px;")
            self.dw_lbl.setStyleSheet("color: #94a3b8; font-size: 7.5pt; font-weight: bold; font-family: Consolas, monospace; margin: 0px; padding: 0px;")
            if self.hk_lbl:
                self.hk_lbl.setStyleSheet("background-color: #0b0e14; border: 1px solid #262e3d; color: #94a3b8; font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; border-radius: 4px; padding: 0px 6px;")

    def set_selected_state(self, sel: bool):
        self.is_selected = sel
        self.setProperty("selected", "true" if sel else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class HardwareSwitch(QWidget):
    """Two-state hardware switch; the skin's ``switch`` element paints it (bat toggle,
    rocker or pill). ``compact`` and ``vertical`` pick the smaller widget variants."""
    toggled = Signal(bool)

    def __init__(self, active: bool = True, compact: bool = False, vertical: bool = False, parent=None):
        super().__init__(parent)
        self.active = bool(active)
        self.compact = compact
        self.vertical = vertical
        if self.vertical:
            self.setFixedSize(46, 28)
        elif self.compact:
            self.setFixedSize(50, 24)
        else:
            self.setFixedSize(68, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to toggle ON / BYPASS")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        _follow_look(self)

    def _on_look_changed(self):
        self.update()

    def element(self):
        return look_element("switch", compact=self.compact, vertical=self.vertical)

    def set_active(self, on: bool):
        if self.active != bool(on):
            self.active = bool(on)
            self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.active = not self.active
            self.update()
            self.toggled.emit(self.active)
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def paintEvent(self, _):
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()),
                             ElementState(active=self.active), current_look())
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


class PluginParamKnob(QWidget):
    """
    Hardware rotary macro knob bound directly to a VST3 AudioProcessorParameter.
    Operates in the VST3's native normalized [0.0, 1.0] taper while displaying the
    VST3's own formatted string_value (e.g. '-28.7 dB', '16.2 ms', '2.6:1', '47 %').
    Supports drag, scroll, double-click dial to reset, and double-click value to type.
    """
    paramEdited = Signal()

    def __init__(self, slot: PluginSlot, param_key: str, core: Core, parent=None):
        super().__init__(parent)
        self.slot = slot
        self.param_key = param_key
        self.core = core
        self.plugin = inst(slot)
        params = P.get_plugin_params_dict(self.plugin)
        self.param = params.get(param_key)

        raw_name = getattr(self.param, "name", param_key) if self.param is not None else param_key
        self.full_name = str(raw_name or param_key).strip()
        self.title = P.format_knob_title(self.full_name, max_len=9)

        defaults = getattr(self.plugin, "_factory_defaults", None) or {}
        cur_raw = float(getattr(self.param, "raw_value", 0.5)) if self.param is not None else 0.5
        self.default_raw = float(defaults.get(param_key, cur_raw))
        self.raw_val = max(0.0, min(1.0, cur_raw))

        self.setFixedSize(64, 58)
        _follow_look(self)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._dragging = False
        self._drag_y = 0.0
        self._drag_raw = self.raw_val

        # Inline value editor for typing custom values on double-click
        self.edit = InlineValueEdit(self)
        self.edit.setGeometry(2, 41, 60, 16)
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.hide()
        self.edit.committed.connect(self._commit_edit)
        self.edit.cancelled.connect(self._cancel_edit)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._persist_plugin_state)

        self._update_tooltip()

    def val_str(self) -> str:
        if self.param is None:
            return f"{self.raw_val * 100:.0f}%"
        s = P.clean_param_string(self.param)
        if len(s) > 10:
            s = s[:10]
        return s

    def _update_tooltip(self, over_value: bool = False):
        ro = P.clean_param_string(self.param) if self.param is not None else f"{self.raw_val * 100:.0f}%"
        if over_value:
            self.setToolTip(f"{self.full_name}: {ro} (Double-click to type custom value)")
        else:
            self.setToolTip(f"{self.full_name}: {ro} (Drag up/down, scroll, or double-click dial to reset)")

    def sync_from_plugin(self):
        if self._dragging or self.edit.isVisible() or self.param is None:
            return
        try:
            cur = max(0.0, min(1.0, float(self.param.raw_value)))
            if abs(cur - self.raw_val) > 1e-4:
                self.raw_val = cur
                self._update_tooltip()
                self.update()
        except Exception:
            pass

    def _set_raw(self, new_raw: float, persist_now: bool = False):
        clamped = max(0.0, min(1.0, float(new_raw)))
        self.raw_val = clamped
        if self.param is not None:
            try:
                self.param.raw_value = clamped
            except Exception:
                pass
        self._update_tooltip()
        self.update()
        if persist_now:
            self._persist_plugin_state()
        else:
            self._save_timer.start(300)

    def _persist_plugin_state(self):
        self._save_timer.stop()
        if self.plugin is not None:
            st = P.capture_state(self.plugin)
            if st:
                self.slot.state = st
                self.core.save()
        self.paramEdited.emit()

    def mousePressEvent(self, ev):
        if self.edit.isVisible():
            self._commit_edit(self.edit.text())
        if ev.button() == Qt.LeftButton:
            pos_y = ev.position().y() if hasattr(ev, "position") else ev.pos().y()
            if pos_y < 40:
                self._dragging = True
                pos = ev.globalPosition() if hasattr(ev, "globalPosition") else ev.globalPos()
                self._drag_y = float(pos.y())
                self._drag_raw = self.raw_val
                ev.accept()

    def mouseMoveEvent(self, ev):
        if self._dragging:
            pos = ev.globalPosition() if hasattr(ev, "globalPosition") else ev.globalPos()
            dy = self._drag_y - float(pos.y())
            self._set_raw(self._drag_raw + (dy / 140.0), persist_now=False)
            ev.accept()
        else:
            pos_y = ev.position().y() if hasattr(ev, "position") else ev.pos().y()
            if pos_y >= 40 and not self.edit.isVisible():
                self.setCursor(Qt.IBeamCursor)
                self._update_tooltip(over_value=True)
            else:
                self.setCursor(Qt.PointingHandCursor)
                self._update_tooltip(over_value=False)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._persist_plugin_state()
            ev.accept()

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        step = 1.0 / 60.0
        self._set_raw(self.raw_val + (1.0 if delta > 0 else -1.0) * step, persist_now=False)
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        pos_y = ev.position().y() if hasattr(ev, "position") else ev.pos().y()
        if pos_y >= 40:
            self._start_edit()
        else:
            self._set_raw(self.default_raw, persist_now=True)
        ev.accept()

    def _start_edit(self):
        cur_txt = P.clean_param_string(self.param) if self.param is not None else f"{self.raw_val * 100:.0f}"
        self.edit.setText(cur_txt)
        self.edit.show()
        self.edit.selectAll()
        self.edit.setFocus()
        self.update()

    def _commit_edit(self, txt: str):
        self.edit.hide()
        if self.param is not None and txt.strip():
            if P.set_param_from_text(self.param, txt):
                try:
                    self.raw_val = max(0.0, min(1.0, float(self.param.raw_value)))
                except Exception:
                    pass
                self._persist_plugin_state()
        self._update_tooltip()
        self.update()

    def _cancel_edit(self):
        self.edit.hide()
        self.update()

    def _on_look_changed(self):
        self.update()

    def element(self):
        return look_element("knob", compact=True)

    def paintEvent(self, _):
        state = ElementState(value=self.raw_val, label=self.title,
                             readout="" if self.edit.isVisible() else self.val_str())
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()), state, current_look())
        p.end()


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
        self.setWindowTitle(f"Map VST Parameters — {slot.display_name or slot.path}")
        self.resize(680, 480)

        self.usable_params = P.get_usable_parameters(self.plugin) if self.plugin else []
        self.param_by_key = dict(self.usable_params)
        self.selected_keys: list[str] = list(P.resolve_slot_mapped_params(slot, core.cfg))[: self.MAX_KNOBS]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        # Header
        hdr_row = QHBoxLayout()
        title_lbl = QLabel(f"VST MACRO KNOB MAPPING  //  {(slot.display_name or '').upper()}")
        title_lbl.setStyleSheet("font-weight: 800; font-size: 9.5pt; color: #f8fafc; letter-spacing: 0.6px;")
        hdr_row.addWidget(title_lbl, 1)

        self.count_badge = QLabel()
        self.count_badge.setStyleSheet(
            "background: #0c1928; border: 1px solid #0284c7; border-radius: 4px; "
            "color: #38bdf8; font-family: Consolas, monospace; font-size: 8pt; font-weight: bold; padding: 2px 8px;"
        )
        hdr_row.addWidget(self.count_badge)
        lay.addLayout(hdr_row)

        sub_lbl = QLabel(
            f"Select up to {self.MAX_KNOBS} VST parameters to expose as hardware rotary knobs on this rack module. "
            "This mapping is saved globally for this plugin whenever you insert it into any voice preset."
        )
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet("color: #94a3b8; font-size: 8.5pt;")
        lay.addWidget(sub_lbl)

        # Search filter bar + Quick action buttons
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(f"Search {len(self.usable_params)} parameters (e.g. Threshold, Mix, Macro, Gain, Decay)…")
        self.search_edit.textChanged.connect(self._populate_available)
        filter_row.addWidget(self.search_edit, 1)

        smart_btn = QPushButton("SMART AUTO-PICK")
        smart_btn.setToolTip("Automatically pick up to 6 key studio controls for this plugin")
        smart_btn.setStyleSheet(
            "background: #0f2922; border: 1px solid #10b981; color: #6ee7b7; "
            "font-weight: bold; font-size: 7.5pt; padding: 5px 10px; border-radius: 4px;"
        )
        smart_btn.clicked.connect(self._smart_pick)
        filter_row.addWidget(smart_btn)

        clear_btn = QPushButton("CLEAR ALL")
        clear_btn.setToolTip("Unmap all knobs so this plugin displays as a compact 1U module without knobs")
        clear_btn.setStyleSheet(
            "background: #1a1d28; border: 1px solid #334155; color: #cbd5e1; "
            "font-weight: bold; font-size: 7.5pt; padding: 5px 10px; border-radius: 4px;"
        )
        clear_btn.clicked.connect(self._clear_all)
        filter_row.addWidget(clear_btn)
        lay.addLayout(filter_row)

        # Two-column body: Available Parameters (left) | Mapped Module Knobs (right)
        cols = QHBoxLayout()
        cols.setSpacing(12)

        left_box = QGroupBox(f"AVAILABLE VST PARAMETERS ({len(self.usable_params)})")
        left_lay = QVBoxLayout(left_box)
        self.avail_list = QListWidget()
        self.avail_list.itemChanged.connect(self._on_avail_item_changed)
        left_lay.addWidget(self.avail_list, 1)
        cols.addWidget(left_box, 3)

        right_box = QGroupBox("MAPPED MODULE KNOBS (LEFT → RIGHT)")
        right_lay = QVBoxLayout(right_box)
        self.mapped_list = QListWidget()
        right_lay.addWidget(self.mapped_list, 1)

        order_row = QHBoxLayout()
        order_row.setSpacing(6)
        btn_up = QPushButton("▲ MOVE LEFT")
        btn_dn = QPushButton("▼ MOVE RIGHT")
        btn_rm = QPushButton("REMOVE")
        btn_up.clicked.connect(lambda: self._move_mapped(-1))
        btn_dn.clicked.connect(lambda: self._move_mapped(1))
        btn_rm.clicked.connect(self._remove_selected_mapped)
        for b in (btn_up, btn_dn, btn_rm):
            b.setStyleSheet("font-size: 7.5pt; font-weight: bold; padding: 4px 8px;")
            order_row.addWidget(b)
        right_lay.addLayout(order_row)
        cols.addWidget(right_box, 2)

        lay.addLayout(cols, 1)

        # Dialog footer buttons
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("SAVE MAPPING")
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
        slot_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 10.5pt; font-weight: bold; color: #64748b;")
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
        fmt_badge.setStyleSheet("background: #111e38; border: 1px solid #1d4ed8; border-radius: 3px; font-size: 7.5pt; padding: 1px 5px; color: #93c5fd; font-weight: bold;")
        name_row.addWidget(fmt_badge)

        # Keep-Awake Badge (Serum 2 / persistent silence pump)
        is_serum = "serum" in (slot.display_name or slot.path).lower()
        if is_serum or getattr(core.cfg, "keep_chains_awake", False):
            awake_badge = QLabel("KEEP-AWAKE ACTIVE")
            awake_badge.setStyleSheet("background: #052e20; border: 1px solid #059669; border-radius: 3px; font-size: 7.5pt; padding: 1px 5px; color: #6ee7b7; font-weight: bold;")
            name_row.addWidget(awake_badge)

        if err:
            err_lbl = QLabel(f"ERROR: {err}")
            err_lbl.setStyleSheet("color: #ef4444; font-size: 8pt; font-weight: bold;")
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
        lat_chip.setStyleSheet("color: #64748b; font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold;")
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
            col_btn.setObjectName("rackHotkeyBtn")
            col_btn.setToolTip(
                "Expand VST macro knobs (2U view)"
                if is_collapsed
                else "Collapse VST macro knobs to compact 1U display"
            )
            col_btn.setStyleSheet(
                "background: #141923; border: 1px solid #334155; color: #cbd5e1; "
                "font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; "
                "padding: 3px 7px; border-radius: 4px;"
            )
            col_btn.clicked.connect(self._toggle_macros_collapsed)
            btn_row.addWidget(col_btn)

        map_txt = f"MAP ({len(mapped_keys)})" if mapped_keys else "MAP"
        self.map_btn = QPushButton(map_txt)
        self.map_btn.setObjectName("rackHotkeyBtn")
        if mapped_keys:
            self.map_btn.setStyleSheet(
                "background: #0c1928; border: 1px solid #0284c7; color: #38bdf8; "
                "font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; "
                "padding: 3px 7px; border-radius: 4px;"
            )
        else:
            self.map_btn.setStyleSheet(
                "background: #131620; border: 1px solid #2d3748; color: #94a3b8; "
                "font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; "
                "padding: 3px 7px; border-radius: 4px;"
            )
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
            bay_lbl.setStyleSheet(
                "font-family: Consolas, monospace; font-size: 6.5pt; font-weight: bold; "
                "color: #475569; letter-spacing: 0.5px; border: none; background: transparent;"
            )
            kb_lay.addWidget(bay_lbl)

            vsep = QFrame()
            vsep.setFrameShape(QFrame.VLine)
            vsep.setStyleSheet("color: #1c2230; background: #1c2230; max-width: 1px;")
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
        lbl.setStyleSheet("color: #64748b; font-size: 7.5pt; font-weight: bold; font-family: Consolas, monospace;")
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
        a.setStyleSheet("color: #475569; font-size: 8.5pt; font-weight: bold;")
        return a

    def refresh(self, target_id: str | None, active_chain_name: str):
        # 1. Update Pre-FX state
        p = self.core.cfg.prefx
        p_on = p.highpass_enabled or p.rnnoise_enabled or p.noise_gate_enabled
        self.prefx_btn.setText(f"RNNOISE: {'ON' if p_on else 'OFF'}")
        self.prefx_btn.setProperty("active", "true" if p_on else "false")
        self.prefx_btn.style().unpolish(self.prefx_btn)
        self.prefx_btn.style().polish(self.prefx_btn)

        # 2. Update Active Chain state
        is_fx = target_id is not None and target_id != DRY_ID
        clean_name = active_chain_name.replace("●", "").strip().upper()
        self.chain_pill.setText(f"PLUGIN RACK: {clean_name}")
        self.chain_pill.setProperty("active", "true" if is_fx else "false")
        self.chain_pill.style().unpolish(self.chain_pill)
        self.chain_pill.style().polish(self.chain_pill)

        # 3. Update Soundboard state
        n_clips = len(self.core.cfg.soundboard)
        self.sb_btn.setText(f"SOUNDBOARD ({n_clips})")

        # 4. Update Limiter state
        l_on = self.core.cfg.limiter.enabled
        self.lim_btn.setText(f"LIMITER: {'ON' if l_on else 'OFF'}")
        self.lim_btn.setProperty("active", "true" if l_on else "false")
        self.lim_btn.style().unpolish(self.lim_btn)
        self.lim_btn.style().polish(self.lim_btn)



# =============================================================== dialogs
class HotkeyDialog(QDialog):
    captured = Signal(object)

    def __init__(self, core: Core, parent=None, title="Set hotkey"):
        super().__init__(parent)
        self.core = core
        self.result_hotkey: Hotkey | None = None
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lbl = QLabel("Press the key combination you want to use…\n\n"
                     "Modifiers (Ctrl / Shift / Alt / Win) are allowed.\nEsc cancels.")
        lbl.setAlignment(Qt.AlignCenter)
        f = lbl.font()
        f.setPointSize(f.pointSize() + 1)
        lbl.setFont(f)
        lay.addWidget(lbl)
        row = QHBoxLayout()
        clear = QPushButton("Remove hotkey")
        cancel = QPushButton("Cancel")
        row.addWidget(clear)
        row.addStretch()
        row.addWidget(cancel)
        lay.addLayout(row)
        clear.clicked.connect(self._clear)
        cancel.clicked.connect(self.reject)
        self.captured.connect(self._got)
        self.setMinimumWidth(340)
        core.hotkeys.capture_next(lambda hk: self.captured.emit(hk))

    def _got(self, hk):
        if hk is None:
            self.reject()
            return
        self.result_hotkey = hk
        self.accept()

    def _clear(self):
        self.result_hotkey = Hotkey()
        self.accept()

    def done(self, r):
        self.core.hotkeys.cancel_capture()
        super().done(r)


class AddPluginDialog(QDialog):
    def __init__(self, extra_dirs, parent=None):
        super().__init__(parent)
        self.extra_dirs = extra_dirs
        self.setWindowTitle("Add VST3 plugin")
        self.resize(520, 560)
        self.path = ""
        lay = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search plugins by name or vendor…")
        self.search.setClearButtonEnabled(True)
        rescan_btn = QPushButton("Rescan")
        rescan_btn.setToolTip("Rescan system folders for newly installed VST3 plugins")
        top_row.addWidget(self.search, 1)
        top_row.addWidget(rescan_btn)
        lay.addLayout(top_row)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        browse = QPushButton("Browse for .vst3…")
        row.addWidget(browse)
        row.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        row.addWidget(bb)
        lay.addLayout(row)

        self._populate(force_rescan=False)
        self.search.textChanged.connect(self._filter)
        self.list.itemDoubleClicked.connect(lambda _: self._ok())
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        browse.clicked.connect(self._browse)
        rescan_btn.clicked.connect(lambda: self._populate(force_rescan=True))
        self.search.setFocus()

    def _populate(self, force_rescan: bool):
        self.list.clear()
        plugins = P.get_cached_plugins(self.extra_dirs, force_rescan=force_rescan)
        # Sort favorites first, then alphabetically
        plugins.sort(key=lambda x: (not x.get("favorite", False), x["name"].lower()))
        for item in plugins:
            vendor = f"  [{item['vendor']}]" if item.get("vendor") else ""
            fav = "[FAV] " if item.get("favorite") else ""
            text = f"{fav}{item['name']}{vendor}"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, item["path"])
            it.setToolTip(f"{item['path']}\nRight-click to toggle Favorite")
            self.list.addItem(it)

    def _filter(self, text):
        t = text.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(t not in it.text().lower())

    def _ok(self):
        it = self.list.currentItem()
        if it is None or it.isHidden():
            return
        self.path = it.data(Qt.UserRole)
        self.accept()

    def _browse(self):
        start = P.default_vst3_dirs()[0] if P.default_vst3_dirs() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Choose VST3 plugin", start, "VST3 plugins (*.vst3)")
        if path:
            self.path = os.path.normpath(path)
            self.accept()


class PreFXDialog(QDialog):
    """Microphone Pre-processing: High-pass rumble filter, RNNoise AI, and Noise Gate."""
    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.cfg = copy.copy(core.cfg.prefx)
        self.setWindowTitle("Microphone Clean-up (Pre-FX)")
        self.resize(460, 380)
        lay = QVBoxLayout(self)

        # Highpass
        hp_box = QGroupBox("Rumble Filter (Low-Cut)")
        hp_lay = QVBoxLayout(hp_box)
        self.hp_en = QCheckBox("Enable High-pass filter (removes desk thumps, AC rumble, and plosives)")
        self.hp_en.setChecked(self.cfg.highpass_enabled)
        hp_row = QHBoxLayout()
        hp_row.addWidget(QLabel("Cutoff frequency:"))
        self.hp_freq = QSpinBox()
        self.hp_freq.setRange(20, 300)
        self.hp_freq.setValue(int(self.cfg.highpass_cutoff_hz))
        self.hp_freq.setSuffix(" Hz")
        hp_row.addWidget(self.hp_freq)
        hp_row.addStretch()
        hp_lay.addWidget(self.hp_en)
        hp_lay.addLayout(hp_row)
        lay.addWidget(hp_box)

        # AI RNNoise
        rnn_box = QGroupBox("AI Noise Suppression (RNNoise)")
        rnn_lay = QVBoxLayout(rnn_box)
        self.rnn_en = QCheckBox("Enable RNNoise AI suppression (removes fan noise, keyboard clicks, and mic hiss)")
        self.rnn_en.setChecked(self.cfg.rnnoise_enabled)
        rnn_row = QHBoxLayout()
        rnn_row.addWidget(QLabel("Suppression intensity:"))
        self.rnn_wet = QSlider(Qt.Horizontal)
        self.rnn_wet.setRange(0, 100)
        self.rnn_wet.setValue(int(round(self.cfg.rnnoise_wet * 100)))
        self.rnn_lbl = QLabel(f"{self.rnn_wet.value()}%")
        self.rnn_wet.valueChanged.connect(lambda v: self.rnn_lbl.setText(f"{v}%"))
        rnn_row.addWidget(self.rnn_wet, 1)
        rnn_row.addWidget(self.rnn_lbl)
        rnn_lay.addWidget(self.rnn_en)
        rnn_lay.addLayout(rnn_row)
        lay.addWidget(rnn_box)

        # Noise Gate
        gate_box = QGroupBox("Noise Gate (Silence during pauses)")
        gate_lay = QVBoxLayout(gate_box)
        self.gate_en = QCheckBox("Enable Noise Gate (completely mutes room background when you are silent)")
        self.gate_en.setChecked(self.cfg.noise_gate_enabled)
        g_row1 = QHBoxLayout()
        g_row1.addWidget(QLabel("Threshold:"))
        self.gate_thresh = QSlider(Qt.Horizontal)
        self.gate_thresh.setRange(-70, -20)
        self.gate_thresh.setValue(int(round(self.cfg.noise_gate_threshold_db)))
        self.gate_t_lbl = QLabel(f"{self.gate_thresh.value()} dB")
        self.gate_thresh.valueChanged.connect(lambda v: self.gate_t_lbl.setText(f"{v} dB"))
        g_row1.addWidget(self.gate_thresh, 1)
        g_row1.addWidget(self.gate_t_lbl)

        g_row2 = QHBoxLayout()
        g_row2.addWidget(QLabel("Release:"))
        self.gate_rel = QSpinBox()
        self.gate_rel.setRange(10, 1000)
        self.gate_rel.setValue(int(round(self.cfg.noise_gate_release_ms)))
        self.gate_rel.setSuffix(" ms")
        g_row2.addWidget(self.gate_rel)
        g_row2.addStretch()

        gate_lay.addWidget(self.gate_en)
        gate_lay.addLayout(g_row1)
        gate_lay.addLayout(g_row2)
        lay.addWidget(gate_box)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        self.cfg.highpass_enabled = self.hp_en.isChecked()
        self.cfg.highpass_cutoff_hz = float(self.hp_freq.value())
        self.cfg.rnnoise_enabled = self.rnn_en.isChecked()
        self.cfg.rnnoise_wet = self.rnn_wet.value() / 100.0
        self.cfg.noise_gate_enabled = self.gate_en.isChecked()
        self.cfg.noise_gate_threshold_db = float(self.gate_thresh.value())
        self.cfg.noise_gate_release_ms = float(self.gate_rel.value())
        self.core.set_prefx(self.cfg)
        self.accept()


class SoundboardDialog(QDialog):
    """Soundboard management: add clips, assign hotkeys, adjust volumes, and trigger sounds."""
    def __init__(self, core: Core, parent=None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("Soundboard")
        self.resize(680, 420)
        lay = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Name", "Hotkey", "Volume", "Out", "Headphones", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        lay.addWidget(self.table, 1)

        # Waveform & Trim Editor
        self.waveform_widget = SoundboardWaveformWidget(self.core, self)
        lay.addWidget(self.waveform_widget)

        # Soundboard Mic Ducking Options Strip
        duck_strip = QFrame()
        duck_strip.setStyleSheet("background: #11141f; border: 1px solid #1f2638; border-radius: 4px; padding: 4px 8px;")
        duck_lay = QHBoxLayout(duck_strip)
        duck_lay.setContentsMargins(6, 4, 6, 4)
        duck_lay.setSpacing(10)

        self.duck_en = QCheckBox("Duck microphone during soundboard playback")
        self.duck_en.setChecked(getattr(self.core.cfg, "soundboard_ducking_enabled", False))
        self.duck_en.toggled.connect(self._on_duck_toggled)
        duck_lay.addWidget(self.duck_en)

        duck_lay.addStretch()

        duck_lbl = QLabel("Attenuation:")
        duck_lbl.setStyleSheet("color: #94a3b8; font-size: 8pt;")
        duck_lay.addWidget(duck_lbl)

        self.duck_slider = QSlider(Qt.Horizontal)
        self.duck_slider.setRange(-30, -3)
        self.duck_slider.setValue(int(round(getattr(self.core.cfg, "soundboard_duck_db", -12.0))))
        self.duck_slider.setFixedWidth(100)
        self.duck_slider.valueChanged.connect(self._on_duck_db_changed)
        duck_lay.addWidget(self.duck_slider)

        self.duck_val_lbl = QLabel(f"{self.duck_slider.value()} dB")
        self.duck_val_lbl.setStyleSheet("color: #38bdf8; font-family: Consolas; font-size: 8pt; font-weight: bold;")
        self.duck_val_lbl.setFixedWidth(45)
        duck_lay.addWidget(self.duck_val_lbl)

        lay.addWidget(duck_strip)

        bottom = QHBoxLayout()
        add_btn = QPushButton("+ Add sound clip…")
        stop_all_btn = QPushButton("Stop all sounds")
        stop_all_btn.setObjectName("testButton")
        bottom.addWidget(add_btn)
        bottom.addWidget(stop_all_btn)
        bottom.addStretch()
        close_btn = QPushButton("Close")
        bottom.addWidget(close_btn)
        lay.addLayout(bottom)

        add_btn.clicked.connect(self._add_clip)
        stop_all_btn.clicked.connect(core.stop_all_soundboard)
        close_btn.clicked.connect(self.accept)
        core.soundboardChanged.connect(self._refresh_rows)

        self.resize(760, 520)
        self._refresh_rows()

    def _refresh_rows(self):
        self.table.setRowCount(0)
        for row, clip in enumerate(self.core.cfg.soundboard):
            self.table.insertRow(row)

            # Name
            self.table.setItem(row, 0, QTableWidgetItem(clip.name))

            # Hotkey button
            hk_btn = QPushButton(clip.hotkey.label if clip.hotkey.is_set() else "Set key…")
            hk_btn.clicked.connect(partial(self._set_hotkey, clip))
            self.table.setCellWidget(row, 1, hk_btn)

            # Volume slider
            vol_slider = QSlider(Qt.Horizontal)
            vol_slider.setRange(-40, 12)
            vol_slider.setValue(int(round(clip.volume_db)))
            vol_slider.valueChanged.connect(partial(self._vol_changed, clip))
            self.table.setCellWidget(row, 2, vol_slider)

            # Route out
            out_cb = QCheckBox()
            out_cb.setChecked(clip.route_output)
            out_cb.toggled.connect(partial(self._route_out_changed, clip))
            self.table.setCellWidget(row, 3, out_cb)

            # Route mon
            mon_cb = QCheckBox()
            mon_cb.setChecked(clip.route_monitor)
            mon_cb.toggled.connect(partial(self._route_mon_changed, clip))
            self.table.setCellWidget(row, 4, mon_cb)

            # Play / Stop button
            action_btn = QPushButton("STOP" if self.core.engine.soundboard.is_playing(clip.id) else "PLAY")
            action_btn.clicked.connect(partial(self._toggle_play, clip))
            self.table.setCellWidget(row, 5, action_btn)

        if self.core.cfg.soundboard:
            cur_r = self.table.currentRow()
            r_sel = cur_r if 0 <= cur_r < len(self.core.cfg.soundboard) else 0
            self.table.selectRow(r_sel)
            self.waveform_widget.set_clip(self.core.cfg.soundboard[r_sel])
        else:
            self.waveform_widget.set_clip(None)

    def _add_clip(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose audio clip",
            "",
            "Audio files (*.wav *.mp3 *.ogg *.flac *.aac *.m4a)",
        )
        if path:
            name = os.path.splitext(os.path.basename(path))[0]
            clip = SoundboardClipConfig(name=name, path=path)
            self.core.cfg.soundboard.append(clip)
            self.core.rebind_hotkeys()
            self.core.save()
            self._refresh_rows()

    def _set_hotkey(self, clip: SoundboardClipConfig):
        dlg = HotkeyDialog(self.core, self, f"Hotkey for '{clip.name}'")
        if dlg.exec() and dlg.result_hotkey is not None:
            clip.hotkey = dlg.result_hotkey
            self.core.rebind_hotkeys()
            self.core.save()
            self._refresh_rows()

    def _vol_changed(self, clip: SoundboardClipConfig, val: int):
        clip.volume_db = float(val)
        self.core.save()

    def _route_out_changed(self, clip: SoundboardClipConfig, val: bool):
        clip.route_output = val
        self.core.save()

    def _route_mon_changed(self, clip: SoundboardClipConfig, val: bool):
        clip.route_monitor = val
        self.core.save()

    def _toggle_play(self, clip: SoundboardClipConfig):
        if self.core.engine.soundboard.is_playing(clip.id):
            self.core.stop_soundboard(clip.id)
        else:
            self.core.play_soundboard(clip)
        self._refresh_rows()

    def _on_table_selection_changed(self):
        rows = self.table.selectedIndexes()
        if not rows:
            return
        row = rows[0].row()
        if 0 <= row < len(self.core.cfg.soundboard):
            clip = self.core.cfg.soundboard[row]
            self.waveform_widget.set_clip(clip)

    def _on_duck_toggled(self, checked: bool):
        db = float(self.duck_slider.value())
        self.core.set_soundboard_ducking(checked, db)

    def _on_duck_db_changed(self, val: int):
        self.duck_val_lbl.setText(f"{val} dB")
        if self.duck_en.isChecked():
            self.core.set_soundboard_ducking(True, float(val))


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
        wizard_btn.setStyleSheet("""
            QPushButton {
                background: #0f2b20;
                border: 1px solid #10b981;
                color: #6ee7b7;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #143d2e;
            }
        """)
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
        lim_sep.setStyleSheet("color: #262c3d; margin: 8px 0;")
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
        tabs.addTab(tab_lim, "Limiter & Normalizer")

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
        midi_info.setStyleSheet("color: #94a3b8; font-size: 8.5pt;")
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
        self.midi_learn_btn.setStyleSheet(
            "background: #0c1928; border: 1px solid #0284c7; color: #38bdf8; font-weight: bold; padding: 5px 12px; border-radius: 4px;"
        )
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
        self.api_en = QCheckBox("Enable Local HTTP/REST API (for Stream Deck, OBS, & Webhooks)")
        self.api_en.setChecked(getattr(self.cfg, "api_enabled", False))
        self.api_port_spin = QSpinBox()
        self.api_port_spin.setRange(1024, 65535)
        self.api_port_spin.setValue(getattr(self.cfg, "api_port", 38420))

        api_lay.addRow("", self.api_en)
        api_lay.addRow("API Port", self.api_port_spin)

        api_info = QLabel("Allows Elgato Stream Deck, OBS browser docks, and local apps to switch presets, play soundboard clips, and mute over HTTP.")
        api_info.setWordWrap(True)
        api_info.setStyleSheet("color: #94a3b8; font-size: 8.5pt;")
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

    def apply_all(self):
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


# =============================================================== chain editor
class ChainEditor(QWidget):
    chainEdited = Signal()          # name/hotkey/mode changed -> refresh list
    openEditor = Signal(object)     # PluginSlot

    def __init__(self, core: Core):
        super().__init__()
        self.core = core
        self.chain: Chain | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # Rack Bay Outer Container
        rack_bay = QFrame()
        rack_bay.setObjectName("modularBay")
        rb_lay = QVBoxLayout(rack_bay)
        rb_lay.setContentsMargins(12, 10, 12, 10)
        rb_lay.setSpacing(8)

        # Rack Bay Header
        rb_hdr = QHBoxLayout()
        rb_hdr.setSpacing(8)
        rb_hdr.addWidget(RackScrew(14))
        self.hdr_static = QLabel("EFFECTS RACK  //  BUS:")
        self.hdr_static.setStyleSheet("font-weight: 800; font-size: 8.5pt; color: #94a3b8; letter-spacing: 0.8px;")
        rb_hdr.addWidget(self.hdr_static)

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("rackBusNameEdit")
        self.name_edit.setPlaceholderText("PRESET NAME")
        self.name_edit.setToolTip("Click to rename this voice preset bus")
        self.name_edit.setMinimumWidth(140)
        self.name_edit.setMaximumWidth(280)
        self.name_edit.setStyleSheet("""
            QLineEdit#rackBusNameEdit {
                background: #0b0e14;
                border: 1px dashed #334155;
                border-radius: 4px;
                padding: 3px 8px;
                color: #ffffff;
                font-family: "Segoe UI", sans-serif;
                font-weight: 800;
                font-size: 9pt;
                letter-spacing: 0.5px;
            }
            QLineEdit#rackBusNameEdit:hover {
                border: 1px solid #475569;
                background: #141923;
            }
            QLineEdit#rackBusNameEdit:focus {
                border: 1.5px solid #e11d48;
                background: #1a202c;
            }
        """)
        self.name = self.name_edit  # backward compatibility alias
        rb_hdr.addWidget(self.name_edit)
        rb_hdr.addStretch()

        self.add_btn = QPushButton("+ INSERT PLUGIN")
        self.add_btn.setObjectName("rackUiBtn")
        self.add_btn.setStyleSheet("background: #e11d48; border: 1px solid #f43f5e; color: white; font-weight: 800; font-size: 8pt; padding: 4px 12px; border-radius: 4px; letter-spacing: 0.5px;")
        rb_hdr.addWidget(self.add_btn)
        rb_hdr.addWidget(RackScrew(14))
        rb_lay.addLayout(rb_hdr)

        # Streamlined 1-Row Hardware Inspector with Rotary Knobs
        insp_box = QFrame()
        insp_box.setStyleSheet("background: #090a0f; border: 1px solid #1c202d; border-radius: 6px; padding: 4px 8px;")
        insp_lay = QHBoxLayout(insp_box)
        insp_lay.setContentsMargins(6, 4, 6, 4)
        insp_lay.setSpacing(12)

        # Hotkey section
        hk_box = QHBoxLayout()
        hk_box.setSpacing(6)
        lbl_hk = QLabel("HOTKEY:")
        lbl_hk.setObjectName("rackInspLabel")
        hk_box.addWidget(lbl_hk)
        self.hk_btn = QPushButton("SET KEY")
        self.hk_btn.setObjectName("rackHotkeyBtn")
        self.hk_label = QLabel("—")
        self.hk_label.setVisible(False)
        hk_box.addWidget(self.hk_btn)
        insp_lay.addLayout(hk_box)

        # Mode section
        mode_box = QHBoxLayout()
        mode_box.setSpacing(6)
        lbl_mode = QLabel("TRIGGER:")
        lbl_mode.setObjectName("rackInspLabel")
        mode_box.addWidget(lbl_mode)
        self.mode = QComboBox()
        self.mode.addItem("Toggle", "toggle")
        self.mode.addItem("Hold", "hold")
        mode_box.addWidget(self.mode)
        insp_lay.addLayout(mode_box)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #1e2433;")
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
        sep2.setStyleSheet("color: #1e2433;")
        insp_lay.addWidget(sep2)

        # DSP Latency chip
        self.lat_lbl = QLabel("LATENCY: 0.0 ms")
        self.lat_lbl.setStyleSheet("color: #64748b; font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold;")
        insp_lay.addWidget(self.lat_lbl)
        insp_lay.addStretch()

        # Live on Mic Toggle Button
        self.live_btn = QPushButton("SET LIVE ON MIC")
        self.live_btn.setObjectName("rackLiveToggle")
        self.live_btn.setMinimumHeight(28)
        self.live_btn.setStyleSheet("background: #151822; border: 1px solid #334155; color: #94a3b8; font-weight: bold; font-size: 7.5pt; padding: 4px 12px; border-radius: 4px;")
        self.live_btn.setToolTip("Click to toggle this preset live on your microphone output")
        insp_lay.addWidget(self.live_btn)
        self.test_btn = self.live_btn  # backward compatibility alias

        rb_lay.addWidget(insp_box)

        # The 1U Modular Effects Rack List
        self.plugins = QListWidget()
        self.plugins.setObjectName("rackList")
        rb_lay.addWidget(self.plugins, 1)

        lay.addWidget(rack_bay, 1)

        self.name_edit.editingFinished.connect(self._rename)
        self.hk_btn.clicked.connect(self._set_hotkey)
        self.mode.currentIndexChanged.connect(self._mode)
        self.knob_gain.valueChanged.connect(self._params)
        self.knob_wet.valueChanged.connect(self._params)
        self.knob_tail.valueChanged.connect(self._params)
        self.add_btn.clicked.connect(self._add)
        self.live_btn.clicked.connect(self._toggle_live)

    def _toggle_live(self):
        if self.chain:
            self.core.press(self.chain.id)

    def set_chain(self, chain: Chain | None):
        self.chain = chain
        self.setEnabled(chain is not None)
        if chain is None:
            self.name_edit.setText("")
            self.hk_btn.setText("SET KEY")
            self.plugins.clear()
            self.lat_lbl.setText("LATENCY: 0.0 ms")
            self.live_btn.setText("STANDBY")
            return
        self.name_edit.setText(chain.name)
        self.hk_btn.setText(chain.hotkey.label.upper() if chain.hotkey.is_set() else "SET KEY")
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
                it.setSizeHint(QSize(280, card_h))
                self.plugins.addItem(it)
                self.plugins.setItemWidget(it, card)

        self.plugins.blockSignals(False)
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
    def __init__(self, core: Core):
        super().__init__()
        self.core = core
        self.cfg = core.cfg
        self._editor_event: threading.Event | None = None
        self._quitting = False
        self.setWindowTitle("Mandible")
        self.setWindowIcon(branding.app_icon())
        self.resize(1020, 660)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        self.setCentralWidget(central)

        # Outer 19" Rack Chassis
        self.chassis = ChassisWrapperFrame()
        self.chassis.setObjectName("rackChassis")
        ch_lay = QVBoxLayout(self.chassis)
        self.chassis.update_frame_margins()
        ch_lay.setSpacing(0)
        root.addWidget(self.chassis, 1)

        # ---- Top Master Hardware Head Strip (Zero Emojis)
        master_strip = QFrame()
        master_strip.setObjectName("masterHeadStrip")
        top = QHBoxLayout(master_strip)
        top.setContentsMargins(14, 10, 14, 10)
        top.setSpacing(14)

        # Left: Rack screw + Pilot Lamp + Master Power toggle
        mb_left = QHBoxLayout()
        mb_left.setSpacing(10)
        mb_left.addWidget(RackScrew(16))

        self.pilot_lamp = PilotLamp(active=False, size=18)
        mb_left.addWidget(self.pilot_lamp)

        self.power = QPushButton("MASTER POWER")
        self.power.setCheckable(True)
        self.power.setObjectName("hardwareMasterToggle")
        mb_left.addWidget(self.power)
        top.addLayout(mb_left)

        # Center-Left: Smoked-glass Digital Telemetry VFD
        self.vfd_box = QFrame()
        self.vfd_box.setObjectName("telemetryDisplay")
        vfd_lay = QHBoxLayout(self.vfd_box)
        vfd_lay.setContentsMargins(10, 5, 10, 5)
        vfd_lay.setSpacing(10)

        self.vfd_stat = QLabel("DSP: STOPPED")
        self.vfd_stat.setStyleSheet("font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; color: #64748b;")
        self.vfd_sr = QLabel("48.0 kHz")
        self.vfd_sr.setStyleSheet("font-family: Consolas, monospace; font-size: 7.5pt; color: #94a3b8;")
        self.vfd_buf = QLabel("128 SMP")
        self.vfd_buf.setStyleSheet("font-family: Consolas, monospace; font-size: 7.5pt; color: #94a3b8;")
        self.vfd_lat = QLabel("2.7 ms")
        self.vfd_lat.setStyleSheet("font-family: Consolas, monospace; font-size: 7.5pt; color: #38bdf8; font-weight: bold;")
        self.vfd_drv = QLabel("ASIO")
        self.vfd_drv.setStyleSheet("font-family: Consolas, monospace; font-size: 7.5pt; color: #cbd5e1; font-weight: bold;")

        for w in [self.vfd_stat, self.vfd_sr, self.vfd_buf, self.vfd_lat, self.vfd_drv]:
            vfd_lay.addWidget(w)
        top.addWidget(self.vfd_box)

        # Center: Illuminated routing bus
        self.flow_strip = SignalFlowStrip(core, self)
        top.addWidget(self.flow_strip, 1)

        # Right: Mic Audition Loop, Phones Monitor, Panic Cut, Config & Right Rack Screw
        mb_right = QHBoxLayout()
        mb_right.setSpacing(8)

        self.audition_btn = QPushButton("TEST MIC (5s)")
        self.audition_btn.setObjectName("hardwareAuditionBtn")
        self.audition_btn.setToolTip("Record 5 seconds of your dry voice and loop it continuously through active rack so you can audition knobs and pitch without speaking")
        self.audition_btn.clicked.connect(self._toggle_mic_audition)
        mb_right.addWidget(self.audition_btn)

        self.monitor = QPushButton("PHONES MONITOR")
        self.monitor.setCheckable(True)
        self.monitor.setChecked(self.cfg.monitor_enabled)
        self.monitor.setObjectName("hardwareMonitorToggle")
        self.monitor.setToolTip("Listen to your output in your headphones")
        mb_right.addWidget(self.monitor)

        self.panic_top_btn = QPushButton("PANIC CUT")
        self.panic_top_btn.setObjectName("hardwarePanicCut")
        self.panic_top_btn.setToolTip("Hotkey F12 / Panic: Turn all effect chains off immediately")
        mb_right.addWidget(self.panic_top_btn)

        settings_btn = QPushButton("CONFIG")
        settings_btn.setObjectName("hardwareConfigBtn")
        mb_right.addWidget(settings_btn)

        help_btn = QPushButton("HELP")
        help_btn.setObjectName("hardwareConfigBtn")
        help_menu = QMenu(help_btn)
        help_menu.addAction("About Mandible…").triggered.connect(lambda: self._open_about(0))
        help_menu.addAction("Licenses…").triggered.connect(lambda: self._open_about(1))
        help_btn.setMenu(help_menu)
        mb_right.addWidget(help_btn)

        mb_right.addWidget(RackScrew(16))
        top.addLayout(mb_right)

        ch_lay.addWidget(master_strip)

        # Retain aliases for backward compatibility
        self.clean_mic_btn = self.flow_strip.prefx_btn
        self.soundboard_btn = self.flow_strip.sb_btn
        self.status = QLabel("Stopped")
        self.status.setVisible(False)
        self.active_lbl = QLabel()
        self.active_lbl.setVisible(False)

        # ---- Body: Voice Presets Bank (left) | 1U Effects Rack (right)
        body_widget = QWidget()
        body_lay = QHBoxLayout(body_widget)
        body_lay.setContentsMargins(12, 12, 12, 12)
        body_lay.setSpacing(12)

        left = QFrame()
        left.setObjectName("sideRackBay")
        left.setFixedWidth(310)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        # 1. Top: PRE-FX NOISE GATE Hardware Unit
        self.prefx_strip = QFrame()
        self.prefx_strip.setObjectName("prefxModule")
        self.prefx_strip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prefx_strip.setFixedHeight(36)
        pfx_lay = QHBoxLayout(self.prefx_strip)
        pfx_lay.setContentsMargins(12, 0, 10, 0)
        pfx_lay.setSpacing(8)

        # Name label (redundant left lamp removed; switch has its own jewel pilot light)
        pfx_lbl = QLabel("PRE-FX NOISE GATE")
        pfx_lbl.setStyleSheet("font-weight: 800; font-size: 7.5pt; color: #94a3b8; letter-spacing: 0.8px;")
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
        pb_lay = QVBoxLayout(self.preset_bay)
        pb_lay.setContentsMargins(10, 10, 10, 10)
        pb_lay.setSpacing(8)

        # Inset Preset Bay Header
        chain_head = QHBoxLayout()
        chain_head.setSpacing(6)
        chain_head.addWidget(RackScrew(12))
        chain_title = QLabel("VOICE PRESET BANK")
        chain_title.setStyleSheet("font-weight: 800; font-size: 8pt; color: #94a3b8; letter-spacing: 0.8px;")
        chain_head.addWidget(chain_title)
        chain_head.addStretch()

        factory_c = QPushButton("FACTORY")
        factory_c.setToolTip("Browse and load factory voice presets (Built-in effects)")
        factory_c.setCursor(Qt.CursorShape.PointingHandCursor)
        factory_c.setStyleSheet(
            "QPushButton { background: #131722; border: 1px solid #262c3d; color: #10b981; "
            "font-family: Consolas, monospace; font-size: 7pt; font-weight: bold; padding: 2px 6px; border-radius: 3px; }"
            "QPushButton:hover { background: #064e3b; color: #6ee7b7; border-color: #10b981; }"
        )
        factory_c.clicked.connect(self._show_factory_presets_menu)

        imp_c = QPushButton("IMPORT")
        imp_c.setToolTip("Import a Mandible preset file (.mandible or legacy .vfxpreset)")
        imp_c.setCursor(Qt.CursorShape.PointingHandCursor)
        imp_c.setStyleSheet(
            "QPushButton { background: #131722; border: 1px solid #262c3d; color: #94a3b8; "
            "font-family: Consolas, monospace; font-size: 7pt; font-weight: bold; padding: 2px 6px; border-radius: 3px; }"
            "QPushButton:hover { background: #1e293b; color: #38bdf8; border-color: #38bdf8; }"
        )
        exp_c = QPushButton("EXPORT")
        exp_c.setToolTip("Export selected voice preset (.mandible)")
        exp_c.setCursor(Qt.CursorShape.PointingHandCursor)
        exp_c.setStyleSheet(
            "QPushButton { background: #131722; border: 1px solid #262c3d; color: #94a3b8; "
            "font-family: Consolas, monospace; font-size: 7pt; font-weight: bold; padding: 2px 6px; border-radius: 3px; }"
            "QPushButton:hover { background: #1e293b; color: #38bdf8; border-color: #38bdf8; }"
        )
        chain_head.addWidget(factory_c)
        chain_head.addWidget(imp_c)
        chain_head.addWidget(exp_c)
        chain_head.addWidget(RackScrew(12))
        pb_lay.addLayout(chain_head)

        self.chain_list = QListWidget()
        self.chain_list.setObjectName("chainList")
        self.chain_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chain_list.customContextMenuRequested.connect(self._chain_context_menu)
        pb_lay.addWidget(self.chain_list, 1)

        # Presets Toolbar: [ + ] [ DUPLICATE ] [ DELETE ] [ ▲ ] [ ▼ ]
        cb = QHBoxLayout()
        cb.setSpacing(5)
        add_c = RackToolButton("plus", "Add new voice preset (+)")
        dup_c = QPushButton("DUPLICATE")
        dup_c.setStyleSheet("background: #151822; border: 1px solid #262a3a; color: #cbd5e1; font-size: 7.5pt; font-weight: bold; padding: 5px 8px; border-radius: 4px;")
        del_c = QPushButton("DELETE")
        del_c.setStyleSheet("background: #151822; border: 1px solid #262a3a; color: #94a3b8; font-size: 7.5pt; font-weight: bold; padding: 5px 8px; border-radius: 4px;")
        up_c = RackToolButton("up", "Move preset earlier in bank")
        dn_c = RackToolButton("down", "Move preset later in bank")
        for b in (add_c, dup_c, del_c, up_c, dn_c):
            cb.addWidget(b)
        pb_lay.addLayout(cb)
        ll.addWidget(self.preset_bay, 1)

        # 3. Bottom: MASTER SAFETY LIMITER Hardware Unit (below toolbar)
        self.limiter_strip = QFrame()
        self.limiter_strip.setObjectName("limiterModule")
        self.limiter_strip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.limiter_strip.setFixedHeight(36)
        lim_lay = QHBoxLayout(self.limiter_strip)
        lim_lay.setContentsMargins(12, 0, 10, 0)
        lim_lay.setSpacing(8)

        # Name label (redundant left lamp removed; switch has its own jewel pilot light)
        lim_lbl = QLabel("MASTER SAFETY LIMITER")
        lim_lbl.setStyleSheet("font-weight: 800; font-size: 7.5pt; color: #94a3b8; letter-spacing: 0.8px;")
        lim_lay.addWidget(lim_lbl)

        lim_lay.addStretch()

        self.limiter_thresh_lbl = QLabel(f"{self.cfg.limiter.threshold_db:+.1f} dB")
        self.limiter_thresh_lbl.setStyleSheet("color: #94a3b8; font-family: Consolas; font-size: 7.5pt; font-weight: bold; margin-right: 4px;")
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
        self.limiter_strip.setToolTip("Click to toggle Master Safety Limiter  ·  Right-click for Ceiling Settings")
        ll.addWidget(self.limiter_strip)

        body_lay.addWidget(left)

        self.editor = ChainEditor(core)
        body_lay.addWidget(self.editor, 1)
        ch_lay.addWidget(body_widget, 1)

        # ---- bottom calibrated meters & gain sliders (collapsible)
        self.console_frame = QFrame()
        self.console_frame.setStyleSheet("background: #090a0f; border-top: 1px solid #1c2130;")
        cf_lay = QVBoxLayout(self.console_frame)
        cf_lay.setContentsMargins(12, 6, 12, 6)
        cf_lay.setSpacing(6)

        cf_head = QHBoxLayout()
        cf_head.setContentsMargins(0, 0, 0, 0)
        c_title = QLabel("HARDWARE I/O CHANNEL STRIPS")
        c_title.setStyleSheet("font-weight: 800; font-size: 7.5pt; color: #64748b; letter-spacing: 0.8px;")
        cf_head.addWidget(c_title)
        cf_head.addStretch()

        self.faders_collapsed = False
        self.collapse_faders_btn = QPushButton("▼ COLLAPSE FADERS")
        self.collapse_faders_btn.setStyleSheet("""
            QPushButton {
                background: #131722;
                border: 1px solid #262c3d;
                border-radius: 4px;
                color: #94a3b8;
                font-size: 7.5pt;
                font-weight: bold;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background: #1e2436;
                color: #ffffff;
                border-color: #3b4560;
            }
        """)
        self.collapse_faders_btn.clicked.connect(self._toggle_faders_collapse)
        cf_head.addWidget(self.collapse_faders_btn)
        cf_lay.addLayout(cf_head)

        # 1. Full Faders View (Meters + Faders)
        self.full_faders_widget = QWidget()
        meters = QHBoxLayout(self.full_faders_widget)
        meters.setContentsMargins(0, 0, 0, 0)
        meters.setSpacing(8)

        self.m_in = LevelMeter("CH 01  PRE-FX MIC IN")
        self.m_out = LevelMeter("CH 02  POST-FX BROADCAST")
        self.m_mon = LevelMeter("CH 03  HEADPHONE MONITOR")

        self.g_in = GainSlider("Trim", self.cfg.input_gain_db)
        self.g_out = GainSlider("Master", self.cfg.output_gain_db)
        self.g_mon = GainSlider("Phones", self.cfg.monitor_gain_db)

        in_name = self.cfg.audio.input_device or "Focusrite"
        strip_in = ChannelStripCard(f"CH 01  MIC IN ({in_name})", "#10b981", self.m_in, self.g_in)
        strip_out = ChannelStripCard("CH 02  MAIN OUT (DISCORD / LOOPBACK)", "#e11d48", self.m_out, self.g_out)
        strip_mon = ChannelStripCard("CH 03  HEADPHONES (MONITOR)", "#06b6d4", self.m_mon, self.g_mon)

        meters.addWidget(strip_in, 1)
        meters.addWidget(strip_out, 1)
        meters.addWidget(strip_mon, 1)
        cf_lay.addWidget(self.full_faders_widget)

        # 2. Condensed Meter View (Thin level meters)
        self.condensed_faders_widget = QWidget()
        self.condensed_faders_widget.setVisible(False)
        cond_lay = QHBoxLayout(self.condensed_faders_widget)
        cond_lay.setContentsMargins(4, 2, 4, 2)
        cond_lay.setSpacing(12)

        def _make_condensed_strip(name: str, dot_col: str):
            box = QFrame()
            box.setStyleSheet("background: #0f121a; border: 1px solid #1e2433; border-radius: 4px; padding: 4px 8px;")
            b_lay = QHBoxLayout(box)
            b_lay.setContentsMargins(6, 3, 6, 3)
            b_lay.setSpacing(8)

            d = QLabel()
            d.setFixedSize(6, 6)
            d.setStyleSheet(f"background: {dot_col}; border-radius: 3px;")
            b_lay.addWidget(d)

            lbl = QLabel(name)
            lbl.setStyleSheet("font-weight: bold; font-size: 7.5pt; color: #94a3b8;")
            b_lay.addWidget(lbl)

            tm = ThinLevelMeter()
            b_lay.addWidget(tm, 1)
            return box, tm

        c_box_in, self.thin_m_in = _make_condensed_strip(f"CH 01 MIC ({in_name})", "#10b981")
        c_box_out, self.thin_m_out = _make_condensed_strip("CH 02 MAIN OUT", "#e11d48")
        c_box_mon, self.thin_m_mon = _make_condensed_strip("CH 03 PHONES", "#06b6d4")

        cond_lay.addWidget(c_box_in, 1)
        cond_lay.addWidget(c_box_out, 1)
        cond_lay.addWidget(c_box_mon, 1)
        cf_lay.addWidget(self.condensed_faders_widget)

        ch_lay.addWidget(self.console_frame)

        # ---- footer
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(QLabel("When inactive:"))
        self.idle = QComboBox()
        bottom.addWidget(self.idle)
        bottom.addSpacing(10)
        self.hk_enabled = QCheckBox("Hotkeys enabled")
        self.hk_enabled.setChecked(self.cfg.hotkeys_enabled)
        bottom.addWidget(self.hk_enabled)
        bottom.addSpacing(10)
        self.panic_btn = QPushButton("Panic Hotkey…")
        self.panic_btn.setToolTip("Set global hotkey that turns every chain off")
        bottom.addWidget(self.panic_btn)
        bottom.addStretch()
        self.diag = QLabel()
        self.diag.setObjectName("diagLabel")
        bottom.addWidget(self.diag)
        root.addLayout(bottom)

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
        self.tray.show()

        # ---- wiring
        self.power.toggled.connect(self._power)
        self.monitor.toggled.connect(self._monitor_toggled)
        self.clean_mic_btn.clicked.connect(self._open_prefx)
        self.soundboard_btn.clicked.connect(self._open_soundboard)
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
        imp_c.clicked.connect(self._import_chain)
        exp_c.clicked.connect(self._export_chain)
        self.chain_list.currentRowChanged.connect(self._select_chain)
        self.chain_list.itemDoubleClicked.connect(self._chain_double_clicked)
        self.editor.chainEdited.connect(self.refresh_chains)
        self.editor.openEditor.connect(self.open_plugin_editor)
        self.g_in.changed.connect(core.set_input_gain)
        self.g_out.changed.connect(core.set_output_gain)
        self.g_mon.changed.connect(core.set_monitor_gain)
        self.idle.currentIndexChanged.connect(self._idle_changed)
        self.hk_enabled.toggled.connect(self._hk_toggled)
        self.panic_btn.clicked.connect(self._set_panic)
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
        self._update_prefx_button_style()
        self.refresh_chains()
        self._update_limiter_ui()
        if self.cfg.chains:
            self.chain_list.setCurrentRow(0)

    def _toggle_faders_collapse(self):
        self.faders_collapsed = not self.faders_collapsed
        self.full_faders_widget.setVisible(not self.faders_collapsed)
        self.condensed_faders_widget.setVisible(self.faders_collapsed)
        self.collapse_faders_btn.setText("▲ EXPAND FADERS" if self.faders_collapsed else "▼ COLLAPSE FADERS")

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

    def _update_limiter_ui(self):
        l_on = bool(self.cfg.limiter.enabled)
        if hasattr(self, "limiter_switch"):
            self.limiter_switch.set_active(l_on)
        if hasattr(self, "limiter_lamp"):
            self.limiter_lamp.set_active(l_on)
        if hasattr(self, "limiter_strip"):
            self.limiter_strip.setProperty("active", "true" if l_on else "false")
            self.limiter_strip.style().unpolish(self.limiter_strip)
            self.limiter_strip.style().polish(self.limiter_strip)
        if hasattr(self, "limiter_stat_lbl"):
            self.limiter_stat_lbl.setText("ACTIVE" if l_on else "BYPASS")
            if l_on:
                self.limiter_stat_lbl.setStyleSheet(
                    "color: #10b981; font-family: Consolas; font-size: 7.5pt; font-weight: 800; "
                    "background: #092318; border: 1px solid #059669; border-radius: 4px; padding: 1px 7px;"
                )
            else:
                self.limiter_stat_lbl.setStyleSheet(
                    "color: #f87171; font-family: Consolas; font-size: 7.5pt; font-weight: 800; "
                    "background: #201014; border: 1px solid #4d1d24; border-radius: 4px; padding: 1px 7px;"
                )
        if hasattr(self, "limiter_thresh_lbl"):
            self.limiter_thresh_lbl.setText(f"{self.cfg.limiter.threshold_db:+.1f} dB")
            self.limiter_thresh_lbl.setStyleSheet(
                "color: #94a3b8; font-family: Consolas; font-size: 7.5pt; font-weight: bold; margin-right: 4px;" if l_on
                else "color: #475569; font-family: Consolas; font-size: 7.5pt; font-weight: bold; margin-right: 4px;"
            )
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
            it.setSizeHint(QSize(260, 68))
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
            text, on = "MUTED", False
        elif target == DRY_ID:
            text, on = "CLEAN VOICE", False
        else:
            c = self.core.chain_by_id(target)
            text, on = (f"{c.name.upper()}" if c else "?"), True

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
            if is_live:
                self.editor.live_btn.setText("● LIVE ON MIC")
                self.editor.live_btn.setStyleSheet("background: #064e3b; border: 1.5px solid #10b981; color: #a7f3d0; font-size: 7.5pt; font-weight: 800; padding: 4px 12px; border-radius: 4px;")
            else:
                self.editor.live_btn.setText("SET LIVE ON MIC")
                self.editor.live_btn.setStyleSheet("background: #151822; border: 1px solid #334155; color: #94a3b8; font-size: 7.5pt; font-weight: bold; padding: 4px 12px; border-radius: 4px;")

        if hasattr(self, "power"):
            self.power.setChecked(self.core.engine.running)
            self.power.setText("AUDIO ACTIVE" if self.core.engine.running else "MASTER POWER")

        if hasattr(self, "pilot_lamp"):
            self.pilot_lamp.set_active(self.core.engine.running)

        if hasattr(self, "monitor"):
            self.monitor.setChecked(self.core.engine.monitor_enabled)
            self.monitor.setText("PHONES MONITOR: ON" if self.core.engine.monitor_enabled else "PHONES MONITOR")


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

    def _show_factory_presets_menu(self):
        menu = QMenu(self)
        for p_def in get_factory_presets():
            a = menu.addAction(f"{p_def['name']}  ·  {p_def['desc']}")
            a.triggered.connect(partial(self._load_factory_preset, p_def))
        menu.exec(self.chain_list.mapToGlobal(QPointF(20, 20).toPoint()))

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
            self.audition_btn.setText("TEST MIC (5s)")
            self.audition_btn.setStyleSheet("")
        else:
            if not self.core.engine.running:
                try:
                    self.core.start_audio()
                except Exception as exc:
                    QMessageBox.warning(self, "Audio Error", f"Could not start audio engine: {exc}")
                    return
            self.core.start_mic_audition(5.0)
            self.audition_btn.setText("REC (0.0s / 5.0s)")
            self.audition_btn.setStyleSheet("background: #450a0a; border: 1px solid #ef4444; color: #fca5a5; font-weight: bold;")
            if not self.cfg.monitor_enabled:
                self.monitor.setChecked(True)
                self.core.set_monitor_enabled(True)

    def _on_audition_progress(self, state: str, cur_s: float, tot_s: float):
        if state == "recording":
            self.audition_btn.setText(f"REC ({cur_s:.1f}s / {tot_s:.1f}s)")
            self.audition_btn.setStyleSheet("background: #450a0a; border: 1px solid #ef4444; color: #fca5a5; font-weight: bold;")
        elif state == "looping":
            self.audition_btn.setText("STOP LOOP")
            self.audition_btn.setStyleSheet("background: #064e3b; border: 1px solid #10b981; color: #6ee7b7; font-weight: bold;")
        elif state == "idle":
            self.audition_btn.setText("TEST MIC (5s)")
            self.audition_btn.setStyleSheet("")

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
        if hasattr(self, "prefx_lamp"):
            self.prefx_lamp.set_active(active)
        if hasattr(self, "prefx_strip"):
            self.prefx_strip.setProperty("active", "true" if active else "false")
            self.prefx_strip.style().unpolish(self.prefx_strip)
            self.prefx_strip.style().polish(self.prefx_strip)
        if hasattr(self, "prefx_stat_lbl"):
            self.prefx_stat_lbl.setText("ACTIVE" if active else "BYPASS")
            if active:
                self.prefx_stat_lbl.setStyleSheet(
                    "color: #10b981; font-family: Consolas; font-size: 7.5pt; font-weight: 800; "
                    "background: #092318; border: 1px solid #059669; border-radius: 4px; padding: 1px 7px;"
                )
            else:
                self.prefx_stat_lbl.setStyleSheet(
                    "color: #f87171; font-family: Consolas; font-size: 7.5pt; font-weight: 800; "
                    "background: #201014; border: 1px solid #4d1d24; border-radius: 4px; padding: 1px 7px;"
                )
        if hasattr(self, "clean_mic_btn"):
            self.clean_mic_btn.setText("MIC PRE-FX [ON]" if active else "MIC PRE-FX")
            self.clean_mic_btn.setProperty("active", active)
            self.clean_mic_btn.style().unpolish(self.clean_mic_btn)
            self.clean_mic_btn.style().polish(self.clean_mic_btn)
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
            self.power.setText("MASTER POWER")
            if hasattr(self, "pilot_lamp"):
                self.pilot_lamp.set_active(False)
            self.status.setText(f"[ERR] {exc}")
            self._update_status()
            return False
        self.power.blockSignals(True)
        self.power.setChecked(True)
        self.power.blockSignals(False)
        self.power.setText("AUDIO ACTIVE")
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
            self.power.setText("MASTER POWER")
            if hasattr(self, "pilot_lamp"):
                self.pilot_lamp.set_active(False)
            self._update_status()

    def _engine_stopped(self, reason):
        if self.core.engine.running:
            return
        self.power.blockSignals(True)
        self.power.setChecked(False)
        self.power.blockSignals(False)
        self.power.setText("MASTER POWER")
        if hasattr(self, "pilot_lamp"):
            self.pilot_lamp.set_active(False)
        self.core.engine.stream = None
        self.status.setText(f"[OFFLINE] {reason}")
        self._update_status()

    def _on_look_changed(self):
        """Look switched: the tray follows the accent (widgets repaint themselves)."""
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
                    self.vfd_stat.setStyleSheet("font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; color: #10b981;")
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
                    self.vfd_stat.setStyleSheet("font-family: Consolas, monospace; font-size: 7.5pt; font-weight: bold; color: #64748b;")
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
        self.diag.setText(f"DSP {e.load * 100:4.0f}%   dropouts {e.xruns}" if e.running else "DSP OFFLINE")
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
        self.panic_btn.setText(f"All-off key: {hk.label if hk.is_set() else 'not set'}")

    def _set_panic(self):
        dlg = HotkeyDialog(self.core, self, "All-off hotkey")
        if dlg.exec() and dlg.result_hotkey is not None:
            hk = dlg.result_hotkey
            if hk.is_set():
                clash = self.core.find_hotkey_conflict(hk)
                if clash:
                    QMessageBox.warning(self, "Hotkey in use", f"{hk.label} is already used by {clash}.")
                    return
            self.cfg.panic_hotkey = hk
            self.core.rebind_hotkeys()
            self.core.save()
            self._update_panic_label()

    def _open_about(self, start_tab: int = 0):
        from .about import AboutDialog
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
        self.core.shutdown()
        self.tray.hide()
        QApplication.quit()


# =============================================================== app entry point
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Mandible")
    app.setQuitOnLastWindowClosed(False)

    os.makedirs(APP_DIR, exist_ok=True)
    lock = QLockFile(os.path.join(APP_DIR, "mandible.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.information(None, "Mandible", "Mandible is already running (check the system tray).")
        return 0

    cfg = load_config()
    apply_theme(app, look_from_config(cfg))

    first_run = not cfg.audio.driver
    if first_run:
        cfg.audio = D.guess_focusrite_setup()
    if not cfg.chains:
        cfg.chains.append(Chain(name="My first voice"))

    core = Core(cfg)

    start_minimized = bool(cfg.start_minimized or ("--minimized" in sys.argv))

    n_plugins = sum(len(c.plugins) for c in cfg.chains)
    prog = None
    if n_plugins and not start_minimized:
        prog = QProgressDialog("Loading plugins…", None, 0, n_plugins)
        prog.setWindowTitle("Mandible")
        prog.setWindowIcon(branding.app_icon())
        prog.setMinimumDuration(300)

    def progress(n, total, name):
        if prog:
            prog.setValue(n)
            prog.setLabelText(f"Loading {name}…")
            QApplication.processEvents()

    core.load_all(progress)
    if prog:
        prog.close()

    win = MainWindow(core)
    if cfg.autostart_audio:
        win.start_audio()
    if not start_minimized:
        win.show()
    if first_run:
        core.save_now()
        win.show()
        QTimer.singleShot(300, win._open_setup_assistant)

    rc = app.exec()
    lock.unlock()
    return rc

