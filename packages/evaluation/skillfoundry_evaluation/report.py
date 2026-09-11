"""The release gate and its human readable report.

A candidate procedure is publishable only if it clears every criterion below.
The gate is deliberately hard to satisfy by accident: beating the original is
not enough, because a rule that merely memorizes the taught row would do that.
It also has to beat verbatim recall, which is what forces the rule to
generalize.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .metrics import CaseOutcome, PairedComparison, Verdict, compare_paired
from .runner import RunResult


@dataclass(frozen=True)
class GateCriterion:
    code: str
    description: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ReleaseDecision:
    candidate: str
    criteria: tuple[GateCriterion, ...]
    holdout_comparison: PairedComparison
    recall_comparison: PairedComparison
    new_critical_cases: tuple[str, ...]
    unreviewed_regressions: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria)

    @property
    def verdict(self) -> str:
        return "PUBLISHABLE" if self.passed else "BLOCKED"


def _critical_ids(outcomes: Sequence[CaseOutcome]) -> set[str]:
    return {o.case_id for o in outcomes if o.verdict.is_critical}


def _regressed_ids(
    baseline: Sequence[CaseOutcome], candidate: Sequence[CaseOutcome]
) -> set[str]:
    base = {o.case_id: o.verdict.is_correct for o in baseline}
    return {
        o.case_id
        for o in candidate
        if base.get(o.case_id) is True and not o.verdict.is_correct
    }


def evaluate_gate(
    *,
    original: RunResult,
    recall: RunResult,
    candidate: RunResult,
    original_holdout: RunResult,
    candidate_holdout: RunResult,
    reviewed_regressions: frozenset[str] = frozenset(),
) -> ReleaseDecision:
    # Validate full-suite identity before judging missing regressions as successes.
    compare_paired(original.outcomes, candidate.outcomes)
    new_critical = sorted(
        _critical_ids(candidate.outcomes) - _critical_ids(original.outcomes)
    )
    regressed = _regressed_ids(original.outcomes, candidate.outcomes)
    unreviewed = sorted(regressed - reviewed_regressions)

    holdout = compare_paired(original_holdout.outcomes, candidate_holdout.outcomes)
    against_recall = compare_paired(recall.outcomes, candidate.outcomes)

    criteria = (
        GateCriterion(
            code="no_new_critical_errors",
            description="Introduces no new critical unit errors on the full suite",
            passed=not new_critical,
            detail=(
                "none introduced"
                if not new_critical
                else f"{len(new_critical)} new critical cases: {', '.join(new_critical)}"
            ),
        ),
        GateCriterion(
            code="no_execution_faults",
            description="Every case reaches a defined terminal state",
            passed=candidate.metrics.faulted == 0,
            detail=(
                "no faults"
                if candidate.metrics.faulted == 0
                else f"{candidate.metrics.faulted} executions faulted"
            ),
        ),
        GateCriterion(
            code="improves_on_holdout",
            description="Positive paired performance against the original on supplier-held-out source fixtures",
            passed=holdout.net_change > 0,
            detail=(
                f"fixed {holdout.candidate_fixed}, broke {holdout.candidate_broke} "
                f"of {holdout.sample_size} held out cases, exact two sided p={holdout.p_value:.4g}"
            ),
        ),
        GateCriterion(
            code="beats_verbatim_recall",
            description="Generalizes beyond recalling the taught row",
            passed=against_recall.net_change > 0,
            detail=(
                f"fixed {against_recall.candidate_fixed}, broke {against_recall.candidate_broke} "
                f"against verbatim recall over {against_recall.sample_size} cases, "
                f"exact two sided p={against_recall.p_value:.4g}"
            ),
        ),
        GateCriterion(
            code="regressions_reviewed",
            description="Every regression against the original has been explicitly reviewed",
            passed=not unreviewed,
            detail=(
                "no unreviewed regressions"
                if not unreviewed
                else f"{len(unreviewed)} unreviewed: {', '.join(unreviewed)}"
            ),
        ),
    )

    return ReleaseDecision(
        candidate=candidate.name,
        criteria=criteria,
        holdout_comparison=holdout,
        recall_comparison=against_recall,
        new_critical_cases=tuple(new_critical),
        unreviewed_regressions=tuple(unreviewed),
    )


# Rendering ----------------------------------------------------------------

_HEAD = f"{'procedure':<34}{'rows':>6}{'correct':>9}{'coverage':>10}{'critical':>10}{'abstain':>9}{'fields':>9}"


def render_metrics_table(results: Sequence[RunResult]) -> str:
    lines = [_HEAD, "-" * len(_HEAD)]
    for result in results:
        m = result.metrics
        lines.append(
            f"{result.label:<34}{m.total:>6}"
            f"{m.correct:>4}/{m.total:<4}"
            f"{m.coverage * 100:>9.0f}%"
            f"{m.critical:>10}"
            f"{m.abstention_rate * 100:>8.0f}%"
            f"{m.field_accuracy * 100:>8.0f}%"
        )
    return "\n".join(lines)


def render_decision(decision: ReleaseDecision) -> str:
    lines = [f"Release gate: {decision.verdict}", ""]
    for criterion in decision.criteria:
        mark = "pass" if criterion.passed else "FAIL"
        lines.append(f"  [{mark}] {criterion.description}")
        lines.append(f"         {criterion.detail}")
    return "\n".join(lines)


def render_failures(result: RunResult, limit: int = 12) -> str:
    bad = [o for o in result.outcomes if not o.verdict.is_correct]
    if not bad:
        return f"{result.label}: no incorrect cases"
    lines = [f"{result.label}: {len(bad)} incorrect cases"]
    order = {
        Verdict.CRITICAL_FABRICATED: 0,
        Verdict.CRITICAL_WRONG_FACTOR: 0,
        Verdict.FAULTED: 1,
        Verdict.WRONG_VALUE: 2,
        Verdict.WRONG_REVIEW_CODE: 3,
        Verdict.OVER_ABSTAINED: 4,
    }
    for outcome in sorted(bad, key=lambda o: (order.get(o.verdict, 9), o.case_id))[
        :limit
    ]:
        lines.append(
            f"  {outcome.case_id:<18} {outcome.verdict.value:<24} "
            f"expected {outcome.expected:<28} got {outcome.actual}"
        )
    if len(bad) > limit:
        lines.append(f"  ... and {len(bad) - limit} more")
    return "\n".join(lines)
