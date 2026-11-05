"""Tests run against a scripted AI, so they are fast, repeatable and spend no quota."""
from __future__ import annotations

import io
import re
import sys
import time
from pathlib import Path

import pytest
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import Settings  # noqa: E402
from core.web import create_app  # noqa: E402

TEXTBOOK = """Machine learning is a branch of artificial intelligence.
Supervised learning uses labeled data to train models. Examples include Linear Regression and SVM.
Unsupervised learning works with unlabeled data. Examples include K-means clustering and PCA."""


class FakeAI:
    """Returns queued answers by schema key, and records every prompt it was sent."""

    model = "fake-model"

    def __init__(self):
        self.calls = []
        self.overrides = {}
        self.error = None

    def generate_json(self, system, prompt, schema, on_wait=None):
        self.calls.append({"system": system, "prompt": prompt})
        if self.error:
            raise self.error
        key = next(iter(schema["properties"]))
        if key in self.overrides:
            value = self.overrides[key]
            return value(prompt) if callable(value) else value
        if key == "topics":
            return {"topics": ["Supervised learning", "Unsupervised learning"]}
        if key == "decisions":
            ids = re.findall(r'"id": "(q\d+)"', prompt)
            return {"decisions": [{"id": i, "item_type": "question", "verdict": "keep", "reason": "Relevant.",
                                   "difficulty": "easy", "marks": 2, "topics": ["Supervised learning"],
                                   "source_ids": ["T1"]} for i in ids]}
        if key == "questions":
            count = int(re.search(r"Write exactly (\d+)", prompt).group(1))
            return {"questions": [{"text": f"Question {n}?", "difficulty": "medium", "marks": 5,
                                   "topic": "Supervised learning", "answer": f"Answer {n}",
                                   "source_ids": ["T1"]} for n in range(count)]}
        if key == "answers":
            ids = re.findall(r'"id": "(q\d+)"', prompt)
            return {"answers": [{"id": i, "answer": f"Key for {i}", "source_ids": ["T1"]} for i in ids]}
        if key == "issues":
            return {"issues": []}
        if key == "answer_markdown":
            return {"answer_markdown": "Supervised learning uses **labeled** data.",
                    "found_in_documents": True, "source_ids": ["A1", "A999"]}
        raise AssertionError(f"Unscripted schema: {key}")


@pytest.fixture
def ai():
    return FakeAI()


@pytest.fixture
def app(tmp_path, ai):
    return create_app(Settings(api_key="test", data_dir=tmp_path, max_upload_mb=1), ai=ai)


@pytest.fixture
def client(app):
    return app.test_client()


def make_docx(*lines: str, table: list | None = None) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                grid.cell(r, c).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def upload(client, name, data, role=None):
    form = {"files": (io.BytesIO(data), name)}
    if role:
        form["role"] = role
    response = client.post("/api/documents", data=form, content_type="multipart/form-data")
    assert response.status_code == 200, response.json
    assert response.json["uploaded"], response.json
    return response.json["uploaded"][0]["id"]


def wait_job(client, response):
    assert response.status_code == 202, response.json
    job_id = response.json["job_id"]
    for _ in range(300):
        job = client.get(f"/api/jobs/{job_id}").json
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("Job did not finish")
