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

🚧 Early scaffold stage. The project structure has been initialized.
No database schema, AI agent logic, or user interface has been
implemented yet. Development proceeds incrementally, one feature per
iteration.

## Project Structure

```
ai-sql-data-agent/
├── app.py                 # Entry point (placeholder)
├── agent/                 # AI agent logic (not yet implemented)
├── database/               # Database setup and access (not yet implemented)
│   └── init_db.py
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
