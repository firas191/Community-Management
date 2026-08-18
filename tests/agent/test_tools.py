"""Tool registry: schemas, argument handling, and failure behavior (Week 7). Pure.

These tests use a dummy session because the point is the registry's contract
(validation, clamping, never raising), not the analytics functions themselves,
which are already covered by their own tests.
"""

from __future__ import annotations

from app.agent import tools


def test_schemas_are_well_formed_function_specs():
    schemas = tools.tool_schemas()
    assert len(schemas) == len(tools.TOOLS)
    names = {s["function"]["name"] for s in schemas}
    assert {"get_kpi_overview", "get_sentiment_summary", "recommend_best_time", "list_accounts"} <= names
    for s in schemas:
        assert s["type"] == "function"
        fn = s["function"]
        assert fn["description"]  # the model picks tools by description
        assert fn["parameters"]["type"] == "object"


def test_unknown_tool_returns_error_not_raise():
    out = tools.run_tool(None, "definitely_not_a_tool", "{}")
    assert "error" in out and "Unknown tool" in out["error"]


def test_bad_json_arguments_return_error():
    out = tools.run_tool(None, "get_kpi_overview", "{not json")
    assert "error" in out and "not valid JSON" in out["error"]


def test_tool_exception_is_captured_as_error():
    # No db session, so the underlying call raises; the registry must catch it.
    out = tools.run_tool(None, "get_kpi_overview", '{"account_id": 1}')
    assert "error" in out


def test_missing_account_id_is_reported():
    out = tools.run_tool(None, "get_kpi_overview", "{}")
    assert "error" in out and "account_id" in out["error"]


def test_window_validation_falls_back_to_default():
    assert tools._window("30d") == "30d"
    assert tools._window("12w") == "12w"
    assert tools._window("garbage") == "30d"  # invalid -> default, never an exception
    assert tools._window(None, "90d") == "90d"


def test_int_coercion():
    assert tools._int("5", 1) == 5
    assert tools._int(None, 3) == 3
    assert tools._int("abc", 7) == 7


def test_limits_are_clamped_in_schema_contract():
    # The registry caps list sizes so a model cannot request an unbounded result.
    assert tools.MAX_LIMIT == 20
