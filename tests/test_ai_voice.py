"""Tests for the AI Voice Changer (.onnx only), GitHub Model Hub, LFO Modulator, Sub-Harmonic & Exciter, and DSP voice presets."""
from __future__ import annotations

import base64
import json

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt

from mandible import ai_voice as AV
from mandible import plugins as P
from mandible.config import Chain, PluginSlot, _from_dict
from mandible.factory_presets import get_factory_presets, instantiate_factory_preset
from mandible.internal_dsp import (
    AIVoicePlugin,
    LFOModulatorPlugin,
    SubHarmonicSynthPlugin,
    get_internal_plugin_catalog,
    load_internal_plugin,
)
from mandible.ui.app import apply_theme
from mandible.ui.dialogs.add_plugin import AddPluginDialog
from mandible.ui.dialogs.ai_voice import AIVoiceDialog
from mandible.ui.dialogs.lfo_mod import LFOModulatorDialog
from mandible.ui.dialogs.model_hub import ModelHubDialog
from mandible.ui.inspect import (
    find_clipped_text,
    find_overflow,
    off_scale_spacing,
    untiered_buttons,
)
from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look
from mandible.ui.widgets.plugin_card import PluginRackCard


def _flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def test_internal_catalog_contains_ai_voice_lfo_and_sub_exciter():
    catalog = get_internal_plugin_catalog()
    paths = [item["path"] for item in catalog]
    assert AV.AI_VOICE_PLUGIN_PATH in paths
    assert "internal:lfo" in paths
    assert "internal:sub_exciter" in paths


def test_list_voice_models_returns_only_onnx_models(tmp_path):
    models_dir = tmp_path / "ai_models"
    # Empty directory has no pseudo-AI built-in profiles
    assert AV.list_voice_models(str(models_dir)) == []
    assert AV.get_voice_model("xen_overmind", str(models_dir)) is None


def test_ai_voice_plugin_dsp_and_state_roundtrip(tmp_path):
    models_dir = tmp_path / "ai_models"
    onnx_file = tmp_path / "Xen_Harbinger_v2.onnx"
    onnx_file.write_bytes(b"fake-onnx-weights-payload")
    info = AV.import_voice_model(
        str(onnx_file),
        display_name="Xen Harbinger (RVC v2)",
        models_dir=str(models_dir),
    )

    plugin = load_internal_plugin(AV.AI_VOICE_PLUGIN_PATH)
    assert isinstance(plugin, AIVoicePlugin)
    assert plugin.has_custom_editor is True
    assert plugin.reported_latency_samples == 1024

    plugin.set_model(info.id, apply_defaults=False)
    plugin.f0_method = "harvest"
    plugin.parameters["pitch"].value = -5.0
    plugin.parameters["formant"].value = -3.0
    plugin.parameters["breathiness"].value = 35.0
    plugin.parameters["mix"].value = 85.0

    # Roundtrip state persistence
    raw = plugin.raw_state
    restored = load_internal_plugin(AV.AI_VOICE_PLUGIN_PATH)
    restored.raw_state = raw
    assert restored.model_id == info.id
    assert restored.f0_method == "harvest"
    assert pytest.approx(restored.parameters["pitch"].value, abs=0.1) == -5.0
    assert pytest.approx(restored.parameters["formant"].value, abs=0.1) == -3.0
    assert pytest.approx(restored.parameters["breathiness"].value, abs=0.5) == 35.0
    assert pytest.approx(restored.parameters["mix"].value, abs=0.5) == 85.0

    # Process stereo audio buffer and verify finite output
    sr = 48000.0
    t = np.arange(2048, dtype=np.float32) / sr
    sig = 0.25 * np.sin(2.0 * np.pi * 220.0 * t).astype(np.float32)
    stereo = np.vstack([sig, sig])
    out = restored.process(stereo, sr)
    assert out.shape == stereo.shape
    assert np.all(np.isfinite(out))
    assert float(np.max(np.abs(out))) > 0.01


