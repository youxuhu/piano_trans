"""Benchmark metric input conventions and empty-set behavior."""

import sys
import types

import numpy as np

from backend.lingpu.events import NoteEvent, PedalEvent, Transcription
from backend.scripts import benchmark


def test_score_passes_hz_pitches_and_positive_pedal_token(monkeypatch):
    calls = []

    def evaluate(ref_intervals, ref_pitches, pred_intervals, pred_pitches, **kwargs):
        calls.append(
            (
                ref_intervals.copy(),
                ref_pitches.copy(),
                pred_intervals.copy(),
                pred_pitches.copy(),
                kwargs,
            )
        )
        return {"F-measure": 0.75, "F-measure_no_offset": 0.9}

    fake_mir_eval = types.SimpleNamespace(transcription=types.SimpleNamespace(evaluate=evaluate))
    monkeypatch.setitem(sys.modules, "mir_eval", fake_mir_eval)
    monkeypatch.setattr(
        benchmark, "_midi_notes", lambda _path: (np.asarray([[0.0, 0.5]]), np.asarray([69]))
    )
    monkeypatch.setattr(benchmark, "_midi_pedals", lambda _path: np.asarray([[0.0, 1.0]]))
    prediction = Transcription(
        notes=[NoteEvent(pitch=69, start=0.0, end=0.5, velocity=80)],
        pedals=[PedalEvent(start=0.0, end=1.0)],
    )

    scores = benchmark._score(None, prediction)

    assert scores["onset_f1"] == 0.9
    assert scores["onset_offset_f1"] == 0.75
    assert scores["pedal_onset_f1"] == 0.9
    assert scores["pedal_onset_offset_f1"] == 0.75
    assert calls[0][1][0] == 440.0
    assert calls[0][3][0] == 440.0
    assert calls[1][1][0] == calls[1][3][0] == 440.0
    assert calls[1][4]["offset_min_tolerance"] == 0.05


def test_score_handles_empty_note_and_pedal_predictions_without_mir_eval():
    assert (
        benchmark._safe_transcription_evaluate(
            None, np.empty((0, 2)), np.empty(0), np.empty((0, 2)), np.empty(0)
        )["F-measure"]
        == 1.0
    )
    assert (
        benchmark._safe_transcription_evaluate(
            None, np.asarray([[0.0, 1.0]]), np.asarray([440.0]), np.empty((0, 2)), np.empty(0)
        )["F-measure"]
        == 0.0
    )
