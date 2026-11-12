"""The teacher assistant: a tool-calling agent built as a LangGraph state graph.

    START -> agent -> (tool calls?) -> tools -> agent -> ... -> END

The agent decides which read-only tool to call, reads the result and either searches again or
answers. A step limit stops runaway loops, and the conversation is kept by the checkpointer so
follow-up questions work."""
from __future__ import annotations

from typing import Annotated, Any, Callable, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .models import AGENT_RULES, text_of
from .tools import FRIENDLY_TOOL_NAMES, ToolContext, make_tools

SYSTEM = (
    "You are DocuMentor's teaching assistant. You help a teacher with their own textbooks, notes, "
    "homework, question bank and gradings, using the tools to look things up. Look things up "
    "rather than guessing. If a search misses, try other words or another tool before giving up. "
    "When you use document passages, name the source in brackets, like [Textbook.docx · "
    "Supervised Learning]. Only cite documents, never tool names or ids. If the teacher's "
    "material doesn't contain the answer, say so plainly. "
    "Answer in clear Markdown and keep it short.\n\n" + AGENT_RULES
)
HISTORY_TURNS = 4


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    steps: int


def _recent(messages: list[AnyMessage]) -> list[AnyMessage]:
    """The last few turns, starting at a question so no tool reply is left without its call."""
    starts = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    return messages[starts[-HISTORY_TURNS]:] if len(starts) > HISTORY_TURNS else messages


def build(model: Any, ctx: ToolContext, checkpointer: Any, max_steps: int):
    tools = make_tools(ctx)
    with_tools = model.bind_tools(tools)

    def agent(state: State) -> dict:
        messages = [SystemMessage(SYSTEM)] + _recent(state["messages"])
        if state.get("steps", 0) >= max_steps:  # out of steps: answer with what was found
            messages.append(HumanMessage("Stop using tools now and answer with what you found."))
            reply = model.invoke(messages)
            if getattr(reply, "tool_calls", None) or not text_of(reply).strip():
                reply = AIMessage("I ran out of steps before finding a full answer. Try a narrower "
                                  "question, or name the document or homework to look at.")
        else:
            reply = with_tools.invoke(messages)
        return {"messages": [reply], "steps": state.get("steps", 0) + 1}

    def route(state: State) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else END

    graph = StateGraph(State)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


def describe_call(call: dict) -> str:
    args = ", ".join(f"{k}: {v}" for k, v in (call.get("args") or {}).items() if v not in ("", None))
    return FRIENDLY_TOOL_NAMES.get(call["name"], call["name"]) + (f" ({args})" if args else "")


def ask(graph: Any, thread_id: str, question: str, progress: Callable[[int, str], None]) -> None:
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}
    progress(10, "Thinking")
    pct = 10
    for update in graph.stream({"messages": [HumanMessage(question)], "steps": 0}, config,
                               stream_mode="updates"):
        for node, change in update.items():
            for message in (change or {}).get("messages", []):
                pct = min(pct + 12, 90)
                if isinstance(message, AIMessage) and message.tool_calls:
                    progress(pct, "; ".join(describe_call(c) for c in message.tool_calls))
                elif isinstance(message, ToolMessage):
                    progress(pct, "Reading the results")


def transcript(graph: Any, thread_id: str, sources: dict | None = None) -> list[dict]:
    """The conversation for the page: questions, answers, and the steps taken in between."""
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    messages = (state.values or {}).get("messages", []) if state else []
    turns: list[dict] = []
    steps: list[dict] = []
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    for message in messages:
        if isinstance(message, HumanMessage):
            turns.append({"role": "user", "content": text_of(message)})
            steps = []
        elif isinstance(message, AIMessage):
            for call in message.tool_calls:
                result = results.get(call["id"])
                preview = text_of(result).split("\n", 1)[-1][:500] if result else ""
                steps.append({"tool": call["name"], "label": describe_call(call), "result": preview})
            text = text_of(message).strip()
            if text and not message.tool_calls:
                turns.append({"role": "assistant", "content": text, "steps": steps})
                steps = []
    return turns
