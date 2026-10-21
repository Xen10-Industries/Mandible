"""Application settings: a section list on the left, one scrollable page per section."""
from __future__ import annotations

import copy
import os
from types import SimpleNamespace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractScrollArea, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QStackedWidget, QTableWidget,
                               QVBoxLayout, QWidget)

from ... import devices as D
from ...config import APP_DIR, AudioSettings, MidiBinding, is_startup_enabled, set_startup_enabled
from ...core import Core
from ...midi import list_midi_inputs
from ..look import Look, current_look, look_bus, look_from_config, set_look, space
from ..user_looks import all_palettes, all_skins
from ..widgets.base import SpacedLayouts, _follow_look
from ..widgets.buttons import make_button, tier_button_box
from .hotkey import HotkeyDialog
from .parts import check_row, group_label, hint_label
from .setup_assistant import SetupAssistantDialog


MIDI_LEARN_TEXT = "MIDI learn (new binding)…"

# (id, title) in display order. Titles are shown literally by the section list.
SECTIONS = (
    ("audio", "Audio"),
    ("ptt", "Push-to-talk"),
    ("output_safety", "Limiter & Normalizer"),
    ("midi", "MIDI"),
    ("overlay", "Overlay"),
    ("appearance", "Appearance"),
    ("addons", "Add-ons"),
    ("general", "General"),
    ("api", "Local API"),
)


def appearance_skins():
    """The skins the Appearance picker offers: built-ins first, then user skins by name."""
    return tuple(all_skins().values())


def appearance_palettes():
    """The themes the Appearance picker offers: built-ins first, then user themes by name."""
    return tuple(all_palettes().values())


