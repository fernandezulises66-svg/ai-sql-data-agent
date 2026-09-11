"""Safe, read-only SQL execution tool for the AI SQL Data Analyst Agent.

This module is the only supported way to run analytical SQL against the
project's SQLite database. It is written defensively because it will
later be exposed to an AI agent that generates SQL text on its own, and a
single mistake in generated SQL must never be able to modify data.

Three independent layers of defense are used, so that no single one of
them being wrong or bypassed is enough to cause a write:

1. Text validation (validate_read_only_sql) rejects anything that is not
   a single SELECT/WITH statement before it ever reaches SQLite.
2. The database connection itself is opened read-only via a
   ``file:...?mode=ro`` URI, plus ``PRAGMA query_only = ON``, so SQLite
   refuses writes at the connection level regardless of the SQL text.
3. A ``sqlite3.Connection.set_authorizer`` callback allow-lists only the
   handful of actions a plain analytical SELECT needs and denies
   everything else (writes, schema changes, ATTACH, PRAGMA, transaction
   control, ...), independent of what the text validator decided.

Layer 1 alone is not treated as sufficient security (keyword matching can
always be fooled by SQL's flexibility); layers 2 and 3 are what actually
make it impossible for a query to modify the database through this tool.
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from database.init_db import get_database_path

DEFAULT_MAX_ROWS = 100


class SQLToolError(Exception):
    """Base class for errors raised by this module."""


class SQLValidationError(SQLToolError, ValueError):
    """Raised when a query fails safety validation before execution."""


class SQLExecutionError(SQLToolError, RuntimeError):
    """Raised when a validated query still cannot be executed safely."""


# Statement keywords that must never appear in a query handed to this
# tool. Matched with word boundaries so, e.g., "created_at" does not
# falsely match "CREATE".
_FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE",
    "TRUNCATE", "VACUUM", "ATTACH", "DETACH", "PRAGMA", "REINDEX",
    "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE",
)
_FORBIDDEN_PATTERN = re.compile(
    r"\b(" + "|".join(_FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE
)

_ALLOWED_FIRST_WORDS = {"SELECT", "WITH"}

# Authorizer actions a plain analytical SELECT legitimately needs.
# Everything else (writes, schema changes, ATTACH, PRAGMA, transaction
# control, ...) is denied by default: this is a default-deny allow list,
# not a blocklist, so unfamiliar/future SQLite features are denied
# automatically instead of needing to be remembered.
_ALLOWED_AUTHORIZER_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


def _strip_sql_comments(query: str) -> str:
    """Remove ``--`` line comments and ``/* */`` block comments.

    Used only to decide the query's real first keyword and to split it
    into statements; comments are genuinely inert SQL, so removing them
    before analysis cannot change what actually executes.
    """
    without_block_comments = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", without_block_comments)


def _split_top_level_statements(sql: str) -> list[str]:
    """Split sql on ``;`` characters that are not inside a string literal.

    This is a lightweight character scan, not a SQL parser: its only job
    is telling "one statement" apart from "more than one statement" so
    validate_read_only_sql can reject multi-statement input, including
    when a legitimate query contains a semicolon inside a string value.
    """
    statements = []
    current: list[str] = []
    in_string = False
    i = 0
    length = len(sql)
    while i < length:
        char = sql[i]
        if in_string:
            if char == "'":
                if i + 1 < length and sql[i + 1] == "'":
                    current.append("''")
                    i += 2
                    continue
                in_string = False
            current.append(char)
        else:
            if char == "'":
                in_string = True
                current.append(char)
            elif char == ";":
                statements.append("".join(current))
                current = []
            else:
                current.append(char)
        i += 1
    statements.append("".join(current))
    return statements


def validate_read_only_sql(query: str) -> str:
    """Validate that ``query`` is a single, read-only analytical statement.

    Allows exactly one SELECT statement, optionally starting with a WITH
    (CTE) clause, and rejects everything else: empty input, database
    modification statements, and multiple statements.

    Returns the original (trimmed) query text on success. Raises
    SQLValidationError with a human-readable message otherwise.
    """
    if query is None or not query.strip():
        raise SQLValidationError("Query must not be empty.")

    trimmed = query.strip()
    stripped = _strip_sql_comments(trimmed).strip()

    if not stripped:
        raise SQLValidationError("Query must not be empty.")

    statements = [s.strip() for s in _split_top_level_statements(stripped)]
    non_empty_statements = [s for s in statements if s]

    if len(non_empty_statements) == 0:
        raise SQLValidationError("Query must not be empty.")
    if len(non_empty_statements) > 1:
        raise SQLValidationError(
            "Multiple SQL statements are not allowed; submit one query at a time."
        )

    body = non_empty_statements[0]

    first_word_match = re.match(r"([A-Za-z]+)", body)
    first_word = first_word_match.group(1).upper() if first_word_match else ""
    if first_word not in _ALLOWED_FIRST_WORDS:
        raise SQLValidationError(
            "Only SELECT queries (optionally starting with WITH/CTEs) are allowed."
        )

    forbidden_match = _FORBIDDEN_PATTERN.search(body)
    if forbidden_match:
        raise SQLValidationError(
            f"Query contains a disallowed operation: {forbidden_match.group(1).upper()}."
        )

    return trimmed


def _authorizer(action: int, arg1: str | None, arg2: str | None, db_name: str | None,
                 trigger_or_view: str | None) -> int:
    """Allow only the SQLite actions a read-only SELECT needs; deny the rest."""
    if action in _ALLOWED_AUTHORIZER_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def get_read_only_connection(database_path: str | None = None) -> sqlite3.Connection:
    """Open a connection that cannot write, even if text validation is bypassed.

    Combines a ``mode=ro`` URI connection, ``PRAGMA query_only = ON``, and
    an authorizer allow list. Any one of these being wrong still leaves
    the others enforcing read-only access.
    """
    database_path = database_path or get_database_path()
    db_file = Path(database_path)

    if not db_file.exists():
        raise SQLExecutionError(f"Database file not found: {database_path}")

    uri = f"{db_file.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        raise SQLExecutionError(
            f"Could not open database in read-only mode: {exc}"
        ) from exc

    # Autocommit mode: this connection never issues an implicit BEGIN, so
    # there is no transaction to accidentally commit.
    connection.isolation_level = None
    connection.execute("PRAGMA query_only = ON;")
    connection.set_authorizer(_authorizer)
    return connection


def execute_read_only_query(
    query: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    database_path: str | None = None,
) -> dict[str, Any]:
    """Validate and safely execute a read-only analytical SQL query.

    Returns a dict shaped for easy consumption by a future AI agent::

        {
            "columns": [...],
            "rows": [...],
            "row_count": 10,
            "truncated": False,
            "execution_time_ms": 2.4,
        }

    ``rows`` is capped at ``max_rows`` (default 100); ``truncated`` is
    True when more rows were available than were returned.
    ``execution_time_ms`` covers only the actual statement execution and
    row fetch (not connection setup), measured with
    ``time.perf_counter()``, for lightweight observability into query
    performance.
    """
    if max_rows <= 0:
        raise SQLValidationError("max_rows must be a positive integer.")

    validated_query = validate_read_only_sql(query)

    connection = get_read_only_connection(database_path)
    try:
        start_time = time.perf_counter()
        try:
            cursor = connection.execute(validated_query)
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as exc:
            raise SQLExecutionError(f"Invalid SQL: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            raise SQLExecutionError(f"Query could not be executed: {exc}") from exc

        columns = [description[0] for description in cursor.description or []]

        # Fetch one extra row (never returned) so truncation can be
        # detected without pulling an unbounded result set into memory.
        fetched = cursor.fetchmany(max_rows + 1)
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        truncated = len(fetched) > max_rows
        rows = [tuple(row) for row in fetched[:max_rows]]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "execution_time_ms": round(execution_time_ms, 3),
        }
    finally:
        connection.close()
