"""Deployment-safe database bootstrap for the AI SQL Data Analyst Agent.

Locally, a developer runs `python -m database.init_db` and
`python -m database.seed_db` once before starting the app. A fresh
deployment (e.g. Streamlit Community Cloud cloning this repository from
GitHub) has neither step done for it: `data/ecommerce.db` is
intentionally gitignored and never committed, so it simply doesn't exist
yet on a new deployment.

This module gives the deployed app one small, safe entry point to
prepare that database automatically. It reuses the existing, already
idempotent `init_db()` and `seed_database()` exactly as the local
workflow does — no schema creation or sample-data generation logic is
duplicated here.
"""

from __future__ import annotations

from database.init_db import get_database_path, init_db
from database.seed_db import seed_database


def ensure_sample_database(database_path: str | None = None) -> str:
    """Make sure a seeded sample database exists at database_path.

    1. Resolves the configured DATABASE_PATH (env var, or the default)
       if database_path isn't given explicitly.
    2. Ensures the schema exists (init_db's "CREATE ... IF NOT EXISTS"
       statements make this a no-op on an already-initialized database).
    3. Ensures the deterministic sample dataset exists (seed_database is
       a no-op if the customers table already has rows).

    Safe to call on every application startup — repeated calls neither
    fail nor duplicate data. Returns the resolved database path.
    """
    database_path = database_path or get_database_path()
    init_db(database_path)
    seed_database(database_path)
    return database_path


if __name__ == "__main__":
    resolved_path = ensure_sample_database()
    print(f"Sample database ready at: {resolved_path}")
