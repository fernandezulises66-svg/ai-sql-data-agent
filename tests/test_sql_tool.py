import sqlite3

import pytest

from database.seed_db import seed_database
from tools.sql_tool import (
    SQLExecutionError,
    SQLValidationError,
    execute_read_only_query,
    get_read_only_connection,
    validate_read_only_sql,
)

TABLES = ("customers", "products", "orders", "order_items")


@pytest.fixture
def seeded_db_path(tmp_path) -> str:
    """An isolated, seeded temporary database — never the real project DB."""
    db_path = str(tmp_path / "test_ecommerce.db")
    seed_database(db_path)
    return db_path


def _row_counts(db_path: str) -> dict[str, int]:
    connection = sqlite3.connect(db_path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# validate_read_only_sql: SAFE analytical queries
# ---------------------------------------------------------------------------

SAFE_QUERIES = [
    "SELECT * FROM customers",
    "SELECT c.first_name, o.id FROM customers c JOIN orders o ON o.customer_id = c.id",
    "SELECT COUNT(*) FROM orders",
    "SELECT status, COUNT(*) FROM orders GROUP BY status",
    (
        "WITH totals AS (SELECT customer_id, COUNT(*) AS n FROM orders "
        "GROUP BY customer_id) SELECT * FROM totals"
    ),
    "SELECT * FROM customers WHERE city = 'Austin'",
    "SELECT * FROM products ORDER BY price DESC",
    "SELECT * FROM products LIMIT 5",
    "  select * from customers  ",
    "SELECT * FROM customers;",
]


@pytest.mark.parametrize("query", SAFE_QUERIES)
def test_validate_accepts_safe_queries(query):
    assert validate_read_only_sql(query) == query.strip()


# ---------------------------------------------------------------------------
# validate_read_only_sql: UNSAFE queries
# ---------------------------------------------------------------------------

UNSAFE_QUERIES = [
    "INSERT INTO customers (first_name, last_name, email) VALUES ('a', 'b', 'c@example.com')",
    "UPDATE customers SET city = 'Nowhere'",
    "DELETE FROM customers",
    "DROP TABLE customers",
    "CREATE TABLE evil (id INTEGER)",
    "ALTER TABLE customers ADD COLUMN evil TEXT",
    "PRAGMA table_info(customers)",
    "ATTACH DATABASE 'other.db' AS other",
    "DETACH DATABASE other",
    "REPLACE INTO customers (id) VALUES (1)",
    "TRUNCATE TABLE customers",
    "VACUUM",
    "REINDEX customers",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SELECT * FROM customers; DROP TABLE customers;",
    "SELECT 1; SELECT 2",
    "",
    "   ",
]


@pytest.mark.parametrize("query", UNSAFE_QUERIES)
def test_validate_rejects_unsafe_queries(query):
    with pytest.raises(SQLValidationError):
        validate_read_only_sql(query)


def test_validation_error_message_names_the_bad_keyword():
    # DROP here is not the query's first word (that check is covered by
    # test_validate_rejects_unsafe_queries above); this exercises the
    # keyword scan itself and the message it produces.
    with pytest.raises(SQLValidationError, match="DROP"):
        validate_read_only_sql("SELECT * FROM customers WHERE DROP = 1")


# ---------------------------------------------------------------------------
# execute_read_only_query: SAFE queries against a seeded temp database
# ---------------------------------------------------------------------------


def test_execute_simple_select(seeded_db_path):
    result = execute_read_only_query(
        "SELECT * FROM customers", database_path=seeded_db_path
    )
    assert "id" in result["columns"]
    assert "email" in result["columns"]
    assert result["row_count"] == 100
    assert result["truncated"] is False


def test_execute_join_query(seeded_db_path):
    result = execute_read_only_query(
        "SELECT c.first_name, o.status FROM customers c "
        "JOIN orders o ON o.customer_id = c.id",
        max_rows=10,
        database_path=seeded_db_path,
    )
    assert result["columns"] == ["first_name", "status"]
    assert result["row_count"] == 10


def test_execute_aggregation(seeded_db_path):
    result = execute_read_only_query(
        "SELECT COUNT(*) AS n FROM orders", database_path=seeded_db_path
    )
    assert result["rows"][0][0] > 0


def test_execute_group_by(seeded_db_path):
    result = execute_read_only_query(
        "SELECT status, COUNT(*) FROM orders GROUP BY status",
        database_path=seeded_db_path,
    )
    assert result["row_count"] == 4


def test_execute_cte_with_clause(seeded_db_path):
    result = execute_read_only_query(
        "WITH totals AS ("
        "  SELECT customer_id, COUNT(*) AS n FROM orders GROUP BY customer_id"
        ") SELECT * FROM totals ORDER BY n DESC LIMIT 3",
        database_path=seeded_db_path,
    )
    assert result["row_count"] == 3
    assert result["columns"] == ["customer_id", "n"]


def test_execute_filtering_with_where(seeded_db_path):
    result = execute_read_only_query(
        "SELECT * FROM orders WHERE status = 'cancelled'",
        database_path=seeded_db_path,
    )
    assert result["row_count"] > 0


def test_execute_order_by(seeded_db_path):
    result = execute_read_only_query(
        "SELECT price FROM products ORDER BY price DESC", database_path=seeded_db_path
    )
    prices = [row[0] for row in result["rows"]]
    assert prices == sorted(prices, reverse=True)


def test_execute_limit(seeded_db_path):
    result = execute_read_only_query(
        "SELECT * FROM products LIMIT 3", database_path=seeded_db_path
    )
    assert result["row_count"] == 3
    assert result["truncated"] is False


def test_results_contain_column_names(seeded_db_path):
    result = execute_read_only_query(
        "SELECT id, name, category FROM products LIMIT 1",
        database_path=seeded_db_path,
    )
    assert result["columns"] == ["id", "name", "category"]


# ---------------------------------------------------------------------------
# execute_read_only_query: execution time metadata (observability)
# ---------------------------------------------------------------------------


def test_execution_time_ms_is_present_and_non_negative(seeded_db_path):
    result = execute_read_only_query(
        "SELECT * FROM customers", database_path=seeded_db_path
    )
    assert "execution_time_ms" in result
    assert isinstance(result["execution_time_ms"], float)
    assert result["execution_time_ms"] >= 0


def test_execution_time_ms_does_not_replace_existing_fields(seeded_db_path):
    result = execute_read_only_query(
        "SELECT * FROM customers", database_path=seeded_db_path
    )
    assert set(result.keys()) == {
        "columns", "rows", "row_count", "truncated", "execution_time_ms",
    }


# ---------------------------------------------------------------------------
# execute_read_only_query: max_rows truncation
# ---------------------------------------------------------------------------


def test_max_rows_truncation(seeded_db_path):
    result = execute_read_only_query(
        "SELECT * FROM order_items", max_rows=10, database_path=seeded_db_path
    )
    assert result["row_count"] == 10
    assert result["truncated"] is True


def test_default_max_rows_is_100(seeded_db_path):
    result = execute_read_only_query(
        "SELECT * FROM order_items", database_path=seeded_db_path
    )
    assert result["row_count"] == 100
    assert result["truncated"] is True


def test_max_rows_not_truncated_when_result_is_smaller(seeded_db_path):
    result = execute_read_only_query(
        "SELECT * FROM products", max_rows=1000, database_path=seeded_db_path
    )
    assert result["row_count"] == 30
    assert result["truncated"] is False


def test_invalid_max_rows_is_rejected(seeded_db_path):
    with pytest.raises(SQLValidationError):
        execute_read_only_query(
            "SELECT * FROM products", max_rows=0, database_path=seeded_db_path
        )


# ---------------------------------------------------------------------------
# execute_read_only_query: UNSAFE queries are rejected and the database is
# left completely unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", UNSAFE_QUERIES)
def test_execute_rejects_unsafe_queries_and_db_is_unchanged(seeded_db_path, query):
    before = _row_counts(seeded_db_path)

    with pytest.raises(SQLValidationError):
        execute_read_only_query(query, database_path=seeded_db_path)

    assert _row_counts(seeded_db_path) == before


# ---------------------------------------------------------------------------
# Error handling: malformed SQL, unknown tables/columns, missing database
# ---------------------------------------------------------------------------


def test_malformed_sql_raises_execution_error(seeded_db_path):
    with pytest.raises(SQLExecutionError):
        execute_read_only_query("SELECT * FRM customers", database_path=seeded_db_path)


def test_unknown_table_raises_execution_error(seeded_db_path):
    with pytest.raises(SQLExecutionError):
        execute_read_only_query(
            "SELECT * FROM not_a_real_table", database_path=seeded_db_path
        )


def test_unknown_column_raises_execution_error(seeded_db_path):
    with pytest.raises(SQLExecutionError):
        execute_read_only_query(
            "SELECT not_a_real_column FROM customers", database_path=seeded_db_path
        )


def test_missing_database_file_raises_execution_error(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.db")
    with pytest.raises(SQLExecutionError):
        execute_read_only_query("SELECT 1", database_path=missing_path)


# ---------------------------------------------------------------------------
# Defense in depth: the read-only connection itself must refuse writes,
# schema changes, PRAGMAs, and ATTACH even if text validation is bypassed
# entirely (e.g. a future caller uses get_read_only_connection() directly).
# ---------------------------------------------------------------------------


def test_read_only_connection_rejects_writes_even_without_validation(seeded_db_path):
    before = _row_counts(seeded_db_path)

    connection = get_read_only_connection(seeded_db_path)
    try:
        with pytest.raises(sqlite3.Error):
            connection.execute("DELETE FROM customers")
    finally:
        connection.close()

    assert _row_counts(seeded_db_path) == before


def test_read_only_connection_rejects_attach(seeded_db_path):
    connection = get_read_only_connection(seeded_db_path)
    try:
        with pytest.raises(sqlite3.Error):
            connection.execute("ATTACH DATABASE ':memory:' AS other")
    finally:
        connection.close()


def test_read_only_connection_rejects_pragma_writes(seeded_db_path):
    connection = get_read_only_connection(seeded_db_path)
    try:
        with pytest.raises(sqlite3.Error):
            connection.execute("PRAGMA journal_mode = DELETE")
    finally:
        connection.close()


def test_read_only_connection_blocks_pragma_statements_outright(seeded_db_path):
    # The authorizer denies PRAGMA entirely (not just PRAGMAs that write),
    # so even a purely informational PRAGMA cannot run through this
    # connection — a stricter guarantee than allowing "safe" PRAGMAs.
    connection = get_read_only_connection(seeded_db_path)
    try:
        with pytest.raises(sqlite3.Error):
            connection.execute("PRAGMA query_only")
    finally:
        connection.close()
