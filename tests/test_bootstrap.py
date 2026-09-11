"""Tests for database/bootstrap.py.

Ordinary, fast, local-SQLite tests — database bootstrapping is a backend
concern with no OpenAI API involvement at all, so nothing here needs
mocking beyond isolating each test to its own tmp_path database.
"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from database.bootstrap import ensure_sample_database

EXPECTED_TABLES = {"customers", "products", "orders", "order_items"}


def _table_names(database_path: str) -> set[str]:
    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    finally:
        connection.close()
    return {row[0] for row in rows}


def _row_counts(database_path: str) -> dict:
    connection = sqlite3.connect(database_path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in EXPECTED_TABLES
        }
    finally:
        connection.close()


def test_ensure_sample_database_creates_a_missing_database(tmp_path):
    db_path = str(tmp_path / "does_not_exist_yet" / "ecommerce.db")
    assert not Path(db_path).exists()

    ensure_sample_database(db_path)

    assert Path(db_path).exists()


def test_ensure_sample_database_creates_all_expected_tables(tmp_path):
    db_path = str(tmp_path / "ecommerce.db")

    ensure_sample_database(db_path)

    assert EXPECTED_TABLES.issubset(_table_names(db_path))


def test_ensure_sample_database_populates_sample_data(tmp_path):
    db_path = str(tmp_path / "ecommerce.db")

    ensure_sample_database(db_path)

    counts = _row_counts(db_path)
    assert counts["customers"] == 100
    assert counts["products"] == 30
    assert 500 <= counts["orders"] <= 800
    assert counts["order_items"] > 0


def test_ensure_sample_database_is_idempotent(tmp_path):
    db_path = str(tmp_path / "ecommerce.db")

    ensure_sample_database(db_path)
    counts_after_first_call = _row_counts(db_path)

    ensure_sample_database(db_path)
    counts_after_second_call = _row_counts(db_path)

    assert counts_after_first_call == counts_after_second_call


def test_ensure_sample_database_works_with_a_custom_path(tmp_path):
    custom_path = str(tmp_path / "custom_subdir" / "custom_name.db")

    resolved = ensure_sample_database(custom_path)

    assert resolved == custom_path
    assert _row_counts(custom_path)["customers"] == 100


def test_ensure_sample_database_resolves_database_path_env_var_when_not_passed(
    monkeypatch, tmp_path
):
    db_path = str(tmp_path / "env_configured.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)

    resolved = ensure_sample_database()

    assert resolved == db_path
    assert _row_counts(db_path)["customers"] == 100


def test_ensure_sample_database_returns_the_resolved_path(tmp_path):
    db_path = str(tmp_path / "ecommerce.db")

    resolved = ensure_sample_database(db_path)

    assert resolved == db_path


def test_ensure_sample_database_handles_concurrent_bootstrap_calls(tmp_path):
    """Simulates several Streamlit workers bootstrapping the same fresh
    database at the same time — the real-world scenario this whole
    concurrency fix exists for."""
    db_path = str(tmp_path / "concurrent_bootstrap.db")
    assert not Path(db_path).exists()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(ensure_sample_database, db_path) for _ in range(5)]
        # .result() re-raises any exception (e.g. a UNIQUE constraint
        # failure), so this fails loudly if the race isn't prevented.
        resolved_paths = [future.result() for future in futures]

    assert all(path == db_path for path in resolved_paths)
    assert _row_counts(db_path)["customers"] == 100
