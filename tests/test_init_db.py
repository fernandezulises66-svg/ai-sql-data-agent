import sqlite3
from pathlib import Path

import pytest

from database.init_db import get_connection, init_db

EXPECTED_TABLES = {"customers", "products", "orders", "order_items"}


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test_ecommerce.db")


def test_init_db_creates_database_file(db_path):
    init_db(db_path)

    assert Path(db_path).exists()


def test_init_db_creates_all_expected_tables(db_path):
    init_db(db_path)

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    finally:
        connection.close()

    table_names = {row[0] for row in rows}
    assert EXPECTED_TABLES.issubset(table_names)


def test_init_db_is_idempotent(db_path):
    init_db(db_path)
    init_db(db_path)  # running again must not fail or duplicate tables

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'customers'"
        ).fetchall()
    finally:
        connection.close()

    assert len(rows) == 1


def test_foreign_keys_are_enabled_on_connection(db_path):
    init_db(db_path)

    connection = get_connection(db_path)
    try:
        enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        connection.close()

    assert enabled == 1


def test_orders_foreign_key_references_customers(db_path):
    init_db(db_path)

    connection = sqlite3.connect(db_path)
    try:
        fk_list = connection.execute("PRAGMA foreign_key_list(orders)").fetchall()
    finally:
        connection.close()

    referenced_tables = {fk[2] for fk in fk_list}
    assert referenced_tables == {"customers"}


def test_order_items_foreign_keys_reference_orders_and_products(db_path):
    init_db(db_path)

    connection = sqlite3.connect(db_path)
    try:
        fk_list = connection.execute(
            "PRAGMA foreign_key_list(order_items)"
        ).fetchall()
    finally:
        connection.close()

    referenced_tables = {fk[2] for fk in fk_list}
    assert referenced_tables == {"orders", "products"}
