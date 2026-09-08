"""Running an evaluable over a case set and collecting graded outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from skillfoundry_domain.catalog import Supplier, load_all_rows, load_suppliers

from .cases import Case, load_case_sets
from .metrics import CaseOutcome, Metrics, grade, summarize


@dataclass(frozen=True)
class Fixtures:
    root: Path
    suppliers: dict[str, Supplier]
    rows_by_case: dict[str, dict[str, str]]
    real: list[Case]
    generated: list[Case]

    @property
    def all_cases(self) -> list[Case]:
        return [*self.real, *self.generated]

    def split(self, name: str, origin: str | None = None) -> list[Case]:
        pool = self.all_cases if origin is None else [c for c in self.all_cases if c.origin == origin]
        return [c for c in pool if c.split == name]


def load_fixtures(root: Path) -> Fixtures:
    suppliers = load_suppliers(root)
    source_rows = load_all_rows(root, suppliers)
    case_sets = load_case_sets(root)

    rows_by_case: dict[str, dict[str, str]] = {
        key: dict(row.values) for key, row in source_rows.items()
    }
    for case in case_sets["generated"]:
        if case.row is None:
            raise ValueError(f"generated case {case.case_id!r} must carry its own row")
        rows_by_case[case.case_id] = dict(case.row)

    for case in case_sets["real"]:
        if case.case_id not in rows_by_case:
            raise ValueError(f"real case {case.case_id!r} has no matching source row")

    return Fixtures(
        root=root,
        suppliers=suppliers,
        rows_by_case=rows_by_case,
        real=case_sets["real"],
        generated=case_sets["generated"],
    )


@dataclass(frozen=True)
class RunResult:
    name: str
    label: str
    outcomes: tuple[CaseOutcome, ...]
    metrics: Metrics


def evaluate(evaluable, cases: Sequence[Case], fixtures: Fixtures) -> RunResult:
    outcomes: list[CaseOutcome] = []
    for case in cases:
        values = fixtures.rows_by_case[case.case_id]
        supplier = fixtures.suppliers[case.supplier]
        execution = evaluable.execute(values, supplier.context, case.case_id)
        outcomes.append(grade(case, execution))
    return RunResult(
        name=evaluable.name,
        label=evaluable.label,
        outcomes=tuple(outcomes),
        metrics=summarize(outcomes),
    )
