from contextlib import contextmanager
import json
from typing import Literal
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from .editing import (
    EditConflict,
    commit_change,
    events_from_data,
    load_events,
    merge_region,
    move_history,
    score_lock,
    score_options,
    session_data,
)
from .events import NoteEvent, Transcription


class Revision(BaseModel):
    expected_revision: int = Field(ge=0)


class EditableNote(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    pitch: int = Field(ge=21, le=108)
    start: float = Field(ge=0, le=3600, allow_inf_nan=False)
    end: float = Field(gt=0, le=3600, allow_inf_nan=False)
    velocity: int = Field(default=90, ge=1, le=127)
    hand: Literal["right", "left"] | None = None

    @model_validator(mode="after")
    def valid_duration(self):
        if self.end <= self.start:
            raise ValueError("音符结束时间必须晚于开始时间")
        return self


class EditNotes(Revision):
    notes: list[EditableNote] = Field(max_length=100000)

    @model_validator(mode="after")
    def unique_notes(self):
        if len({n.id for n in self.notes}) != len(self.notes):
            raise ValueError("音符标识重复，请重新载入")
        return self


class Region(Revision):
    start: float = Field(ge=0, lt=600, allow_inf_nan=False)
    end: float = Field(gt=0, le=600, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end - self.start < 0.1:
            raise ValueError("片段至少需要 0.1 秒")
        return self


def create_edit_router(config, store):
    router = APIRouter(prefix="/api/scores")

    @contextmanager
    def editable(ident):
        item = store.score(ident)
        if not item:
            raise HTTPException(404, "曲目不存在")
        if not item["has_audio"]:
            raise HTTPException(400, "音符纠错和局部重转录适用于音频转录曲目")
        with score_lock(config.data_dir / ident):
            item = store.score(ident)
            if not item:
                raise HTTPException(404, "曲目不存在")
            try:
                yield item
            except EditConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

    @router.get("/{ident}/events")
    def events(ident: str):
        with editable(ident):
            return session_data(store, ident)

    @router.put("/{ident}/events")
    def save_events(ident: str, body: EditNotes):
        with editable(ident) as item:
            original = load_events(config.data_dir / ident)
            events = Transcription(
                [NoteEvent(**n.model_dump()) for n in body.notes], original.pedals
            )
            return commit_change(
                store,
                ident,
                events,
                score_options(item, config.data_dir / ident),
                body.expected_revision,
                "音符纠错",
            )

    @router.post("/{ident}/history/{action}")
    def history(ident: str, action: Literal["undo", "redo"], body: Revision):
        with editable(ident):
            return move_history(store, ident, body.expected_revision, -1 if action == "undo" else 1)

    @router.post("/{ident}/retranscriptions", status_code=202)
    def retranscribe(ident: str, body: Region):
        with editable(ident) as item:
            if item["revision"] != body.expected_revision:
                raise EditConflict("曲目已更新，请重新载入后选择片段")
            if body.end > (item["duration"] or 0) + 0.025:
                raise HTTPException(422, "所选片段超出了原录音长度")
            session_data(store, ident)
            task_id = uuid.uuid4().hex
            folder = config.data_dir / task_id
            folder.mkdir()
            try:
                store.create_task(
                    task_id,
                    {
                        "kind": "partial",
                        "score_id": ident,
                        "base_revision": body.expected_revision,
                        "start": body.start,
                        "end": body.end,
                    },
                )
            except Exception:
                folder.rmdir()
                raise
            return {"task_id": task_id}

    def preview_task(ident, task_id):
        task = store.get_task(task_id)
        if (
            not task
            or task["payload"].get("kind") != "partial"
            or task["payload"].get("score_id") != ident
        ):
            raise HTTPException(404, "局部转录任务不存在")
        if task["status"] != "completed":
            raise HTTPException(409, "局部转录尚未完成")
        path = config.data_dir / task_id / "replacement.json"
        if not path.exists():
            raise HTTPException(404, "局部结果已不存在，请重新转录")
        return json.loads(path.read_text(encoding="utf-8"))

    @router.get("/{ident}/retranscriptions/{task_id}")
    def preview(ident: str, task_id: str):
        with editable(ident):
            return preview_task(ident, task_id)

    @router.post("/{ident}/retranscriptions/{task_id}/apply")
    def apply(ident: str, task_id: str, body: Revision):
        with editable(ident) as item:
            result = preview_task(ident, task_id)
            if body.expected_revision != result["base_revision"]:
                raise EditConflict("此结果基于较早版本，请按当前版本重新转录")
            old = load_events(config.data_dir / ident)
            merged = merge_region(old, events_from_data(result), result["start"], result["end"])
            return commit_change(
                store,
                ident,
                merged,
                score_options(item, config.data_dir / ident),
                body.expected_revision,
                "局部重转录",
            )

    return router
