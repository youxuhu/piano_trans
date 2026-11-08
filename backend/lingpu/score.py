"""Export transcribed piano events to MIDI and MusicXML."""

from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pretty_midi

from .events import Transcription


def estimate_bpm(audio: np.ndarray, sr: int) -> float:
    """Estimate tempo with librosa; use a stable 120 BPM fallback for silence/errors."""
    signal = np.asarray(audio, dtype=float)
    if signal.size == 0 or not np.isfinite(signal).any() or np.nanmax(np.abs(signal)) < 1e-7:
        return 120.0
    try:
        import librosa

        clean = np.nan_to_num(signal)
        tempo = librosa.feature.tempo(y=clean, sr=sr, aggregate=np.median)
        value = float(np.asarray(tempo).reshape(-1)[0])
        return value if math.isfinite(value) and value > 0 else 120.0
    except Exception:
        return 120.0


def _pitch_xml(parent, midi_pitch: int, fifths=0):
    import music21

    p = music21.pitch.Pitch(midi=int(midi_pitch))
    if fifths < 0 and p.accidental and p.accidental.alter > 0:
        p = p.getEnharmonic()
    elem = ET.SubElement(parent, "pitch")
    ET.SubElement(elem, "step").text = p.step
    if p.accidental is not None and p.accidental.alter:
        ET.SubElement(elem, "alter").text = str(int(p.accidental.alter))
    ET.SubElement(elem, "octave").text = str(p.octave)


