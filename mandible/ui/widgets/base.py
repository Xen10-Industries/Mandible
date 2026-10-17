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


def set_style_property(widget: QWidget, name: str, value) -> None:
    """Set a dynamic property that a stylesheet rule selects on and restyle the widget."""
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
