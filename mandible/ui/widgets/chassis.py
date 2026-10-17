"""Outer chassis frame and rack screws."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QWidget

from ..elements.base import ElementState
from ..look import current_look
from .base import _follow_look, look_element


class _FrameOutline(QWidget):
    """Mouse-transparent layer over the chassis content that strokes the frame's outline
    (frames with ``overlay_outline``, whose content sits flush against the edge)."""

    def __init__(self, chassis: "ChassisWrapperFrame"):
        super().__init__(chassis)
        self.setObjectName("frameOutline")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chassis = chassis

    def paintEvent(self, _):
        element = self._chassis.element()
        if not getattr(element, "overlay_outline", False):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        element.outline(p, float(self.width()), float(self.height()), current_look())
        p.end()


class ChassisWrapperFrame(QFrame):
    """Full-window outer chassis; the skin's ``frame`` element paints it and sets the margins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rackChassis")
        self._outline = _FrameOutline(self)
        self._sync_outline()
        _follow_look(self)

    def element(self):
        return look_element("frame")

    def update_frame_margins(self):
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(*self.element().content_margins(current_look()))

    def _sync_outline(self):
        """Show the outline layer only for frames that need it, over the whole chassis and on
        top of every other child."""
        outline = getattr(self, "_outline", None)
        if outline is None:
            return
        outline.setGeometry(self.rect())
        outline.setVisible(bool(getattr(self.element(), "overlay_outline", False)))
        outline.raise_()
        outline.update()

    def _on_look_changed(self):
        self.update_frame_margins()
        self._sync_outline()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_outline()

    def childEvent(self, event):
        super().childEvent(event)
        if event.type() == QEvent.Type.ChildAdded and event.child() is not getattr(self, "_outline", None):
            outline = getattr(self, "_outline", None)
            if outline is not None:
                outline.raise_()

    def paintEvent(self, _):
        p = QPainter(self)
        self.element().paint(p, QRectF(0, 0, self.width(), self.height()), ElementState(), current_look())
        p.end()


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
