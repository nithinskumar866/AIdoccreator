"""The assignment planner: a LangGraph workflow that drafts an assignment and waits for approval.

    understand -> gather -> select -> write -> check --(problems, < 2 tries)--> select
                                                    \\-> review (pauses for the teacher)
    review: approve -> save -> END · ask for changes -> select · cancel -> END

The model makes the judgement calls (reading the request, choosing questions, writing new ones).
Code does the counting and checking, and nothing is saved until the teacher approves."""
from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from ..bank import HOMEWORK_TYPES, fingerprint
from ..services import (DIFFICULTIES, MAX_QUESTIONS, QUESTION_TYPES, Data, ServiceError, _clean_text,
                        _marks, _prose, final_items, strip_number)
from ..store import Store
from .models import AGENT_RULES

MAX_REVISIONS = 2
MAX_CANDIDATES = 60


# ---------- what the model returns ----------
class Spec(BaseModel):
    """The teacher's request, made precise."""
    title: str = Field(description="A short title for the assignment")
    total_marks: Optional[int] = Field(None, description="Total marks asked for, if any")
    question_count: Optional[int] = Field(None, description="Number of questions asked for, if any")
    topics: list[str] = Field(default_factory=list, description="Topics to cover; empty means any")
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"
    question_types: list[str] = Field(default_factory=list)
    avoid_recent: bool = Field(False, description="True if the teacher wants to avoid recently used questions")
    notes: str = Field("", description="Any other requirement, in a sentence")


class NewQuestionPlan(BaseModel):
    topic: str
    difficulty: Literal["easy", "medium", "hard"]
    marks: int
    question_type: str = "short answer"
    focus: str = Field("", description="What the question should test")


class Selection(BaseModel):
    use_bank_ids: list[str] = Field(default_factory=list, description="Ids of bank questions to use")
    write_new: list[NewQuestionPlan] = Field(default_factory=list, description="Questions to write")
    reasoning: str = Field("", description="One short sentence on the choice, for the teacher")


class NewQuestion(BaseModel):
    text: str
    options: list[str] = Field(default_factory=list)
    answer: str
    topic: str
    difficulty: Literal["easy", "medium", "hard"]
    marks: int
    question_type: str = "short answer"
    source_ids: list[str] = Field(default_factory=list)


class NewQuestions(BaseModel):
    questions: list[NewQuestion]


class State(TypedDict, total=False):
    request: str
    textbook_id: Optional[str]
    spec: dict
    candidates: list[dict]
    recent: list[str]
    selection: dict
    items: list[dict]
    problems: list[str]
    revisions: int
    feedback: str
    log: list[dict]
    decision: dict
    status: str
    result_id: Optional[str]


def _log(state: State, step: str, detail: str) -> list[dict]:
    return (state.get("log") or []) + [{"step": step, "detail": detail}]


