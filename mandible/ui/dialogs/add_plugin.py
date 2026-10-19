"""Pick a VST3 plugin to add to a chain."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout)

from ... import plugins as P
from ...internal_dsp import is_internal_plugin
from ..widgets.buttons import make_button, tier_button_box


# (label, key) for the Show filter
SOURCES = (("All plugins", "all"), ("Built-in effects", "builtin"), ("VST3 plugins", "vst3"))
_BUILTIN_ROLE = Qt.UserRole + 1


class AddPluginDialog(QDialog):
    def __init__(self, extra_dirs, parent=None):
        super().__init__(parent)
        self.extra_dirs = extra_dirs
        self.setWindowTitle("Add VST3 plugin")
        self.resize(520, 560)
        self.path = ""
        lay = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search plugins by name or vendor…")
        self.search.setClearButtonEnabled(True)
        self.source = QComboBox()
        self.source.setAccessibleName("Show")
        self.source.setToolTip("Show all plugins, only Mandible's built-in effects, or only VST3 plugins")
        for label, key in SOURCES:
            self.source.addItem(label, key)
        rescan_btn = make_button("Rescan")
        rescan_btn.setToolTip("Rescan system folders for newly installed VST3 plugins")
        top_row.addWidget(self.search, 1)
        top_row.addWidget(self.source)
        top_row.addWidget(rescan_btn)
        lay.addLayout(top_row)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        browse = make_button("Browse for .vst3…")
        row.addWidget(browse)
        row.addStretch()
        bb = tier_button_box(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
        row.addWidget(bb)
        lay.addLayout(row)

        self._populate(force_rescan=False)
        self.search.textChanged.connect(self._filter)
        self.source.currentIndexChanged.connect(lambda _: self._filter())
        self.list.itemDoubleClicked.connect(lambda _: self._ok())
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        browse.clicked.connect(self._browse)
        rescan_btn.clicked.connect(lambda: self._populate(force_rescan=True))
        self.search.setFocus()

    def _populate(self, force_rescan: bool):
        self.list.clear()
        plugins = P.get_cached_plugins(self.extra_dirs, force_rescan=force_rescan)
        # Sort favorites first, then alphabetically
        plugins.sort(key=lambda x: (not x.get("favorite", False), x["name"].lower()))
        for item in plugins:
            vendor = f"  [{item['vendor']}]" if item.get("vendor") else ""
            fav = "[FAV] " if item.get("favorite") else ""
            text = f"{fav}{item['name']}{vendor}"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, item["path"])
            it.setData(_BUILTIN_ROLE, is_internal_plugin(item["path"]))
            it.setToolTip(f"{item['path']}\nRight-click to toggle Favorite")
            self.list.addItem(it)
        self._filter()

    def show_source(self, key: str) -> None:
        """Select the Show filter by key (``all``, ``builtin`` or ``vst3``)."""
        self.source.setCurrentIndex(max(0, self.source.findData(key)))

    def _filter(self, _text: str | None = None):
        t = self.search.text().lower()
        source = self.source.currentData()
        for i in range(self.list.count()):
            it = self.list.item(i)
            builtin = bool(it.data(_BUILTIN_ROLE))
            wrong_source = (source == "builtin" and not builtin) or (source == "vst3" and builtin)
            it.setHidden(wrong_source or t not in it.text().lower())

    def _ok(self):
        it = self.list.currentItem()
        if it is None or it.isHidden():
            return
        self.path = it.data(Qt.UserRole)
        self.accept()

    def _browse(self):
        start = P.default_vst3_dirs()[0] if P.default_vst3_dirs() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Choose VST3 plugin", start, "VST3 plugins (*.vst3)")
        if path:
            self.path = os.path.normpath(path)
            self.accept()
