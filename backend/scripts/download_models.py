#!/usr/bin/env python3
"""Explicitly download and verify the official ByteDance piano checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import hmac
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CHECKPOINT_URL = (
    "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
)
SOURCE = "https://github.com/qiuqiangkong/piano_transcription_inference"
LICENSE = "CC-BY-4.0 (checkpoint; Zenodo record 4034264)"
ZENODO_SIZE_BYTES = 171_966_578
ZENODO_MD5 = "22b961b77c1878239fec963362097045"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--weights-dir", type=Path, default=Path(__file__).resolve().parents[1] / "weights"
    )
    parser.add_argument("--sha256", help="Expected SHA-256; reject the download unless it matches")
    args = parser.parse_args()
    dest = args.weights_dir / "bytedance.pth"
    args.weights_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".bytedance-", suffix=".part", dir=args.weights_dir)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(CHECKPOINT_URL, timeout=60) as response, tmp.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
                digest.update(chunk)
            out.flush()
            os.fsync(out.fileno())
        actual = digest.hexdigest()
        if tmp.stat().st_size != ZENODO_SIZE_BYTES:
            raise RuntimeError(
                f"Unexpected checkpoint size: {tmp.stat().st_size} bytes (Zenodo reports {ZENODO_SIZE_BYTES})"
            )
        md5 = hashlib.md5()
        with tmp.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                md5.update(block)
        actual_md5 = md5.hexdigest()
        if not hmac.compare_digest(actual_md5, ZENODO_MD5):
            raise RuntimeError(f"Zenodo MD5 mismatch: expected {ZENODO_MD5}, received {actual_md5}")
        if args.sha256 and actual.lower() != args.sha256.lower():
            raise RuntimeError(f"SHA-256 mismatch: expected {args.sha256}, received {actual}")
        os.replace(tmp, dest)
        manifest = {
            "model": "bytedance-piano-transcription-note-pedal",
            "file": dest.name,
            "sha256": actual,
            "zenodo_md5": actual_md5,
            "zenodo_size_bytes": ZENODO_SIZE_BYTES,
            "size_bytes": dest.stat().st_size,
            "source_url": CHECKPOINT_URL,
            "source_repository": SOURCE,
            "source_record": "https://zenodo.org/records/4034264",
            "license": LICENSE,
            "license_source": "https://zenodo.org/api/records/4034264 (metadata.license.id=cc-by-4.0)",
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "expected_sha256_supplied": args.sha256,
        }
        manifest_path = args.weights_dir / "manifest.json"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=args.weights_dir,
            prefix=".manifest-",
            suffix=".tmp",
            delete=False,
        ) as out:
            json.dump(manifest, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
            manifest_tmp = Path(out.name)
        os.replace(manifest_tmp, manifest_path)
        print(f"Saved {dest} ({dest.stat().st_size} bytes), SHA-256 {actual}")
        print(f"Manifest: {manifest_path}")
        return 0
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
