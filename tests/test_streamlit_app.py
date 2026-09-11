"""Tests for streamlit_app.py.

Per project convention, this does not attempt to exhaustively test
Streamlit rendering. It covers:

1. The pure helper functions (no Streamlit calls) that turn backend
   results into display-ready data — these are plain functions and are
   tested directly, the same way any other module in this project is.
2. A handful of smoke tests using streamlit.testing.v1.AppTest to prove
   the app boots and the main flows (ask -> answer -> SQL details,
   errors, empty input, no-SQL-call case) render without exceptions.

agent.data_analyst_agent.run_data_agent is always monkeypatched before
driving the app, so no test here ever calls the real OpenAI API.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import agent.data_analyst_agent as data_analyst_agent
from agent.data_analyst_agent import (
    AgentAnswer,
    AgentConfigError,
    AgentError,
    AgentRuntimeError,
    SQLToolCallRecord,
)
from streamlit_app import (
    build_observability_view,
    build_tool_call_view,
    error_message_for,
    used_sql,
)
from tools.schema_tool import SchemaToolError

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def test_build_tool_call_view_includes_only_observable_fields():
    record = SQLToolCallRecord(
        query="SELECT COUNT(*) FROM customers",
        success=True,
        execution_time_ms=2.4,
        row_count=1,
        truncated=False,
    )

    view = build_tool_call_view(record)

    assert view == {
        "query": "SELECT COUNT(*) FROM customers",
        "success": True,
        "row_count": 1,
        "truncated": False,
        "execution_time_ms": 2.4,
        "error": None,
    }


def test_build_tool_call_view_includes_error_for_failed_calls():
    record = SQLToolCallRecord(
        query="DELETE FROM customers",
        success=False,
        execution_time_ms=0.5,
        error="Only SELECT queries are allowed.",
    )

    view = build_tool_call_view(record)

    assert view["success"] is False
    assert view["error"] == "Only SELECT queries are allowed."
    assert view["row_count"] is None


def test_build_observability_view_handles_an_agent_answer_with_calls():
    answer = AgentAnswer(
        answer="Revenue was $100.",
        tool_calls=[
            SQLToolCallRecord(query="SELECT 1", success=True, execution_time_ms=1.0),
            SQLToolCallRecord(query="SELECT 2", success=True, execution_time_ms=2.0),
        ],
    )

    view = build_observability_view(answer)

    assert len(view) == 2
    assert view[0]["query"] == "SELECT 1"
    assert view[1]["query"] == "SELECT 2"


def test_build_observability_view_handles_no_sql_call_case():
    answer = AgentAnswer(answer="Hello!", tool_calls=[])

    assert build_observability_view(answer) == []


def test_used_sql_true_when_tool_calls_present():
    answer = AgentAnswer(
        answer="a", tool_calls=[SQLToolCallRecord(query="q", success=True, execution_time_ms=1.0)]
    )
    assert used_sql(answer) is True


def test_used_sql_false_when_no_tool_calls():
    answer = AgentAnswer(answer="a", tool_calls=[])
    assert used_sql(answer) is False


@pytest.mark.parametrize(
    "exc, expected_prefix",
    [
        (AgentConfigError("OPENAI_API_KEY is not set."), "Error de configuración:"),
        (SchemaToolError("Database file not found."), "Error de base de datos:"),
        (AgentRuntimeError("The agent could not complete this request."), "Error del agente:"),
        (AgentError("something else"), "Error:"),
        (RuntimeError("totally unexpected"), "Error inesperado:"),
    ],
)
def test_error_message_for_maps_known_exception_types(exc, expected_prefix):
    message = error_message_for(exc)
    assert message.startswith(expected_prefix)
    assert str(exc) in message


def test_error_message_for_never_includes_a_traceback():
    message = error_message_for(RuntimeError("boom"))
    assert "Traceback" not in message
    assert "File \"" not in message


# ---------------------------------------------------------------------------
# App smoke tests (streamlit.testing.v1.AppTest) — no real API calls
# ---------------------------------------------------------------------------


def _ask_button(at: AppTest):
    return [b for b in at.button if b.label == "Consultar"][0]


def test_app_boots_without_exceptions(monkeypatch):
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)

    assert not at.exception
    assert at.title[0].value == "Agente de Análisis de Datos con IA y SQL"


def test_app_shows_example_question_buttons_in_both_languages():
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)

    # 5 English + 4 Spanish example question buttons, plus the Ask button.
    assert len(at.button) == 10


def test_submitting_a_question_shows_answer_and_sql_details(monkeypatch):
    def fake_run_data_agent(question, database_path=None):
        return AgentAnswer(
            answer=f"Answer to: {question}",
            tool_calls=[
                SQLToolCallRecord(
                    query="SELECT 1", success=True, execution_time_ms=1.5,
                    row_count=1, truncated=False,
                )
            ],
        )

    monkeypatch.setattr(data_analyst_agent, "run_data_agent", fake_run_data_agent)

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.text_input(key="question_input").set_value("Which products generated the most revenue?")
    _ask_button(at).click().run(timeout=30)

    assert not at.exception
    assert "Respuesta" in [s.value for s in at.subheader]
    assert "Ver detalles SQL" in [e.label for e in at.expander]
    assert "SELECT 1" in [c.value for c in at.code]


def test_submitting_a_conversational_question_shows_no_sql_message(monkeypatch):
    def fake_run_data_agent(question, database_path=None):
        return AgentAnswer(answer="Hello! I can help with sales questions.", tool_calls=[])

    monkeypatch.setattr(data_analyst_agent, "run_data_agent", fake_run_data_agent)

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.text_input(key="question_input").set_value("Hi there")
    _ask_button(at).click().run(timeout=30)

    assert not at.exception
    assert any("No fue necesario consultar la base de datos" in c.value for c in at.caption)


def test_submitting_empty_question_shows_warning_and_does_not_call_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        data_analyst_agent, "run_data_agent", lambda q, database_path=None: calls.append(q)
    )

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    _ask_button(at).click().run(timeout=30)

    assert not at.exception
    assert calls == []
    assert any("Por favor, escribí una pregunta" in w.value for w in at.warning)


def test_agent_config_error_is_shown_as_clean_error_message(monkeypatch):
    def failing_run_data_agent(question, database_path=None):
        raise AgentConfigError("OPENAI_API_KEY is not set.")

    monkeypatch.setattr(data_analyst_agent, "run_data_agent", failing_run_data_agent)

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.text_input(key="question_input").set_value("Any question")
    _ask_button(at).click().run(timeout=30)

    assert not at.exception
    assert any("Error de configuración" in e.value for e in at.error)


def test_unexpected_error_is_shown_cleanly_without_traceback(monkeypatch):
    def failing_run_data_agent(question, database_path=None):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(data_analyst_agent, "run_data_agent", failing_run_data_agent)

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)
    at.text_input(key="question_input").set_value("Any question")
    _ask_button(at).click().run(timeout=30)

    assert not at.exception
    errors = [e.value for e in at.error]
    assert any("Error inesperado" in e for e in errors)
    assert not any("Traceback" in e for e in errors)


def test_clicking_example_question_fills_the_input(monkeypatch):
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=30)

    example_question = "What are the top 5 products by completed-order revenue?"
    example_button = [b for b in at.button if b.label == example_question][0]
    example_button.click().run(timeout=30)

    assert not at.exception
    assert at.text_input(key="question_input").value == example_question
