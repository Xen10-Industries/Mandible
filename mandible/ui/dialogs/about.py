"""About / Licenses dialog: shows Mandible's license and the bundled third-party notices."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QTabWidget,
                               QVBoxLayout, QWidget)

from ... import APP_NAME, PUBLISHER, __version__
from ...config import resource_path
from ..look import font_px
from ..widgets.buttons import tier_button_box
from .parts import keep_wrapped_text_visible

TRADEMARK_NOTICE = "VST is a trademark of Steinberg Media Technologies GmbH, registered in Europe and other countries."


def _read_text(name: str) -> str:
    path = resource_path(name)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return f"{name} could not be found next to the application ({path})."


def _text_tab(text: str) -> QWidget:
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setPlainText(text)
    view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    font = QFont("Consolas")
    font.setPixelSize(font_px("body"))
    view.setFont(font)
    return view


class AboutDialog(QDialog):
    def __init__(self, parent=None, start_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(480)
        self.resize(760, 560)
        lay = QVBoxLayout(self)

        header = QLabel(
            f"<b>{APP_NAME}</b> {__version__}<br>"
            f"© {PUBLISHER}<br>"
            "Free and open-source software, licensed under the GNU General Public License v3.0 or later.<br>"
            "Hosts VST3 plugins."
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setWordWrap(True)
        lay.addWidget(header)
        notice = QLabel(TRADEMARK_NOTICE)
        notice.setObjectName("hint")
        notice.setWordWrap(True)
        lay.addWidget(notice)

        tabs = QTabWidget()
        tabs.addTab(_text_tab(_read_text("LICENSE")), "License (GPL-3.0-or-later)")
        tabs.addTab(_text_tab(_read_text("THIRD_PARTY_NOTICES.txt")), "Third-party notices")
        tabs.setCurrentIndex(start_tab)
        lay.addWidget(tabs, 1)

        buttons = tier_button_box(QDialogButtonBox(QDialogButtonBox.StandardButton.Close))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        keep_wrapped_text_visible(self)
