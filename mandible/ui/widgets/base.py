"""Helpers shared by the custom widgets."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from ..elements import registry as _registry
from ..look import Look, current_look, look_bus


@lru_cache(maxsize=16)
def _resolved_elements(look: Look) -> dict[str, str]:
    return _registry.resolve(look.skin.elements)[0]


def look_element(slot: str, preset: str | None = None, **ctor):
    """The current skin's element for ``slot``: ``cls.<preset>()`` or ``cls(**ctor)``."""
    cls = _registry.get(slot, _resolved_elements(current_look())[slot])
    return getattr(cls, preset)() if preset else cls(**ctor)


def look_color(token: str) -> QColor:
    """A palette token of the current look as a QColor."""
    return QColor(current_look().palette.color(token))


def _follow_look(widget: QWidget) -> None:
    """Call ``widget._on_look_changed`` (default: repaint) whenever the look changes.

    The connection goes away with the widget (the slot is a method of the QObject).
    """
    look_bus().lookChanged.connect(widget._on_look_changed)


class SpacedLayouts:
    """Layouts whose spacing and margins are spacing-scale steps (``look.space``: 1..5 ->
    4/8/12/16/24 px, 0 = none), re-applied when the look (and so the density) changes.

    The owning widget calls ``apply()`` from its ``_on_look_changed``.
    """

    def __init__(self):
        self._items: list[tuple] = []

    def add(self, layout, spacing: int | None = None, margins=None):
        if isinstance(margins, int):
            margins = (margins,) * 4
        self._items.append((layout, spacing, margins))
        self._apply_one(layout, spacing, margins)
        return layout

    @staticmethod
    def _apply_one(layout, spacing, margins) -> None:
        from ..look import space

        if spacing is not None:
            layout.setSpacing(space(spacing) if spacing else 0)
        if margins is not None:
            layout.setContentsMargins(*(space(m) if m else 0 for m in margins))

    def apply(self) -> None:
        for item in self._items:
            try:
                self._apply_one(*item)
            except RuntimeError:  # layout already deleted with its widget
                pass


def reserve_text_width(widget, *samples: str) -> None:
    """Give a label/button a minimum width that fits any of ``samples`` (its texts over time),
    so changing text never shifts the layout around it."""
    widget.ensurePolished()
    current = widget.text()
    widest = 0
    for text in (current, *samples):
        widget.setText(text)
        widest = max(widest, widget.sizeHint().width())
    widget.setText(current)
    widget.setMinimumWidth(widest)


def set_style_property(widget: QWidget, name: str, value) -> None:
    """Set a dynamic property that a stylesheet rule selects on and restyle the widget."""
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
