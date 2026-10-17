"""Layout inspection helpers: find overflowing children, clipped text and untiered buttons.

Used by ``tools/ui_gallery.py`` and the layout tests. All functions are read-only and expect
the widget tree to be shown (``isVisible()``) and laid out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractScrollArea, QCheckBox, QLabel, QPushButton,
    QRadioButton, QStyle, QWidget,
)

__all__ = ["Overflow", "find_overflow", "find_clipped_text", "untiered_buttons"]

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


def untiered_buttons(root: QWidget) -> list[str]:
    """QPushButtons that carry no ``tier`` dynamic property."""
    return [_describe(w) for w in root.findChildren(QPushButton) if not w.property("tier")]
