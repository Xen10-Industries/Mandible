"""Layout inspection helpers: overflowing children, clipped text, untiered buttons, off-scale
layout spacing, unnamed icon-only controls and small painted text.

Used by ``tools/ui_gallery.py``, ``tools/layout_probe.py`` and the layout / skin tests. All
functions are read-only and expect the widget tree to be shown (``isVisible()``) and laid out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox, QCheckBox,
    QComboBox, QFormLayout, QGridLayout, QLabel, QLayout, QLineEdit, QPushButton, QRadioButton,
    QScrollBar, QStackedLayout, QStyle, QTabBar, QToolBar, QToolButton, QWidget,
)

__all__ = ["Overflow", "find_overflow", "find_clipped_text", "untiered_buttons",
           "SPACING_SCALE", "COMPACT_SPACING_SCALE", "off_scale_spacing",
           "unnamed_icon_controls", "painted_text_sizes", "MIN_TEXT_PX"]

# Layout spacing and margins may only use the spacing scale (spec 7.7), plus 0.
SPACING_SCALE = frozenset({0, 4, 8, 12, 16, 24})
COMPACT_SPACING_SCALE = frozenset({0, 4, 8, 12, 16})
MIN_TEXT_PX = 10   # nothing below 10 px (spec 7.7)

# Qt's own sub-widgets (tab-bar scroll arrows, line-edit clear buttons, spin-box and combo-box
# internals) live inside these; they are not the app's controls.
_QT_INTERNAL_PARENTS = (QTabBar, QLineEdit, QAbstractSpinBox, QComboBox, QScrollBar, QToolBar)

_TAG_RE = re.compile(r"<[^>]*>")


@dataclass
class Overflow:
    widget: str
    object_name: str
    right: int
    parent_right: int


def _scrollable_content(w: QWidget) -> bool:
    """True when ``w`` is the content of a scroll area or item view: a direct child of its
    viewport (scroll-area content, item widgets) or of the view itself.

    Only that content root may extend past its parent; the widgets inside it are still
    checked against the content root, so a squeezed item widget whose children spill out
    of it is reported.
    """
    parent = w.parentWidget()
    if parent is None:
        return False
    if isinstance(parent, QAbstractItemView):
        return True
    view = parent.parentWidget()
    return isinstance(view, QAbstractScrollArea) and view.viewport() is parent


def _describe(w: QWidget) -> str:
    name = w.objectName()
    text = ""
    if isinstance(w, (QLabel, QAbstractButton)):
        text = w.text().replace("\n", " ")[:40]
    parts = [type(w).__name__]
    if name:
        parts.append(f"#{name}")
    if text:
        parts.append(f"'{text}'")
    return " ".join(parts)


def _visible_widgets(root: QWidget):
    for w in root.findChildren(QWidget):
        if w.isVisible() and w.width() > 0 and w.height() > 0:
            yield w


def find_overflow(root: QWidget) -> list[Overflow]:
    """Visible children whose geometry extends past their parent's rect by more than 1 px.

    The content roots of scroll areas and item views (direct children of a viewport) are
    skipped, since they legitimately exceed the visible rect; their own children are not.
    Zero-size widgets are skipped.
    """
    found: list[Overflow] = []
    for w in _visible_widgets(root):
        parent = w.parentWidget()
        if parent is None or not parent.isVisible() or _scrollable_content(w):
            continue
        geo, rect = w.geometry(), parent.rect()
        if geo.right() > rect.right() + 1 or geo.bottom() > rect.bottom() + 1:
            found.append(Overflow(type(w).__name__, w.objectName(), geo.right(), rect.right()))
    return found


def _plain_text(w: QLabel | QAbstractButton) -> str:
    text = w.text()
    if isinstance(w, QLabel):
        if w.textFormat() == Qt.RichText or (w.textFormat() == Qt.AutoText and "<" in text):
            text = _TAG_RE.sub("", text)
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def find_clipped_text(root: QWidget) -> list[str]:
    """Labels/buttons whose text is wider than their content area and not covered by a tooltip."""
    clipped: list[str] = []
    for w in _visible_widgets(root):
        if not isinstance(w, (QLabel, QAbstractButton)):
            continue
        if isinstance(w, QLabel) and (w.wordWrap() or not w.pixmap().isNull()):
            continue
        text = _plain_text(w)
        if not text.strip() or "\n" in text:
            continue
        if text in w.toolTip():
            continue
        avail = w.contentsRect().width()
        if isinstance(w, QAbstractButton):
            if isinstance(w, (QCheckBox, QRadioButton)):
                style = w.style()
                avail -= style.pixelMetric(QStyle.PM_IndicatorWidth, None, w) + style.pixelMetric(
                    QStyle.PM_CheckBoxLabelSpacing, None, w)
            if not w.icon().isNull():
                avail -= w.iconSize().width()
        if w.fontMetrics().horizontalAdvance(text) > avail:
            clipped.append(_describe(w))
    return clipped


def _own_widget(w: QWidget) -> bool:
    """False for Qt's internal sub-widgets (see ``_QT_INTERNAL_PARENTS``)."""
    parent = w.parentWidget()
    while parent is not None:
        if isinstance(parent, _QT_INTERNAL_PARENTS):
            return False
        if parent.isWindow():
            return True
        parent = parent.parentWidget()
    return True


