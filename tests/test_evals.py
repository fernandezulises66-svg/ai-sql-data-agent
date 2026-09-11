"""Tests for the evaluation framework itself (evals/).

These tests never call the real OpenAI API: run_case/run_all always take
an explicit agent_runner stand-in here, so agent.data_analyst_agent.
Runner.run_sync is never reached. Ground-truth tests run real SQL
against a small, hand-built temporary database so expected values are
exactly known and asserted precisely — no reliance on the large
(randomly generated, if still deterministic) seeded dataset.
"""

import sqlite3

import pytest

from agent.data_analyst_agent import AgentAnswer, SQLToolCallRecord
from database.init_db import init_db
from evals.checks import (
    check_expected_entities,
    check_expected_numeric,
    check_no_fabricated_answer,
    check_sql_usage,
)
from evals.eval_cases import EVAL_CASES, EvalCase
from evals.ground_truth import GroundTruth, GroundTruthError, compute_ground_truth
from evals.runner import EvalSummary, format_report, run_all, run_case


# ---------------------------------------------------------------------------
# Evaluation-case structure
# ---------------------------------------------------------------------------


def test_eval_case_count_is_within_expected_range():
    assert 8 <= len(EVAL_CASES) <= 12


def test_eval_case_ids_are_unique():
    ids = [case.id for case in EVAL_CASES]
    assert len(ids) == len(set(ids))


def test_every_eval_case_has_required_fields():
    for case in EVAL_CASES:
        assert case.id
        assert case.question.strip()
        assert case.category
        assert isinstance(case.sql_expected, bool)
        assert isinstance(case.unsupported, bool)


def test_at_least_one_unsupported_case_exists():
    assert any(case.unsupported for case in EVAL_CASES)


def test_at_least_one_conversational_non_sql_case_exists():
    assert any(
        not case.sql_expected and not case.unsupported for case in EVAL_CASES
    )


def test_at_least_one_case_requires_a_join():
    assert any("join" in case.category.lower() for case in EVAL_CASES)


def test_no_case_hardcodes_a_full_answer_sentence():
    # Cases carry only a question + metadata, never a full expected answer.
    for case in EVAL_CASES:
        assert not hasattr(case, "expected_answer")
        assert not hasattr(case, "answer")


