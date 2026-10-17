"""In-game / desktop floating HUD overlay showing active voice and mic status.
Uses Windows WS_EX_TRANSPARENT so mouse clicks pass right through to games.
"""
from __future__ import annotations

import ctypes
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from .ui.look import current_look, look_bus


def _tok(token: str) -> QColor:
    return QColor(current_look().palette.color(token))


class VoiceOverlay(QWidget):
    def __init__(self, position: str = "top-right", opacity: float = 0.85):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint
            | Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.position = position
        self.opacity = opacity
        self.text = "MANDIBLE // CLEAN"
        self.is_active = False
        self.is_muted = False
        self.setFixedSize(230, 38)
        look_bus().lookChanged.connect(self._on_look_changed)

        # Make clicks pass completely through the window using Win32 API
        try:
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        except Exception:
            pass

    def _on_look_changed(self):
        self.update()

    def active_color(self) -> QColor:
        """LED / border colour while a voice is live: the look's accent."""
        return _tok("accent")

    def _state_color(self) -> QColor:
        if self.is_active:
            return self.active_color()
        return _tok("status.danger") if self.is_muted else _tok("text.secondary")

    def update_status(self, text: str, is_active: bool = False, is_muted: bool = False):
        self.text = text.upper()
        self.is_active = is_active
        self.is_muted = is_muted
        font = QFont("Consolas", 9, QFont.Bold)
        fm = QFontMetrics(font)
        needed_w = max(210, min(420, fm.horizontalAdvance(self.text) + 54))
        if needed_w != self.width():
            self.setFixedSize(needed_w, 38)
        self.update()

    def reposition(self, screen=None):
        from PySide6.QtGui import QGuiApplication

        scr = screen or QGuiApplication.primaryScreen()
        if not scr:
            return
        geo = scr.availableGeometry()
        w, h = self.width(), self.height()
        margin = 20

        if self.position == "top-left":
            x, y = geo.left() + margin, geo.top() + margin
        elif self.position == "bottom-left":
            x, y = geo.left() + margin, geo.bottom() - h - margin
        elif self.position == "bottom-right":
            x, y = geo.right() - w - margin, geo.bottom() - h - margin
        else:  # top-right
            x, y = geo.right() - w - margin, geo.top() + margin

        self.move(x, y)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        live = self.is_active or self.is_muted

        # Panel background
        bg_grad = QLinearGradient(0, 0, 0, self.height())
        c_top = _tok("bg.panel")
        c_bot = _tok("bg.window")
        alpha = max(0.2, min(1.0, float(self.opacity)))
        c_top.setAlphaF(alpha)
        c_bot.setAlphaF(alpha)
        bg_grad.setColorAt(0.0, c_top)
        bg_grad.setColorAt(1.0, c_bot)
        p.setBrush(QBrush(bg_grad))

        border_col = self._state_color() if live else _tok("line.subtle")
        border_col.setAlphaF(min(1.0, alpha + 0.1))
        p.setPen(QPen(border_col, 1.4))
        p.drawRoundedRect(r, 6.0, 6.0)

        # Faceted jewel pilot LED
        cx, cy = 18.0, self.height() / 2.0
        led_r = 4.8
        p.setPen(QPen(_tok("line.strong"), 0.8))
        p.setBrush(_tok("bg.inset"))
        p.drawEllipse(QPointF(cx, cy), led_r + 1.2, led_r + 1.2)

        led = self._state_color()
        jg = QRadialGradient(QPointF(cx - 1.2, cy - 1.2), led_r)
        jg.setColorAt(0.0, _tok("text.primary" if live else "text.secondary").lighter(110))
        jg.setColorAt(0.4, led)
        jg.setColorAt(1.0, led.darker(190))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(jg))
        p.drawEllipse(QPointF(cx, cy), led_r, led_r)

        # Monospace telemetry readout
        p.setPen(_tok("text.primary" if live else "text.secondary"))
        font = QFont("Consolas", 9, QFont.Bold)
        p.setFont(font)
        p.drawText(r.adjusted(32, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        p.end()
