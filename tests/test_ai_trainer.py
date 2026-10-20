"""Tests for the local AI voice model training engine, ONNX Runtime inference, and AITrainerDialog."""
from __future__ import annotations

import os
import pedalboard.io
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt

from mandible import ai_trainer as AT
from mandible import ai_voice as AV
from mandible.internal_dsp import load_internal_plugin
from mandible.ui.app import apply_theme
from mandible.ui.dialogs.ai_trainer import AITrainerDialog, ExternalTrainingGuideDialog
from mandible.ui.inspect import (find_clipped_text, find_overflow, off_scale_spacing,
                                 untiered_buttons)
from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look


def _flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _make_dummy_wav(
    path: str,
    duration_s: float = 2.0,
    sr: int = 44100,
    freq: float = 220.0,
    formant_hz: float = 1200.0,
) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    frames = int(sr * duration_s)
    t = np.arange(frames, dtype=np.float32) / sr
    # Rich harmonic glottal pulse train shaped around formant_hz
    sig = (
        0.30 * np.sin(2.0 * np.pi * freq * t)
        + 0.45 * np.sin(2.0 * np.pi * formant_hz * t)
        + 0.25 * np.sin(2.0 * np.pi * (formant_hz * 1.5) * t)
    ).astype(np.float32)
    stereo = np.vstack([sig, sig])
    with pedalboard.io.AudioFile(path, "w", sr, 2) as af:
        af.write(stereo)
    return path


def test_inspect_audio_file(tmp_path):
    wav = tmp_path / "speaker.wav"
    _make_dummy_wav(str(wav), duration_s=1.5, sr=44100)

    info = AT.inspect_audio_file(str(wav))
    assert info.is_valid is True
    assert info.filename == "speaker.wav"
    assert pytest.approx(info.duration_s, abs=0.05) == 1.5
    assert info.channels == 2
    assert info.samplerate == 44100

    # Nonexistent file returns invalid info
    bad = AT.inspect_audio_file(str(tmp_path / "nope.wav"))
    assert bad.is_valid is False
    assert "exist" in bad.error.lower()


def test_voice_model_trainer_end_to_end_export_and_onnx_inference(tmp_path):
    wav_dark = str(tmp_path / "dark_voice.wav")
    wav_bright = str(tmp_path / "bright_voice.wav")
    _make_dummy_wav(wav_dark, duration_s=2.0, freq=140.0, formant_hz=600.0)
    _make_dummy_wav(wav_bright, duration_s=2.0, freq=260.0, formant_hz=4200.0)

    models_dir = str(tmp_path / "ai_models")
    progress_history: list[AT.TrainingProgress] = []

    cfg1 = AT.TrainingJobConfig(
        voice_name="Dark Overlord",
        input_files=[wav_dark],
        epochs=20,
        target_sr=44100,
        normalize_loudness=True,
    )
    trainer1 = AT.VoiceModelTrainer(cfg1, models_dir=models_dir, progress_cb=progress_history.append)
    trainer1.start()
    trainer1.join(timeout=15.0)
    assert trainer1.is_running is False

    cfg2 = AT.TrainingJobConfig(
        voice_name="Bright Seraph",
        input_files=[wav_bright],
        epochs=20,
        target_sr=44100,
        normalize_loudness=True,
    )
    trainer2 = AT.VoiceModelTrainer(cfg2, models_dir=models_dir)
    trainer2.start()
    trainer2.join(timeout=15.0)

    stages = [p.stage for p in progress_history]
    assert "preparing" in stages
    assert "extracting" in stages
    assert "indexing" in stages
    assert "training" in stages
    assert "exporting" in stages
    assert "completed" in stages

    # Verify loss genuinely decreased during Adam neural training
    train_losses = [p.loss for p in progress_history if p.stage == "training"]
    assert len(train_losses) >= 5
    assert train_losses[-1] <= train_losses[0]

    # Verify ONNX Runtime loads the exported .onnx model and .index codebook
    info_dark = AV.get_voice_model("onnx:dark_overlord.onnx", models_dir)
    info_bright = AV.get_voice_model("onnx:bright_seraph.onnx", models_dir)
    assert info_dark is not None and info_bright is not None

    rt_dark = AV.get_onnx_runtime(info_dark)
    assert rt_dark is not None
    assert rt_dark.is_mandible_vocoder is True
    assert rt_dark.index_keys is not None

    # Verify AIVoicePlugin produces measurably distinct spectral output for the two trained models
    # even when all manual sliders (pitch=0, formant=0) are identical
    sr = 48000.0
    t = np.arange(4096, dtype=np.float32) / sr
    test_sig = (
        0.2 * np.sin(2.0 * np.pi * 180.0 * t)
        + 0.2 * np.sin(2.0 * np.pi * 700.0 * t)
        + 0.2 * np.sin(2.0 * np.pi * 3800.0 * t)
    ).astype(np.float32)
    stereo_in = np.vstack([test_sig, test_sig])

    plugin = load_internal_plugin(AV.AI_VOICE_PLUGIN_PATH)
    plugin.set_model(info_dark.id, apply_defaults=False, models_dir=models_dir)
    plugin.parameters["pitch"].value = 0.0
    plugin.parameters["formant"].value = 0.0
    plugin.parameters["index_rate"].value = 100.0
    plugin.parameters["breathiness"].value = 0.0
    out_dark = plugin.process(stereo_in, sr, reset=True)

    plugin.set_model(info_bright.id, apply_defaults=False, models_dir=models_dir)
    out_bright = plugin.process(stereo_in, sr, reset=True)

    assert not np.allclose(out_dark, out_bright, atol=1e-3)


def test_ai_trainer_and_external_guide_dialog_ui_compliance(qapp, sample_core, tmp_path):
    apply_theme(qapp, Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    wav = str(tmp_path / "voice_sample.wav")
    _make_dummy_wav(wav, duration_s=2.0)

    models_dir = str(tmp_path / "test_models")
    dlg = AITrainerDialog(sample_core, None, models_dir=models_dir)
    guide = ExternalTrainingGuideDialog(models_dir, None)
    try:
        for w in (dlg, guide):
            w.setAttribute(Qt.WA_DontShowOnScreen)
            w.show()
        for _ in range(3):
            qapp.processEvents()

        for w in (dlg, guide):
            assert off_scale_spacing(w) == []
            assert untiered_buttons(w) == []
            assert find_clipped_text(w) == []
            assert find_overflow(w) == []

        # Add files to the dataset list
        dlg.add_files([wav])
        assert dlg.file_list.count() == 1
        assert "1 valid files" in dlg.dataset_stats_lbl.text()

        # Remove files
        dlg.file_list.setCurrentRow(0)
        dlg._on_remove_selected()
        assert dlg.file_list.count() == 0

        # Clear files
        dlg.add_files([wav])
        dlg._on_clear_files()
        assert dlg.file_list.count() == 0
    finally:
        for w in (guide, dlg):
            w.hide()
            w.deleteLater()
        _flush()


def test_rvc_engine_selector_and_detection(tmp_path, monkeypatch):
    assert AT.find_mandible_rvc_exe() is None or isinstance(AT.find_mandible_rvc_exe(), str)

    # Custom env var pointing to fake exe
    fake_exe = tmp_path / "fake_rvc.exe"
    fake_exe.write_text("dummy")
    monkeypatch.setenv("MANDIBLE_RVC_EXE", str(fake_exe))
    assert AT.find_mandible_rvc_exe() == str(fake_exe)
