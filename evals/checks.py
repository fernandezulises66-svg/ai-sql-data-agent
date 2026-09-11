"""Transparent, rule-based checks for AI Data Analyst Agent evaluations.

Every check here is a small, explainable function that returns a
CheckOutcome(passed, reason) — no LLM-as-a-judge, no fuzzy scoring, so a
failing evaluation always comes with a plain-English reason a human can
verify by reading this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent.data_analyst_agent import SQLToolCallRecord
from evals.eval_cases import EvalCase
from evals.ground_truth import GroundTruth

# A numeric answer is accepted if it falls within this tolerance of the
# ground-truth value — the larger of a relative (2%) and an absolute
# ($0.50) margin, which comfortably covers rounding/formatting
# differences without accepting a substantively wrong number.
RELATIVE_TOLERANCE = 0.02
ABSOLUTE_TOLERANCE = 0.5

# Phrases suggesting the agent is (correctly) declining to answer rather
# than fabricating a result. Simple substring matching, deliberately not
# an LLM judge.
_HEDGE_PHRASES = (
    "cannot", "can't", "unable", "don't have", "do not have",
    "not available", "no data", "not possible", "doesn't include",
    "does not include", "not tracked", "no information", "not stored",
    "isn't available", "is not available", "don't track", "do not track",
    "no such", "not part of", "not in the database", "not in the schema",
)


@dataclass
class CheckOutcome:
    name: str
    passed: bool
    reason: str


def check_sql_usage(case: EvalCase, tool_calls: list[SQLToolCallRecord]) -> CheckOutcome:
    """If SQL is expected, the tool must have been called at least once (and vice versa)."""
    used = len(tool_calls) > 0
    if case.sql_expected and not used:
        return CheckOutcome(
            "sql_usage", False,
            "Expected the agent to use run_sql_query, but it made no SQL calls.",
        )
    if not case.sql_expected and used:
        return CheckOutcome(
            "sql_usage", False,
            f"Expected no SQL calls for this question, but {len(tool_calls)} were made.",
        )
    return CheckOutcome("sql_usage", True, "SQL tool usage matched expectations.")


def check_expected_entities(ground_truth: GroundTruth, answer: str) -> CheckOutcome:
    """Every expected entity name must appear (case-insensitively) in the answer."""
    if not ground_truth.expected_entities:
        return CheckOutcome("expected_entities", True, "No entities required for this case.")

    answer_lower = answer.lower()
    missing = [e for e in ground_truth.expected_entities if e.lower() not in answer_lower]
    if missing:
        return CheckOutcome(
            "expected_entities", False,
            f"Answer is missing expected entity name(s): {', '.join(missing)}.",
        )
    return CheckOutcome(
        "expected_entities", True,
        f"Found all expected entities: {', '.join(ground_truth.expected_entities)}.",
    )


_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")


def _numbers_in_text(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_PATTERN.findall(text):
        cleaned = match.replace(",", "")
        try:
            numbers.append(float(cleaned))
        except ValueError:
            continue
    return numbers


def check_expected_numeric(ground_truth: GroundTruth, answer: str) -> CheckOutcome:
    """A number reasonably close to the expected value must appear in the answer."""
    if ground_truth.expected_numeric is None:
        return CheckOutcome("expected_numeric", True, "No numeric value required for this case.")

    expected = ground_truth.expected_numeric
    tolerance = max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * abs(expected))

    for candidate in _numbers_in_text(answer):
        if abs(candidate - expected) <= tolerance:
            return CheckOutcome(
                "expected_numeric", True,
                f"Found {candidate} in the answer, within tolerance of expected {expected:.2f}.",
            )
    return CheckOutcome(
        "expected_numeric", False,
        f"No number close to expected value {expected:.2f} (tolerance {tolerance:.2f}) "
        "found in the answer.",
    )


def check_no_fabricated_answer(answer: str) -> CheckOutcome:
    """For unsupported questions, the agent should not confidently fabricate an answer.

    Simple keyword heuristic: the answer should contain hedging/refusal
    language indicating the data isn't available, rather than reading
    like a confident, invented statistic.
    """
    answer_lower = answer.lower()
    if any(phrase in answer_lower for phrase in _HEDGE_PHRASES):
        return CheckOutcome(
            "no_fabricated_answer", True,
            "Answer acknowledges the data/question is not supported by the schema.",
        )
    return CheckOutcome(
        "no_fabricated_answer", False,
        "Answer does not clearly acknowledge that this cannot be answered from the "
        "available data; it may be fabricating a result.",
    )
