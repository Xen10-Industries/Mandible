"""Tests for the local AI voice model training engine, dataset preparation, and AITrainerDialog."""
from __future__ import annotations

import os
import pedalboard.io
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt

from mandible import ai_trainer as AT
from mandible import ai_voice as AV
from mandible.ui.app import apply_theme
from mandible.ui.dialogs.ai_trainer import AITrainerDialog
from mandible.ui.inspect import (find_clipped_text, find_overflow, off_scale_spacing,
                                 untiered_buttons)
from mandible.ui.look import BUILTIN_PALETTES, BUILTIN_SKINS, Look


def _flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _make_dummy_wav(path: str, duration_s: float = 2.0, sr: int = 44100, freq: float = 220.0) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    frames = int(sr * duration_s)
    t = np.arange(frames, dtype=np.float32) / sr
    sig = 0.4 * np.sin(2.0 * np.pi * freq * t).astype(np.float32)
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


def test_voice_model_trainer_end_to_end_export(tmp_path):
    wav1 = str(tmp_path / "clip1.wav")
    wav2 = str(tmp_path / "clip2.wav")
    _make_dummy_wav(wav1, duration_s=2.5, freq=200.0)
    _make_dummy_wav(wav2, duration_s=2.0, freq=220.0)

    models_dir = str(tmp_path / "ai_models")
    progress_history: list[AT.TrainingProgress] = []

    cfg = AT.TrainingJobConfig(
        voice_name="Commander Shepard",
        input_files=[wav1, wav2],
        epochs=15,  # short epoch run for fast test
        target_sr=40000,
        normalize_loudness=True,
    )

    trainer = AT.VoiceModelTrainer(
        cfg,
        models_dir=models_dir,
        progress_cb=progress_history.append,
    )
    assert trainer.is_running is False
    trainer.start()
    assert trainer.is_running is True
    trainer.join(timeout=10.0)
    assert trainer.is_running is False

    stages = [p.stage for p in progress_history]
    assert "preparing" in stages
    assert "extracting" in stages
    assert "training" in stages
    assert "exporting" in stages
    assert "completed" in stages

    # Check generated model files
    onnx_file = os.path.join(models_dir, "commander_shepard.onnx")
    index_file = os.path.join(models_dir, "commander_shepard.index")
    json_file = os.path.join(models_dir, "commander_shepard.json")

    assert os.path.isfile(onnx_file)
    assert os.path.isfile(index_file)
    assert os.path.isfile(json_file)
    assert os.path.getsize(onnx_file) > 100
    assert os.path.getsize(index_file) > 100

    # Model is immediately recognized and usable by Mandible's voice listing
    models = AV.list_voice_models(models_dir)
    target = next((m for m in models if m.name == "Commander Shepard"), None)
    assert target is not None
    assert target.id == "onnx:commander_shepard.onnx"
    assert target.kind == "onnx"
    assert os.path.isfile(target.model_path)
    assert os.path.isfile(target.index_path)


def test_ai_trainer_dialog_ui_compliance(qapp, sample_core, tmp_path):
    apply_theme(qapp, Look(BUILTIN_PALETTES["scarlet"], BUILTIN_SKINS["skeuomorphic"]))
    wav = str(tmp_path / "voice_sample.wav")
    _make_dummy_wav(wav, duration_s=2.0)

    models_dir = str(tmp_path / "test_models")
    dlg = AITrainerDialog(sample_core, None, models_dir=models_dir)
    try:
        dlg.setAttribute(Qt.WA_DontShowOnScreen)
        dlg.show()
        for _ in range(3):
            qapp.processEvents()

        assert off_scale_spacing(dlg) == []
        assert untiered_buttons(dlg) == []
        assert find_clipped_text(dlg) == []
        assert find_overflow(dlg) == []

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
        dlg.hide()
        dlg.deleteLater()
        _flush()
