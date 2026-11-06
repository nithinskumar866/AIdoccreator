"""The question bank: questions the teacher chose to keep, and assignments built from them.

Picking from the bank needs no AI. Only the optional top-up, which writes questions the bank
doesn't have, calls the model."""
from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from typing import Any, Optional

from .services import (DIFFICULTIES, MAX_QUESTIONS, Progress, ServiceError, Services, _clean_text,
                       _enum, _marks, final_items, strip_number)
from .store import Store

HOMEWORK_TYPES = {"homework_check", "homework_generated", "homework_bank"}
ANY = "any"
MAX_RULES = 12


def fingerprint(text: str, options: Optional[list[str]] = None) -> str:
    """Same wording, ignoring case, punctuation and spacing, counts as the same question."""
    words = re.sub(r"[^a-z0-9]+", " ", " ".join([text, *(options or [])]).lower()).strip()
    return hashlib.sha256(words.encode()).hexdigest()


def _entry(item: dict, result: dict) -> dict:
    data = result["data"]
    return {
        "text": strip_number(item["text"]),  # options written inline in a checked file stay inline
        "options": list(item.get("options") or []),
        "answer": item.get("answer") or "",
        "marks": item.get("marks"),
        "difficulty": item.get("difficulty") or "",
        "topic": (item.get("topics") or [""])[0],
        "question_type": item.get("question_type") or "",
        "sources": item.get("sources") or [],
        "textbook": (data.get("documents") or {}).get("textbook") or "",
        "textbook_id": data.get("textbook_id"),
        "origin": {"result_id": result["id"], "item_id": item["id"], "title": result["title"]},
    }


def save_from_result(store: Store, result: dict, item_ids: Optional[list[str]]) -> dict:
    """Save questions as they stand after the teacher's decisions. Undecided changes aren't saved."""
    if result["type"] not in HOMEWORK_TYPES:
        raise ServiceError("Only homework questions can be saved to the bank.")
    final = {i["id"]: i for i in final_items(result["data"]) if i["type"] == "question"}
    if item_ids is None:
        chosen = [i for i in final.values() if i.get("decision") != "pending"]
    else:
        if any(i not in final or final[i].get("decision") == "pending" for i in item_ids):
            raise ServiceError("Only questions in the final homework can be saved. "
                               "Decide any suggested change first.")
        chosen = [final[i] for i in item_ids]
    added, duplicates = [], 0
    for item in chosen:
        entry = _entry(item, result)
        new = store.add_bank_question(fingerprint(entry["text"], entry["options"]), entry)
        if new:
            added.append(new)
        else:
            duplicates += 1
    return {"added": len(added), "duplicates": duplicates}


def saved_item_ids(store: Store, result_id: str) -> list[str]:
    return [q["origin"]["item_id"] for q in store.list_bank()
            if (q.get("origin") or {}).get("result_id") == result_id]


def listing(store: Store) -> dict:
    questions = store.list_bank()
    topics = Counter(q["topic"] for q in questions if q["topic"])
    return {
        "questions": [{k: v for k, v in q.items() if k != "fingerprint"} for q in questions],
        "topics": [{"topic": t, "count": n} for t, n in sorted(topics.items(), key=lambda x: x[0].lower())],
        "difficulties": DIFFICULTIES,
    }


def update(store: Store, question_id: str, body: dict) -> dict:
    question = store.get_bank_question(question_id)
    if not question:
        raise ServiceError("That question is no longer in the bank.")
    if "text" in body:
        text = _clean_text(body.get("text"))
        if not text:
            raise ServiceError("The question can't be empty.")
        question["text"] = strip_number(text)
    if "answer" in body:
        question["answer"] = _clean_text(body.get("answer"))
    if "topic" in body:
        question["topic"] = _clean_text(body.get("topic"), 80)
    if "difficulty" in body:
        question["difficulty"] = _enum(body.get("difficulty"), DIFFICULTIES)
    if "marks" in body:
        question["marks"] = _marks(body.get("marks"))
    stored = {k: v for k, v in question.items() if k not in ("id", "used", "created_at", "fingerprint")}
    if not store.update_bank_question(question_id, fingerprint(question["text"], question["options"]), stored):
        raise ServiceError("Another question in the bank already has this wording.")
    return store.get_bank_question(question_id)


def _rules(raw: Any) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_RULES:
        raise ServiceError(f"Add between 1 and {MAX_RULES} picking rules.")
    rules = []
    for rule in raw:
        if not isinstance(rule, dict):
            raise ServiceError("Invalid picking rule.")
        try:
            count = int(rule.get("count", 0))
        except (TypeError, ValueError):
            raise ServiceError("The number of questions must be a number.") from None
        if not 1 <= count <= MAX_QUESTIONS:
            raise ServiceError(f"Each rule can ask for 1 to {MAX_QUESTIONS} questions.")
        topic = _clean_text(rule.get("topic"), 80) or ANY
        difficulty = _enum(rule.get("difficulty"), DIFFICULTIES, ANY)
        rules.append({"topic": topic, "difficulty": difficulty, "count": count})
    if not rules:
        raise ServiceError("Add at least one picking rule.")
    return rules


