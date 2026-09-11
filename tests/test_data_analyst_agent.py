"""Tests for the AI Data Analyst Agent.

These tests never make a real OpenAI API call: Runner.run_sync is always
monkeypatched before ask_data_agent is exercised, and everything else
(instructions, the SQL tool, config handling) is testable without the
Agents SDK ever reaching the network.
"""

import sqlite3

import pytest

import agent.data_analyst_agent as data_analyst_agent
from agent.data_analyst_agent import (
    AgentConfigError,
    AgentRuntimeError,
    _run_sql_query_impl,
    ask_data_agent,
    build_data_analyst_agent,
)
from database.seed_db import seed_database
from tools.schema_tool import SchemaToolError
from tools.sql_tool import execute_read_only_query


@pytest.fixture
def seeded_db_path(tmp_path) -> str:
    db_path = str(tmp_path / "test_ecommerce.db")
    seed_database(db_path)
    return db_path


@pytest.fixture(autouse=True)
def _default_test_env(monkeypatch):
    # A present-but-fake key by default, so tests that aren't specifically
    # about the missing-key case don't need to repeat this setup.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


# ---------------------------------------------------------------------------
# Schema is dynamically injected into agent instructions
# ---------------------------------------------------------------------------


def test_agent_instructions_include_live_schema(seeded_db_path):
    agent_obj = build_data_analyst_agent(seeded_db_path)

    assert "TABLE customers" in agent_obj.instructions
    assert "TABLE orders" in agent_obj.instructions
    assert "TABLE order_items" in agent_obj.instructions
    assert "TABLE products" in agent_obj.instructions
    assert "FOREIGN KEY: customer_id -> customers.id" in agent_obj.instructions


def test_agent_instructions_reflect_a_different_database_schema(tmp_path):
    db_path = str(tmp_path / "custom.db")
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        )
        connection.commit()
    finally:
        connection.close()

    agent_obj = build_data_analyst_agent(db_path)

    assert "TABLE widgets" in agent_obj.instructions
    assert "TABLE customers" not in agent_obj.instructions


def test_agent_instructions_mention_key_business_rules(seeded_db_path):
    agent_obj = build_data_analyst_agent(seeded_db_path)

    assert "completed" in agent_obj.instructions
    assert "quantity * order_items.unit_price" in agent_obj.instructions
    assert "run_sql_query" in agent_obj.instructions


def test_agent_instructions_do_not_hardcode_seeded_business_answers(seeded_db_path):
    agent_obj = build_data_analyst_agent(seeded_db_path)

    # The instructions should describe schema/rules only, never a
    # concrete seeded result the agent should instead discover via SQL.
    assert "66791" not in agent_obj.instructions
    assert "Ergonomic Office Chair" not in agent_obj.instructions


# ---------------------------------------------------------------------------
# The SQL tool delegates to execute_read_only_query and stays model-friendly
# ---------------------------------------------------------------------------


def test_run_sql_query_tool_delegates_to_execute_read_only_query(seeded_db_path):
    direct = execute_read_only_query(
        "SELECT COUNT(*) FROM customers", database_path=seeded_db_path
    )
    via_tool = _run_sql_query_impl("SELECT COUNT(*) FROM customers", seeded_db_path)

    assert via_tool == direct


def test_run_sql_query_tool_result_is_model_friendly_dict(seeded_db_path):
    result = _run_sql_query_impl("SELECT id, city FROM customers LIMIT 3", seeded_db_path)

    assert set(result.keys()) == {"columns", "rows", "row_count", "truncated"}
    assert result["columns"] == ["id", "city"]
    assert result["row_count"] == 3
    assert isinstance(result["rows"], list)


def test_run_sql_query_tool_returns_error_dict_for_unsafe_query_instead_of_raising(
    seeded_db_path,
):
    result = _run_sql_query_impl("DELETE FROM customers", seeded_db_path)

    assert "error" in result
    assert "SELECT" in result["error"]


def test_run_sql_query_tool_returns_error_dict_for_malformed_sql(seeded_db_path):
    result = _run_sql_query_impl("SELECT * FRM customers", seeded_db_path)

    assert "error" in result


def test_agent_exposes_exactly_one_sql_tool_with_clear_description(seeded_db_path):
    agent_obj = build_data_analyst_agent(seeded_db_path)

    assert len(agent_obj.tools) == 1
    tool = agent_obj.tools[0]
    description = tool.description.lower()

    assert tool.name == "run_sql_query"
    assert "read-only" in description
    assert "select" in description
    assert "modify" in description
    assert "forbidden" in description