def untiered_buttons(root: QWidget) -> list[str]:
    """QPushButtons and QToolButtons (the app's own, visible or not) with no ``tier`` property."""
    return [_describe(w) for w in root.findChildren(QAbstractButton)
            if isinstance(w, (QPushButton, QToolButton)) and _own_widget(w)
            and not w.property("tier")]


def _layout_owner(lay: QLayout) -> str:
    w = lay.parentWidget()
    if w is None:
        return type(lay).__name__
    name = f"#{w.objectName()}" if w.objectName() else ""
    return f"{type(w).__name__}{name} {type(lay).__name__}"


def off_scale_spacing(root: QWidget, allowed=SPACING_SCALE) -> list[str]:
    """Layouts (the app's own, inside ``root``) whose spacing or any contents margin is not
    in ``allowed``. A spacing of -1 (the style's per-control default) is off the scale too.
    Stacked layouts have no spacing and are skipped."""
    found: list[str] = []
    layouts = root.findChildren(QLayout)
    if root.layout() is not None and root.layout() not in layouts:
        layouts.insert(0, root.layout())
    for lay in layouts:
        # A main window's own layout places its central widget and bars; its margins are unused.
        if isinstance(lay, QStackedLayout) or lay.metaObject().className() == "QMainWindowLayout":
            continue
        owner = lay.parentWidget()
        if owner is not None and not _own_widget(owner):
            continue
        if isinstance(lay, (QGridLayout, QFormLayout)):
            gaps = {"h-spacing": lay.horizontalSpacing(), "v-spacing": lay.verticalSpacing()}
        else:
            gaps = {"spacing": lay.spacing()}
        m = lay.contentsMargins()
        gaps.update({"margin-left": m.left(), "margin-top": m.top(),
                     "margin-right": m.right(), "margin-bottom": m.bottom()})
        bad = [f"{k} {v}" for k, v in gaps.items() if v not in allowed]
        if bad:
            found.append(f"{_layout_owner(lay)}: {', '.join(bad)}")
    return found


def unnamed_icon_controls(root: QWidget) -> list[str]:
    """Icon-only buttons and pixmap-only labels (visible or not) with no accessible name:
    a screen reader has nothing to say for them."""
    found: list[str] = []
    for w in root.findChildren(QWidget):
        if not _own_widget(w):
            continue
        if isinstance(w, QAbstractButton):
            icon_only = not w.text().strip() and not w.icon().isNull()
        elif isinstance(w, QLabel):
            icon_only = not w.text().strip() and not w.pixmap().isNull()
        else:
            continue
        if icon_only and not w.accessibleName().strip():
            name = f"#{w.objectName()}" if w.objectName() else ""
            tip = f" ({w.toolTip()[:30]!r})" if w.toolTip() else ""
            found.append(f"{type(w).__name__}{name}{tip}")
    return found


def _font_px(painter: QPainter) -> float:
    f = painter.font()
    if f.pixelSize() > 0:
        return float(f.pixelSize())
    dev = painter.device()
    dpi = dev.logicalDpiY() if dev is not None else 96
    return f.pointSizeF() * dpi / 72.0


def painted_text_sizes(widget: QWidget) -> list[tuple[str, str, float]]:
    """``(painting widget class, text, pixel size)`` for every ``QPainter.drawText`` call made
    from Python while ``widget`` (and its visible children) paint once into a pixmap.

    Custom widgets and skin elements draw their text from Python, so this sees what a
    stylesheet-based check cannot: knob titles, switch labels, meter scales."""
    seen: list[tuple[str, str, float]] = []
    original = QPainter.drawText

    def recording(painter, *args):
        text = next((a for a in args if isinstance(a, str)), "")
        dev = painter.device()
        seen.append((type(dev).__name__ if dev is not None else "", text, round(_font_px(painter), 2)))
        return original(painter, *args)

    QPainter.drawText = recording
    try:
        widget.grab()
    finally:
        QPainter.drawText = original
    return seen
