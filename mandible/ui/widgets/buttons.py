"""Buttons in tiers and status pills (spec 7.7).

Every push button in the app comes from ``make_button`` (or is given a tier with
``set_tier``): the stylesheet styles it by its ``tier`` property, so every tier shows the same
hover / pressed / focus / disabled / checked states in every skin. Buttons carry no object
name rules of their own; an ID rule would out-rank the tier's state rules.

* ``primary``   filled accent; at most one per view (a top-level window or dock panel)
* ``secondary`` outlined
* ``quiet``     borderless until hover: row tools (move, remove, map, open UI)
* ``danger``    ``status.danger`` (Panic, Delete)

A ``state`` property (``on`` / ``warn`` / ``danger``) tints a secondary or quiet button with
a status colour (live, recording, a flow step that is on). Status that is not clickable uses
``StatusPill``: a different shape and no hover, so it never looks like a button.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QPushButton, QWidget

from ..icons import bind_button_icon
from .base import set_style_property
from .labels import ElidedLabel

TIERS = ("primary", "secondary", "quiet", "danger")
BUTTON_STATES = ("", "on", "warn", "danger")
PILL_STATES = ("off", "on", "warn", "danger")
ICON_BUTTON_PX = 26   # square icon-only buttons (icons and meters may have fixed sizes)


def set_tier(button: QPushButton, tier: str) -> QPushButton:
    """Give an existing button a tier (restyles it if it is already polished)."""
    if tier not in TIERS:
        raise ValueError(f"unknown button tier {tier!r} (expected one of {', '.join(TIERS)})")
    if button.property("tier") != tier:
        set_style_property(button, "tier", tier)
    return button


def set_button_state(button: QPushButton, state: str) -> None:
    """Status tint for a button: ``""`` (none), ``on``, ``warn`` or ``danger``. The icon
    follows the state's colour."""
    if state not in BUTTON_STATES:
        raise ValueError(f"unknown button state {state!r}")
    if (button.property("state") or "") == state:
        return
    set_style_property(button, "state", state)
    name = button.property("iconName")
    if name:
        bind_button_icon(button, name)


def set_button_icon(button: QPushButton, name: str | None) -> None:
    """Change a button's icon (kept in the look's colours for its tier and state)."""
    bind_button_icon(button, name)


def make_button(text: str = "", tier: str = "secondary", icon: str | None = None,
                tooltip: str = "", parent: QWidget | None = None) -> QPushButton:
    """A push button of ``tier`` with optional ``icon`` (a name from ``ui.icons``).

    Raises ``ValueError`` for an unknown tier, and for an icon-only button without a
    tooltip (the tooltip is its only label). Icon-only buttons are square and fixed-size.
    """
    if tier not in TIERS:
        raise ValueError(f"unknown button tier {tier!r} (expected one of {', '.join(TIERS)})")
    if icon and not text and not tooltip:
        raise ValueError(f"icon-only button {icon!r} needs a tooltip")
    btn = QPushButton(text, parent)
    btn.setProperty("tier", tier)
    if tooltip:
        btn.setToolTip(tooltip)
    if icon:
        bind_button_icon(btn, icon)
        if not text:
            btn.setProperty("iconOnly", "true")
            btn.setFixedSize(ICON_BUTTON_PX, ICON_BUTTON_PX)
            btn.setAccessibleName(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def tier_button_box(box: QDialogButtonBox) -> QDialogButtonBox:
    """Tier a dialog's standard buttons: the accept button (OK / Save) is primary,
    destructive ones are danger, the rest secondary."""
    primary_done = False
    for button in box.buttons():
        role = box.buttonRole(button)
        if role in (QDialogButtonBox.AcceptRole, QDialogButtonBox.YesRole) and not primary_done:
            set_tier(button, "primary")
            primary_done = True
        elif role == QDialogButtonBox.DestructiveRole:
            set_tier(button, "danger")
        else:
            set_tier(button, "secondary")
    return box


class StatusPill(ElidedLabel):
    """A status chip: ``set_state("off" | "on" | "warn" | "danger")``. Never focusable and
    styled with no hover (``QLabel#statusPill`` in the stylesheet).

    ``elide=True`` lets layouts squeeze it to ``min_chars`` characters (full text in the
    tooltip); otherwise it always shows its whole text.
    """

    def __init__(self, text: str = "", state: str = "off", parent=None, *, elide: bool = False,
                 min_chars: int = 3):
        self._elides = elide
        super().__init__(text, parent, min_chars=min_chars if elide else 10_000)
        self.setObjectName("statusPill")
        self.setFocusPolicy(Qt.NoFocus)
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("state", "off")
        self.set_state(state)

    def set_state(self, state: str) -> None:
        if state not in PILL_STATES:
            raise ValueError(f"unknown pill state {state!r} (expected one of {', '.join(PILL_STATES)})")
        if self.property("state") != state:
            set_style_property(self, "state", state)

    def state(self) -> str:
        return self.property("state")

    def _elide(self) -> None:
        if self._elides:
            super()._elide()
        elif QLabel.text(self) != self._full:
            QLabel.setText(self, self._full)
            self._sync_tooltip()
