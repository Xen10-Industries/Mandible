"""Building blocks shared by the dialogs: section label rows, check boxes with a muted hint,
the hint label itself (Settings and Mic cleanup lay their pages out with these) and a guard
that keeps wrapped text from being clipped when a dialog is made small."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QCheckBox, QFormLayout, QLabel, QStyle, QWidget

from ..look import space


def hint_label(text: str, indent: bool = False) -> QLabel:
    """A muted, word-wrapped explanation (``QLabel#hint``). ``indent`` lines it up with a
    check box's label above it."""
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    if indent:
        style = QApplication.style()
        label.setIndent(style.pixelMetric(QStyle.PM_IndicatorWidth)
                        + style.pixelMetric(QStyle.PM_CheckBoxLabelSpacing))
    return label


def _add_row(layout, widget) -> None:
    """Append ``widget`` as a row of a form layout or a vertical box layout."""
    if isinstance(layout, QFormLayout):
        layout.addRow(widget)
    else:
        layout.addWidget(widget)


def group_label(layout, text: str) -> QLabel:
    """A section label row (uppercase, spaced): the only place small caps are used. ``layout``
    is a form layout or a vertical box layout."""
    label = QLabel(text.upper())
    label.setObjectName("settingsGroupLabel")
    count = layout.rowCount() if isinstance(layout, QFormLayout) else layout.count()
    if count:                    # air between a group and whatever precedes it
        label.setContentsMargins(0, space(3), 0, 0)
    _add_row(layout, label)
    return label


def check_row(layout, text: str, checked: bool = False, hint: str = "") -> QCheckBox:
    """A check box on a row of its own, with an optional muted explanation under it."""
    box = QCheckBox(text)
    box.setChecked(checked)
    _add_row(layout, box)
    if hint:
        _add_row(layout, hint_label(hint, indent=True))
    return box


class _WrapGuard(QObject):
    """Keeps a dialog at least as tall as its word-wrapped text needs at the dialog's width.

    Qt sizes a window's minimum from the layouts alone, so a dialog with wrapped labels can be
    dragged shorter than its text at the narrower width it is being dragged to. On every
    resize / show / layout change the minimum height is set to what the layout needs at the
    current width (never below the layout's own minimum)."""

    _EVENTS = (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest)

    def __init__(self, dialog: QWidget):
        super().__init__(dialog)
        self._dialog = dialog
        dialog.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt naming
        dialog = self.__dict__.get("_dialog")      # absent while the dialog is being torn down
        if dialog is not None and obj is dialog and event.type() in self._EVENTS:
            self._update()
        return False

    def _update(self) -> None:
        layout = self._dialog.layout()
        if layout is None or not layout.hasHeightForWidth():
            return
        need = max(layout.totalMinimumSize().height(),
                   layout.minimumHeightForWidth(self._dialog.width()))
        if need != self._dialog.minimumHeight():
            self._dialog.setMinimumHeight(need)


def keep_wrapped_text_visible(dialog: QWidget) -> None:
    """Install the minimum-height guard on ``dialog`` (see ``_WrapGuard``)."""
    dialog._wrap_guard = _WrapGuard(dialog)    # the Python wrapper must outlive this call
