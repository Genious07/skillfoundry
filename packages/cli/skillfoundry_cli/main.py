"""SkillFoundry command line interface.

Everything here runs offline against the bundled synthetic fixtures. No API key
and no network access is required.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillfoundry_domain import library
from skillfoundry_domain.interpreter import TerminalState, run
from skillfoundry_evaluation.baselines import LiteralRecall, ProcedureRunner, load_corrections
from skillfoundry_evaluation.report import (
    evaluate_gate,
    render_decision,
    render_failures,
    render_metrics_table,
)
from skillfoundry_evaluation.runner import evaluate, load_fixtures

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "demo"


def _fixture_root(args) -> Path:
    return Path(args.fixtures).resolve() if args.fixtures else FIXTURE_ROOT


def cmd_procedures(args) -> int:
    print(f"{'name':<12}{'rev':>4}  {'digest':<18}{'valid':<8}operators")
    print("-" * 92)
    for name in sorted(library.REGISTRY):
        proc = library.load(name)
        report = proc.validate_structure(library.TABLES)
        status = "yes" if report.ok else "NO"
        print(
            f"{name:<12}{proc.revision:>4}  {proc.digest:<18}{status:<8}"
            f"{', '.join(sorted(proc.operators_used()))}"
        )
        if not report.ok:
            print(f"{'':<24}{report.describe()}")
    return 0


def cmd_show(args) -> int:
    proc = library.load(args.name)
    report = proc.validate_structure(library.TABLES)
    print(f"{proc.name}")
    print(f"  procedure   {proc.procedure_id} revision {proc.revision} digest {proc.digest}")
    print(f"  origin      {proc.origin}")
    print(f"  capability  {', '.join(proc.capabilities)}")
    print(f"  validation  {report.describe()}")
    print(f"  reads       {', '.join(sorted(proc.input_fields))}")
    print(f"  writes      {', '.join(sorted(proc.output_fields))}")
    print()
    print("  " + proc.description)
    if args.json:
        print()
        print(json.dumps(json.loads(proc.canonical_json()), indent=2))
    return 0


def cmd_run(args) -> int:
    root = _fixture_root(args)
    fixtures = load_fixtures(root)
    proc = library.load(args.name)
    report = proc.validate_structure(library.TABLES)
    if not report.ok:
        print(f"procedure is invalid: {report.describe()}")
        return 2

    supplier = fixtures.suppliers[args.supplier]
    print(f"{proc.name}  digest {proc.digest}")
    print(f"supplier {supplier.supplier_id}  locale {supplier.locale.value}  currency {supplier.currency}")
    print()
    header = (
        f"{'sku':<10}{'description':<24}{'listed':>12}{' unit':<10}"
        f"{'pack':<9}{'unit price':>13}  outcome"
    )
    print(header)
    print("-" * len(header))

    for key, values in sorted(fixtures.rows_by_case.items()):
        if not key.startswith(f"{supplier.supplier_id}:"):
            continue
        execution = run(proc, values, tables=library.TABLES, context=supplier.context, row_id=key)
        state = execution.terminal_state
        if state is TerminalState.NEEDS_REVIEW:
            outcome = f"review: {execution.reviews[0].code}"
            price = "-"
        elif state is TerminalState.INVALID:
            outcome = f"fault: {execution.fault}"
            price = "-"
        else:
            price = str(execution.output.get("unit_price"))
            outcome = str(execution.output.get("price_basis"))
            if execution.rounding_applied:
                outcome += " (rounded)"
        print(
            f"{values['supplier_sku']:<10}{values['description'][:23]:<24}"
            f"{values['price']:>12}{' /' + (values['price_unit'] or '?'):<10}"
            f"{values['pack_size'] or '-':<9}{price:>13}  {outcome}"
        )
    return 0


def cmd_explain(args) -> int:
    root = _fixture_root(args)
    fixtures = load_fixtures(root)
    proc = library.load(args.name)
    values = fixtures.rows_by_case.get(args.case)
    if values is None:
        print(f"unknown case {args.case!r}")
        return 2
    supplier = fixtures.suppliers[args.case.split(":")[0]]
    execution = run(proc, values, tables=library.TABLES, context=supplier.context, row_id=args.case)

    print(f"case {args.case} under {proc.name} (digest {proc.digest})")
    print(f"  source     {json.dumps(values)}")
    print(f"  state      {execution.terminal_state.value}")
    for field_name, value in execution.output.items():
        evidence = execution.evidence.get(field_name)
        print(f"  {field_name:<12}= {value}")
        if evidence:
            print(f"{'':<15}from {', '.join(evidence.source_fields) or 'a literal'}")
            print(f"{'':<15}rule {evidence.rule_path}")
    for review in execution.reviews:
        print(f"  review     {review.code}")
        print(f"{'':<15}{review.reason}")
        print(f"{'':<15}rule {review.rule_path}")
    if execution.fault:
        print(f"  fault      {execution.fault}")
    if execution.rounding_applied:
        print("  note       the division was inexact and the unit price was rounded")
    return 0


def _build_runners(fixtures):
    original = ProcedureRunner(
        procedure=library.load("naive"),
        tables=library.TABLES,
        name="baseline_original",
        label="Baseline 1, original procedure",
    )
    corrections = load_corrections(fixtures.root / "teaching.jsonl", fixtures.rows_by_case)
    recall = LiteralRecall(fallback=original, corrections=corrections)
    return original, recall, corrections


def cmd_evaluate(args) -> int:
    root = _fixture_root(args)
    fixtures = load_fixtures(root)
    original, recall, corrections = _build_runners(fixtures)

    candidates = {
        "corrected": ProcedureRunner(
            procedure=library.load("corrected"),
            tables=library.TABLES,
            name="candidate_corrected",
            label="Candidate, explicit pack rule",
        ),
        "overeager": ProcedureRunner(
            procedure=library.load("overeager"),
            tables=library.TABLES,
            name="candidate_overeager",
            label="Candidate, over generalized",
        ),
    }

    suite = fixtures.all_cases
    holdout = fixtures.split("holdout", origin="real")

    print(f"fixtures      {root}")
    print(f"case suite    {len(fixtures.real)} real, {len(fixtures.generated)} generated")
    print(f"held out      {len(holdout)} real cases from suppliers "
          f"{sorted({c.supplier for c in holdout})}, never shown to the proposer")
    print(f"taught        {len(corrections)} correction(s) from teaching.jsonl")
    print()

    runs = [evaluate(original, suite, fixtures), evaluate(recall, suite, fixtures)]
    for candidate in candidates.values():
        runs.append(evaluate(candidate, suite, fixtures))

    print("Full suite, real and generated cases together")
    print(render_metrics_table(runs))
    print()

    original_holdout = evaluate(original, holdout, fixtures)
    exit_code = 0

    for key, candidate in candidates.items():
        candidate_run = evaluate(candidate, suite, fixtures)
        candidate_holdout = evaluate(candidate, holdout, fixtures)
        reviewed = frozenset(args.reviewed or ()) if key == args.accept_regressions_for else frozenset()
        decision = evaluate_gate(
            original=runs[0],
            recall=runs[1],
            candidate=candidate_run,
            original_holdout=original_holdout,
            candidate_holdout=candidate_holdout,
            reviewed_regressions=reviewed,
        )
        print("=" * 78)
        print(f"{candidate.label}  (procedure digest {candidate.procedure.digest})")
        print("=" * 78)
        print(render_decision(decision))
        print()
        print(render_failures(candidate_run))
        print()
        if not decision.passed and key == "corrected":
            exit_code = 1

    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="skillfoundry",
        description="Teach a catalog correction, then test whether it generalizes.",
    )
    parser.add_argument("--fixtures", help="path to a fixture root (defaults to fixtures/demo)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("procedures", help="list library procedures and validate them")
    p.set_defaults(func=cmd_procedures)

    p = sub.add_parser("show", help="describe one procedure")
    p.add_argument("name")
    p.add_argument("--json", action="store_true", help="also print the canonical AST")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("run", help="run a procedure over one supplier feed")
    p.add_argument("name")
    p.add_argument("--supplier", default="acme")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("explain", help="show the evidence behind one case")
    p.add_argument("name")
    p.add_argument("case", help="for example acme:AC-100")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("evaluate", help="compare candidates against both baselines and the gate")
    p.add_argument("--reviewed", nargs="*", help="case ids whose regression has been reviewed")
    p.add_argument(
        "--accept-regressions-for",
        default=None,
        help="which candidate the reviewed list applies to",
    )
    p.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
