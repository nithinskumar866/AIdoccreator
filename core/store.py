"""SQLite storage for documents, jobs, results, chats and the question bank. Only extracted text is kept."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL,
  sha256 TEXT NOT NULL, chars INTEGER NOT NULL, pages INTEGER NOT NULL,
  segments TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL,
  message TEXT NOT NULL, params TEXT NOT NULL, output TEXT, error_code TEXT, error TEXT,
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL, data TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, document_ids TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_chat ON messages(chat_id, created_at);
CREATE TABLE IF NOT EXISTS embeddings (
  document_id TEXT NOT NULL, chunk_id TEXT NOT NULL, model TEXT NOT NULL, vector BLOB NOT NULL,
  PRIMARY KEY (document_id, chunk_id, model)
);
CREATE TABLE IF NOT EXISTS doc_index (
  document_id TEXT NOT NULL, model TEXT NOT NULL, chunks INTEGER NOT NULL, embedded INTEGER NOT NULL,
  status TEXT NOT NULL, error TEXT, updated_at REAL NOT NULL, PRIMARY KEY (document_id, model)
);
CREATE TABLE IF NOT EXISTS agent_threads (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
  data TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bank (
  id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, data TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
"""


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "documentor.sqlite3"
        with self._db() as db:
            db.executescript(SCHEMA)
            db.execute("UPDATE doc_index SET status='partial' WHERE status='indexing'")
            db.execute(
                "UPDATE jobs SET status='failed', error_code='interrupted', "
                "error='DocuMentor restarted before this finished. Please run it again.' "
                "WHERE status IN ('queued','running')"
            )

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    # Documents
    def find_document(self, sha256: str, role: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT id FROM documents WHERE sha256=? AND role=?", (sha256, role)).fetchone()
        return self.get_document(row["id"]) if row else None

    def add_document(self, name: str, role: str, kind: str, sha256: str, segments: list[dict], pages: int) -> dict:
        doc_id = new_id()
        chars = sum(len(s["text"]) for s in segments)
        with self._db() as db:
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)",
                       (doc_id, name, role, kind, sha256, chars, pages, json.dumps(segments), time.time()))
        return self.get_document(doc_id)

    def get_document(self, doc_id: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return None
        document = dict(row)
        document["segments"] = json.loads(document["segments"])
        return document

    def list_documents(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT id,name,role,kind,chars,pages,created_at FROM documents "
                              "ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def update_document_role(self, doc_id: str, role: str) -> bool:
        with self._db() as db:
            return db.execute("UPDATE documents SET role=? WHERE id=?", (role, doc_id)).rowcount > 0

    def delete_document(self, doc_id: str) -> bool:
        with self._db() as db:
            db.execute("DELETE FROM embeddings WHERE document_id=?", (doc_id,))
            db.execute("DELETE FROM doc_index WHERE document_id=?", (doc_id,))
            return db.execute("DELETE FROM documents WHERE id=?", (doc_id,)).rowcount > 0

    # Jobs
    def create_job(self, job_type: str, params: dict) -> str:
        job_id, now = new_id(), time.time()
        with self._db() as db:
            db.execute("INSERT INTO jobs (id,type,status,progress,message,params,created_at,updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (job_id, job_type, "queued", 0, "Waiting to start", json.dumps(params), now, now))
        return job_id

    def update_job(self, job_id: str, **fields: Any) -> None:
        if "output" in fields:
            fields["output"] = json.dumps(fields["output"])
        fields["updated_at"] = time.time()
        columns = ",".join(f"{name}=?" for name in fields)
        with self._db() as db:
            db.execute(f"UPDATE jobs SET {columns} WHERE id=?", (*fields.values(), job_id))

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT id,type,status,progress,message,output,error_code,error "
                             "FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job["output"] = json.loads(job["output"]) if job["output"] else None
        return job

    def active_jobs(self) -> int:
        with self._db() as db:
            return db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]

    # Results
    def add_result(self, result_type: str, title: str, data: dict) -> str:
        result_id, now = new_id(), time.time()
        with self._db() as db:
            db.execute("INSERT INTO results VALUES (?,?,?,?,?,?)",
                       (result_id, result_type, title, json.dumps(data), now, now))
        return result_id

    def get_result(self, result_id: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT * FROM results WHERE id=?", (result_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["data"] = json.loads(result["data"])
        return result

    def save_result(self, result_id: str, data: dict, title: Optional[str] = None) -> None:
        with self._db() as db:
            db.execute("UPDATE results SET data=?, updated_at=?, title=COALESCE(?,title) WHERE id=?",
                       (json.dumps(data), time.time(), title, result_id))

    def list_results(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT id,type,title,created_at,updated_at FROM results "
                              "ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_result(self, result_id: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM results WHERE id=?", (result_id,)).rowcount > 0

    # Chats
    def create_chat(self, title: str, document_ids: list[str]) -> str:
        chat_id = new_id()
        with self._db() as db:
            db.execute("INSERT INTO chats VALUES (?,?,?,?)",
                       (chat_id, title, json.dumps(document_ids), time.time()))
        return chat_id

    def get_chat(self, chat_id: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
            if not row:
                return None
            messages = db.execute("SELECT id,role,content,sources,created_at FROM messages "
                                  "WHERE chat_id=? ORDER BY created_at, rowid", (chat_id,)).fetchall()
        chat = dict(row)
        chat["document_ids"] = json.loads(chat["document_ids"])
        chat["messages"] = [{**dict(m), "sources": json.loads(m["sources"])} for m in messages]
        return chat

    def list_chats(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT id,title,created_at FROM chats ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def add_message(self, chat_id: str, role: str, content: str, sources: Optional[list] = None) -> None:
        with self._db() as db:
            db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)",
                       (new_id(), chat_id, role, content, json.dumps(sources or []), time.time()))

    def delete_chat(self, chat_id: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM chats WHERE id=?", (chat_id,)).rowcount > 0

    # Question bank
    def add_bank_question(self, fingerprint: str, data: dict) -> Optional[str]:
        """Returns the new id, or None when the same question is already saved."""
        question_id, now = new_id(), time.time()
        with self._db() as db:
            added = db.execute("INSERT OR IGNORE INTO bank (id,fingerprint,data,used,created_at,updated_at) "
                               "VALUES (?,?,?,0,?,?)",
                               (question_id, fingerprint, json.dumps(data), now, now)).rowcount
        return question_id if added else None

    def list_bank(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM bank ORDER BY created_at DESC, rowid DESC").fetchall()
        return [self._bank_row(r) for r in rows]

    def get_bank_question(self, question_id: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT * FROM bank WHERE id=?", (question_id,)).fetchone()
        return self._bank_row(row) if row else None

    @staticmethod
    def _bank_row(row) -> dict:
        return {**json.loads(row["data"]), "id": row["id"], "used": row["used"],
                "created_at": row["created_at"], "fingerprint": row["fingerprint"]}

    def update_bank_question(self, question_id: str, fingerprint: str, data: dict) -> bool:
        """False when another saved question already has this wording."""
        with self._db() as db:
            clash = db.execute("SELECT 1 FROM bank WHERE fingerprint=? AND id<>?",
                               (fingerprint, question_id)).fetchone()
            if clash:
                return False
            db.execute("UPDATE bank SET fingerprint=?, data=?, updated_at=? WHERE id=?",
                       (fingerprint, json.dumps(data), time.time(), question_id))
        return True

    def delete_bank_question(self, question_id: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM bank WHERE id=?", (question_id,)).rowcount > 0

    def mark_bank_used(self, question_ids: list[str]) -> None:
        with self._db() as db:
            db.executemany("UPDATE bank SET used=used+1 WHERE id=?", [(i,) for i in question_ids])

    def bank_count(self) -> int:
        with self._db() as db:
            return db.execute("SELECT COUNT(*) FROM bank").fetchone()[0]

    # Embeddings for meaning-based search
    def get_vectors(self, doc_id: str, model: str) -> dict[str, bytes]:
        with self._db() as db:
            rows = db.execute("SELECT chunk_id, vector FROM embeddings WHERE document_id=? AND model=?",
                              (doc_id, model)).fetchall()
        return {r["chunk_id"]: r["vector"] for r in rows}

    def add_vectors(self, doc_id: str, model: str, vectors: dict[str, bytes]) -> None:
        with self._db() as db:
            db.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)",
                           [(doc_id, chunk, model, blob) for chunk, blob in vectors.items()])

    def set_index(self, doc_id: str, model: str, chunks: int, embedded: int, status: str,
                  error: Optional[str] = None) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO doc_index VALUES (?,?,?,?,?,?,?)",
                       (doc_id, model, chunks, embedded, status, error, time.time()))

    def index_status(self, model: str) -> dict[str, dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM doc_index WHERE model=?", (model,)).fetchall()
        return {r["document_id"]: {k: r[k] for k in ("chunks", "embedded", "status", "error")} for r in rows}

    # Agent conversations and plans (their step-by-step state lives in the LangGraph checkpointer)
    def create_thread(self, kind: str, title: str, data: Optional[dict] = None) -> str:
        thread_id, now = new_id(), time.time()
        with self._db() as db:
            db.execute("INSERT INTO agent_threads VALUES (?,?,?,?,?,?,?)",
                       (thread_id, kind, title, "new", json.dumps(data or {}), now, now))
        return thread_id

    def get_thread(self, thread_id: str) -> Optional[dict]:
        with self._db() as db:
            row = db.execute("SELECT * FROM agent_threads WHERE id=?", (thread_id,)).fetchone()
        return {**dict(row), "data": json.loads(row["data"])} if row else None

    def update_thread(self, thread_id: str, status: Optional[str] = None, data: Optional[dict] = None) -> None:
        with self._db() as db:
            db.execute("UPDATE agent_threads SET status=COALESCE(?,status), data=COALESCE(?,data), "
                       "updated_at=? WHERE id=?",
                       (status, json.dumps(data) if data is not None else None, time.time(), thread_id))

    def list_threads(self, kind: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT id,kind,title,status,created_at,updated_at FROM agent_threads "
                              "WHERE kind=? ORDER BY updated_at DESC", (kind,)).fetchall()
        return [dict(r) for r in rows]

    def delete_thread(self, thread_id: str) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM agent_threads WHERE id=?", (thread_id,)).rowcount > 0
