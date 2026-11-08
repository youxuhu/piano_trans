"""Adapters for locally installed piano transcription models.

Importing this module is deliberately cheap: neither PyTorch nor model packages
are imported until ``load`` is called.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from .events import NoteEvent, PedalEvent, Transcription


Progress = Callable[[float], None]


class TranscriberAdapter(Protocol):
    def load(self) -> None: ...
    def transcribe(
        self, audio: np.ndarray, sample_rate: int, progress: Progress | None = None
    ) -> Transcription: ...


def create_transcriber(
    model: str = "bytedance",
    device: str = "cuda",
    weights_dir: Path = Path("backend/weights"),
    **options: object,
) -> TranscriberAdapter:
    """Create a named adapter without importing heavyweight model runtimes."""
    name = model.strip().lower()
    if name == "bytedance":
        return ByteDanceAdapter(Path(weights_dir), device=device)
    if name == "transkun":
        return TranskunAdapter(Path(weights_dir), device=device, **options)
    raise ValueError(f"Unsupported transcription model: {model!r}")


class ByteDanceAdapter:
    """Adapter around qiuqiangkong/piano_transcription_inference."""

    def __init__(self, weights_dir: Path, device: str = "cuda") -> None:
        self.weights_dir = weights_dir
        self.checkpoint = weights_dir / "bytedance.pth"
        self.device_name = device
        self._runtime = None

    def load(self) -> None:
        if not self.checkpoint.is_file():
            raise FileNotFoundError(
                f"ByteDance checkpoint missing: {self.checkpoint}. "
                "Run backend/scripts/download_models.py explicitly first."
            )
        if self.checkpoint.stat().st_size < 160_000_000:
            raise ValueError(f"ByteDance checkpoint is incomplete or too small: {self.checkpoint}")
        manifest_path = self.weights_dir / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Checkpoint manifest missing: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_hash = manifest["sha256"]
            expected_file = manifest["file"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Invalid checkpoint manifest: {manifest_path}") from exc
        if expected_file != self.checkpoint.name or not isinstance(expected_hash, str):
            raise ValueError("Checkpoint manifest does not describe backend/weights/bytedance.pth")
        digest = hashlib.sha256()
        with self.checkpoint.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest().lower() != expected_hash.lower():
            raise ValueError("ByteDance checkpoint SHA-256 does not match manifest.json")
        # Old librosa versions used aliases removed by NumPy 2.  Set aliases
        # before importing the third-party package for compatibility.
        for alias, value in (("complex", np.complex128), ("float", float), ("int", int)):
            if not hasattr(np, alias):
                setattr(np, alias, value)
        try:
            import torch
            from piano_transcription_inference import PianoTranscription, sample_rate
            from piano_transcription_inference import config
        except ImportError as exc:
            raise RuntimeError(
                "Install piano_transcription_inference and its PyTorch dependencies"
            ) from exc
        if self.device_name.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but PyTorch reports no available CUDA device")
        self._torch = torch
        self._sample_rate = int(sample_rate)
        self._config = config
        device = torch.device(self.device_name)
        # This library's constructor may download a default checkpoint. Pass an
        # explicit local path and guard it above to keep inference offline.
        self._runtime = PianoTranscription(
            model_type="Note_pedal", checkpoint_path=str(self.checkpoint), device=device
        )
        from piano_transcription_inference.utilities import RegressionPostProcessor

        self._processor_class = RegressionPostProcessor

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, progress: Progress | None = None
    ) -> Transcription:
        if self._runtime is None:
            raise RuntimeError("Call load() before transcribe()")
        import librosa

        y = np.asarray(audio, dtype=np.float32)
        if y.ndim == 2:
            y = y.mean(axis=0) if y.shape[0] <= 8 else y.mean(axis=1)
        if y.ndim != 1 or not len(y):
            raise ValueError("audio must be a non-empty mono or multichannel array")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if int(sample_rate) != self._sample_rate:
            y = librosa.resample(y, orig_sr=int(sample_rate), target_sr=self._sample_rate)
        y = np.ascontiguousarray(y, dtype=np.float32)
        rt = self._runtime
        seg_samples = int(rt.segment_samples)
        audio_len = len(y)
        padded_len = int(np.ceil(audio_len / seg_samples)) * seg_samples
        padded = np.pad(y, (0, padded_len - audio_len))
        segments = rt.enframe(padded[None, :], seg_samples)
        outputs: dict[str, list[np.ndarray]] = {}
        # The upstream forward helper accepts batches; run one segment at a
        # time so callers receive meaningful, monotonic progress.
        from piano_transcription_inference.pytorch_utils import forward

        for i, segment in enumerate(segments):
            part = forward(rt.model, segment[None, :], batch_size=1)
            for key, value in part.items():
                outputs.setdefault(key, []).append(np.asarray(value))
            if progress:
                progress(100.0 * (i + 1) / len(segments))
        merged = {key: np.concatenate(parts, axis=0) for key, parts in outputs.items()}
        real_duration = audio_len / self._sample_rate
        valid_frames = int(np.ceil(real_duration * float(rt.frames_per_second)))
        for key in merged:
            merged[key] = rt.deframe(merged[key])[:valid_frames]
        pp = self._processor_class(
            rt.frames_per_second,
            classes_num=rt.classes_num,
            onset_threshold=rt.onset_threshold,
            offset_threshold=rt.offset_threshod,
            frame_threshold=rt.frame_threshold,
            pedal_offset_threshold=rt.pedal_offset_threshold,
        )
        note_dicts, pedal_dicts = pp.output_dict_to_midi_events(merged)
        notes = []
        for event in note_dicts:
            start = float(event["onset_time"])
            end = min(float(event["offset_time"]), real_duration)
            if start < real_duration and end > start:
                notes.append(
                    NoteEvent(
                        pitch=int(event["midi_note"]),
                        start=start,
                        end=end,
                        velocity=int(event["velocity"]),
                    )
                )
        pedals = []
        for event in pedal_dicts or []:
            start = float(event["onset_time"])
            end = min(float(event["offset_time"]), real_duration)
            if start < real_duration and end > start:
                pedals.append(PedalEvent(start=start, end=end))
        return Transcription(notes=notes, pedals=pedals)


class TranskunAdapter:
    """CLI bridge for Transkun installed in its own environment.

    Set ``TRANSKUN_EXECUTABLE`` to a wrapper that activates the separate
    conda environment, or pass ``executable=...`` to the factory. The wrapper
    must accept ``audio.mid --device DEVICE`` arguments (the official CLI).
    """

    def __init__(
        self, weights_dir: Path, device: str = "cuda", executable: str | None = None, **_: object
    ) -> None:
        self.device_name = device
        self.executable = (
            executable or os.environ.get("TRANSKUN_EXECUTABLE") or shutil.which("transkun")
        )
        self._loaded = False

    def load(self) -> None:
        if not self.executable:
            raise RuntimeError(
                "Transkun CLI not found; set TRANSKUN_EXECUTABLE to the isolated-environment wrapper"
            )
        self._loaded = True

    def transcribe(
        self, audio: np.ndarray, sample_rate: int, progress: Progress | None = None
    ) -> Transcription:
        if not self._loaded:
            raise RuntimeError("Call load() before transcribe()")
        import soundfile as sf

        y = np.asarray(audio, dtype=np.float32)
        if y.ndim == 2:
            y = y.mean(axis=0) if y.shape[0] <= 8 else y.mean(axis=1)
        with tempfile.TemporaryDirectory(prefix="lingpu-transkun-") as td:
            source, result = Path(td) / "input.wav", Path(td) / "output.mid"
            sf.write(source, y, int(sample_rate))
            proc = subprocess.run(
                [str(self.executable), str(source), str(result), "--device", self.device_name],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode:
                raise RuntimeError(f"Transkun failed ({proc.returncode}): {proc.stderr[-2000:]}")
            if not result.is_file():
                raise RuntimeError("Transkun completed without creating its MIDI output")
            transcription = _read_midi_events(result)
        if progress:
            progress(100.0)
        return transcription


def _read_midi_events(path: Path) -> Transcription:
    """Read note and CC64 intervals from MIDI using mido's tempo-aware merge."""
    try:
        import mido
    except ImportError as exc:
        raise RuntimeError("Transkun MIDI bridge requires mido") from exc
    midi = mido.MidiFile(path)
    active: dict[tuple[int, int], list[tuple[float, int]]] = {}
    pedal_start: dict[int, float] = {}
    notes: list[NoteEvent] = []
    pedals: list[PedalEvent] = []
    seconds = 0.0
    tempo = 500000
    for msg in mido.merge_tracks(midi.tracks):
        seconds += mido.tick2second(msg.time, midi.ticks_per_beat, tempo)
        if msg.type == "set_tempo":
            tempo = msg.tempo
        elif msg.type == "note_on" and msg.velocity > 0:
            active.setdefault((msg.channel, msg.note), []).append((seconds, msg.velocity))
        elif msg.type in ("note_off", "note_on"):
            key = (msg.channel, msg.note)
            if active.get(key):
                start, velocity = active[key].pop(0)
                if seconds > start:
                    notes.append(
                        NoteEvent(pitch=msg.note, start=start, end=seconds, velocity=velocity)
                    )
        elif msg.type == "control_change" and msg.control == 64:
            if msg.value >= 64 and msg.channel not in pedal_start:
                pedal_start[msg.channel] = seconds
            elif msg.value < 64 and msg.channel in pedal_start:
                pedals.append(PedalEvent(start=pedal_start.pop(msg.channel), end=seconds))
    for channel, start in pedal_start.items():
        pedals.append(PedalEvent(start=start, end=seconds))
    return Transcription(notes=notes, pedals=pedals)
