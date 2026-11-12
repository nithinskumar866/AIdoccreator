"""Scripted LangChain models, so agent tests are fast, repeatable and spend no quota."""
from __future__ import annotations

import hashlib
import itertools
import math
import re
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda


class FakeAgentModel(BaseChatModel):
    """`turns` answers tool-calling calls in order; `structured` answers with_structured_output
    by schema name. Every prompt is recorded in `calls`."""

    turns: list = []
    structured: dict = {}
    calls: list = []
    model: str = "fake-agent"

    @property
    def _llm_type(self) -> str:
        return "fake-agent"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append({"messages": messages, "tools": kwargs.get("tools")})
        reply = self.turns.pop(0) if self.turns else AIMessage("Done.")
        if callable(reply):
            reply = reply(messages)
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=[t.name for t in tools])

    def with_structured_output(self, schema, **kwargs):
        def answer(value: Any):
            self.calls.append({"messages": value, "schema": schema.__name__})
            scripted = self.structured[schema.__name__]
            if isinstance(scripted, list):
                scripted = scripted.pop(0) if len(scripted) > 1 else scripted[0]
            return schema(**(scripted(value) if callable(scripted) else scripted))
        return RunnableLambda(answer)


_CALLS = itertools.count(1)


def tool_call(name: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_CALLS)}"}])


CONCEPTS = [
    {"cluster", "clustering", "group", "grouping", "groups", "kmeans", "similar"},
    {"label", "labelled", "labeled", "supervised", "regression", "answers"},
    {"pca", "dimension", "dimensions", "component", "reduce", "reducing"},
]


class FakeEmbeddings(Embeddings):
    """Words in the same concept land on the same axis, so meaning search can be tested."""

    def __init__(self, fail_after: int | None = None):
        self.texts = 0
        self.fail_after = fail_after

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * 12
        for word in re.findall(r"[a-z]+", text.lower()):
            for axis, words in enumerate(CONCEPTS):
                if word in words:
                    vector[axis] += 1.0
                    break
            else:
                vector[3 + int(hashlib.md5(word.encode()).hexdigest(), 16) % 9] += 0.05
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail_after is not None and self.texts + len(texts) > self.fail_after:
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota per minute")
        self.texts += len(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
