from contextlib import asynccontextmanager
from pathlib import Path
import multiprocessing as mp
import re
import shutil
import uuid
import threading

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from urllib.parse import quote
from pydantic import BaseModel, Field

from .config import Config
from .storage import Store
from .worker import run_worker
from .editing import score_lock, session_data, load_events, commit_change
from .editing_routes import create_edit_router

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm"}


class Rename(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class Rescore(BaseModel):
    bpm: float = Field(ge=30, le=300)
    time_signature: str = Field(default="4/4", pattern=r"^(?:[1-9]|1[0-2])/(?:2|4|8|16)$")
    quantization: int = Field(default=16)
    hand_split: int = Field(default=64, ge=36, le=84)
    key_fifths: int | None = Field(default=None, ge=-7, le=7)


def create_app(config=None):
    config = config or Config.from_env()
    store = Store(config.data_dir)
    library_lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        context = mp.get_context("spawn")
        stop = context.Event()
        process = None
        store.set_runtime(
            {
                "device": config.device,
                "model": config.model,
                "model_loaded": False,
                "ready": False,
                "error": None,
            }
        )
        if config.start_worker:
            process = context.Process(
                target=run_worker, args=(config, stop), daemon=True, name="lingpu-inference"
            )
            process.start()
        app.state.worker = process
        try:
            yield
        finally:
            stop.set()
            if process:
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)

    app = FastAPI(title="灵谱", version="1.0.0", lifespan=lifespan)
    app.state.store = store
    app.include_router(create_edit_router(config, store))

    def score_or_404(ident):
        result = store.score(ident)
        if result is None:
            raise HTTPException(404, "乐谱不存在")
        return result

    @app.get("/api/health")
    def health():
        runtime = store.runtime()
        process = getattr(app.state, "worker", None)
        alive = bool(process and process.is_alive())
        return {
            **runtime,
            "status": "ok",
            "worker_alive": alive,
            "ready": alive and runtime.get("ready", False),
        }

    @app.post("/api/transcriptions", status_code=202)
    async def transcribe(
        audio: UploadFile = File(...),
        bpm: str = Form(""),
        time_signature: str = Form("4/4"),
        quantization: int = Form(16),
    ):
        filename = Path((audio.filename or "audio").replace("\\", "/")).name
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "不支持的音频格式")
        if not re.fullmatch(r"(?:[1-9]|1[0-2])/(?:2|4|8|16)", time_signature):
            raise HTTPException(422, "拍号无效")
        if quantization not in (4, 8, 16, 32):
            raise HTTPException(422, "量化精度应为 4、8、16 或 32")
        tempo = None
        if bpm.strip():
            try:
                tempo = float(bpm)
            except ValueError:
                raise HTTPException(422, "BPM 必须为数字")
            if not 30 <= tempo <= 300:
                raise HTTPException(422, "BPM 应在 30–300 之间")
        ident = uuid.uuid4().hex
        folder = config.data_dir / ident
        folder.mkdir()
        try:
            total = 0
            with (folder / ("original" + ext)).open("wb") as target:
                while chunk := await audio.read(1024 * 1024):
                    total += len(chunk)
                    if total > config.max_bytes:
                        raise HTTPException(413, "音频超过 100 MB 限制")
                    target.write(chunk)
            if total == 0:
                raise HTTPException(400, "上传文件为空")
            store.create_task(
                ident,
                {
                    "title": Path(filename).stem[:160] or "未命名演奏",
                    "audio_name": "original" + ext,
                    "bpm": tempo,
                    "time_signature": time_signature,
                    "quantization": quantization,
                },
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:
            await audio.close()
        return {"task_id": ident}

    @app.get("/api/tasks/{ident}")
    def task(ident: str):
        process = getattr(app.state, "worker", None)
        if config.start_worker and process and not process.is_alive():
            store.fail_pending("转录进程已退出，请重启服务后重试")
        item = store.get_task(ident)
        if item is None:
            raise HTTPException(404, "任务不存在")
        payload = item.pop("payload", {})
        item["kind"] = payload.get("kind", "full")
        return item

    @app.get("/api/scores")
    def scores():
        return store.scores()

    @app.post("/api/scores/import", status_code=201)
    def import_score(file: UploadFile = File(...)):
        from .library import import_musicxml

        name = Path((file.filename or "").replace("\\", "/")).name
        if Path(name).suffix.lower() not in (".xml", ".musicxml", ".mxl"):
            raise HTTPException(400, "请选择 MusicXML 或 MXL 文件")
        folder = config.data_dir / uuid.uuid4().hex
        folder.mkdir()
        try:
            content = file.file.read(10 * 1024 * 1024 + 1)
            if not content or len(content) > 10 * 1024 * 1024:
                raise HTTPException(413 if content else 400, "乐谱须为非空文件，且不超过 10 MB")
            title, metadata = import_musicxml(content, name, folder)
            store.add_score(folder.name, title, "", metadata)
            return store.score(folder.name)
        except HTTPException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(422, "乐谱解析失败，请检查 MusicXML 内容") from exc
        finally:
            file.file.close()

    @app.get("/api/scores/{ident}")
    def detail(ident: str):
        return score_or_404(ident)

    @app.patch("/api/scores/{ident}")
    def rename(ident: str, body: Rename):
        score_or_404(ident)
        title = body.title.strip()
        if not title:
            raise HTTPException(422, "曲名不能为空")
        from .library import rename_musicxml

        with library_lock, score_lock(config.data_dir / ident):
            rename_musicxml(config.data_dir / ident, title)
            store.rename(ident, title)
        return store.score(ident)

    @app.post("/api/scores/{ident}/regenerate")
    def regenerate(ident: str, body: Rescore):
        score_or_404(ident)
        with library_lock, score_lock(config.data_dir / ident):
            item = score_or_404(ident)
            if not item["can_regenerate"]:
                raise HTTPException(
                    400, "导入的成品乐谱请在制谱软件中修改；重新建谱适用于音频转录曲目"
                )
            if body.quantization not in (4, 8, 16, 32):
                raise HTTPException(422, "量化精度应为 4、8、16 或 32")
            session_data(store, ident)
            commit_change(
                store,
                ident,
                load_events(config.data_dir / ident),
                body.model_dump(),
                item["revision"],
                "重新建谱",
            )
            return store.score(ident)

    @app.delete("/api/scores/{ident}", status_code=204)
    def delete(ident: str):
        score_or_404(ident)
        with library_lock, score_lock(config.data_dir / ident):
            score_or_404(ident)
            store.delete(ident)
            shutil.rmtree(config.data_dir / ident, ignore_errors=True)

    @app.get("/api/scores/{ident}/artifacts/{kind}")
    def artifact(ident: str, kind: str):
        item = score_or_404(ident)
        names = {
            "audio": (item["audio_name"], None),
            "midi": ("score.mid", "audio/midi"),
            "musicxml": ("score.musicxml", "application/vnd.recordare.musicxml+xml"),
        }
        if kind not in names:
            raise HTTPException(404, "文件类型不存在")
        name, media_type = names[kind]
        if not name:
            raise HTTPException(404, "此乐谱没有原音")
        path = config.data_dir / ident / name
        if not path.is_file():
            raise HTTPException(404, "文件不存在")
        if kind != "audio":
            with score_lock(config.data_dir / ident):
                return Response(
                    path.read_bytes(),
                    media_type=media_type,
                    headers={
                        "Content-Disposition": "attachment; filename*=utf-8''"
                        + quote(item["title"] + path.suffix)
                    },
                )
        return FileResponse(
            path,
            media_type=media_type,
            filename=item["title"] + path.suffix,
            content_disposition_type="inline" if kind == "audio" else "attachment",
        )

    return app
