# Mandible UI Design Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Mandible's theming as data (palettes + skins), fix resizing, unify every control, bring all three skins to one finished standard, and add a Customize editor with custom colours.

**Architecture:** A frozen `Look = (Palette, Skin)` in `mandible/ui/look.py` is the only source of colours and shapes. One generated stylesheet plus an element registry (frames, switches, knobs, meters, panels) replace the 569 hex literals, 88 inline styles and 13 skin branches in `gui.py`, which is split into a `mandible/ui/` package. A gallery tool and pytest suite (offscreen Qt) prove layout, contrast and consistency for every skin x theme.

**Tech Stack:** Python 3.13, PySide6 6.12 (QtWidgets/QtGui), pytest (dev-only), GitHub Actions (windows-2022).

**Spec:** `docs/superpowers/specs/2026-10-16-ui-design-pass-design.md` (read it first; section numbers below refer to it)

## Global Constraints

- Minimum main window **1024 x 640**; no clipping/overflow at widths 1024, 1280, 1600, 1920, 2560 and heights 640, 720, 900, 1080, at Qt scale factors 1.0, 1.25, 1.5.
- Contrast: text >= **4.5:1** on its surface; large text, icons, interactive borders, focus ring >= **3:1** (WCAG 2.x relative luminance).
- Type: text sizes **11, 13, 16 px** plus readout mono **11 px** (at 100 %); nothing below **10 px**. Fonts: Segoe UI (text), Consolas / Cascadia Mono (readouts). No bundled fonts.
- Spacing scale **4, 8, 12, 16, 24**; `compact` density maps 16 -> 12 and 24 -> 16.
- Button tiers: `primary` (filled accent, **at most one per view**), `secondary` (outlined), `quiet` (borderless until hover), `danger` (`status.danger`). No typed characters as icons (`<`, `>`, `▲`, `▼`, `x`, `✕`, `+` alone, emoji).
- Look switch completes in **< 150 ms** on the sample setup and never touches the audio engine.
- No hex colour literals or `setStyleSheet(` calls outside `mandible/ui/look.py`, `mandible/ui/stylesheet.py`, `mandible/ui/palette_gen.py`, `mandible/branding.py` (enforced by `tools/check_ui_tokens.py`).
- No new runtime dependencies. Dev-only tools go in `requirements-dev.txt` and are never shipped.
- Built-in palette ids `scarlet`, `cyan`, `stealth`, `amber`, display names **Scarlet, Cyan, Stealth, Amber**. Built-in skin ids `skeuomorphic`, `vintage`, `minimal`. User ids are prefixed `user:`.
- User files: `%APPDATA%\Xen10\Mandible\skins\<slug>.json`, `...\themes\<slug>.json`; export/import extensions **`.mandibleskin`**, **`.mandibletheme`**; JSON `format` = `Mandible.Skin` / `Mandible.Theme`, `version: 1`.
- Status hues fixed (green / amber / red families); only lightness adapts.
- CLAUDE.md rules apply (no "VST" in names; describe as "VST3 plugins"; dependencies; CI-only release builds).

## Review Focus

1. **A malformed or hostile import file** (not JSON, wrong `format`, unknown keys, unknown variant, > 256 KB): show one clear error, change nothing, never crash. Test in Task 17.
2. **A saved user skin naming a variant this build doesn't have** (file from a newer version, or a variant later removed): load with that slot falling back to the skin default and a notice; never crash at startup. Test in Task 3 and Task 17.
3. **Very long and non-Latin names** (60-character chain names, plugin names, device names such as `Микрофон (USB Audio CODEC)`) at the 1024 x 640 minimum: elide with full text in the tooltip; no overflow. Test in Task 9.
4. **150 % Windows scaling at the minimum size**: still no clipping or overflow. Test in Task 9 (subprocess with `QT_SCALE_FACTOR=1.5`).
5. **Changing skin or colours while audio is running**: no engine calls, completes under 150 ms, and the choice survives a restart. Test in Task 7 and Task 19.

---

## Stage 1: Foundation

### Task 1: Test harness and regression tests for the audit fixes

**Files:**
- Create: `requirements-dev.txt`, `tests/conftest.py`, `tests/test_audit_regressions.py`, `.github/workflows/ci.yml`
- Modify: `CLAUDE.md` (one line: dev-only tools live in `requirements-dev.txt`, are not shipped, and need no notices entry)

**Interfaces:**
- Produces fixtures: `qapp` (session `QApplication`, `QT_QPA_PLATFORM=offscreen`), `appdata` (temp dir set as `APPDATA` before `mandible` is imported; yields `pathlib.Path`), `core` (a `Core` built on a fresh `AppConfig` with `autostart_audio=False`, shut down after the test), `sample_core` (as `core`, plus chains Robot Voice [pitch_formant, gsm, reverb], Deep Narrator [pitch_formant, reverb, mode="hold"], Walkie-Talkie [gsm, filter], Cave Echo [reverb, delay] and soundboard clips Airhorn, Rimshot, Sad trombone).

