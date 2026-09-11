"""CLI for running the AI Data Analyst Agent evaluation suite.

    python -m evals.run_evals

This calls the REAL AI agent for every case (agent/data_analyst_agent.py
-> the OpenAI Agents SDK), which means it makes real OpenAI API calls
and consumes API usage. It requires OPENAI_API_KEY and a seeded database
(python -m database.init_db && python -m database.seed_db) exactly like
app.py does.

pytest never runs this automatically — see tests/test_evals.py for the
(fully mocked) unit tests of the evaluation framework itself.
"""

from __future__ import annotations

import argparse

from evals.eval_cases import EVAL_CASES
from evals.runner import format_report, run_all


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the AI Data Analyst Agent evaluation suite against the real "
            "OpenAI API. This consumes API usage."
        )
    )
    parser.add_argument(
        "--database-path",
        default=None,
        help="Database to evaluate against (defaults to DATABASE_PATH / data/ecommerce.db).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    print(
        "Running evaluation cases against the real AI agent "
        "(this calls the OpenAI API and consumes API usage)...\n"
    )
    results = run_all(EVAL_CASES, database_path=args.database_path)
    print(format_report(results))


if __name__ == "__main__":
    main()
