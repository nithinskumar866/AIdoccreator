"""Running on your own models through Ollama (for example on a RunPod GPU) instead of Gemini."""
import json

import httpx
import pytest

from core.ai import AIError, OllamaClient
from core.config import Settings
from core.web import create_app

SCHEMA = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}


def client_with(handler, **kwargs):
    return OllamaClient("https://pod-11434.proxy.runpod.net/", "llama3.1:8b", max_retries=2,
                        sleep=lambda _s: None, transport=httpx.MockTransport(handler), **kwargs)


def test_json_requests_use_the_native_api_with_a_schema_and_a_bigger_context():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"city": "Paris"}'}})

    ai = client_with(handler, num_ctx=16384, api_key="secret")
    assert ai.generate_json("Answer in JSON.", "Capital of France?", SCHEMA) == {"city": "Paris"}
    request = seen[0]
    body = json.loads(request.content)
    assert request.url.path == "/api/chat" and body["stream"] is False
    assert body["format"] == SCHEMA and body["options"]["num_ctx"] == 16384  # no silent truncation
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert request.headers["User-Agent"] == "DocuMentor/1.0"  # RunPod's proxy blocks some defaults
    assert request.headers["Authorization"] == "Bearer secret"


def test_errors_are_explained_and_temporary_ones_retried():
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="loading")
        return httpx.Response(200, json={"message": {"content": '{"city": "Rome"}'}})

    assert client_with(flaky).generate_json("s", "p", SCHEMA) == {"city": "Rome"} and calls["n"] == 2

    missing = client_with(lambda r: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(AIError) as error:
        missing.generate_json("s", "p", SCHEMA)
    assert error.value.code == "model" and "ollama pull llama3.1:8b" in error.value.message

    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(AIError) as error:
        client_with(down).generate_json("s", "p", SCHEMA)
    assert error.value.code == "network" and "pod-11434.proxy.runpod.net" in error.value.message
    assert "pod running" in error.value.message

    refused = client_with(lambda r: httpx.Response(403, text="forbidden"))
    with pytest.raises(AIError) as error:
        refused.generate_json("s", "p", SCHEMA)
    assert error.value.code == "auth"


def test_settings_choose_the_provider_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "Ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://pod-11434.proxy.runpod.net/")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    settings = Settings.from_env()
    assert settings.provider == "ollama" and settings.ollama_url == "https://pod-11434.proxy.runpod.net"
    assert settings.ai_ready and settings.active_model == "qwen2.5:7b"
    assert settings.active_embedding_model == "ollama/nomic-embed-text"
    monkeypatch.setenv("LLM_PROVIDER", "something-else")
    assert Settings.from_env().provider == "gemini"


def test_the_app_runs_everything_on_ollama_without_a_gemini_key(tmp_path):
    settings = Settings(provider="ollama", ollama_url="https://pod-11434.proxy.runpod.net",
                        ollama_model="llama3.1:8b", data_dir=tmp_path)
    app = create_app(settings)
    assert isinstance(app.config["SERVICES"].ai, OllamaClient)
    agents = app.config["AGENTS"]
    assert type(agents.model).__name__ == "ChatOllama" and agents.model.num_ctx == 16384
    assert agents.search.model == "ollama/nomic-embed-text" and agents.search.per_minute == 100_000
    status = app.test_client().get("/api/status").json
    assert status["ai_configured"] and status["agents"] and status["provider"] == "ollama"
    assert status["model"] == "llama3.1:8b"

    unset = create_app(Settings(provider="ollama", data_dir=tmp_path / "b"))
    assert unset.test_client().get("/api/status").json["ai_configured"] is False
