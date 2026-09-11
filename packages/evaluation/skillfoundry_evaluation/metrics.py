"""Independent grading of procedure output against reviewer labels.

This module never asks a model whether it did well. It compares emitted values
against hand authored expectations using exact decimal arithmetic.

The verdict taxonomy separates safe failures from dangerous ones. A procedure
that declines an answerable row costs the reviewer time. A procedure that
invents a unit price on a row whose pack size is unknown, or that is wrong by a
whole pack factor, corrupts a catalog quietly. Only the second kind blocks a
release.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Sequence

from skillfoundry_domain.interpreter import Execution, TerminalState

from .cases import Case, ExpectedReview, ExpectedValue

# A unit price wrong by at least this ratio is treated as a pack factor error
# rather than a rounding disagreement. The smallest real pack is two.
CRITICAL_RATIO = Decimal(2)


class Verdict(str, Enum):
    CORRECT_VALUE = "correct_value"
    CORRECT_REVIEW = "correct_review"
    WRONG_VALUE = "wrong_value"
    WRONG_REVIEW_CODE = "wrong_review_code"
    OVER_ABSTAINED = "over_abstained"
    CRITICAL_WRONG_FACTOR = "critical_wrong_factor"
    CRITICAL_FABRICATED = "critical_fabricated"
    FAULTED = "faulted"

    @property
    def is_correct(self) -> bool:
        return self in {Verdict.CORRECT_VALUE, Verdict.CORRECT_REVIEW}

    @property
    def is_critical(self) -> bool:
        return self in {Verdict.CRITICAL_WRONG_FACTOR, Verdict.CRITICAL_FABRICATED}


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    origin: str
    supplier: str
    verdict: Verdict
    detail: str
    expected: str
    actual: str
    fields_total: int = 0
    fields_correct: int = 0


def _fmt(value: object) -> str:
    return "review" if value is None else str(value)


def grade(case: Case, execution: Execution) -> CaseOutcome:
    """Compare one execution against its reviewer label."""
    base = dict(
        case_id=case.case_id,
        origin=case.origin,
        supplier=case.supplier,
    )

    if execution.terminal_state is TerminalState.INVALID:
        return CaseOutcome(
            **base,
            verdict=Verdict.FAULTED,
            detail=execution.fault or "execution faulted",
            expected=_describe(case),
            actual="faulted",
        )

    emitted_review = execution.terminal_state is TerminalState.NEEDS_REVIEW
    codes = [r.code for r in execution.reviews]

    if isinstance(case.expect, ExpectedReview):
        if emitted_review:
            if case.expect.code in codes:
                return CaseOutcome(
                    **base,
                    verdict=Verdict.CORRECT_REVIEW,
                    detail=f"declined with {case.expect.code}",
                    expected=_describe(case),
                    actual=f"review {','.join(codes)}",
                )
            return CaseOutcome(
                **base,
                verdict=Verdict.WRONG_REVIEW_CODE,
                detail=f"declined with {codes} but the labelled reason is {case.expect.code}",
                expected=_describe(case),
                actual=f"review {','.join(codes)}",
            )
        # It answered a row the reviewer marked unanswerable.
        return CaseOutcome(
            **base,
            verdict=Verdict.CRITICAL_FABRICATED,
            detail=(
                "emitted a unit price of "
                f"{execution.output.get('unit_price')} on a row whose correct value is "
                "unknown, so the output cannot be trusted"
            ),
            expected=_describe(case),
            actual=_fmt(execution.output.get("unit_price")),
        )

    expected: ExpectedValue = case.expect

    if emitted_review:
        return CaseOutcome(
            **base,
            verdict=Verdict.OVER_ABSTAINED,
            detail=f"declined with {codes} although the row is answerable",
            expected=_describe(case),
            actual=f"review {','.join(codes)}",
            fields_total=_field_count(expected),
            fields_correct=0,
        )

    actual_price = execution.output.get("unit_price")
    actual_basis = execution.output.get("price_basis")
    actual_pack = execution.output.get("pack_size")

    fields_total = _field_count(expected)
    fields_correct = 0
    if isinstance(actual_price, Decimal) and actual_price == expected.unit_price:
        fields_correct += 1
    if actual_basis == expected.price_basis:
        fields_correct += 1
    if expected.pack_size is not None and actual_pack == expected.pack_size:
        fields_correct += 1

    if not isinstance(actual_price, Decimal):
        return CaseOutcome(
            **base,
            verdict=Verdict.WRONG_VALUE,
            detail=f"unit price was not a decimal value: {actual_price!r}",
            expected=_describe(case),
            actual=_fmt(actual_price),
            fields_total=fields_total,
            fields_correct=fields_correct,
        )

    if fields_correct == fields_total:
        return CaseOutcome(
            **base,
            verdict=Verdict.CORRECT_VALUE,
            detail="matches the labelled unit price and basis",
            expected=_describe(case),
            actual=f"{actual_price} {actual_basis}",
            fields_total=fields_total,
            fields_correct=fields_correct,
        )

    ratio = _ratio(actual_price, expected.unit_price)
    if ratio is not None and ratio >= CRITICAL_RATIO:
        return CaseOutcome(
            **base,
            verdict=Verdict.CRITICAL_WRONG_FACTOR,
            detail=(
                f"unit price {actual_price} is off by a factor of {ratio.normalize()} "
                f"against the labelled {expected.unit_price}, which is the signature "
                "of a pack size applied to the wrong row"
            ),
            expected=_describe(case),
            actual=f"{actual_price} {actual_basis}",
            fields_total=fields_total,
            fields_correct=fields_correct,
        )

    return CaseOutcome(
        **base,
        verdict=Verdict.WRONG_VALUE,
        detail=f"unit price {actual_price} does not match the labelled {expected.unit_price}",
        expected=_describe(case),
        actual=f"{actual_price} {actual_basis}",
        fields_total=fields_total,
        fields_correct=fields_correct,
    )


def _field_count(expected: ExpectedValue) -> int:
    return 3 if expected.pack_size is not None else 2


def _describe(case: Case) -> str:
    if isinstance(case.expect, ExpectedReview):
        return f"review {case.expect.code}"
    return f"{case.expect.unit_price} {case.expect.price_basis}"


def _ratio(actual: Decimal, expected: Decimal) -> Decimal | None:
    if actual == expected == 0:
        return None
    if actual <= 0 or expected <= 0:
        return Decimal("Infinity")
    high, low = (actual, expected) if actual > expected else (expected, actual)
    return high / low


@dataclass(frozen=True)
class Metrics:
    total: int
    correct: int
    correct_covered: int
    critical: int
    critical_wrong_factor: int
    critical_fabricated: int
    over_abstained: int
    wrong_value: int
    wrong_review_code: int
    faulted: int
    covered: int
    fields_total: int
    fields_correct: int

    @property
    def row_accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def coverage(self) -> float:
        return self.covered / self.total if self.total else 0.0

    @property
    def abstention_rate(self) -> float:
        return (self.total - self.covered) / self.total if self.total else 0.0

    @property
    def field_accuracy(self) -> float:
        return self.fields_correct / self.fields_total if self.fields_total else 0.0

    @property
    def accuracy_on_covered(self) -> float:
        return self.correct_covered / self.covered if self.covered else 0.0


def summarize(outcomes: Sequence[CaseOutcome]) -> Metrics:
    covered = sum(
        1
        for o in outcomes
        if o.verdict
        not in {
            Verdict.CORRECT_REVIEW,
            Verdict.WRONG_REVIEW_CODE,
            Verdict.OVER_ABSTAINED,
            Verdict.FAULTED,
        }
    )
    return Metrics(
        total=len(outcomes),
        correct=sum(1 for o in outcomes if o.verdict.is_correct),
        correct_covered=sum(o.verdict is Verdict.CORRECT_VALUE for o in outcomes),
        critical=sum(1 for o in outcomes if o.verdict.is_critical),
        critical_wrong_factor=sum(
            1 for o in outcomes if o.verdict is Verdict.CRITICAL_WRONG_FACTOR
        ),
        critical_fabricated=sum(
            1 for o in outcomes if o.verdict is Verdict.CRITICAL_FABRICATED
        ),
        over_abstained=sum(1 for o in outcomes if o.verdict is Verdict.OVER_ABSTAINED),
        wrong_value=sum(1 for o in outcomes if o.verdict is Verdict.WRONG_VALUE),
        wrong_review_code=sum(
            1 for o in outcomes if o.verdict is Verdict.WRONG_REVIEW_CODE
        ),
        faulted=sum(1 for o in outcomes if o.verdict is Verdict.FAULTED),
        covered=covered,
        fields_total=sum(o.fields_total for o in outcomes),
        fields_correct=sum(o.fields_correct for o in outcomes),
    )


@dataclass(frozen=True)
class PairedComparison:
    """Case level paired comparison of two procedures.

    b is the count of cases the candidate fixed, c the count it broke. The p
    value is an exact two sided binomial sign test on those discordant pairs,
    which is the McNemar exact test. With small case sets this is the honest
    statistic: it reports how easily the observed split could be chance.
    """

    both_correct: int
    both_wrong: int
    candidate_fixed: int
    candidate_broke: int
    p_value: float
    sample_size: int

    @property
    def net_change(self) -> int:
        return self.candidate_fixed - self.candidate_broke


def _exact_binomial_two_sided(fixed: int, broke: int) -> float:
    n = fixed + broke
    if n == 0:
        return 1.0
    observed = min(fixed, broke)
    tail = sum(math.comb(n, k) for k in range(observed + 1))
    p = 2.0 * tail / (2.0**n)
    return min(1.0, p)


def compare_paired(
    baseline: Sequence[CaseOutcome], candidate: Sequence[CaseOutcome]
) -> PairedComparison:
    base_index = {o.case_id: o for o in baseline}
    cand_index = {o.case_id: o for o in candidate}
    if len(base_index) != len(baseline) or len(cand_index) != len(candidate):
        raise ValueError("duplicate case IDs cannot be paired")
    if set(base_index) != set(cand_index):
        raise ValueError("paired comparison requires identical case IDs")
    shared = sorted(base_index)

    both_correct = both_wrong = fixed = broke = 0
    for case_id in shared:
        b_ok = base_index[case_id].verdict.is_correct
        c_ok = cand_index[case_id].verdict.is_correct
        if b_ok and c_ok:
            both_correct += 1
        elif not b_ok and not c_ok:
            both_wrong += 1
        elif c_ok and not b_ok:
            fixed += 1
        else:
            broke += 1

    return PairedComparison(
        both_correct=both_correct,
        both_wrong=both_wrong,
        candidate_fixed=fixed,
        candidate_broke=broke,
        p_value=_exact_binomial_two_sided(fixed, broke),
        sample_size=len(shared),
    )
