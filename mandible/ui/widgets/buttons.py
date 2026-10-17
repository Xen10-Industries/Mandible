"""Rack buttons."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from ..elements.base import mix
from ..look import current_look
from .base import _follow_look, look_color


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
