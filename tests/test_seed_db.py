import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from database.init_db import get_connection
from database.seed_db import MAX_ORDERS, MIN_ORDERS, NUM_CUSTOMERS, seed_database


@pytest.fixture
def seeded_db_path(tmp_path) -> str:
    db_path = str(tmp_path / "test_ecommerce.db")
    seed_database(db_path)
    return db_path


def _count(connection: sqlite3.Connection, table: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------------------
# Basic population checks
# ---------------------------------------------------------------------------


def test_customers_contain_data(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        assert _count(connection, "customers") == NUM_CUSTOMERS
    finally:
        connection.close()


def test_products_contain_data(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        assert _count(connection, "products") == 30
    finally:
        connection.close()


def test_orders_contain_data(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        order_count = _count(connection, "orders")
        assert MIN_ORDERS <= order_count <= MAX_ORDERS
    finally:
        connection.close()


def test_order_items_contain_data(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        assert _count(connection, "order_items") > 0
    finally:
        connection.close()


def test_most_orders_have_between_one_and_five_items(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        rows = connection.execute(
            "SELECT COUNT(*) FROM order_items GROUP BY order_id"
        ).fetchall()
    finally:
        connection.close()

    item_counts = [row[0] for row in rows]
    assert all(1 <= count <= 5 for count in item_counts)


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


def test_foreign_key_relationships_remain_valid(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()

    assert violations == []


def test_no_orphan_order_customer_ids(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        orphans = connection.execute(
            """
            SELECT COUNT(*) FROM orders o
            LEFT JOIN customers c ON c.id = o.customer_id
            WHERE c.id IS NULL
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert orphans == 0


def test_no_orphan_order_item_references(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        orphans = connection.execute(
            """
            SELECT COUNT(*) FROM order_items oi
            LEFT JOIN orders o ON o.id = oi.order_id
            LEFT JOIN products p ON p.id = oi.product_id
            WHERE o.id IS NULL OR p.id IS NULL
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert orphans == 0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_seeding_twice_does_not_duplicate_records(tmp_path):
    db_path = str(tmp_path / "idempotent.db")

    first_run_inserted = seed_database(db_path)
    connection = get_connection(db_path)
    try:
        counts_after_first_run = {
            table: _count(connection, table)
            for table in ("customers", "products", "orders", "order_items")
        }
    finally:
        connection.close()

    second_run_inserted = seed_database(db_path)
    connection = get_connection(db_path)
    try:
        counts_after_second_run = {
            table: _count(connection, table)
            for table in ("customers", "products", "orders", "order_items")
        }
    finally:
        connection.close()

    assert first_run_inserted is True
    assert second_run_inserted is False
    assert counts_after_first_run == counts_after_second_run


# ---------------------------------------------------------------------------
# Concurrency: two (or more) seeders racing to bootstrap the same fresh
# database, simulating e.g. two Streamlit Community Cloud workers starting
# up together. seed_database() opens its own connection per call, so
# threads with independent connections faithfully exercise the same
# SQLite file-locking path that separate OS processes would.
# ---------------------------------------------------------------------------


def _all_table_counts(db_path: str) -> dict:
    connection = get_connection(db_path)
    try:
        return {
            table: _count(connection, table)
            for table in ("customers", "products", "orders", "order_items")
        }
    finally:
        connection.close()


def test_concurrent_seed_calls_do_not_raise_unique_constraint_errors(tmp_path):
    db_path = str(tmp_path / "concurrent.db")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(seed_database, db_path) for _ in range(2)]
        # .result() re-raises any exception the thread hit (e.g. a
        # UNIQUE constraint failure), so this fails loudly if the race
        # is not actually prevented.
        results = [future.result() for future in futures]

    assert sorted(results) == [False, True]


def test_concurrent_seed_calls_produce_exactly_one_deterministic_dataset(tmp_path):
    db_path = str(tmp_path / "concurrent.db")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(seed_database, db_path) for _ in range(2)]
        for future in futures:
            future.result()

    counts = _all_table_counts(db_path)
    assert counts["customers"] == NUM_CUSTOMERS
    assert counts["products"] == 30
    assert MIN_ORDERS <= counts["orders"] <= MAX_ORDERS
    assert counts["order_items"] > 0


def test_concurrent_seeding_matches_sequential_seeding_row_counts(tmp_path):
    """Proves concurrency doesn't duplicate orders/order_items either,
    by comparing against a plain single sequential seed of the same
    deterministic dataset."""
    sequential_db_path = str(tmp_path / "sequential.db")
    seed_database(sequential_db_path)
    sequential_counts = _all_table_counts(sequential_db_path)

    concurrent_db_path = str(tmp_path / "concurrent.db")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(seed_database, concurrent_db_path) for _ in range(2)]
        for future in futures:
            future.result()
    concurrent_counts = _all_table_counts(concurrent_db_path)

    assert concurrent_counts == sequential_counts


def test_higher_concurrency_still_seeds_exactly_once(tmp_path):
    """Five simultaneous bootstrap attempts against one fresh database."""
    db_path = str(tmp_path / "many_concurrent.db")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(seed_database, db_path) for _ in range(5)]
        results = [future.result() for future in futures]

    assert results.count(True) == 1
    assert results.count(False) == 4
    assert _all_table_counts(db_path)["customers"] == NUM_CUSTOMERS


# ---------------------------------------------------------------------------
# Analytical / business-question verification queries.
#
# These double as documentation of the SQL an analyst (or, later, the AI
# agent) would run against this dataset.
# ---------------------------------------------------------------------------


def test_total_revenue_from_completed_orders(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        total_revenue = connection.execute(
            """
            SELECT SUM(oi.quantity * oi.unit_price)
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.status = 'completed'
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert total_revenue is not None
    assert total_revenue > 0


def test_top_5_products_by_revenue(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        rows = connection.execute(
            """
            SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE o.status = 'completed'
            GROUP BY p.id
            ORDER BY revenue DESC
            LIMIT 5
            """
        ).fetchall()
    finally:
        connection.close()

    assert len(rows) == 5
    revenues = [row[1] for row in rows]
    assert revenues == sorted(revenues, reverse=True)
    assert all(revenue > 0 for revenue in revenues)


def test_revenue_by_category_varies(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        rows = connection.execute(
            """
            SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN products p ON p.id = oi.product_id
            WHERE o.status = 'completed'
            GROUP BY p.category
            ORDER BY revenue DESC
            """
        ).fetchall()
    finally:
        connection.close()

    categories = {row[0] for row in rows}
    assert categories == {"Electronics", "Home", "Office", "Sports", "Accessories"}
    revenues = [row[1] for row in rows]
    # Revenue should not be perfectly uniform across categories.
    assert len(set(revenues)) > 1


def test_top_customers_by_spending(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        rows = connection.execute(
            """
            SELECT c.id, SUM(oi.quantity * oi.unit_price) AS spending
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            JOIN customers c ON c.id = o.customer_id
            WHERE o.status = 'completed'
            GROUP BY c.id
            ORDER BY spending DESC
            LIMIT 10
            """
        ).fetchall()
    finally:
        connection.close()

    assert len(rows) == 10
    spending_values = [row[1] for row in rows]
    assert spending_values == sorted(spending_values, reverse=True)


def test_monthly_sales_trend_covers_multiple_months(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        rows = connection.execute(
            """
            SELECT strftime('%Y-%m', order_date) AS month,
                   SUM(oi.quantity * oi.unit_price) AS revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.status = 'completed'
            GROUP BY month
            ORDER BY month
            """
        ).fetchall()
    finally:
        connection.close()

    # Orders are generated across a fixed 12-month window.
    assert len(rows) == 12
    revenues = [row[1] for row in rows]
    assert len(set(revenues)) > 1


def test_average_completed_order_value(seeded_db_path):
    connection = get_connection(seeded_db_path)
    try:
        avg_order_value = connection.execute(
            """
            SELECT AVG(order_total)
            FROM (
                SELECT o.id, SUM(oi.quantity * oi.unit_price) AS order_total
                FROM orders o
                JOIN order_items oi ON oi.order_id = o.id
                WHERE o.status = 'completed'
                GROUP BY o.id
            )
            """
        ).fetchone()[0]
    finally:
        connection.close()

    assert avg_order_value is not None
    assert avg_order_value > 0
