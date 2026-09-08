"""Grading and paired statistics.

The grader is the product's independent judge, so its classifications and its
statistics both need to be pinned down by tests rather than eyeballed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from skillfoundry_domain.interpreter import Execution, ReviewRequest
from skillfoundry_evaluation.cases import Case, ExpectedReview, ExpectedValue
from skillfoundry_evaluation.metrics import (
    CaseOutcome,
    Verdict,
    _exact_binomial_two_sided,
    compare_paired,
    grade,
    summarize,
)


def _exec(**output) -> Execution:
    execution = Execution(
        procedure_id="p", procedure_revision=1, procedure_digest="d", row_id="r"
    )
    execution.output.update(output)
    return execution


def _review(code: str) -> Execution:
    execution = Execution(
        procedure_id="p", procedure_revision=1, procedure_digest="d", row_id="r"
    )
    execution.reviews.append(ReviewRequest(code=code, reason="because", rule_path="x"))
    return execution


def _case(expect) -> Case:
    return Case(case_id="c1", supplier="acme", origin="real", split="teach", expect=expect)


VALUE = ExpectedValue(unit_price=Decimal("10.0000"), price_basis="per_unit_from_pack", pack_size=12)
LISTED = ExpectedValue(unit_price=Decimal("10"), price_basis="as_listed")
REVIEW = ExpectedReview(code="pack_size_not_explicit")


def test_a_matching_value_is_correct():
    outcome = grade(
        _case(VALUE),
        _exec(unit_price=Decimal("10.0000"), price_basis="per_unit_from_pack", pack_size=12),
    )
    assert outcome.verdict is Verdict.CORRECT_VALUE
    assert outcome.fields_correct == outcome.fields_total == 3


def test_decimal_comparison_ignores_trailing_zeros():
    # 10 and 10.0000 are the same price. The grader must not fail a procedure
    # over decimal presentation.
    outcome = grade(
        _case(LISTED), _exec(unit_price=Decimal("10.0000"), price_basis="as_listed")
    )
    assert outcome.verdict is Verdict.CORRECT_VALUE


def test_a_correct_decline_is_correct():
    assert grade(_case(REVIEW), _review("pack_size_not_explicit")).verdict is Verdict.CORRECT_REVIEW


def test_declining_for_the_wrong_stated_reason_is_not_correct():
    outcome = grade(_case(REVIEW), _review("unknown_price_unit"))
    assert outcome.verdict is Verdict.WRONG_REVIEW_CODE
    assert not outcome.verdict.is_correct


def test_answering_a_row_the_reviewer_marked_unanswerable_is_critical():
    outcome = grade(_case(REVIEW), _exec(unit_price=Decimal("15.0000"), price_basis="per_unit_from_pack"))
    assert outcome.verdict is Verdict.CRITICAL_FABRICATED
    assert outcome.verdict.is_critical


def test_declining_an_answerable_row_is_wrong_but_not_critical():
    outcome = grade(_case(VALUE), _review("pack_size_not_explicit"))
    assert outcome.verdict is Verdict.OVER_ABSTAINED
    assert not outcome.verdict.is_critical
    assert not outcome.verdict.is_correct


def test_being_wrong_by_a_pack_factor_is_critical():
    # 0.8333 against a correct 10 is the twelvefold error that comes from
    # dividing a per item price by a diameter.
    outcome = grade(
        _case(LISTED), _exec(unit_price=Decimal("0.8333"), price_basis="per_unit_from_pack")
    )
    assert outcome.verdict is Verdict.CRITICAL_WRONG_FACTOR
    assert "factor" in outcome.detail


@pytest.mark.parametrize(
    "actual,expected_verdict",
    [
        (Decimal("20.0000"), Verdict.CRITICAL_WRONG_FACTOR),  # exactly 2x
        (Decimal("5.0000"), Verdict.CRITICAL_WRONG_FACTOR),   # exactly half
        (Decimal("15.0000"), Verdict.WRONG_VALUE),            # 1.5x
        (Decimal("10.0100"), Verdict.WRONG_VALUE),            # a cent out
    ],
)
def test_the_critical_ratio_boundary_sits_at_two(actual, expected_verdict):
    outcome = grade(_case(VALUE), _exec(unit_price=actual, price_basis="per_unit_from_pack", pack_size=12))
    assert outcome.verdict is expected_verdict


def test_a_faulted_execution_is_never_counted_as_correct():
    execution = Execution(procedure_id="p", procedure_revision=1, procedure_digest="d", row_id="r")
    execution.fault = "convert refused"
    outcome = grade(_case(VALUE), execution)
    assert outcome.verdict is Verdict.FAULTED
    assert not outcome.verdict.is_correct


def test_summarize_reports_coverage_and_accuracy_together():
    outcomes = [
        CaseOutcome("a", "real", "acme", Verdict.CORRECT_VALUE, "", "", "", 2, 2),
        CaseOutcome("b", "real", "acme", Verdict.CORRECT_REVIEW, "", "", ""),
        CaseOutcome("c", "real", "acme", Verdict.CRITICAL_WRONG_FACTOR, "", "", "", 2, 1),
        CaseOutcome("d", "real", "acme", Verdict.OVER_ABSTAINED, "", "", "", 2, 0),
    ]
    metrics = summarize(outcomes)
    assert metrics.total == 4
    assert metrics.correct == 2
    assert metrics.critical == 1
    assert metrics.over_abstained == 1
    assert metrics.covered == 2  # a and c emitted values
    assert metrics.coverage == 0.5
    assert metrics.abstention_rate == 0.5
    assert metrics.row_accuracy == 0.5
    assert metrics.field_accuracy == pytest.approx(3 / 6)


@pytest.mark.parametrize(
    "fixed,broke,expected",
    [
        (0, 0, 1.0),
        (1, 1, 1.0),
        (6, 0, 0.03125),   # 2 * C(6,0) / 2**6
        (5, 1, 0.21875),   # 2 * (C(6,0) + C(6,1)) / 2**6
        (10, 0, 2 / 1024),
    ],
)
def test_exact_two_sided_binomial_matches_hand_calculation(fixed, broke, expected):
    assert _exact_binomial_two_sided(fixed, broke) == pytest.approx(expected)


def test_paired_comparison_counts_fixes_and_breaks():
    baseline = [
        CaseOutcome("a", "real", "s", Verdict.CRITICAL_WRONG_FACTOR, "", "", ""),
        CaseOutcome("b", "real", "s", Verdict.CORRECT_VALUE, "", "", ""),
        CaseOutcome("c", "real", "s", Verdict.CORRECT_VALUE, "", "", ""),
    ]
    candidate = [
        CaseOutcome("a", "real", "s", Verdict.CORRECT_VALUE, "", "", ""),
        CaseOutcome("b", "real", "s", Verdict.OVER_ABSTAINED, "", "", ""),
        CaseOutcome("c", "real", "s", Verdict.CORRECT_VALUE, "", "", ""),
    ]
    result = compare_paired(baseline, candidate)
    assert (result.candidate_fixed, result.candidate_broke) == (1, 1)
    assert result.both_correct == 1
    assert result.net_change == 0
    assert result.sample_size == 3
    assert result.p_value == pytest.approx(1.0)
