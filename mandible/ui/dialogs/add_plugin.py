"""Pick a plugin (built-in effect or VST3) to insert into a chain."""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QStyleOptionViewItem,
                               QVBoxLayout)

from ... import plugins as P
from ...internal_dsp import is_internal_plugin
from ..icons import icon
from ..look import look_bus
from ..widgets.buttons import make_button, tier_button_box


# (label, key) for the Show filter
SOURCES = (("All plugins", "all"), ("Built-in effects", "builtin"), ("VST3 plugins", "vst3"))
_BUILTIN_ROLE = Qt.UserRole + 1
_FAVORITE_ROLE = Qt.UserRole + 2


class AddPluginDialog(QDialog):
    def __init__(self, extra_dirs, parent=None):
        super().__init__(parent)
        self.extra_dirs = extra_dirs
        self.setWindowTitle("Insert plugin")
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
        self.list.setIconSize(QSize(16, 16))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.viewport().installEventFilter(self)
        self.list.viewport().setMouseTracking(True)
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
        look_bus().lookChanged.connect(self._refresh_icons)
        self.search.setFocus()

    def _populate(self, force_rescan: bool):
        self.list.clear()
        plugins = P.get_cached_plugins(self.extra_dirs, force_rescan=force_rescan)
        # Sort favorites first, then alphabetically
        plugins.sort(key=lambda x: (not x.get("favorite", False), x["name"].lower()))
        for item in plugins:
            vendor = f"  [{item['vendor']}]" if item.get("vendor") else ""
            it = QListWidgetItem(f"{item['name']}{vendor}")
            it.setData(Qt.UserRole, item["path"])
            it.setData(_BUILTIN_ROLE, is_internal_plugin(item["path"]))
            it.setToolTip(f"{item['path']}\nClick the star or right-click to add to or remove from favorites")
            self._set_favorite_display(it, bool(item.get("favorite")))
            self.list.addItem(it)
        self._filter()

    @staticmethod
    def _set_favorite_display(it: QListWidgetItem, favorite: bool) -> None:
        it.setData(_FAVORITE_ROLE, favorite)
        it.setIcon(icon("star", "accent") if favorite else icon("star_outline", "text.disabled"))

    def _refresh_icons(self) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            self._set_favorite_display(it, bool(it.data(_FAVORITE_ROLE)))

    def toggle_favorite(self, it: QListWidgetItem) -> None:
        """Flip ``it``'s favorite flag, saved to the plugin cache. The row stays where it is;
        favorites sort to the top the next time the list is built."""
        favorite = not bool(it.data(_FAVORITE_ROLE))
        if P.set_favorite(it.data(Qt.UserRole), favorite):
            self._set_favorite_display(it, favorite)

    def _item_star_hit(self, pos: QPoint) -> QListWidgetItem | None:
        it = self.list.itemAt(pos)
        if it is None:
            return None
        opt = QStyleOptionViewItem()
        self.list.initViewItemOption(opt)
        opt.rect = self.list.visualItemRect(it)
        opt.features |= QStyleOptionViewItem.HasDecoration
        icon_rect = self.list.style().subElementRect(
            self.list.style().SubElement.SE_ItemViewItemDecoration, opt, self.list
        )
        hit_rect = icon_rect.adjusted(-4, -4, 4, 4)
        return it if hit_rect.contains(pos) else None

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 - Qt naming
        if obj is self.list.viewport():
            if ev.type() == QEvent.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                pos = ev.position().toPoint()
                it = self._item_star_hit(pos)
                if it is not None:
                    self.toggle_favorite(it)
                    return True
            elif ev.type() == QEvent.MouseMove:
                pos = ev.position().toPoint()
                if self._item_star_hit(pos) is not None:
                    self.list.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    self.list.viewport().unsetCursor()
        return super().eventFilter(obj, ev)

    def _context_menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        menu = QMenu(self)
        label = ("Remove from favorites" if it.data(_FAVORITE_ROLE) else "Add to favorites")
        menu.addAction(icon("star", "text.primary"), label, lambda: self.toggle_favorite(it))
        menu.exec(self.list.viewport().mapToGlobal(pos))

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
