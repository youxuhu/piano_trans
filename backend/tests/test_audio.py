import subprocess
import pytest
from lingpu.audio import decode, AudioError


def test_decode_and_invalid_input(tmp_path):
    path = tmp_path / "valid.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.1",
            "-y",
            str(path),
        ],
        check=True,
    )
    audio, sr = decode(path, tmp_path / "out.wav")
    assert sr == 16000 and len(audio) == 1600
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(AudioError, match="解码失败"):
        decode(bad, tmp_path / "out.wav")
    with pytest.raises(AudioError, match="超过"):
        decode(path, tmp_path / "out.wav", max_seconds=0.05)