def build(model: Any, svc: Any, search: Any, checkpointer: Any):
    store: Store = svc.store

    def structured(schema: type[BaseModel], system: str, prompt: str) -> BaseModel:
        return model.with_structured_output(schema).invoke(
            [("system", system + "\n\n" + AGENT_RULES), ("human", prompt)])

    # ----- nodes -----
    def understand(state: State) -> dict:
        topics = sorted({q["topic"] for q in store.list_bank() if q["topic"]})
        data = Data()
        spec = structured(Spec, "You turn a teacher's request for an assignment into a precise "
                                "specification. Prefer topic names from KNOWN TOPICS when they match.",
                          data.block("KNOWN TOPICS", json.dumps(topics)) + "\n\n"
                          + data.block("TEACHER REQUEST", state["request"]))
        spec_d = spec.model_dump()
        spec_d["difficulty"] = spec_d["difficulty"] if spec_d["difficulty"] in DIFFICULTIES + ["mixed"] else "mixed"
        parts = [f"{spec_d['question_count']} questions" if spec_d["question_count"] else None,
                 f"{spec_d['total_marks']} marks" if spec_d["total_marks"] else None,
                 ", ".join(spec_d["topics"]) or "any topic", spec_d["difficulty"]]
        return {"spec": spec_d, "revisions": 0, "status": "working",
                "log": _log(state, "Understood the request", " · ".join(p for p in parts if p))}

    def gather(state: State) -> dict:
        spec = state["spec"]
        recent: set[str] = set()
        if spec.get("avoid_recent"):
            homework = [r for r in store.list_results() if r["type"] in HOMEWORK_TYPES][:3]
            for r in homework:
                full = store.get_result(r["id"])
                for item in final_items(full["data"]):
                    if item["type"] == "question":
                        recent.add(fingerprint(strip_number(item["text"]), item.get("options")))
        wanted = [t.lower() for t in spec.get("topics") or []]
        bank = store.list_bank()
        matches = lambda q: not wanted or any(w in (q["topic"] or "").lower() or (q["topic"] or "").lower() in w  # noqa: E731
                                              for w in wanted)
        ordered = sorted(bank, key=lambda q: (not matches(q), q["used"]))
        candidates = [{"id": q["id"], "question": q["text"], "options": q["options"], "topic": q["topic"],
                       "difficulty": q["difficulty"], "marks": q["marks"], "times_used": q["used"],
                       "recently_used": fingerprint(q["text"], q["options"]) in recent}
                      for q in ordered[:MAX_CANDIDATES]]
        usable = sum(1 for c in candidates if not c["recently_used"] and matches(c))
        return {"candidates": candidates, "recent": sorted(recent),
                "log": _log(state, "Searched the question bank",
                            f"{len(bank)} saved questions, {usable} on the requested topics"
                            + (f", {len(recent)} recent questions to avoid" if recent else ""))}

    def select(state: State) -> dict:
        data = Data()
        parts = [data.block("SPECIFICATION", json.dumps(state["spec"], ensure_ascii=False)),
                 data.block("BANK QUESTIONS", json.dumps(state["candidates"], ensure_ascii=False))]
        if state.get("items"):
            parts.append(data.block("CURRENT DRAFT", json.dumps(
                [{"bank_id": i.get("bank_id"), "question": i["original"], "topic": (i["topics"] or [""])[0],
                  "difficulty": i["difficulty"], "marks": i["marks"]} for i in state["items"]], ensure_ascii=False)))
        if state.get("problems"):
            parts.append(data.block("PROBLEMS TO FIX", json.dumps(state["problems"])))
        if state.get("feedback"):
            parts.append(data.block("TEACHER FEEDBACK", state["feedback"]))
        choice = structured(Selection, (
            "You plan an assignment for a teacher. Prefer good bank questions, and only plan new "
            "questions for gaps the bank can't fill. Never choose bank questions marked "
            "recently_used if the specification says to avoid recent questions. Match the requested "
            "number of questions, total marks, topics and difficulty as closely as you can. When "
            "fixing problems or feedback, change only what is needed."), "\n\n".join(parts))
        known = {c["id"] for c in state["candidates"]}
        if state["spec"].get("avoid_recent"):
            known -= {c["id"] for c in state["candidates"] if c["recently_used"]}
        ids = list(dict.fromkeys(i for i in choice.use_bank_ids if i in known))
        new = [p.model_dump() for p in choice.write_new][:MAX_QUESTIONS]
        why = summary(choice.reasoning)
        return {"selection": {"bank_ids": ids, "write_new": new, "reasoning": why},
                "log": _log(state, "Chose questions" if not state.get("items") else "Revised the choice",
                            f"{len(ids)} from the bank, {len(new)} to write." + (f" {why}" if why else ""))}

    def write(state: State) -> dict:
        selection = state["selection"]
        items = []
        for bank_id in selection["bank_ids"]:
            q = store.get_bank_question(bank_id)
            if q:
                items.append({"original": q["text"], "options": q["options"], "answer": q["answer"],
                              "topics": [q["topic"]] if q["topic"] else [], "difficulty": q["difficulty"],
                              "marks": q["marks"], "question_type": q["question_type"], "sources": q["sources"],
                              "bank_id": q["id"], "added": False})
        plans = selection["write_new"]
        detail = "Nothing new needed"
        if plans:
            textbook = _textbook(store, state.get("textbook_id"))
            if not textbook:
                return {"items": items, "log": _log(state, "Couldn't write new questions",
                                                    "There's no textbook in the library to write from.")}
            queries = [f"{p['topic']} {p['focus']}".strip() for p in plans]
            passages, lookup = [], {}
            for query in dict.fromkeys(queries):
                for hit in search.search(query, [textbook], top=3):
                    pid = f"P{len(lookup) + 1}"
                    if hit["text"] in (p["text"] for p in passages):
                        continue
                    lookup[pid] = {"id": pid, "document": textbook["name"], "label": hit["label"],
                                   "excerpt": hit["text"][:400]}
                    passages.append({"id": pid, "label": hit["label"], "text": hit["text"]})
            data = Data()
            written = structured(NewQuestions, (
                "You write homework questions for a teacher using only the supplied passages. Write "
                "exactly one question per plan, matching its topic, difficulty, marks and type. Give a "
                "correct, concise answer and cite passage ids in source_ids. Write plain question "
                "text without numbering; put multiple-choice options in options."),
                data.passages("TEXTBOOK PASSAGES", passages) + "\n\n" + data.block(
                    "PLANS", json.dumps(plans, ensure_ascii=False))
                + "\n\n" + data.block("AVOID REPEATING", json.dumps([i["original"] for i in items], ensure_ascii=False)))
            for q in written.questions[:len(plans)]:
                text = strip_number(_clean_text(q.text))
                if not text:
                    continue
                items.append({"original": text, "options": [_clean_text(o, 400) for o in q.options if _clean_text(o)][:8],
                              "answer": _prose(q.answer), "topics": [_clean_text(q.topic, 80)] if q.topic else [],
                              "difficulty": q.difficulty, "marks": _marks(q.marks),
                              "question_type": _clean_text(q.question_type, 40),
                              "sources": [lookup[s] for s in dict.fromkeys(q.source_ids) if s in lookup],
                              "bank_id": None, "added": True})
            detail = f"Wrote {sum(1 for i in items if i['added'])} new questions from {textbook['name']}"
        for n, item in enumerate(items, start=1):
            item["id"] = f"q{n}"
        log = _log(state, "Wrote new questions" if plans else "Assembled the draft", detail)
        before = sum(i["marks"] or 1 for i in items)
        if balance_marks(items, state["spec"].get("total_marks")):
            log.append({"step": "Balanced the marks",
                        "detail": f"Changed marks from {before} to {state['spec']['total_marks']} in total"})
        return {"items": items, "log": log}

    def check(state: State) -> dict:
        spec, items = state["spec"], state["items"]
        problems = []
        total = sum(i["marks"] or 0 for i in items)
        if not items:
            problems.append("The draft has no questions.")
        if spec.get("question_count") and len(items) != spec["question_count"]:
            problems.append(f"The draft has {len(items)} questions; {spec['question_count']} were asked for.")
        target = spec.get("total_marks")
        if target and abs(total - target) > max(1, round(target * 0.1)):
            problems.append(f"The draft is worth {total} marks; {target} were asked for.")
        covered = " ".join(t.lower() for i in items for t in i["topics"])
        for topic in spec.get("topics") or []:
            if topic.lower() not in covered:
                problems.append(f"No question covers {topic}.")
        if spec.get("difficulty") in DIFFICULTIES and items:
            share = sum(1 for i in items if i["difficulty"] == spec["difficulty"]) / len(items)
            if share < 0.5:
                problems.append(f"Fewer than half the questions are {spec['difficulty']}.")
        seen = set()
        for item in items:
            key = fingerprint(item["original"], item["options"])
            if key in seen:
                problems.append(f"\"{item['original'][:60]}\" appears twice.")
            seen.add(key)
            if key in set(state.get("recent") or []) and spec.get("avoid_recent"):
                problems.append(f"\"{item['original'][:60]}\" was used recently.")
        for a, b in similar_pairs([i["original"] for i in items], search.embeddings):
            problems.append(f"Questions {a + 1} and {b + 1} test almost the same thing; make one of "
                            "them ask about something else.")
        detail = "No problems found" if not problems else "; ".join(problems)
        return {"problems": problems, "log": _log(state, "Checked the draft", detail)}

    def after_check(state: State) -> str:
        if state["problems"] and state.get("revisions", 0) < MAX_REVISIONS:
            return "revise"
        return "review"

    def revise(state: State) -> dict:
        return {"revisions": state.get("revisions", 0) + 1}

    def review(state: State) -> dict:
        decision = interrupt({"items": state["items"], "problems": state["problems"]})
        return {"decision": decision if isinstance(decision, dict) else {"action": "cancel"},
                "status": "working", "feedback": ""}

    def after_review(state: State) -> str:
        return {"approve": "save", "revise": "apply_feedback"}.get(state["decision"].get("action"), "cancel")

    def apply_feedback(state: State) -> dict:
        decision = state["decision"]
        remove = set(decision.get("remove") or [])
        kept = [i for i in state["items"] if i["id"] not in remove]
        feedback = _clean_text(decision.get("feedback"), 1500)
        return {"items": kept, "feedback": feedback, "revisions": 0,
                "log": _log(state, "Teacher asked for changes",
                            (feedback or "No comment") + (f" · removed {len(remove)}" if remove else ""))}

    def save(state: State) -> dict:
        remove = set(state["decision"].get("remove") or [])
        items = [i for i in state["items"] if i["id"] not in remove]
        if not items:
            raise ServiceError("Every question was removed, so there's nothing to save.")
        built = []
        for n, i in enumerate(items, start=1):
            built.append({"id": f"q{n}", "original": i["original"], "type": "question", "flagged": False,
                          "verdict": "keep", "reason": "", "replacement": "", "difficulty": i["difficulty"],
                          "marks": i["marks"], "topics": i["topics"], "question_type": i["question_type"],
                          "options": i["options"], "sources": i["sources"], "answer": i["answer"],
                          "decision": "accepted", "edited": False, "bank_id": i["bank_id"], "added": i["added"]})
        store.mark_bank_used([i["bank_id"] for i in items if i["bank_id"]])
        textbook = _textbook(store, state.get("textbook_id"))
        topics = list(dict.fromkeys(t for i in built for t in i["topics"]))
        result_id = store.add_result("homework_bank", _clean_text(state["spec"].get("title"), 160)
                                     or f"Planned assignment ({len(built)} questions)", {
            "items": built, "topics": topics, "analysis": None,
            "documents": {"textbook": textbook["name"] if textbook else None, "notes": None},
            "textbook_id": textbook["id"] if textbook else None, "notes_id": None,
            "planned_from": state["request"],
        })
        return {"status": "saved", "result_id": result_id,
                "log": _log(state, "Saved after your approval", f"{len(built)} questions")}

    def cancel(state: State) -> dict:
        return {"status": "cancelled", "log": _log(state, "Cancelled", "Nothing was saved")}

    graph = StateGraph(State)
    for name, fn in [("understand", understand), ("gather", gather), ("select", select), ("write", write),
                     ("check", check), ("revise", revise), ("review", review),
                     ("apply_feedback", apply_feedback), ("save", save), ("cancel", cancel)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "gather")
    graph.add_edge("gather", "select")
    graph.add_edge("select", "write")
    graph.add_edge("write", "check")
    graph.add_conditional_edges("check", after_check, {"revise": "revise", "review": "review"})
    graph.add_edge("revise", "select")
    graph.add_conditional_edges("review", after_review,
                                {"save": "save", "apply_feedback": "apply_feedback", "cancel": "cancel"})
    graph.add_edge("apply_feedback", "select")
    graph.add_edge("save", END)
    graph.add_edge("cancel", END)
    return graph.compile(checkpointer=checkpointer)


