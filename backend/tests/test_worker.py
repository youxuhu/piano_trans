import threading
import subprocess
from lingpu.config import Config
from lingpu.events import NoteEvent, Transcription
from lingpu.storage import Store
from lingpu.worker import run_worker


def test_worker_exports_persisted_task(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path, device="cpu")
    store = Store(tmp_path)
    folder = tmp_path / "task"
    folder.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            "-y",
            str(folder / "original.wav"),
        ],
        check=True,
    )
    store.create_task(
        "task",
        dict(
            audio_name="original.wav", title="演奏", bpm=120, time_signature="4/4", quantization=16
        ),
    )
    stop = threading.Event()

    class Adapter:
        def load(self):
            pass

        def transcribe(self, audio, sr, progress):
            progress(50)
            assert store.get_task("task")["stage"] == "transcribing"
            stop.set()
            return Transcription([NoteEvent(60, 0, 0.2, 80)])

    monkeypatch.setattr("lingpu.models.create_transcriber", lambda **kwargs: Adapter())
    run_worker(config, stop)
    assert store.get_task("task")["status"] == "completed"
    assert store.score("task")["note_count"] == 1
    assert (folder / "score.mid").exists() and (folder / "score.musicxml").exists()
    assert not (folder / "decoded.wav").exists()


def test_recovery_removes_incomplete_decodes(tmp_path):
    store = Store(tmp_path)
    folder = tmp_path / "task"
    folder.mkdir()
    (folder / "decoded.wav").write_bytes(b"temp")
    store.create_task("task", {})
    store.update_task("task", status="running", stage="scoring")
    store.recover()
    assert store.get_task("task")["status"] == "failed"
    assert not (folder / "decoded.wav").exists()