def pick(store: Store, body: dict) -> dict:
    """Choose questions for each rule: least-used first, shuffled among equals, no AI."""
    rules = _rules(body.get("rules"))
    taken = {str(i) for i in body.get("exclude") or []}
    questions = store.list_bank()
    rng = random.Random()
    picked, shortfall = [], []
    for rule in rules:
        pool = [q for q in questions if q["id"] not in taken
                and (rule["topic"] == ANY or q["topic"].lower() == rule["topic"].lower())
                and (rule["difficulty"] == ANY or q["difficulty"] == rule["difficulty"])]
        rng.shuffle(pool)
        pool.sort(key=lambda q: q["used"])
        chosen = pool[:rule["count"]]
        taken |= {q["id"] for q in chosen}
        picked += [q["id"] for q in chosen]
        if len(chosen) < rule["count"]:
            shortfall.append({**rule, "missing": rule["count"] - len(chosen)})
    return {"picked": picked, "shortfall": shortfall}


def validate_assignment(params: Any) -> dict:
    if not isinstance(params, dict):
        raise ServiceError("Invalid request.")
    ids = params.get("question_ids") or []
    if not isinstance(ids, list) or len(ids) > MAX_QUESTIONS:
        raise ServiceError(f"Choose up to {MAX_QUESTIONS} questions.")
    top_up = _rules(params["top_up"]) if params.get("top_up") else []
    if not ids and not top_up:
        raise ServiceError("Choose at least one question from the bank.")
    if len(ids) + sum(r["count"] for r in top_up) > MAX_QUESTIONS:
        raise ServiceError(f"An assignment can have up to {MAX_QUESTIONS} questions.")
    if top_up and not params.get("textbook_id"):
        raise ServiceError("Choose a textbook so the missing questions can be written from it.")
    return {"question_ids": [str(i) for i in ids], "top_up": top_up,
            "textbook_id": params.get("textbook_id") or None,
            "title": _clean_text(params.get("title"), 160)}


def build_assignment(svc: Services, params: dict, progress: Progress) -> dict:
    """A new homework result from bank questions, optionally topped up with new ones."""
    progress(5, "Collecting questions from the bank")
    questions = [svc.store.get_bank_question(i) for i in params["question_ids"]]
    if not all(questions):
        raise ServiceError("Some of those questions were deleted from the bank. Pick again.")
    items = []
    for number, q in enumerate(questions, start=1):
        items.append({
            "id": f"q{number}", "original": q["text"], "type": "question", "flagged": False,
            "verdict": "keep", "reason": "", "replacement": "", "difficulty": q["difficulty"],
            "marks": q["marks"], "topics": [q["topic"]] if q["topic"] else [],
            "question_type": q["question_type"], "options": q["options"], "sources": q["sources"],
            "answer": q["answer"], "decision": "accepted", "edited": False, "bank_id": q["id"],
        })
    topics = list(dict.fromkeys(q["topic"] for q in questions if q["topic"]))

    textbook = svc._document(params["textbook_id"], "textbook") if params.get("textbook_id") else None
    if not textbook:
        used = Counter(q["textbook_id"] for q in questions if q.get("textbook_id"))
        for textbook_id, _ in used.most_common():
            textbook = svc.store.get_document(textbook_id)
            if textbook:
                break
    analysis = None
    for number, rule in enumerate(params["top_up"], start=1):
        span = (10 + 80 * (number - 1) // len(params["top_up"]), 10 + 80 * number // len(params["top_up"]))
        progress(span[0], f"Writing questions the bank doesn't have ({number} of {len(params['top_up'])})")
        focus = f"Every question must be on the topic: {rule['topic']}." if rule["topic"] != ANY else ""
        written, book_topics, analysis = svc.write_questions(
            textbook, None, count=rule["count"],
            difficulty=rule["difficulty"] if rule["difficulty"] != ANY else "mixed",
            kinds=[], instructions=focus, total_marks=None, progress=progress,
            avoid=tuple(i["original"] for i in items), first_id=len(items) + 1, pct=span)
        for item in written:
            item["added"] = True
            if rule["topic"] != ANY:
                item["topics"] = [rule["topic"]]
        items += written
        topics += [t for t in ([rule["topic"]] if rule["topic"] != ANY else book_topics) if t not in topics]
    if not items:
        raise ServiceError("Nothing to put in the assignment. Please try again.")

    svc.store.mark_bank_used([q["id"] for q in questions])
    progress(95, "Preparing your review")
    title = params.get("title") or f"From the bank ({len(items)} questions)"
    return {"result_id": svc.store.add_result("homework_bank", title, {
        "items": items, "topics": topics, "analysis": analysis,
        "documents": {"textbook": textbook["name"] if textbook else None, "notes": None},
        "textbook_id": textbook["id"] if textbook else None, "notes_id": None,
    })}
