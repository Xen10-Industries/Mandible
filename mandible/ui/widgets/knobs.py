"""Rotary knobs."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from ... import plugins as P
from ...config import PluginSlot
from ...core import Core, inst
from ..elements.base import ElementState
from ..look import current_look
from .base import _follow_look, look_element
from .sliders import InlineValueEdit, parse_audio_value


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
