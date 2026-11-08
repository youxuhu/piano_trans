#!/usr/bin/env python3
"""Run comparable single-file transcription benchmarks and optional scoring."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.lingpu.models import create_transcriber


def _midi_notes(path: Path) -> tuple[np.ndarray, np.ndarray]:
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(str(path))
    notes = [n for inst in pm.instruments for n in inst.notes]
    intervals = np.asarray([[n.start, n.end] for n in notes], dtype=float).reshape(-1, 2)
    pitches = np.asarray([n.pitch for n in notes], dtype=int)
    return intervals, pitches


def _midi_pedals(path: Path) -> np.ndarray:
    import mido

    midi = mido.MidiFile(str(path))
    active: dict[int, float] = {}
    intervals: list[tuple[float, float]] = []
    seconds, tempo = 0.0, 500000
    for msg in mido.merge_tracks(midi.tracks):
        seconds += mido.tick2second(msg.time, midi.ticks_per_beat, tempo)
        if msg.type == "set_tempo":
            tempo = msg.tempo
        elif msg.type == "control_change" and msg.control == 64:
            if msg.value >= 64 and msg.channel not in active:
                active[msg.channel] = seconds
            elif msg.value < 64 and msg.channel in active:
                intervals.append((active.pop(msg.channel), seconds))
    intervals.extend((start, seconds) for start in active.values())
    return np.asarray(intervals, dtype=float).reshape(-1, 2)


def _score(reference: Path, predicted) -> dict[str, object]:
    import mir_eval

    ref_intervals, ref_pitches = _midi_notes(reference)
    pred_intervals = np.asarray([[n.start, n.end] for n in predicted.notes], dtype=float).reshape(
        -1, 2
    )
    pred_pitches = np.asarray([n.pitch for n in predicted.notes], dtype=int)
    # Use physical key-down note intervals as encoded in MIDI; pedal does not
    # extend note-offs on either side of the comparison.
    ref_hz = 440.0 * np.power(2.0, (ref_pitches - 69) / 12.0)
    pred_hz = 440.0 * np.power(2.0, (pred_pitches - 69) / 12.0)
    note_scores = _safe_transcription_evaluate(
        mir_eval, ref_intervals, ref_hz, pred_intervals, pred_hz
    )
    ref_pedals = _midi_pedals(reference)
    pred_pedals = np.asarray([[p.start, p.end] for p in predicted.pedals], dtype=float).reshape(
        -1, 2
    )
    # mir_eval expects pitches in Hz; use the same constant token for every
    # CC64 interval so matching is solely by onset and offset time.
    pedal_scores = _safe_transcription_evaluate(
        mir_eval,
        ref_pedals,
        np.full(len(ref_pedals), 440.0),
        pred_pedals,
        np.full(len(pred_pedals), 440.0),
    )
    return {
        "reference_note_count": int(len(ref_pitches)),
        "predicted_note_count": int(len(pred_pitches)),
        "onset_f1": float(note_scores["F-measure_no_offset"]),
        "onset_offset_f1": float(note_scores["F-measure"]),
        "offset_tolerance_seconds": 0.05,
        "reference_pedal_count": int(len(ref_pedals)),
        "predicted_pedal_count": int(len(pred_pedals)),
        "pedal_onset_f1": float(pedal_scores["F-measure_no_offset"]),
        "pedal_onset_offset_f1": float(pedal_scores["F-measure"]),
        "pedal_convention": "CC64 down >=64 to up <64; note offsets are not extended by pedal",
    }


def _safe_transcription_evaluate(
    mir_eval,
    ref_intervals: np.ndarray,
    ref_pitches: np.ndarray,
    pred_intervals: np.ndarray,
    pred_pitches: np.ndarray,
) -> dict[str, float]:
    if not len(ref_intervals) and not len(pred_intervals):
        return {"F-measure": 1.0, "F-measure_no_offset": 1.0}
    if not len(ref_intervals) or not len(pred_intervals):
        return {"F-measure": 0.0, "F-measure_no_offset": 0.0}
    return mir_eval.transcription.evaluate(
        ref_intervals,
        ref_pitches,
        pred_intervals,
        pred_pitches,
        onset_tolerance=0.05,
        offset_ratio=0.2,
        offset_min_tolerance=0.05,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", choices=("bytedance", "transkun"), default="bytedance")
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--weights-dir", type=Path, default=Path(__file__).resolve().parents[1] / "weights"
    )
    parser.add_argument("--reference-midi", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--transkun-executable")
    args = parser.parse_args()

    import librosa

    y, sr = librosa.load(args.audio, sr=None, mono=True)
    options = {"executable": args.transkun_executable} if args.transkun_executable else {}
    adapter = create_transcriber(args.model, args.device, args.weights_dir, **options)
    gpu_peak = None
    torch = None
    # Parent-process CUDA allocation counters cannot see a Transkun CLI child.
    if args.model == "bytedance":
        try:
            import torch as torch_module

            torch = torch_module
            if args.device.startswith("cuda") and torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats(torch.device(args.device))
        except ImportError:
            pass
    start = time.perf_counter()
    adapter.load()
    if torch is not None and args.device.startswith("cuda") and torch.cuda.is_available():
        torch.cuda.synchronize(torch.device(args.device))
    load_seconds = time.perf_counter() - start
    start = time.perf_counter()
    result = adapter.transcribe(y, sr)
    if torch is not None and args.device.startswith("cuda") and torch.cuda.is_available():
        torch.cuda.synchronize(torch.device(args.device))
    inference_seconds = time.perf_counter() - start
    if torch is not None and args.device.startswith("cuda") and torch.cuda.is_available():
        gpu_peak = int(torch.cuda.max_memory_allocated(torch.device(args.device)))

    output = {
        "model": args.model,
        "device": args.device,
        "audio": str(args.audio.resolve()),
        "sample_rate": int(sr),
        "duration_seconds": float(len(y) / sr),
        "load_seconds": load_seconds,
        "inference_seconds": inference_seconds,
        "model_pipeline_seconds": load_seconds + inference_seconds,
        "peak_gpu_memory_bytes": gpu_peak,
        "peak_gpu_memory_note": (
            "unavailable: model runs in a child process; parent CUDA counters do not include it"
            if args.model == "transkun"
            else None
        ),
        "timing_scope": (
            "adapter.load() plus full transcribe() call; excludes audio decoding and top-level Python startup; Transkun transcribe() includes child startup, model loading, and inference"
            if args.model == "transkun"
            else "adapter.load() plus full transcribe() call; excludes audio decoding and top-level Python startup"
        ),
        "notes": [asdict(event) for event in result.notes],
        "pedals": [asdict(event) for event in result.pedals],
    }
    if args.reference_midi:
        output["metrics"] = _score(args.reference_midi, result)
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