def test_import_and_remove_custom_onnx_model(tmp_path):
    models_dir = tmp_path / "ai_models"
    onnx_file = tmp_path / "GLaDOS_v2.onnx"
    onnx_file.write_bytes(b"fake-onnx-weights-payload")
    idx_file = tmp_path / "GLaDOS_v2.index"
    idx_file.write_bytes(b"fake-faiss-index")

    info = AV.import_voice_model(
        str(onnx_file),
        str(idx_file),
        display_name="GLaDOS v2",
        models_dir=str(models_dir),
    )
    assert info.kind == "onnx"
    assert info.name == "GLaDOS v2"
    assert info.id.startswith("onnx:")

    all_models = AV.list_voice_models(str(models_dir))
    assert [m.id for m in all_models] == [info.id]

    fetched = AV.get_voice_model(info.id, str(models_dir))
    assert fetched is not None
    assert fetched.name == "GLaDOS v2"

    # Non-onnx IDs cannot be removed
    assert AV.remove_voice_model("non_existent", str(models_dir)) is False

    # Custom model removal cleans up files
    assert AV.remove_voice_model(info.id, str(models_dir)) is True
    assert AV.list_voice_models(str(models_dir)) == []


def test_download_remote_voice_model_and_hub_dialog(qapp, sample_core, tmp_path):
    apply_theme(qapp, Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    models_dir = tmp_path / "ai_models"
    remote = AV.DEFAULT_REMOTE_MODELS[0]
    assert AV.is_remote_model_installed(remote, str(models_dir)) is False

    installed = AV.download_remote_voice_model(
        remote,
        models_dir=str(models_dir),
        timeout=0.05,
    )
    assert installed.id == f"onnx:{remote.id}.onnx"
    assert AV.is_remote_model_installed(remote, str(models_dir)) is True

    info = AV.get_voice_model(installed.id, str(models_dir))
    assert info is not None
    assert info.default_pitch == remote.default_pitch
    assert info.default_formant == remote.default_formant

    dlg = ModelHubDialog(sample_core, None, models_dir=str(models_dir), auto_fetch=False)
    try:
        dlg.setAttribute(Qt.WA_DontShowOnScreen)
        dlg.show()
        for _ in range(3):
            qapp.processEvents()

        assert off_scale_spacing(dlg) == []
        assert untiered_buttons(dlg) == []
        assert find_clipped_text(dlg) == []
        assert find_overflow(dlg) == []
        assert dlg.model_list.count() == len(AV.DEFAULT_REMOTE_MODELS)
    finally:
        dlg.hide()
        dlg.deleteLater()
        _flush()


def test_lfo_modulator_plugin_and_dialog(qapp, sample_core):
    apply_theme(qapp, Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    chorus_slot = PluginSlot(path="internal:chorus", display_name="Stereo Chorus")
    chorus_slot._instance = load_internal_plugin("internal:chorus")
    lfo_slot = PluginSlot(path="internal:lfo", display_name="LFO Modulator")
    lfo_plugin = load_internal_plugin("internal:lfo")
    assert isinstance(lfo_plugin, LFOModulatorPlugin)
    lfo_slot._instance = lfo_plugin

    chain = Chain(name="Modulated Chain", plugins=[chorus_slot, lfo_slot])
    lfo_plugin.target_slot_index = 0
    lfo_plugin.target_param_key = "mix"
    lfo_plugin.parameters["rate_hz"].value = 2.0
    lfo_plugin.parameters["depth"].value = 80.0
    lfo_plugin.parameters["center"].value = 50.0

    # Step LFO across buffers and verify target parameter sweeps
    seen_values = []
    for _ in range(10):
        lfo_plugin.step_and_apply(tuple(chain.plugins), 2400, 48000.0)
        seen_values.append(float(chorus_slot._instance.parameters["mix"].value))
    assert max(seen_values) - min(seen_values) > 0.4

    dlg = LFOModulatorDialog(lfo_slot, chain, sample_core, None)
    try:
        dlg.setAttribute(Qt.WA_DontShowOnScreen)
        dlg.show()
        for _ in range(3):
            qapp.processEvents()

        assert off_scale_spacing(dlg) == []
        assert untiered_buttons(dlg) == []
        assert find_clipped_text(dlg) == []
        assert find_overflow(dlg) == []
    finally:
        dlg.hide()
        dlg.deleteLater()
        _flush()


def test_sub_harmonic_exciter_and_dsp_voice_factory_presets():
    sub = load_internal_plugin("internal:sub_exciter")
    assert isinstance(sub, SubHarmonicSynthPlugin)
    sr = 48000.0
    t = np.arange(2048, dtype=np.float32) / sr
    sig = 0.25 * np.sin(2.0 * np.pi * 180.0 * t).astype(np.float32)
    stereo = np.vstack([sig, sig])
    out = sub.process(stereo, sr)
    assert out.shape == stereo.shape
    assert np.all(np.isfinite(out))

    presets = {p['id']: p for p in get_factory_presets()}
    for pid in (
        "factory_xen_overmind",
        "factory_cyber_valkyrie",
        "factory_shadow_operative",
        "factory_titan_brute",
        "factory_ethereal_oracle",
    ):
        assert pid in presets
        chain = instantiate_factory_preset(presets[pid])
        assert len(chain.plugins) >= 4
        for slot in chain.plugins:
            inst = load_internal_plugin(slot.path)
            assert inst is not None
            if slot.state:
                inst.raw_state = base64.b64decode(slot.state)


def test_only_one_ai_voice_changer_per_chain_in_core(sample_core):
    chain = Chain(name="Test AI Chain", plugins=[])
    sample_core.cfg.chains.append(chain)

    # First AI Voice Changer succeeds
    slot1 = sample_core.add_plugin(chain, AV.AI_VOICE_PLUGIN_PATH)
    assert slot1 in chain.plugins
    assert AV.chain_has_ai_voice(chain) is True

    # Adding a second AI Voice Changer to the SAME chain raises ValueError
    with pytest.raises(ValueError, match="only contain one AI Voice Changer"):
        sample_core.add_plugin(chain, AV.AI_VOICE_PLUGIN_PATH)
    assert sum(1 for s in chain.plugins if AV.is_ai_voice_plugin(s.path)) == 1

    # Adding an AI Voice Changer to a DIFFERENT chain succeeds
    chain2 = Chain(name="Second AI Chain", plugins=[])
    sample_core.cfg.chains.append(chain2)
    slot2 = sample_core.add_plugin(chain2, AV.AI_VOICE_PLUGIN_PATH)
    assert slot2 in chain2.plugins


def test_config_deserialization_deduplicates_ai_voice_in_single_chain():
    raw_chain = {
        "id": "chain-1",
        "name": "Duplicate Test",
        "plugins": [
            {"path": "internal:ai_voice", "display_name": "AI Voice Changer", "enabled": True},
            {"path": "internal:reverb", "display_name": "Studio Reverb", "enabled": True},
            {"path": "internal:ai_voice", "display_name": "AI Voice Changer 2", "enabled": True},
        ],
    }
    chain = _from_dict(Chain, raw_chain)
    ai_slots = [s for s in chain.plugins if AV.is_ai_voice_plugin(s.path)]
    assert len(ai_slots) == 1
    assert len(chain.plugins) == 2


def test_add_plugin_dialog_disables_ai_voice_when_already_in_chain(qapp, monkeypatch):
    monkeypatch.setattr(P, "scan_vst3", lambda extra=None: [])
    chain_with_ai = Chain(
        name="Has AI",
        plugins=[PluginSlot(path=AV.AI_VOICE_PLUGIN_PATH, display_name=AV.AI_VOICE_DISPLAY_NAME)],
    )
    dlg = AddPluginDialog([], None, chain=chain_with_ai)
    ai_items = [
        dlg.list.item(i)
        for i in range(dlg.list.count())
        for _ in [0]
        if dlg.list.item(i).data(Qt.UserRole) == AV.AI_VOICE_PLUGIN_PATH
    ]
    assert len(ai_items) == 1
    item = ai_items[0]
    assert not (item.flags() & Qt.ItemIsEnabled)
    assert "already in this chain" in item.text()

    # In a chain without AI Voice Changer, the item is enabled
    empty_chain = Chain(name="Empty", plugins=[])
    dlg2 = AddPluginDialog([], None, chain=empty_chain)
    ai_items2 = [
        dlg2.list.item(i)
        for i in range(dlg2.list.count())
        if dlg2.list.item(i).data(Qt.UserRole) == AV.AI_VOICE_PLUGIN_PATH
    ]
    assert len(ai_items2) == 1
    assert bool(ai_items2[0].flags() & Qt.ItemIsEnabled)
    dlg.deleteLater()
    dlg2.deleteLater()
    _flush()


def test_plugin_rack_card_shows_open_ui_button_for_ai_voice_and_lfo(qapp, sample_core):
    slot = PluginSlot(path=AV.AI_VOICE_PLUGIN_PATH, display_name=AV.AI_VOICE_DISPLAY_NAME)
    slot._instance = load_internal_plugin(AV.AI_VOICE_PLUGIN_PATH)
    lfo_slot = PluginSlot(path="internal:lfo", display_name="LFO Modulator")
    lfo_slot._instance = load_internal_plugin("internal:lfo")
    chain = Chain(name="AI Chain", plugins=[slot, lfo_slot])
    card = PluginRackCard(slot, chain, sample_core)
    lfo_card = PluginRackCard(lfo_slot, chain, sample_core)
    assert card.ui_btn.isHidden() is False
    assert "AI voice model" in card.ui_btn.toolTip()
    assert lfo_card.ui_btn.isHidden() is False
    assert "LFO modulation" in lfo_card.ui_btn.toolTip()
    card.deleteLater()
    lfo_card.deleteLater()
    _flush()


def test_ai_voice_dialog_ui_and_controls(qapp, sample_core, tmp_path):
    apply_theme(qapp, Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    models_dir = tmp_path / "ai_models"
    m1 = AV.download_remote_voice_model(
        AV.DEFAULT_REMOTE_MODELS[0], models_dir=str(models_dir), timeout=0.05
    )
    m2 = AV.download_remote_voice_model(
        AV.DEFAULT_REMOTE_MODELS[1], models_dir=str(models_dir), timeout=0.05
    )

    slot = PluginSlot(path=AV.AI_VOICE_PLUGIN_PATH, display_name=AV.AI_VOICE_DISPLAY_NAME)
    plugin = load_internal_plugin(AV.AI_VOICE_PLUGIN_PATH)
    slot._instance = plugin

    dlg = AIVoiceDialog(slot, sample_core, models_dir=str(models_dir))
    try:
        dlg.setAttribute(Qt.WA_DontShowOnScreen)
        dlg.show()
        for _ in range(3):
            qapp.processEvents()

        assert off_scale_spacing(dlg) == []
        assert untiered_buttons(dlg) == []
        assert find_clipped_text(dlg) == []
        assert find_overflow(dlg) == []

        # Selecting another installed .onnx model updates the plugin and persists state
        idx = dlg.model_combo.findData(m1.id)
        assert idx >= 0
        dlg.model_combo.setCurrentIndex(idx)
        assert plugin.model_id == m1.id
        assert slot.state != ""

        decoded = json.loads(base64.b64decode(slot.state).decode("utf-8"))
        assert decoded["model_id"] == m1.id
    finally:
        dlg.hide()
        dlg.deleteLater()
        _flush()