- [ ] **Step 1:** `requirements-dev.txt` contains `-r requirements-build.txt` and `pytest==8.3.4`.
- [ ] **Step 2: Write regression tests** in `tests/test_audit_regressions.py`, porting the session's verification scripts:
  - `test_soundboard_dialog_opens_with_clips` (no `NameError`)
  - `test_api_rejects_browser_requests`: text/plain POST -> 415; `Origin` header -> 403; `Host: evil.example:PORT` -> 403; OPTIONS -> 405; no `Access-Control-Allow-Origin` header on GET
  - `test_api_select_clean`: POST `{"name": "clean"}` -> 200 and `core.target() == DRY_ID`; `/api/status` `active_chain_name == "Clean"`
  - `test_formant_level_independent_of_block_size`: +4 st formant on 220 Hz sine, output level within 0.2 dB across blocks 128/256/512/1024
  - `test_formant_identity_latency_exact`: pitch 0 / formant 0, `max|out[L:] - in[:-L]| < 1e-6` with `L == 1024`, mix 100 and 50
  - `test_rnnoise_fifo_no_gaps` at 44100/48000/96000 x blocks 64/128/441/512 with an identity lib stub; measured latency 563 / 480 / 1152 samples
  - `test_chain_dry_wet_phase_aligned`: 50 % dry/wet through a 1024-sample-latency chain, error < 1e-6
  - `test_keep_awake_round_robin`: three idle fake boards over 30 blocks -> calls `[10, 10, 10]`
  - `test_midi_cc_midpoint_edges`: values 10,40,70,90,127,100,50,20,80 -> `['press','release','press']`; note on/off -> press then release
  - `test_meter_timer_pauses_when_hidden`: shown -> active; minimized/hidden -> inactive, status interval 2000
- [ ] **Step 3:** Run `python -m pytest -q`; expected: all pass (they pin behaviour already on the branch).
- [ ] **Step 4:** `ci.yml`: on `push` and `pull_request`, windows-2022, Python 3.13, `pip install -r requirements-dev.txt`, `python tools/check_release_compliance.py`, `python -m pytest -q` with `QT_QPA_PLATFORM=offscreen`.
- [ ] **Step 5: Commit** `test: pytest harness, audit regression tests, CI test job`

### Task 2: Palette generation and contrast (`mandible/ui/palette_gen.py`)

**Files:** Create `mandible/ui/__init__.py`, `mandible/ui/palette_gen.py`; Test `tests/test_palette_gen.py`

**Interfaces:**
- Produces:
  - `TEXT_MIN = 4.5`, `UI_MIN = 3.0`
  - `TINTS: dict[str, tuple[float | None, float]]` = `{"neutral": (None, 0.008), "warm": (60.0, 0.02), "cool": (250.0, 0.02)}` (hue degrees, chroma)
  - `hex_to_oklch(hex_: str) -> tuple[float, float, float]`; `oklch_to_hex(l: float, c: float, h: float) -> str` (out-of-gamut: reduce chroma until in sRGB)
  - `contrast_ratio(fg: str, bg: str) -> float`
  - `CONTRAST_PAIRS: tuple[tuple[str, str, float], ...]` (token, partner token, target): every `text.*` except `text.disabled` vs `bg.window`/`bg.panel`/`bg.raised` at 4.5; `text.on_accent` vs `accent` at 4.5; `accent`, `focus.ring`, `line.strong`, `status.*` vs `bg.panel` at 3.0
  - `@dataclass(frozen=True) ContrastIssue(token: str, partner: str, ratio: float, target: float)`
  - `check_colors(colors: Mapping[str, str]) -> list[ContrastIssue]`
  - `derive_colors(accent: str, tint: str = "neutral", dark: bool = True) -> tuple[dict[str, str], list[str]]` returning every token in `PALETTE_TOKENS` (Task 3) and a list of human-readable adjustment notices (e.g. `"accent: adjusted for readability"`). Surfaces: fixed OKLCH lightness steps (dark: window 0.16, panel 0.19, raised 0.23, inset 0.14, overlay 0.27) at the tint hue/chroma; text primary 0.95, secondary 0.75, disabled 0.50; `text.on_accent` is near-white or near-black, whichever meets 4.5 on `accent`; accent lightness raised in 0.01 steps until 3.0 vs `bg.panel`; status hues 150 (ok), 75 (warn), 25 (danger).

