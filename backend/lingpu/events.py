"""Shared immutable-ish event containers used by transcription and score export."""

from dataclasses import asdict, dataclass, field
import json
import uuid
from pathlib import Path


@dataclass
class NoteEvent:
    pitch: int
    start: float
    end: float
    velocity: int = 90
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    hand: str | None = None


@dataclass
class PedalEvent:
    start: float
    end: float


@dataclass
class Transcription:
    notes: list[NoteEvent] = field(default_factory=list)
    pedals: list[PedalEvent] = field(default_factory=list)

    def save(self, path: Path):
        path.write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")

    @classmethod
    def read(cls, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            [NoteEvent(**n) for n in data["notes"]], [PedalEvent(**p) for p in data["pedals"]]
        )

    @classmethod
    def from_midi(cls, path: Path):
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(str(path))
        notes, pedals = [], []
        for instrument in midi.instruments:
            if instrument.is_drum:
                continue
            notes.extend(NoteEvent(n.pitch, n.start, n.end, n.velocity) for n in instrument.notes)
            start = None
            for cc in sorted(instrument.control_changes, key=lambda c: c.time):
                if cc.number != 64:
                    continue
                if cc.value >= 64 and start is None:
                    start = cc.time
                elif cc.value < 64 and start is not None:
                    pedals.append(PedalEvent(start, cc.time))
                    start = None
            if start is not None and midi.get_end_time() > start:
                pedals.append(PedalEvent(start, midi.get_end_time()))
        return cls(notes, pedals)
