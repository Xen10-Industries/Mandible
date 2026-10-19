# Mandible UI design pass: skins, themes, layout and polish

- **Date:** 2026-10-16
- **Status:** Approved by owner 2026-10-16
- **Owner:** Xen10 Industries
- **Related:** UI review (https://claude.ai/artifact/SoBeAbuBs6sN8GDysdXZXb), audit fixes and new logo on branch `fix/audit-findings`

## 1. Intent

Mandible works, but it looks unfinished: buttons in half a dozen unrelated styles, loose spacing, decorative clutter, labels that truncate, and a window that cannot shrink below 2,033 px (so on a 1920 px screen it hangs past the right edge). This pass makes the app look like one deliberate, professional product **in every skin and colour theme**, and rebuilds theming so that new skins and themes, including ones users make themselves, can be added without touching widget code.

The rack-hardware character stays. The goal is to make every control belong to it, not to replace it.

## 2. Goals

1. **Every skin and every colour theme reaches the same finished standard** (section 9). Existing skins: skeuomorphic, vintage, minimal. Existing themes: four, all dark.
2. **Skins and themes are data.** Widgets read named tokens only; no colour or shape literals in widget code. Any skin works with any theme.
3. **Simple to choose, deep to customize.** One skin picker; a skin bundles frame, switches, knobs, meters, materials and density. A *Customize...* editor swaps individual elements and colours with a live preview and saves the result as the user's own skin or theme.
4. **Custom colours that stay readable.** Pick an accent (and optionally a background tint); the full palette is derived with contrast checks. An Advanced mode exposes every colour.
5. **Resizing works.** Minimum window 1024 x 640; nothing clips, overlaps or overflows from 1024 to 2560+ px wide, at 100/125/150 % Windows scaling.
6. **One control system.** Consistent buttons, icons, type, spacing and states across the main window and every dialog.
7. **Fix the bugs found in the review** (section 10).
8. **A gallery tool** renders every screen in every skin x theme at several sizes, so new skins can be checked in minutes.

## 3. Non-goals

- New features beyond the skin/theme editor (no new audio features, no new effect types).
- Light themes. The system must support them, but all built-in themes stay dark in this pass; a light theme is a natural first follow-up.
- Loading third-party skin *code*. Custom skins/themes are data files only (section 6).
- Animations beyond what exists (meter motion, hover/press feedback).

## 4. Anti-goals (would make this a failure even if it "works")

- Any skin x theme combination that is visibly worse than the default (clipped text, unreadable contrast, misaligned edges).
- A custom theme that can make text unreadable or make status colours lie (e.g. a green Panic button).
- Losing a user's current look on upgrade.
- Making the audio path slower: repaint and theme work must stay off the audio thread and not raise idle CPU.
- Generic "AI-looking" controls: stock rounded rectangles with emoji or typed arrows (`<`, `▲`, `x`) as icons.

## 5. Current state (measured 2026-10-16)

- `mandible/gui.py`: ~5,900 lines holding theme data, the stylesheet builder (~560 lines), ~25 custom widgets, all dialogs and the main window.
- 569 hard-coded hex colours (213 distinct) in `gui.py`; 88 inline `setStyleSheet` calls; 10 custom `paintEvent`s; 13 branches on `current_skin()`.
- `THEMES` dict: 4 themes x 16 colour keys. Theme display names include a trademark ("Focusrite Scarlet & Matte Obsidian").
- Config fields: `ui_skin` (skeuomorphic | vintage | minimal), `theme` (scarlet | cyan | stealth | amber), `chassis_frame` (auto | metal_rack | wood_cheeks | frameless), `switch_style` (bat_toggle | rocker).
- Minimum window width is forced to 2,033 px by the header strip (`masterHeadStrip`, minimum 1,953 px).

## 6. Decisions made with the owner

| Topic | Decision |
|---|---|
| Skins | Keep all three and bring each to the same standard; more will be added later. |
| What a skin is | A complete, tested look: frame, switches, knobs, meters, panel materials, screws, density. Chassis frame and switch style stop being separate settings. |
| Customization | Settings shows one skin picker plus a *Customize...* button. The editor swaps individual elements, previews live, and saves the combination under a user-chosen name. Saved skins appear in the picker. |
| Built-ins | Cannot be overwritten; customizing a built-in starts a copy. |
| Colours | Custom colours are in scope. Simple mode: accent + optional background tint, full palette derived. Advanced mode: every colour editable. Contrast is checked and nudged with a visible notice. |
| Status colours | OK / warning / danger keep their meaning; only adjusted for readability, never freely recoloured. |
| Light themes | Supported by the system, none built-in this pass. |
| Sharing | Custom skins and themes export/import as files. |
| Release | v0.1.0 is published only after all eight stages in section 11 are done, Customize and custom colours included. The existing v0.1.0 draft release and tag (built before this pass) will be replaced, with the owner's go-ahead at that time. |

## 7. Design

### 7.1 Two independent layers: Palette (colour) and Skin (material/shape)

**Palette** (a colour theme): a flat set of named colour tokens.

| Group | Tokens |
|---|---|
| Surfaces | `bg.window`, `bg.panel`, `bg.raised`, `bg.inset`, `bg.overlay` |
| Lines | `line.subtle`, `line.strong`, `focus.ring` |
| Text | `text.primary`, `text.secondary`, `text.disabled`, `text.on_accent` |
| Accent | `accent`, `accent.hover`, `accent.pressed`, `accent.subtle` (tinted background) |
| Status (fixed hues) | `status.ok`, `status.warn`, `status.danger`, each with `.subtle` |
| Meters | `meter.low`, `meter.mid`, `meter.high`, `meter.off` |
| Readouts | `readout.text` (the VFD/LCD figures) |

**Skin**: element choices plus shape/material tokens.

| Element slot | Variants (initial) |
|---|---|
| `frame` | metal_rack, wood_cheeks, frameless |
| `switch` | bat_toggle, rocker, pill (the minimal skin's switch) |
| `knob` | machined, vintage_bakelite, flat_ring |
| `meter` | led_segments, smooth_bar |
| `panel` | brushed, lacquer, flat (how raised/inset surfaces are shaded) |
| `screws` | corners_only, none |
| `density` | compact, comfortable (feeds the spacing scale) |

Shape tokens: `radius.control`, `radius.panel`, `border.width`, `shadow.depth` (0-2), `font.display`, `font.readout`.

Built-in skins are presets over these slots:

| Skin | frame | switch | knob | meter | panel | screws | density |
|---|---|---|---|---|---|---|---|
| Skeuomorphic (default) | metal_rack | bat_toggle | machined | led_segments | brushed | corners_only | comfortable |
| Vintage | wood_cheeks | rocker | vintage_bakelite | led_segments | lacquer | corners_only | comfortable |
| Minimal | frameless | pill | flat_ring | smooth_bar | flat | none | compact |

Each element variant is a small class registered in a registry keyed by slot, with one `paint(painter, rect, state, look)` (or a QSS fragment for style-only variants). A new skin that adds a variant makes it available to every skin in Customize automatically.

### 7.2 The `Look` object and how widgets use it

- `Look = (Palette, Skin)`, immutable. One current `Look` lives in a small `ui/look.py` module, with `current_look()` and a Qt signal `lookChanged`.
- **Stylesheet:** generated from the `Look` by one builder, replacing the 560-line `build_stylesheet` and all 88 inline `setStyleSheet` calls. Widgets set `objectName`/dynamic properties (e.g. `tier="primary"`, `state="active"`) instead of inline styles.
- **Custom painting:** every `paintEvent` takes colours/shapes from `current_look()`; skin-dependent drawing goes through the element registry. The 13 `current_skin()` branches disappear.
- **Switching looks:** apply the stylesheet once at app level, emit `lookChanged`, custom-painted widgets `update()`. Target: under 150 ms on the sample setup, no audio dropouts (look changes never touch the audio engine).
- **Rule enforced in review and by a check script:** no hex literals or `setStyleSheet` calls outside `mandible/ui/look*` and `mandible/branding.py`.

### 7.3 Palette generation and contrast

- Simple mode inputs: `accent` (any colour), `tint` (neutral, warm, cool, or a picked hue at low chroma), and the theme's light/dark flag (dark for now).
- Derivation works in OKLCH: surfaces are fixed lightness steps at the tint's hue and a low chroma; text levels are fixed lightness steps; accent hover/pressed/subtle are lightness/chroma offsets of the accent.
- Contrast targets (WCAG 2.x): body and label text >= 4.5:1 on its surface; large text, icons, borders of interactive controls and focus rings >= 3:1. If a picked accent fails as a button fill with `text.on_accent`, `text.on_accent` flips between near-white and near-black; if the accent fails 3:1 against `bg.panel`, its lightness is nudged until it passes, and the editor shows "Adjusted for readability" next to the swatch.
- Status hues are fixed (green / amber / red families); only their lightness adapts to the surfaces.
- Advanced mode shows every token with its contrast ratio against its partner surface and a warning badge when below target. Saving with warnings is allowed but the warning stays visible in the editor.
- Implementation note: OKLCH conversion is ~40 lines of maths; no new dependency.

### 7.4 Customize editor

- Opened from Settings > Appearance > *Customize...*. Non-modal side panel docked to the main window so the real UI is the live preview (no separate mock).
- **Elements** section: one row per slot with the variants as visual tiles (a rendered thumbnail of that element).
- **Colours** section: accent picker, tint chips, Advanced toggle (token list with swatches and contrast ratios).
- Header: name field, *Save as new*, *Save* (disabled for built-ins), *Revert*, *Export...*, *Import...*, *Delete* (user items only).
- Closing with unsaved changes asks: Save / Discard / Keep editing (built into the panel, not an OS dialog).

### 7.5 Storage, files and migration

- User items: `%APPDATA%\Xen10\Mandible\skins\<slug>.json` and `...\themes\<slug>.json`.
- Export/import file extensions: `.mandibleskin` and `.mandibletheme` (JSON inside). Import validates against a schema, ignores unknown keys, rejects unknown element variants with a clear message, and never executes anything.
- Schema carries `format` (`Mandible.Skin` / `Mandible.Theme`) and `version: 1`.
- Config: `ui_skin` and `theme` now hold an id that may be built-in or user. `chassis_frame` and `switch_style` are migrated once: if a user's saved values differ from their skin's defaults, Mandible creates a user skin named "<Skin> (my settings)" containing those choices and selects it, so nobody's look changes on upgrade. The old fields are then ignored (kept for one release for downgrade safety).
- Built-in theme ids stay (`scarlet`, `cyan`, `stealth`, `amber`); display names become trademark-free: Scarlet, Cyan, Stealth, Amber.

### 7.6 Layout

Target minimum window: **1024 x 640**. Must render without clipping or horizontal overflow at 1024, 1280, 1600, 1920 and 2560 px wide, and at 640, 720, 900 and 1080 px tall, at 100/125/150 % scaling.

- **Header:** three zones. Left (fixed): power, logo mark, status readout. Middle (flexible): signal-flow strip; below ~1,400 px its steps drop to icons with tooltips, below ~1,100 px it hides. Right (fixed): Test mic, Monitor, Panic, Settings, Help; below ~1,180 px Test mic and Monitor fold into an overflow menu.
- **Left panel:** a splitter (default 300 px, 240 to 420 px), remembered in config. Title on its own row; Factory/Import/Export become one menu button.
- **Channel strips:** collapse to thin meters automatically when the window is under 800 px tall (the user's collapse toggle still wins when set).
- **Bottom stray row** (idle mode, hotkeys, all-off key) moves into the header status zone and Settings.
- **Plugin cards:** action buttons right-aligned in a fixed-width cluster; name/badges elide with tooltip; knob titles abbreviate on word boundaries with full name in tooltip.
- Every top-level layout uses the spacing scale; no fixed pixel widths except icons and meters.

### 7.7 Control system

- **Buttons, three tiers:** *Primary* (filled accent, at most one per view: Insert Plugin, dialog OK/Save, wizard Next); *Secondary* (outlined); *Quiet* (icon or text, no border until hover: row tools such as move, remove, map, open UI). Plus *Danger* (Panic, Delete) which uses `status.danger`.
- **Icons:** one vector set drawn from path data in `mandible/ui/icons.py` (power, mic, monitor, panic, settings, help, plus, menu, up, down, remove, map, open-window, play, stop, record, hotkey, chevrons). No typed characters as icons.
- **Status pills** (signal-flow steps, badges) have a different shape and no hover, so status never looks clickable.
- **Type scale:** 3 text sizes (11, 13, 16 px at 100 %) plus readout mono (11 px); nothing below 10 px. Uppercase with letter-spacing only for section labels and readouts; buttons and body in sentence case.
- **Spacing scale:** 4, 8, 12, 16, 24 (compact density maps 16 to 12 and 24 to 16).
- **States:** hover, pressed, focus (visible `focus.ring`), disabled, active; identical rules for every control in every skin.
- **The new mark** appears in the header left zone.

### 7.8 Dialogs

Settings, Soundboard, Mic cleanup (Pre-FX), Knob mapping, Hotkey, Add plugin and About use the same components. The Setup Assistant is the reference. Settings switches from top tabs to a left section list (Audio, Push-to-talk, Output safety, MIDI, Overlay, Appearance, General, Local API); the new **Appearance** section holds the skin and theme pickers and *Customize...*.

### 7.9 Code structure

`gui.py` is split as part of this work (it is touched everywhere anyway):

```
mandible/ui/
  look.py          Palette, Skin, Look, current_look(), lookChanged
  palette_gen.py   OKLCH maths, palette derivation, contrast checks
  stylesheet.py    QSS generated from a Look
  elements/        registry + variants: frames, switches, knobs, meters, panels
  icons.py         vector icon set
  widgets/         meters, knobs, switches, cards, strips, header
  dialogs/         settings, soundboard, prefx, param_map, hotkey, add_plugin, customize
  main_window.py
mandible/gui.py    thin compatibility shim (main() entry), removed once nothing imports it
```

### 7.10 Gallery tool

`tools/ui_gallery.py` renders the main window and every dialog in every skin x theme (built-in plus any in a given folder) at 1024x640, 1280x720 and 1920x1080, off-screen with a fixed sample setup, into one HTML contact sheet. It also reports minimum sizes, widgets overflowing their parent, and token contrast failures. CI runs it on pull requests and uploads the sheet as an artifact (no pass/fail on looks; it fails only on overflow or contrast errors).

## 8. Constraints

- Python 3.13, PySide6 6.12 (LGPL). No new third-party dependencies; if one becomes necessary it follows CLAUDE.md (open source, GPL-3.0-compatible, added to THIRD_PARTY_NOTICES.txt).
- Windows only; must look right at 100/125/150 % DPI scaling.
- Idle CPU must not rise: painting stays event-driven; meter repaint rules from the audit fixes stay.
- Config and preset files remain backward compatible (section 7.5).
- The "VST" trademark rules in CLAUDE.md apply to all new copy (describe as "VST3 plugins"; never in skin/theme/product names).

## 9. The "same standard" checklist (per skin x theme)

A combination is done when, in the gallery at all three sizes:

1. No clipped, overlapping or truncated-without-tooltip text; nothing past a parent's edge.
2. All text and icon contrast meets section 7.3.
3. Every button belongs to one of the tiers in 7.7 and shows all five states.
4. Edges of sibling panels align; spacing uses only the scale.
5. No decorative element without a function, except the skin's chosen frame and corner screws.
6. Meters, knobs and switches are legible at the window's minimum size.
7. The look switches live without restart and without audio dropouts.

## 10. Bugs to fix in this pass (from the review)

1. Header forces a 2,033 px minimum width (section 7.6).
2. "RNNOISE: ON" pill reports any pre-FX stage; becomes "Pre-FX" with per-stage tooltip.
3. Plugin card latency always shows 0 ms (reads a non-existent attribute); use the plugin's reported latency.
4. Built-in effects show a "VST3" badge and an "Open UI" button; show "Built-in" and hide Open UI.
5. "Limiter & Normalizer" tab renders as "Limiter _Normalizer" (escape `&`).
6. Soundboard row buttons are clipped by row height; selected-row highlight conflicts with "No clip selected".
7. Channel strip falls back to the word "Focusrite" when no input device is set.
8. Empty bordered boxes in the chain header (hidden gain/dry-wet controls).
9. Knob titles truncate at 9 characters without tooltip.
10. Knob mapping dialog calls built-in parameters "VST parameters".

## 11. Order of work

1. `ui/look.py`, `palette_gen.py`, stylesheet builder, element registry; port the 4 themes and 3 skins to data with no visual change intended. Gallery tool lands here to compare before/after.
2. Split `gui.py` into `mandible/ui/` and remove literals and inline styles (check script enforces).
3. Layout (7.6) and the bugs in section 10.
4. Control system and icons (7.7) across the main window.
5. Bring each skin to the checklist (9), skin by skin.
6. Dialogs (7.8), including the Appearance section.
7. Customize editor, storage, import/export and migration (7.4, 7.5).
8. CI gallery job; CLAUDE.md rules for adding skins/themes.

## 12. Left to the builder

- Exact element variant visuals within each skin's character, judged against the checklist.
- Icon drawings, provided they share one stroke weight and grid.
- Exact breakpoints, within the ranges given.
- Internal APIs of the element registry, provided a new variant is one class plus one registry entry.

## 13. Builder's calls (made while writing; flag any you disagree with)

- File extensions `.mandibleskin` / `.mandibletheme`.
- Built-in theme display names: Scarlet, Cyan, Stealth, Amber.
- Minimal skin gets a new `pill` switch variant (today it reuses the toggle drawing).
- Settings moves from top tabs to a section list.
- The Customize editor is a docked side panel, so the real window is the preview.
- Test mic and Monitor fold into an overflow menu below ~1,180 px.
- Fonts stay Windows system fonts (Segoe UI for text, Consolas/Cascadia Mono for readouts); no bundled fonts, so no new license to carry.
- The in-game overlay and the tray icon's active colour follow the current palette's `accent`.
- The Setup Assistant moves onto the same tokens and components (it keeps its layout, which the review rated best).
