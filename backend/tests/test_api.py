from fastapi.testclient import TestClient
from lingpu.app import create_app
from lingpu.config import Config
from lingpu.storage import Store
from types import SimpleNamespace


def test_upload_validation_and_persistence(tmp_path):
    config = Config(data_dir=tmp_path, start_worker=False, max_bytes=8)
    app = create_app(config)
    with TestClient(app) as client:
        assert (
            client.post("/api/transcriptions", files={"audio": ("test.wav", b"")}).status_code
            == 400
        )
        assert (
            client.post("/api/transcriptions", files={"audio": ("test.exe", b"abc")}).status_code
            == 400
        )
        assert (
            client.post(
                "/api/transcriptions", files={"audio": ("test.wav", b"123456789")}
            ).status_code
            == 413
        )
        assert (
            client.post(
                "/api/transcriptions", files={"audio": ("test.wav", b"abc")}, data={"bpm": "nan"}
            ).status_code
            == 422
        )
        result = client.post("/api/transcriptions", files={"audio": ("test.wav", b"abc")})
        assert result.status_code == 202
        ident = result.json()["task_id"]
        assert client.get("/api/tasks/" + ident).json()["status"] == "queued"
        assert client.get("/api/health").json()["ready"] is False
    with TestClient(create_app(config)) as client:
        task = client.get("/api/tasks/" + ident).json()
        assert task["status"] == "failed"
        assert "重启" in task["error"]


def test_library_and_artifacts(tmp_path):
    config = Config(data_dir=tmp_path, start_worker=False)
    store = Store(tmp_path)
    ident = "123abc"
    folder = tmp_path / ident
    folder.mkdir()
    (folder / "original.wav").write_bytes(b"audio")
    (folder / "score.mid").write_bytes(b"midi")
    (folder / "score.musicxml").write_text("<score-partwise/>")
    store.add_score(
        ident, "测试", "original.wav", dict(duration=2, bpm=120, time_signature="4/4", note_count=3)
    )
    with TestClient(create_app(config)) as client:
        assert len(client.get("/api/scores").json()) == 1
        assert (
            client.patch("/api/scores/" + ident, json={"title": "新曲名"}).json()["title"]
            == "新曲名"
        )
        assert client.patch("/api/scores/" + ident, json={"title": "   "}).status_code == 422
        assert client.get("/api/scores/" + ident + "/artifacts/midi").content == b"midi"
        assert client.get("/api/scores/" + ident + "/artifacts/unknown").status_code == 404
        assert client.delete("/api/scores/" + ident).status_code == 204
        assert not folder.exists()
        assert client.get("/api/scores/" + ident).status_code == 404


def test_dead_worker_does_not_leave_task_running(tmp_path):
    config = Config(data_dir=tmp_path, start_worker=False)
    app = create_app(config)
    with TestClient(app) as client:
        app.state.store.create_task("interrupted", {"title": "test"})
        app.state.store.update_task("interrupted", status="running", stage="transcribing")
        app.state.worker = SimpleNamespace(is_alive=lambda: False)
        config.start_worker = True
        task = client.get("/api/tasks/interrupted").json()
        assert task["status"] == "failed"
        assert "进程已退出" in task["error"]
        assert client.get("/api/health").json()["ready"] is False
