#!/usr/bin/env python3
"""Reproducibly benchmark both transcription models on the same local audio clip."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=REPO / "音源素材" / "小星星_爱给网_aigei_com.mp3"
    )
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--clip", type=Path, default=Path("/tmp/lingpu-benchmark.wav"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--results-dir", type=Path, default=REPO / "backend/output/benchmarks")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    args.clip.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(args.source),
            "-t",
            str(args.seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "22050",
            str(args.clip),
        ],
        check=True,
    )
    args.results_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "source": str(args.source.resolve()),
        "clip": str(args.clip.resolve()),
        "seconds_requested": args.seconds,
        "device": args.device,
        "models": {},
    }
    for model in ("transkun", "bytedance"):
        result_path = args.results_dir / f"{model}.json"
        cmd = [
            sys.executable,
            "-m",
            "backend.scripts.benchmark",
            str(args.clip),
            "--model",
            model,
            "--device",
            args.device,
            "--output-json",
            str(result_path),
        ]
        if model == "transkun":
            cmd.extend(["--transkun-executable", str(REPO / "scripts/transkun.sh")])
        proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
        summary["models"][model] = {
            "returncode": proc.returncode,
            "result": str(result_path),
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
        if proc.returncode == 0 and result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            summary["models"][model].update(
                {
                    key: result.get(key)
                    for key in (
                        "load_seconds",
                        "inference_seconds",
                        "model_pipeline_seconds",
                        "duration_seconds",
                    )
                }
            )
            summary["models"][model]["note_count"] = len(result.get("notes", []))
            summary["models"][model]["pedal_count"] = len(result.get("pedals", []))
    summary_path = args.results_dir / "suite.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if all(v["returncode"] == 0 for v in summary["models"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
