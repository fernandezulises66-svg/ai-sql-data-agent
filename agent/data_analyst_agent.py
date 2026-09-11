"""AI Data Analyst Agent for the ecommerce SQLite database.

Wires the OpenAI Agents SDK to the project's existing, already-tested
tools instead of duplicating any of their logic:

- ``tools.schema_tool`` supplies the live database schema, formatted for
  a prompt, so the agent's instructions never hardcode table/column
  names by hand.
- ``tools.sql_tool`` is the *only* way the agent can read data. The
  agent never opens a sqlite3 connection itself; the ``run_sql_query``
  tool below is a thin wrapper around
  ``tools.sql_tool.execute_read_only_query``, which enforces read-only
  access independently of anything this module does (see sql_tool.py's
  module docstring for its defense-in-depth design).

This module does not implement a UI; see app.py for the terminal demo.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from agents import Agent, Runner, function_tool

from tools.schema_tool import SchemaToolError, format_schema_for_llm, get_database_schema
from tools.sql_tool import SQLToolError, execute_read_only_query

# Loads variables from a local .env file, if one exists, into the
# process environment. Never overrides a variable that is already set
# (e.g. one a test deliberately configured via monkeypatch), and is a
# harmless no-op when no .env file is present.
load_dotenv()

AGENT_NAME = "Data Analyst Agent"
DEFAULT_MODEL = "gpt-4o-mini"

_API_KEY_ENV_VAR = "OPENAI_API_KEY"
_MODEL_ENV_VAR = "OPENAI_MODEL"


class AgentError(Exception):
    """Base class for errors raised by this module."""


class AgentConfigError(AgentError):
    """Raised when the agent is missing required configuration."""


class AgentRuntimeError(AgentError):
    """Raised when the agent/OpenAI API fails while answering a question."""


@dataclass
class SQLToolCallRecord:
    """Observability metadata for one run_sql_query tool call.

    Captures only what's needed to see how the agent used the SQL tool:
    the query text and outcome metadata. Deliberately does not capture
    the actual returned rows/columns (only row_count), API keys,
    environment secrets, or any other internal SDK data.
    """

    query: str
    success: bool
    execution_time_ms: float
    row_count: int | None = None
    truncated: bool | None = None
    error: str | None = None


@dataclass
class AgentAnswer:
    """Result of run_data_agent(): the final answer plus SQL tool activity."""

    answer: str
    tool_calls: list[SQLToolCallRecord] = field(default_factory=list)


def _get_openai_api_key() -> str:
    """Return the configured OpenAI API key, or raise a clear error."""
    api_key = os.environ.get(_API_KEY_ENV_VAR, "").strip()
    if not api_key:
        raise AgentConfigError(
            f"{_API_KEY_ENV_VAR} is not set. Copy .env.example to .env and add your key."
        )
    return api_key


def _get_model() -> str:
    """Return the configured model, falling back to a sensible default.

    Centralizes model selection in one place so it is never hardcoded
    anywhere else in the application.
    """
    return os.environ.get(_MODEL_ENV_VAR, "").strip() or DEFAULT_MODEL


INSTRUCTIONS_TEMPLATE = """\
You are a business data analyst for a fictional ecommerce company. You \
answer natural-language business questions about sales, customers, \
products, and orders by querying the company's SQLite database.

Rules:
- The database schema below is the only source of truth for table and \
column names. Never guess at or invent tables, columns, or values.
- When a question requires data, call the run_sql_query tool to run a \
single read-only SELECT (or WITH ... SELECT) query before answering. \
Never state a number, name, or result that did not come from a \
run_sql_query call, and never claim you queried the database if you did \
not actually call the tool.
- Write valid SQLite SQL. Use JOINs across tables when a question needs \
data from more than one table.
- Compute revenue/sales amounts as: order_items.quantity * order_items.unit_price.
- Unless the user explicitly asks about a specific order status (or all \
statuses), compute revenue/sales figures using only orders where \
status = 'completed'.
- If a query returns no rows, fails, or the result was truncated, say so \
plainly instead of guessing.
- Answer in clear, concise business language a non-technical stakeholder \
can understand: summarize the finding, not the SQL. Mention relevant \
limitations (e.g. a status filter you applied, a truncated result) when \
they matter to the answer.
- Always respond in the same language the user's question was written \
in (e.g. a Spanish question gets a Spanish answer, an English question \
gets an English answer), regardless of the language of the schema or \
this prompt.

