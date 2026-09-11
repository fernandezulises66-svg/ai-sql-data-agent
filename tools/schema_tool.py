"""Database schema introspection for the AI SQL Data Analyst Agent.

Provides structured, LLM-friendly schema metadata read directly from the
live SQLite database (via SQLite's own introspection PRAGMAs), so a
future AI agent always sees the database's real, current structure
instead of a schema duplicated by hand in Python.

Connection note
----------------
This module opens its own dedicated read-only connection rather than
reusing ``tools.sql_tool.get_read_only_connection``. That connection's
authorizer intentionally denies *all* PRAGMA statements (verified: even
read-only ones like ``PRAGMA table_info``) because it exists to run
arbitrary, possibly agent-generated SQL text safely. This module never
executes user- or agent-supplied SQL — only a small, fixed set of
hardcoded introspection PRAGMAs against table names that were themselves
just read from ``sqlite_master`` — so reusing that stricter authorizer
isn't appropriate here, and this module does not modify or relax it.
The connection opened below is still read-only in its own right
(``mode=ro`` URI + ``PRAGMA query_only = ON``), so it cannot write to the
database either; ``sql_tool.py`` and the guarantees it gives agent-facing
queries are completely unaffected.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from database.init_db import get_database_path


class SchemaToolError(Exception):
    """Raised when the database schema cannot be inspected."""


def _open_trusted_readonly_connection(database_path: str | None) -> sqlite3.Connection:
    """Open a read-only connection for trusted, hardcoded introspection queries."""
    database_path = database_path or get_database_path()
    db_file = Path(database_path)

    if not db_file.exists():
        raise SchemaToolError(f"Database file not found: {database_path}")

    uri = f"{db_file.resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        raise SchemaToolError(
            f"Could not open database in read-only mode: {exc}"
        ) from exc

    connection.isolation_level = None
    connection.execute("PRAGMA query_only = ON;")
    return connection


def _list_application_tables(connection: sqlite3.Connection) -> list[str]:
    """Return application table names, excluding SQLite's internal tables."""
    rows = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _describe_table(connection: sqlite3.Connection, table_name: str) -> dict[str, Any]:
    """Build structured metadata for one table from SQLite's PRAGMAs."""
    columns_info = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    foreign_keys_info = connection.execute(
        f'PRAGMA foreign_key_list("{table_name}")'
    ).fetchall()
    index_list_info = connection.execute(f'PRAGMA index_list("{table_name}")').fetchall()

    # table_info rows: (cid, name, type, notnull, dflt_value, pk)
    # pk is 0 when the column is not part of the primary key, otherwise
    # its 1-based position within the key (supports composite keys).
    columns = [
        {
            "name": row[1],
            "type": row[2] or "",
            "not_null": bool(row[3]),
            "default": row[4],
            "primary_key": row[5] > 0,
        }
        for row in columns_info
    ]
    primary_key_columns = [
        row[1] for row in sorted((r for r in columns_info if r[5] > 0), key=lambda r: r[5])
    ]

    # foreign_key_list rows: (id, seq, table, from, to, on_update, on_delete, match)
    foreign_keys = sorted(
        (
            {
                "column": row[3],
                "references_table": row[2],
                "references_column": row[4],
            }
            for row in foreign_keys_info
        ),
        key=lambda fk: fk["column"],
    )

    # index_list rows: (seq, name, unique, origin, partial)
    indexes = []
    for row in index_list_info:
        index_name = row[1]
        index_columns = [
            info_row[2]
            for info_row in connection.execute(
                f'PRAGMA index_info("{index_name}")'
            ).fetchall()
        ]
        indexes.append(
            {"name": index_name, "unique": bool(row[2]), "columns": index_columns}
        )
    indexes.sort(key=lambda index: index["name"])

    return {
        "name": table_name,
        "columns": columns,
        "primary_key": primary_key_columns,
        "foreign_keys": foreign_keys,
        "indexes": indexes,
    }


def get_database_schema(database_path: str | None = None) -> dict[str, Any]:
    """Return structured schema metadata for every application table.

    Reads directly from the SQLite database via ``PRAGMA table_info``,
    ``PRAGMA foreign_key_list``, and ``PRAGMA index_list`` — nothing
    about the schema is duplicated by hand in this module, so the result
    always reflects the database's actual current structure.

    Returns ``{"tables": [...]}``. Tables are sorted alphabetically by
    name, columns are in their declared order, foreign keys are sorted by
    column name, and indexes are sorted by name — this fixed ordering is
    what makes ``format_schema_for_llm`` deterministic. A database with
    no application tables (or none yet) returns ``{"tables": []}``
    rather than raising.
    """
    connection = _open_trusted_readonly_connection(database_path)
    try:
        table_names = _list_application_tables(connection)
        tables = [_describe_table(connection, name) for name in table_names]
        return {"tables": tables}
    finally:
        connection.close()


def format_schema_for_llm(schema: dict[str, Any]) -> str:
    """Render get_database_schema()'s output as concise text for a prompt.

    Example, for the ecommerce ``orders`` table::

        TABLE orders
        - id INTEGER PRIMARY KEY
        - customer_id INTEGER NOT NULL
        - order_date TEXT NOT NULL
        - status TEXT NOT NULL
        FOREIGN KEY: customer_id -> customers.id

    Deterministic: get_database_schema() already returns tables, columns,
    foreign keys, and indexes in a fixed order, so the same schema always
    renders to the same text.
    """
    tables = schema.get("tables", [])
    if not tables:
        return "No application tables found in the database."

    blocks = []
    for table in tables:
        single_column_unique = {
            index["columns"][0]
            for index in table["indexes"]
            if index["unique"] and len(index["columns"]) == 1
        }
        multi_column_unique = [
            index["columns"]
            for index in table["indexes"]
            if index["unique"] and len(index["columns"]) > 1
        ]

        lines = [f"TABLE {table['name']}"]

        for column in table["columns"]:
            parts = [column["name"], column["type"]]
            if column["primary_key"]:
                parts.append("PRIMARY KEY")
            elif column["not_null"]:
                parts.append("NOT NULL")
            if column["name"] in single_column_unique and not column["primary_key"]:
                parts.append("UNIQUE")
            lines.append("- " + " ".join(part for part in parts if part))

        for foreign_key in table["foreign_keys"]:
            lines.append(
                f"FOREIGN KEY: {foreign_key['column']} -> "
                f"{foreign_key['references_table']}.{foreign_key['references_column']}"
            )

        for unique_columns in multi_column_unique:
            lines.append("UNIQUE: " + ", ".join(unique_columns))

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)
