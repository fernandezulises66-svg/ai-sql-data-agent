# AI SQL Data Analyst Agent

## Problem

Business users often need answers from data (sales, customers, orders)
but don't know SQL. This project aims to build an AI agent that accepts
natural language business questions, translates them into safe, read-only
SQL queries, executes them against a database, and returns clear,
business-oriented answers.

## Planned Tech Stack

- Python 3.11+
- SQLite
- OpenAI API / tool calling
- Streamlit
- pytest

## Current Status

🚧 In development. The relational database schema (customers, products,
orders, order_items) is implemented and initializable via
`database/init_db.py`, and it can be populated with a realistic,
deterministic sample dataset via `database/seed_db.py`. A safe, read-only
SQL execution layer (`tools/sql_tool.py`) can now validate and run
analytical SQL against that database, and `tools/schema_tool.py` can
introspect the database's actual schema into a structured, LLM-friendly
description. No AI agent logic, OpenAI integration, or user interface
has been implemented yet. Development proceeds incrementally, one
feature per iteration.

## Project Structure

```
ai-sql-data-agent/
├── app.py                 # Entry point (placeholder)
├── agent/                 # AI agent logic (not yet implemented)
├── database/               # Database setup and access
│   ├── schema.sql          # SQLite schema: customers, products, orders, order_items
│   ├── init_db.py          # Creates the SQLite database from schema.sql
│   └── seed_db.py          # Populates the database with deterministic sample data
├── tools/                  # Agent tools
│   ├── sql_tool.py         # Safe, read-only SQL validation and execution
│   └── schema_tool.py      # Database schema introspection for prompts
├── tests/                   # pytest test suite
├── data/                    # Local database files (not committed)
├── .env.example             # Template for required environment variables
└── requirements.txt
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env` with real values locally. Never commit `.env`.

## Database

Initialize the SQLite database (creates it at `DATABASE_PATH`, or
`data/ecommerce.db` by default, if it doesn't already exist):

```bash
python -m database.init_db
```

Inspect it with the `sqlite3` CLI:

```bash
sqlite3 data/ecommerce.db ".tables"
sqlite3 data/ecommerce.db ".schema"
```

### Sample data

Populate the database with a realistic, deterministic sample dataset
(~100 customers, 30 products, 500-800 orders, and their order items,
spread across a fixed 12-month period):

```bash
python -m database.seed_db
```

The dataset uses a fixed random seed and a fixed calendar year, so every
run generates identical data. Seeding is idempotent: if the `customers`
table already has rows, `seed_db.py` skips seeding instead of inserting
duplicates. To regenerate the dataset from scratch, delete the database
file and re-run both commands above.

The data is intentionally non-uniform so it supports meaningful
analysis: some products sell far better than others, a subset of
customers place many more orders than average, revenue varies by
category and by month, and a portion of orders are `cancelled` (most are
`completed`).

Example verification queries (also encoded as assertions in
`tests/test_seed_db.py`):

```sql
-- Total revenue from completed orders
SELECT SUM(oi.quantity * oi.unit_price)
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE o.status = 'completed';

-- Top 5 products by revenue
SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
WHERE o.status = 'completed'
GROUP BY p.id
ORDER BY revenue DESC
LIMIT 5;

-- Revenue by category
SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
WHERE o.status = 'completed'
GROUP BY p.category
ORDER BY revenue DESC;

-- Top customers by spending
SELECT c.first_name, c.last_name, SUM(oi.quantity * oi.unit_price) AS spending
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
JOIN customers c ON c.id = o.customer_id
WHERE o.status = 'completed'
GROUP BY c.id
ORDER BY spending DESC
LIMIT 10;

-- Monthly sales trend
SELECT strftime('%Y-%m', o.order_date) AS month,
       SUM(oi.quantity * oi.unit_price) AS revenue
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE o.status = 'completed'
GROUP BY month
ORDER BY month;

-- Average completed order value
SELECT AVG(order_total) FROM (
    SELECT o.id, SUM(oi.quantity * oi.unit_price) AS order_total
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.id
    WHERE o.status = 'completed'
    GROUP BY o.id
);
```

### Safe, read-only SQL execution

`tools/sql_tool.py` is the only supported way to run SQL against the
database. It is built so that this database can never be modified through
it, even by a mistake in generated SQL, using three independent layers:

1. **Text validation** (`validate_read_only_sql`) — only a single SELECT
   statement (optionally starting with a `WITH`/CTE clause) is allowed;
   empty input, multiple statements, and statements such as `INSERT`,
   `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `REPLACE`, `TRUNCATE`,
   `VACUUM`, `ATTACH`, `DETACH`, `PRAGMA`, `REINDEX`, `BEGIN`, `COMMIT`,
   and `ROLLBACK` are rejected with a clear error.
2. **Read-only connection** — the database is opened with a
   `file:...?mode=ro` URI plus `PRAGMA query_only = ON`, so SQLite itself
   refuses writes regardless of the SQL text.
3. **SQLite authorizer** — `sqlite3.Connection.set_authorizer` allow-lists
   only the actions a plain SELECT needs and denies everything else
   (writes, schema changes, `ATTACH`, `PRAGMA`, transaction control),
   independent of what the text validator decided.

```python
from tools.sql_tool import execute_read_only_query

result = execute_read_only_query(
    "SELECT status, COUNT(*) FROM orders GROUP BY status",
    max_rows=100,
)
# {"columns": [...], "rows": [...], "row_count": 4, "truncated": False}
```

This layer does not yet decide *what* SQL to run — that's for the AI
agent in a later iteration.

### Schema introspection

`tools/schema_tool.py` reads the database's actual structure with
SQLite's own introspection PRAGMAs (`table_info`, `foreign_key_list`,
`index_list`) rather than duplicating the schema by hand in Python, so
the description a future AI agent sees always matches the real database.

```python
from tools.schema_tool import get_database_schema, format_schema_for_llm

schema = get_database_schema()          # {"tables": [...]} structured metadata
print(format_schema_for_llm(schema))     # concise text for a prompt
```

```
TABLE orders
- id INTEGER PRIMARY KEY
- customer_id INTEGER NOT NULL
- order_date TEXT NOT NULL
- status TEXT NOT NULL
FOREIGN KEY: customer_id -> customers.id
```

It uses its own dedicated read-only connection (`mode=ro` +
`PRAGMA query_only = ON`) rather than `sql_tool.py`'s connection, because
that one's authorizer denies PRAGMA statements outright — this module
only ever runs a small, fixed set of hardcoded introspection PRAGMAs, so
`sql_tool.py`'s stricter, agent-facing security model is left untouched.

Run the test suite:

```bash
pytest
```
