"""Agentic features built on LangGraph: the teacher assistant, the assignment planner and grading
second opinions. They read through tools and propose; only the teacher's approval saves."""
from __future__ import annotations

import sqlite3
import threading
from functools import wraps
from typing import Any, Callable

from ..ai import AIError
from ..hybrid import HybridSearch
from ..services import ServiceError, _clean_text
from . import assistant, planner, second_opinion
from .models import friendly
from .tools import ToolContext

Progress = Callable[[int, str], None]


def _agent_job(fn):
    """Turn LangChain and Gemini errors into the app's friendly ones."""
    @wraps(fn)
    def run(self: "Agents", *args: Any, **kwargs: Any):
        if self.model is None:
            raise AIError("auth", "No AI is set up. Add GEMINI_API_KEY, or LLM_PROVIDER=ollama with "
                                  "OLLAMA_BASE_URL, to your .env file and restart DocuMentor.")
        try:
            return fn(self, *args, **kwargs)
        except (AIError, ServiceError):
            raise
        except Exception as exc:
            raise friendly(exc, getattr(self.model, "model", "")) from exc
    return run


class Agents:
    def __init__(self, services: Any, model: Any, embeddings: Any, settings: Any):
        from langgraph.checkpoint.sqlite import SqliteSaver

        self.svc = services
        self.store = services.store
        self.model = model
        self.settings = settings
        own_gpu = settings.provider == "ollama"  # no free-tier limit to stay under
        self.search = HybridSearch(self.store, embeddings, settings.active_embedding_model,
                                   100_000 if own_gpu else settings.embeds_per_minute)
        connection = sqlite3.connect(settings.data_dir / "agents.sqlite3", check_same_thread=False)
        self.checkpointer = SqliteSaver(connection)
        self.checkpointer.setup()
        self._locks: dict[str, threading.Lock] = {}

    def _lock(self, thread_id: str) -> threading.Lock:
        return self._locks.setdefault(thread_id, threading.Lock())

    def context(self, document_ids: list[str] | None = None, roles: set[str] | None = None) -> ToolContext:
        return ToolContext(self.store, self.search, document_ids, roles)

    # ---------- indexing for meaning search (no model needed for keyword fallback) ----------
    def index_document(self, params: dict, progress: Progress) -> dict:
        document = self.store.get_document(params["document_id"])
        if not document:
            raise ServiceError("That document no longer exists.")
        try:
            return self.search.index(document, progress)
        except Exception as exc:
            raise friendly(exc, self.settings.active_embedding_model) from exc

    # ---------- teacher assistant ----------
    @_agent_job
    def ask(self, params: dict, progress: Progress) -> dict:
        thread_id = params["thread_id"]
        with self._lock(thread_id):
            graph = assistant.build(self.model, self.context(), self.checkpointer, self.settings.agent_max_steps)
            assistant.ask(graph, thread_id, params["question"], progress)
            self.store.update_thread(thread_id, status="ready")
        return {"thread_id": thread_id}

    def assistant_view(self, thread: dict) -> dict:
        graph = assistant.build(_NoModel(), self.context(), self.checkpointer, 0)
        return {**thread, "messages": assistant.transcript(graph, thread["id"])}

    # ---------- assignment planner ----------
    def _planner(self):
        return planner.build(self.model, self.svc, self.search, self.checkpointer)

    @_agent_job
    def plan(self, params: dict, progress: Progress) -> dict:
        thread_id = params["thread_id"]
        with self._lock(thread_id):
            shown = planner.run(self._planner(), thread_id, {"request": params["request"],
                                                             "textbook_id": params.get("textbook_id")}, progress)
            self.store.update_thread(thread_id, status=shown["status"])
        return {"thread_id": thread_id, "status": shown["status"]}

    @_agent_job
    def resume_plan(self, params: dict, progress: Progress) -> dict:
        from langgraph.types import Command

        thread_id = params["thread_id"]
        with self._lock(thread_id):
            graph = self._planner()
            if planner.snapshot(graph, thread_id)["status"] != "review":
                raise ServiceError("This plan isn't waiting for your review any more.")
            shown = planner.run(graph, thread_id, Command(resume=params["decision"]), progress)
            self.store.update_thread(thread_id, status=shown["status"],
                                     data={"result_id": shown["result_id"]} if shown["result_id"] else None)
        return {"thread_id": thread_id, "status": shown["status"], "result_id": shown["result_id"]}

    def planner_view(self, thread: dict) -> dict:
        graph = planner.build(_NoModel(), self.svc, self.search, self.checkpointer)
        return {**thread, **planner.snapshot(graph, thread["id"])}

    # ---------- grading second opinion ----------
    @_agent_job
    def second_opinion(self, params: dict, progress: Progress) -> dict:
        # Only the textbook and notes are an authority on what's right; a homework sheet isn't.
        return second_opinion.review(self.model, lambda: self.context(roles={"textbook", "notes"}),
                                     self.store, params, progress)

    # ---------- threads ----------
    def view(self, thread: dict) -> dict:
        return self.assistant_view(thread) if thread["kind"] == "assistant" else self.planner_view(thread)

    def delete(self, thread_id: str) -> bool:
        self.checkpointer.delete_thread(thread_id)
        return self.store.delete_thread(thread_id)

    @staticmethod
    def title(text: str) -> str:
        text = " ".join(_clean_text(text, 200).split())
        return text[:77] + "…" if len(text) > 80 else text


class _NoModel:
    """Lets a graph be built just to read its saved state."""

    def bind_tools(self, tools: Any) -> "_NoModel":
        return self

    def with_structured_output(self, schema: Any) -> "_NoModel":
        return self

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise AIError("auth", "No Gemini API key is set.")
