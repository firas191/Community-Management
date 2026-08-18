"""Agent loop nodes and routing (Week 7). No LangGraph, no network, no DB.

The node functions are plain functions over a state dict precisely so the loop's
behavior (when it calls tools, when it stops, what it records) can be pinned down
without compiling the graph or reaching a provider.
"""

from __future__ import annotations

from app.agent import graph, tools
from app.llm.gateway import LLMResult, ToolCall


class FakeGateway:
    """Returns queued results in order, and records the calls it received."""

    def __init__(self, *results: LLMResult):
        self.queue = list(results)
        self.calls: list[dict] = []

    def complete(self, messages, *, purpose="general", max_tokens=800, temperature=0.7, use_cache=True, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools, "purpose": purpose})
        return self.queue.pop(0)


def _result(text="", tool_calls=None) -> LLMResult:
    return LLMResult(
        text=text, provider="groq", model="groq/a", latency_ms=10, fallback_depth=0,
        tool_calls=tool_calls or [],
    )


def test_initial_state_has_system_and_question():
    st = graph.initial_state("How did we do?", 1)
    assert st["messages"][0]["role"] == "system"
    assert "account_id 1" in st["messages"][0]["content"]
    assert st["messages"][-1] == {"role": "user", "content": "How did we do?"}
    assert st["tool_calls_used"] == 0 and st["trace"] == []


def test_think_without_tool_calls_produces_the_answer():
    st = graph.initial_state("q", None)
    gw = FakeGateway(_result(text="Engagement rose 12%."))
    st = graph.think(st, gateway=gw)
    assert st["answer"] == "Engagement rose 12%."
    assert st["pending"] == []
    assert st["messages"][-1] == {"role": "assistant", "content": "Engagement rose 12%."}
    # tools are offered to the model on a normal turn
    assert gw.calls[0]["tools"] is not None


def test_think_with_tool_calls_queues_them():
    st = graph.initial_state("q", None)
    tc = ToolCall(id="c1", name="get_kpi_overview", arguments='{"account_id": 1}')
    st = graph.think(st, gateway=FakeGateway(_result(tool_calls=[tc])))
    assert st["answer"] == ""
    assert [c.name for c in st["pending"]] == ["get_kpi_overview"]
    msg = st["messages"][-1]
    assert msg["role"] == "assistant"
    assert msg["tool_calls"][0]["function"]["name"] == "get_kpi_overview"


def test_act_runs_tools_and_records_the_trace(monkeypatch):
    monkeypatch.setattr(tools, "run_tool", lambda db, name, args, default=None: {"n_posts": 12})
    st = graph.initial_state("q", None)
    st["pending"] = [ToolCall(id="c1", name="get_kpi_overview", arguments="{}")]
    st = graph.act(st, db=None)

    assert st["tool_calls_used"] == 1
    assert st["pending"] == []
    tool_msg = st["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert "12" in tool_msg["content"]  # the result is fed back to the model
    step = st["trace"][0]
    assert step["tool"] == "get_kpi_overview" and step["ok"] is True and step["step"] == 1


def test_act_marks_failed_tools_in_the_trace(monkeypatch):
    monkeypatch.setattr(tools, "run_tool", lambda db, name, args, default=None: {"error": "boom"})
    st = graph.initial_state("q", None)
    st["pending"] = [ToolCall(id="c1", name="get_kpi_overview", arguments="{}")]
    st = graph.act(st, db=None)
    assert st["trace"][0]["ok"] is False


def test_act_truncates_a_huge_result(monkeypatch):
    monkeypatch.setattr(tools, "run_tool", lambda db, name, args, default=None: {"blob": "x" * 5000})
    st = graph.initial_state("q", None)
    st["pending"] = [ToolCall(id="c1", name="get_kpi_timeseries", arguments="{}")]
    st = graph.act(st, db=None)
    assert st["trace"][0]["truncated"] is True
    assert len(st["trace"][0]["result"]) <= graph.MAX_TRACE_CHARS + 3


def test_routing_rules():
    st = graph.initial_state("q", None)
    st["pending"] = []
    assert graph.next_step(st) == "end"

    st["pending"] = [ToolCall("c1", "get_kpi_overview", "{}")]
    st["tool_calls_used"] = 0
    assert graph.next_step(st) == "act"

    st["tool_calls_used"] = graph.MAX_TOOL_CALLS
    assert graph.next_step(st) == "finalize"  # budget spent -> stop calling tools


def test_finalize_asks_for_an_answer_without_tools():
    st = graph.initial_state("q", None)
    gw = FakeGateway(_result(text="Final answer from gathered data."))
    st = graph.finalize(st, gateway=gw)
    assert st["answer"] == "Final answer from gathered data."
    assert gw.calls[0]["tools"] is None  # no tools offered on the closing turn


def test_tool_budget_matches_the_data_dictionary():
    assert graph.MAX_TOOL_CALLS == 6
