<img src="assets/icon/mandible-tile.svg" width="96" height="96" alt="Mandible logo">

# Mandible

**Mandible** by **Xen10 Industries** is a free, open-source, low-latency voice effects rack for Windows.
It hosts VST3 plugins (voice changers, noise cleanup, EQ, reverb, and so on) in swappable chains you
switch with global hotkeys, then sends the processed voice to a virtual audio cable or Focusrite
Loopback so Discord, OBS, games or any other app can use it as a microphone.

## Features

- **Swappable chains (racks) of VST3 plugins**, switched with global hotkeys in **Toggle** or **Hold** mode.
  Modifiers (`Ctrl`, `Shift`, `Alt`, `Win`) are supported, and keys still reach your game or app.
- **Natural tails.** When you switch an effect off, the input fades to dry within about 15 ms, while
  reverb and delay tails keep ringing for the tail time you set.
- **Native plugin editors.** Double-click a plugin (or click **Open UI**) to open its own window.
  Audio and hotkeys keep running while you edit.
- **Built-in effects** (pitch & formant, reverb, delay, chorus, drive, bitcrush, radio, filter), plus
  pre-processing: high-pass filter, RNNoise noise suppression and a noise gate.
- **Clean pass-through, mute, or a default chain** when no hotkey is active, plus a **panic / all-off**
  hotkey.
- **Skins and colour themes**, switched live, plus a **Customize** panel to build your own and share
  them as files.
- Soundboard, MIDI control, an on-screen overlay, a local HTTP API (127.0.0.1 only) for Stream Deck and
  OBS, and system tray integration.

## Requirements

- Windows 10 or 11, 64-bit.
- **One** of the following to carry Mandible's output to other apps:
  - **Focusrite interface with Loopback** (e.g. Scarlett 3rd/4th gen). Nothing extra is needed.
  - **A virtual audio cable** such as **VB-Audio Virtual Cable**, downloaded free from
    <https://vb-audio.com/Cable/>. Mandible does **not** bundle or install any audio driver; install
    the cable yourself from VB-Audio's site.
- VST3 plugins of your choice (optional; Mandible has built-in effects).

## Install

1. Download the latest release from this repository's [**Releases** page](../../releases/latest):
   - `Mandible-<version>-Setup.exe` (installer), or
   - `Mandible-<version>-win64-portable.zip` (unzip anywhere and run `Mandible.exe`).
2. *(Optional)* Check the download against `SHA256SUMS.txt` (see below).
3. Run Mandible. The **Audio Setup Assistant** walks you through choosing your microphone and output.

### "Windows protected your PC"

Mandible's releases are not code-signed yet, so Windows SmartScreen may warn you the first time you run
the installer or `Mandible.exe`. Click **More info**, check the app is `Mandible-<version>-Setup.exe` or
`Mandible.exe`, then click **Run anyway**. Only do this for files downloaded from this repository's
Releases page; every release is built by GitHub Actions from the source code here.

To check a download wasn't altered, compare its SHA-256 hash with the matching line in that release's
`SHA256SUMS.txt`. In PowerShell:

```powershell
Get-FileHash .\Mandible-0.1.1-Setup.exe -Algorithm SHA256
```

The `Hash` it prints must equal the value on the file's line in `SHA256SUMS.txt` (case doesn't matter).

### Routing with Focusrite Loopback

```
[ Microphone ] → Focusrite Input 1 → [ Mandible: VST3 chain ] → Focusrite Playback 3-4
        → Focusrite Control: Loopback source = Playback 3-4 → "Loopback" input in Discord / OBS
```

1. **Mandible → Config:** Driver `ASIO`, input device `Focusrite USB ASIO`, mic channel `1`, output
   channels `3-4`. The buffer size is set in the Focusrite driver's control panel, which you can open
   from Mandible's settings.
2. **Focusrite Control:** set the Loopback source to **Playback 3-4**.
3. **Discord / OBS:** choose **Focusrite USB Audio - Loopback** as the microphone.

### Routing with VB-Cable

Set Mandible's output to **CABLE Input (VB-Audio Virtual Cable)**, and in Discord / OBS select
**CABLE Output (VB-Audio Virtual Cable)** as the microphone. Turn off Discord's own noise suppression and
echo cancellation so they don't fight your chain.

Settings, chains and plugin states are stored in `%APPDATA%\Xen10\Mandible\`. Presets export as
`.mandible` files; older `.vfxpreset` files from pre-release builds still import.

## Build from source

Requirements: Windows 10/11 x64, Python 3.13 (64-bit) and Git.

```powershell
git clone https://github.com/Xen10-Industries/Mandible.git
cd Mandible
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m mandible
```

`Mandible.bat` / `Mandible-debug.bat` start the app from `.venv` (the debug variant keeps a console open).
When run from source, Mandible uses the PortAudio build that ships with the `sounddevice` package, and
RNNoise noise suppression is available only if you place an `rnnoise.dll` in `mandible/lib/`.

**Release builds** (exe, portable zip and installer) are produced only by the GitHub Actions workflow
in [`.github/workflows/release.yml`](.github/workflows/release.yml). It compiles PortAudio (with ASIO)
and RNNoise from pinned upstream sources, runs PyInstaller and Inno Setup, and attaches everything to a
draft GitHub Release. `build.ps1` exists only for local test builds, which must not be distributed.

The version number lives in one place: [`mandible/_version.py`](mandible/_version.py)
([semver](https://semver.org/)). To release, bump it, commit, and push a matching tag `vX.Y.Z`.

## License

Mandible is free software, licensed under the **GNU General Public License v3.0 or later**. See
[LICENSE](LICENSE). It is GPL-licensed because it builds on GPL-3.0 components, chiefly Spotify's
[pedalboard](https://github.com/spotify/pedalboard), JUCE and the Steinberg VST 3 and ASIO SDKs
(both used under their GPLv3 license option).

Third-party components and their licenses are listed in
[THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt). This file also ships with every release and can be
viewed in the app under **Help → Licenses**.

## Trademarks

VST is a trademark of Steinberg Media Technologies GmbH, registered in Europe and other countries.
ASIO is a trademark of Steinberg Media Technologies GmbH. Focusrite, VB-Audio, Discord and OBS are
trademarks of their respective owners. Mandible is not affiliated with or endorsed by any of them.
