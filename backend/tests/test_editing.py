from dataclasses import asdict
import json
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
import numpy as np
import pretty_midi
import pytest

from backend.lingpu.app import create_app
from backend.lingpu.config import Config
from backend.lingpu.events import NoteEvent, PedalEvent, Transcription
from backend.lingpu.editing import merge_region
from backend.lingpu.score import export_artifacts
from backend.lingpu.worker import run_partial


@pytest.fixture
def editable_score(tmp_path):
    config = Config(data_dir=tmp_path, start_worker=False)
    app = create_app(config)
    folder = tmp_path / "piano"
    folder.mkdir()
    events = Transcription(
        [NoteEvent(48, 0, 3), NoteEvent(60, 1, 1.5), NoteEvent(64, 1, 1.5), NoteEvent(72, 3, 4)],
        [PedalEvent(0.5, 3)],
    )
    metadata = export_artifacts(events, "测试", folder, 120)
    metadata["duration"] = 5
    events.save(folder / "events.json")
    (folder / "original.wav").write_bytes(b"original audio")
    app.state.store.add_score("piano", "测试", "original.wav", metadata)
    with TestClient(app) as client:
        yield config, app, client, events, folder


def test_save_updates_midi_xml_hand_and_preserves_original(editable_score):
    _, _, client, original, folder = editable_score
    before = client.get("/api/scores/piano/events").json()
    assert before["revision"] == 0
    notes = before["notes"]
    notes[1].update(pitch=74, start=1.125, end=1.875, hand="right")
    response = client.put("/api/scores/piano/events", json={"expected_revision": 0, "notes": notes})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] == 1 and saved["can_undo"]
    assert (
        next(
            n
            for n in pretty_midi.PrettyMIDI(str(folder / "score.mid")).instruments[0].notes
            if n.pitch == 74
        ).start
        == 1.125
    )
    root = ET.parse(folder / "score.musicxml")
    assert root.find("part/measure/note/pitch") is not None
    right = root.findall("part[@id='P1']//pitch")
    assert any(p.findtext("step") == "D" and p.findtext("octave") == "5" for p in right)
    assert Transcription.read(folder / "original-events.json") == original
    assert (folder / "original.wav").read_bytes() == b"original audio"
    stale = client.put(
        "/api/scores/piano/events", json={"expected_revision": 0, "notes": before["notes"]}
    )
    assert stale.status_code == 409
    assert client.get("/api/scores/piano/events").json() == saved


def test_history_survives_reload_and_discards_redo_on_new_edit(editable_score):
    _, _, client, _, _ = editable_score
    original = client.get("/api/scores/piano/events").json()
    notes = original["notes"]
    notes[0]["pitch"] = 50
    client.put("/api/scores/piano/events", json={"expected_revision": 0, "notes": notes})
    undo = client.post("/api/scores/piano/history/undo", json={"expected_revision": 1}).json()
    assert undo["notes"][0]["pitch"] == 48 and undo["can_redo"] and undo["revision"] == 2
    redo = client.post("/api/scores/piano/history/redo", json={"expected_revision": 2}).json()
    assert redo["notes"][0]["pitch"] == 50 and redo["revision"] == 3
    undo = client.post("/api/scores/piano/history/undo", json={"expected_revision": 3}).json()
    notes = undo["notes"]
    notes.pop()
    saved = client.put(
        "/api/scores/piano/events", json={"expected_revision": 4, "notes": notes}
    ).json()
    assert len(saved["notes"]) == 3 and not saved["can_redo"]
    assert (
        client.post("/api/scores/piano/history/redo", json={"expected_revision": 5}).status_code
        == 422
    )


def test_invalid_notes_do_not_change_artifacts(editable_score):
    _, _, client, _, folder = editable_score
    state = client.get("/api/scores/piano/events").json()
    before = (folder / "score.mid").read_bytes()
    for replacement in [
        dict(state["notes"][0], end=-1),
        dict(state["notes"][0], pitch=300),
        dict(state["notes"][0], start=2, end=1),
    ]:
        assert (
            client.put(
                "/api/scores/piano/events", json={"expected_revision": 0, "notes": [replacement]}
            ).status_code
            == 422
        )
    assert (
        client.put(
            "/api/scores/piano/events",
            json={"expected_revision": 0, "notes": [state["notes"][0], state["notes"][0]]},
        ).status_code
        == 422
    )
    assert (folder / "score.mid").read_bytes() == before


def test_merge_preserves_outside_notes_and_boundary_pedals():
    held = NoteEvent(48, 0, 4)
    after = NoteEvent(72, 3, 4)
    removed = NoteEvent(60, 1, 1.5)
    original = Transcription([held, removed, after], [PedalEvent(0.5, 3)])
    replacement = Transcription(
        [NoteEvent(48, 1.01, 1.7), NoteEvent(48, 1.5, 2.1), NoteEvent(65, 1.2, 2.8)], []
    )
    merged = merge_region(original, replacement, 1, 2)
    assert held in merged.notes and after in merged.notes and removed not in merged.notes
    assert len(merged.notes) == 3
    assert next(n for n in merged.notes if n.pitch == 65).end == 2
    assert merged.pedals == [PedalEvent(0.5, 1), PedalEvent(2, 3)]


