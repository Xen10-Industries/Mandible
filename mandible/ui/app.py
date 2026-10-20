"""Application entry point: ``main()`` (QApplication, lock file, first run) and ``apply_theme``."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from .. import branding
from .. import devices as D
from ..config import APP_DIR, Chain, load_config
from ..core import Core
from .look import Look, current_look, look_from_config, set_look
from .main_window import MainWindow
from .style import ScaleStyle


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
    if getattr(cfg, "auto_check_updates", True):
        QTimer.singleShot(2500, win.check_updates_in_background)

    rc = app.exec()
    lock.unlock()
    return rc
