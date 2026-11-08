"""Generate a reproducible synthetic reference corpus and separately score notation/model output.

The additive tones are controlled signals, not a benchmark of real piano accuracy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import soundfile as sf

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.lingpu.events import NoteEvent, PedalEvent, Transcription
from backend.lingpu.score import export_artifacts
from backend.scripts.benchmark import _score


def cases():
    return {
        "melody": Transcription(
            [
                NoteEvent(p, 0.5 + i * 0.5, 1 + i * 0.5)
                for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72])
            ]
        ),
        "chords_two_hands": Transcription(
            [
                NoteEvent(p, t, t + 0.75)
                for t, pitches in [
                    (0, [48, 60, 64, 67]),
                    (1, [43, 59, 62, 67]),
                    (2, [45, 60, 64, 69]),
                ]
                for p in pitches
            ]
        ),
        "repeats_pedal": Transcription(
            [NoteEvent(60, i * 0.5, i * 0.5 + 0.375) for i in range(6)], [PedalEvent(0.1, 2.8)]
        ),
        "bar_ties": Transcription(
            [NoteEvent(48, 0, 4.5), NoteEvent(72, 1.5, 3), NoteEvent(76, 1.5, 3)]
        ),
        "silence": Transcription(),
    }


def render(events, sr=16000):
    duration = max([p.end for p in events.pedals] + [n.end for n in events.notes] + [2]) + 0.5
    audio = np.zeros(round(duration * sr), dtype=np.float32)
    for note in events.notes:
        end = max([p.end for p in events.pedals if p.start <= note.end <= p.end] + [note.end])
        start = round(note.start * sr)
        t = np.arange(round((end - note.start + 0.1) * sr)) / sr
        frequency = 440 * 2 ** ((note.pitch - 69) / 12)
        envelope = (1 - np.exp(-t * 150)) * np.exp(-t * 1.8)
        envelope *= np.minimum(1, np.maximum(0, (end - note.start + 0.1 - t) / 0.1))
        signal = (
            sum(
                np.sin(2 * np.pi * frequency * harmonic * t) / harmonic**2
                for harmonic in range(1, 6)
            )
            * envelope
        )
        length = min(len(signal), len(audio) - start)
        audio[start : start + length] += signal[:length] * note.velocity / 127
    peak = np.max(np.abs(audio))
    return audio * (0.8 / peak) if peak else audio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/lingpu-reference-suite"))
    parser.add_argument("--model", choices=["bytedance", "transkun"])
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    adapter = None
    load_seconds = None
    if args.model:
        from backend.lingpu.models import create_transcriber

        adapter = create_transcriber(
            args.model, args.device, Path(__file__).resolve().parents[1] / "weights"
        )
        started = time.perf_counter()
        adapter.load()
        load_seconds = time.perf_counter() - started
    import music21

    results = {}
    for name, events in cases().items():
        folder = args.output / name
        export_artifacts(events, name, folder, 120)
        events.save(folder / "events.json")
        audio = render(events)
        sf.write(folder / "reference.wav", audio, 16000)
        parsed = music21.converter.parse(folder / "score.musicxml").stripTies()
        parsed.write("midi", fp=str(folder / "notation.mid"))
        notation = Transcription.from_midi(folder / "notation.mid")
        result = {
            "reference_notes": len(events.notes),
            "notation": _score(folder / "score.mid", notation),
        }
        if adapter:
            started = time.perf_counter()
            predicted = adapter.transcribe(audio, 16000)
            result["recognition"] = _score(folder / "score.mid", predicted)
            result["inference_seconds"] = time.perf_counter() - started
        results[name] = result
        print(name, json.dumps(result, ensure_ascii=False))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(
        json.dumps(
            {
                "scope": "synthetic controlled signals; not real piano accuracy",
                "model": args.model,
                "load_seconds": load_seconds,
                "cases": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