def test_partial_worker_only_runs_excerpt_and_requires_review(editable_score, monkeypatch):
    config, app, client, original, folder = editable_score
    response = client.post(
        "/api/scores/piano/retranscriptions", json={"expected_revision": 0, "start": 1, "end": 2}
    )
    assert response.status_code == 202, response.text
    ident = response.json()["task_id"]

    def decode(_source, _destination, _limit):
        return np.zeros(500, dtype=np.float32), 100

    monkeypatch.setattr("backend.lingpu.worker.decode", decode)

    class Model:
        def transcribe(self, audio, sr, progress):
            assert len(audio) == 250 and sr == 100  # .25s–2.75s, including context
            progress(100)
            return Transcription([NoteEvent(65, 0.9, 1.4), NoteEvent(76, 2.5, 2.7)], [])

    before = client.get("/api/scores/piano/events").json()
    run_partial(
        config,
        app.state.store,
        app.state.store.get_task(ident),
        Model(),
        {"ready": True, "error": None},
    )
    preview = client.get(f"/api/scores/piano/retranscriptions/{ident}").json()
    assert preview["old_note_count"] == 2 and len(preview["notes"]) == 1
    assert preview["notes"][0]["start"] == pytest.approx(1.15)
    assert (
        client.get("/api/scores/piano/events").json() == before
    )  # worker never applies automatically
    applied = client.post(
        f"/api/scores/piano/retranscriptions/{ident}/apply", json={"expected_revision": 0}
    )
    assert applied.status_code == 200, applied.text
    assert (
        client.post(
            f"/api/scores/piano/retranscriptions/{ident}/apply", json={"expected_revision": 0}
        ).status_code
        == 409
    )
    notes = applied.json()["notes"]
    assert {n["id"] for n in notes if n["start"] < 1 or n["start"] >= 2} == {
        original.notes[0].id,
        original.notes[-1].id,
    }
    undo = client.post("/api/scores/piano/history/undo", json={"expected_revision": 1}).json()
    assert undo["notes"] == before["notes"]
    assert (
        client.post(
            f"/api/scores/piano/retranscriptions/{ident}/apply", json={"expected_revision": 2}
        ).status_code
        == 409
    )


def test_pending_partial_cannot_overwrite_later_correction(editable_score):
    config, app, client, _, _ = editable_score
    state = client.get("/api/scores/piano/events").json()
    ident = client.post(
        "/api/scores/piano/retranscriptions", json={"expected_revision": 0, "start": 1, "end": 2}
    ).json()["task_id"]
    preview = {
        **asdict(Transcription()),
        "base_revision": 0,
        "start": 1,
        "end": 2,
        "old_note_count": 2,
    }
    (config.data_dir / ident / "replacement.json").write_text(json.dumps(preview))
    app.state.store.update_task(ident, status="completed", stage="review")
    client.put(
        "/api/scores/piano/events", json={"expected_revision": 0, "notes": state["notes"][:-1]}
    )
    assert (
        client.post(
            f"/api/scores/piano/retranscriptions/{ident}/apply", json={"expected_revision": 0}
        ).status_code
        == 409
    )
    assert len(client.get("/api/scores/piano/events").json()["notes"]) == 3
    assert (
        client.post(
            "/api/scores/piano/retranscriptions",
            json={"expected_revision": 1, "start": 3, "end": 8},
        ).status_code
        == 422
    )


def test_failed_rebuild_rolls_back_file_and_database(editable_score, monkeypatch):
    _, _, client, _, folder = editable_score
    state = client.get("/api/scores/piano/events").json()

    def fail(*_args, **_kwargs):
        raise ValueError("模拟建谱失败")

    monkeypatch.setattr("backend.lingpu.editing.export_artifacts", fail)
    before = (folder / "score.musicxml").read_bytes()
    assert (
        client.put(
            "/api/scores/piano/events", json={"expected_revision": 0, "notes": state["notes"]}
        ).status_code
        == 422
    )
    assert (folder / "score.musicxml").read_bytes() == before
    assert client.get("/api/scores/piano/events").json()["revision"] == 0


def test_history_is_available_after_server_restart(editable_score):
    config, _, client, _, _ = editable_score
    original = client.get("/api/scores/piano/events").json()
    notes = original["notes"]
    notes[0]["hand"] = "right"
    assert (
        client.put(
            "/api/scores/piano/events", json={"expected_revision": 0, "notes": notes}
        ).status_code
        == 200
    )
    with TestClient(create_app(Config(data_dir=config.data_dir, start_worker=False))) as restarted:
        state = restarted.get("/api/scores/piano/events").json()
        assert state["revision"] == 1 and state["can_undo"]
        undo = restarted.post(
            "/api/scores/piano/history/undo", json={"expected_revision": 1}
        ).json()
        assert undo["notes"][0]["hand"] is None
