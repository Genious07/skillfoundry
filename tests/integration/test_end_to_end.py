"""End to end evaluation over the bundled fixtures.

These assertions pin the numbers quoted in the README. If the fixtures or the
rules change, these tests fail and the README has to be updated with them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from skillfoundry_domain import library
from skillfoundry_evaluation.baselines import LiteralRecall, ProcedureRunner, load_corrections
from skillfoundry_evaluation.report import evaluate_gate
from skillfoundry_evaluation.runner import evaluate, load_fixtures

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo"


@pytest.fixture(scope="module")
def fixtures():
    return load_fixtures(FIXTURE_ROOT)


@pytest.fixture(scope="module")
def runs(fixtures):
    original = ProcedureRunner(
        procedure=library.load("naive"),
        tables=library.TABLES,
        name="baseline_original",
        label="Baseline 1, original procedure",
    )
    corrections = load_corrections(FIXTURE_ROOT / "teaching.jsonl", fixtures.rows_by_case)
    recall = LiteralRecall(fallback=original, corrections=corrections)
    corrected = ProcedureRunner(
        procedure=library.load("corrected"),
        tables=library.TABLES,
        name="candidate_corrected",
        label="Candidate, explicit pack rule",
    )
    overeager = ProcedureRunner(
        procedure=library.load("overeager"),
        tables=library.TABLES,
        name="candidate_overeager",
        label="Candidate, over generalized",
    )
    suite = fixtures.all_cases
    holdout = fixtures.split("holdout", origin="real")
    return {
        "original": evaluate(original, suite, fixtures),
        "recall": evaluate(recall, suite, fixtures),
        "corrected": evaluate(corrected, suite, fixtures),
        "overeager": evaluate(overeager, suite, fixtures),
        "original_holdout": evaluate(original, holdout, fixtures),
        "corrected_holdout": evaluate(corrected, holdout, fixtures),
        "overeager_holdout": evaluate(overeager, holdout, fixtures),
    }


# Fixture integrity ---------------------------------------------------------


def test_the_fixture_suite_has_the_expected_shape(fixtures):
    assert len(fixtures.real) == 32
    assert len(fixtures.generated) == 6
    assert len(fixtures.all_cases) == 38


def test_generated_cases_stay_distinguishable_from_real_ones(fixtures):
    # A rule that only satisfies its own counterexamples has not been shown to
    # transfer, so the two origins must never be merged into one number.
    assert {c.origin for c in fixtures.real} == {"real"}
    assert {c.origin for c in fixtures.generated} == {"generated"}
    assert all(c.rationale for c in fixtures.generated)
    assert all(c.label_reviewed for c in fixtures.generated)


def test_the_holdout_is_a_whole_supplier_not_a_random_row_sample(fixtures):
    holdout = fixtures.split("holdout", origin="real")
    assert len(holdout) == 10
    assert {c.supplier for c in holdout} == {"corvid"}
    assert fixtures.suppliers["corvid"].split == "holdout"


def test_no_taught_correction_comes_from_the_holdout_supplier(fixtures):
    payloads = [
        json.loads(line)
        for line in (FIXTURE_ROOT / "teaching.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert payloads, "there must be at least one taught correction"
    holdout_ids = {c.case_id for c in fixtures.split("holdout", origin="real")}
    for payload in payloads:
        assert payload["case_id"] not in holdout_ids


def test_every_real_case_resolves_to_a_source_row(fixtures):
    for case in fixtures.real:
        assert case.case_id in fixtures.rows_by_case
        assert case.row is None, "real cases read their row from the supplier feed"


# Measured outcomes ---------------------------------------------------------


def test_the_original_procedure_is_wrong_on_the_pack_priced_rows(runs):
    metrics = runs["original"].metrics
    assert metrics.total == 38
    assert metrics.correct == 14
    assert metrics.critical == 24
    assert metrics.abstention_rate == 0.0


def test_verbatim_recall_only_fixes_the_row_it_was_taught(runs):
    assert runs["recall"].metrics.correct == 15
    assert runs["recall"].metrics.correct == runs["original"].metrics.correct + 1


def test_the_corrected_candidate_is_correct_on_every_case(runs):
    metrics = runs["corrected"].metrics
    assert metrics.correct == 38
    assert metrics.row_accuracy == 1.0
    assert metrics.critical == 0
    assert metrics.faulted == 0
    assert metrics.field_accuracy == 1.0


def test_the_corrected_candidate_pays_for_that_by_declining_seven_rows(runs):
    # Being right on every case includes being right to decline. Coverage is
    # reported next to accuracy so the cost is visible rather than hidden.
    metrics = runs["corrected"].metrics
    assert metrics.covered == 31
    assert metrics.total - metrics.covered == 7
    assert metrics.coverage == pytest.approx(31 / 38)


def test_the_over_generalized_candidate_introduces_critical_errors(runs):
    metrics = runs["overeager"].metrics
    assert metrics.correct == 23
    assert metrics.critical == 15
    # Eight rows get a per item price divided by a dimension, and seven rows
    # whose pack size is unknowable get a fabricated price anyway.
    assert metrics.critical_wrong_factor == 8
    assert metrics.critical_fabricated == 7


# The gate ------------------------------------------------------------------


def test_the_corrected_candidate_clears_the_release_gate(runs):
    decision = evaluate_gate(
        original=runs["original"],
        recall=runs["recall"],
        candidate=runs["corrected"],
        original_holdout=runs["original_holdout"],
        candidate_holdout=runs["corrected_holdout"],
    )
    assert decision.passed
    assert decision.verdict == "PUBLISHABLE"
    assert decision.new_critical_cases == ()
    assert decision.unreviewed_regressions == ()


def test_the_holdout_improvement_is_measured_not_asserted(runs):
    decision = evaluate_gate(
        original=runs["original"],
        recall=runs["recall"],
        candidate=runs["corrected"],
        original_holdout=runs["original_holdout"],
        candidate_holdout=runs["corrected_holdout"],
    )
    comparison = decision.holdout_comparison
    assert comparison.sample_size == 10
    assert comparison.candidate_fixed == 6
    assert comparison.candidate_broke == 0
    # Exact two sided sign test on six discordant pairs, all in one direction.
    assert comparison.p_value == pytest.approx(0.03125)


def test_the_over_generalized_candidate_is_blocked(runs):
    decision = evaluate_gate(
        original=runs["original"],
        recall=runs["recall"],
        candidate=runs["overeager"],
        original_holdout=runs["original_holdout"],
        candidate_holdout=runs["overeager_holdout"],
    )
    assert not decision.passed
    assert decision.verdict == "BLOCKED"
    failed = {c.code for c in decision.criteria if not c.passed}
    assert "no_new_critical_errors" in failed
    assert "regressions_reviewed" in failed
    assert len(decision.new_critical_cases) == 8


def test_the_over_generalized_candidate_still_looks_good_on_the_holdout_alone(runs):
    # It fixes five held out cases and breaks one, which is a positive net
    # change. Only the critical error criterion stops it, which is the point of
    # having more than one criterion.
    decision = evaluate_gate(
        original=runs["original"],
        recall=runs["recall"],
        candidate=runs["overeager"],
        original_holdout=runs["original_holdout"],
        candidate_holdout=runs["overeager_holdout"],
    )
    assert decision.holdout_comparison.net_change > 0
    passed = {c.code for c in decision.criteria if c.passed}
    assert "improves_on_holdout" in passed


def test_acknowledging_the_regressions_still_does_not_unblock_it(runs):
    # A reviewer cannot wave through a critical unit error by ticking a box.
    all_regressions = frozenset(
        o.case_id for o in runs["overeager"].outcomes if not o.verdict.is_correct
    )
    decision = evaluate_gate(
        original=runs["original"],
        recall=runs["recall"],
        candidate=runs["overeager"],
        original_holdout=runs["original_holdout"],
        candidate_holdout=runs["overeager_holdout"],
        reviewed_regressions=all_regressions,
    )
    assert not decision.passed
    failed = {c.code for c in decision.criteria if not c.passed}
    assert failed == {"no_new_critical_errors"}


# The command line ----------------------------------------------------------


def test_the_cli_evaluate_command_runs_offline_and_succeeds():
    result = subprocess.run(
        [sys.executable, "-m", "skillfoundry_cli.main", "evaluate"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "Release gate: PUBLISHABLE" in result.stdout
    assert "Release gate: BLOCKED" in result.stdout


def test_the_cli_explains_a_single_case():
    result = subprocess.run(
        [sys.executable, "-m", "skillfoundry_cli.main", "explain", "corrected", "acme:AC-100"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "unit_price  = 10.0000" in result.stdout
    assert "price, pack_size" in result.stdout
