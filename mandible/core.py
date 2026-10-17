"""App core: owns config, audio engine, plugin instances, hotkeys, MIDI, overlay, and soundboard."""
from __future__ import annotations

import copy
import threading
import time
from functools import partial

from PySide6.QtCore import QObject, QTimer, Signal

from . import plugins as P
from .audio_engine import DRY_ID, AudioEngine, ChainRuntime, db_to_lin
from .config import AppConfig, Chain, PluginSlot, SoundboardClipConfig, save_config
from .hotkeys import HotkeyManager
from .midi import MidiManager
from .overlay import VoiceOverlay
from .soundboard import SoundboardClip
from .api import ApiManager
from .ui.look import current_look, look_from_config, set_look


def inst(slot: PluginSlot):
    return getattr(slot, "_instance", None)


def slot_error(slot: PluginSlot) -> str:
    return getattr(slot, "_error", "")


class Core(QObject):
    activeChanged = Signal()
    engineStopped = Signal(str)
    soundboardChanged = Signal()
    pluginBypassChanged = Signal(str)           # chain_id when a slot bypass hotkey toggles
    gainsChanged = Signal()                     # emitted when MIDI CC changes input/output/monitor gain
    midiMessageReceived = Signal(str, int, int) # (event_type, note_or_cc, channel) for MIDI Learn UI
    _overlaySyncRequested = Signal()
    _saveRequested = Signal()
    auditionProgress = Signal(str, float, float)  # (state, cur_sec, total_sec)

    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self.engine = AudioEngine()
        self.engine.on_stopped = lambda reason: self.engineStopped.emit(reason)
        self.engine.in_gain = db_to_lin(cfg.input_gain_db)
        self.engine.out_gain = db_to_lin(cfg.output_gain_db)
        self.engine.monitor_enabled = cfg.monitor_enabled
        self.engine.monitor_gain = db_to_lin(cfg.monitor_gain_db)
        self.engine.monitor_mode = cfg.headphone_monitor_mode
        self.engine.keep_awake = cfg.keep_chains_awake
        self.engine.crossfade_ms = cfg.crossfade_ms
        self.engine.update_prefx(cfg.prefx)
        self.engine.update_limiter(cfg.limiter)
        self.engine.ptt_muted = (cfg.ptt.mode == "push_to_talk")
        self.engine.soundboard_ducking_enabled = getattr(cfg, "soundboard_ducking_enabled", False)
        self.engine.soundboard_duck_db = getattr(cfg, "soundboard_duck_db", -12.0)
        self.engine.normalizer_enabled = getattr(cfg, "normalizer_enabled", False)
        self.engine.normalizer_target_db = getattr(cfg, "normalizer_target_db", -14.0)

        self.hotkeys = HotkeyManager()
        self.hotkeys.enabled = cfg.hotkeys_enabled

        self.midi = MidiManager()
        self._midi_cc_down: dict[tuple, bool] = {}
        self.overlay = VoiceOverlay(cfg.overlay.position, cfg.overlay.opacity)

        self._toggled: str | None = None
        self._holds: list[str] = []
        self._ctl_lock = threading.Lock()

        # Objects the audio thread may still reference are kept alive briefly and
        # released on the GUI thread, so a VST is never destroyed in the audio callback.
        self._graveyard: list[tuple[float, object]] = []
        self._gc_timer = QTimer(self)
        self._gc_timer.timeout.connect(self._purge_graveyard)
        self._gc_timer.start(1000)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_now)
        self._saveRequested.connect(self._start_save_timer)

        self._overlaySyncRequested.connect(self._do_sync_overlay)
        self.activeChanged.connect(self._do_sync_overlay)
        self._init_midi()
        self._do_sync_overlay()

        # Local Web API for Stream Deck / OBS
        self.api = ApiManager(self)
        if getattr(cfg, "api_enabled", False):
            self.api.start(getattr(cfg, "api_port", 38420))

        # Audition polling timer
        self._audition_timer = QTimer(self)
        self._audition_timer.timeout.connect(self._poll_audition)
        self._audition_timer.start(50)

    # =========================================================== persistence
    def _start_save_timer(self):
        self._save_timer.start(400)

    def save(self):
        """Thread-safe debounced save."""
        self._saveRequested.emit()


    def save_now(self):
        self._save_timer.stop()
        try:
            save_config(self.cfg)
        except Exception as exc:
            print(f"[Mandible] failed to save config: {exc}")

    def capture_all_states(self):
        for c in self.cfg.chains:
            for s in c.plugins:
                if inst(s) is not None:
                    st = P.capture_state(inst(s))
                    if st:
                        s.state = st

    # =========================================================== chains
    def chain_by_id(self, cid: str) -> Chain | None:
        return next((c for c in self.cfg.chains if c.id == cid), None)

    def load_all(self, progress=None):
        total = sum(len(c.plugins) for c in self.cfg.chains) or 1
        n = 0
        for c in self.cfg.chains:
            for s in c.plugins:
                if progress:
                    progress(n, total, s.display_name or s.path)
                self._load(s)
                n += 1
            self.rebuild(c)
        self.rebind_hotkeys()
        self._apply()

    def _load(self, slot: PluginSlot) -> bool:
        try:
            slot._instance = P.load_slot(slot)
            slot._error = ""
            self.engine.prewarm(slot._instance)
            return True
        except Exception as exc:
            slot._instance = None
            slot._error = str(exc) or exc.__class__.__name__
            return False

    def rebuild(self, chain: Chain):
        live = [inst(s) for s in chain.plugins if s.enabled and inst(s) is not None]
        board = P.make_board(live)
        chain.latency_samples = P.get_chain_latency_samples(chain)
        for s in chain.plugins:
            if not hasattr(s, "_pre_peak"):
                s._pre_peak = 0.0
            if not hasattr(s, "_post_peak"):
                s._post_peak = 0.0
            if not s.enabled:
                s._post_peak = 0.0
        rt = ChainRuntime(
            chain.id,
            board,
            db_to_lin(chain.gain_db),
            float(chain.tail_s),
            float(getattr(chain, "dry_wet", 1.0)),
            chain.latency_samples,
            slots=tuple(chain.plugins),
        )
        self._retire(self.engine.runtime(chain.id))
        self.engine.set_runtime(rt)

    def save_plugin_param_mapping(self, slot: PluginSlot, param_keys: list[str]):
        """Save a persistent parameter knob mapping for this VST plugin across all presets."""
        mkey = P.plugin_mapping_key(slot)
        if not hasattr(self.cfg, "plugin_param_mappings") or self.cfg.plugin_param_mappings is None:
            self.cfg.plugin_param_mappings = {}
        self.cfg.plugin_param_mappings[mkey] = list(param_keys)
        slot.mapped_params = None  # follow global mapping for this plugin
        self.save()


    def update_chain_params(self, chain: Chain):
        rt = self.engine.runtime(chain.id)
        if rt is not None:
            rt.gain = db_to_lin(chain.gain_db)
            rt.tail_s = float(chain.tail_s)
            rt.dry_wet = float(getattr(chain, "dry_wet", 1.0))
        self.save()

    def add_chain(self, name: str) -> Chain:
        c = Chain(name=name)
        self.cfg.chains.append(c)
        self.rebuild(c)
        self.rebind_hotkeys()
        self.save()
        return c

    def duplicate_chain(self, chain: Chain) -> Chain:
        self.capture_all_states()
        c = Chain(
            name=chain.name + " copy",
            mode=chain.mode,
            gain_db=chain.gain_db,
            tail_s=chain.tail_s,
            dry_wet=getattr(chain, "dry_wet", 1.0),
            plugins=[copy.copy(s) for s in chain.plugins],
        )
        for s in c.plugins:
            s.__dict__.pop("_instance", None)
            s.__dict__.pop("_error", None)
            self._load(s)
        self.cfg.chains.append(c)
        self.rebuild(c)
        self.rebind_hotkeys()
        self.save()
        return c

    def export_chain(self, chain: Chain, file_path: str) -> None:
        from .config import export_chain_preset
        self.capture_all_states()
        export_chain_preset(chain, self.cfg, file_path)

    def import_chain(self, file_path: str) -> Chain:
        from .config import Hotkey, import_chain_preset
        c = import_chain_preset(file_path, self.cfg)
        if c.hotkey.is_set() and self.find_hotkey_conflict(c.hotkey):
            c.hotkey = Hotkey()
        for s in c.plugins:
            if s.bypass_hotkey.is_set() and self.find_hotkey_conflict(s.bypass_hotkey):
                s.bypass_hotkey = Hotkey()
            self._load(s)
        self.cfg.chains.append(c)
        self.rebuild(c)
        self.rebind_hotkeys()
        self.save()
        return c


    def delete_chain(self, chain: Chain):
        with self._ctl_lock:
            if self._toggled == chain.id:
                self._toggled = None
            self._holds = [h for h in self._holds if h != chain.id]
        self._retire(self.engine.runtime(chain.id))
        self.engine.remove_runtime(chain.id)
        for s in chain.plugins:
            self._retire(inst(s))
            s._instance = None
        self.cfg.chains.remove(chain)
        if self.cfg.idle_mode == chain.id:
            self.cfg.idle_mode = "dry"
        self.rebind_hotkeys()
        self._apply()
        self.save()

    def move_chain(self, chain: Chain, delta: int):
        lst = self.cfg.chains
        i = lst.index(chain)
        j = max(0, min(len(lst) - 1, i + delta))
        lst.insert(j, lst.pop(i))
        self.save()

    # =========================================================== plugins
    def add_plugin(self, chain: Chain, path: str, plugin_name: str = "") -> PluginSlot:
        slot = PluginSlot(path=path, plugin_name=plugin_name, display_name=plugin_name)
        ok = self._load(slot)
        chain.plugins.append(slot)
        if ok:
            slot.state = P.capture_state(inst(slot))
        self.rebuild(chain)
        self.rebind_hotkeys()
        self.save()
        return slot

    def remove_plugin(self, chain: Chain, slot: PluginSlot):
        chain.plugins.remove(slot)
        self.rebuild(chain)
        self.rebind_hotkeys()
        self._retire(inst(slot))
        slot._instance = None
        self.save()

    def move_plugin(self, chain: Chain, slot: PluginSlot, delta: int):
        lst = chain.plugins
        i = lst.index(slot)
        j = max(0, min(len(lst) - 1, i + delta))
        lst.insert(j, lst.pop(i))
        self.rebuild(chain)
        self.save()

    def set_plugin_enabled(self, chain: Chain, slot: PluginSlot, enabled: bool):
        slot.enabled = enabled
        self.rebuild(chain)
        self.save()

    def toggle_plugin_bypass(self, chain: Chain, slot: PluginSlot):
        slot.enabled = not slot.enabled
        self.rebuild(chain)
        self.save()
        self.pluginBypassChanged.emit(chain.id)

    # =========================================================== activation
    def _idle_target(self) -> str | None:
        m = self.cfg.idle_mode
        if m == "mute":
            return None
        if m != "dry" and self.chain_by_id(m) is not None:
            return m
        return DRY_ID

    def target(self) -> str | None:
        with self._ctl_lock:
            if self._holds:
                return self._holds[-1]
            if self._toggled:
                return self._toggled
        return self._idle_target()

    def press(self, cid: str):
        chain = self.chain_by_id(cid)
        if chain is None:
            return
        with self._ctl_lock:
            if chain.mode == "hold":
                if cid not in self._holds:
                    self._holds.append(cid)
            else:
                self._toggled = None if self._toggled == cid else cid
        self._apply()

    def release(self, cid: str):
        with self._ctl_lock:
            if cid not in self._holds:
                return
            self._holds.remove(cid)
        self._apply()

    def panic(self):
        with self._ctl_lock:
            self._toggled = None
            self._holds.clear()
        self.engine.soundboard.stop_all()
        self._apply()

    def select_clean(self):
        """Release every toggled/held chain (like panic, but leaves the soundboard playing)."""
        with self._ctl_lock:
            self._toggled = None
            self._holds.clear()
        self._apply()

    def clear_chain_state(self, cid: str):
        with self._ctl_lock:
            if self._toggled == cid:
                self._toggled = None
            self._holds = [h for h in self._holds if h != cid]
        self._apply()

    def _apply(self):
        self.engine.set_target(self.target())
        self.activeChanged.emit()

    # =========================================================== Push to Talk
    def ptt_press(self):
        mode = self.cfg.ptt.mode
        if mode == "push_to_talk":
            self.engine.ptt_muted = False
        elif mode == "push_to_mute":
            self.engine.ptt_muted = True
        self._sync_overlay()

    def ptt_release(self):
        mode = self.cfg.ptt.mode
        if mode == "push_to_talk":
            self.engine.ptt_muted = True
        elif mode == "push_to_mute":
            self.engine.ptt_muted = False
        self._sync_overlay()

    def update_ptt_mode(self, mode: str):
        self.cfg.ptt.mode = mode
        self.engine.ptt_muted = (mode == "push_to_talk")
        self.save()
        self._sync_overlay()

    # =========================================================== soundboard
    def play_soundboard(self, clip_cfg: SoundboardClipConfig):
        clip = SoundboardClip(
            id=clip_cfg.id,
            name=clip_cfg.name,
            path=clip_cfg.path,
            volume_db=clip_cfg.volume_db,
            loop=clip_cfg.loop,
            route_output=clip_cfg.route_output,
            route_monitor=clip_cfg.route_monitor,
            trim_start_s=getattr(clip_cfg, "trim_start_s", 0.0),
            trim_end_s=getattr(clip_cfg, "trim_end_s", 0.0),
        )
        self.engine.soundboard.play(clip, target_sr=self.engine.samplerate)
        self.soundboardChanged.emit()

    def stop_soundboard(self, clip_id: str):
        self.engine.soundboard.stop(clip_id)
        self.soundboardChanged.emit()

    def stop_all_soundboard(self):
        self.engine.soundboard.stop_all()
        self.soundboardChanged.emit()

    # =========================================================== MIDI
    def _init_midi(self):
        if self.cfg.midi_device:
            self.midi.open_device(self.cfg.midi_device, self._handle_midi_msg)

    def set_midi_device(self, dev_name: str):
        self.cfg.midi_device = dev_name
        self.midi.open_device(dev_name, self._handle_midi_msg)
        self.save()

    _CONTINUOUS_ACTIONS = ("monitor_vol", "out_vol", "in_vol")

    def _handle_midi_msg(self, status: int, data1: int, data2: int):
        kind = status & 0xF0
        ch = (status & 0x0F) + 1
        # Note Off arrives as 0x80, or as Note On with velocity 0 (running status).
        if kind == 0x80 or (kind == 0x90 and data2 == 0):
            for b in self.cfg.midi_bindings:
                if b.event_type == "note_on" and b.note_or_cc == data1 and b.channel in (0, ch):
                    self._release_action(b.action)
            return
        msg_type = "note_on" if kind == 0x90 else ("cc" if kind == 0xB0 else None)
        if not msg_type:
            return
        self.midiMessageReceived.emit(msg_type, int(data1), int(ch))

        for b in self.cfg.midi_bindings:
            if b.event_type != msg_type or b.note_or_cc != data1 or b.channel not in (0, ch):
                continue
            if msg_type == "cc" and b.action not in self._CONTINUOUS_ACTIONS:
                # Knobs/faders/CC buttons send a stream of values: treat >= 64 as "down" and only
                # act when the control crosses the midpoint, instead of on every message.
                key = (b.note_or_cc, b.channel, b.action)
                down = data2 >= 64
                if down == self._midi_cc_down.get(key, False):
                    continue
                self._midi_cc_down[key] = down
                if not down:
                    self._release_action(b.action)
                    continue
            self._execute_action(b.action, data2)

    def _release_action(self, action: str):
        """Key-up counterpart of _execute_action: releases hold-mode chains."""
        if action.startswith("chain:"):
            self.release(action[len("chain:"):])

    def _execute_action(self, action: str, value: int = 127):
        if not action:
            return
        if action.startswith("chain:"):
            cid = action[len("chain:") :]
            self.press(cid)
        elif action.startswith("soundboard:"):
            s_id = action[len("soundboard:") :]
            clip = next((s for s in self.cfg.soundboard if s.id == s_id), None)
            if clip:
                if self.engine.soundboard.is_playing(s_id):
                    self.stop_soundboard(s_id)
                else:
                    self.play_soundboard(clip)
        elif action == "panic":
            self.panic()
        elif action == "mute":
            self.engine.ptt_muted = not self.engine.ptt_muted
            self._sync_overlay()
        elif action == "monitor_vol":
            # Map MIDI 0-127 to -60 dB .. +12 dB
            db = -60.0 + (value / 127.0) * 72.0
            self.set_monitor_gain(db)
            self.gainsChanged.emit()
        elif action == "out_vol":
            db = -60.0 + (value / 127.0) * 72.0
            self.set_output_gain(db)
            self.gainsChanged.emit()
        elif action == "in_vol":
            db = -60.0 + (value / 127.0) * 72.0
            self.set_input_gain(db)
            self.gainsChanged.emit()

    # =========================================================== overlay
    def _sync_overlay(self):
        """Request an overlay sync safely from any thread (including Win32 hotkey/MIDI callbacks)."""
        self._overlaySyncRequested.emit()

    def _do_sync_overlay(self):
        ov = self.cfg.overlay
        if not ov.enabled:
            self.overlay.hide()
            return

        target = self.target()
        muted = self.engine.ptt_muted or (target is None and self.cfg.idle_mode == "mute")

        if muted:
            text = "MANDIBLE // MIC MUTED"
            is_active = False
        elif target == DRY_ID:
            text = "MANDIBLE // CLEAN"
            is_active = False
        else:
            chain = self.chain_by_id(target) if target else None
            text = f"MANDIBLE // {chain.name.upper() if chain else 'ACTIVE'}"
            is_active = True

        if ov.hide_when_clean and not is_active and not muted:
            self.overlay.hide()
            return

        self.overlay.position = ov.position
        self.overlay.opacity = ov.opacity
        self.overlay.update_status(text, is_active=is_active, is_muted=muted)
        self.overlay.reposition()
        self.overlay.show()


    # =========================================================== hotkeys
    def rebind_hotkeys(self):
        b = [(c.hotkey, partial(self.press, c.id), partial(self.release, c.id)) for c in self.cfg.chains]
        b.append((self.cfg.panic_hotkey, self.panic, None))

        # Push to talk hotkey
        if self.cfg.ptt.hotkey.is_set():
            b.append((self.cfg.ptt.hotkey, self.ptt_press, self.ptt_release))

        # Soundboard clip hotkeys
        for s in self.cfg.soundboard:
            if s.hotkey.is_set():
                b.append((s.hotkey, partial(self._trigger_soundboard_clip, s), None))

        # Individual plugin bypass hotkeys
        for c in self.cfg.chains:
            for slot in c.plugins:
                if slot.bypass_hotkey.is_set():
                    b.append((slot.bypass_hotkey, partial(self.toggle_plugin_bypass, c, slot), None))

        self.hotkeys.set_bindings(b)

    def _trigger_soundboard_clip(self, clip: SoundboardClipConfig):
        if self.engine.soundboard.is_playing(clip.id):
            self.stop_soundboard(clip.id)
        else:
            self.play_soundboard(clip)

    def find_hotkey_conflict(self, hk, exclude=None) -> str | None:
        def same(a):
            return a.is_set() and a.scan_code == hk.scan_code and a.keypad == hk.keypad and set(a.mods) == set(hk.mods)

        for c in self.cfg.chains:
            if c is not exclude and same(c.hotkey):
                return f'chain "{c.name}"'
            for s in c.plugins:
                if s is not exclude and same(s.bypass_hotkey):
                    return f'plugin bypass "{s.display_name}"'

        if exclude is not self.cfg.panic_hotkey and same(self.cfg.panic_hotkey):
            return "the all-off hotkey"

        if exclude is not self.cfg.ptt.hotkey and same(self.cfg.ptt.hotkey):
            return "the Push-to-Talk hotkey"

        for s in self.cfg.soundboard:
            if s is not exclude and same(s.hotkey):
                return f'soundboard clip "{s.name}"'

        return None

    # =========================================================== audio
    def start_audio(self):
        self.engine.start(self.cfg.audio)

    def stop_audio(self):
        self.engine.stop()

    def set_input_gain(self, db: float):
        self.cfg.input_gain_db = db
        self.engine.in_gain = db_to_lin(db)
        self.save()

    def set_output_gain(self, db: float):
        self.cfg.output_gain_db = db
        self.engine.out_gain = db_to_lin(db)
        self.save()

    def set_monitor_enabled(self, enabled: bool):
        self.cfg.monitor_enabled = bool(enabled)
        self.engine.monitor_enabled = bool(enabled)
        self.save()

    def set_monitor_gain(self, db: float):
        self.cfg.monitor_gain_db = db
        self.engine.monitor_gain = db_to_lin(db)
        self.save()

    def set_monitor_mode(self, mode: str):
        self.cfg.headphone_monitor_mode = mode
        self.engine.monitor_mode = mode
        self.save()

    def set_prefx(self, prefx_cfg):
        self.cfg.prefx = prefx_cfg
        self.engine.update_prefx(prefx_cfg)
        self.save()

    def set_limiter(self, lim_cfg):
        self.cfg.limiter = lim_cfg
        self.engine.update_limiter(lim_cfg)
        self.save()

    # Appearance: store the id, then make the Look the config selects current. Changing
    # the look restyles and repaints widgets only; it never touches the audio engine.
    def _apply_look(self):
        look = look_from_config(self.cfg)
        if look != current_look():
            set_look(look)

    def set_theme(self, theme: str):
        self.cfg.theme = theme
        self._apply_look()
        self.save()

    def set_ui_skin(self, skin: str):
        self.cfg.ui_skin = skin
        self._apply_look()
        self.save()

    def set_chassis_frame(self, frame: str):
        self.cfg.chassis_frame = frame
        self._apply_look()
        self.save()

    def set_switch_style(self, style: str):
        self.cfg.switch_style = style
        self._apply_look()
        self.save()

    def set_soundboard_ducking(self, enabled: bool, duck_db: float):
        self.cfg.soundboard_ducking_enabled = bool(enabled)
        self.cfg.soundboard_duck_db = float(duck_db)
        self.engine.soundboard_ducking_enabled = bool(enabled)
        self.engine.soundboard_duck_db = float(duck_db)
        self.save()

    def set_normalizer(self, enabled: bool, target_db: float):
        self.cfg.normalizer_enabled = bool(enabled)
        self.cfg.normalizer_target_db = float(target_db)
        self.engine.normalizer_enabled = bool(enabled)
        self.engine.normalizer_target_db = float(target_db)
        self.save()

    def set_api_enabled(self, enabled: bool, port: int = 38420):
        self.cfg.api_enabled = bool(enabled)
        self.cfg.api_port = int(port)
        if enabled:
            self.api.start(port)
        else:
            self.api.stop()
        self.save()

    # =========================================================== mic audition
    def start_mic_audition(self, duration_s: float = 5.0):
        self.engine.start_mic_audition(duration_s)

    def stop_mic_audition(self):
        self.engine.stop_mic_audition()

    def get_audition_status(self) -> tuple[str, float, float]:
        return self.engine.get_audition_status()

    def _poll_audition(self):
        state, cur, tot = self.engine.get_audition_status()
        if state != "idle":
            self.auditionProgress.emit(state, cur, tot)

    # =========================================================== lifecycle
    def _retire(self, obj):
        if obj is not None:
            self._graveyard.append((time.monotonic(), obj))

    def _purge_graveyard(self):
        cutoff = time.monotonic() - 2.0
        self._graveyard = [(t, o) for t, o in self._graveyard if t > cutoff]

    def shutdown(self):
        self.hotkeys.close()
        self.midi.close()
        self.overlay.close()
        self.api.stop()
        self.capture_all_states()
        self.save_now()
        self.engine.stop()
