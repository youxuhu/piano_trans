import io
import zipfile
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from backend.lingpu.app import create_app
from backend.lingpu.config import Config
from backend.lingpu.events import NoteEvent, PedalEvent, Transcription
from backend.lingpu.score import export_artifacts


def fixture(folder):
    folder.mkdir(exist_ok=True)
    events = Transcription(
        [
            NoteEvent(48, 0, 2),
            NoteEvent(60, 0, 0.5),
            NoteEvent(64, 0, 0.5),
            NoteEvent(67, 0.5, 1),
            NoteEvent(67, 1, 1.5),
            NoteEvent(61, 1.5, 3),
        ],
        [PedalEvent(0, 2)],
    )
    metadata = export_artifacts(events, "双手测试", folder, 120)
    events.save(folder / "events.json")
    return events, metadata


def test_import_persists_downloads_and_renames(tmp_path):
    source = tmp_path / "fixture"
    fixture(source)
    config = Config(data_dir=tmp_path / "library", start_worker=False)
    with TestClient(create_app(config)) as client:
        response = client.post(
            "/api/scores/import",
            files={"file": ("piano.musicxml", (source / "score.musicxml").read_bytes())},
        )
        assert response.status_code == 201, response.text
        item = response.json()
        assert not item["has_audio"] and not item["can_regenerate"]
        assert client.get("/api/scores").json()[0]["id"] == item["id"]
        assert client.get(f"/api/scores/{item['id']}/artifacts/midi").status_code == 200
        assert client.get(f"/api/scores/{item['id']}/artifacts/audio").status_code == 404
        client.patch(f"/api/scores/{item['id']}", json={"title": "新标题"})
        xml = ET.fromstring(client.get(f"/api/scores/{item['id']}/artifacts/musicxml").content)
        assert xml.findtext("work/work-title") == "新标题"
    with TestClient(create_app(config)) as client:
        assert client.get(f"/api/scores/{item['id']}").json()["title"] == "新标题"


def test_compressed_import_and_invalid_files(tmp_path):
    source = tmp_path / "fixture"
    fixture(source)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="music.xml"/></rootfiles></container>',
        )
        archive.writestr("music.xml", (source / "score.musicxml").read_bytes())
    with TestClient(
        create_app(Config(data_dir=tmp_path / "library", start_worker=False))
    ) as client:
        assert (
            client.post(
                "/api/scores/import", files={"file": ("piano.mxl", data.getvalue())}
            ).status_code
            == 201
        )
        for name, content in [("broken.xml", b"<bad/>"), ("empty.xml", b""), ("wrong.txt", b"abc")]:
            assert (
                client.post("/api/scores/import", files={"file": (name, content)}).status_code
                >= 400
            )
        assert len(client.get("/api/scores").json()) == 1


def test_regenerate_uses_saved_events_and_keeps_original(tmp_path):
    app = create_app(Config(data_dir=tmp_path, start_worker=False))
    events, metadata = fixture(tmp_path / "piano")
    (tmp_path / "piano" / "original.wav").write_bytes(b"recording")
    original_xml = (tmp_path / "piano" / "score.musicxml").read_bytes()
    app.state.store.add_score("piano", "双手测试", "original.wav", metadata)
    with TestClient(app) as client:
        result = client.post(
            "/api/scores/piano/regenerate",
            json={
                "bpm": 90,
                "time_signature": "3/4",
                "quantization": 8,
                "hand_split": 60,
                "key_fifths": -3,
            },
        )
        assert result.status_code == 200, result.text
        xml = ET.fromstring((tmp_path / "piano" / "score.musicxml").read_bytes())
        assert xml.findtext("part/measure/attributes/key/fifths") == "-3"
        assert xml.findtext("part/measure/attributes/time/beats") == "3"
        assert result.json()["note_count"] == len(events.notes)
        assert (tmp_path / "piano" / "original-score.musicxml").read_bytes() == original_xml
        assert (tmp_path / "piano" / "original.wav").read_bytes() == b"recording"
        assert Transcription.read(tmp_path / "piano" / "events.json") == events
        before = (tmp_path / "piano" / "score.musicxml").read_bytes()
        assert client.post("/api/scores/piano/regenerate", json={"bpm": 0}).status_code == 422
        assert (tmp_path / "piano" / "score.musicxml").read_bytes() == before


def test_old_library_can_rebuild_from_original_midi(tmp_path):
    app = create_app(Config(data_dir=tmp_path, start_worker=False))
    _, metadata = fixture(tmp_path / "old")
    (tmp_path / "old" / "events.json").unlink()
    app.state.store.add_score("old", "旧曲目", "original.wav", metadata)
    with TestClient(app) as client:
        result = client.post("/api/scores/old/regenerate", json={"bpm": 120})
        assert result.status_code == 200, result.text
        assert len(Transcription.read(tmp_path / "old" / "events.json").notes) == 6
