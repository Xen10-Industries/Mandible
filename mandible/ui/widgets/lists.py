"""List widgets whose item widgets (cards) always span the viewport."""
from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QListWidget


class CardListWidget(QListWidget):
    """A QListWidget of card item widgets that track the viewport width in both directions.

    QListView only widens item rects when its viewport grows; when it shrinks, the rects (and
    so the cards placed on them) keep their old width until the next full item layout, which
    left plugin cards poking past the rack's right edge after the window shrank (Task 9b).
    ``ResizeMode.Adjust`` only schedules that layout on a 100 ms timer. Here a viewport width
    change re-lays the items out at once.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._laid_out_width = -1

    def viewportEvent(self, event) -> bool:  # noqa: N802 - Qt naming
        handled = super().viewportEvent(event)
        if event.type() == QEvent.Type.Resize:
            width = self.viewport().width()
            if width != self._laid_out_width:
                self._laid_out_width = width
                self.doItemsLayout()
        return handled
