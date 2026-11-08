import json
import shutil
import subprocess
from pathlib import Path


class AudioError(ValueError):
    pass


def decode(source: Path, destination: Path, max_seconds=600):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise AudioError("未找到系统 ffmpeg / ffprobe，请先安装")
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        info = json.loads(probe.stdout)
        if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
            raise AudioError("文件不包含可解码音频")
        reported = float(info.get("format", {}).get("duration") or 0)
        if reported > max_seconds:
            raise AudioError(f"音频超过 {max_seconds // 60} 分钟限制")
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-t",
                str(max_seconds + 1),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )
        import soundfile as sf

        audio, sr = sf.read(destination, dtype="float32")
        if audio.size == 0:
            raise AudioError("音频为空")
        if len(audio) / sr > max_seconds:
            raise AudioError(f"音频超过 {max_seconds // 60} 分钟限制")
        return audio, sr
    except AudioError:
        raise
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise AudioError("音频解码失败，请检查文件是否损坏") from exc
