import io
import os
import re
import time
from pathlib import Path

import pytest

from conftest import TEXTBOOK, upload
from core.ai import AIError, GeminiClient, UnconfiguredAI, _retry_delay
from core.config import Settings
from core.web import create_app


def test_page_and_static_assets_load_with_strict_headers(client):
    response = client.get("/")
    assert response.status_code == 200 and b"DocuMentor" in response.data
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert not re.search(rb'(?:src|href)="https?://', response.data)  # nothing from a CDN
    assert not re.search(rb"<script(?![^>]*src=)|<style|\sstyle=|\son\w+=", response.data)  # CSP-safe
    assert client.get("/static/js/app.js").status_code == 200
    assert client.get("/static/css/app.css").status_code == 200


def test_remote_hosts_are_refused_by_default(client):
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/", headers={"Host": "localhost:10000"}).status_code == 200


def test_cross_site_writes_are_refused(client):
    url = "/api/jobs/check_homework"
    assert client.post(url, json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post(url, json={}, headers={"Origin": "http://localhost"}).status_code == 400  # same origin


def test_remote_mode_is_explicit(tmp_path, ai):
    app = create_app(Settings(data_dir=tmp_path, allow_remote=True), ai=ai)
    assert app.test_client().get("/", headers={"Host": "school.example"}).status_code == 200


def test_app_refuses_to_listen_on_the_network_without_opt_in(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DOCUMENTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DOCUMENTOR_HOST", "0.0.0.0")
    monkeypatch.delenv("DOCUMENTOR_ALLOW_REMOTE", raising=False)
    import importlib
    import app as entry
    importlib.reload(entry)
    assert entry.main() == 1
    assert "only runs on this computer" in capsys.readouterr().err


def test_oversized_upload_returns_413_as_json(client):
    data = {"files": (io.BytesIO(b"x" * (2 * 1024 * 1024)), "big.txt")}
    response = client.post("/api/documents", data=data, content_type="multipart/form-data")
    assert response.status_code == 413 and "1 MB" in response.json["error"]


def test_bad_upload_explains_and_does_not_leak_paths(client):
    data = {"files": (io.BytesIO(b"nope"), "x.docx")}
    response = client.post("/api/documents", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    failed = response.json["failed"][0]
    assert "valid Word document" in failed["error"] and ":\\" not in failed["error"]


def test_mixed_upload_reports_each_file(client):
    data = {"files": [(io.BytesIO(b"good text"), "a.txt"), (io.BytesIO(b"x"), "b.exe")]}
    response = client.post("/api/documents", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert len(response.json["uploaded"]) == 1 and len(response.json["failed"]) == 1


def test_path_in_filename_is_stripped_and_nothing_is_written_outside_the_store(client, tmp_path):
    upload(client, "../../evil.txt", b"text", "notes")
    names = [d["name"] for d in client.get("/api/documents").json["documents"]]
    assert names == ["evil.txt"]
    assert not list(tmp_path.parent.glob("evil*"))
    assert {p.suffix for p in tmp_path.iterdir()} <= {".sqlite3", ".sqlite3-wal", ".sqlite3-shm"}


def test_duplicate_upload_is_reused_and_documents_can_be_deleted(client):
    first = upload(client, "a.txt", b"same text", "notes")
    assert upload(client, "b.txt", b"same text", "notes") == first
    assert len(client.get("/api/documents").json["documents"]) == 1
    assert client.delete(f"/api/documents/{first}").status_code == 200
    assert client.get(f"/api/documents/{first}").status_code == 404


def test_deleted_document_gives_a_clear_job_error(client):
    book = upload(client, "a.txt", TEXTBOOK.encode(), "textbook")
    client.delete(f"/api/documents/{book}")
    response = client.post("/api/jobs/generate_homework", json={"textbook_id": book, "count": 2})
    job_id = response.json["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json
        if job["status"] == "failed":
            break
        time.sleep(0.02)
    assert job["status"] == "failed" and "no longer exists" in job["error"]


@pytest.mark.parametrize("job,body,message", [
    ("generate_homework", {"textbook_id": "x", "count": 0}, "between 1"),
    ("generate_homework", {"textbook_id": "x", "count": "abc"}, "must be a number"),
    ("generate_homework", {}, "textbook"),
    ("check_homework", {"textbook_id": "x"}, "homework"),
    ("correct_notes", {"textbook_id": "x"}, "notes"),
    ("chat", {}, "Unknown"),
    ("nonsense", {}, "Unknown"),
])
def test_job_validation(client, job, body, message):
    response = client.post(f"/api/jobs/{job}", json=body)
    assert response.status_code == 400 and message in response.json["error"]


def test_too_many_queued_jobs_are_refused(tmp_path, ai):
    settings = Settings(data_dir=tmp_path, max_queued_jobs=0)
    client = create_app(settings, ai=ai).test_client()
    response = client.post("/api/jobs/generate_homework", json={"textbook_id": "x", "count": 1})
    assert response.status_code == 429


def test_unknown_api_paths_return_json(client):
    response = client.get("/api/nothing")
    assert response.status_code == 404 and response.is_json


def test_missing_key_still_opens_and_explains(tmp_path):
    client = create_app(Settings(data_dir=tmp_path)).test_client()
    assert client.get("/").status_code == 200
    assert client.get("/api/status").json["ai_configured"] is False
    with pytest.raises(AIError, match="No Gemini API key"):
        UnconfiguredAI().generate_json("s", "p", {})


def test_interrupted_jobs_are_marked_failed_on_restart(tmp_path, ai):
    from core.store import Store
    store = Store(tmp_path)
    job = store.create_job("chat", {})
    assert Store(tmp_path).get_job(job)["error_code"] == "interrupted"


class _Models:
    def __init__(self, effects):
        self.effects = list(effects)
        self.count = 0

    def generate_content(self, **_kwargs):
        self.count += 1
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return type("R", (), {"text": effect})()


def _client(effects):
    sleeps = []
    client = GeminiClient("k", "m", rpm=0, max_retries=2, sleep=sleeps.append)
    models = _Models(effects)
    client._client = type("C", (), {"models": models})()
    return client, models, sleeps


def _api_error(code, message="boom"):
    from google.genai import errors
    return errors.APIError(code, {"error": {"code": code, "message": message, "status": "X"}})


def test_rate_limit_waits_as_told_then_succeeds():
    client, models, sleeps = _client([_api_error(429, "Please retry in 7.5s."), '{"ok": true}'])
    assert client.generate_json("s", "p", {"type": "object"}) == {"ok": True}
    assert models.count == 2 and sleeps == [8.5]


def test_daily_quota_and_bad_key_do_not_retry():
    client, models, _ = _client([_api_error(429, "Quota exceeded: GenerateRequestsPerDay")])
    with pytest.raises(AIError) as info:
        client.generate_json("s", "p", {})
    assert info.value.code == "quota" and models.count == 1

    client, models, _ = _client([_api_error(403)])
    with pytest.raises(AIError) as info:
        client.generate_json("s", "p", {})
    assert info.value.code == "auth" and models.count == 1

    client, models, _ = _client([_api_error(404)])
    with pytest.raises(AIError) as info:
        client.generate_json("s", "p", {})
    assert info.value.code == "model" and "GEMINI_MODEL" in info.value.message


def test_timeouts_are_retried_then_reported():
    import httpx
    client, models, _ = _client([httpx.ReadTimeout("t")] * 3)
    with pytest.raises(AIError) as info:
        client.generate_json("s", "p", {})
    assert info.value.code == "timeout" and models.count == 3


def test_bad_json_gets_one_more_try():
    client, models, _ = _client(["not json", '```json\n{"a": 1}\n```'])
    assert client.generate_json("s", "p", {}) == {"a": 1}
    client, _, _ = _client(["nope", "still nope"])
    with pytest.raises(AIError, match="unreadable"):
        client.generate_json("s", "p", {})


def test_retry_delay_parsing():
    assert _retry_delay(Exception("Please retry in 45.53s.")) == 45.53
    assert _retry_delay(Exception("'retryDelay': '12s'")) == 12
    assert _retry_delay(Exception("nothing")) is None


def test_repo_has_no_secret_files_tracked_by_design():
    root = Path(__file__).resolve().parent.parent
    ignored = (root / ".gitignore").read_bytes()
    assert not ignored.startswith((b"\xff\xfe", b"\xfe\xff"))  # git can't read UTF-16
    assert b".env" in ignored
    assert (root / ".env.example").exists()
    assert "AIza" not in (root / ".env.example").read_text()
    assert os.path.exists(root / "requirements.txt")
    assert not (root / "requirements.txt").read_bytes().startswith(b"\xff\xfe")


def test_backoff_is_capped():
    client = GeminiClient("k", "m", rpm=0, max_retries=5, sleep=(sleeps := []).append)
    models = _Models([_api_error(503)] * 6)
    client._client = type("C", (), {"models": models})()
    with pytest.raises(AIError) as info:
        client.generate_json("s", "p", {})
    assert info.value.code == "unavailable" and models.count == 6
    assert sleeps == [2, 6, 18, 30, 30]
