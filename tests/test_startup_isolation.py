"""Tests must never touch the real HKCU Run key (Mandible's launch-at-startup entry)."""
from __future__ import annotations

import importlib
import pkgutil
import sys

import mandible


def _all_mandible_modules():
    for info in pkgutil.walk_packages(mandible.__path__, "mandible."):
        if info.name in ("mandible.__main__",):
            continue
        importlib.import_module(info.name)
    return {n: m for n, m in sys.modules.items()
            if m is not None and (n == "mandible" or n.startswith("mandible."))}


def test_startup_helpers_are_fakes_everywhere(startup_registry):
    real = startup_registry.real
    leaks = [f"{name}.{fn}" for name, mod in _all_mandible_modules().items()
             for fn, func in real.items() if getattr(mod, fn, None) is func]
    assert leaks == []
    from mandible import config
    from mandible.ui.dialogs import settings

    assert settings.set_startup_enabled == startup_registry.set_startup_enabled
    assert settings.is_startup_enabled == startup_registry.is_startup_enabled
    assert config.set_startup_enabled == startup_registry.set_startup_enabled


def test_settings_apply_writes_only_the_fake(startup_registry, core):
    from mandible.ui.dialogs.settings import SettingsDialog

    startup_registry.enabled = True
    dlg = SettingsDialog(core, False, None)
    try:
        assert dlg.launch_startup.isChecked()   # read from the fake, not the registry
        dlg.launch_startup.setChecked(False)
        dlg.apply_all()
    finally:
        dlg.deleteLater()
    assert startup_registry.calls == [(False, bool(core.cfg.start_minimized))]
    assert startup_registry.enabled is False
