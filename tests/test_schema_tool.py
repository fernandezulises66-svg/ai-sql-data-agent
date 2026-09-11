import sqlite3

import pytest

from database.init_db import init_db
from database.seed_db import seed_database
from tools.schema_tool import (
    SchemaToolError,
    format_schema_for_llm,
    get_database_schema,
)

EXPECTED_TABLES = {"customers", "products", "orders", "order_items"}


@pytest.fixture
def seeded_db_path(tmp_path) -> str:
    db_path = str(tmp_path / "test_ecommerce.db")
    seed_database(db_path)
    return db_path


def _tables_by_name(schema: dict) -> dict:
    return {table["name"]: table for table in schema["tables"]}


# ---------------------------------------------------------------------------
# Table / column detection
# ---------------------------------------------------------------------------


def test_all_four_ecommerce_tables_are_detected(seeded_db_path):
    schema = get_database_schema(seeded_db_path)

    table_names = {table["name"] for table in schema["tables"]}
    assert table_names == EXPECTED_TABLES


def test_expected_columns_are_returned_for_customers(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    customers = _tables_by_name(schema)["customers"]

    column_names = {column["name"] for column in customers["columns"]}
    assert column_names == {"id", "first_name", "last_name", "email", "city", "created_at"}


def test_expected_columns_are_returned_for_order_items(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    order_items = _tables_by_name(schema)["order_items"]

    column_names = {column["name"] for column in order_items["columns"]}
    assert column_names == {"id", "order_id", "product_id", "quantity", "unit_price"}


def test_column_not_null_flags_are_correct(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    customers = _tables_by_name(schema)["customers"]
    columns_by_name = {c["name"]: c for c in customers["columns"]}

    assert columns_by_name["first_name"]["not_null"] is True
    assert columns_by_name["email"]["not_null"] is True
    assert columns_by_name["city"]["not_null"] is False


def test_column_types_are_returned(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    products = _tables_by_name(schema)["products"]
    columns_by_name = {c["name"]: c for c in products["columns"]}

    assert columns_by_name["price"]["type"] == "REAL"
    assert columns_by_name["stock"]["type"] == "INTEGER"
    assert columns_by_name["name"]["type"] == "TEXT"


# ---------------------------------------------------------------------------
# Primary keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", ["customers", "products", "orders", "order_items"])
def test_primary_keys_are_detected(seeded_db_path, table_name):
    schema = get_database_schema(seeded_db_path)
    table = _tables_by_name(schema)[table_name]

    assert table["primary_key"] == ["id"]
    id_column = next(c for c in table["columns"] if c["name"] == "id")
    assert id_column["primary_key"] is True


# ---------------------------------------------------------------------------
# Foreign keys
# ---------------------------------------------------------------------------


def test_orders_foreign_key_references_customers(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    orders = _tables_by_name(schema)["orders"]

    assert orders["foreign_keys"] == [
        {"column": "customer_id", "references_table": "customers", "references_column": "id"}
    ]


def test_order_items_foreign_keys_reference_orders_and_products(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    order_items = _tables_by_name(schema)["order_items"]

    fk_columns = {fk["column"]: fk for fk in order_items["foreign_keys"]}
    assert fk_columns["order_id"]["references_table"] == "orders"
    assert fk_columns["order_id"]["references_column"] == "id"
    assert fk_columns["product_id"]["references_table"] == "products"
    assert fk_columns["product_id"]["references_column"] == "id"


def test_customers_and_products_have_no_foreign_keys(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    tables = _tables_by_name(schema)

    assert tables["customers"]["foreign_keys"] == []
    assert tables["products"]["foreign_keys"] == []


# ---------------------------------------------------------------------------
# Unique constraints / indexes
# ---------------------------------------------------------------------------


def test_customers_email_unique_index_is_detected(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    customers = _tables_by_name(schema)["customers"]

    unique_single_column_indexes = [
        index for index in customers["indexes"]
        if index["unique"] and index["columns"] == ["email"]
    ]
    assert len(unique_single_column_indexes) == 1


def test_order_items_composite_unique_constraint_is_detected(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    order_items = _tables_by_name(schema)["order_items"]

    unique_composite_indexes = [
        index for index in order_items["indexes"]
        if index["unique"] and set(index["columns"]) == {"order_id", "product_id"}
    ]
    assert len(unique_composite_indexes) == 1


# ---------------------------------------------------------------------------
# Schema is read live from the database, not hardcoded
# ---------------------------------------------------------------------------


def test_schema_reflects_a_custom_database_not_the_ecommerce_schema(tmp_path):
    db_path = str(tmp_path / "custom.db")
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE widgets ("
            "  widget_id INTEGER PRIMARY KEY,"
            "  label TEXT NOT NULL,"
            "  factory_id INTEGER,"
            "  FOREIGN KEY (factory_id) REFERENCES factories (id)"
            ")"
        )
        connection.execute("CREATE TABLE factories (id INTEGER PRIMARY KEY, name TEXT)")
        connection.commit()
    finally:
        connection.close()

    schema = get_database_schema(db_path)
    table_names = {table["name"] for table in schema["tables"]}

    assert table_names == {"widgets", "factories"}
    widgets = _tables_by_name(schema)["widgets"]
    assert {c["name"] for c in widgets["columns"]} == {"widget_id", "label", "factory_id"}
    assert widgets["foreign_keys"] == [
        {"column": "factory_id", "references_table": "factories", "references_column": "id"}
    ]


# ---------------------------------------------------------------------------
# Internal SQLite tables are excluded
# ---------------------------------------------------------------------------


def test_internal_sqlite_tables_are_excluded(seeded_db_path):
    # The seeded database uses AUTOINCREMENT, which creates sqlite_sequence.
    connection = sqlite3.connect(seeded_db_path)
    try:
        internal_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        connection.close()
    assert internal_tables, "test setup expects sqlite_sequence to exist"

    schema = get_database_schema(seeded_db_path)
    table_names = {table["name"] for table in schema["tables"]}

    assert not any(name.startswith("sqlite_") for name in table_names)


# ---------------------------------------------------------------------------
# Empty database / no application tables
# ---------------------------------------------------------------------------


def test_empty_database_returns_no_tables(tmp_path):
    db_path = str(tmp_path / "empty.db")
    connection = sqlite3.connect(db_path)
    connection.close()

    schema = get_database_schema(db_path)

    assert schema == {"tables": []}


def test_initialized_but_unseeded_database_has_expected_tables(tmp_path):
    db_path = str(tmp_path / "initialized.db")
    init_db(db_path)

    schema = get_database_schema(db_path)
    table_names = {table["name"] for table in schema["tables"]}

    assert table_names == EXPECTED_TABLES


def test_database_with_only_internal_tables_has_no_application_tables(tmp_path):
    db_path = str(tmp_path / "internal_only.db")
    connection = sqlite3.connect(db_path)
    try:
        # AUTOINCREMENT forces SQLite to create sqlite_sequence with no
        # other application tables defined.
        connection.execute("CREATE TABLE placeholder (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        connection.execute("DROP TABLE placeholder")
        connection.commit()
    finally:
        connection.close()

    schema = get_database_schema(db_path)

    assert schema == {"tables": []}


# ---------------------------------------------------------------------------
# Missing database file
# ---------------------------------------------------------------------------


def test_missing_database_file_raises_schema_tool_error(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.db")
    with pytest.raises(SchemaToolError):
        get_database_schema(missing_path)


# ---------------------------------------------------------------------------
# format_schema_for_llm: determinism and content
# ---------------------------------------------------------------------------


def test_formatted_output_is_deterministic(seeded_db_path):
    schema_a = get_database_schema(seeded_db_path)
    schema_b = get_database_schema(seeded_db_path)

    assert format_schema_for_llm(schema_a) == format_schema_for_llm(schema_b)


def test_formatted_output_is_stable_across_multiple_calls(seeded_db_path):
    schema = get_database_schema(seeded_db_path)

    first = format_schema_for_llm(schema)
    second = format_schema_for_llm(schema)
    assert first == second


def test_formatted_output_contains_table_and_column_lines(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    text = format_schema_for_llm(schema)

    assert "TABLE customers" in text
    assert "- id INTEGER PRIMARY KEY" in text
    assert "- first_name TEXT NOT NULL" in text
    assert "- email TEXT NOT NULL UNIQUE" in text


def test_formatted_output_contains_foreign_key_lines(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    text = format_schema_for_llm(schema)

    assert "FOREIGN KEY: customer_id -> customers.id" in text
    assert "FOREIGN KEY: order_id -> orders.id" in text
    assert "FOREIGN KEY: product_id -> products.id" in text


def test_formatted_output_orders_table_matches_expected_style(seeded_db_path):
    schema = get_database_schema(seeded_db_path)
    text = format_schema_for_llm(schema)

    expected_block = (
        "TABLE orders\n"
        "- id INTEGER PRIMARY KEY\n"
        "- customer_id INTEGER NOT NULL\n"
        "- order_date TEXT NOT NULL\n"
        "- status TEXT NOT NULL\n"
        "FOREIGN KEY: customer_id -> customers.id"
    )
    assert expected_block in text


def test_format_schema_for_llm_handles_no_tables():
    text = format_schema_for_llm({"tables": []})
    assert text == "No application tables found in the database."
