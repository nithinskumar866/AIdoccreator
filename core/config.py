"""Application settings, read once from the environment (and .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-flash-lite-latest"
DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-001"
PROVIDERS = ("gemini", "ollama")


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
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embeds_per_minute: int = 90  # the free tier allows 100 texts a minute
    agent_max_steps: int = 6
    # Your own models on Ollama, for example on a RunPod GPU, instead of Gemini.
    provider: str = "gemini"
    ollama_url: str = ""
    ollama_model: str = "llama3.1:8b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_api_key: str = ""
    ollama_num_ctx: int = 16384
    ollama_rpm: int = 0  # 0 means no pacing: it's your own GPU

    @property
    def ai_ready(self) -> bool:
        return bool(self.ollama_url) if self.provider == "ollama" else bool(self.api_key)

    @property
    def active_model(self) -> str:
        return self.ollama_model if self.provider == "ollama" else self.model

    @property
    def active_embedding_model(self) -> str:
        return f"ollama/{self.ollama_embed_model}" if self.provider == "ollama" else self.embedding_model

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
            embedding_model=os.getenv("GEMINI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip()
            or DEFAULT_EMBEDDING_MODEL,
            embeds_per_minute=_int("GEMINI_EMBEDS_PER_MINUTE", 90),
            agent_max_steps=_int("DOCUMENTOR_AGENT_MAX_STEPS", 6),
            provider=provider if (provider := os.getenv("LLM_PROVIDER", "gemini").strip().lower()) in PROVIDERS
            else "gemini",
            ollama_url=os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip() or "llama3.1:8b",
            ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text").strip() or "nomic-embed-text",
            ollama_api_key=os.getenv("OLLAMA_API_KEY", "").strip(),
            ollama_num_ctx=_int("OLLAMA_NUM_CTX", 16384),
            ollama_rpm=_int("OLLAMA_REQUESTS_PER_MINUTE", 0),
        )
