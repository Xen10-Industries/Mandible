"""In-game / desktop floating HUD overlay showing active voice and mic status.
Uses Windows WS_EX_TRANSPARENT so mouse clicks pass right through to games.
"""
from __future__ import annotations

import ctypes
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

ACTIVE = "#10b981"
MUTED = "#ef4444"
CLEAN = "#64748b"


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

        # Anodized hardware chassis background
        bg_grad = QLinearGradient(0, 0, 0, self.height())
        c_top = QColor("#141923")
        c_bot = QColor("#090b10")
        alpha = max(0.2, min(1.0, float(self.opacity)))
        c_top.setAlphaF(alpha)
        c_bot.setAlphaF(alpha)
        bg_grad.setColorAt(0.0, c_top)
        bg_grad.setColorAt(1.0, c_bot)
        p.setBrush(QBrush(bg_grad))

        border_hex = ACTIVE if self.is_active else (MUTED if self.is_muted else "#262f40")
        border_col = QColor(border_hex)
        border_col.setAlphaF(min(1.0, alpha + 0.1))
        p.setPen(QPen(border_col, 1.4))
        p.drawRoundedRect(r, 6.0, 6.0)

        # Faceted jewel pilot LED
        cx, cy = 18.0, self.height() / 2.0
        led_r = 4.8
        p.setPen(QPen(QColor("#334155"), 0.8))
        p.setBrush(QColor("#07090d"))
        p.drawEllipse(QPointF(cx, cy), led_r + 1.2, led_r + 1.2)

        led_hex = ACTIVE if self.is_active else (MUTED if self.is_muted else CLEAN)
        jg = QRadialGradient(QPointF(cx - 1.2, cy - 1.2), led_r)
        jg.setColorAt(0.0, QColor("#ffffff" if (self.is_active or self.is_muted) else "#cbd5e1"))
        jg.setColorAt(0.4, QColor(led_hex))
        jg.setColorAt(1.0, QColor(led_hex).darker(190))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(jg))
        p.drawEllipse(QPointF(cx, cy), led_r, led_r)

        # Monospace telemetry readout
        txt_col = QColor("#f8fafc" if (self.is_active or self.is_muted) else "#94a3b8")
        p.setPen(txt_col)
        font = QFont("Consolas", 9, QFont.Bold)
        p.setFont(font)
        p.drawText(r.adjusted(32, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        p.end()