- [ ] **Step 1: Write failing tests:** `contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)`; `contrast_ratio("#777777", "#777777") == pytest.approx(1.0)`; `oklch_to_hex(*hex_to_oklch("#e11d48")) == "#e11d48"`; for accents `["#e11d48", "#06b6d4", "#10b981", "#d97706", "#000000", "#ffffff", "#ffff00", "#0000ff", "#404040"]` x tints `TINTS` -> `check_colors(derive_colors(a, t)[0]) == []`; `derive_colors("#000000")[1]` contains `"accent: adjusted for readability"`; status hue of `status.danger` is within 15 degrees of 25 for every accent.
- [ ] **Step 2:** Run `python -m pytest tests/test_palette_gen.py -q`; expected FAIL (module missing).
- [ ] **Step 3:** Implement (OKLab/OKLCH per Björn Ottosson's published matrices; ~40 lines of maths).
- [ ] **Step 4:** Run the tests; expected PASS.
- [ ] **Step 5: Commit** `feat(ui): OKLCH palette derivation with contrast enforcement`

### Task 3: Look model, built-ins and element registry

**Files:** Create `mandible/ui/look.py`, `mandible/ui/elements/__init__.py`, `mandible/ui/elements/registry.py`; Test `tests/test_look.py`

**Interfaces:**
- Consumes: `derive_colors`, `check_colors` (Task 2).
- Produces (`look.py`):
  - `PALETTE_TOKENS: tuple[str, ...]` = exactly the tokens in spec 7.1 table (bg.window ... readout.text)
  - `@dataclass(frozen=True) Palette(id: str, name: str, dark: bool, colors: Mapping[str, str], source: dict | None = None)`; `Palette.color(token: str) -> str` (KeyError on unknown token); `source` keeps `{"accent", "tint"}` for simple-mode palettes
  - `SKIN_SLOTS = ("frame", "switch", "knob", "meter", "panel", "screws", "density")`; `SHAPE_TOKENS = ("radius.control", "radius.panel", "border.width", "shadow.depth")`
  - `@dataclass(frozen=True) Skin(id: str, name: str, elements: Mapping[str, str], shape: Mapping[str, float])`
  - `@dataclass(frozen=True) Look(palette: Palette, skin: Skin)`
  - `BUILTIN_PALETTES: dict[str, Palette]` (4, ported from `THEMES`, names per Global Constraints, every value passing `check_colors`); `BUILTIN_SKINS: dict[str, Skin]` (3, element table in spec 7.1)
  - `space(step: int) -> int` (step 1..5 -> 4/8/12/16/24, density-adjusted for the current look); `font_px(role: str) -> int` for roles `small`=11, `body`=13, `title`=16, `readout`=11
  - `current_look() -> Look`; `set_look(look: Look, app: QApplication | None = None) -> None` (applies `build_qss` from Task 4 once, emits); `look_bus() -> LookBus` where `class LookBus(QObject): lookChanged = Signal()`
- Produces (`elements/registry.py`): `register(slot: str, variant: str, cls: type, label: str) -> None`; `variants(slot: str) -> list[str]`; `label(slot, variant) -> str`; `get(slot: str, variant: str) -> type`; `DEFAULTS: dict[str, str]` (the skeuomorphic choices); `resolve(elements: Mapping[str, str]) -> tuple[dict[str, str], list[str]]` (unknown slot/variant -> default plus notice `"switch: 'laser' not available, using bat_toggle"`). Placeholder variant classes for every id in the spec table are registered here; Stage 2 fills in painting.

- [ ] **Step 1: Write failing tests:** every built-in palette has exactly `PALETTE_TOKENS` keys and `check_colors(p.colors) == []`; palette names are `["Scarlet", "Cyan", "Stealth", "Amber"]` and none contains "Focusrite"; every built-in skin's elements are registered variants; `resolve({"switch": "laser"})` returns `DEFAULTS["switch"]` and a notice mentioning `laser`; `space(4)` is 16 for comfortable and 12 for compact; `set_look` emits `lookChanged` once.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement. Port the four palettes by mapping old keys (`bg_win`->`bg.window`, `bg_card`->`bg.panel`, `bg_card_alt`->`bg.raised`, `bg_input`->`bg.inset`, `border`->`line.subtle`, `text`->`text.primary`, `text_muted`->`text.secondary`, `accent`, `accent_hover`, `vfd`->`readout.text`); fill the remaining tokens from `derive_colors(accent)` and fix any that fail contrast.
- [ ] **Step 4:** Run; expected PASS.
- [ ] **Step 5: Commit** `feat(ui): Look model, built-in palettes and skins, element registry`

### Task 4: Stylesheet builder and the token lint

**Files:** Create `mandible/ui/stylesheet.py`, `tools/check_ui_tokens.py`; Test `tests/test_stylesheet.py`, `tests/test_ui_tokens_lint.py`

**Interfaces:**
- Produces: `build_qss(look: Look) -> str`. Styling hooks widgets use instead of inline styles: object names (`rackChassis`, `masterHeadStrip`, `modularBay`, `pluginRackCard`, `channelStrip`, `statusPill`), dynamic properties `tier` in {primary, secondary, quiet, danger}, `state` in {off, on, warn, danger}, `surface` in {panel, raised, inset}.
- Produces: `tools/check_ui_tokens.py [paths...]`; exit 1 listing `file:line` for any `#rrggbb`/`#rgb` literal or `setStyleSheet(` outside the allowed modules; `ALLOWLIST_LEGACY: set[str]` (initially `{"mandible/gui.py", "mandible/setup_assistant.py", "mandible/overlay.py", "mandible/waveform_widget.py", "mandible/about.py"}`, emptied by Task 8c).

- [ ] **Step 1: Write failing tests:** `build_qss` succeeds for every built-in palette x skin, contains no `{` placeholder residue, is identical across two calls; the QSS contains a `QPushButton[tier="primary"]` rule using `accent` and a `[tier="danger"]` rule using `status.danger`; lint test runs the tool on the repo and expects exit 0 with the legacy allowlist, and exit 1 on a temp file containing `setStyleSheet("color:#fff")`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run; expected PASS.
- [ ] **Step 5: Commit** `feat(ui): generated stylesheet and token lint`

### Task 5: Inspection helpers and the gallery tool

**Files:** Create `mandible/ui/inspect.py`, `tools/ui_gallery.py`; Test `tests/test_gallery.py`

**Interfaces:**
- Produces (`inspect.py`): `@dataclass Overflow(widget: str, object_name: str, right: int, parent_right: int)`; `find_overflow(root: QWidget) -> list[Overflow]` (visible children whose geometry extends past their visible parent's rect by > 1 px, ignoring scroll-area viewports' contents); `find_clipped_text(root) -> list[str]` (QLabel/QAbstractButton whose `fontMetrics().horizontalAdvance(text)` exceeds the content width and that have no tooltip carrying the full text); `untiered_buttons(root) -> list[str]` (QPushButtons with no `tier` property).
- Produces (`ui_gallery.py`): CLI `--out DIR --skins a,b --themes a,b --sizes 1024x640,1280x720,1920x1080 [--user-looks DIR] [--strict]`. Writes `DIR/index.html` (grid of PNGs per screen x skin x theme x size) and `DIR/report.json` = `{"<screen>|<skin>|<theme>|<WxH>": {"min_size": [w, h], "overflow": [...], "clipped_text": [...], "untiered_buttons": [...], "contrast": [...]}}`. Screens: main window and every dialog (spec 7.8). `--strict` exits 1 when any overflow, clipped-text or contrast list is non-empty. Uses the `sample_core` setup (factor it into `mandible/ui/sample_setup.py` and have `tests/conftest.py` reuse it).

- [ ] **Step 1: Write failing test:** run the gallery for `skeuomorphic` x `scarlet` at `1280x720` into `tmp_path`; assert `index.html` exists, `report.json` has a key for `main|skeuomorphic|scarlet|1280x720`, and its `min_size[0] == 2033` (pins today's bug; Task 9 changes this assertion to `<= 1024`).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement (base on the session's `capture_ui.py`: `WA_DontShowOnScreen`, `grab()`).
- [ ] **Step 4:** Run; expected PASS. Also run the full gallery once and keep the output as the "before" reference outside the repo.
- [ ] **Step 5: Commit** `feat(tools): UI gallery with overflow, clipped-text and contrast report`

## Stage 2: Port and split (no visual change intended)

### Task 6: Element variants carry today's drawing

**Files:** Create `mandible/ui/elements/{frames,switches,knobs,meters,panels,screws}.py`; Modify `mandible/ui/elements/registry.py`; Test `tests/test_elements.py`

**Interfaces:**
- Produces: `@dataclass ElementState(enabled: bool = True, active: bool = False, hovered: bool = False, pressed: bool = False, value: float = 0.0)`; base `class Element: def paint(self, p: QPainter, rect: QRectF, state: ElementState, look: Look) -> None` and `def size_hint(self, look: Look) -> QSize`. Variants: frames `metal_rack, wood_cheeks, frameless`; switches `bat_toggle, rocker, pill`; knobs `machined, vintage_bakelite, flat_ring`; meters `led_segments, smooth_bar`; panels `brushed, lacquer, flat`; screws `corners_only, none`. Move the existing painting from `ChassisWrapperFrame`, `HardwareSwitch`, `HardwareKnob`/`PluginParamKnob`, `LevelMeter`/`ThinLevelMeter`/`PluginPrePostMeter`, `RackScrew` into these classes, replacing literals with `look.palette.color(...)`. `pill`, `flat_ring` and `smooth_bar` start as the minimal skin's current drawing.

- [ ] **Step 1: Write failing test:** for every slot/variant x built-in palette, painting into a 64 x 64 `QImage` at states off/on/disabled produces a non-transparent image and differs between `active=False` and `active=True` for switches.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run; expected PASS.
- [ ] **Step 5: Commit** `refactor(ui): element variants for frames, switches, knobs, meters, panels, screws`

### Task 7: Switch the app to Look and the generated stylesheet

**Files:** Modify `mandible/gui.py` (remove `THEMES`, `_UI_STATE`, `current_skin`, `get_theme_dict`, `build_stylesheet`, `resolve_chassis_frame`; `apply_theme` becomes a call to `set_look`), `mandible/core.py` (`set_theme`/`set_ui_skin` store ids and call `set_look`), `mandible/branding.py` (tray active colour from `current_look().palette.color("accent")`), `mandible/overlay.py` (overlay colours from the current palette); Test `tests/test_look_switch.py`

**Interfaces:**
- Consumes: `set_look`, `BUILTIN_*`, `build_qss`, element registry.
- Produces: `look_from_config(cfg: AppConfig) -> Look` in `mandible/ui/look.py` (unknown ids fall back to `skeuomorphic`/`scarlet`).

- [ ] **Step 1: Write failing tests:** `test_overlay_and_tray_follow_accent`: after `set_look` to amber, the overlay's active colour and the tray's active icon colour equal amber's `accent`; `test_switch_look_fast_and_engine_free`: with `sample_core` main window shown off-screen, `set_look` for each skin x palette completes in < 150 ms (median of 3) and a mock engine records zero calls; `test_look_persists`: `core.set_ui_skin("minimal")`, `core.set_theme("amber")`, `save_now()`, reload config -> `look_from_config` returns minimal/amber.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement; every widget that painted with `get_theme_dict()` now uses `current_look()` and connects `look_bus().lookChanged` to `update`.
- [ ] **Step 4:** Run full suite and the gallery; compare against the Task 5 "before" output: same screens, no new overflow entries.
- [ ] **Step 5: Commit** `refactor(ui): drive all styling from Look`

### Task 8a / 8b / 8c: Split `gui.py` into `mandible/ui/` and remove literals

Three separately reviewable tasks, same shape:

- **8a widgets:** move meters, knobs, switches, `ChainCardWidget`, `PluginRackCard`, `PluginParamKnob`, `SignalFlowStrip`, `ChannelStripCard`, `GainSlider` to `mandible/ui/widgets/*.py`.
- **8b dialogs:** move `PluginParamMapDialog`, `HotkeyDialog`, `AddPluginDialog`, `PreFXDialog`, `SoundboardDialog`, `SettingsDialog` to `mandible/ui/dialogs/*.py`; move `setup_assistant.py` and `about.py` there.
- **8c main window:** move `ChainEditor` and `MainWindow` to `mandible/ui/main_window.py`; `mandible/gui.py` keeps only `main()` re-exported from `mandible/ui/app.py`; empty `ALLOWLIST_LEGACY`.

**Files (each):** the modules above; Modify imports in `mandible/__main__.py`, `Mandible.spec` hiddenimports (every new module), `tests/`; Test: existing suite + `tests/test_ui_tokens_lint.py`.

- [ ] **Step 1:** Remove the moved files from `ALLOWLIST_LEGACY` in `check_ui_tokens.py`; run the lint; expected FAIL listing their literals.
- [ ] **Step 2:** Move the code; replace every literal/inline style with tokens, `tier`/`state`/`surface` properties, or element painting.
- [ ] **Step 3:** Run lint (PASS), full pytest (PASS), gallery (no new overflow vs "before"); `python -m pyflakes mandible tools` clean.
- [ ] **Step 4: Commit** `refactor(ui): move <widgets|dialogs|main window> into mandible/ui`

## Stage 3: Layout and bugs

### Task 9: Responsive layout (spec 7.6)

**Files:** Create `mandible/ui/widgets/header.py`; Modify `mandible/ui/main_window.py`, `mandible/ui/widgets/flow_strip.py`, `mandible/ui/widgets/plugin_card.py`, `mandible/config.py` (`left_panel_width: int = 300`); Test `tests/test_layout.py`

**Interfaces:**
- Produces: `class HeaderBar(QFrame)` with zones `left`, `middle`, `right`; breakpoints `FLOW_ICONS_BELOW = 1400`, `FLOW_HIDDEN_BELOW = 1100`, `ACTIONS_OVERFLOW_BELOW = 1180`, `STRIPS_COLLAPSE_BELOW_H = 800`; left panel `QSplitter` 240..420 px persisted to `cfg.left_panel_width`; `abbreviate_title(name: str, max_len: int = 9) -> str` in `mandible/ui/text.py` (word-boundary abbreviation; full name goes to tooltip).

- [ ] **Step 1: Write failing tests:**
  - `test_minimum_size`: `win.minimumSizeHint().width() <= 1024` and `height() <= 640`
  - `test_no_overflow[W x H]` for every width x height in Global Constraints: `find_overflow(win) == []` and `find_clipped_text(win) == []`
  - `test_long_and_non_latin_names` (Review Focus 3): chain named `"A" * 60`, plugin display name `"Very Long Plugin Name With Many Words Version 3"`, input device `"Микрофон (USB Audio CODEC)"` at 1024 x 640 -> no overflow; each elided label's tooltip contains the full text
  - `test_scale_150` (Review Focus 4): subprocess with `QT_SCALE_FACTOR=1.5` runs the 1024 x 640 overflow check and exits 0
  - `test_abbreviate_title`: `"Radio Squelch" -> "SQUELCH"`, `"Stereo Width" -> "WIDTH"`, `"Threshold" -> "THRESH"`, `"Mix" -> "MIX"`
  - `test_strips_collapse_below_800`, `test_splitter_width_persisted`
  - Update `tests/test_gallery.py`: `min_size[0] <= 1024`
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement; move the idle-mode / hotkeys / all-off row into the header status zone (idle mode compact dropdown, hotkeys switch) and Settings > General.
- [ ] **Step 4:** Run; expected PASS.
- [ ] **Step 5: Commit** `feat(ui): responsive header, resizable panel, collapsing strips; 1024x640 minimum`

### Task 10: Review bugs (spec section 10, items 2-10)

**Files:** Modify the owning widget/dialog modules; Test `tests/test_review_bugs.py`

- [ ] **Step 1: Write failing tests**, one per bug:
  - pre-FX pill reads `"PRE-FX"`; tooltip lists active stages (`"High-pass"` only by default); with all stages off its `state` is `"off"`
  - plugin card latency for Pitch & Formant reads `"21.3 ms (1024 smp)"` at 48 kHz (uses `plugins.get_slot_latency_samples`)
  - built-in effect cards show a `"Built-in"` badge, no `"VST3"` badge, and no Open UI button; a fake VST3 slot shows `"VST3"` and Open UI
  - no Settings section label contains `"_"` and the output-safety section is titled `"Limiter & Normalizer"`
  - soundboard rows: every cell widget's height <= row height; with no selection the detail panel reads `"No clip selected"` and no row is selected
  - channel strip title with empty input device reads `"No input"`; never contains `"Focusrite"`
  - chain header contains no empty framed widgets (every visible QFrame child has at least one visible child)
  - knob mapping dialog text contains no `"VST"` for a built-in slot
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Fix each.
- [ ] **Step 4:** Run; expected PASS.
- [ ] **Step 5: Commit** `fix(ui): review bugs (pre-FX pill, latency, built-in badges, labels, soundboard rows)`

## Stage 4: Control system

### Task 11: Icons, button tiers, status pills, type and spacing

**Files:** Create `mandible/ui/icons.py`, `mandible/ui/widgets/buttons.py`; Modify every module that creates buttons; Test `tests/test_controls.py`

**Interfaces:**
- Produces: `ICON_NAMES = ("power", "mic", "monitor", "panic", "settings", "help", "plus", "menu", "up", "down", "remove", "map", "open_window", "play", "stop", "record", "hotkey", "chevron_left", "chevron_right", "chevron_down")`; `icon_pixmap(name: str, color: str, px: int) -> QPixmap` (vector paths on a 24-unit grid, one stroke weight); `icon(name: str) -> QIcon` (current look's `text.primary`, refreshed on `lookChanged`).
- Produces: `make_button(text: str = "", tier: str = "secondary", icon: str | None = None, tooltip: str = "", parent: QWidget | None = None) -> QPushButton` (raises `ValueError` for unknown tier; icon-only buttons require a tooltip); `class StatusPill(QLabel)` with `set_state(state: str)` for `off/on/warn/danger`, never focusable, no hover style.

- [ ] **Step 1: Write failing tests:** every icon renders non-empty at 16 and 24 px; in the main window and every dialog `untiered_buttons(...) == []`; each view has at most one `tier="primary"` button; no button text matches `^[<>▲▼xX✕+]$|[←-⇿☀-➿\U0001F300-\U0001FAFF]`; every QLabel/QAbstractButton font pixel size >= 10; status pills have `Qt.NoFocus`; header left zone contains the brand mark (`branding.render_mark`).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement and convert every button (Insert Plugin = primary; Open UI, move, remove, map = quiet with icons; Panic and Delete = danger; dialog OK/Save = primary).
- [ ] **Step 4:** Run; expected PASS.
- [ ] **Step 5: Commit** `feat(ui): icon set, button tiers, status pills, type and spacing scale`

## Stage 5: Every skin to the standard

### Tasks 12 / 13 / 14: Skeuomorphic, Vintage, Minimal

One task per skin, same shape. Vintage: replace the bright amber IN switch cap with a lacquer cap drawn from palette tokens. Minimal: real `pill` switch, `flat_ring` knob, `smooth_bar` meter; screws `none`; density `compact`. Skeuomorphic: corner screws only; drop the circle glyphs beside headings.

**Files:** `mandible/ui/elements/*.py`, `mandible/ui/look.py` (skin shape tokens); Test `tests/test_skins.py` (parametrized by skin, so later skins add one id)

- [ ] **Step 1: Write failing test** `test_skin_meets_standard[<skin>]` over the 4 built-in palettes x sizes 1024x640, 1280x720, 1920x1080, main window and every dialog: `find_overflow == []`, `find_clipped_text == []`, `untiered_buttons == []`, `check_colors(palette) == []`, and switching to the skin live raises no exception and completes < 150 ms (checklist items 1-3, 7). Items 4-6 (alignment, decoration, legibility) are reviewed on the gallery sheet.
- [ ] **Step 2:** Run for this skin; expected FAIL where it doesn't yet meet the standard.
- [ ] **Step 3:** Fix the skin's element variants and shape tokens; review the gallery for alignment and legibility.
- [ ] **Step 4:** Run; expected PASS. Attach the skin's gallery page to the PR.
- [ ] **Step 5: Commit** `feat(ui): <skin> skin meets the standard`

## Stage 6: Dialogs

### Task 15: Settings section list and Appearance section

**Files:** Modify `mandible/ui/dialogs/settings.py`; Test `tests/test_dialogs.py`

**Interfaces:** Produces `SettingsDialog(core, running, parent=None, initial_section: str = "audio")` with sections, in order, `audio, ptt, output_safety, midi, overlay, appearance, general, api` titled "Audio", "Push-to-talk", "Limiter & Normalizer", "MIDI", "Overlay", "Appearance", "General", "Local API". Appearance holds the skin picker, theme picker (built-in + user, from Task 17's `all_skins()`/`all_palettes()`; until Task 17 lands, built-ins only) and a "Customize..." button emitting `customizeRequested`. The ASIO button reads "ASIO driver settings..." and is visible only when the driver is ASIO.

- [ ] **Step 1: Write failing tests:** section ids/titles as above; picking a skin in Appearance applies live and persists on OK; ASIO button hidden for WASAPI; the setup assistant button is `tier="secondary"`.
- [ ] **Step 2-4:** Run (FAIL) -> implement -> run (PASS).
- [ ] **Step 5: Commit** `feat(ui): Settings section list with Appearance`

### Task 16: Remaining dialogs on the shared components

**Files:** `mandible/ui/dialogs/{soundboard,prefx,param_map,hotkey,add_plugin,about,setup_assistant}.py`; Test `tests/test_dialogs.py`

- [ ] **Step 1: Write failing tests:** for each dialog x built-in skin x palette at its default size and its minimum size: no overflow, no clipped text, no untiered buttons, one primary at most; Pre-FX dialog titled "Mic cleanup", explanations are in muted hint labels (`objectName == "hint"`), not in checkbox text; Setup Assistant Back is disabled on step 1; Knob mapping list shows full names without a horizontal scrollbar at default size.
- [ ] **Step 2-4:** Run (FAIL) -> implement -> run (PASS).
- [ ] **Step 5: Commit** `feat(ui): dialogs on the shared components`

## Stage 7: Customize

### Task 17: User skins and themes: storage, import, export

**Files:** Create `mandible/ui/user_looks.py`; Test `tests/test_user_looks.py`

**Interfaces:**
- Produces: `SKINS_DIR`, `THEMES_DIR` (under `paths.APP_DIR`); `MAX_IMPORT_BYTES = 256 * 1024`; `class LookFileError(Exception)`; `slugify(name: str) -> str`; `save_skin(skin: Skin) -> Path`; `save_palette(p: Palette) -> Path` (both require `id` starting `user:`, else `ValueError`); `load_user_skins() -> tuple[dict[str, Skin], list[str]]`; `load_user_palettes() -> tuple[dict[str, Palette], list[str]]` (second item: notices for skipped or adjusted files); `delete_user_look(look_id: str) -> None`; `all_skins() -> dict[str, Skin]`; `all_palettes() -> dict[str, Palette]` (built-ins first); `export_skin(skin, path)`, `export_palette(p, path)`; `import_skin(path) -> tuple[Skin, list[str]]`, `import_palette(path) -> tuple[Palette, list[str]]` (assigns a new `user:` id on collision with an existing name, adding " (2)").
- File JSON: `{"format": "Mandible.Skin", "version": 1, "name": str, "elements": {...}, "shape": {...}}` / `{"format": "Mandible.Theme", "version": 1, "name": str, "dark": bool, "source": {"accent": str, "tint": str} | null, "colors": {...}}`.

- [ ] **Step 1: Write failing tests:** save/load round trip for a skin and a simple-mode palette; `delete_user_look` removes the file; saving with a built-in id raises `ValueError`; Review Focus 1 (each raises `LookFileError` with a one-line message and leaves `all_skins()` unchanged): not JSON, `format` wrong, `version` 2, file of 300 KB, a colour value `"red; background:url(x)"` (only `#rrggbb` accepted); unknown top-level keys are ignored; Review Focus 2: a stored user skin with `"switch": "laser"` loads with `bat_toggle` and a notice; a theme whose colours fail contrast loads with the issues listed in the notices (not rejected).
- [ ] **Step 2-4:** Run (FAIL) -> implement -> run (PASS).
- [ ] **Step 5: Commit** `feat(ui): user skins and themes with safe import/export`

### Task 18: Appearance migration

**Files:** Modify `mandible/ui/user_looks.py`, `mandible/config.py` (`appearance_migrated: bool = False`), `mandible/__main__.py` (call after `migrate_legacy_data`); Test `tests/test_user_looks.py`

**Interfaces:** Produces `migrate_appearance(cfg: AppConfig) -> str | None` (returns the created user skin id or None). Old frame value `auto` means "the skin default"; `switch_style` values map to variants `bat_toggle`/`rocker`.

- [ ] **Step 1: Write failing tests:** default config -> returns None, sets `appearance_migrated`; `ui_skin="skeuomorphic", chassis_frame="wood_cheeks"` -> creates "Skeuomorphic (my settings)" with `frame="wood_cheeks"`, sets `cfg.ui_skin` to its id; running twice creates nothing the second time.
- [ ] **Step 2-4:** Run (FAIL) -> implement -> run (PASS).
- [ ] **Step 5: Commit** `feat(ui): migrate old frame/switch settings into a user skin`

### Task 19: Customize panel

**Files:** Create `mandible/ui/dialogs/customize.py`; Modify `mandible/ui/main_window.py` (dock it on `customizeRequested`); Test `tests/test_customize.py`

**Interfaces:**
- Consumes: registry `variants`/`label`, `Element.paint` (tile thumbnails), `derive_colors`, `check_colors`, `user_looks.*`, `set_look`.
- Produces: `class CustomizePanel(QDockWidget)`, signals `saved(str)` (look id); methods `select_variant(slot: str, variant: str)`, `set_accent(hex_: str)`, `set_tint(tint: str)`, `set_advanced(on: bool)`, `set_token(token: str, hex_: str)`, `save()`, `save_as(name: str)`, `revert()`, `export(path: Path)`, `import_file(path: Path)` (shows `LookFileError` text inline), `delete()` (user items only), `is_dirty() -> bool`; unsaved-changes prompt is an inline banner with Save / Discard / Keep editing.

- [ ] **Step 1: Write failing tests:** `select_variant("switch", "rocker")` updates `current_look()` immediately; `save()` is disabled while a built-in is selected and `save_as("Night")` creates `user:night` visible in Appearance's skin list; `set_accent("#000000")` shows the notice "Adjusted for readability"; Advanced mode lists every `PALETTE_TOKENS` entry with its ratio, and setting `text.secondary` to `"#333333"` shows a warning badge on that row and still allows saving; closing while dirty shows the banner rather than closing; Review Focus 5: a fake engine callback thread running during 50 `select_variant` calls records no exceptions and the panel never calls into `core.engine`; after save and restart (`look_from_config`), the user look is current.
- [ ] **Step 2-4:** Run (FAIL) -> implement -> run (PASS).
- [ ] **Step 5: Commit** `feat(ui): Customize panel with elements, colours, save and share`

## Stage 8: CI and documentation

### Task 20: Gallery in CI and the rules for new skins

**Files:** Modify `.github/workflows/ci.yml`, `CLAUDE.md`, `README.md`

- [ ] **Step 1:** `ci.yml` adds a step `python tools/ui_gallery.py --out gallery --strict` (all built-ins, three sizes) and uploads `gallery/` with `actions/upload-artifact@v4` (`if: always()`).
- [ ] **Step 2:** CLAUDE.md gains "Skins and themes": colours only via palette tokens; shapes via skin tokens or element variants; a new variant = one class + one `register(...)`; a new built-in skin/theme must pass `tests/test_skins.py` (add its id) and `--strict` gallery; no literals outside the look modules (lint enforces); keep theme/skin names free of third-party trademarks.
- [ ] **Step 3:** README Features gains one line on skins, colour themes and Customize; screenshots are not added yet (they come from the release build).
- [ ] **Step 4:** Push the branch (owner approval required) and confirm CI is green; run `python tools/ui_gallery.py --out gallery --strict` locally; expected exit 0.
- [ ] **Step 5: Commit** `ci: UI gallery artifact; docs: rules for skins and themes`

---

## Release (after Task 20; each step needs the owner's go-ahead)

1. Merge the branch to `main`.
2. Delete the old v0.1.0 draft release and the `v0.1.0` tag (built before this pass), re-tag `v0.1.0` on the final commit, let CI build the new draft.