DATABASE SCHEMA
{schema_text}
"""


def _build_instructions(database_path: str | None) -> str:
    """Build agent instructions with the live database schema injected."""
    try:
        schema = get_database_schema(database_path)
    except SchemaToolError:
        raise
    except sqlite3.DatabaseError as exc:
        # e.g. the configured file exists but is not a valid SQLite database.
        raise SchemaToolError(f"The database schema could not be read: {exc}") from exc

    if not schema["tables"]:
        raise AgentConfigError(
            "The database has no application tables yet. Run "
            "`python -m database.init_db` and `python -m database.seed_db` first."
        )

    schema_text = format_schema_for_llm(schema)
    return INSTRUCTIONS_TEMPLATE.format(schema_text=schema_text)


def _run_sql_query_impl(
    query: str,
    database_path: str | None,
    tool_calls: list[SQLToolCallRecord] | None = None,
) -> dict[str, Any]:
    """Implementation behind the run_sql_query tool, kept plain for tests.

    Delegates entirely to tools.sql_tool.execute_read_only_query; no SQL
    validation is reimplemented here. A rejected/failed query is returned
    to the model as {"error": "..."} instead of raising, so the model can
    see what went wrong and adjust its next query.

    When tool_calls is provided, one SQLToolCallRecord for this call is
    appended to it — the project's only SQL tool observability hook.
    Existing callers that pass just (query, database_path) are unaffected.
    """
    start_time = time.perf_counter()
    try:
        result = execute_read_only_query(query, database_path=database_path)
    except SQLToolError as exc:
        if tool_calls is not None:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            tool_calls.append(
                SQLToolCallRecord(
                    query=query,
                    success=False,
                    execution_time_ms=round(elapsed_ms, 3),
                    error=str(exc),
                )
            )
        return {"error": str(exc)}

    if tool_calls is not None:
        tool_calls.append(
            SQLToolCallRecord(
                query=query,
                success=True,
                execution_time_ms=result["execution_time_ms"],
                row_count=result["row_count"],
                truncated=result["truncated"],
            )
        )
    return result


def _build_run_sql_query_tool(
    database_path: str | None, tool_calls: list[SQLToolCallRecord] | None
):
    """Create the run_sql_query function tool bound to database_path.

    Each call this tool makes is recorded into tool_calls, if provided
    (see _run_sql_query_impl).
    """

    @function_tool
    def run_sql_query(query: str) -> dict[str, Any]:
        """Execute one read-only analytical SQL query against the ecommerce database.

        Only a single SELECT statement is allowed, optionally starting
        with a WITH clause (CTE) — for example aggregations, joins,
        filters, ordering, and limits are all fine. Any statement that
        could modify the database (INSERT, UPDATE, DELETE, DROP, ALTER,
        CREATE, etc.), or more than one statement, is forbidden and will
        be rejected before it ever reaches the database.

        Args:
            query: A single read-only SQLite SELECT (or WITH ... SELECT) statement.
        """
        return _run_sql_query_impl(query, database_path, tool_calls)

    return run_sql_query


def build_data_analyst_agent(
    database_path: str | None = None,
    *,
    tool_calls: list[SQLToolCallRecord] | None = None,
) -> Agent:
    """Build an Agent wired to the live database schema and the safe SQL tool.

    tool_calls, if provided, is the list this agent's run_sql_query tool
    will record a SQLToolCallRecord into on every call (see
    run_data_agent()); callers that don't need this can ignore it.

    Raises SchemaToolError if the database can't be read, or
    AgentConfigError if it has no application tables to analyze. Does
    not require OPENAI_API_KEY or make any network call.
    """
    instructions = _build_instructions(database_path)
    run_sql_query_tool = _build_run_sql_query_tool(database_path, tool_calls)

    return Agent(
        name=AGENT_NAME,
        instructions=instructions,
        tools=[run_sql_query_tool],
        model=_get_model(),
    )


def run_data_agent(question: str, database_path: str | None = None) -> AgentAnswer:
    """Run a natural-language business question through the data analyst agent.

    Like ask_data_agent(), but also returns the SQLToolCallRecords for
    every run_sql_query call the agent made while answering — this is
    what the CLI's --debug mode (see app.py) uses to show SQL tool
    activity. Most callers that only need the text answer should use
    ask_data_agent() instead.

    Raises AgentConfigError for missing configuration, SchemaToolError
    for database problems, and AgentRuntimeError for agent/API failures —
    all with a clean message, never a raw SDK traceback.
    """
    _get_openai_api_key()
    tool_calls: list[SQLToolCallRecord] = []
    agent = build_data_analyst_agent(database_path, tool_calls=tool_calls)

    try:
        result = Runner.run_sync(agent, question)
    except Exception as exc:
        raise AgentRuntimeError(f"The agent could not complete this request: {exc}") from exc

    return AgentAnswer(answer=result.final_output, tool_calls=tool_calls)


def ask_data_agent(question: str, database_path: str | None = None) -> str:
    """Run a natural-language business question and return only the answer.

    A convenience wrapper around run_data_agent() for callers that don't
    need SQL tool-call metadata.
    """
    return run_data_agent(question, database_path).answer
