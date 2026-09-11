"""Database initialization for the AI SQL Data Analyst Agent.

Creates the SQLite database file and schema (customers, products, orders,
order_items) at the location configured by the DATABASE_PATH environment
variable, defaulting to data/ecommerce.db.

Running this module multiple times is safe: schema.sql uses
"CREATE ... IF NOT EXISTS" throughout, so re-running it does not fail or
duplicate tables/indexes.
"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DATABASE_PATH = "data/ecommerce.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_database_path() -> str:
    """Resolve the configured database path, falling back to the default."""
    return os.environ.get("DATABASE_PATH", DEFAULT_DATABASE_PATH)


def get_connection(database_path: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with foreign key enforcement enabled.

    SQLite enforces foreign keys per-connection and defaults to off, so
    every connection used by this project must opt in explicitly.
    """
    database_path = database_path or get_database_path()
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def init_db(database_path: str | None = None) -> str:
    """Create the SQLite database file and schema if they don't exist yet.

    Returns the resolved database path that was initialized.
    """
    database_path = database_path or get_database_path()

    db_file = Path(database_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    connection = get_connection(database_path)
    try:
        connection.executescript(schema_sql)
        connection.commit()
    finally:
        connection.close()

    return database_path


if __name__ == "__main__":
    initialized_path = init_db()
    print(f"Database initialized at: {initialized_path}")
