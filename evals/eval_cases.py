"""Representative evaluation cases for the AI Data Analyst Agent.

Each case is a natural-language business question plus metadata the
evaluation runner needs in order to check the agent's behavior — never a
hardcoded full natural-language answer. Objective expected values (a top
product name, a revenue figure, ...) are computed separately and
deterministically in evals/ground_truth.py, straight from the live
database, not written here or invented by hand.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCase:
    """One evaluation case.

    id: stable identifier; also used to look up ground truth (see
        evals/ground_truth.py's GROUND_TRUTH_BUILDERS).
    question: the natural-language question sent to the agent verbatim.
    category: short analytical-pattern label (for grouping/reporting).
    sql_expected: whether a correct answer requires calling run_sql_query.
    unsupported: True for a question the database schema cannot answer —
        graded differently (the agent must not fabricate a result)
        rather than against ground-truth entities/numbers.
    notes: optional human-readable explanation of what this case checks.
    """

    id: str
    question: str
    category: str
    sql_expected: bool
    unsupported: bool = False
    notes: str = ""


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        id="top_products_revenue",
        question="What are the top 5 products by completed-order revenue?",
        category="revenue",
        sql_expected=True,
        notes="Checks the single highest-revenue product name appears in the answer.",
    ),
    EvalCase(
        id="top_category_revenue",
        question="Which product category generated the most revenue?",
        category="revenue",
        sql_expected=True,
    ),
    EvalCase(
        id="top_customers_spending",
        question="Who are the top 5 customers by spending on completed orders?",
        category="customers",
        sql_expected=True,
    ),
    EvalCase(
        id="best_sales_month",
        question="What was the best sales month in terms of completed-order revenue?",
        category="temporal",
        sql_expected=True,
    ),
    EvalCase(
        id="average_completed_order_value",
        question="What is the average completed order value?",
        category="aggregation",
        sql_expected=True,
    ),
    EvalCase(
        id="order_count_by_status",
        question="How many orders are there for each status?",
        category="aggregation",
        sql_expected=True,
        notes="Expects all status names present, confirming a full breakdown was given.",
    ),
    EvalCase(
        id="category_comparison",
        question="Compare completed-order revenue between the Electronics and Home categories.",
        category="comparison",
        sql_expected=True,
    ),
    EvalCase(
        id="multi_join_question",
        question="How many completed orders included at least one Electronics product?",
        category="joins",
        sql_expected=True,
        notes="Requires joining orders, order_items, and products.",
    ),
    EvalCase(
        id="unsupported_question",
        question="What is the average customer satisfaction rating for each product?",
        category="unsupported",
        sql_expected=False,
        unsupported=True,
        notes="The schema has no rating/review data; the agent must not invent one.",
    ),
    EvalCase(
        id="conversational_question",
        question="Hi! What kinds of business questions can you help me answer?",
        category="conversational",
        sql_expected=False,
        notes="A general question that should not require querying the database.",
    ),
)
