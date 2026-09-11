"""Runs evaluation cases against the AI Data Analyst Agent and grades them.

This is not a unit-test replacement: unit tests (tests/) already cover
deterministic application logic (SQL validation, schema introspection,
seeding, agent wiring) with mocks. This module instead exercises full
end-to-end agent behavior against representative business questions and
grades the result with small, transparent, rule-based checks (see
evals/checks.py) — never an LLM judge.

agent_runner defaults to the real agent.data_analyst_agent.run_data_agent,
which calls the OpenAI API. Tests must pass a stand-in agent_runner
instead so pytest never makes a real API call (see tests/test_evals.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from agent.data_analyst_agent import AgentAnswer, run_data_agent
from evals.checks import (
    CheckOutcome,
    check_expected_entities,
    check_expected_numeric,
    check_no_fabricated_answer,
    check_sql_usage,
)
from evals.eval_cases import EVAL_CASES, EvalCase
from evals.ground_truth import compute_ground_truth

AgentRunner = Callable[[str, "str | None"], AgentAnswer]


@dataclass
class EvalResult:
    """Outcome of running one EvalCase against the agent."""

    case_id: str
    question: str
    passed: bool
    sql_tool_used: bool
    sql_call_count: int
    execution_time_ms: float
    answer: str
    checks: list[CheckOutcome] = field(default_factory=list)
    failure_reason: str | None = None


def run_case(
    case: EvalCase,
    database_path: str | None = None,
    agent_runner: AgentRunner = run_data_agent,
) -> EvalResult:
    """Run one case against the agent and grade the result.

    agent_runner defaults to the real run_data_agent (which calls the
    OpenAI API and consumes API usage); pass a mock/stub for tests.
    A failure to run the agent at all (config/API/runtime error) is
    reported as a failed EvalResult rather than raised, so one broken
    case doesn't stop the rest of the suite from running.
    """
    start_time = time.perf_counter()
    try:
        agent_answer = agent_runner(case.question, database_path)
    except Exception as exc:  # agent/API errors surface as a failed case, not a crash
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return EvalResult(
            case_id=case.id,
            question=case.question,
            passed=False,
            sql_tool_used=False,
            sql_call_count=0,
            execution_time_ms=round(elapsed_ms, 3),
            answer="",
            checks=[],
            failure_reason=f"Agent run failed: {exc}",
        )
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    checks: list[CheckOutcome] = []
    if case.unsupported:
        checks.append(check_no_fabricated_answer(agent_answer.answer))
    else:
        checks.append(check_sql_usage(case, agent_answer.tool_calls))
        ground_truth = compute_ground_truth(case.id, database_path)
        if ground_truth is not None:
            checks.append(check_expected_entities(ground_truth, agent_answer.answer))
            checks.append(check_expected_numeric(ground_truth, agent_answer.answer))

    passed = all(check.passed for check in checks)
    failure_reason = "; ".join(c.reason for c in checks if not c.passed) or None

    return EvalResult(
        case_id=case.id,
        question=case.question,
        passed=passed,
        sql_tool_used=len(agent_answer.tool_calls) > 0,
        sql_call_count=len(agent_answer.tool_calls),
        execution_time_ms=round(elapsed_ms, 3),
        answer=agent_answer.answer,
        checks=checks,
        failure_reason=failure_reason,
    )


def run_all(
    cases: tuple[EvalCase, ...] = EVAL_CASES,
    database_path: str | None = None,
    agent_runner: AgentRunner = run_data_agent,
) -> list[EvalResult]:
    """Run every case in cases and return their EvalResults, in order."""
    return [run_case(case, database_path, agent_runner) for case in cases]


@dataclass
class EvalSummary:
    """Aggregate statistics over a list of EvalResults."""

    results: list[EvalResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return self.passed_count / self.total if self.total else 0.0

    @property
    def average_execution_time_ms(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.execution_time_ms for r in self.results) / len(self.results)

    @property
    def total_sql_calls(self) -> int:
        return sum(r.sql_call_count for r in self.results)


def format_report(results: list[EvalResult]) -> str:
    """Render results as the CLI report text (also used directly by tests)."""
    summary = EvalSummary(results)

    lines = ["AI DATA AGENT EVALUATION", ""]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"{status}  {result.case_id}")
        if not result.passed and result.failure_reason:
            lines.append(f"      -> {result.failure_reason}")
    lines.append("")
    lines.append(
        f"Score: {summary.passed_count}/{summary.total} ({summary.pass_rate * 100:.0f}%)"
    )
    lines.append(f"Average agent execution time: {summary.average_execution_time_ms:.1f} ms")
    lines.append(f"Total SQL tool calls: {summary.total_sql_calls}")
    return "\n".join(lines)
