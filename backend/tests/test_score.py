import xml.etree.ElementTree as ET

import numpy as np
import pretty_midi

from backend.lingpu.events import NoteEvent, PedalEvent, Transcription
from backend.lingpu.score import estimate_bpm, export_artifacts


def test_exports_chord_two_hands_pedal_and_initial_rest(tmp_path):
    tr = Transcription(
        notes=[
            NoteEvent(60, 0.5, 1.0, 70),
            NoteEvent(64, 0.5, 1.0, 75),
            NoteEvent(48, 0.5, 1.5, 90),
            NoteEvent(60, 1.5, 2.0, 85),
        ],
        pedals=[PedalEvent(0.4, 1.2)],
    )
    meta = export_artifacts(tr, "sample", tmp_path, 120)
    midi = pretty_midi.PrettyMIDI(str(tmp_path / "score.mid"))
    notes = midi.instruments[0].notes
    assert sorted(n.pitch for n in notes if n.start < 1) == [48, 60, 64]
    assert any(c.number == 64 and c.value == 127 for c in midi.instruments[0].control_changes)
    assert any(c.number == 64 and c.value == 0 for c in midi.instruments[0].control_changes)
    root = ET.parse(tmp_path / "score.musicxml").getroot()
    xml_notes = root.findall(".//note")
    assert len([n for n in xml_notes if n.find("pitch") is not None]) == 4
    assert any(n.find("rest") is not None for n in xml_notes)
    assert len(root.findall(".//part")) == 2
    assert meta["note_count"] == 4 and meta["duration"] == 2


def test_long_note_is_tied_across_measures(tmp_path):
    tr = Transcription([NoteEvent(72, 0.0, 5.0, 100)], [])
    export_artifacts(tr, "long", tmp_path, 120, "4/4", 16)
    root = ET.parse(tmp_path / "score.musicxml").getroot()
    assert len(root.findall(".//tie[@type='start']")) >= 1
    assert len(root.findall(".//tie[@type='stop']")) >= 1
    # Every measure begins with attributes where applicable and declares meter.
    for part in root.findall("part"):
        assert all(m.get("number") for m in part.findall("measure"))
        attrs = part.find("measure/attributes")
        assert attrs.find("time/beats") is not None


def test_silence_tempo_fallback():
    assert estimate_bpm(np.zeros(1000), 22050) == 120.0


def test_overlapping_same_pitch_retrigger_is_preserved_and_truncated(tmp_path):
    tr = Transcription([NoteEvent(60, 0, 1.0, 70), NoteEvent(60, 0.5, 0.75, 95)], [])
    export_artifacts(tr, "reattack", tmp_path, 120)
    midi_notes = sorted(
        pretty_midi.PrettyMIDI(str(tmp_path / "score.mid")).instruments[0].notes,
        key=lambda n: n.start,
    )
    assert len(midi_notes) == 2
    assert midi_notes[0].end == midi_notes[1].start == 0.5
    root = ET.parse(tmp_path / "score.musicxml").getroot()
    score_notes = [n for n in root.findall(".//note") if n.find("pitch") is not None]
    assert len(score_notes) == 2
    assert root.findtext("work/work-title") == "reattack"
    assert len({len(part.findall("measure")) for part in root.findall("part")}) == 1


def test_musicxml_display_types_match_dotted_durations(tmp_path):
    # This yields nonstandard 3/4-quarter and 1/4-quarter durations after beat conversion.
    tr = Transcription([NoteEvent(65, 0, 0.375, 80), NoteEvent(67, 0.375, 0.5, 80)], [])
    export_artifacts(tr, "durations", tmp_path, 120)
    root = ET.parse(tmp_path / "score.musicxml").getroot()
    allowed = {
        "whole": 4,
        "half": 2,
        "quarter": 1,
        "eighth": 0.5,
        "16th": 0.25,
        "32nd": 0.125,
        "64th": 0.0625,
    }
    for node in root.findall(".//note"):
        typ = node.findtext("type")
        dots = len(node.findall("dot"))
        shown = allowed[typ] * sum(2**-i for i in range(dots + 1))
        actual = int(node.findtext("duration")) / 16
        assert abs(shown - actual) < 1e-8


