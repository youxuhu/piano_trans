"""Fast adapter tests that do not load PyTorch or the real checkpoint."""

import hashlib
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from backend.lingpu.models import ByteDanceAdapter


class _FakeRuntime:
    segment_samples = 10
    frames_per_second = 10
    classes_num = 1
    onset_threshold = 0.3
    offset_threshod = 0.3
    frame_threshold = 0.1
    pedal_offset_threshold = 0.2
    model = object()

    def enframe(self, audio, segment_samples):
        hop = segment_samples // 2
        return np.asarray(
            [
                audio[0, start : start + segment_samples]
                for start in range(0, audio.shape[1] - segment_samples + 1, hop)
            ]
        )

    def deframe(self, output):
        return output.reshape(-1, 1)


class _FakePostProcessor:
    frame_count = None

    def __init__(self, *_args, **_kwargs):
        pass

    def output_dict_to_midi_events(self, outputs):
        type(self).frame_count = outputs["frame_output"].shape[0]
        return (
            [
                {"midi_note": 60, "onset_time": 2.0, "offset_time": 4.0, "velocity": 90},
                {"midi_note": 61, "onset_time": 3.0, "offset_time": 4.0, "velocity": 90},
            ],
            [
                {"onset_time": 2.2, "offset_time": 3.0},
                {"onset_time": 3.0, "offset_time": 3.1},
            ],
        )


def test_transcribe_crops_by_frame_duration_and_reports_percent_progress(monkeypatch):
    package = types.ModuleType("piano_transcription_inference")
    package.__path__ = []
    forward_module = types.ModuleType("piano_transcription_inference.pytorch_utils")
    forward_module.forward = lambda _model, batch, batch_size: {
        "frame_output": np.zeros((len(batch), 10, 1), dtype=np.float32)
    }
    librosa_stub = types.ModuleType("librosa")
    monkeypatch.setitem(sys.modules, "piano_transcription_inference", package)
    monkeypatch.setitem(sys.modules, "piano_transcription_inference.pytorch_utils", forward_module)
    monkeypatch.setitem(sys.modules, "librosa", librosa_stub)

    adapter = ByteDanceAdapter(Path("unused"))
    adapter._runtime = _FakeRuntime()
    adapter._sample_rate = 10
    adapter._processor_class = _FakePostProcessor
    progress = []

    result = adapter.transcribe(np.zeros(25, dtype=np.float32), 10, progress.append)

    assert _FakePostProcessor.frame_count == 25  # 2.5 seconds at 10 frames/sec
    assert [(event.pitch, event.start, event.end) for event in result.notes] == [(60, 2.0, 2.5)]
    assert [(event.start, event.end) for event in result.pedals] == [(2.2, 2.5)]
    assert progress == [20.0, 40.0, 60.0, 80.0, 100.0]
    assert all(0.0 <= value <= 100.0 for value in progress)


def test_load_rejects_checkpoint_hash_mismatch_before_model_import(tmp_path):
    checkpoint = tmp_path / "bytedance.pth"
    # Sparse file is large enough to pass the upstream package's auto-download
    # size guard, without allocating the checkpoint's full storage in this test.
    with checkpoint.open("wb") as stream:
        stream.truncate(160_000_000)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "file": checkpoint.name,
                "sha256": hashlib.sha256(b"not the checkpoint").hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        ByteDanceAdapter(tmp_path).load()


def test_load_rejects_too_small_checkpoint_before_upstream_can_download(tmp_path):
    checkpoint = tmp_path / "bytedance.pth"
    checkpoint.write_bytes(b"partial")

    with pytest.raises(ValueError, match="too small"):
        ByteDanceAdapter(tmp_path).load()
