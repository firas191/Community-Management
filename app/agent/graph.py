"""The analyst agent's think/act loop, orchestrated with LangGraph (Week 7).

The graph is deliberately small: a ``think`` node that asks the model what to do,
an ``act`` node that runs the tools it asked for, and a ``finalize`` node that
forces a written answer once the tool budget is spent.

    START -> think -> (tool calls? and budget left?) -> act -> think -> ...
                   -> (no tool calls) -> END
                   -> (budget spent) -> finalize -> END

Two things are kept out of the graph on purpose. The node functions below are
plain functions over a state dict, so they are unit-testable without LangGraph
installed and without a network (the gateway is injected). And LangGraph itself is
imported lazily inside ``build_graph``, so importing this module is free and the
app still boots when the ``agent`` extra is absent.

The tool budget (6 calls, per the data dictionary) is what keeps a question
bounded in both cost and latency.
"""

from __future__ import annotations

import json
from typing import Any

from app.agent import prompts, tools
from app.core.logging import get_logger
from app.llm.gateway import LLMGateway, LLMResult

log = get_logger("agent.graph")

MAX_TOOL_CALLS = 6  # brief data dictionary: tool_call_count is capped at 6
MAX_TRACE_CHARS = 2000  # per-tool result stored in the trace, truncated for sanity


class AgentUnavailableError(RuntimeError):
    """The agent extra (langgraph) is not installed. Mapped to HTTP 503 with a hint."""


def _truncate(payload: Any) -> tuple[str, bool]:
    raw = json.dumps(payload, default=str, ensure_ascii=False)
    if len(raw) <= MAX_TRACE_CHARS:
        return raw, False
    return raw[:MAX_TRACE_CHARS] + "...", True


def initial_state(question: str, account_id: int | None, history: list[dict] | None = None) -> dict:
    return {
        "messages": prompts.build_messages(question, account_id, history),
        "trace": [],
        "tool_calls_used": 0,
        "answer": "",
        "pending": [],
        "llm_results": [],
    }


def think(state: dict, *, gateway: LLMGateway, with_tools: bool = True) -> dict:
    """Ask the model for the next step: either tool calls or a final answer."""
    result: LLMResult = gateway.complete(
        state["messages"],
        purpose="agent",
        max_tokens=900,
        temperature=0.2,  # analysis, not creative writing
        tools=tools.tool_schemas() if with_tools else None,
    )
    state["llm_results"].append(result)

    if result.tool_calls:
        state["messages"].append(
            {
                "role": "assistant",
                "content": result.text or None,
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in result.tool_calls
                ],
            }
        )
        state["pending"] = list(result.tool_calls)
    else:
        state["messages"].append({"role": "assistant", "content": result.text})
        state["answer"] = result.text
        state["pending"] = []
    return state


def act(state: dict, *, db) -> dict:
    """Run every pending tool call and feed the results back as tool messages."""
    for tc in state["pending"]:
        payload = tools.run_tool(db, tc.name, tc.arguments, state.get("default_account"))
        raw, truncated = _truncate(payload)
        state["messages"].append(
            {"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": raw}
        )
        state["trace"].append(
            {
                "step": state["tool_calls_used"] + 1,
                "tool": tc.name,
                "arguments": tc.arguments,
                "ok": "error" not in payload,
                "result": raw,
                "truncated": truncated,
            }
        )
        state["tool_calls_used"] += 1
        log.info("agent_tool_called", tool=tc.name, ok="error" not in payload)
    state["pending"] = []
    return state


def finalize(state: dict, *, gateway: LLMGateway) -> dict:
    """Tool budget spent: ask for a written answer from what was already gathered."""
    state["messages"].append(
        {
            "role": "user",
            "content": (
                "You have used your tool budget. Answer now using only the tool results above. "
                "If something could not be determined, say so plainly."
            ),
        }
    )
    return think(state, gateway=gateway, with_tools=False)


def next_step(state: dict) -> str:
    """Routing: run the tools, stop for budget, or finish."""
    if state["pending"]:
        return "act" if state["tool_calls_used"] < MAX_TOOL_CALLS else "finalize"
    return "end"


def build_graph(db, gateway: LLMGateway):
    """Compile the LangGraph state machine. Raises AgentUnavailableError without langgraph."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise AgentUnavailableError(
            "langgraph is not installed. Install the agent extra: pip install -e '.[agent]'."
        ) from exc

    builder = StateGraph(dict)
    builder.add_node("think", lambda s: think(s, gateway=gateway))
    builder.add_node("act", lambda s: act(s, db=db))
    builder.add_node("finalize", lambda s: finalize(s, gateway=gateway))
    builder.add_edge(START, "think")
    builder.add_conditional_edges("think", next_step, {"act": "act", "finalize": "finalize", "end": END})
    builder.add_edge("act", "think")
    builder.add_edge("finalize", END)
    return builder.compile()


def run_agent(
    db,
    gateway: LLMGateway,
    question: str,
    *,
    account_id: int | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Answer a question with tools, returning the answer plus the full tool trace."""
    state = initial_state(question, account_id, history)
    state["default_account"] = account_id
    graph = build_graph(db, gateway)
    # recursion_limit bounds graph steps as a second belt to the tool-call budget.
    final = graph.invoke(state, {"recursion_limit": 2 * MAX_TOOL_CALLS + 4})

    results: list[LLMResult] = final.get("llm_results", [])
    return {
        "answer": final.get("answer", ""),
        "trace": final.get("trace", []),
        "tool_call_count": final.get("tool_calls_used", 0),
        "llm_results": results,
        "provider": results[-1].provider if results else None,
        "model": results[-1].model if results else None,
        "latency_ms": sum(r.latency_ms for r in results),
    }
