"""Versioned event editing shared by HTTP handlers and the inference worker."""

from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import fcntl
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET

from .events import NoteEvent, PedalEvent, Transcription
from .score import export_artifacts


class EditConflict(ValueError):
    pass


@contextmanager
def score_lock(folder: Path):
    """Serialize mutations across HTTP threads and the separate GPU process."""
    with (folder / ".score.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def events_from_data(data):
    return Transcription(
        [NoteEvent(**n) for n in data["notes"]], [PedalEvent(**p) for p in data["pedals"]]
    )


def load_events(folder):
    path = folder / "events.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        events = events_from_data(raw)
        if all(n.get("id") for n in raw["notes"]):
            return events
    else:
        events = Transcription.from_midi(folder / "score.mid")
    temporary = folder / "events-migration.tmp"
    events.save(temporary)
    temporary.replace(path)
    return events


def score_options(item, folder):
    settings = item.get("settings", {})
    key = settings.get("key_fifths")
    if key is None:
        label = ET.parse(folder / "score.musicxml").findtext(".//key/fifths")
        key = int(label) if label is not None else 0
    return dict(
        bpm=item["bpm"] or 120,
        time_signature=item["time_signature"] or "4/4",
        quantization=settings.get("quantization", 16),
        hand_split=settings.get("hand_split", 64),
        key_fifths=key,
    )


def session_data(store, ident):
    item = store.score(ident)
    folder = store.root / ident
    events = load_events(folder)
    options = score_options(item, folder)
    with store.connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO score_history VALUES(?,?,?,?,?)",
            (
                ident,
                item["history_position"],
                json.dumps(asdict(events)),
                json.dumps(options),
                "初始结果",
            ),
        )
        following = db.execute(
            "SELECT 1 FROM score_history WHERE score_id=? AND position=?",
            (ident, item["history_position"] + 1),
        ).fetchone()
    return {
        **asdict(events),
        "revision": item["revision"],
        "can_undo": item["history_position"] > 0,
        "can_redo": bool(following),
        "duration": item["duration"],
        "options": options,
    }


def commit_change(store, ident, events, options, expected_revision, reason, history_position=None):
    """Build every artifact first, then commit a consistent new version with rollback."""
    item = store.score(ident)
    if item is None:
        raise ValueError("曲目已不存在")
    if item["revision"] != expected_revision:
        raise EditConflict("曲目已被更新，请重新载入音符后再操作")
    folder = store.root / ident
    session_data(store, ident)
    with tempfile.TemporaryDirectory(prefix="edit-", dir=folder) as temporary:
        target = Path(temporary)
        metadata = export_artifacts(events, item["title"], target, **options)
        events.save(target / "events.json")
        names = ("score.mid", "score.musicxml", "events.json")
        previous = {name: (folder / name).read_bytes() for name in names}
        for name in names:
            original = folder / ("original-" + name)
            if not original.exists():
                shutil.copy2(folder / name, original)
        position = item["history_position"] + 1 if history_position is None else history_position
        try:
            with store.connect() as db:
                # The file lock guards processes; the compare guards stale browser sessions.
                result = db.execute(
                    "UPDATE scores SET bpm=?,time_signature=?,note_count=?,settings=?,revision=revision+1,history_position=? WHERE id=? AND revision=?",
                    (
                        metadata["bpm"],
                        metadata["time_signature"],
                        metadata["note_count"],
                        json.dumps(metadata["settings"]),
                        position,
                        ident,
                        expected_revision,
                    ),
                )
                if result.rowcount != 1:
                    raise EditConflict("曲目已更新，请重新载入")
                if history_position is None:
                    db.execute(
                        "DELETE FROM score_history WHERE score_id=? AND position>?",
                        (ident, item["history_position"]),
                    )
                    db.execute(
                        "INSERT INTO score_history VALUES(?,?,?,?,?)",
                        (ident, position, json.dumps(asdict(events)), json.dumps(options), reason),
                    )
                for name in names:
                    (target / name).replace(folder / name)
        except Exception:
            for name, content in previous.items():
                (target / name).write_bytes(content)
                (target / name).replace(folder / name)
            raise
    return session_data(store, ident)


def move_history(store, ident, expected_revision, direction):
    item = store.score(ident)
    position = item["history_position"] + direction
    with store.connect() as db:
        row = db.execute(
            "SELECT * FROM score_history WHERE score_id=? AND position=?", (ident, position)
        ).fetchone()
    if not row:
        raise ValueError("没有可撤销的版本" if direction < 0 else "没有可重做的版本")
    return commit_change(
        store,
        ident,
        events_from_data(json.loads(row["events"])),
        json.loads(row["options"]),
        expected_revision,
        "撤销" if direction < 0 else "重做",
        history_position=position,
    )


def merge_region(original, replacement, start, end):
    # Note ownership is determined by onset: a held note starting before the
    # selection keeps its identity and original duration across the boundary.
    kept = [n for n in original.notes if n.start < start or n.start >= end]
    inserted = []
    for note in replacement.notes:
        if start <= note.start < end:
            # A selected-region retrigger cannot truncate a held note owned by
            # the untouched region. Include its original onset in the selection
            # when that held note itself needs to be replaced.
            if any(n.pitch == note.pitch and n.start < start and note.start < n.end for n in kept):
                continue
            inserted.append(
                NoteEvent(
                    note.pitch,
                    note.start,
                    min(end, note.end),
                    note.velocity,
                    id=note.id,
                    hand=note.hand,
                )
            )
    pedals = []
    for pedal in original.pedals:
        if pedal.end <= start or pedal.start >= end:
            pedals.append(pedal)
        else:
            if pedal.start < start:
                pedals.append(PedalEvent(pedal.start, start))
            if pedal.end > end:
                pedals.append(PedalEvent(end, pedal.end))
    pedals += [
        PedalEvent(max(start, p.start), min(end, p.end))
        for p in replacement.pedals
        if p.end > start and p.start < end
    ]
    merged_pedals = []
    for pedal in sorted(pedals, key=lambda p: p.start):
        if merged_pedals and pedal.start <= merged_pedals[-1].end:
            merged_pedals[-1].end = max(merged_pedals[-1].end, pedal.end)
        elif pedal.end > pedal.start:
            merged_pedals.append(PedalEvent(pedal.start, pedal.end))
    return Transcription(
        sorted(kept + inserted, key=lambda n: (n.start, n.pitch, n.id)), merged_pedals
    )
