"""Hybrid search: keyword (BM25) and meaning (embeddings), combined with Reciprocal Rank Fusion.

Embeddings are made in the background after an upload, slowly enough to stay inside the free
tier, and kept in SQLite. Until a document is indexed, or if embedding fails, search quietly
falls back to keywords alone, so the agents always work."""
from __future__ import annotations

import logging
import math
import time
from array import array
from typing import Any, Callable, Optional

from . import retrieval
from .store import Store

log = logging.getLogger("documentor.hybrid")
RRF_K = 60
BATCH = 40


def _pack(vector: list[float]) -> bytes:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return array("f", (x / norm for x in vector)).tobytes()


def _unpack(blob: bytes) -> array:
    values = array("f")
    values.frombytes(blob)
    return values


def _cosine(a: array, b: array) -> float:
    return sum(x * y for x, y in zip(a, b))  # both are stored normalised


class HybridSearch:
    def __init__(self, store: Store, embeddings: Any, model: str, per_minute: int = 90,
                 sleep: Callable[[float], None] = time.sleep):
        self.store = store
        self.embeddings = embeddings  # a LangChain Embeddings object, or None when there's no key
        self.model = model
        self.per_minute = max(per_minute, 1)
        self._sleep = sleep

    @staticmethod
    def chunks(document: dict) -> list[dict]:
        return retrieval.chunk_segments(document["segments"], "C")

    # ---------- indexing ----------
    def index(self, document: dict, progress: Optional[Callable[[int, str], None]] = None) -> dict:
        """Embed every chunk not embedded yet. Safe to run again after a failure."""
        chunks = self.chunks(document)
        if self.embeddings is None:
            self.store.set_index(document["id"], self.model, len(chunks), 0, "unavailable",
                                 "No Gemini API key is set.")
            return {"embedded": 0, "chunks": len(chunks)}
        have = self.store.get_vectors(document["id"], self.model)
        todo = [c for c in chunks if c["id"] not in have]
        done = len(chunks) - len(todo)
        self.store.set_index(document["id"], self.model, len(chunks), done, "indexing")
        try:
            for start in range(0, len(todo), BATCH):
                batch = todo[start:start + BATCH]
                began = time.monotonic()
                vectors = self.embeddings.embed_documents([c["text"] for c in batch])
                self.store.add_vectors(document["id"], self.model,
                                       {c["id"]: _pack(v) for c, v in zip(batch, vectors)})
                done += len(batch)
                self.store.set_index(document["id"], self.model, len(chunks), done, "indexing")
                if progress:
                    progress(int(100 * done / max(len(chunks), 1)),
                             f"Preparing meaning search for {document['name']} ({done} of {len(chunks)} passages)")
                if start + BATCH < len(todo):  # stay under the per-minute limit
                    self._sleep(max(0.0, len(batch) * 60.0 / self.per_minute - (time.monotonic() - began)))
        except Exception as exc:  # keyword search still works, so record it and move on
            log.warning("Embedding %s failed: %s", document["id"], type(exc).__name__)
            self.store.set_index(document["id"], self.model, len(chunks), done, "partial",
                                 "Gemini couldn't finish this. Keyword search is used meanwhile.")
            raise
        self.store.set_index(document["id"], self.model, len(chunks), done, "ready")
        return {"embedded": done, "chunks": len(chunks)}

    # ---------- searching ----------
    def search(self, query: str, documents: list[dict], top: int = 5) -> list[dict]:
        """Best passages across the documents, each tagged with how it was found."""
        candidates: list[dict] = []
        keyword_rank: dict[str, int] = {}
        meaning_rank: dict[str, int] = {}
        query_vector = self._query_vector(query, documents)
        for position, document in enumerate(documents):
            chunks = self.chunks(document)
            if not chunks:
                continue
            key = lambda c: f"{document['id']}:{c['id']}"  # noqa: E731
            for c in chunks:
                candidates.append({**c, "key": key(c), "document": document["name"], "doc_index": position})
            for rank, hit in enumerate(retrieval.Index(chunks).search(query, top * 3)):
                keyword_rank[key(hit)] = rank
            if query_vector is not None:
                stored = self.store.get_vectors(document["id"], self.model)
                scored = sorted(((_cosine(query_vector, _unpack(stored[c["id"]])), c) for c in chunks
                                 if c["id"] in stored), key=lambda pair: -pair[0])
                for rank, (score, c) in enumerate(scored[:top * 3]):
                    if score > 0.3:
                        meaning_rank[key(c)] = rank
        # Reciprocal Rank Fusion: reward passages that rank well in either list, more in both.
        fused = []
        for c in candidates:
            k, m = keyword_rank.get(c["key"]), meaning_rank.get(c["key"])
            if k is None and m is None:
                continue
            score = (1 / (RRF_K + k) if k is not None else 0) + (1 / (RRF_K + m) if m is not None else 0)
            found = "both" if k is not None and m is not None else ("keywords" if k is not None else "meaning")
            fused.append((score, {**c, "found_by": found}))
        fused.sort(key=lambda pair: -pair[0])
        return [c for _, c in fused[:top]]

    def _query_vector(self, query: str, documents: list[dict]) -> Optional[array]:
        if self.embeddings is None:
            return None
        if not any(self.store.get_vectors(d["id"], self.model) for d in documents):
            return None
        try:
            return _unpack(_pack(self.embeddings.embed_query(query)))
        except Exception as exc:
            log.warning("Query embedding failed, using keywords only: %s", type(exc).__name__)
            return None
