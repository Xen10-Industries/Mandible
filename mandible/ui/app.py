"""Application entry point: ``main()`` (QApplication, lock file, first run) and ``apply_theme``."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QProxyStyle, QStyle

from .. import branding
from .. import devices as D
from ..config import APP_DIR, Chain, load_config
from ..core import Core
from .look import Look, current_look, look_from_config, set_look, space
from .main_window import MainWindow


class ScaleStyle(QProxyStyle):
    """Fusion whose default layout margins and spacing come from the spacing scale (spec
    7.7): a layout that sets neither gets ``space(3)`` margins in a window (dialogs),
    ``space(2)`` inside child widgets (tab pages, group boxes) and ``space(2)`` spacing,
    instead of Fusion's 11 / 9 px margins and 6 px spacing. Read live, so a density change
    reaches every default layout."""

    _MARGINS = frozenset({QStyle.PM_LayoutLeftMargin, QStyle.PM_LayoutTopMargin,
                          QStyle.PM_LayoutRightMargin, QStyle.PM_LayoutBottomMargin})
    _SPACING = frozenset({QStyle.PM_LayoutHorizontalSpacing, QStyle.PM_LayoutVerticalSpacing})

    def pixelMetric(self, metric, option=None, widget=None):  # noqa: N802
        if metric in self._MARGINS:
            return space(3) if widget is not None and widget.isWindow() else space(2)
        if metric in self._SPACING:
            return space(2)
        return super().pixelMetric(metric, option, widget)


_STYLE_PROPERTY = "mandibleScaleStyle"


def apply_theme(app: QApplication, look: Look | None = None) -> None:
    """Fusion (as ``ScaleStyle``) and the app icon, then ``set_look`` (stylesheet, native
    palette, ``lookChanged``). The style is installed once; later calls only switch the look."""
    if not app.property(_STYLE_PROPERTY):
        app.setStyle(ScaleStyle("Fusion"))
        app.setProperty(_STYLE_PROPERTY, True)
    app.setWindowIcon(branding.app_icon())
    set_look(look or current_look(), app)


# =============================================================== app entry point
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Mandible")
    app.setQuitOnLastWindowClosed(False)

    os.makedirs(APP_DIR, exist_ok=True)
    lock = QLockFile(os.path.join(APP_DIR, "mandible.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.information(None, "Mandible", "Mandible is already running (check the system tray).")
        return 0

    cfg = load_config()
    apply_theme(app, look_from_config(cfg))

    first_run = not cfg.audio.driver
    if first_run:
        cfg.audio = D.guess_focusrite_setup()
    if not cfg.chains:
        cfg.chains.append(Chain(name="My first voice"))

    core = Core(cfg)

    start_minimized = bool(cfg.start_minimized or ("--minimized" in sys.argv))

    n_plugins = sum(len(c.plugins) for c in cfg.chains)
    prog = None
    if n_plugins and not start_minimized:
        prog = QProgressDialog("Loading plugins…", None, 0, n_plugins)
        prog.setWindowTitle("Mandible")
        prog.setWindowIcon(branding.app_icon())
        prog.setMinimumDuration(300)

    def progress(n, total, name):
        if prog:
            prog.setValue(n)
            prog.setLabelText(f"Loading {name}…")
            QApplication.processEvents()

    core.load_all(progress)
    if prog:
        prog.close()

    win = MainWindow(core)
    if cfg.autostart_audio:
        win.start_audio()
    if not start_minimized:
        win.show()
    if first_run:
        core.save_now()
        win.show()
        QTimer.singleShot(300, win._open_setup_assistant)

    rc = app.exec()
    lock.unlock()
    return rc
