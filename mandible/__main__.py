"""Entry point: ``python -m mandible``."""
import ctypes
import datetime
import os
import sys
import traceback

os.environ.setdefault("SD_ENABLE_ASIO", "1")


def _setup_logging():
    """Ensure stdout/stderr and unhandled exceptions are safely logged when running as a windowless .exe."""
    from mandible.paths import APP_DIR, LOG_PATH, migrate_legacy_data
    migrate_legacy_data()
    os.makedirs(APP_DIR, exist_ok=True)
    log_path = LOG_PATH

    # Rotate log if > 2 MB
    try:
        if os.path.isfile(log_path) and os.path.getsize(log_path) > 2 * 1024 * 1024:
            os.replace(log_path, log_path + ".old")
    except OSError:
        pass

    # In frozen --noconsole builds, sys.stdout and sys.stderr are None
    if sys.stdout is None or sys.stderr is None:
        try:
            log_fh = open(log_path, "a", encoding="utf-8", buffering=1)
            if sys.stdout is None:
                sys.stdout = log_fh
            if sys.stderr is None:
                sys.stderr = log_fh
        except Exception:
            pass

    orig_hook = sys.excepthook

    def _exc_hook(exc_type, exc_value, exc_tb):
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- [{datetime.datetime.now().isoformat()}] Unhandled Exception ---\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=fh)
        except Exception:
            pass
        if orig_hook and sys.stderr is not None:
            orig_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _exc_hook


def _tune_process():
    # Shorter GIL switch interval -> the audio callback waits less for the UI thread.
    sys.setswitchinterval(0.001)
    try:
        ABOVE_NORMAL_PRIORITY_CLASS = 0x8000
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), ABOVE_NORMAL_PRIORITY_CLASS)
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass
    try:  # own taskbar identity (icon grouping)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Xen10.Mandible")
    except Exception:
        pass


def _migrate_startup_entry():
    """Swap a leftover 'VoiceFX' Windows startup entry for a 'Mandible' one."""
    from mandible import config, paths
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, config.STARTUP_REG_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, "VoiceFX")
    except (OSError, ImportError):
        return
    paths.migrate_legacy_startup_entry()
    cfg = config.load_config()
    if cfg.launch_at_startup:
        config.set_startup_enabled(True, cfg.start_minimized)


def main():
    _setup_logging()
    _tune_process()
    _migrate_startup_entry()
    from mandible.ui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())

