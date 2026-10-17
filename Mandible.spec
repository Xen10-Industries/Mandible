# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Mandible. Release builds run only in CI (.github/workflows/release.yml).
#
# Native libraries come from third_party_build/, which CI fills by compiling them from source:
#   third_party_build/portaudio/libportaudio64bit-asio.dll   (PortAudio + ASIO SDK, GPLv3 option)
#   third_party_build/rnnoise/rnnoise.dll                     (Xiph RNNoise)
# Set MANDIBLE_RELEASE=1 to make missing source-built libraries a hard error.
import os
import re

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = os.path.abspath(SPECPATH)
RELEASE = os.environ.get("MANDIBLE_RELEASE") == "1"

# ---- version: single source of truth is mandible/_version.py
with open(os.path.join(ROOT, "mandible", "_version.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)
_nums = [int(x) for x in re.match(r"(\d+)\.(\d+)\.(\d+)", VERSION).groups()] + [0]

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=tuple(_nums), prodvers=tuple(_nums)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Xen10 Industries"),
            StringStruct("ProductName", "Mandible"),
            StringStruct("FileDescription", "Mandible"),
            StringStruct("FileVersion", VERSION),
            StringStruct("ProductVersion", VERSION),
            StringStruct("InternalName", "Mandible"),
            StringStruct("OriginalFilename", "Mandible.exe"),
            StringStruct("LegalCopyright", "Copyright (c) Xen10 Industries. Licensed under GPL-3.0-or-later."),
            StringStruct("LegalTrademarks", "VST is a trademark of Steinberg Media Technologies GmbH."),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)


def _native(rel_built, dev_fallback=None):
    built = os.path.join(ROOT, "third_party_build", rel_built)
    if os.path.isfile(built):
        return built
    if RELEASE:
        raise SystemExit(f"Release build requires source-built library: {built}")
    if dev_fallback and os.path.isfile(dev_fallback):
        print(f"WARNING: using non-release fallback {dev_fallback}")
        return dev_fallback
    return None


datas = [
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "THIRD_PARTY_NOTICES.txt"), "."),
    (os.path.join(ROOT, "Mandible.ico"), "."),
]
binaries = []
hiddenimports = [
    "mandible",
    "mandible._version",
    "mandible.api",
    "mandible.audio_engine",
    "mandible.branding",
    "mandible.config",
    "mandible.core",
    "mandible.devices",
    "mandible.factory_presets",
    "mandible.gui",
    "mandible.hotkeys",
    "mandible.internal_dsp",
    "mandible.midi",
    "mandible.overlay",
    "mandible.paths",
    "mandible.plugins",
    "mandible.prefx",
    "mandible.soundboard",
    "mandible.ui",
    "mandible.ui.app",
    "mandible.ui.dialogs",
    "mandible.ui.dialogs.about",
    "mandible.ui.dialogs.add_plugin",
    "mandible.ui.dialogs.hotkey",
    "mandible.ui.dialogs.param_map",
    "mandible.ui.dialogs.prefx",
    "mandible.ui.dialogs.settings",
    "mandible.ui.dialogs.setup_assistant",
    "mandible.ui.dialogs.soundboard",
    "mandible.ui.elements",
    "mandible.ui.elements.base",
    "mandible.ui.elements.frames",
    "mandible.ui.elements.knobs",
    "mandible.ui.elements.meters",
    "mandible.ui.elements.panels",
    "mandible.ui.elements.registry",
    "mandible.ui.elements.screws",
    "mandible.ui.elements.switches",
    "mandible.ui.look",
    "mandible.ui.main_window",
    "mandible.ui.palette_gen",
    "mandible.ui.stylesheet",
    "mandible.ui.widgets",
    "mandible.ui.widgets.base",
    "mandible.ui.widgets.buttons",
    "mandible.ui.widgets.chain_card",
    "mandible.ui.widgets.channel_strip",
    "mandible.ui.widgets.chassis",
    "mandible.ui.widgets.flow_strip",
    "mandible.ui.widgets.knobs",
    "mandible.ui.widgets.lamps",
    "mandible.ui.widgets.meters",
    "mandible.ui.widgets.plugin_card",
    "mandible.ui.widgets.sliders",
    "mandible.ui.widgets.switches",
    "mandible.waveform_widget",
    "_cffi_backend",
]

rnnoise = _native(os.path.join("rnnoise", "rnnoise.dll"), os.path.join(ROOT, "mandible", "lib", "rnnoise.dll"))
if rnnoise:
    datas.append((rnnoise, "mandible/lib"))

for pkg in ("_sounddevice_data", "sounddevice", "pedalboard"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

portaudio = _native(os.path.join("portaudio", "libportaudio64bit-asio.dll"))

a = Analysis(
    [os.path.join(ROOT, "mandible", "__main__.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pytest", "IPython"],
    noarchive=False,
    optimize=0,
)
# Software OpenGL fallback (Mesa) is not used by Mandible's widgets.
a.binaries = [b for b in a.binaries if os.path.basename(b[0]).lower() != "opengl32sw.dll"]

# Replace sounddevice's prebuilt PortAudio DLLs with our source build. This must happen after
# Analysis: PyInstaller's sounddevice hook adds the prebuilt DLLs (all platforms) during analysis.
# TOC entries are (dest_name, src_path, typecode).
PA_DIR = os.path.normpath("_sounddevice_data/portaudio-binaries")
if portaudio:
    def _is_bundled_portaudio(entry):
        return os.path.normpath(entry[0]).startswith(PA_DIR + os.sep)
    a.binaries = [e for e in a.binaries if not _is_bundled_portaudio(e)]
    a.datas = [e for e in a.datas if not _is_bundled_portaudio(e)]
    # sounddevice loads "-asio.dll" when SD_ENABLE_ASIO is set and the plain name otherwise.
    for name in ("libportaudio64bit-asio.dll", "libportaudio64bit.dll"):
        a.binaries.append((os.path.join(PA_DIR, name), portaudio, "BINARY"))
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mandible",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(ROOT, "Mandible.ico")],
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Mandible",
)