class SettingsDialog(QDialog):
    """Settings in eight sections (see ``SECTIONS``): Up / Down move between sections in the
    list, Tab moves into the page. OK applies (``apply_all``); Cancel reverts the live look."""

    # Customize... asks the main window for the Customize panel. Settings applies its pending
    # changes and closes first (it is modal; the panel is docked to the main window).
    customizeRequested = Signal()

    def __init__(self, core: Core, running: bool, parent=None, initial_section: str = "audio"):
        super().__init__(parent)
        self.core = core
        self.cfg = core.cfg
        self.running = running
        self._orig_look = current_look()   # restored when the dialog is cancelled
        self._spaced = SpacedLayouts()
        self._forms: list[QFormLayout] = []
        _follow_look(self)
        self.setWindowTitle("Settings")
        self.setMinimumSize(640, 420)
        self.resize(780, 540)

        root = self._spaced.add(QVBoxLayout(self), spacing=3, margins=4)
        body = self._spaced.add(QHBoxLayout(), spacing=4, margins=0)
        root.addLayout(body, 1)

        self.sections = QListWidget()
        self.sections.setObjectName("settingsSections")
        self.sections.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sections.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.sections.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.sections.setAccessibleName("Settings sections")
        body.addWidget(self.sections)

        right = self._spaced.add(QVBoxLayout(), spacing=3, margins=0)
        self.section_title = QLabel()
        self.section_title.setObjectName("settingsSectionTitle")
        right.addWidget(self.section_title)
        self.pages = QStackedWidget()
        right.addWidget(self.pages, 1)
        body.addLayout(right, 1)

        builders = {
            "audio": self._build_audio, "ptt": self._build_ptt,
            "output_safety": self._build_output_safety, "midi": self._build_midi,
            "overlay": self._build_overlay, "appearance": self._build_appearance,
            "addons": self._build_addons, "general": self._build_general, "api": self._build_api,
        }
        for sid, title in SECTIONS:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, sid)
            self.sections.addItem(item)
            self.pages.addWidget(self._scrolling(builders[sid]()))

        bb = tier_button_box(QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel))
        root.addWidget(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        # Populate drivers & audio devices
        a = self.cfg.audio
        for sr in (0, 44100, 48000, 88200, 96000):
            self.sr.addItem("Device default" if sr == 0 else f"{sr} Hz", sr)
        self.sr.setCurrentIndex(max(0, self.sr.findData(a.samplerate)))
        for bs in (32, 64, 128, 256, 512, 1024):
            self.bs.addItem(f"{bs} samples", bs)
        self.bs.setCurrentIndex(max(0, self.bs.findData(a.blocksize)))
        self.excl.setChecked(a.wasapi_exclusive)

        self._fill_drivers(a)
        self.driver.currentIndexChanged.connect(lambda _: self._driver_changed(None))
        self.in_dev.currentIndexChanged.connect(lambda _: self._in_changed(None))
        self.out_dev.currentIndexChanged.connect(lambda _: self._out_changed(None))
        self.rescan_btn.clicked.connect(self._rescan)

        self._unify_label_column()
        self.sections.currentRowChanged.connect(self._on_section_row)
        ids = self.section_ids()
        self.sections.setCurrentRow(ids.index(initial_section) if initial_section in ids else 0)
        self._on_section_row(self.sections.currentRow())

    # ------------------------------------------------------------------ sections
    def section_ids(self) -> list[str]:
        return [self.sections.item(i).data(Qt.UserRole) for i in range(self.sections.count())]

    def current_section(self) -> str:
        item = self.sections.currentItem()
        return item.data(Qt.UserRole) if item is not None else ""

    def show_section(self, section_id: str) -> None:
        ids = self.section_ids()
        if section_id in ids:
            self.sections.setCurrentRow(ids.index(section_id))

    def _on_section_row(self, row: int) -> None:
        if 0 <= row < self.pages.count():
            self.pages.setCurrentIndex(row)
            self.section_title.setText(self.sections.item(row).text())

    def _unify_label_column(self) -> None:
        """Every form's label column gets the widest label's width, so the fields start at the
        same x in every section (not only within one)."""
        labels = []
        for form in self._forms:
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.LabelRole)
                if item is not None and isinstance(item.widget(), QLabel):
                    labels.append(item.widget())
        for label in labels:
            label.ensurePolished()
        widest = max((label.sizeHint().width() for label in labels), default=0)
        for label in labels:
            label.setMinimumWidth(widest)

    def _on_look_changed(self) -> None:
        """The previewed look can change the density: re-apply the spacing scale."""
        self._spaced.apply()
        self._apply_form_gaps()
        self.sections.updateGeometry()

    # ------------------------------------------------------------------ page helpers
    @staticmethod
    def _scrolling(content: QWidget) -> QScrollArea:
        """A page: scrolls vertically when taller than the dialog, never clips sideways."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setWidget(content)
        return area

    def _form_page(self) -> tuple[QWidget, QFormLayout]:
        """A page with one form: labels share one column, so fields line up within a section."""
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self._spaced.add(form, margins=(0, 0, 3, 0))
        self._forms.append(form)
        self._apply_form_gaps()
        return page, form

    def _apply_form_gaps(self) -> None:
        # QFormLayout has separate horizontal / vertical spacing, both on the scale.
        for form in self._forms:
            form.setHorizontalSpacing(space(3))
            form.setVerticalSpacing(space(2))

    @staticmethod
    def _combo(minimum_chars: int = 14) -> QComboBox:
        """A combo box that can shrink with the dialog (its text elides), not one that sizes
        itself to its longest entry."""
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(minimum_chars)
        return combo

    def _group(self, form: QFormLayout, text: str) -> None:
        group_label(form, text)

    def _check(self, form: QFormLayout, text: str, checked: bool = False, hint: str = "") -> QCheckBox:
        return check_row(form, text, checked, hint)

    @staticmethod
    def _hint(text: str, indent: bool = False) -> QLabel:
        return hint_label(text, indent)

    def _left(self, *widgets: QWidget) -> QHBoxLayout:
        """A row that keeps its widgets at their natural width, at the left."""
        row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        for w in widgets:
            row.addWidget(w)
        row.addStretch(1)
        return row

    # ------------------------------------------------------------------ Audio
    def _build_audio(self) -> QWidget:
        page, form = self._form_page()
        self.driver = self._combo()
        self.in_dev = self._combo()
        self.in_ch = self._combo()
        self.out_dev = self._combo()
        self.out_ch = self._combo()
        self.mon_dev = self._combo()
        self.mon_ch = self._combo()
        self.mon_mode = self._combo()
        self.mon_mode.addItem("Processed voice (standard effect)", "processed")
        self.mon_mode.addItem("Clean microphone (zero-latency dry voice)", "dry")
        self.mon_mode.addItem("50/50 blend (processed + dry mic)", "mix")
        self.mon_mode.setCurrentIndex(max(0, self.mon_mode.findData(self.cfg.headphone_monitor_mode)))
        self.sr = self._combo(10)
        self.bs = self._combo(10)

        form.addRow("Driver", self.driver)
        form.addRow("Input device", self.in_dev)
        form.addRow("Input channel", self.in_ch)
        self.out_dev_label = QLabel("Output device")
        form.addRow(self.out_dev_label, self.out_dev)
        form.addRow("Output channels", self.out_ch)
        self.mon_dev_label = QLabel("Monitor device")
        form.addRow(self.mon_dev_label, self.mon_dev)
        self.mon_ch_label = QLabel("Monitor channels")
        form.addRow(self.mon_ch_label, self.mon_ch)
        form.addRow("Headphones feed", self.mon_mode)
        form.addRow("Sample rate", self.sr)
        form.addRow("Buffer size", self.bs)

        self.excl = QCheckBox("WASAPI exclusive mode")
        self.excl.setToolTip("Lower latency, but locks the device so other apps cannot use it")
        form.addRow(self.excl)
        self.excl_hint = self._hint("Lower latency, but locks the device so other apps cannot use it.",
                                    indent=True)
        form.addRow(self.excl_hint)

        self.asio_panel_btn = make_button("ASIO driver settings…",
                                          tooltip="Open the ASIO driver's own control panel")
        self.asio_panel_btn.clicked.connect(self._open_asio_panel)
        form.addRow(self._left(self.asio_panel_btn))

        self.rescan_btn = make_button("Rescan devices")
        self.rescan_btn.setEnabled(not self.running)
        wizard_btn = make_button("Run the audio setup assistant…",
                                 tooltip="Step-by-step microphone, virtual cable and headphone setup")
        wizard_btn.setObjectName("audioWizardBtn")
        wizard_btn.clicked.connect(self._launch_setup_assistant)
        form.addRow(self._left(self.rescan_btn, wizard_btn))
        return page

    # ------------------------------------------------------------------ Push-to-talk
    def _build_ptt(self) -> QWidget:
        page, form = self._form_page()
        self.ptt_mode = self._combo()
        self.ptt_mode.addItem("Disabled (mic always active)", "disabled")
        self.ptt_mode.addItem("Push-to-talk (unmute mic while key is held)", "push_to_talk")
        self.ptt_mode.addItem("Push-to-mute (mute mic while key is held)", "push_to_mute")
        self.ptt_mode.setCurrentIndex(max(0, self.ptt_mode.findData(self.cfg.ptt.mode)))

        self.ptt_hk_lbl = QLabel(self.cfg.ptt.hotkey.label if self.cfg.ptt.hotkey.is_set() else "Not set")
        self.ptt_hk_btn = make_button("Set PTT key…", icon="hotkey")
        self.ptt_hk_btn.clicked.connect(self._set_ptt_hotkey)
        hk_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        hk_row.addWidget(self.ptt_hk_lbl, 1)
        hk_row.addWidget(self.ptt_hk_btn)

        form.addRow("Microphone mode", self.ptt_mode)
        form.addRow("Hotkey", hk_row)
        return page

    # ------------------------------------------------------------------ Limiter & Normalizer
    def _build_output_safety(self) -> QWidget:
        page, form = self._form_page()
        self._group(form, "Limiter")
        self.lim_en = self._check(form, "Enable limiter", self.cfg.limiter.enabled,
                                  "Catches peaks above the ceiling so nothing clips into Discord and "
                                  "OBS. Everything below the ceiling passes unchanged.")
        self.lim_thresh = QDoubleSpinBox()
        self.lim_thresh.setRange(-12.0, 0.0)
        self.lim_thresh.setSingleStep(0.5)
        self.lim_thresh.setValue(self.cfg.limiter.threshold_db)
        self.lim_thresh.setSuffix(" dB")
        form.addRow("Ceiling", self.lim_thresh)
        self.lim_boost = self._check(form, "Loudness boost", getattr(self.cfg.limiter, "boost", False),
                                     "Raises quiet speech by about 4 dB and compresses loud speech, "
                                     "for a louder, denser voice.")
        self.lim_boost.setEnabled(self.lim_en.isChecked())
        self.lim_en.toggled.connect(self.lim_boost.setEnabled)

        self._group(form, "Normalizer")
        self.norm_en = self._check(form, "Enable output normalizer",
                                   getattr(self.cfg, "normalizer_enabled", False),
                                   "Auto-levels the output volume between presets.")
        self.norm_target = QDoubleSpinBox()
        self.norm_target.setRange(-30.0, -6.0)
        self.norm_target.setSingleStep(0.5)
        self.norm_target.setValue(getattr(self.cfg, "normalizer_target_db", -14.0))
        self.norm_target.setSuffix(" dBFS")
        form.addRow("Target loudness", self.norm_target)
        return page

    # ------------------------------------------------------------------ MIDI
    def _build_midi(self) -> QWidget:
        page = QWidget()
        lay = self._spaced.add(QVBoxLayout(page), spacing=2, margins=(0, 0, 3, 0))
        top = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        top.addWidget(QLabel("Input device"))
        self.midi_dev = self._combo()
        self.midi_dev.addItem("None", "")
        for _idx, mname in list_midi_inputs():
            self.midi_dev.addItem(mname, mname)
        self.midi_dev.setCurrentIndex(max(0, self.midi_dev.findText(self.cfg.midi_device)))
        self.midi_dev.currentIndexChanged.connect(self._on_midi_dev_preview)
        top.addWidget(self.midi_dev, 1)
        rescan_btn = make_button("Rescan MIDI")
        rescan_btn.clicked.connect(self._rescan_midi)
        top.addWidget(rescan_btn)
        lay.addLayout(top)

        lay.addWidget(self._hint("Map incoming MIDI pads and keys (note on) and rotary knobs and faders "
                                 "(CC) to presets, soundboard clips and studio controls."))

        self._midi_bindings_work: list[MidiBinding] = [copy.copy(b) for b in self.cfg.midi_bindings]
        self._midi_learning_row: int | None = None

        self.midi_table = QTableWidget(0, 5)
        self.midi_table.setHorizontalHeaderLabels(["Event type", "Note / CC #", "Channel",
                                                   "Target action", ""])
        mh = self.midi_table.horizontalHeader()
        mh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        mh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        mh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        mh.setSectionResizeMode(3, QHeaderView.Stretch)
        mh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.midi_table.verticalHeader().setVisible(False)
        lay.addWidget(self.midi_table, 1)

        add_midi_btn = make_button("Add MIDI binding", icon="plus")
        add_midi_btn.clicked.connect(self._add_midi_binding)
        self.midi_learn_btn = make_button(MIDI_LEARN_TEXT)
        self.midi_learn_btn.setObjectName("midiLearnBtn")
        self.midi_learn_btn.clicked.connect(self._start_midi_learn_new)
        lay.addLayout(self._left(add_midi_btn, self.midi_learn_btn))

        self._refresh_midi_table()
        self.core.midiMessageReceived.connect(self._on_midi_learned)
        return page

    # ------------------------------------------------------------------ Overlay
    def _build_overlay(self) -> QWidget:
        page, form = self._form_page()
        self.ov_en = self._check(form, "Show the in-game overlay", self.cfg.overlay.enabled,
                                 "A click-through badge on top of games.")
        self.ov_pos = self._combo(10)
        self.ov_pos.addItem("Top right", "top-right")
        self.ov_pos.addItem("Top left", "top-left")
        self.ov_pos.addItem("Bottom right", "bottom-right")
        self.ov_pos.addItem("Bottom left", "bottom-left")
        self.ov_pos.setCurrentIndex(max(0, self.ov_pos.findData(self.cfg.overlay.position)))

        self.ov_opacity = QSlider(Qt.Horizontal)
        self.ov_opacity.setRange(25, 100)
        self.ov_opacity.setValue(int(round(getattr(self.cfg.overlay, "opacity", 0.85) * 100)))
        self.ov_op_lbl = QLabel(f"{self.ov_opacity.value()}%")
        self.ov_op_lbl.setMinimumWidth(self.ov_op_lbl.fontMetrics().horizontalAdvance("100%"))
        self.ov_opacity.valueChanged.connect(lambda v: self.ov_op_lbl.setText(f"{v}%"))
        op_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        op_row.addWidget(self.ov_opacity, 1)
        op_row.addWidget(self.ov_op_lbl)

        form.addRow("Position", self.ov_pos)
        form.addRow("Opacity", op_row)
        self.ov_hide_clean = self._check(form, "Hide the badge when clean voice is active",
                                         self.cfg.overlay.hide_when_clean)
        return page

    # ------------------------------------------------------------------ Appearance
    def _build_appearance(self) -> QWidget:
        page, form = self._form_page()
        self._group(form, "Look")

        self.skin_combo = self._combo(10)
        for skin in appearance_skins():
            self.skin_combo.addItem(skin.name, skin.id)
        cur_skin = getattr(self.cfg, "ui_skin", "skeuomorphic")
        self.skin_combo.setCurrentIndex(max(0, self.skin_combo.findData(cur_skin)))
        self.skin_combo.currentIndexChanged.connect(self._on_appearance_preview_changed)
        form.addRow("Skin", self.skin_combo)

        self.theme_combo = self._combo(10)
        for palette in appearance_palettes():
            self.theme_combo.addItem(palette.name, palette.id)
        cur_theme = getattr(self.cfg, "theme", "scarlet")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(cur_theme)))
        self.theme_combo.currentIndexChanged.connect(self._on_appearance_preview_changed)
        form.addRow("Theme", self.theme_combo)

        self.customize_btn = make_button(
            "Customize…", tooltip="Swap the skin's elements and edit its colours in a panel beside "
                                  "the main window (applies these settings first)")
        self.customize_btn.clicked.connect(self._open_customize)
        form.addRow(self._left(self.customize_btn))
        form.addRow(self._hint("Changes preview straight away. Cancel restores the look you had. "
                               "Frame, switches, knobs and meters are chosen in Customize."))
        look_bus().userLooksChanged.connect(self.refresh_appearance_pickers)
        return page

    def refresh_appearance_pickers(self) -> None:
        """Re-read the user skins and themes (Customize saved, deleted or imported one), keeping
        each picker's selection when it still exists, else the configured one."""
        for combo, looks, configured in (
                (self.skin_combo, appearance_skins(), getattr(self.cfg, "ui_skin", "skeuomorphic")),
                (self.theme_combo, appearance_palettes(), getattr(self.cfg, "theme", "scarlet"))):
            want = combo.currentData()
            combo.blockSignals(True)
            try:
                combo.clear()
                for look in looks:
                    combo.addItem(look.name, look.id)
                index = combo.findData(want)
                combo.setCurrentIndex(index if index >= 0 else max(0, combo.findData(configured)))
            finally:
                combo.blockSignals(False)

    def _open_customize(self) -> None:
        self.customizeRequested.emit()
        self.accept()

    # ------------------------------------------------------------------ General
    def _build_general(self) -> QWidget:
        page, form = self._form_page()
        self._group(form, "Startup")
        self.launch_startup = self._check(
            form, "Launch Mandible when Windows starts",
            is_startup_enabled() or bool(getattr(self.cfg, "launch_at_startup", False)))
        self.autostart = self._check(form, "Start audio when Mandible opens", self.cfg.autostart_audio)
        self.tray = self._check(form, "Closing the window keeps Mandible running in the tray",
                                self.cfg.close_to_tray)
        self.minimized = self._check(form, "Start minimized to the tray", self.cfg.start_minimized)
        self.keep_awake = self._check(
            form, "Keep inactive chains awake", self.cfg.keep_chains_awake,
            "Feeds silence to idle chains so VST plugins do not suspend.")

        # Idle mode, hotkeys and the all-off key (also in the main window's header status zone)
        self._group(form, "Hotkeys and idle")
        self.idle_combo = self._combo()
        self.idle_combo.addItem("Clean voice (pass-through)", "dry")
        self.idle_combo.addItem("Mute", "mute")
        for c in self.cfg.chains:
            self.idle_combo.addItem(f"Chain: {c.name}", c.id)
        i = self.idle_combo.findData(self.cfg.idle_mode)
        self.idle_combo.setCurrentIndex(i if i >= 0 else 0)
        form.addRow("When no chain is active", self.idle_combo)
        self.hotkeys_check = self._check(form, "Global hotkeys enabled", bool(self.cfg.hotkeys_enabled))
        self._panic_hotkey_work = copy.deepcopy(self.cfg.panic_hotkey)
        self.panic_key_btn = make_button("Not set", icon="hotkey",
                                         tooltip="Global hotkey that turns every chain off")
        self.panic_key_btn.clicked.connect(self._pick_panic_hotkey)
        self._update_panic_key_btn()
        form.addRow("All-off key", self._left(self.panic_key_btn))

        self._group(form, "Updates")
        self.auto_updates = self._check(
            form, "Automatically check for updates on startup",
            getattr(self.cfg, "auto_check_updates", True),
            "Checks GitHub Releases at most once a day in the background.")
        self.prerelease_updates = self._check(
            form, "Include pre-release versions",
            getattr(self.cfg, "check_prereleases", True))
        self.check_updates_btn = make_button(
            "Check for updates…",
            tooltip="Check GitHub Releases for a newer version of Mandible")
        self.check_updates_btn.clicked.connect(self._open_update_checker)
        form.addRow(self._left(self.check_updates_btn))

        self._group(form, "Diagnostics")
        open_appdata_btn = make_button("Open config && logs folder…")
        open_appdata_btn.setToolTip(f"Open {APP_DIR} in Windows Explorer")
        open_appdata_btn.clicked.connect(lambda: os.startfile(APP_DIR) if os.path.isdir(APP_DIR) else None)
        form.addRow(self._left(open_appdata_btn))
        return page

    def _open_update_checker(self) -> None:
        from .updater import UpdateDialog
        self.cfg.auto_check_updates = self.auto_updates.isChecked()
        self.cfg.check_prereleases = self.prerelease_updates.isChecked()
        UpdateDialog(self.core, self).exec()

    # ------------------------------------------------------------------ Add-ons
    def _build_addons(self) -> QWidget:
        """Add-ons manager: browse, install, manage, and check updates for official add-ons."""
        from ...addons import ADDON_REGISTRY, get_addon_installed_version, check_addon_update

        page, form = self._form_page()

        self._group(form, "Add-on updates")
        self.auto_addon_updates = self._check(
            form, "Automatically check for add-on updates on startup",
            getattr(self.cfg, "auto_check_addon_updates", True),
            "Checks GitHub Releases for installed add-ons at most once a day.")
        self.notify_updates_check = self._check(
            form, "Notify via desktop notification when updates are found",
            getattr(self.cfg, "notify_updates", True),
            "Displays a notification in the Windows notification center / tray.")

        addon_check_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
        self.check_addons_btn = make_button("Check all add-ons for updates…", "secondary")
        self.open_addons_folder_btn = make_button("Open add-ons folder…", "secondary")
        addon_check_row.addWidget(self.check_addons_btn)
        addon_check_row.addWidget(self.open_addons_folder_btn)
        addon_check_row.addStretch(1)
        form.addRow(addon_check_row)

        self._group(form, "Installed & Available Add-ons")
        self._addon_cards = {}
        for aid, info in ADDON_REGISTRY.items():
            card = QFrame()
            card.setObjectName("wizardCard")
            clay = self._spaced.add(QVBoxLayout(card), spacing=1, margins=3)

            top_row = self._spaced.add(QHBoxLayout(), spacing=2, margins=0)
            title = QLabel(f"<b>{info.name}</b>  ({info.category})</span>")
            title.setObjectName("wizardCardTitle")
            top_row.addWidget(title)
            top_row.addStretch(1)

            btn = make_button("Manage…", "primary")
            top_row.addWidget(btn)
            clay.addLayout(top_row)

            desc = QLabel(info.summary)
            desc.setWordWrap(True)
            clay.addWidget(desc)

            status_lbl = QLabel("")
            clay.addWidget(status_lbl)
            form.addRow(card)

            self._addon_cards[aid] = (card, btn, status_lbl, info)

        def _refresh():
            from ...addons import TOOLS_DIR
            os.makedirs(TOOLS_DIR, exist_ok=True)
            for aid, (card, btn, status_lbl, info) in self._addon_cards.items():
                exe = info.find_exe_fn()
                if exe:
                    ver = get_addon_installed_version(aid) or "v0.1.0"
                    status_lbl.setText(f"● Installed</span> ({ver}) — {exe}")
                    btn.setText("Manage…")
                else:
                    status_lbl.setText("○ Not installed</span>")
                    btn.setText("Install add-on…")

        def _manage(aid: str):
            info = ADDON_REGISTRY.get(aid)
            if info:
                info.open_dialog_fn(self)
                _refresh()

        for aid, (_, btn, _, _) in self._addon_cards.items():
            btn.clicked.connect(lambda _, a=aid: _manage(a))

        self.open_addons_folder_btn.clicked.connect(
            lambda: os.startfile(os.path.join(APP_DIR, "tools")) if os.path.isdir(os.path.join(APP_DIR, "tools")) else None
        )

        def _check_all_addons():
            self.check_addons_btn.setEnabled(False)
            self.check_addons_btn.setText("Checking GitHub Releases…")
            found = []
            for aid, (card, btn, status_lbl, info) in self._addon_cards.items():
                if info.find_exe_fn():
                    latest_tag, newer = check_addon_update(aid)
                    if newer:
                        found.append(f"{info.name} ({latest_tag})")
                        status_lbl.setText(f"★ Update available: {latest_tag}</span>")
            self.check_addons_btn.setEnabled(True)
            self.check_addons_btn.setText("Check all add-ons for updates…")
            if found:
                QMessageBox.information(
                    self,
                    "Add-on Updates Found",
                    "Newer versions are available for the following add-on(s):\n\n" +
                    "\n".join(f"• {x}" for x in found) +
                    "\n\nClick 'Manage…' on the add-on to update."
                )
            else:
                QMessageBox.information(
                    self,
                    "Add-ons Up to Date",
                    "All installed add-ons are up to date!"
                )

        self.check_addons_btn.clicked.connect(_check_all_addons)
        _refresh()
        return page

    # ------------------------------------------------------------------ Local API
    def _build_api(self) -> QWidget:
        import webbrowser

        page, form = self._form_page()
        self.api_en = self._check(
            form, "Enable the local HTTP API", getattr(self.cfg, "api_enabled", False),
            "Lets Elgato Stream Deck, OBS browser docks and local apps switch presets, play "
            "soundboard clips and mute over HTTP.")
        self.api_port_spin = QSpinBox()
        self.api_port_spin.setRange(1024, 65535)
        self.api_port_spin.setValue(getattr(self.cfg, "api_port", 38420))
        form.addRow("Port", self.api_port_spin)

        self.api_test_btn = make_button("Test the API in a web browser",
                                        tooltip="Opens http://127.0.0.1:<port>/api/status")
        self.api_test_btn.clicked.connect(
            lambda: webbrowser.open(f"http://127.0.0.1:{self.api_port_spin.value()}/api/status"))
        form.addRow(self._left(self.api_test_btn))
        return page

    def _midi_action_options(self) -> list[tuple[str, str]]:
        opts = [
            ("Toggle mic mute", "mute"),
            ("Panic cut (all chains off)", "panic"),
            ("Master output volume (CC fader)", "out_vol"),
            ("Headphone monitor volume (CC fader)", "monitor_vol"),
            ("Mic input trim (CC fader)", "in_vol"),
        ]
        for c in self.cfg.chains:
            opts.append((f"Preset: {c.name}", f"chain:{c.id}"))
        for s in self.cfg.soundboard:
            opts.append((f"Soundboard: {s.name}", f"soundboard:{s.id}"))
        return opts

    def _refresh_midi_table(self):
        self.midi_table.setRowCount(len(self._midi_bindings_work))
        action_opts = self._midi_action_options()
        for row, b in enumerate(self._midi_bindings_work):
            # 0: Event Type
            type_cb = QComboBox()
            type_cb.addItem("Note on (pad/key)", "note_on")
            type_cb.addItem("Control change (CC)", "cc")
            type_cb.setCurrentIndex(max(0, type_cb.findData(b.event_type)))
            type_cb.currentIndexChanged.connect(lambda _, r=row, cb=type_cb: setattr(self._midi_bindings_work[r], "event_type", cb.currentData()))
            self.midi_table.setCellWidget(row, 0, type_cb)

            # 1: Note / CC #
            num_sp = QSpinBox()
            num_sp.setRange(0, 127)
            num_sp.setValue(int(b.note_or_cc))
            num_sp.valueChanged.connect(lambda val, r=row: setattr(self._midi_bindings_work[r], "note_or_cc", int(val)))
            self.midi_table.setCellWidget(row, 1, num_sp)

            # 2: Channel (0 = Omni)
            ch_sp = QSpinBox()
            ch_sp.setRange(0, 16)
            ch_sp.setSpecialValueText("All (omni)")
            ch_sp.setValue(int(b.channel))
            ch_sp.valueChanged.connect(lambda val, r=row: setattr(self._midi_bindings_work[r], "channel", int(val)))
            self.midi_table.setCellWidget(row, 2, ch_sp)

            # 3: Action
            act_cb = QComboBox()
            for lbl, act_data in action_opts:
                act_cb.addItem(lbl, act_data)
            idx = act_cb.findData(b.action)
            if idx >= 0:
                act_cb.setCurrentIndex(idx)
            elif action_opts:
                b.action = action_opts[0][1]
            act_cb.currentIndexChanged.connect(lambda _, r=row, cb=act_cb: setattr(self._midi_bindings_work[r], "action", cb.currentData()))
            self.midi_table.setCellWidget(row, 3, act_cb)

            # 4: Remove
            rm_btn = make_button(tier="quiet", icon="remove", tooltip="Remove this binding")
            rm_btn.clicked.connect(lambda _, r=row: self._remove_midi_binding(r))
            self.midi_table.setCellWidget(row, 4, rm_btn)

    def _add_midi_binding(self):
        opts = self._midi_action_options()
        default_act = opts[0][1] if opts else "mute"
        self._midi_bindings_work.append(MidiBinding(device_name=self.midi_dev.currentText(), event_type="note_on", note_or_cc=60, channel=0, action=default_act))
        self._refresh_midi_table()

    def _remove_midi_binding(self, row: int):
        if 0 <= row < len(self._midi_bindings_work):
            self._midi_bindings_work.pop(row)
            self._refresh_midi_table()

    def _rescan_midi(self):
        cur = self.midi_dev.currentText()
        self.midi_dev.blockSignals(True)
        self.midi_dev.clear()
        self.midi_dev.addItem("None", "")
        for idx, mname in list_midi_inputs():
            self.midi_dev.addItem(mname, mname)
        self.midi_dev.setCurrentIndex(max(0, self.midi_dev.findText(cur)))
        self.midi_dev.blockSignals(False)
        self._on_midi_dev_preview()

    def _on_midi_dev_preview(self):
        mdev = self.midi_dev.currentText()
        if mdev == "None":
            mdev = ""
        self.core.set_midi_device(mdev)

    def _start_midi_learn_new(self):
        mdev = self.midi_dev.currentText()
        if not mdev or mdev == "None":
            QMessageBox.information(self, "MIDI learn", "Select a MIDI input device at the top of the page first.")
            return
        self._on_midi_dev_preview()
        if self._midi_learning_row is not None:
            self._midi_learning_row = None
            self.midi_learn_btn.setText(MIDI_LEARN_TEXT)
            return
        self._midi_learning_row = -1
        self.midi_learn_btn.setText("Listening for MIDI input… (click to cancel)")

    def _on_midi_learned(self, event_type: str, note_or_cc: int, channel: int):
        if self._midi_learning_row is None:
            return
        self._midi_learning_row = None
        self.midi_learn_btn.setText(MIDI_LEARN_TEXT)
        opts = self._midi_action_options()
        default_act = "out_vol" if event_type == "cc" else (f"chain:{self.cfg.chains[0].id}" if self.cfg.chains else (opts[0][1] if opts else "mute"))
        self._midi_bindings_work.append(
            MidiBinding(
                device_name=self.midi_dev.currentText(),
                event_type=event_type,
                note_or_cc=note_or_cc,
                channel=channel,
                action=default_act,
            )
        )
        self._refresh_midi_table()

    def _set_ptt_hotkey(self):
        dlg = HotkeyDialog(self.core, self, "Push-to-talk hotkey")
        if dlg.exec() and dlg.result_hotkey is not None:
            self.cfg.ptt.hotkey = dlg.result_hotkey
            self.ptt_hk_lbl.setText(dlg.result_hotkey.label or "Not set")

    def _open_asio_panel(self):
        dev = self.in_dev.currentText()
        if not dev:
            return
        err = D.show_asio_panel(dev, int(self.winId()))
        if err:
            QMessageBox.warning(self, "ASIO driver settings", f"Could not open the ASIO driver settings:\n{err}")

    def _fill_drivers(self, a):
        self.driver.blockSignals(True)
        self.driver.clear()
        for d in D.drivers():
            self.driver.addItem(D.DRIVER_LABELS.get(d, d), d)
        self.driver.setCurrentIndex(max(0, self.driver.findData(a.driver)))
        self.driver.blockSignals(False)
        self._driver_changed(a)

    def _driver_changed(self, a):
        drv = self.driver.currentData()
        asio = drv == "ASIO"
        self.out_dev.setVisible(not asio)
        self.out_dev_label.setVisible(not asio)
        self.mon_dev.setVisible(not asio)
        self.mon_dev_label.setVisible(not asio)
        self.mon_ch.setVisible(asio)
        self.mon_ch_label.setVisible(asio)
        wasapi = drv == "Windows WASAPI"
        self.excl.setVisible(wasapi)
        self.excl_hint.setVisible(wasapi)
        self.asio_panel_btn.setVisible(asio)
        for combo, kind, want in ((self.in_dev, "input", a.input_device if a else None),
                                  (self.out_dev, "output", a.output_device if a else None)):
            combo.blockSignals(True)
            combo.clear()
            for idx, name, n in D.list_devices(drv, kind):
                combo.addItem(name, idx)
            i = combo.findText(want) if want else -1
            if i < 0:
                i = next((k for k in range(combo.count()) if "focusrite" in combo.itemText(k).lower()), 0)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)

        self.mon_dev.blockSignals(True)
        self.mon_dev.clear()
        self.mon_dev.addItem("None", "")
        for idx, name, n in D.list_devices(drv, "output"):
            self.mon_dev.addItem(name, name)
        want_mon = a.monitor_device if a else ""
        i_mon = self.mon_dev.findData(want_mon)
        if i_mon < 0 and want_mon:
            i_mon = self.mon_dev.findText(want_mon)
        if i_mon < 0:
            i_mon = next((k for k in range(self.mon_dev.count()) if "speaker" in self.mon_dev.itemText(k).lower()), 0)
        self.mon_dev.setCurrentIndex(max(0, i_mon))
        self.mon_dev.blockSignals(False)

        self._in_changed(a)
        self._out_changed(a)

    def _in_changed(self, a):
        drv = self.driver.currentData()
        self.in_ch.clear()
        idx = self.in_dev.currentData()
        if idx is not None:
            for i, n in enumerate(D.channel_names(drv, idx, "input")):
                self.in_ch.addItem(f"{i + 1}: {n}" if not n.startswith("Channel") else n, i)
        want = a.input_channel if a else 0
        self.in_ch.setCurrentIndex(max(0, self.in_ch.findData(want)))
        if drv == "ASIO":
            self._out_changed(a)

    def _out_changed(self, a):
        drv = self.driver.currentData()
        self.out_ch.clear()
        self.mon_ch.clear()
        idx = self.in_dev.currentData() if drv == "ASIO" else self.out_dev.currentData()
        if drv == "ASIO" and idx is not None:
            idx = D.find_device(drv, self.in_dev.currentText(), "output")
        if idx is None:
            return
        names = D.channel_names(drv, idx, "output")
        for l in range(0, len(names) - 1, 2):
            text = f"{l + 1}-{l + 2}  ({names[l]} / {names[l + 1]})"
            self.out_ch.addItem(text, [l, l + 1])
            self.mon_ch.addItem(text, [l, l + 1])
        if len(names) == 1:
            self.out_ch.addItem(f"1 ({names[0]}) mono", [0, 0])
            self.mon_ch.addItem(f"1 ({names[0]}) mono", [0, 0])
        want = list(a.output_channels) if a else ([2, 3] if drv == "ASIO" else [0, 1])
        i = next((k for k in range(self.out_ch.count()) if self.out_ch.itemData(k) == want), 0)
        self.out_ch.setCurrentIndex(i)

        want_mon = list(a.monitor_channels) if a else ([0, 1] if drv == "ASIO" else [0, 1])
        i_mon = next((k for k in range(self.mon_ch.count()) if self.mon_ch.itemData(k) == want_mon), 0)
        self.mon_ch.setCurrentIndex(i_mon)

    def _rescan(self):
        D.rescan()
        self._fill_drivers(self.result_settings())

    def result_settings(self):
        a = AudioSettings()
        a.driver = self.driver.currentData() or ""
        a.input_device = self.in_dev.currentText()
        a.output_device = self.in_dev.currentText() if a.driver == "ASIO" else self.out_dev.currentText()
        a.input_channel = int(self.in_ch.currentData() or 0)
        a.output_channels = list(self.out_ch.currentData() or [0, 1])
        a.monitor_channels = list(self.mon_ch.currentData() or [0, 1])
        a.monitor_device = str(self.mon_dev.currentData() or "") if a.driver != "ASIO" else ""
        a.samplerate = int(self.sr.currentData() or 0)
        a.blocksize = int(self.bs.currentData() or 128)
        a.wasapi_exclusive = self.excl.isChecked()
        return a

    def _update_panic_key_btn(self):
        hk = self._panic_hotkey_work
        self.panic_key_btn.setText(hk.label if hk.is_set() else "Not set")

    def _pick_panic_hotkey(self):
        dlg = HotkeyDialog(self.core, self, "All-off hotkey")
        if dlg.exec() and dlg.result_hotkey is not None:
            hk = dlg.result_hotkey
            if hk.is_set():
                clash = self.core.find_hotkey_conflict(hk, exclude=self.cfg.panic_hotkey)
                if clash:
                    QMessageBox.warning(self, "Hotkey in use", f"{hk.label} is already used by {clash}.")
                    return
            self._panic_hotkey_work = hk
            self._update_panic_key_btn()

    def apply_all(self):
        # Idle mode, hotkeys, all-off key
        self.cfg.idle_mode = self.idle_combo.currentData() or "dry"
        self.cfg.hotkeys_enabled = self.hotkeys_check.isChecked()
        self.core.hotkeys.enabled = self.cfg.hotkeys_enabled
        self.cfg.panic_hotkey = copy.deepcopy(self._panic_hotkey_work)
        self.core.rebind_hotkeys()
        self.core._apply()

        self.cfg.launch_at_startup = self.launch_startup.isChecked()
        set_startup_enabled(self.launch_startup.isChecked(), start_minimized=self.minimized.isChecked())

        self.cfg.autostart_audio = self.autostart.isChecked()
        self.cfg.close_to_tray = self.tray.isChecked()
        self.cfg.start_minimized = self.minimized.isChecked()
        self.cfg.keep_chains_awake = self.keep_awake.isChecked()
        self.core.engine.keep_awake = self.keep_awake.isChecked()
        if hasattr(self, "auto_updates"):
            self.cfg.auto_check_updates = self.auto_updates.isChecked()
        if hasattr(self, "prerelease_updates"):
            self.cfg.check_prereleases = self.prerelease_updates.isChecked()
        if hasattr(self, "auto_addon_updates"):
            self.cfg.auto_check_addon_updates = self.auto_addon_updates.isChecked()
        if hasattr(self, "notify_updates_check"):
            self.cfg.notify_updates = self.notify_updates_check.isChecked()

        # Limiter
        self.cfg.limiter.enabled = self.lim_en.isChecked()
        self.cfg.limiter.threshold_db = float(self.lim_thresh.value())
        self.cfg.limiter.boost = self.lim_boost.isChecked()
        self.core.set_limiter(self.cfg.limiter)

        # PTT
        self.core.update_ptt_mode(self.ptt_mode.currentData())

        # MIDI
        mdev = self.midi_dev.currentText()
        if mdev == "None":
            mdev = ""
        self.cfg.midi_bindings = list(self._midi_bindings_work)
        self.core.set_midi_device(mdev)

        # Overlay
        self.cfg.overlay.enabled = self.ov_en.isChecked()
        self.cfg.overlay.position = self.ov_pos.currentData()
        self.cfg.overlay.opacity = float(self.ov_opacity.value()) / 100.0
        self.cfg.overlay.hide_when_clean = self.ov_hide_clean.isChecked()
        self.core._sync_overlay()

        # Monitor Mode
        self.core.set_monitor_mode(self.mon_mode.currentData())

        # Appearance: only when a picker changed, so OK never replaces a look it did not choose
        # (an unsaved Customize draft stays on screen). Both ids are stored first so the core
        # setters apply the final look once. The old chassis_frame / switch_style fields are
        # never written (spec 7.5; Customize owns them).
        new_skin = self.skin_combo.currentData() or self.cfg.ui_skin
        new_theme = self.theme_combo.currentData() or self.cfg.theme
        skin_changed, theme_changed = new_skin != self.cfg.ui_skin, new_theme != self.cfg.theme
        self.cfg.ui_skin, self.cfg.theme = new_skin, new_theme
        if skin_changed:
            self.core.set_ui_skin(new_skin)
        if theme_changed:
            self.core.set_theme(new_theme)

        # Normalizer
        if hasattr(self, "norm_en"):
            self.core.set_normalizer(self.norm_en.isChecked(), float(self.norm_target.value()))

        # Local API
        if hasattr(self, "api_en"):
            self.core.set_api_enabled(self.api_en.isChecked(), int(self.api_port_spin.value()))

    def _launch_setup_assistant(self):
        dlg = SetupAssistantDialog(self.core, self)
        if dlg.exec():
            # Refresh audio controls if wizard updated devices
            self._fill_drivers(self.cfg.audio)

    def _preview_look(self) -> Look:
        """The look the pickers select, resolved exactly as the config will be after OK."""
        return look_from_config(SimpleNamespace(
            theme=self.theme_combo.currentData() or "scarlet",
            ui_skin=self.skin_combo.currentData() or "skeuomorphic",
            chassis_frame=getattr(self.cfg, "chassis_frame", "auto"),
            switch_style=getattr(self.cfg, "switch_style", None),
            appearance_migrated=getattr(self.cfg, "appearance_migrated", False)))

    def _on_appearance_preview_changed(self, _=None):
        # Back on the configured ids: show the look the dialog opened with (which may be an
        # unsaved Customize draft), not a fresh copy of the saved one.
        unchanged = (self.skin_combo.currentData() == getattr(self.cfg, "ui_skin", None)
                     and self.theme_combo.currentData() == getattr(self.cfg, "theme", None))
        look = self._orig_look if unchanged else self._preview_look()
        if look != current_look():
            set_look(look)

    def reject(self):
        if current_look() != self._orig_look:
            set_look(self._orig_look)
        super().reject()