def summary(text: str, limit: int = 220) -> str:
    """The first sentence of the model's reasoning, without ids or working-out."""
    text = re.sub(r"\b[0-9a-f]{12,}\b", "", _prose(text, 1200))
    text = re.sub(r"\s+", " ", text).strip()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "…"


def balance_marks(items: list[dict], target: Optional[int]) -> bool:
    """Make marks add up to the requested total, one mark at a time, newly written questions
    first. Each question keeps at least 1 mark. Returns True if anything changed."""
    for item in items:
        item["marks"] = item["marks"] or 1
    if not target or not items:
        return False
    diff = target - sum(i["marks"] for i in items)
    order = [i for i in items if i["added"]] + [i for i in items if not i["added"]]
    changed = False
    while diff:
        moved = False
        for item in order:
            if diff > 0:
                item["marks"] += 1
                diff -= 1
            elif item["marks"] > 1:
                item["marks"] -= 1
                diff += 1
            else:
                continue
            moved = changed = True
            if not diff:
                break
        if not moved:  # every question is already at 1 mark
            break
    return changed


def similar_pairs(texts: list[str], embeddings: Any = None, words: float = 0.6,
                  meaning: float = 0.94) -> list[tuple[int, int]]:
    """Pairs of questions that are near-duplicates, by shared words or, when available, meaning.

    Measured on real questions with gemini-embedding-001: rewordings of one question scored
    0.941 to 0.96, while different questions on related topics scored up to 0.938."""
    from ..retrieval import tokenize

    bags = [set(tokenize(t)) for t in texts]
    vectors = None
    if embeddings is not None and len(texts) > 1:
        try:
            vectors = [_unit(v) for v in embeddings.embed_documents(texts)]
        except Exception:  # the word check still runs
            vectors = None
    pairs = []
    for a in range(len(texts)):
        for b in range(a + 1, len(texts)):
            union = bags[a] | bags[b]
            overlap = len(bags[a] & bags[b]) / len(union) if union else 0
            close = vectors is not None and sum(x * y for x, y in zip(vectors[a], vectors[b])) >= meaning
            if overlap >= words or close:
                pairs.append((a, b))
    return pairs


