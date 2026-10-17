"""The app's QStyle: Fusion with spacing-scale layout defaults and token-drawn indicators.

``apply_theme`` installs ``ScaleStyle`` once. The stylesheet (``stylesheet.build_qss``) sits on
top of it and delegates what it does not style: default layout metrics and the check-box /
radio-button indicators, which are drawn here from the current look's palette tokens (a QSS
``::indicator`` rule would drop the check glyph unless an image file were shipped).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QProxyStyle, QStyle

from .look import current_look, space

__all__ = ["ScaleStyle", "INDICATOR_TOKENS"]

# Indicator colours (tokens): the unchecked outline must reach 3:1 on every surface a check
# box sits on (bg.window / panel / raised / inset); line.strong only guarantees bg.panel.
INDICATOR_TOKENS = {
    "border": "text.secondary",      # unchecked outline
    "fill": "bg.inset",              # unchecked well
    "hover": "accent.hover",         # outline (unchecked) / fill (checked) under the mouse
    "on": "accent",                  # checked fill and outline
    "mark": "text.on_accent",        # check mark / radio dot on the accent
    "focus": "focus.ring",           # keyboard focus outline
    "disabled": "text.disabled",     # outline and mark while disabled
    "disabled_fill": "bg.panel",
}


class ScaleStyle(QProxyStyle):
    """Fusion whose default layout margins and spacing come from the spacing scale (spec
    7.7): a layout that sets neither gets ``space(3)`` margins in a window (dialogs),
    ``space(2)`` inside child widgets (tab pages, group boxes) and ``space(2)`` spacing,
    instead of Fusion's 11 / 9 px margins and 6 px spacing. Read live, so a density change
    reaches every default layout.

    Check boxes (also item-view checks) and radio buttons are drawn from palette tokens with
    every state: unchecked outline, hover, checked (accent fill and mark), partial, focus
    and disabled."""

    _MARGINS = frozenset({QStyle.PM_LayoutLeftMargin, QStyle.PM_LayoutTopMargin,
                          QStyle.PM_LayoutRightMargin, QStyle.PM_LayoutBottomMargin})
    _SPACING = frozenset({QStyle.PM_LayoutHorizontalSpacing, QStyle.PM_LayoutVerticalSpacing})
    _CHECKS = frozenset({QStyle.PE_IndicatorCheckBox, QStyle.PE_IndicatorItemViewItemCheck})

    def pixelMetric(self, metric, option=None, widget=None):  # noqa: N802
        if metric in self._MARGINS:
            return space(3) if widget is not None and widget.isWindow() else space(2)
        if metric in self._SPACING:
            return space(2)
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):  # noqa: N802
        if element in self._CHECKS:
            _draw_indicator(painter, option, radio=False)
        elif element == QStyle.PE_IndicatorRadioButton:
            _draw_indicator(painter, option, radio=True)
        elif element in (QStyle.PE_IndicatorSpinUp, QStyle.PE_IndicatorSpinDown):
            _draw_spin_arrow(painter, option, up=element == QStyle.PE_IndicatorSpinUp)
        else:
            super().drawPrimitive(element, option, painter, widget)


def _draw_spin_arrow(painter, option, up: bool) -> None:
    """Spin-box step arrows: a small chevron in text.secondary (text.disabled while disabled).
    Under the stylesheet, Fusion's own arrows came out invisible on the inset field."""
    pal = current_look().palette
    enabled = bool(option.state & QStyle.State_Enabled)
    color = QColor(pal.color("text.secondary" if enabled else "text.disabled"))
    r = QRectF(option.rect)
    half_w = min(4.0, max(2.0, (r.width() - 4.0) / 2.0))
    half_h = half_w / 2.0
    cx, cy = r.center().x(), r.center().y()
    dy = -half_h if up else half_h
    path = QPainterPath(QPointF(cx - half_w, cy - dy))
    path.lineTo(QPointF(cx, cy + dy))
    path.lineTo(QPointF(cx + half_w, cy - dy))
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()


def _colors(state) -> tuple[QColor, QColor, QColor | None, float]:
    """(outline, fill, mark or None, outline width) for a ``QStyle.State``."""
    pal = current_look().palette

    def c(role: str) -> QColor:
        return QColor(pal.color(INDICATOR_TOKENS[role]))

    enabled = bool(state & QStyle.State_Enabled)
    checked = bool(state & (QStyle.State_On | QStyle.State_NoChange))
    hover = bool(state & QStyle.State_MouseOver)
    if not enabled:
        return c("disabled"), c("disabled_fill"), (c("disabled") if checked else None), 1.0
    if checked:
        fill = c("hover") if hover else c("on")
        outline, mark = fill, c("mark")
    else:
        outline, fill, mark = (c("hover") if hover else c("border")), c("fill"), None
    width = 1.0
    if state & QStyle.State_HasFocus:
        outline, width = c("focus"), 2.0
    return outline, fill, mark, width


def _draw_indicator(p, option, radio: bool) -> None:
    r = QRectF(option.rect)
    side = min(r.width(), r.height())
    box = QRectF(r.center().x() - side / 2.0, r.center().y() - side / 2.0, side, side)
    outline, fill, mark, width = _colors(option.state)
    radius = 0.0 if radio else min(3.0, float(current_look().skin.shape.get("radius.control", 3)))
    inner = box.adjusted(width / 2.0, width / 2.0, -width / 2.0, -width / 2.0)
    p.save()
    try:
        p.setRenderHint(p.RenderHint.Antialiasing)
        p.setPen(QPen(outline, width))
        p.setBrush(fill)
        if radio:
            p.drawEllipse(inner)
        else:
            p.drawRoundedRect(inner, radius, radius)
        if mark is None:
            return
        if radio:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mark)
            d = side * 0.36
            p.drawEllipse(QRectF(box.center().x() - d / 2.0, box.center().y() - d / 2.0, d, d))
            return
        pen = QPen(mark, max(1.6, side * 0.14), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        x, y, s = box.left(), box.top(), side
        if option.state & QStyle.State_NoChange:          # partially checked: a dash
            p.drawLine(QPointF(x + s * 0.27, y + s * 0.5), QPointF(x + s * 0.73, y + s * 0.5))
        else:                                             # checked: a tick
            path = QPainterPath(QPointF(x + s * 0.24, y + s * 0.52))
            path.lineTo(QPointF(x + s * 0.43, y + s * 0.71))
            path.lineTo(QPointF(x + s * 0.77, y + s * 0.31))
            p.drawPath(path)
    finally:
        p.restore()
