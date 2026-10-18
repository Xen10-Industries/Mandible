"""Labels that shrink gracefully."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy

from ..look import look_bus


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
        # Re-elide once per look switch (the new stylesheet's fonts are in place by then) rather
        # than on each of the dozens of Font/Style change events a switch delivers to a label.
        look_bus().lookChanged.connect(self._elide)

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
        # A look switch delivers several Font/Style changes per label, alternating between fonts;
        # the elided text for a (text, width, font) is remembered, so only new ones are measured.
        key = (self._full, avail, self.font().toString())
        memo = self.__dict__.setdefault("_elide_memo", {})
        shown = memo.get(key)
        if shown is None:
            shown = self._full
            fm = self.fontMetrics()
            if self._full and avail > 0 and fm.horizontalAdvance(self._full) > avail:
                shown = fm.elidedText(self._full, self._mode, avail)
                # elidedText ignores the font's letter spacing (section labels use it): narrow
                # the target until the elided text really fits.
                target = avail
                while shown and fm.horizontalAdvance(shown) > avail and target > 0:
                    target -= max(1, int(fm.horizontalAdvance(shown) - avail))
                    shown = fm.elidedText(self._full, self._mode, max(0, target))
            if len(memo) >= 8:
                memo.clear()
            memo[key] = shown
        if QLabel.text(self) != shown:
            QLabel.setText(self, shown)
            self._sync_tooltip()
        elif self.__dict__.get("_tip_for") != (self._full, self._base_tip, shown):
            self._sync_tooltip()

    def _sync_tooltip(self) -> None:
        if self.is_elided():
            tip = self._full + (f"\n{self._base_tip}" if self._base_tip else "")
        else:
            tip = self._base_tip
        if self.toolTip() != tip:
            self.setToolTip(tip)
        self.__dict__["_tip_for"] = (self._full, self._base_tip, QLabel.text(self))

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

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._elide()             # first polish (stylesheet font) happens just before showing

    def setFont(self, font) -> None:  # noqa: N802
        super().setFont(font)
        self._elide()
