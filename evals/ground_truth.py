"""Trusted, hand-written SQL for computing expected evaluation answers.

These queries are deliberately kept separate from
agent/data_analyst_agent.py: the agent's instructions never see them, so
the agent must independently arrive at the same answer by writing and
running its own SQL. Ground truth is never computed using the AI agent
itself — only plain, explicit SQL written for this evaluation suite.

Execution goes through tools.sql_tool.execute_read_only_query, the same
safe, read-only layer the agent uses, so these queries never modify the
database either.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from typing import Callable

from tools.sql_tool import execute_read_only_query


class GroundTruthError(RuntimeError):
    """Raised when ground truth can't be computed (e.g. an empty database)."""


@dataclass(frozen=True)
class GroundTruth:
    """Deterministic expected characteristics for one evaluation case.

    expected_entities: names that should all appear (case-insensitively)
        somewhere in the agent's answer.
    expected_numeric: a single reference number the answer should contain
        something reasonably close to (see evals/checks.py's tolerance).
    """

    expected_entities: tuple[str, ...] = ()
    expected_numeric: float | None = None


def _first_row(result: dict, case_id: str) -> tuple:
    rows = result["rows"]
    if not rows:
        raise GroundTruthError(
            f"Ground truth query for '{case_id}' returned no rows — is the "
            "database seeded? (python -m database.seed_db)"
        )
    return rows[0]


def _top_product_by_revenue(database_path: str | None) -> GroundTruth:
    result = execute_read_only_query(
        """
        SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN products p ON p.id = oi.product_id
        WHERE o.status = 'completed'
        GROUP BY p.id
        ORDER BY revenue DESC
        LIMIT 1
        """,
        database_path=database_path,
    )
    name, revenue = _first_row(result, "top_products_revenue")
    return GroundTruth(expected_entities=(name,), expected_numeric=float(revenue))


def _top_category_by_revenue(database_path: str | None) -> GroundTruth:
    result = execute_read_only_query(
        """
        SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN products p ON p.id = oi.product_id
        WHERE o.status = 'completed'
        GROUP BY p.category
        ORDER BY revenue DESC
        LIMIT 1
        """,
        database_path=database_path,
    )
    category, revenue = _first_row(result, "top_category_revenue")
    return GroundTruth(expected_entities=(category,), expected_numeric=float(revenue))


def _top_customer_by_spending(database_path: str | None) -> GroundTruth:
    result = execute_read_only_query(
        """
        SELECT c.first_name, c.last_name, SUM(oi.quantity * oi.unit_price) AS spending
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN customers c ON c.id = o.customer_id
        WHERE o.status = 'completed'
        GROUP BY c.id
        ORDER BY spending DESC
        LIMIT 1
        """,
        database_path=database_path,
    )
    first_name, last_name, spending = _first_row(result, "top_customers_spending")
    return GroundTruth(
        expected_entities=(first_name, last_name), expected_numeric=float(spending)
    )


def _best_sales_month(database_path: str | None) -> GroundTruth:
    result = execute_read_only_query(
        """
        SELECT strftime('%Y-%m', o.order_date) AS month,
               SUM(oi.quantity * oi.unit_price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.status = 'completed'
        GROUP BY month
        ORDER BY revenue DESC
        LIMIT 1
        """,
        database_path=database_path,
    )
    month_key, revenue = _first_row(result, "best_sales_month")
    month_number = int(month_key.split("-")[1])
    month_name = calendar.month_name[month_number]
    return GroundTruth(expected_entities=(month_name,), expected_numeric=float(revenue))


def _average_completed_order_value(database_path: str | None) -> GroundTruth:
    result = execute_read_only_query(
        """
        SELECT AVG(order_total) FROM (
            SELECT o.id, SUM(oi.quantity * oi.unit_price) AS order_total
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.id
            WHERE o.status = 'completed'
            GROUP BY o.id
        )
        """,
        database_path=database_path,
    )
    (avg_value,) = _first_row(result, "average_completed_order_value")
    if avg_value is None:
        raise GroundTruthError("No completed orders found to average.")
    return GroundTruth(expected_numeric=float(avg_value))


def _order_count_by_status(database_path: str | None) -> GroundTruth:
    result = execute_read_only_query(
        "SELECT status, COUNT(*) FROM orders GROUP BY status",
        database_path=database_path,
    )
    statuses = tuple(row[0] for row in result["rows"])
    if not statuses:
        raise GroundTruthError("No orders found to count by status.")
    return GroundTruth(expected_entities=statuses)


def _category_comparison(database_path: str | None) -> GroundTruth:
    result = execute_read_only_query(
        """
        SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN products p ON p.id = oi.product_id
        WHERE o.status = 'completed' AND p.category IN ('Electronics', 'Home')
        GROUP BY p.category
        """,
        database_path=database_path,
    )
    revenues = {category: float(revenue) for category, revenue in result["rows"]}
    if not revenues:
        raise GroundTruthError("No Electronics/Home revenue found to compare.")
    return GroundTruth(
        expected_entities=("Electronics", "Home"),
        expected_numeric=max(revenues.values()),
    )


def _completed_orders_with_electronics(database_path: str | None) -> GroundTruth:
    result = execute_read_only_query(
        """
        SELECT COUNT(DISTINCT o.id)
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id
        JOIN products p ON p.id = oi.product_id
        WHERE o.status = 'completed' AND p.category = 'Electronics'
        """,
        database_path=database_path,
    )
    (count,) = _first_row(result, "multi_join_question")
    return GroundTruth(expected_numeric=float(count))


# Maps EvalCase.id -> a function computing its GroundTruth. Cases not
# listed here (e.g. "unsupported_question", "conversational_question")
# have no objective database answer and are graded differently by the
# runner (see evals/checks.py).
GROUND_TRUTH_BUILDERS: dict[str, Callable[[str | None], GroundTruth]] = {
    "top_products_revenue": _top_product_by_revenue,
    "top_category_revenue": _top_category_by_revenue,
    "top_customers_spending": _top_customer_by_spending,
    "best_sales_month": _best_sales_month,
    "average_completed_order_value": _average_completed_order_value,
    "order_count_by_status": _order_count_by_status,
    "category_comparison": _category_comparison,
    "multi_join_question": _completed_orders_with_electronics,
}


def compute_ground_truth(case_id: str, database_path: str | None = None) -> GroundTruth | None:
    """Return the deterministic ground truth for case_id, or None if not applicable."""
    builder = GROUND_TRUTH_BUILDERS.get(case_id)
    if builder is None:
        return None
    return builder(database_path)
