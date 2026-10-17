"""Labels that shrink gracefully."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """A one-line label that elides its text to the width it gets.

    ``sizeHint`` asks for the full text; ``minimumSizeHint`` only for the first
    ``min_chars`` characters plus an ellipsis, so layouts can squeeze it. While the text is
    elided the tooltip shows the full text (followed by any tooltip set with
    ``setBaseToolTip``).
    """

    def __init__(self, text: str = "", parent=None, *, min_chars: int = 3,
                 mode: Qt.TextElideMode = Qt.ElideRight):
        super().__init__(parent)
        self._full = ""
        self._base_tip = ""
        self._min_chars = max(0, int(min_chars))
        self._mode = mode
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(text)

    # ------------------------------------------------------------------ text
    def full_text(self) -> str:
        return self._full

    def is_elided(self) -> bool:
        return QLabel.text(self) != self._full

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        text = "" if text is None else str(text)
        if text != self._full:
            self._full = text
            self.updateGeometry()
        self._elide()

    def setBaseToolTip(self, tip: str) -> None:  # noqa: N802 - Qt naming
        self._base_tip = tip or ""
        self._sync_tooltip()

    def _elide(self) -> None:
        avail = self.contentsRect().width()
        shown = self._full
        if self._full and avail > 0 and self.fontMetrics().horizontalAdvance(self._full) > avail:
            shown = self.fontMetrics().elidedText(self._full, self._mode, avail)
        if QLabel.text(self) != shown:
            QLabel.setText(self, shown)
        self._sync_tooltip()

    def _sync_tooltip(self) -> None:
        if self.is_elided():
            tip = self._full + (f"\n{self._base_tip}" if self._base_tip else "")
        else:
            tip = self._base_tip
        if self.toolTip() != tip:
            self.setToolTip(tip)

    # ---------------------------------------------------------------- sizing
    def _text_delta(self, target: str) -> int:
        fm = self.fontMetrics()
        return fm.horizontalAdvance(target) - fm.horizontalAdvance(QLabel.text(self))

    def sizeHint(self) -> QSize:  # noqa: N802
        s = super().sizeHint()
        return QSize(s.width() + self._text_delta(self._full), s.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        s = super().minimumSizeHint()
        short = self._full
        if len(short) > self._min_chars:
            short = short[:self._min_chars] + "…"
        fm = self.fontMetrics()
        if fm.horizontalAdvance(short) > fm.horizontalAdvance(self._full):
            short = self._full
        return QSize(s.width() + self._text_delta(short), s.height())

    # ---------------------------------------------------------------- events
    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._elide()

    def changeEvent(self, ev) -> None:  # noqa: N802
        super().changeEvent(ev)
        if ev.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._elide()
