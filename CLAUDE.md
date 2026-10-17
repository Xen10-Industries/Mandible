# CLAUDE.md — Mandible

Standing rules for every session working in this repository. They are release-compliance
requirements (licensing, trademarks, code signing via SignPath Foundation), not style preferences.
If a task conflicts with a rule, stop and ask the user before proceeding.

## Project identity

- Product: **Mandible**. Publisher: **Xen10 Industries** (short form "Xen10"). Never use the old
  pre-release name "VoiceFX" in anything user-facing. It survives only in legacy-migration code
  (`mandible/paths.py`, `mandible/__main__.py`, `LEGACY_PRESET_EXT` in `mandible/config.py`).
- Windows version resource: ProductName "Mandible", CompanyName "Xen10 Industries" (set in
  `Mandible.spec`). Installer publisher is the same (`installer.iss`).
- Website xen-10.com is **not live**: do not link to it anywhere until the user says so.
- Repository: https://github.com/Xen10-Industries/Mandible (GitHub org "Xen10 Industries", slug `Xen10-Industries`).
- Free and open source, licensed **GPL-3.0-or-later** (`LICENSE`). Distribution: GitHub Releases
  first; later winget, itch.io and KVR Audio.
- User data: `%APPDATA%\Xen10\Mandible\` (config.json, plugin_cache.json, mandible.log). Defined only in
  `mandible/paths.py`; import `APP_DIR` / `LOG_PATH` from there. Never
  hard-code another location.
- Presets: `.mandible` extension, format id `"Mandible.Preset"`. Legacy `.vfxpreset` must stay importable.
- **Version:** single source of truth is `mandible/_version.py` (`__version__`, semver). Do not
  hard-code the version anywhere else. The spec, CI and installer all read it. Release tags are
  `v<version>` and CI fails if they don't match.

## Stack (for orientation)

Python 3.13 + PySide6 (LGPL-3.0) UI. VST3 hosting via Spotify **pedalboard** (GPL-3.0; bundles JUCE 6.1.4
and VST 3 SDK 3.7.2 under GPLv3). Audio I/O via sounddevice + PortAudio, built in CI with the ASIO SDK
(GPLv3 option). Packaged with PyInstaller (`Mandible.spec`) and Inno Setup (`installer.iss`).
Run from source: `python -m mandible`.

## Dependencies and licensing

- Every new dependency (Python package, native library, vendored code, font, icon, sound, model
  file) must, **before it is merged**:
  1. be open source. **No proprietary or closed-source binaries**, including "free" SDKs whose
     license forbids redistribution. This is a SignPath Foundation requirement.
  2. have a license compatible with **GPL-3.0-or-later** (e.g. MIT, BSD, ISC, Zlib, Apache-2.0,
     LGPL, GPL-2.0-or-later, GPL-3.0). Not compatible: GPL-2.0-only, proprietary, CC-BY-NC/ND,
     "non-commercial" licenses. Ask the user if unsure.
  3. be added to `THIRD_PARTY_NOTICES.txt` with its name, version, copyright line and **full** license
     text, copied verbatim from the project. Update version numbers there when you bump a pin.
  4. be pinned to an exact version in `requirements.txt` (runtime) or `requirements-build.txt` (build),
     and added to `NOTICE_NAMES` in `tools/check_release_compliance.py` (CI enforces this).
- The VST 3 SDK entry stays first in `THIRD_PARTY_NOTICES.txt`. The shipped SDK is **3.7.2 (GPLv3
  option)**, not the MIT-licensed 3.8+. Do not relabel it as MIT unless pedalboard/JUCE actually move to
  SDK ≥ 3.8 (and note that JUCE 8's open-source license is AGPLv3, which would affect Mandible's license).
- Keep every third-party LICENSE/COPYING/NOTICE file intact in its original location. Never strip
  license headers from third-party sources.
- Don't modify vendored third-party code without recording the change (what, why, which files) under
  that component's entry in `THIRD_PARTY_NOTICES.txt`.
- `LICENSE` and `THIRD_PARTY_NOTICES.txt` (plus `licenses/`) must ship in **every** release artifact:
  the PyInstaller bundle (`Mandible.spec` datas), the portable zip and the installer
  (`installer.iss` [Files]). Help → Licenses (`mandible/about.py`) displays them.

## Drivers: never bundle

- Never bundle, download-on-install, or redistribute **VB-Cable / VB-Audio** or any other third-party
  audio driver. Docs, the setup assistant and the installer **link** to <https://vb-audio.com/Cable/>
  only. Focusrite Loopback users need nothing extra.

## VST trademark rules

- "VST" must never appear in the product name, executable name, installer name, window title, icon or
  logo. Describing Mandible as something that "hosts VST3 plugins" is fine.
- Do not add Steinberg's VST logo or any Steinberg artwork unless it follows the usage guidelines
  shipped with the VST 3 SDK (and the user approves).
- Keep the notice "VST is a trademark of Steinberg Media Technologies GmbH" in README.md, the About
  dialog and THIRD_PARTY_NOTICES.txt.
- Prefer neutral UI labels ("PLUGIN RACK", "+ INSERT PLUGIN") over "VST …" used like a brand.

## Builds, releases, signing

- **Release binaries are built only by CI** (`.github/workflows/release.yml`), never locally. Never
  upload a locally built exe/zip/installer anywhere. `build.ps1` is for local testing only.
- Native libraries (PortAudio+ASIO, RNNoise) are compiled from pinned, hash-checked upstream sources in
  CI. Never commit `.dll`, `.exe`, `.pyd` or other prebuilt binaries (`.gitignore` excludes them; CI
  checks this).
- Code signing goes through SignPath (placeholder steps in the workflow). Do not add the SignPath
  attribution line to the README until the user says the application is approved.
- **Never commit secrets or signing material**: no certificates (.pfx/.p12/.cer), private keys,
  API tokens, `.env` files or SignPath tokens. Secrets live only in GitHub Actions secrets.
- Ask the user before anything irreversible or outward-facing: pushing, tagging, creating or publishing
  releases, deleting files, creating repositories or changing GitHub settings. CI creates releases as
  **drafts**; a human publishes them.
