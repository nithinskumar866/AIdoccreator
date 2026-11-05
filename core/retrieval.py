"""Split long documents into passages and find the relevant ones (BM25, no extra services)."""
from __future__ import annotations

import math
import re
from collections import Counter

STOPWORDS = set(
    "a an and are as at be by can do does for from has have how in into is it its of on or that "
    "the their this to was were what when where which who why will with you your about between "
    "describe explain define discuss give list state write".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


def chunk_segments(segments: list[dict], prefix: str, size: int = 1200, overlap: int = 150) -> list[dict]:
    """Group a document's text into passages of about `size` characters, labelled by section."""
    chunks: list[dict] = []

    def add(label: str, text: str) -> None:
        chunks.append({"id": f"{prefix}{len(chunks) + 1}", "label": label, "text": text.strip()})

    for segment in segments:
        buffer = ""
        for line in segment["text"].split("\n"):
            while len(line) > size:  # one enormous line, e.g. a PDF without breaks
                cut = line.rfind(" ", 0, size)
                cut = cut if cut > size // 2 else size
                if buffer:
                    add(segment["label"], buffer)
                    buffer = ""
                add(segment["label"], line[:cut])
                line = line[max(cut - overlap, 1):]
            if buffer and len(buffer) + len(line) + 1 > size:
                add(segment["label"], buffer)
                buffer = buffer[-overlap:] if overlap else ""
            buffer = f"{buffer}\n{line}" if buffer else line
        if buffer.strip():
            add(segment["label"], buffer)
    return chunks


class Index:
    k1 = 1.5
    b = 0.75

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.docs = [Counter(tokenize(f"{c['label']} {c['text']}")) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df: Counter = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, top: int = 3) -> list[dict]:
        terms = set(tokenize(query))
        scored = []
        for i, doc in enumerate(self.docs):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg or 1))
                    score += self.idf.get(term, 0) * tf * (self.k1 + 1) / norm
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [self.chunks[i] for _, i in scored[:top]]


def select(index: Index, queries: list[str], per_query: int, budget: int) -> list[dict]:
    """Best passages across queries, one round per query so no question is starved of context."""
    ranked = [index.search(q, per_query) for q in queries]
    chosen: dict[str, dict] = {}
    used = 0
    for depth in range(per_query):
        for hits in ranked:
            if depth < len(hits) and hits[depth]["id"] not in chosen:
                size = len(hits[depth]["text"])
                if used + size > budget:
                    continue
                chosen[hits[depth]["id"]] = hits[depth]
                used += size
    return sorted(chosen.values(), key=lambda c: int(re.sub(r"\D", "", c["id"]) or 0))


def overview(chunks: list[dict], budget: int) -> list[dict]:
    """Evenly spaced passages, so a summary sees the whole document instead of only its start."""
    if not chunks:
        return []
    average = sum(len(c["text"]) for c in chunks) / len(chunks)
    count = min(len(chunks), max(1, int(budget / max(average, 1))))
    step = len(chunks) / count
    return [chunks[int(i * step)] for i in range(count)]


def source_of(chunk: dict, document: str) -> dict:
    return {"id": chunk["id"], "label": chunk["label"], "document": document,
            "excerpt": chunk["text"][:400]}
