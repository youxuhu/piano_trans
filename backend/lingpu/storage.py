import json
import re
import shutil
from contextlib import contextmanager
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "lingpu.sqlite3"
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, stage TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                progress REAL, error TEXT, score_id TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scores (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at REAL NOT NULL,
                duration REAL, bpm REAL, time_signature TEXT, note_count INTEGER,
                audio_name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runtime (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(scores)")}
            if "settings" not in columns:
                db.execute("ALTER TABLE scores ADD COLUMN settings TEXT NOT NULL DEFAULT '{}'")
            if "revision" not in columns:
                db.execute("ALTER TABLE scores ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            if "history_position" not in columns:
                db.execute(
                    "ALTER TABLE scores ADD COLUMN history_position INTEGER NOT NULL DEFAULT 0"
                )
            db.execute("""CREATE TABLE IF NOT EXISTS score_history(
                score_id TEXT NOT NULL, position INTEGER NOT NULL,
                events TEXT NOT NULL, options TEXT NOT NULL, reason TEXT NOT NULL,
                PRIMARY KEY(score_id,position))""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_task(self, ident, payload):
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)",
                (ident, "queued", "queued", now, now, None, None, None, json.dumps(payload)),
            )

    def update_task(self, ident, **changes):
        allowed = {"status", "stage", "progress", "error", "score_id"}
        assert set(changes) <= allowed
        changes["updated_at"] = time.time()
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET " + ",".join(f"{k}=?" for k in changes) + " WHERE id=?",
                (*changes.values(), ident),
            )

    def get_task(self, ident):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (ident,)).fetchone()
        if row is None:
            return None
        task = dict(row)
        task["payload"] = json.loads(task["payload"])
        end = task["updated_at"] if task["status"] in ("completed", "failed") else time.time()
        task["elapsed_seconds"] = round(end - task["created_at"], 2)
        return task

    def next_task(self):
        with self.connect() as db:
            row = db.execute(
                "SELECT id FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
        return self.get_task(row["id"]) if row else None

    def fail_pending(self, message):
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET status='failed',stage='failed',error=?,updated_at=? WHERE status IN ('running','queued')",
                (message, time.time()),
            )

    def recover(self):
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET status='failed', stage='failed', error='服务重启，任务已中断，请重新提交', updated_at=? WHERE status IN ('running','queued')",
                (time.time(),),
            )
        for path in self.root.glob("*/decoded.wav"):
            path.unlink(missing_ok=True)
        for path in self.root.glob("*.upload"):
            path.unlink(missing_ok=True)
        # Uploads interrupted before a task row was committed are not reusable.
        for folder in self.root.iterdir():
            if not folder.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", folder.name):
                continue
            if self.get_task(folder.name) is None and self.score(folder.name) is None:
                shutil.rmtree(folder)
            elif self.score(folder.name) is None:
                for name in ("score.mid", "score.musicxml"):
                    (folder / name).unlink(missing_ok=True)

    def set_runtime(self, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO runtime VALUES(1,?)", (json.dumps(value),))

    def runtime(self):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runtime WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}

    def add_score(self, ident, title, audio_name, metadata):
        with self.connect() as db:
            db.execute(
                "INSERT INTO scores(id,title,created_at,duration,bpm,time_signature,note_count,audio_name,settings) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    title,
                    time.time(),
                    metadata["duration"],
                    metadata["bpm"],
                    metadata["time_signature"],
                    metadata["note_count"],
                    audio_name,
                    json.dumps(metadata.get("settings", {})),
                ),
            )

    def scores(self):
        with self.connect() as db:
            return [
                self._score_data(row)
                for row in db.execute("SELECT * FROM scores ORDER BY created_at DESC")
            ]

    def score(self, ident):
        with self.connect() as db:
            row = db.execute("SELECT * FROM scores WHERE id=?", (ident,)).fetchone()
        return self._score_data(row) if row else None

    @staticmethod
    def _score_data(row):
        data = dict(row)
        data["settings"] = json.loads(data["settings"])
        data["has_audio"] = bool(data["audio_name"])
        data["can_regenerate"] = bool(data["audio_name"])
        return data

    def update_score(self, ident, metadata):
        with self.connect() as db:
            db.execute(
                "UPDATE scores SET bpm=?,time_signature=?,note_count=?,settings=?,revision=revision+1 WHERE id=?",
                (
                    metadata["bpm"],
                    metadata["time_signature"],
                    metadata["note_count"],
                    json.dumps(metadata.get("settings", {})),
                    ident,
                ),
            )

    def rename(self, ident, title):
        with self.connect() as db:
            db.execute("UPDATE scores SET title=? WHERE id=?", (title, ident))

    def delete(self, ident):
        with self.connect() as db:
            db.execute("DELETE FROM scores WHERE id=?", (ident,))
            db.execute("DELETE FROM score_history WHERE score_id=?", (ident,))
