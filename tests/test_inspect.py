"""Layout inspection helpers (mandible.ui.inspect) on small synthetic widget trees."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QWidget

from mandible.ui import inspect as ins


def _shown(qapp, widget, w=200, h=100):
    widget.setAttribute(Qt.WA_DontShowOnScreen)
    widget.resize(w, h)
    widget.show()
    qapp.processEvents()
    return widget


def test_find_overflow_reports_child_past_parent(qapp):
    root = QWidget()
    child = QLabel("x", root)
    child.setObjectName("wide")
    child.setGeometry(150, 10, 120, 20)
    _shown(qapp, root)
    found = ins.find_overflow(root)
    assert [(o.widget, o.object_name, o.right, o.parent_right) for o in found] == [
        ("QLabel", "wide", 269, 199)]


def test_find_overflow_ignores_fitting_children_and_one_pixel_slack(qapp):
    root = QWidget()
    QLabel("a", root).setGeometry(0, 0, 200, 20)
    QLabel("b", root).setGeometry(10, 10, 191, 20)  # right edge 200: 1 px past
    _shown(qapp, root)
    assert ins.find_overflow(root) == []


def test_find_overflow_skips_scroll_area_content(qapp):
    root = QWidget()
    area = QScrollArea(root)
    area.setGeometry(0, 0, 200, 100)
    inner = QWidget()
    inner.resize(600, 50)
    QLabel("far", inner).setGeometry(500, 0, 80, 20)
    area.setWidget(inner)
    _shown(qapp, root)
    assert ins.find_overflow(root) == []


def test_find_overflow_checks_inside_list_item_widgets(qapp):
    """An item widget may extend past the view, but its children must fit inside it (a
    squeezed card whose buttons spill past its right edge is a real overflow)."""
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    root = QWidget()
    view = QListWidget(root)
    view.setGeometry(0, 0, 200, 100)
    item = QListWidgetItem()
    item.setSizeHint(QSize(1, 40))
    view.addItem(item)
    card = QWidget()
    card.setObjectName("card")
    spill = QPushButton("spill", card)
    spill.setObjectName("spill")
    view.setItemWidget(item, card)
    _shown(qapp, root)
    spill.setGeometry(card.width() - 10, 0, 60, 20)
    found = ins.find_overflow(root)
    assert [(o.widget, o.object_name) for o in found] == [("QPushButton", "spill")]


def test_find_clipped_text_flags_narrow_label_and_honours_tooltip(qapp):
    root = QWidget()
    narrow = QLabel("A rather long caption", root)
    narrow.setGeometry(0, 0, 40, 20)
    covered = QLabel("Another long caption", root)
    covered.setToolTip("Another long caption")
    covered.setGeometry(0, 30, 40, 20)
    fits = QLabel("ok", root)
    fits.setGeometry(0, 60, 100, 20)
    _shown(qapp, root)
    assert ins.find_clipped_text(root) == ["QLabel 'A rather long caption'"]


def test_find_clipped_text_checks_buttons(qapp):
    root = QWidget()
    QPushButton("Wide button text", root).setGeometry(0, 0, 30, 24)
    _shown(qapp, root)
    assert len(ins.find_clipped_text(root)) == 1


def test_untiered_buttons(qapp):
    root = QWidget()
    QPushButton("plain", root)
    tiered = QPushButton("tiered", root)
    tiered.setProperty("tier", "primary")
    _shown(qapp, root)
    assert ins.untiered_buttons(root) == ["QPushButton 'plain'"]
