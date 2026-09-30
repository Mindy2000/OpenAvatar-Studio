from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    avatars_dir: Path
    exports_dir: Path
    max_upload_bytes: int = 50 * 1024 * 1024
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"


def load_settings() -> Settings:
    data_dir = Path(os.getenv("OPENAVATAR_DATA_DIR", ROOT / "data")).expanduser().resolve()
    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "openavatar.sqlite",
        avatars_dir=data_dir / "avatars",
        exports_dir=data_dir / "exports",
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024,
        ollama_url=ollama_url,
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
    )


def ensure_directories(settings: Settings) -> None:
    for path in (settings.data_dir, settings.avatars_dir, settings.exports_dir):
        path.mkdir(parents=True, exist_ok=True)

