# Mandible Add-ons Roadmap & Specifications

This document tracks active development, specifications, and planned future work for official and community add-ons for **Mandible** by **Xen10 Industries**.

---

## 1. Active Development: Mandible Clarity (`mandible-clarity`)

- **Status:** In Design & Implementation
- **Category:** Audio DSP / AI Pre-FX Sidecar
- **Purpose:** Next-generation studio AI noise suppression and acoustic dereverberation (removing room echo, air conditioning, and harsh mechanical keyboard clatter) for vocal microphones.
- **Underlying Technology:** DeepFilterNet3 / ONNX neural speech enhancement.
- **Architecture:**
  - **Sidecar / CLI:** Standalone companion executable / Python package (`mandible_clarity`) capable of running on CUDA GPU or DirectML / CPU with low latency.
  - **In-App Integration:** Integrated into Mandible's **Mic cleanup** (`PreFXProcessor` and `PreFXDialog`). Users can choose between **RNNoise** (ultra-lightweight built-in CPU filter) and **Mandible Clarity** (deep neural de-noise + de-reverb).
  - **Add-on Manager:** Built-in one-click downloader and detector dialog (`ClarityAddonDialog`) following the same seamless workflow as the Mandible RVC add-on.

---

## 2. Queued for Future Sessions / Backlog

The following add-on projects are scoped and ready for implementation in upcoming sprints:

### A. Elgato Stream Deck Plugin (`mandible-streamdeck`)
- **Status:** Backlog / Queued
- **Category:** Hardware Controller Integration
- **Target Audience:** Streamers, VTubers, podcasters, gamers.
- **Tech Stack:** JavaScript / TypeScript (Elgato Stream Deck SDK v6+).
- **Core Features:**
  - **Voice Chain Grid:** Keys dynamically populated from Mandible's active rack presets. Shows active state with theme accent borders and titles.
  - **Mute / Panic Controls:** Instant one-tap PTT/Mute toggle with visual mic mute indicators; emergency Panic bypass (kills all active FX and soundboard audio).
  - **Soundboard Trigger Keys:** Grid keys for firing assigned sound clips with live playback animation.
  - **Stream Deck + Dial Support:** Rotary encoders mapped to rack master volume, wet/dry mix, or selected plugin parameters (pitch, cutoff, drive).
- **Mandible REST API Endpoints Used:**
  - `GET /api/status` & `GET /api/chains`
  - `POST /api/chains/select` (`{"id": "<chain_id>"}`)
  - `POST /api/mute` (`{"muted": true|false}`)
  - `POST /api/panic`
  - `GET /api/soundboard` & `POST /api/soundboard/play`

---

### F. Community Preset & Soundboard Pack Hub (`mandible-community-presets`)
- **Status:** Backlog / Queued
- **Category:** Community Content / Cloud Hub
- **Purpose:** Provide an in-app browser for discovering, previewing, and importing curated vocal chains and soundboard packs.
- **Repository Structure:** GitHub repository (e.g. `Xen10-Industries/mandible-community-presets`) hosting a versioned `presets.json` manifest and `.mandible` / `.zip` assets in GitHub Releases (mirroring `mandible-voice-models`).
- **Core Features:**
  - **In-App Preset Hub Dialog:** Tabbed browser for "Vocal Chains" (Sci-Fi, Radio/Comms, Monster/Creature, Studio Voice) and "Soundboard Packs" (Game SFX, Stream Alerts, Memes).
  - **Audio Preview:** Embedded short sample auditions to hear the chain in action before downloading.
  - **One-Click Install:** Automatically extracts and places `.mandible` files into `%APPDATA%\Xen10\Mandible\presets\` and soundboard clips into `%APPDATA%\Xen10\Mandible\soundboard\`.

---

### G. Skin & Theme Community Gallery (`mandible-skins`)
- **Status:** Backlog / Queued
- **Category:** Community Content / UI Customization
- **Purpose:** An online and in-app gallery for sharing custom Mandible looks (`.mandiblelook` files created with the **Customize** panel).
- **Format:**
  - Standard JSON manifest (`skins.json`) indexing skin packs, author info, tags (Retro, Cyberpunk, Studio Skeuomorphic, OLED Dark), and preview screenshot URLs.
- **Core Features:**
  - **Gallery Dialog:** Visual grid showing cards with rendered look screenshots.
  - **Live Preview & Apply:** Applies skin palette tokens, knob styles, switch types, and frame textures instantly via `mandible.ui.look.set_look()`.
  - **Export to Hub:** Export button in the Customize dialog to package the current user look with a thumbnail for submission.
