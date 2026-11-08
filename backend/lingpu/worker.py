import logging
import time
from dataclasses import asdict
import json
from .audio import decode, AudioError
from .storage import Store

log = logging.getLogger(__name__)


def run_worker(config, stop):
    store = Store(config.data_dir)
    runtime = {
        "device": config.device,
        "model": config.model,
        "model_loaded": False,
        "ready": False,
        "error": None,
    }
    store.set_runtime(runtime)
    adapter = None
    try:
        from .models import create_transcriber

        adapter = create_transcriber(
            model=config.model, device=config.device, weights_dir=config.weights_dir
        )
        adapter.load()
        runtime.update(model_loaded=True, ready=True)
    except Exception as exc:
        log.exception("Model initialization failed")
        runtime["error"] = friendly_error(exc)
    store.set_runtime(runtime)
    while not stop.is_set():
        task = store.next_task()
        if task is None:
            stop.wait(0.25)
            continue
        ident = task["id"]
        payload = task["payload"]
        folder = config.data_dir / ident
        try:
            if payload.get("kind") == "partial":
                run_partial(config, store, task, adapter, runtime)
                continue
            store.update_task(ident, status="running", stage="decoding")
            audio, sr = decode(
                folder / payload["audio_name"], folder / "decoded.wav", config.max_seconds
            )
            if not runtime["ready"]:
                raise RuntimeError(runtime["error"] or "模型未就绪")
            store.update_task(ident, stage="transcribing")
            started = time.perf_counter()
            transcription = adapter.transcribe(
                audio, sr, progress=lambda p: store.update_task(ident, progress=float(p))
            )
            transcription.save(folder / "events.json")
            store.update_task(ident, stage="scoring", progress=None)
            from .score import export_artifacts, estimate_bpm

            bpm = payload.get("bpm") or estimate_bpm(audio, sr)
            metadata = export_artifacts(
                transcription,
                payload["title"],
                folder,
                bpm,
                payload["time_signature"],
                payload["quantization"],
            )
            # Library duration describes the uploaded recording, including trailing silence.
            metadata["duration"] = len(audio) / sr
            store.add_score(ident, payload["title"], payload["audio_name"], metadata)
            store.update_task(
                ident, status="completed", stage="completed", progress=100, score_id=ident
            )
            log.info("Task %s completed in %.2fs", ident, time.perf_counter() - started)
        except Exception as exc:
            log.exception("Task %s failed", ident)
            store.update_task(
                ident, status="failed", stage="failed", progress=None, error=friendly_error(exc)
            )
            for name in ("score.mid", "score.musicxml"):
                (folder / name).unlink(missing_ok=True)
        finally:
            (folder / "decoded.wav").unlink(missing_ok=True)


def friendly_error(exc):
    message = str(exc)
    from .editing import EditConflict

    if isinstance(exc, EditConflict):
        return message
    if isinstance(exc, AudioError):
        return message
    if "out of memory" in message.lower():
        return "GPU 显存不足，请关闭其他 GPU 程序或上传较短片段"
    if isinstance(exc, FileNotFoundError):
        return "模型权重缺失，请先运行模型下载脚本"
    if any(word in message.lower() for word in ("sha-256", "manifest", "checkpoint")):
        return "模型权重校验失败，请重新运行模型下载脚本后重启后端"
    if "cuda" in message.lower() or "nvidia" in message.lower():
        return "GPU 初始化或推理失败，请检查 CUDA 环境；可显式配置 CPU 模式"
    if "模型" in message:
        return message
    return "转录失败，请查看后端日志并重新提交"


def run_partial(config, store, task, adapter, runtime):
    from .editing import EditConflict, load_events, merge_region, score_lock
    from .events import NoteEvent, PedalEvent, Transcription

    payload, ident = task["payload"], task["id"]
    source_id = payload["score_id"]
    source_folder, folder = config.data_dir / source_id, config.data_dir / ident
    if not source_folder.is_dir():
        raise AudioError("原曲目已删除，请重新选择音频")
    with score_lock(source_folder):
        source = store.score(source_id)
        if not source or not source["audio_name"]:
            raise AudioError("原曲目没有可用录音")
        if source["revision"] != payload["base_revision"]:
            raise EditConflict("曲目已更新，请重新选择片段转录")
        original = load_events(source_folder)
        source_path = source_folder / source["audio_name"]
    store.update_task(ident, status="running", stage="decoding")
    audio, sr = decode(source_path, folder / "decoded.wav", config.max_seconds)
    if not runtime["ready"]:
        raise RuntimeError(runtime["error"] or "模型未就绪")
    start, end = payload["start"], payload["end"]
    if end > len(audio) / sr + 0.025:
        raise AudioError("片段超出了原录音实际长度")
    lo, hi = max(0, round((start - 0.75) * sr)), min(len(audio), round((end + 0.75) * sr))
    store.update_task(ident, stage="transcribing")
    output = adapter.transcribe(
        audio[lo:hi], sr, progress=lambda p: store.update_task(ident, progress=float(p))
    )
    offset = lo / sr
    notes = [
        NoteEvent(n.pitch, n.start + offset, min(end, n.end + offset), n.velocity, id=n.id)
        for n in output.notes
        if start <= n.start + offset < end and n.end + offset > n.start + offset
    ]
    pedals = [
        PedalEvent(max(start, p.start + offset), min(end, p.end + offset))
        for p in output.pedals
        if p.end + offset > start and p.start + offset < end
    ]
    replacement = Transcription(notes, pedals)
    candidate_ids = {n.id for n in notes}
    replacement.notes = [
        n for n in merge_region(original, replacement, start, end).notes if n.id in candidate_ids
    ]
    result = {
        **asdict(replacement),
        "score_id": source_id,
        "base_revision": payload["base_revision"],
        "start": start,
        "end": end,
        "context_start": lo / sr,
        "context_end": hi / sr,
        "old_note_count": sum(start <= n.start < end for n in original.notes),
    }
    temporary = folder / "replacement.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(folder / "replacement.json")
    store.update_task(ident, status="completed", stage="review", progress=100, score_id=source_id)
