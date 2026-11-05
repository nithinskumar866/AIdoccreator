"""Application settings, read once from the environment (and .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-flash-lite-latest"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    host: str = "127.0.0.1"
    port: int = 10000
    allow_remote: bool = False
    data_dir: Path = field(default_factory=lambda: BASE_DIR / "data")
    max_upload_mb: int = 25
    ai_timeout_s: int = 60
    ai_max_retries: int = 5
    ai_rpm: int = 10
    job_workers: int = 2
    max_queued_jobs: int = 20

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(BASE_DIR / ".env")
        return cls(
            api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            host=os.getenv("DOCUMENTOR_HOST", "127.0.0.1").strip(),
            port=_int("PORT", 10000),
            allow_remote=os.getenv("DOCUMENTOR_ALLOW_REMOTE", "").lower() in {"1", "true", "yes"},
            data_dir=Path(os.getenv("DOCUMENTOR_DATA_DIR", str(BASE_DIR / "data"))),
            max_upload_mb=_int("DOCUMENTOR_MAX_UPLOAD_MB", 25),
            ai_timeout_s=_int("GEMINI_TIMEOUT_SECONDS", 60),
            ai_max_retries=_int("GEMINI_MAX_RETRIES", 5),
            ai_rpm=_int("GEMINI_REQUESTS_PER_MINUTE", 10),
        )