def test_hands_are_on_expected_staff_and_empty_hand_has_full_measure_rest(tmp_path):
    tr = Transcription([NoteEvent(72, 0, 1, 90), NoteEvent(48, 0, 1, 80)], [])
    export_artifacts(tr, "hands", tmp_path, 120)
    root = ET.parse(tmp_path / "score.musicxml").getroot()
    right, left = root.findall("part")

    def midi_pitches(part):
        result = []
        for note in part.findall(".//note"):
            pitch = note.find("pitch")
            if pitch is not None:
                import music21

                text = pitch.findtext("step")
                alter = int(pitch.findtext("alter", "0"))
                octave = int(pitch.findtext("octave"))
                result.append(
                    int(
                        music21.pitch.Pitch(
                            f"{text}{'#' if alter == 1 else 'b' if alter == -1 else ''}{octave}"
                        ).midi
                    )
                )
        return result

    assert midi_pitches(right) == [72]
    assert midi_pitches(left) == [48]
    assert all(
        measure.find("attributes/time") is not None
        for part in (right, left)
        for measure in part.findall("measure")
    )

    # In a measure without events, a full-measure rest still fills the voice.
    export_artifacts(Transcription([NoteEvent(72, 0, 1, 90)], []), "empty", tmp_path, 120)
    root = ET.parse(tmp_path / "score.musicxml").getroot()
    empty_left = root.findall("part")[1]
    rests = [n for n in empty_left.findall("measure[1]/note") if n.find("rest") is not None]
    assert sum(int(n.findtext("duration")) for n in rests) == 4 * 16


def test_chord_is_one_voice_event_and_survives_music21_parse(tmp_path):
    from music21 import converter

    tr = Transcription(
        [
            NoteEvent(60, 0, 1, 70),
            NoteEvent(64, 0, 1, 80),
            NoteEvent(67, 0, 1, 90),
            NoteEvent(62, 1, 2, 75),
        ],
        [],
    )
    export_artifacts(tr, "和弦测试", tmp_path, 120)
    xml_path = tmp_path / "score.musicxml"
    root = ET.parse(xml_path).getroot()
    assert len(root.findall(".//chord")) >= 1
    # The simultaneous triad occupies one voice event; the later note remains
    # in that same voice rather than adding a voice for each chord tone.
    right = root.findall("part")[0]
    assert {
        n.findtext("voice") for n in right.findall(".//note") if n.find("pitch") is not None
    } == {"1"}
    parsed = converter.parse(str(xml_path))
    assert (
        sum(
            sum(len(getattr(note, "pitches", ())) or 1 for note in measure.notes)
            for part in parsed.parts
            for measure in part.getElementsByClass("Measure")
        )
        == 4
    )


def test_chinese_title_does_not_break_midi_export(tmp_path):
    export_artifacts(Transcription([NoteEvent(60, 0, 0.5, 70)], []), "中文标题", tmp_path, 120)
    midi = pretty_midi.PrettyMIDI(str(tmp_path / "score.mid"))
    assert midi.instruments[0].name == "Piano"
    assert ET.parse(tmp_path / "score.musicxml").getroot().findtext("work/work-title") == "中文标题"


def test_nonstandard_chord_duration_preserves_simultaneous_fragments(tmp_path):
    import music21

    tr = Transcription([NoteEvent(72, 0, 1.25), NoteEvent(76, 0, 1.25)])
    export_artifacts(tr, "fragment", tmp_path, 60)
    score = music21.converter.parse(tmp_path / "score.musicxml")
    chords = list(score.parts[0].recurse().getElementsByClass(music21.chord.Chord))
    assert chords and all(
        set(c.pitches[i].midi for i in range(len(c.pitches))) == {72, 76} for c in chords
    )
    assert sum(float(c.quarterLength) for c in chords) == 1.25