# ---------------------------------------------------------------------------
# Deterministic ground truth, against a small hand-built database
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_db_path(tmp_path) -> str:
    """A minimal database with hand-picked values so expected results are
    unambiguous and can be asserted exactly, independent of the (larger,
    randomly-weighted) seeded sample dataset used elsewhere."""
    db_path = str(tmp_path / "tiny.db")
    init_db(db_path)

    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executemany(
            "INSERT INTO customers (id, first_name, last_name, email, city) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (1, "Alice", "Anders", "alice@example.com", "Austin"),
                (2, "Bob", "Baker", "bob@example.com", "Boston"),
            ],
        )
        connection.executemany(
            "INSERT INTO products (id, name, category, price, stock) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "Widget", "Electronics", 100.0, 10),
                (2, "Gadget", "Home", 10.0, 10),
            ],
        )
        connection.executemany(
            "INSERT INTO orders (id, customer_id, order_date, status) VALUES (?, ?, ?, ?)",
            [
                (1, 1, "2024-01-15 10:00:00", "completed"),  # Widget x1 = 100
                (2, 2, "2024-02-15 10:00:00", "completed"),  # Gadget x5 = 50
                (3, 1, "2024-02-16 10:00:00", "cancelled"),  # Widget x1 = 100, excluded
            ],
        )
        connection.executemany(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
            "VALUES (?, ?, ?, ?)",
            [
                (1, 1, 1, 100.0),
                (2, 2, 5, 10.0),
                (3, 1, 1, 100.0),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    return db_path


def test_ground_truth_top_product(tiny_db_path):
    gt = compute_ground_truth("top_products_revenue", tiny_db_path)
    assert gt.expected_entities == ("Widget",)
    assert gt.expected_numeric == pytest.approx(100.0)


def test_ground_truth_top_category(tiny_db_path):
    gt = compute_ground_truth("top_category_revenue", tiny_db_path)
    assert gt.expected_entities == ("Electronics",)
    assert gt.expected_numeric == pytest.approx(100.0)


def test_ground_truth_top_customer_excludes_cancelled_orders(tiny_db_path):
    gt = compute_ground_truth("top_customers_spending", tiny_db_path)
    # Alice's cancelled order (100) must not count toward her spending,
    # so she should NOT outrank Bob on that basis alone.
    assert gt.expected_entities == ("Alice", "Anders")
    assert gt.expected_numeric == pytest.approx(100.0)


def test_ground_truth_best_sales_month(tiny_db_path):
    gt = compute_ground_truth("best_sales_month", tiny_db_path)
    assert gt.expected_entities == ("January",)
    assert gt.expected_numeric == pytest.approx(100.0)


def test_ground_truth_average_completed_order_value(tiny_db_path):
    gt = compute_ground_truth("average_completed_order_value", tiny_db_path)
    assert gt.expected_numeric == pytest.approx(75.0)  # (100 + 50) / 2


def test_ground_truth_order_count_by_status_only_lists_present_statuses(tiny_db_path):
    gt = compute_ground_truth("order_count_by_status", tiny_db_path)
    assert set(gt.expected_entities) == {"completed", "cancelled"}


def test_ground_truth_category_comparison(tiny_db_path):
    gt = compute_ground_truth("category_comparison", tiny_db_path)
    assert set(gt.expected_entities) == {"Electronics", "Home"}
    assert gt.expected_numeric == pytest.approx(100.0)


def test_ground_truth_multi_join_counts_only_completed_electronics_orders(tiny_db_path):
    gt = compute_ground_truth("multi_join_question", tiny_db_path)
    # Only order 1 is both completed and contains an Electronics product;
    # order 3 has the same product but is cancelled.
    assert gt.expected_numeric == pytest.approx(1.0)


def test_ground_truth_is_none_for_unsupported_and_conversational_cases(tiny_db_path):
    assert compute_ground_truth("unsupported_question", tiny_db_path) is None
    assert compute_ground_truth("conversational_question", tiny_db_path) is None


def test_ground_truth_raises_clear_error_on_empty_database(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_db(db_path)

    with pytest.raises(GroundTruthError):
        compute_ground_truth("top_products_revenue", db_path)


def test_ground_truth_does_not_require_openai_api_key(tiny_db_path, monkeypatch):
    # Ground truth comes from plain, trusted SQL only — never the AI
    # agent — so it must work with no OpenAI configuration at all.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    gt = compute_ground_truth("top_products_revenue", tiny_db_path)

    assert gt.expected_entities == ("Widget",)


# ---------------------------------------------------------------------------
# check_sql_usage
# ---------------------------------------------------------------------------


def _case(sql_expected: bool, unsupported: bool = False) -> EvalCase:
    return EvalCase(
        id="x", question="q", category="c", sql_expected=sql_expected, unsupported=unsupported
    )


def _call(success: bool = True) -> SQLToolCallRecord:
    return SQLToolCallRecord(query="SELECT 1", success=success, execution_time_ms=1.0)


def test_check_sql_usage_passes_when_sql_expected_and_used():
    outcome = check_sql_usage(_case(sql_expected=True), [_call()])
    assert outcome.passed is True


def test_check_sql_usage_fails_when_sql_expected_but_not_used():
    outcome = check_sql_usage(_case(sql_expected=True), [])
    assert outcome.passed is False
    assert "no SQL calls" in outcome.reason


def test_check_sql_usage_passes_when_sql_not_expected_and_not_used():
    outcome = check_sql_usage(_case(sql_expected=False), [])
    assert outcome.passed is True


def test_check_sql_usage_fails_when_sql_not_expected_but_used():
    outcome = check_sql_usage(_case(sql_expected=False), [_call()])
    assert outcome.passed is False
    assert "Expected no SQL calls" in outcome.reason


# ---------------------------------------------------------------------------
# check_expected_entities / check_expected_numeric
# ---------------------------------------------------------------------------


def test_check_expected_entities_passes_when_all_present():
    gt = GroundTruth(expected_entities=("Widget", "Electronics"))
    outcome = check_expected_entities(gt, "The Widget in Electronics sold best.")
    assert outcome.passed is True


def test_check_expected_entities_is_case_insensitive():
    gt = GroundTruth(expected_entities=("Widget",))
    outcome = check_expected_entities(gt, "the WIDGET performed best")
    assert outcome.passed is True


def test_check_expected_entities_fails_when_missing():
    gt = GroundTruth(expected_entities=("Widget", "Gadget"))
    outcome = check_expected_entities(gt, "The Widget sold best.")
    assert outcome.passed is False
    assert "Gadget" in outcome.reason


def test_check_expected_entities_passes_trivially_when_none_required():
    gt = GroundTruth()
    outcome = check_expected_entities(gt, "anything at all")
    assert outcome.passed is True


def test_check_expected_numeric_passes_within_tolerance():
    gt = GroundTruth(expected_numeric=100.0)
    outcome = check_expected_numeric(gt, "The total was $100.40.")
    assert outcome.passed is True


def test_check_expected_numeric_fails_when_far_off():
    gt = GroundTruth(expected_numeric=100.0)
    outcome = check_expected_numeric(gt, "The total was $9.")
    assert outcome.passed is False


def test_check_expected_numeric_handles_comma_thousands_separators():
    gt = GroundTruth(expected_numeric=12776.82)
    outcome = check_expected_numeric(gt, "Revenue reached $12,776.82 for that product.")
    assert outcome.passed is True


def test_check_expected_numeric_passes_trivially_when_none_required():
    gt = GroundTruth()
    outcome = check_expected_numeric(gt, "no numbers needed here")
    assert outcome.passed is True


# ---------------------------------------------------------------------------
# check_no_fabricated_answer (unsupported-question check)
# ---------------------------------------------------------------------------


def test_check_no_fabricated_answer_passes_on_hedge_language():
    outcome = check_no_fabricated_answer(
        "I cannot answer that — the database does not track customer ratings."
    )
    assert outcome.passed is True


def test_check_no_fabricated_answer_fails_on_confident_invented_result():
    outcome = check_no_fabricated_answer(
        "The average customer satisfaction rating is 4.7 out of 5."
    )
    assert outcome.passed is False


# ---------------------------------------------------------------------------
# run_case / run_all with a mocked agent_runner (no real API calls)
# ---------------------------------------------------------------------------


def _fake_runner_for(answer: str, tool_calls: list[SQLToolCallRecord]):
    def runner(question: str, database_path: str | None = None) -> AgentAnswer:
        return AgentAnswer(answer=answer, tool_calls=tool_calls)

    return runner


def test_run_case_passes_for_correct_data_answer(tiny_db_path):
    case = next(c for c in EVAL_CASES if c.id == "top_products_revenue")
    runner = _fake_runner_for("The Widget generated the most revenue at $100.00.", [_call()])

    result = run_case(case, database_path=tiny_db_path, agent_runner=runner)

    assert result.passed is True
    assert result.sql_tool_used is True
    assert result.sql_call_count == 1
    assert result.failure_reason is None


def test_run_case_fails_when_entity_missing(tiny_db_path):
    case = next(c for c in EVAL_CASES if c.id == "top_products_revenue")
    runner = _fake_runner_for("Sales were strong overall.", [_call()])

    result = run_case(case, database_path=tiny_db_path, agent_runner=runner)

    assert result.passed is False
    assert "Widget" in result.failure_reason


def test_run_case_fails_when_sql_not_used_but_expected(tiny_db_path):
    case = next(c for c in EVAL_CASES if c.id == "top_products_revenue")
    runner = _fake_runner_for("The Widget generated the most revenue at $100.00.", [])

    result = run_case(case, database_path=tiny_db_path, agent_runner=runner)

    assert result.passed is False
    assert result.sql_tool_used is False


def test_run_case_passes_conversational_case_without_sql(tiny_db_path):
    case = next(c for c in EVAL_CASES if c.id == "conversational_question")
    runner = _fake_runner_for("I can help analyze sales, customers, and orders!", [])

    result = run_case(case, database_path=tiny_db_path, agent_runner=runner)

    assert result.passed is True
    assert result.sql_call_count == 0


def test_run_case_passes_unsupported_case_with_hedge_language(tiny_db_path):
    case = next(c for c in EVAL_CASES if c.id == "unsupported_question")
    runner = _fake_runner_for(
        "I don't have rating data available for products.", []
    )

    result = run_case(case, database_path=tiny_db_path, agent_runner=runner)

    assert result.passed is True


def test_run_case_fails_unsupported_case_when_answer_fabricates_a_number(tiny_db_path):
    case = next(c for c in EVAL_CASES if c.id == "unsupported_question")
    runner = _fake_runner_for("The average rating is 4.8 out of 5.", [])

    result = run_case(case, database_path=tiny_db_path, agent_runner=runner)

    assert result.passed is False


def test_run_case_reports_agent_failure_without_raising(tiny_db_path):
    case = next(c for c in EVAL_CASES if c.id == "top_products_revenue")

    def failing_runner(question, database_path=None):
        raise RuntimeError("simulated API failure")

    result = run_case(case, database_path=tiny_db_path, agent_runner=failing_runner)

    assert result.passed is False
    assert "Agent run failed" in result.failure_reason


def test_run_case_records_execution_time(tiny_db_path):
    case = next(c for c in EVAL_CASES if c.id == "conversational_question")
    runner = _fake_runner_for("Hello!", [])

    result = run_case(case, database_path=tiny_db_path, agent_runner=runner)

    assert isinstance(result.execution_time_ms, float)
    assert result.execution_time_ms >= 0


def test_run_all_runs_every_case_in_order(tiny_db_path):
    calls = []

    def runner(question, database_path=None):
        calls.append(question)
        return AgentAnswer(answer="I don't have that information.", tool_calls=[])

    results = run_all(EVAL_CASES, database_path=tiny_db_path, agent_runner=runner)

    assert [r.case_id for r in results] == [c.id for c in EVAL_CASES]
    assert calls == [c.question for c in EVAL_CASES]


# ---------------------------------------------------------------------------
# Scoring logic (EvalSummary)
# ---------------------------------------------------------------------------


def _result(passed: bool, sql_calls: int = 1, time_ms: float = 10.0):
    from evals.runner import EvalResult

    return EvalResult(
        case_id="x",
        question="q",
        passed=passed,
        sql_tool_used=sql_calls > 0,
        sql_call_count=sql_calls,
        execution_time_ms=time_ms,
        answer="a",
    )


def test_eval_summary_pass_rate():
    summary = EvalSummary([_result(True), _result(True), _result(False), _result(False)])
    assert summary.total == 4
    assert summary.passed_count == 2
    assert summary.pass_rate == pytest.approx(0.5)


def test_eval_summary_pass_rate_handles_empty_results():
    summary = EvalSummary([])
    assert summary.pass_rate == 0.0
    assert summary.average_execution_time_ms == 0.0


def test_eval_summary_average_execution_time():
    summary = EvalSummary([_result(True, time_ms=10.0), _result(True, time_ms=30.0)])
    assert summary.average_execution_time_ms == pytest.approx(20.0)


def test_eval_summary_total_sql_calls():
    summary = EvalSummary([_result(True, sql_calls=2), _result(True, sql_calls=3)])
    assert summary.total_sql_calls == 5


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def test_format_report_shows_pass_and_fail_labels():
    from evals.runner import EvalResult

    results = [
        EvalResult(
            case_id="revenue_top_products", question="q", passed=True,
            sql_tool_used=True, sql_call_count=1, execution_time_ms=5.0, answer="a",
        ),
        EvalResult(
            case_id="unsupported_question", question="q", passed=False,
            sql_tool_used=False, sql_call_count=0, execution_time_ms=2.0, answer="a",
            failure_reason="did not hedge",
        ),
    ]

    report = format_report(results)

    assert "AI DATA AGENT EVALUATION" in report
    assert "PASS  revenue_top_products" in report
    assert "FAIL  unsupported_question" in report
    assert "did not hedge" in report
    assert "Score: 1/2 (50%)" in report
    assert "Average agent execution time:" in report
    assert "Total SQL tool calls:" in report


def test_format_report_handles_empty_results():
    report = format_report([])
    assert "Score: 0/0 (0%)" in report


# ---------------------------------------------------------------------------
# CLI wiring (python -m evals.run_evals): mocked, no real API calls
# ---------------------------------------------------------------------------


def test_run_evals_cli_prints_report_without_calling_the_real_agent(monkeypatch, capsys):
    import sys

    import evals.run_evals as run_evals_module
    from evals.runner import EvalResult

    def fake_run_all(cases, database_path=None, agent_runner=None):
        return [
            EvalResult(
                case_id=case.id, question=case.question, passed=True,
                sql_tool_used=case.sql_expected, sql_call_count=1, execution_time_ms=1.0,
                answer="ok",
            )
            for case in cases
        ]

    monkeypatch.setattr(run_evals_module, "run_all", fake_run_all)
    monkeypatch.setattr(sys, "argv", ["run_evals.py"])

    run_evals_module.main()

    out = capsys.readouterr().out
    assert "consumes API usage" in out
    assert "AI DATA AGENT EVALUATION" in out
    assert "Score: 10/10 (100%)" in out


def test_run_evals_cli_accepts_database_path_argument(monkeypatch):
    import sys

    import evals.run_evals as run_evals_module

    captured = {}

    def fake_run_all(cases, database_path=None, agent_runner=None):
        captured["database_path"] = database_path
        return []

    monkeypatch.setattr(run_evals_module, "run_all", fake_run_all)
    monkeypatch.setattr(sys, "argv", ["run_evals.py", "--database-path", "some/other.db"])

    run_evals_module.main()

    assert captured["database_path"] == "some/other.db"
