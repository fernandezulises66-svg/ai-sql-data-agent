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
`database/init_db.py`. No AI agent logic, OpenAI integration, sample
data, or user interface has been implemented yet. Development proceeds
incrementally, one feature per iteration.

## Project Structure

```
ai-sql-data-agent/
├── app.py                 # Entry point (placeholder)
├── agent/                 # AI agent logic (not yet implemented)
├── database/               # Database setup and access
│   ├── schema.sql          # SQLite schema: customers, products, orders, order_items
│   └── init_db.py          # Creates the SQLite database from schema.sql
├── tools/                  # Agent tools, e.g. SQL validation (not yet implemented)
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

Run the test suite:

```bash
pytest
```