def _unit(vector: list[float]) -> list[float]:
    norm = sum(x * x for x in vector) ** 0.5 or 1.0
    return [x / norm for x in vector]


def _textbook(store: Store, textbook_id: Optional[str]) -> Optional[dict]:
    if textbook_id:
        return store.get_document(textbook_id)
    books = [d for d in store.list_documents() if d["role"] == "textbook"]
    return store.get_document(books[0]["id"]) if books else None


STEP_MESSAGES = {
    "understand": "Reading your request", "gather": "Searching the question bank",
    "select": "Choosing questions", "write": "Writing questions the bank doesn't have",
    "check": "Checking marks, topics and duplicates", "revise": "Fixing problems it found",
    "apply_feedback": "Applying your feedback", "save": "Saving", "cancel": "Cancelling",
}


def run(graph: Any, thread_id: str, payload: Any, progress) -> dict:
    """Run until the draft is ready for review, or the plan is saved or cancelled."""
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    pct = 5
    for update in graph.stream(payload, config, stream_mode="updates"):
        for node in update:
            if node in STEP_MESSAGES:
                pct = min(pct + 9, 92)
                progress(pct, STEP_MESSAGES[node])
    return snapshot(graph, thread_id)


def snapshot(graph: Any, thread_id: str) -> dict:
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    values = dict(state.values or {}) if state else {}
    waiting = bool(state and state.next and "review" in state.next)
    items = values.get("items") or []
    return {
        "status": "review" if waiting else values.get("status", "new"),
        "request": values.get("request", ""), "spec": values.get("spec"),
        "items": items, "problems": values.get("problems") or [],
        "total_marks": sum(i["marks"] or 0 for i in items), "log": values.get("log") or [],
        "result_id": values.get("result_id"),
    }


def validate(params: Any) -> dict:
    if not isinstance(params, dict):
        raise ServiceError("Invalid request.")
    request = _clean_text(params.get("request"), 2000)
    if len(request) < 8:
        raise ServiceError("Describe the assignment you want, for example \"a 20-mark quiz on clustering\".")
    return {"request": request, "textbook_id": params.get("textbook_id") or None}


def validate_resume(params: Any) -> dict:
    if not isinstance(params, dict) or params.get("action") not in {"approve", "revise", "cancel"}:
        raise ServiceError("Choose approve, ask for changes, or cancel.")
    remove = [str(i) for i in params.get("remove") or []][:MAX_QUESTIONS]
    feedback = _clean_text(params.get("feedback"), 1500)
    if params["action"] == "revise" and not feedback and not remove:
        raise ServiceError("Say what to change, or untick the questions to drop.")
    return {"action": params["action"], "feedback": feedback, "remove": remove}


__all__ = ["build", "run", "snapshot", "validate", "validate_resume", "QUESTION_TYPES"]