# ---------------------------------------------------------------------------
# Existing SQL safety behavior is not weakened by the agent layer
# ---------------------------------------------------------------------------


UNSAFE_QUERIES = [
    "INSERT INTO customers (first_name, last_name, email) VALUES ('a', 'b', 'c@example.com')",
    "DROP TABLE customers",
    "ATTACH DATABASE 'other.db' AS other",
    "PRAGMA table_info(customers)",
    "SELECT 1; DROP TABLE customers;",
]


@pytest.mark.parametrize("query", UNSAFE_QUERIES)
def test_agent_sql_tool_still_rejects_unsafe_queries(seeded_db_path, query):
    result = _run_sql_query_impl(query, seeded_db_path)
    assert "error" in result


def test_agent_sql_tool_cannot_modify_the_database(seeded_db_path):
    def count_customers() -> int:
        connection = sqlite3.connect(seeded_db_path)
        try:
            return connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        finally:
            connection.close()

    before = count_customers()
    _run_sql_query_impl("DELETE FROM customers", seeded_db_path)
    after = count_customers()

    assert after == before


# ---------------------------------------------------------------------------
# Database path configuration
# ---------------------------------------------------------------------------


def test_build_agent_uses_explicit_database_path(seeded_db_path):
    agent_obj = build_data_analyst_agent(seeded_db_path)
    assert "TABLE customers" in agent_obj.instructions


def test_build_agent_uses_database_path_env_var_when_not_passed(monkeypatch, seeded_db_path):
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)

    agent_obj = build_data_analyst_agent()

    assert "TABLE customers" in agent_obj.instructions


def test_build_agent_raises_for_missing_database(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.db")
    with pytest.raises(SchemaToolError):
        build_data_analyst_agent(missing_path)


def test_build_agent_raises_for_database_with_no_application_tables(tmp_path):
    db_path = str(tmp_path / "empty.db")
    sqlite3.connect(db_path).close()

    with pytest.raises(AgentConfigError):
        build_data_analyst_agent(db_path)


# ---------------------------------------------------------------------------
# Missing API key / configuration handling
# ---------------------------------------------------------------------------


def test_ask_data_agent_raises_config_error_when_api_key_missing(monkeypatch, seeded_db_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(AgentConfigError):
        ask_data_agent("How many customers are there?", database_path=seeded_db_path)


def test_ask_data_agent_raises_config_error_when_api_key_blank(monkeypatch, seeded_db_path):
    monkeypatch.setenv("OPENAI_API_KEY", "   ")

    with pytest.raises(AgentConfigError):
        ask_data_agent("How many customers are there?", database_path=seeded_db_path)


def test_missing_api_key_check_happens_before_any_agent_run(monkeypatch, seeded_db_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Runner.run_sync should not be called without an API key")

    monkeypatch.setattr(data_analyst_agent.Runner, "run_sync", fail_if_called)

    with pytest.raises(AgentConfigError):
        ask_data_agent("Any question", database_path=seeded_db_path)


def test_model_defaults_when_not_configured(seeded_db_path):
    agent_obj = build_data_analyst_agent(seeded_db_path)
    assert agent_obj.model == data_analyst_agent.DEFAULT_MODEL


def test_model_env_var_overrides_default(monkeypatch, seeded_db_path):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")

    agent_obj = build_data_analyst_agent(seeded_db_path)

    assert agent_obj.model == "gpt-4.1-mini"


# ---------------------------------------------------------------------------
# ask_data_agent with a mocked Runner: no real API calls
# ---------------------------------------------------------------------------


def test_ask_data_agent_returns_final_output_from_runner(monkeypatch, seeded_db_path):
    captured = {}

    class FakeResult:
        final_output = "Total revenue from completed orders is $66,791.61."

    def fake_run_sync(starting_agent, input, **kwargs):
        captured["agent"] = starting_agent
        captured["input"] = input
        return FakeResult()

    monkeypatch.setattr(data_analyst_agent.Runner, "run_sync", fake_run_sync)

    answer = ask_data_agent("What is total revenue?", database_path=seeded_db_path)

    assert answer == "Total revenue from completed orders is $66,791.61."
    assert captured["input"] == "What is total revenue?"
    assert captured["agent"].name == data_analyst_agent.AGENT_NAME


def test_ask_data_agent_wraps_runner_errors_without_leaking_raw_exception_type(
    monkeypatch, seeded_db_path
):
    def fake_run_sync(starting_agent, input, **kwargs):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(data_analyst_agent.Runner, "run_sync", fake_run_sync)

    with pytest.raises(AgentRuntimeError):
        ask_data_agent("What is total revenue?", database_path=seeded_db_path)
