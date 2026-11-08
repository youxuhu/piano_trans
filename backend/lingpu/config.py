from dataclasses import dataclass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Config:
    data_dir: Path = ROOT / "data"
    weights_dir: Path = ROOT / "weights"
    device: str = "cuda"
    model: str = "bytedance"
    max_bytes: int = 100 * 1024 * 1024
    max_seconds: int = 600
    start_worker: bool = True

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("LINGPU_DATA_DIR", ROOT / "data")),
            weights_dir=Path(os.getenv("LINGPU_WEIGHTS_DIR", ROOT / "weights")),
            device=os.getenv("LINGPU_DEVICE", "cuda"),
            model=os.getenv("LINGPU_MODEL", "bytedance"),
        )
