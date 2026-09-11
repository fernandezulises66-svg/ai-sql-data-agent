"""Tests for the app.py terminal CLI, especially the --debug option.

These tests never call the real OpenAI API: app.run_data_agent is always
monkeypatched to a fake that returns a hand-built AgentAnswer, so
Runner.run_sync is never reached.
"""

import builtins
import sys

import pytest

import app
from agent.data_analyst_agent import AgentAnswer, AgentConfigError, SQLToolCallRecord


def _feed_inputs(monkeypatch, *inputs: str) -> None:
    """Make input() return each of inputs in order, like a scripted user."""
    iterator = iter(inputs)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(iterator))


@pytest.fixture(autouse=True)
def _default_test_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")


SAMPLE_TOOL_CALLS = [
    SQLToolCallRecord(
        query="SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "GROUP BY p.id ORDER BY revenue DESC LIMIT 1",
        success=True,
        execution_time_ms=2.4,
        row_count=1,
        truncated=False,
    )
]


# ---------------------------------------------------------------------------
# Debug mode formatting
# ---------------------------------------------------------------------------


def test_debug_mode_prints_sql_rows_and_timing(monkeypatch, capsys):
    _feed_inputs(monkeypatch, "Which product generated the most revenue?", "exit")
    monkeypatch.setattr(
        app,
        "run_data_agent",
        lambda question, database_path=None: AgentAnswer(
            answer="The Ergonomic Office Chair generated the most revenue.",
            tool_calls=SAMPLE_TOOL_CALLS,
        ),
    )
    monkeypatch.setattr(sys, "argv", ["app.py", "--debug"])

    app.main()

    out = capsys.readouterr().out
    assert "The Ergonomic Office Chair generated the most revenue." in out
    assert "SQL executed:" in out
    assert SAMPLE_TOOL_CALLS[0].query in out
    assert "Rows returned: 1" in out
    assert "Execution time: 2.4 ms" in out


def test_debug_mode_reports_failed_calls(monkeypatch, capsys):
    failed_call = SQLToolCallRecord(
        query="SELECT * FRM customers",
        success=False,
        execution_time_ms=0.5,
        error="Invalid SQL: near \"FRM\": syntax error",
    )
    _feed_inputs(monkeypatch, "A broken question", "exit")
    monkeypatch.setattr(
        app,
        "run_data_agent",
        lambda question, database_path=None: AgentAnswer(
            answer="I could not find that information.", tool_calls=[failed_call]
        ),
    )
    monkeypatch.setattr(sys, "argv", ["app.py", "--debug"])

    app.main()

    out = capsys.readouterr().out
    assert "Failed:" in out
    assert "syntax error" in out


def test_debug_mode_reports_when_no_sql_was_run(monkeypatch, capsys):
    _feed_inputs(monkeypatch, "Hello", "exit")
    monkeypatch.setattr(
        app,
        "run_data_agent",
        lambda question, database_path=None: AgentAnswer(answer="Hi there!", tool_calls=[]),
    )
    monkeypatch.setattr(sys, "argv", ["app.py", "--debug"])

    app.main()

    out = capsys.readouterr().out
    assert "no SQL was executed" in out


# ---------------------------------------------------------------------------
# Normal mode: only the final business answer, never SQL
# ---------------------------------------------------------------------------


def test_normal_mode_does_not_print_sql(monkeypatch, capsys):
    _feed_inputs(monkeypatch, "Which product generated the most revenue?", "exit")
    monkeypatch.setattr(
        app,
        "run_data_agent",
        lambda question, database_path=None: AgentAnswer(
            answer="The Ergonomic Office Chair generated the most revenue.",
            tool_calls=SAMPLE_TOOL_CALLS,
        ),
    )
    monkeypatch.setattr(sys, "argv", ["app.py"])

    app.main()

    out = capsys.readouterr().out
    assert "The Ergonomic Office Chair generated the most revenue." in out
    assert "SQL executed:" not in out
    assert SAMPLE_TOOL_CALLS[0].query not in out
    assert "Execution time" not in out
    assert "Rows returned" not in out


# ---------------------------------------------------------------------------
# Error handling: clean messages, no raw tracebacks
# ---------------------------------------------------------------------------


def test_config_error_is_shown_cleanly(monkeypatch, capsys):
    _feed_inputs(monkeypatch, "Any question", "exit")

    def raise_config_error(question, database_path=None):
        raise AgentConfigError("OPENAI_API_KEY is not set.")

    monkeypatch.setattr(app, "run_data_agent", raise_config_error)
    monkeypatch.setattr(sys, "argv", ["app.py"])

    app.main()

    out = capsys.readouterr().out
    assert "Configuration error:" in out
    assert "Traceback" not in out


def test_empty_input_is_ignored_and_loop_continues(monkeypatch, capsys):
    _feed_inputs(monkeypatch, "", "   ", "exit")
    calls = []
    monkeypatch.setattr(
        app,
        "run_data_agent",
        lambda question, database_path=None: calls.append(question),
    )
    monkeypatch.setattr(sys, "argv", ["app.py"])

    app.main()

    assert calls == []  # run_data_agent should never be called for blank input
    out = capsys.readouterr().out
    assert "Goodbye." in out


def test_quit_command_exits_cleanly(monkeypatch, capsys):
    _feed_inputs(monkeypatch, "quit")
    monkeypatch.setattr(sys, "argv", ["app.py"])

    app.main()

    out = capsys.readouterr().out
    assert "Goodbye." in out