def _duration_chunks(duration: float, divisions: int) -> list[tuple[int, str, int]]:
    """Represent a duration as legal MusicXML values (ticks, type, dots)."""
    ticks = max(1, round(duration * divisions))
    # Longest legal values first. A dotted value is 3/2 or 7/4 of its base.
    values = []
    for base_ticks, name in [
        (4 * divisions, "whole"),
        (2 * divisions, "half"),
        (divisions, "quarter"),
        (divisions // 2, "eighth"),
        (divisions // 4, "16th"),
        (divisions // 8, "32nd"),
        (divisions // 16, "64th"),
    ]:
        if base_ticks < 1:
            continue
        values.append((base_ticks, name, 0))
        if base_ticks % 2 == 0:
            values.append((base_ticks * 3 // 2, name, 1))
        if base_ticks % 4 == 0:
            values.append((base_ticks * 7 // 4, name, 2))
    values = sorted(set(values), key=lambda x: x[0], reverse=True)
    chunks = []
    while ticks:
        candidate = next((v for v in values if v[0] <= ticks), None)
        if candidate is None:
            # MusicXML supports arbitrary duration ticks; the smallest type is a
            # display hint while <duration> remains the authoritative length.
            chunks.append((ticks, "64th", 0))
            break
        chunks.append(candidate)
        ticks -= candidate[0]
    return chunks


def _append_rest(measure, dur, voice, divisions):
    for ticks, typ, dots in _duration_chunks(dur, divisions):
        el = ET.SubElement(measure, "note")
        ET.SubElement(el, "rest")
        ET.SubElement(el, "duration").text = str(ticks)
        ET.SubElement(el, "voice").text = str(voice)
        ET.SubElement(el, "type").text = typ
        for _ in range(dots):
            ET.SubElement(el, "dot")


def _append_chord(
    measure, pitches, dur, voice, divisions, tie_start=False, tie_stop=False, fifths=0
):
    chunks = _duration_chunks(dur, divisions)
    # MusicXML chord members must follow the corresponding first note of each
    # duration fragment, rather than following all fragments of another pitch.
    for index, (ticks, typ, dots) in enumerate(chunks):
        for pitch_index, pitch in enumerate(pitches):
            el = ET.SubElement(measure, "note")
            if pitch_index:
                ET.SubElement(el, "chord")
            _pitch_xml(el, pitch, fifths)
            ET.SubElement(el, "duration").text = str(ticks)
            stop = (tie_stop and index == 0) or index > 0
            start = (tie_start and index == len(chunks) - 1) or index < len(chunks) - 1
            if stop:
                ET.SubElement(el, "tie", type="stop")
            if start:
                ET.SubElement(el, "tie", type="start")
            ET.SubElement(el, "voice").text = str(voice)
            ET.SubElement(el, "type").text = typ
            for _ in range(dots):
                ET.SubElement(el, "dot")
            if stop or start:
                notations = ET.SubElement(el, "notations")
                if stop:
                    ET.SubElement(notations, "tied", type="stop")
                if start:
                    ET.SubElement(notations, "tied", type="start")


def _write_musicxml(
    transcription: Transcription,
    path: Path,
    bpm: float,
    time_signature: str,
    quantization: int,
    title: str,
    hand_split: int = 64,
    key_fifths: int = 0,
):
    try:
        numerator, denominator = (int(x) for x in time_signature.split("/"))
    except Exception as exc:
        raise ValueError("time_signature must look like '4/4'") from exc
    if numerator <= 0 or denominator <= 0 or quantization <= 0:
        raise ValueError("time signature and quantization must be positive")
    measure_q = numerator * 4 / denominator
    grid = 4.0 / quantization

    # Quantize in beats, preserving positive durations. Keep same-pitch overlaps
    # distinct only when they are sequential; overlapping duplicates are invalid.
    notes = []
    for n in transcription.notes:
        start = max(0.0, float(n.start) * bpm / 60)
        end = max(start + grid, float(n.end) * bpm / 60)
        qs = round(start / grid) * grid
        qe = max(qs + grid, round(end / grid) * grid)
        notes.append([int(n.pitch), qs, qe, max(1, min(127, int(n.velocity))), n.hand])
    notes.sort(key=lambda x: (x[1], x[2], x[0]))
    filtered = []
    by_pitch = {}
    for note in notes:
        prior = by_pitch.get(note[0])
        if prior and note[1] < prior[2]:
            # Retrigger the same pitch at the new onset; truncate the held note.
            prior[2] = note[1]
            if prior[2] <= prior[1]:
                filtered.remove(prior)
        filtered.append(note)
        by_pitch[note[0]] = note

    # Split into conventional piano hands with a soft continuity penalty.
    hands = [[], []]
    last = [60, 60]
    for note in sorted(filtered, key=lambda x: (x[1], x[0])):
        pitch = note[0]
        costs = [
            abs(pitch - last[h]) / 12 + (0 if (pitch >= hand_split) == (h == 0) else 1.7)
            for h in range(2)
        ]
        hand = (
            0
            if note[4] == "right"
            else 1
            if note[4] == "left"
            else 0
            if costs[0] <= costs[1]
            else 1
        )
        hands[hand].append(note)
        last[hand] = pitch

    root = ET.Element("score-partwise", version="3.1")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = title
    ET.SubElement(root, "movement-title").text = title
    part_list = ET.SubElement(root, "part-list")
    group = ET.SubElement(part_list, "part-group", type="start", number="1")
    ET.SubElement(group, "group-symbol").text = "brace"
    ET.SubElement(group, "group-barline").text = "yes"
    for channel, (pid, name) in enumerate((("P1", "右手"), ("P2", "左手")), 1):
        sp = ET.SubElement(part_list, "score-part", id=pid)
        ET.SubElement(sp, "part-name").text = name
        instrument = ET.SubElement(sp, "score-instrument", id=pid + "-I1")
        ET.SubElement(instrument, "instrument-name").text = "Piano"
        midi_instrument = ET.SubElement(sp, "midi-instrument", id=pid + "-I1")
        ET.SubElement(midi_instrument, "midi-channel").text = str(channel)
        ET.SubElement(midi_instrument, "midi-program").text = "1"
    ET.SubElement(part_list, "part-group", type="stop", number="1")

    # Collapse pitches with identical onset/end in the same hand into one
    # rhythmic event; pitches in that event are serialized as MusicXML chords.
    hand_events = []
    for hand_notes in hands:
        grouped = {}
        for note in hand_notes:
            grouped.setdefault((note[1], note[2]), []).append(note)
        events = [
            {"start": start, "end": end, "pitches": sorted(items, key=lambda n: n[0])}
            for (start, end), items in grouped.items()
        ]
        hand_events.append(sorted(events, key=lambda e: (e["start"], e["end"])))

    total_duration = max((e["end"] for hand in hand_events for e in hand), default=0)
    count = max(1, math.ceil(max(total_duration, measure_q) / measure_q))
    for h, pid in enumerate(("P1", "P2")):
        part = ET.SubElement(root, "part", id=pid)
        # Each lane is a monophonic rhythmic stream. Simultaneous chord tones
        # stay together in one event instead of creating one voice per pitch.
        lanes: list[list[dict]] = []
        for event in hand_events[h]:
            available = [lane for lane in lanes if lane[-1]["end"] <= event["start"]]
            lane = min(
                available,
                key=lambda lane: abs(lane[-1]["pitches"][-1][0] - event["pitches"][-1][0]),
                default=None,
            )
            if lane is None:
                lane = []
                lanes.append(lane)
            lane.append(event)
        if not lanes:
            lanes = [[]]
        attrs_template = ET.Element("attributes")
        ET.SubElement(attrs_template, "divisions").text = str(quantization)
        key = ET.SubElement(attrs_template, "key")
        ET.SubElement(key, "fifths").text = str(key_fifths)
        time = ET.SubElement(attrs_template, "time")
        ET.SubElement(time, "beats").text = str(numerator)
        ET.SubElement(time, "beat-type").text = str(denominator)
        clef = ET.SubElement(attrs_template, "clef")
        ET.SubElement(clef, "sign").text = "G" if h == 0 else "F"
        ET.SubElement(clef, "line").text = "2" if h == 0 else "4"
        for mi in range(count):
            measure = ET.SubElement(part, "measure", number=str(mi + 1))
            measure.append(deepcopy(attrs_template))
            if mi == 0:
                direction = ET.SubElement(measure, "direction", placement="above")
                dtype = ET.SubElement(direction, "direction-type")
                met = ET.SubElement(dtype, "metronome")
                ET.SubElement(met, "beat-unit").text = "quarter"
                ET.SubElement(met, "per-minute").text = str(round(bpm, 2))
                ET.SubElement(direction, "sound", tempo=str(round(bpm, 2)))
            lo, hi = mi * measure_q, (mi + 1) * measure_q
            for vi, lane in enumerate(lanes, 1):
                if vi > 1:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(round(measure_q * quantization))
                cursor = lo
                for note in lane:
                    a, b = max(note["start"], lo), min(note["end"], hi)
                    if b <= a:
                        continue
                    if a > cursor + 1e-8:
                        _append_rest(measure, a - cursor, vi, quantization)
                    _append_chord(
                        measure,
                        [p[0] for p in note["pitches"]],
                        b - a,
                        vi,
                        quantization,
                        tie_start=note["end"] > hi + 1e-8,
                        tie_stop=note["start"] < lo - 1e-8,
                        fifths=key_fifths,
                    )
                    cursor = max(cursor, b)
                if cursor < hi - 1e-8:
                    _append_rest(measure, hi - cursor, vi, quantization)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def export_artifacts(
    transcription: Transcription,
    title: str,
    output_dir: Path,
    bpm: float,
    time_signature: str = "4/4",
    quantization: int = 16,
    hand_split: int = 64,
    key_fifths: int | None = None,
) -> dict:
    """Write score.mid and score.musicxml, returning compact artifact metadata."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bpm = float(bpm) if math.isfinite(float(bpm)) and bpm > 0 else 120.0
    if key_fifths is None:
        key_fifths = estimate_key(transcription)
    midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    numerator, denominator = map(int, time_signature.split("/"))
    midi.time_signature_changes.append(pretty_midi.TimeSignature(numerator, denominator, 0))
    piano = pretty_midi.Instrument(
        program=pretty_midi.instrument_name_to_program("Acoustic Grand Piano"), name="Piano"
    )
    midi_events = sorted(
        (n for n in transcription.notes if float(n.end) > max(0.0, float(n.start))),
        key=lambda n: (max(0.0, float(n.start)), int(n.pitch)),
    )
    active_by_pitch = {}
    for n in midi_events:
        start, end, pitch = max(0.0, float(n.start)), float(n.end), int(n.pitch)
        prior = active_by_pitch.get(pitch)
        if prior and prior.end > start:
            prior.end = start
            if prior.end <= prior.start:
                piano.notes.remove(prior)
        event = pretty_midi.Note(
            velocity=max(1, min(127, int(n.velocity))), pitch=pitch, start=start, end=end
        )
        piano.notes.append(event)
        active_by_pitch[pitch] = event
    # Sustain pedal CC64 is represented as down/up transitions per event.
    transitions = []
    for p in transcription.pedals:
        start, end = max(0.0, float(p.start)), max(0.0, float(p.end))
        if end > start:
            transitions.extend(((start, 127), (end, 0)))
    for t, value in sorted(transitions):
        piano.control_changes.append(pretty_midi.ControlChange(number=64, value=value, time=t))
    midi.instruments.append(piano)
    midi.write(str(output_dir / "score.mid"))
    _write_musicxml(
        transcription,
        output_dir / "score.musicxml",
        bpm,
        time_signature,
        quantization,
        title,
        hand_split,
        key_fifths,
    )
    duration = max((float(n.end) for n in transcription.notes), default=0.0)
    return {
        "bpm": bpm,
        "time_signature": time_signature,
        "note_count": len(transcription.notes),
        "duration": duration,
        "settings": {
            "quantization": quantization,
            "hand_split": hand_split,
            "key_fifths": key_fifths,
        },
    }


def estimate_key(transcription):
    """Duration-weighted key estimate; sparse/no-note input keeps a neutral signature."""
    if len({n.pitch % 12 for n in transcription.notes}) < 3:
        return 0
    import music21

    excerpt = music21.stream.Stream()
    for event in transcription.notes:
        note = music21.note.Note(event.pitch)
        note.duration.quarterLength = max(0.01, event.end - event.start)
        excerpt.append(note)
    return max(-7, min(7, excerpt.analyze("key").sharps))
